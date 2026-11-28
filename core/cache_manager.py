# -*- coding: utf-8 -*-
"""
core/cache_manager.py
SHA-256 Hash-Based Smart TTS Audio Cache:
Computes sha256(f"{translated_text}|{speaker_voice}|{voice_fx}|{speech_rate}").
During TTS dubbing, checks cache/tts/{hash}.wav first; reuses existing .wav immediately
if matched, and only invokes TTS synthesis for newly edited or uncached segments.
"""

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any


class SmartTTSCache:
    """
    Deterministic SHA-256 Audio Cache Manager preventing redundant TTS generation
    when re-exporting or tweaking a few lines in a project.
    """

    def __init__(self, cache_dir: str = "data/cache/tts"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    @staticmethod
    def compute_hash(
        translated_text: str,
        speaker_voice: str,
        voice_fx: str = "normal",
        speech_rate: str = "+0%",
    ) -> str:
        norm_text = (translated_text or "").strip()
        norm_voice = (speaker_voice or "km-KH-SreymomNeural").strip()
        norm_fx = (voice_fx or "normal").strip().lower()
        norm_rate = str(speech_rate or "+0%").strip()
        payload = f"{norm_text}|{norm_voice}|{norm_fx}|{norm_rate}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_cache_path(self, audio_hash: str) -> Path:
        return self.cache_dir / f"{audio_hash}.wav"

    def get_cached_audio(
        self,
        translated_text: str,
        speaker_voice: str,
        voice_fx: str = "normal",
        speech_rate: str = "+0%",
    ) -> Optional[str]:
        """
        Returns the cached WAV file path if it exists and is non-empty; otherwise None.
        """
        h = self.compute_hash(translated_text, speaker_voice, voice_fx, speech_rate)
        p = self.get_cache_path(h)
        if p.exists() and p.stat().st_size > 256:
            self.hits += 1
            return str(p.resolve())
        self.misses += 1
        return None

    def store_audio(
        self,
        source_wav_path: str,
        translated_text: str,
        speaker_voice: str,
        voice_fx: str = "normal",
        speech_rate: str = "+0%",
    ) -> tuple[str, str]:
        """
        Copies synthesized WAV into the content-addressable cache and returns (audio_hash, cached_path).
        """
        h = self.compute_hash(translated_text, speaker_voice, voice_fx, speech_rate)
        dest = self.get_cache_path(h)
        if os.path.exists(source_wav_path):
            if Path(source_wav_path).resolve() != dest.resolve():
                shutil.copy2(source_wav_path, dest)
        return h, str(dest.resolve())

    def stats(self) -> Dict[str, Any]:
        files = list(self.cache_dir.glob("*.wav"))
        total_bytes = sum(f.stat().st_size for f in files if f.exists())
        return {
            "hits": self.hits,
            "misses": self.misses,
            "cached_files": len(files),
            "size_mb": round(total_bytes / (1024 * 1024), 2),
        }
