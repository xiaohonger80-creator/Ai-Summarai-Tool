# -*- coding: utf-8 -*-
"""
core/recap_dubbing/tts_dubber.py
Selectable AI Voice Dubbing Engine with:
  1. Smart SHA-256 TTS Audio Caching (`core/cache_manager.py`)
  2. Multi-Speaker Role Mapping & Dramatic Voice FX (`core/recap_dubbing/voice_fx.py`)
  3. GPT-SoVITS Local API, Fish-Speech Local API, and Edge-TTS + Somleng Khmer Normalization
  4. Dynamic FFmpeg `atempo` Speech-Rate Synchronization
"""

import gc
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import requests

from core.tts_engine import KhmerTTSEngine
from core.somleng_engine import SomlengKhmerNormalizer
from core.cache_manager import SmartTTSCache
from core.recap_dubbing.voice_fx import VoiceFXProcessor

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class TTSDubber:
    """
    Multi-engine Voice Dubber with Smart SHA-256 Cache, Speaker Role Mapping,
    Voice FX filters, automatic `atempo` synchronization, and mandatory VRAM `unload()`.
    """

    ENGINE_OPTIONS = [
        "GPT-SoVITS (Local Voice Clone)",
        "Fish-Speech (Local Natural TTS)",
        "Edge-TTS (Fast Online/Fallback)",
    ]

    def __init__(
        self,
        engine_name: str = "Edge-TTS (Fast Online/Fallback)",
        voice_id: str = "km-KH-SreymomNeural",
        auto_rate_sync: bool = True,
        gpt_sovits_url: str = "http://127.0.0.1:9880",
        fish_speech_url: str = "http://127.0.0.1:8080",
        cache_dir: str = "data/cache/tts",
        speaker_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self.engine_name = engine_name
        self.voice_id = voice_id or "km-KH-SreymomNeural"
        self.auto_rate_sync = bool(auto_rate_sync)
        self.gpt_sovits_url = gpt_sovits_url.rstrip("/")
        self.fish_speech_url = fish_speech_url.rstrip("/")
        self.edge_engine = KhmerTTSEngine()
        self.cache = SmartTTSCache(cache_dir=cache_dir)
        self.speaker_map = speaker_map or {}

    def synthesize_segments(
        self,
        segments: List[Dict[str, Any]],
        out_dir: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Synthesizes voice audio for each segment using SmartTTSCache and applies Voice FX.
        Stores path in segment['dub_audio'] and SHA-256 hash in segment['audio_hash'].
        """
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        total = max(1, len(segments))

        for idx, seg in enumerate(segments):
            if is_cancelled and is_cancelled():
                break

            sid = seg.get("id", idx + 1)
            raw_text = (seg.get("translated") or seg.get("text") or "").strip()
            if not raw_text:
                continue

            norm_text = SomlengKhmerNormalizer.normalize_text(raw_text)
            speaker_id = seg.get("speaker", "SPEAKER_01")
            spk_cfg = VoiceFXProcessor.resolve_speaker_config(
                speaker_id=speaker_id,
                speaker_map=self.speaker_map,
                default_voice=self.voice_id,
            )
            assigned_voice = spk_cfg["voice"]
            speech_rate = spk_cfg["rate"]
            voice_fx = seg.get("voice_fx", "normal") or "normal"

            wav_file = str(out_path / f"dub_seg_{sid:04d}.wav")

            # 1. Check Smart SHA-256 TTS Audio Cache first
            cached_wav = self.cache.get_cached_audio(
                translated_text=norm_text,
                speaker_voice=assigned_voice,
                voice_fx=voice_fx,
                speech_rate=speech_rate,
            )
            if cached_wav and os.path.exists(cached_wav):
                if Path(cached_wav).resolve() != Path(wav_file).resolve():
                    shutil.copy2(cached_wav, wav_file)
                seg["dub_audio"] = wav_file
                seg["audio_hash"] = self.cache.compute_hash(norm_text, assigned_voice, voice_fx, speech_rate)
                if progress_callback:
                    pct = int(((idx + 1) / total) * 100)
                    progress_callback(pct, f"⚡ Smart Cache Hit [{idx + 1}/{total}]: {norm_text[:24]}...")
                continue

            # 2. Cache Miss -> Synthesize new audio
            start_s = float(seg.get("start", 0.0))
            end_s = float(seg.get("end", start_s + 2.0))
            target_ms = max(400, int(round((end_s - start_s) * 1000)))

            if progress_callback:
                pct = int(((idx + 1) / total) * 100)
                progress_callback(pct, f"🎙️ Synthesizing [{idx + 1}/{total}] ({assigned_voice}): {norm_text[:24]}...")

            synthesized = False
            if "GPT-SoVITS" in self.engine_name:
                synthesized = self._try_gpt_sovits(norm_text, wav_file, target_ms)
            elif "Fish-Speech" in self.engine_name:
                synthesized = self._try_fish_speech(norm_text, wav_file, target_ms)

            if not synthesized:
                self.edge_engine.generate_clip(
                    norm_text,
                    assigned_voice,
                    target_ms,
                    wav_file,
                    speed_mult=1.0 if self.auto_rate_sync else 0.95,
                )

            if os.path.exists(wav_file):
                # 3. Apply dramatic Voice FX (inner_thought, phone_call, radio, normal)
                if voice_fx and voice_fx != "normal":
                    VoiceFXProcessor.apply_voice_fx(wav_file, wav_file, voice_fx=voice_fx)

                # 4. Store in Smart SHA-256 Cache
                audio_hash, _ = self.cache.store_audio(
                    source_wav_path=wav_file,
                    translated_text=norm_text,
                    speaker_voice=assigned_voice,
                    voice_fx=voice_fx,
                    speech_rate=speech_rate,
                )
                seg["dub_audio"] = wav_file
                seg["audio_hash"] = audio_hash

        return segments

    def _try_gpt_sovits(self, text: str, out_wav: str, target_ms: int) -> bool:
        try:
            resp = requests.get(
                f"{self.gpt_sovits_url}/",
                params={"text": text, "text_language": "zh"},
                timeout=8,
            )
            if resp.status_code == 200 and len(resp.content) > 512:
                raw_tmp = out_wav + ".raw.wav"
                with open(raw_tmp, "wb") as f:
                    f.write(resp.content)
                self._time_stretch_to_duration(raw_tmp, out_wav, target_ms)
                Path(raw_tmp).unlink(missing_ok=True)
                return os.path.exists(out_wav)
        except Exception:
            pass
        return False

    def _try_fish_speech(self, text: str, out_wav: str, target_ms: int) -> bool:
        try:
            resp = requests.post(
                f"{self.fish_speech_url}/v1/tts",
                json={"text": text, "format": "wav"},
                timeout=8,
            )
            if resp.status_code == 200 and len(resp.content) > 512:
                raw_tmp = out_wav + ".raw.wav"
                with open(raw_tmp, "wb") as f:
                    f.write(resp.content)
                self._time_stretch_to_duration(raw_tmp, out_wav, target_ms)
                Path(raw_tmp).unlink(missing_ok=True)
                return os.path.exists(out_wav)
        except Exception:
            pass
        return False

    def _time_stretch_to_duration(self, in_wav: str, out_wav: str, target_ms: int) -> None:
        if not self.auto_rate_sync or target_ms <= 0:
            os.replace(in_wav, out_wav)
            return
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", in_wav],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW, timeout=5
            )
            cur_sec = float((probe.stdout or "0").strip() or 0.0)
            target_sec = target_ms / 1000.0
            if cur_sec > 0.1 and cur_sec > target_sec * 1.05:
                ratio = max(0.85, min(1.85, cur_sec / target_sec))
                subprocess.run(
                    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", in_wav, "-af", f"atempo={ratio:.3f}", out_wav],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, timeout=15
                )
                if os.path.exists(out_wav):
                    return
        except Exception:
            pass
        os.replace(in_wav, out_wav)

    def unload(self) -> None:
        """Mandatory VRAM / resource release after TTS stage."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        gc.collect()
