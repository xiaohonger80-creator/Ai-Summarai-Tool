# -*- coding: utf-8 -*-
"""
core/schema.py
Unified Segment Data Schema shared across Extraction, Translation, Recap, Dubbing & VideoFX.
Extended with `voice_fx` ("normal" | "inner_thought" | "phone_call" | "radio") and `audio_hash`.
"""

from dataclasses import dataclass
from typing import Dict, Any, List

VALID_VOICE_FX = ("normal", "inner_thought", "phone_call", "radio")


@dataclass
class SubtitleSegment:
    """
    Unified Subtitle & Dubbing Segment Schema:
    [{"id": 1, "start": 0.50, "end": 2.80, "speaker": "SPEAKER_01", "text": "Original text",
      "translated": "", "dub_audio": "", "voice_fx": "normal", "audio_hash": ""}]
    """
    id: int
    start: float                 # Start time in seconds (e.g. 0.50)
    end: float                   # End time in seconds (e.g. 2.80)
    text: str                    # Original transcript/OCR text
    translated: str = ""         # Translated or Recap narration script
    speaker: str = "SPEAKER_01"  # Speaker / Voice role identifier
    dub_audio: str = ""          # Generated TTS WAV/MP3 path for this segment
    voice_fx: str = "normal"     # "normal" | "inner_thought" | "phone_call" | "radio"
    audio_hash: str = ""         # SHA-256 cache hash of (translated|voice|voice_fx|rate)

    def to_dict(self) -> Dict[str, Any]:
        fx = str(self.voice_fx or "normal").lower().strip().replace(" ", "_")
        if fx not in VALID_VOICE_FX:
            fx = "normal"
        return {
            "id": int(self.id),
            "start": round(float(self.start), 2),
            "end": round(float(self.end), 2),
            "speaker": str(self.speaker or "SPEAKER_01"),
            "text": str(self.text or ""),
            "translated": str(self.translated or ""),
            "dub_audio": str(self.dub_audio or ""),
            "voice_fx": fx,
            "audio_hash": str(self.audio_hash or ""),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], default_id: int = 1) -> "SubtitleSegment":
        start_val = d.get("start")
        if start_val is None and "start_ms" in d:
            start_val = float(d["start_ms"]) / 1000.0
        end_val = d.get("end")
        if end_val is None and "end_ms" in d:
            end_val = float(d["end_ms"]) / 1000.0

        fx = str(d.get("voice_fx") or "normal").lower().strip().replace(" ", "_")
        if fx not in VALID_VOICE_FX:
            fx = "normal"

        return cls(
            id=int(d.get("id") or default_id),
            start=round(float(start_val or 0.0), 2),
            end=round(float(end_val or 0.0), 2),
            text=str(d.get("text") or d.get("zh_text") or "").strip(),
            translated=str(d.get("translated") or d.get("kh_text") or "").strip(),
            speaker=str(d.get("speaker") or d.get("voice_override") or "SPEAKER_01").strip(),
            dub_audio=str(d.get("dub_audio") or d.get("tts_audio_path") or "").strip(),
            voice_fx=fx,
            audio_hash=str(d.get("audio_hash") or "").strip(),
        )

    @property
    def duration(self) -> float:
        return max(0.1, round(self.end - self.start, 2))

    @property
    def start_timecode(self) -> str:
        return self._sec_to_srt_tc(self.start)

    @property
    def end_timecode(self) -> str:
        return self._sec_to_srt_tc(self.end)

    @staticmethod
    def _sec_to_srt_tc(sec: float) -> str:
        s = max(0.0, float(sec))
        hrs = int(s // 3600)
        mins = int((s % 3600) // 60)
        secs = int(s % 60)
        millis = int(round((s - int(s)) * 1000))
        if millis >= 1000:
            millis = 999
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def normalize_segments(raw_list: List[Any]) -> List[Dict[str, Any]]:
    """Normalizes a list of dicts or SubtitleSegment objects into standard schema dicts."""
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_list or [], start=1):
        if isinstance(item, SubtitleSegment):
            seg = item
        elif isinstance(item, dict):
            seg = SubtitleSegment.from_dict(item, default_id=idx)
        else:
            continue
        normalized.append(seg.to_dict())
    return normalized
