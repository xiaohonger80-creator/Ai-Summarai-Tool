from dataclasses import dataclass, asdict
from typing import Dict, Any, List


@dataclass
class SubtitleSegment:
    """
    Unified Subtitle Data Schema:
    Enforced across all ASR, OCR, Hybrid extractors, and LLM translators.
    """
    id: int
    start: float      # Start time in seconds (e.g. 1.25)
    end: float        # End time in seconds (e.g. 3.80)
    text: str         # Original Chinese text
    translated: str = ""  # Translated subtitle text (Khmer, English, etc.)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SubtitleSegment":
        return cls(
            id=int(d.get("id", 0)),
            start=round(float(d.get("start", 0.0)), 2),
            end=round(float(d.get("end", 0.0)), 2),
            text=str(d.get("text", "")).strip(),
            translated=str(d.get("translated", "")).strip(),
        )

    @property
    def duration(self) -> float:
        return max(0.1, round(self.end - self.start, 2))

    @property
    def start_timecode(self) -> str:
        s = self.start
        hrs = int(s // 3600)
        mins = int((s % 3600) // 60)
        secs = int(s % 60)
        millis = int(round((s - int(s)) * 1000))
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    @property
    def end_timecode(self) -> str:
        s = self.end
        hrs = int(s // 3600)
        mins = int((s % 3600) // 60)
        secs = int(s % 60)
        millis = int(round((s - int(s)) * 1000))
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"
