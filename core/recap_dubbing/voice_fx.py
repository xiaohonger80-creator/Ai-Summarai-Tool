# -*- coding: utf-8 -*-
"""
core/recap_dubbing/voice_fx.py
Multi-Speaker Role Mapping & Special FFmpeg Voice FX Processor:
  - normal: Clean normalized speech (`loudnorm`)
  - inner_thought: Dreamy internal monologue reverb (`aecho=0.8:0.88:60:0.4,highpass=f=120`)
  - phone_call: Realistic telecom bandpass (`highpass=f=300,lowpass=f=3400,acompressor=threshold=-18dB:ratio=4`)
  - radio: Walkie-talkie / broadcast effect (`highpass=f=500,lowpass=f=2800,acrusher=bits=8:mode=log:aa=1`)
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class VoiceFXProcessor:
    """
    Manages speaker-to-voice role mapping and applies FFmpeg dramatic Voice FX filters
    to dubbed TTS segments.
    """

    VOICE_FX_FILTERS: Dict[str, str] = {
        "normal": "loudnorm=I=-16:TP=-1.5:LRA=11",
        "inner_thought": "aecho=0.8:0.88:60:0.4,highpass=f=120",
        "phone_call": "highpass=f=300,lowpass=f=3400,acompressor=threshold=-18dB:ratio=4",
        "radio": "highpass=f=500,lowpass=f=2800,acrusher=bits=8:mode=log:aa=1",
    }

    DEFAULT_SPEAKER_MAP: Dict[str, Dict[str, str]] = {
        "SPEAKER_00": {"voice": "km-KH-PisethNeural", "rate": "+0%", "pitch": "+0Hz"},
        "SPEAKER_01": {"voice": "km-KH-SreymomNeural", "rate": "+0%", "pitch": "+0Hz"},
        "SPEAKER_02": {"voice": "km-KH-PisethNeural", "rate": "-5%", "pitch": "-4Hz"},
        "NARRATOR": {"voice": "km-KH-PisethNeural", "rate": "+5%", "pitch": "-2Hz"},
    }

    @classmethod
    def resolve_speaker_config(
        cls,
        speaker_id: str,
        speaker_map: Optional[Dict[str, Dict[str, Any]]] = None,
        default_voice: str = "km-KH-SreymomNeural",
    ) -> Dict[str, str]:
        smap = dict(cls.DEFAULT_SPEAKER_MAP)
        if speaker_map:
            smap.update(speaker_map)
        spk = (speaker_id or "SPEAKER_01").strip()
        if spk in smap and isinstance(smap[spk], dict):
            cfg = smap[spk]
            return {
                "voice": str(cfg.get("voice") or default_voice),
                "rate": str(cfg.get("rate") or "+0%"),
                "pitch": str(cfg.get("pitch") or "+0Hz"),
            }
        return {"voice": default_voice, "rate": "+0%", "pitch": "+0Hz"}

    @classmethod
    def get_filter_expr(cls, voice_fx: str) -> str:
        key = str(voice_fx or "normal").lower().strip().replace(" ", "_")
        return cls.VOICE_FX_FILTERS.get(key, cls.VOICE_FX_FILTERS["normal"])

    @classmethod
    def apply_voice_fx(cls, input_wav: str, output_wav: str, voice_fx: str = "normal") -> bool:
        """
        Applies the selected FFmpeg audio effect filter to `input_wav` and writes `output_wav`.
        """
        if not os.path.exists(input_wav):
            return False

        key = str(voice_fx or "normal").lower().strip().replace(" ", "_")
        if key == "normal" and Path(input_wav).resolve() == Path(output_wav).resolve():
            return True

        af_expr = cls.get_filter_expr(key)
        tmp_out = output_wav + ".fx_tmp.wav"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_wav),
            "-af", af_expr,
            "-ar", "44100", "-ac", "1",
            "-c:a", "pcm_s16le",
            str(tmp_out),
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
                timeout=20,
            )
            if res.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 256:
                os.replace(tmp_out, output_wav)
                return True
        except Exception:
            pass
        finally:
            Path(tmp_out).unlink(missing_ok=True)
        return False
