# -*- coding: utf-8 -*-
"""
core/legacy_bridge.py
Bidirectional Legacy & Cross-Module Compatibility Bridge:
  - Normalizes legacy SQLite segment dicts (`start_ms`, `end_ms`, `zh_text`, `kh_text`, `tts_audio_path`, `voice_override`),
    old `.vfxproj` files, and new AI Studio segments into the unified segment schema:
    `{"id": int, "start": float, "end": float, "speaker": str, "text": str, "translated": str,
      "dub_audio": str, "voice_fx": str, "emotion": str, "audio_hash": str}`
  - Converts unified segments back into SQLite database format without data loss.
  - Enforces Sequential GPU VRAM Unloading (`safe_unload(engine)`) between pipeline stages.
"""

import gc
import re
from typing import Dict, Any, List, Optional

from core.schema import SubtitleSegment, normalize_segments


class LegacyCompatibilityAdapter:
    """
    Bridges legacy MainWindow / SQLite structures with the modular EngineRegistry & StudioPipelineWorker.
    """

    LEGACY_ENGINE_ALIASES: Dict[str, str] = {
        "voice": "Audio ASR + Speaker ID (WhisperX)",
        "ocr": "Hard-Subtitle OCR (PaddleOCR)",
        "hybrid": "Hybrid (OCR Primary + ASR Check)",
        "funasr": "Audio ASR (FunASR SenseVoice)",
        "whisper.cpp": "whisper.cpp (Ultra-Fast CPU / Low-VRAM Fallback)",
        "demucs": "Demucs (htdemucs - True Vocal & BGM/SFX Stem Separation)",
        "uvr5": "UVR5 Instrumental Keep",
        "ffmpeg_vocal": "FFmpeg Vocal Suppression",
        "duck": "Duck Original Audio -18dB",
        "edge": "Edge-TTS (Fast Online/Fallback)",
        "gpt-sovits": "GPT-SoVITS (Local Voice Clone)",
        "fish-speech": "Fish-Speech (Local Natural TTS)",
        "khmer-xtts": "Khmer-XTTS / F5-TTS Khmer (Local Khmer Voice Cloning)",
        "mms-khmer": "Meta MMS-TTS Khmer (facebook/mms-tts-khm)",
    }

    @classmethod
    def resolve_engine_key(cls, raw_key: str, default_key: str) -> str:
        if not raw_key:
            return default_key
        clean = str(raw_key).strip()
        low = clean.lower()
        if low in cls.LEGACY_ENGINE_ALIASES:
            return cls.LEGACY_ENGINE_ALIASES[low]
        return clean

    @classmethod
    def to_unified_segments(cls, raw_list: List[Any]) -> List[Dict[str, Any]]:
        """
        Normalizes any list of legacy SQLite dicts or SubtitleSegment objects into unified schema dicts.
        """
        return normalize_segments(raw_list)

    @classmethod
    def to_sqlite_segments(cls, unified_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Converts unified schema dicts back to MainWindow's SQLite segment table schema
        (`id`, `start_ms`, `end_ms`, `zh_text`, `kh_text`, `voice_override`, `tts_audio_path`, `status`).
        """
        sqlite_rows: List[Dict[str, Any]] = []
        for idx, item in enumerate(unified_list or [], start=1):
            seg = SubtitleSegment.from_dict(item, default_id=idx)
            start_ms = int(round(seg.start * 1000))
            end_ms = max(start_ms + 300, int(round(seg.end * 1000)))
            status = "Voiced" if seg.dub_audio else ("Ready" if seg.translated else "Pending")
            sqlite_rows.append({
                "id": seg.id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "zh_text": seg.text,
                "kh_text": seg.translated,
                "voice_override": seg.speaker,
                "tts_audio_path": seg.dub_audio,
                "voice_fx": seg.voice_fx,
                "emotion": seg.emotion,
                "status": status,
            })
        return sqlite_rows

    @staticmethod
    def apply_emotion_tag_to_text(text: str, emotion: str = "normal") -> str:
        """
        Inserts or updates an emotion cue prefix `[whisper]`, `[laughing]`, `[angry]`, `[sad]`
        on a segment's text, or strips it when `normal` is chosen.
        """
        clean = re.sub(r"^\s*\[(normal|whisper|laughing|angry|sad)\]\s*", "", str(text or ""), flags=re.IGNORECASE).strip()
        em = str(emotion or "normal").lower().strip("[] ")
        if em and em != "normal":
            return f"[{em}] {clean}"
        return clean

    @staticmethod
    def safe_unload(engine_obj: Optional[Any]) -> None:
        """
        Mandatory Sequential GPU VRAM Unloading guard called after every pipeline stage.
        """
        if engine_obj is not None:
            try:
                if hasattr(engine_obj, "unload") and callable(engine_obj.unload):
                    engine_obj.unload()
            except Exception:
                pass
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
