from pathlib import Path
from typing import List, Dict, Any

from core.schema import SubtitleSegment


class SRTExporter:
    """
    Exports subtitle segments into industry-standard UTF-8 .srt files.
    Always enforces encoding='utf-8' so Khmer & Chinese Unicode never corrupt.
    """

    @staticmethod
    def _format_timecode(sec: float) -> str:
        s = max(0.0, float(sec))
        hrs = int(s // 3600)
        mins = int((s % 3600) // 60)
        secs = int(s % 60)
        millis = int(round((s - int(s)) * 1000))
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    @classmethod
    def export_translated_only(cls, segments: List[Dict[str, Any]], out_path: str) -> str:
        """Exports .srt containing ONLY translated text."""
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        for idx, s in enumerate(segments, start=1):
            start_tc = cls._format_timecode(s["start"])
            end_tc = cls._format_timecode(s["end"])
            text = (s.get("translated") or s.get("text") or "").strip()

            lines.append(str(idx))
            lines.append(f"{start_tc} --> {end_tc}")
            lines.append(text)
            lines.append("")

        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")

        return str(p)

    @classmethod
    def export_bilingual(cls, segments: List[Dict[str, Any]], out_path: str) -> str:
        """Exports .srt containing Original Chinese + Translated Subtitle."""
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        for idx, s in enumerate(segments, start=1):
            start_tc = cls._format_timecode(s["start"])
            end_tc = cls._format_timecode(s["end"])
            orig = (s.get("text") or "").strip()
            trans = (s.get("translated") or "").strip()

            lines.append(str(idx))
            lines.append(f"{start_tc} --> {end_tc}")
            if orig and trans and orig != trans:
                lines.append(f"{orig}\n{trans}")
            else:
                lines.append(trans or orig)
            lines.append("")

        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")

        return str(p)
