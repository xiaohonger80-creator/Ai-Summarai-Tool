import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from core.extractors.base import BaseExtractor
from core.schema import SubtitleSegment

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class WhisperExtractor(BaseExtractor):
    """
    Chinese ASR extraction via faster-whisper (large-v3 / medium / base).
    Enforces unified schema and CPU/GPU memory safety.
    """

    def __init__(self, model_size: str = "large-v3", device: str = "auto", compute_type: str = "auto"):
        super().__init__()
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def _ensure_model(self):
        if self.model is None:
            from faster_whisper import WhisperModel
            import torch

            dev = "cuda" if (self.device == "cuda" or (self.device == "auto" and torch.cuda.is_available())) else "cpu"
            ctype = "float16" if dev == "cuda" else "int8"
            cpu_threads = 2 if dev == "cpu" else 4

            self.model = WhisperModel(
                self.model_size,
                device=dev,
                compute_type=ctype,
                cpu_threads=cpu_threads,
            )

    def extract(
        self,
        video_path: str,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        cancel_event=None,
    ) -> List[Dict[str, Any]]:
        if not video_path or not Path(video_path).exists():
            return []

        if progress_cb:
            progress_cb(10, "Extracting 16kHz mono audio track via FFmpeg...")

        wav_path = str(Path(video_path).with_suffix(".temp_whisper.wav"))
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            wav_path
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:
            if progress_cb:
                progress_cb(0, f"FFmpeg Audio Extraction Error: {e}")
            return []

        if cancel_event and cancel_event.is_set():
            Path(wav_path).unlink(missing_ok=True)
            return []

        if progress_cb:
            progress_cb(25, f"Loading Faster-Whisper ({self.model_size})...")

        try:
            self._ensure_model()
            if progress_cb:
                progress_cb(40, "Transcribing Chinese speech (VAD enabled)...")

            segments, info = self.model.transcribe(
                wav_path,
                language="zh",
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.30,
                    min_speech_duration_ms=80,
                    min_silence_duration_ms=200,
                    speech_pad_ms=150,
                ),
                beam_size=1,
            )

            results: List[Dict[str, Any]] = []
            seg_id = 1
            for s in segments:
                if cancel_event and cancel_event.is_set():
                    break
                txt = s.text.strip()
                if txt:
                    results.append(SubtitleSegment(
                        id=seg_id,
                        start=round(float(s.start), 2),
                        end=round(float(s.end), 2),
                        text=txt,
                        translated="",
                    ).to_dict())
                    seg_id += 1

            if progress_cb:
                progress_cb(90, f"Extracted {len(results)} dialogue segments.")
            return results

        finally:
            Path(wav_path).unlink(missing_ok=True)
            self.unload()
