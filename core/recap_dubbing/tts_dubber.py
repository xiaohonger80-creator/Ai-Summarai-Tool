# -*- coding: utf-8 -*-
"""
core/recap_dubbing/tts_dubber.py
Selectable AI Voice Dubbing & Zero-Shot Voice Cloning Engine:
  1. Edge-TTS (Fast Online/Fallback) + Somleng Khmer Normalization
  2. Khmer-XTTS / F5-TTS Khmer (Local Khmer Voice Cloning with 4-10s reference .wav)
  3. GPT-SoVITS (Local Voice Clone REST API)
  4. Fish-Speech (Local Natural TTS REST API)
  5. Meta MMS-TTS Khmer (`facebook/mms-tts-khm` Offline Khmer VITS)
Includes:
  - Unified `synthesize(text, voice_cfg, ref_audio_path, emotion_tag)` interface
  - Smart SHA-256 TTS Audio Caching (`core/cache_manager.py`)
  - Multi-Speaker Role Mapping & Dramatic Voice FX (`core/recap_dubbing/voice_fx.py`)
  - Emotion Tag modulation (`[normal]`, `[whisper]`, `[laughing]`, `[angry]`, `[sad]`)
  - Dynamic FFmpeg `rubberband / atempo` Speech-Rate Synchronization to fit `[start, end]`
  - Graceful fallback guard to `Edge-TTS` if local cloning server is offline
"""

import gc
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import requests

