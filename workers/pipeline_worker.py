# -*- coding: utf-8 -*-
"""
workers/pipeline_worker.py
Sequential 4-Stage GPU VRAM-Safe Background Pipeline Orchestrator:
  - Processes single video or sequential Batch Queue items
  - Stage 1: Extract (ASR/OCR) -> extractor.unload()
  - Stage 2: LLM Translate or Story Recap Script -> release HTTP session
  - Stage 3: Vocal Separation / TTS Dubbing (with SHA-256 SmartTTSCache & Voice FX) -> dubber.unload()
  - Stage 4: Video Masking + 3D LUT + Animated .ASS + GPU NVENC/AMF/QSV Encoding -> masker.unload()
"""

import gc
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QThread, Signal

from core.schema import normalize_segments
from core.engine_factory import EngineFactory
from core.hardware_profiler import HardwareProfiler
from core.videofx.text_animator import TextAnimator

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class StudioPipelineWorker(QThread):
    """
    Non-blocking QThread orchestrating the 4-stage production pipeline
    across single videos or sequential Batch Queue episodes.
    """

    progress_updated = Signal(int, str)          # (percent 0-100, status message)
    stage_changed = Signal(str)                  # e.g. "[1/4] Extracting..."
    preview_ready = Signal(str, float)           # (jpg_path, timestamp_sec)
    segment_updated = Signal(list)               # list of normalized segment dicts
    batch_item_updated = Signal(int, str, str)   # (item_id, status, detail_or_output)
    finished = Signal(str, list)                 # (final_output_path, final_segments)
    failed = Signal(str)                         # error description

    def __init__(
        self,
        video_path: str,
        settings: Dict[str, Any],
        existing_segments: Optional[List[Dict[str, Any]]] = None,
        output_dir: Optional[str] = None,
        batch_queue: Optional[List[Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = str(video_path or "")
        self.settings = HardwareProfiler.apply_performance_profile(
            (settings or {}).get("hardware_profile", "high"),
            settings or {},
        )
        self.segments = normalize_segments(existing_segments or [])
        self.output_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="aisummarai_pipeline_"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.batch_queue = list(batch_queue or [])
        self._is_cancelled = False
        self._active_proc: Optional[subprocess.Popen] = None

    def cancel(self) -> None:
        self._is_cancelled = True
        if self._active_proc is not None:
            try:
                self._active_proc.terminate()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    @staticmethod
    def _clear_vram() -> None:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def run(self) -> None:
        try:
            if self.batch_queue:
                last_out = ""
                for item in self.batch_queue:
                    if self._is_cancelled:
                        break
                    item_id = getattr(item, "id", 0) or (item.get("id", 0) if isinstance(item, dict) else 0)
                    vpath = getattr(item, "video_path", "") or (item.get("video_path", "") if isinstance(item, dict) else "")
                    if not vpath or not os.path.exists(vpath):
                        self.batch_item_updated.emit(item_id, "Failed", "Video file missing")
                        continue
                    self.batch_item_updated.emit(item_id, "Processing", "")
                    try:
                        out_mp4, segs = self._process_single_video(vpath, initial_segments=[])
                        if not self._is_cancelled:
                            last_out = out_mp4
                            self.segments = segs
                            self.batch_item_updated.emit(item_id, "Completed", out_mp4)
                    except Exception as item_exc:
                        self.batch_item_updated.emit(item_id, "Failed", str(item_exc))
                if not self._is_cancelled and last_out:
                    self.finished.emit(last_out, self.segments)
                return

            if not self.video_path or not os.path.exists(self.video_path):
                self.failed.emit("សូមជ្រើសរើសឯកសារវីដេអូជាមុនសិន (Video file not found).")
                return

            final_mp4, final_segs = self._process_single_video(self.video_path, self.segments)
            if not self._is_cancelled:
                self.progress_updated.emit(100, "Pipeline Complete (100%)!")
                self.stage_changed.emit("Ready — Pipeline Completed Successfully")
                self.finished.emit(final_mp4, final_segs)

        except Exception as exc:
            self._clear_vram()
            if not self._is_cancelled:
                self.failed.emit(f"Pipeline Error: {exc}")

    def _process_single_video(
        self,
        video_path: str,
        initial_segments: List[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        segs = normalize_segments(initial_segments)

        # =================================================================
        # STAGE 1: EXTRACT (ASR / OCR / HYBRID) -> mandatory unload()
        # =================================================================
        self.stage_changed.emit("[1/4] Extracting Subtitles / Speech...")
        self.progress_updated.emit(5, "[1/4] Starting Extraction Engine...")

        if not segs:
            extractor = EngineFactory.create_extractor(
                engine_name=self.settings.get("extraction_engine", "Hybrid (OCR Primary + ASR Check)"),
                settings=self.settings,
            )
            try:
                raw_segs = extractor.extract(
                    media_path=video_path,
                    progress_callback=lambda p, m: self.progress_updated.emit(5 + int(p * 0.20), f"[1/4] {m}"),
                    is_cancelled=self.is_cancelled,
                )
                segs = normalize_segments(raw_segs)
            finally:
                extractor.unload()
                self._clear_vram()

        if self._is_cancelled:
            return "", segs

        self.segment_updated.emit(segs)

        # =================================================================
        # STAGE 2: TRANSLATE OR STORY RECAP -> release LLM session
        # =================================================================
        self.stage_changed.emit("[2/4] Clearing VRAM & Translating / Writing Recap...")
        self.progress_updated.emit(30, "[2/4] Running AI Translation / Recap Script...")

        dub_mode = self.settings.get("dub_mode", "AI Movie Dubbing (Replace Dialogue)")
        target_lang = self.settings.get("target_language", "Khmer (ភាសាខ្មែរ)")
        needs_translation = any(not (s.get("translated") or "").strip() for s in segs)

        if segs and needs_translation:
            if "Story Recap" in dub_mode:
                recap_writer = EngineFactory.create_recap_writer(self.settings)
                try:
                    segs = recap_writer.generate_recap_segments(
                        segments=segs,
                        target_lang=target_lang,
                        progress_callback=lambda p, m: self.progress_updated.emit(30 + int(p * 0.25), f"[2/4] {m}"),
                        is_cancelled=self.is_cancelled,
                    )
                finally:
                    recap_writer.unload()
                    self._clear_vram()
            else:
                translator = EngineFactory.create_translator(
                    strategy_name=self.settings.get("translation_strategy", "Story Context Mode"),
                    provider_name=self.settings.get("ai_provider", "100% Local Offline (Ollama)"),
                    model_name=self.settings.get("model_name", "qwen2.5:7b"),
                    settings=self.settings,
                )
                try:
                    trans_segs = translator.translate(
                        segments=segs,
                        target_lang=target_lang,
                        progress_callback=lambda p, m: self.progress_updated.emit(30 + int(p * 0.25), f"[2/4] {m}"),
                        is_cancelled=self.is_cancelled,
                    )
                    segs = normalize_segments(trans_segs)
                finally:
                    del translator
                    self._clear_vram()

        if self._is_cancelled:
            return "", segs

        self.segment_updated.emit(segs)

        # =================================================================
        # STAGE 3: VOCAL SEPARATION & SMART-CACHED TTS DUBBING -> unload()
        # =================================================================
        self.stage_changed.emit("[3/4] Clearing VRAM & Synthesizing Dubbing (Smart TTS Cache)...")
        self.progress_updated.emit(58, "[3/4] Preparing Audio & Smart TTS Cache...")

        bgm_wav_path: Optional[str] = None
        if "Disabled" not in dub_mode and segs:
            separator = EngineFactory.create_vocal_separator(
                self.settings,
                fallback_notice_cb=lambda msg: self.stage_changed.emit(msg),
            )
            try:
                bgm_target = str(self.output_dir / f"{Path(video_path).stem}_bgm.wav")
                bgm_wav_path = separator.extract_bgm(video_path, bgm_target)
            finally:
                separator.unload()
                self._clear_vram()

            if self._is_cancelled:
                return "", segs

            dubber = EngineFactory.create_tts_dubber(
                self.settings,
                fallback_notice_cb=lambda msg: self.stage_changed.emit(msg),
            )
            try:
                tts_dir = str(self.output_dir / "dub_clips")
                segs = dubber.synthesize_segments(
                    segments=segs,
                    out_dir=tts_dir,
                    progress_callback=lambda p, m: self.progress_updated.emit(60 + int(p * 0.20), f"[3/4] {m}"),
                    is_cancelled=self.is_cancelled,
                )
                cache_stats = dubber.cache.stats()
                self.progress_updated.emit(
                    80,
                    f"[3/4] TTS Complete (Cache Hits: {cache_stats['hits']}, Misses: {cache_stats['misses']})",
                )
            finally:
                dubber.unload()
                self._clear_vram()

            self.segment_updated.emit(segs)

        if self._is_cancelled:
            return "", segs

        # =================================================================
        # STAGE 4: VIDEO MASKING, LUTS, ASS SUBTITLES & GPU ENCODING
        # =================================================================
        enc_badge = HardwareProfiler.get_encoder_badge_text()
        self.stage_changed.emit(f"[4/4] Compositing VideoFX & Encoding ({enc_badge})...")
        self.progress_updated.emit(82, "[4/4] Generating UTF-8-SIG .ASS Subtitles & Filtergraph...")

        ass_path = str(self.output_dir / f"{Path(video_path).stem}_subtitles.ass")
        TextAnimator.generate_studio_ass(
            segments=segs,
            out_ass_path=ass_path,
            style_mode=self.settings.get("text_fx_style", "Static Styled Subtitles"),
            bottom_cover_box=bool(self.settings.get("bottom_cover_box", True)),
            font_name=self.settings.get("font_family", "Noto Sans Khmer"),
            font_size=int(self.settings.get("font_size", 46)),
            primary_color=self.settings.get("text_color", "#FFFFFF"),
            outline_color=self.settings.get("outline_color", "#000000"),
            speed_factor=float(self.settings.get("text_speed", 1.0)),
        )

        compositor = EngineFactory.create_compositor()
        preview_jpg = str(self.output_dir / "live_stage4_preview.jpg")
        pv_w = int(self.settings.get("preview_w", 960))
        pv_h = int(self.settings.get("preview_h", 540))
        if compositor.render_preview_frame(
            video_path=video_path,
            timestamp_sec=1.0,
            out_jpg_path=preview_jpg,
            settings=self.settings,
            ass_path=ass_path,
            target_w=pv_w,
            target_h=pv_h,
        ):
            self.preview_ready.emit(preview_jpg, 1.0)

        src_p = Path(video_path)
        final_mp4 = str(self.output_dir / f"{src_p.stem}_Studio_Output.mp4")
        cmd = compositor.compose_final_video(
            video_path=video_path,
            out_video_path=final_mp4,
            settings=self.settings,
            ass_path=ass_path,
            bgm_wav_path=bgm_wav_path,
            segments=segs,
        )

        self._run_ffmpeg_export(cmd)
        self._clear_vram()
        return final_mp4, segs

    def _run_ffmpeg_export(self, cmd: List[str]) -> None:
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        self._active_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        for line in self._active_proc.stderr:
            if self._is_cancelled:
                try:
                    self._active_proc.kill()
                except Exception:
                    pass
                return
            m = time_re.search(line)
            if m:
                cur_s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                self.progress_updated.emit(90, f"[4/4] Encoding video ({cur_s:.1f}s)...")
        self._active_proc.wait()
        if self._active_proc.stderr:
            try:
                self._active_proc.stderr.close()
            except Exception:
                pass
        self._active_proc = None