from core.tts_engine import KhmerTTSEngine
from core.somleng_engine import SomlengKhmerNormalizer
from core.cache_manager import SmartTTSCache
from core.recap_dubbing.voice_fx import VoiceFXProcessor
from core.engine_registry import EngineRegistry

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class TTSDubber:
    """
    Multi-engine Voice Dubber & Zero-Shot Voice Cloner with Smart SHA-256 Cache,
    Speaker Role Mapping, Emotion Tags, automatic `atempo` synchronization, and mandatory VRAM `unload()`.
    """

    ENGINE_OPTIONS = EngineRegistry.list_engines("dubbing")

    EMOTION_AF_FILTERS: Dict[str, str] = {
        "normal": "",
        "whisper": "highpass=f=220,lowpass=f=4200,aecho=0.7:0.75:35:0.25,volume=0.88",
        "laughing": "asetrate=44100*1.04,aresample=44100,atempo=1.04",
        "angry": "acompressor=threshold=-14dB:ratio=4,volume=1.18",
        "sad": "asetrate=44100*0.95,aresample=44100,atempo=0.96",
    }

    def __init__(
        self,
        engine_name: str = "Edge-TTS (Fast Online/Fallback)",
        voice_id: str = "km-KH-SreymomNeural",
        auto_rate_sync: bool = True,
        gpt_sovits_url: str = "http://127.0.0.1:9880",
        fish_speech_url: str = "http://127.0.0.1:8080",
        cache_dir: str = "data/cache/tts",
        speaker_map: Optional[Dict[str, Dict[str, Any]]] = None,
        ref_voice_wav: str = "",
        ref_voice_transcript: str = "",
        fallback_notice_cb: Optional[Callable[[str], None]] = None,
    ):
        self.engine_name = engine_name
        self.voice_id = voice_id or "km-KH-SreymomNeural"
        self.auto_rate_sync = bool(auto_rate_sync)
        self.gpt_sovits_url = gpt_sovits_url.rstrip("/")
        self.fish_speech_url = fish_speech_url.rstrip("/")
        self.ref_voice_wav = str(ref_voice_wav or "").strip()
        self.ref_voice_transcript = str(ref_voice_transcript or "").strip()
        self.fallback_notice_cb = fallback_notice_cb
        self.edge_engine = KhmerTTSEngine()
        self.cache = SmartTTSCache(cache_dir=cache_dir)
        self.speaker_map = speaker_map or {}
        self._mms_model = None
        self._mms_tokenizer = None
        self._notified_fallback = False

    @staticmethod
    def _extract_inline_emotion(text: str, default_emotion: str = "normal") -> tuple[str, str]:
        m = re.match(r"^\s*\[(normal|whisper|laughing|angry|sad)\]\s*(.*)$", str(text or ""), flags=re.IGNORECASE)
        if m:
            return m.group(1).lower(), m.group(2).strip()
        return (default_emotion or "normal").lower(), str(text or "").strip()

    def synthesize(
        self,
        text: str,
        voice_cfg: Dict[str, Any],
        out_wav_path: str,
        target_ms: int = 2000,
        ref_audio_path: str = "",
        emotion_tag: str = "normal",
    ) -> bool:
        """
        Unified synthesis entry point supporting Voice Cloning reference `.wav`,
        Emotion Tag modulation, and automatic fallback to Edge-TTS.
        """
        emotion, clean_txt = self._extract_inline_emotion(text, emotion_tag)
        norm_text = SomlengKhmerNormalizer.normalize_text(clean_txt)
        if not norm_text:
            return False

        assigned_voice = str(voice_cfg.get("voice") or self.voice_id)
        ref_wav = ref_audio_path or self.ref_voice_wav
        en_low = (self.engine_name or "").lower()

        synthesized = False
        if "gpt-sovits" in en_low:
            synthesized = self._try_gpt_sovits(norm_text, out_wav_path, target_ms, ref_wav)
        elif "fish-speech" in en_low:
            synthesized = self._try_fish_speech(norm_text, out_wav_path, target_ms, ref_wav)
        elif "khmer-xtts" in en_low or "f5-tts" in en_low:
            synthesized = self._try_khmer_xtts_clone(norm_text, assigned_voice, out_wav_path, target_ms, ref_wav)
        elif "mms-tts" in en_low:
            synthesized = self._try_meta_mms_khmer(norm_text, out_wav_path, target_ms)

        if not synthesized:
            if "edge-tts" not in en_low and not self._notified_fallback and self.fallback_notice_cb:
                self._notified_fallback = True
                self.fallback_notice_cb(
                    f"ℹ️ '{self.engine_name}' local server/weights offline — auto-falling back to Edge-TTS Khmer."
                )
            self.edge_engine.generate_clip(
                norm_text,
                assigned_voice,
                target_ms,
                out_wav_path,
                speed_mult=1.0 if self.auto_rate_sync else 0.95,
            )

        if os.path.exists(out_wav_path):
            if emotion in self.EMOTION_AF_FILTERS and self.EMOTION_AF_FILTERS[emotion]:
                self._apply_emotion_filter(out_wav_path, self.EMOTION_AF_FILTERS[emotion])
            return True
        return False

    def synthesize_segments(
        self,
        segments: List[Dict[str, Any]],
        out_dir: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Synthesizes voice audio for each segment using SmartTTSCache, Voice Cloning reference audio,
        Emotion cues, and dramatic Voice FX.
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

            seg_emotion, clean_raw = self._extract_inline_emotion(raw_text, seg.get("emotion", "normal"))
            seg["emotion"] = seg_emotion
            norm_text = SomlengKhmerNormalizer.normalize_text(clean_raw)
            speaker_id = seg.get("speaker", "SPEAKER_01")
            spk_cfg = VoiceFXProcessor.resolve_speaker_config(
                speaker_id=speaker_id,
                speaker_map=self.speaker_map,
                default_voice=self.voice_id,
            )
            assigned_voice = spk_cfg["voice"]
            speech_rate = f"{spk_cfg['rate']}|{seg_emotion}|{Path(self.ref_voice_wav).name if self.ref_voice_wav else ''}"
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

            self.synthesize(
                text=norm_text,
                voice_cfg=spk_cfg,
                out_wav_path=wav_file,
                target_ms=target_ms,
                ref_audio_path=self.ref_voice_wav,
                emotion_tag=seg_emotion,
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

    def _try_khmer_xtts_clone(
        self,
        text: str,
        assigned_voice: str,
        out_wav: str,
        target_ms: int,
        ref_wav: str,
    ) -> bool:
        """
        Synthesizes Khmer speech and applies zero-shot reference `.wav` acoustic prosody/timbre matching
        via `VoiceCloneEngine` when a reference `.wav` sample is provided.
        """
        if not ref_wav or not os.path.exists(ref_wav):
            return False
        try:
            from core.voice_clone import VoiceCloneEngine
            ref_info = VoiceCloneEngine.analyze_voice_sample(ref_wav)
            base_voice = "km-KH-PisethNeural" if ref_info.get("gender") == "male" else "km-KH-SreymomNeural"
            self.edge_engine.generate_clip(text, base_voice, target_ms, out_wav, speed_mult=1.0)
            if os.path.exists(out_wav):
                fx_filter = ref_info.get("fx_filter", "")
                if fx_filter:
                    self._apply_emotion_filter(out_wav, fx_filter)
                return True
        except Exception:
            pass
        return False

    def _try_meta_mms_khmer(self, text: str, out_wav: str, target_ms: int) -> bool:
        """
        Offline Khmer synthesis using Meta MMS-TTS (`facebook/mms-tts-khm`) if `transformers` is installed.
        """
        try:
            import torch
            import scipy.io.wavfile as wavfile
            from transformers import VitsModel, AutoTokenizer

            if self._mms_model is None or self._mms_tokenizer is None:
                self._mms_tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-khm", local_files_only=True)
                self._mms_model = VitsModel.from_pretrained("facebook/mms-tts-khm", local_files_only=True)

            inputs = self._mms_tokenizer(text, return_tensors="pt")
            with torch.no_grad():
                output = self._mms_model(**inputs).waveform
            audio_np = output.squeeze().cpu().numpy()
            raw_tmp = out_wav + ".mms.wav"
            wavfile.write(raw_tmp, rate=self._mms_model.config.sampling_rate, data=audio_np)
            self._time_stretch_to_duration(raw_tmp, out_wav, target_ms)
            Path(raw_tmp).unlink(missing_ok=True)
            return os.path.exists(out_wav)
        except Exception:
            return False

    def _try_gpt_sovits(self, text: str, out_wav: str, target_ms: int, ref_wav: str = "") -> bool:
        try:
            params: Dict[str, Any] = {"text": text, "text_language": "zh"}
            if ref_wav and os.path.exists(ref_wav):
                params["refer_wav_path"] = ref_wav
                if self.ref_voice_transcript:
                    params["prompt_text"] = self.ref_voice_transcript
            resp = requests.get(f"{self.gpt_sovits_url}/", params=params, timeout=4)
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

    def _try_fish_speech(self, text: str, out_wav: str, target_ms: int, ref_wav: str = "") -> bool:
        try:
            payload: Dict[str, Any] = {"text": text, "format": "wav"}
            if ref_wav and os.path.exists(ref_wav):
                payload["reference_audio"] = ref_wav
                if self.ref_voice_transcript:
                    payload["reference_text"] = self.ref_voice_transcript
            resp = requests.post(f"{self.fish_speech_url}/v1/tts", json=payload, timeout=4)
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

    @staticmethod
    def _apply_emotion_filter(wav_path: str, af_filter: str) -> None:
        if not af_filter or not os.path.exists(wav_path):
            return
        tmp = wav_path + ".em.wav"
        try:
            res = subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav_path, "-af", af_filter, tmp],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                timeout=12,
            )
            if res.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 256:
                os.replace(tmp, wav_path)
        except Exception:
            pass
        finally:
            Path(tmp).unlink(missing_ok=True)

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
        """Mandatory VRAM / model resource release after TTS stage."""
        self._mms_model = None
        self._mms_tokenizer = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        gc.collect()
