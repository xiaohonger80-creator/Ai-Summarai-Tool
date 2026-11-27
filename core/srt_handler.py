import re
from pathlib import Path
from typing import List, Dict

TIME_PATTERN = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


class SRTHandler:
    @staticmethod
    def _to_ms(h: str, m: str, s: str, ms: str) -> int:
        return ((int(h) * 3600 + int(m) * 60 + int(s)) * 1000) + int(ms)

    @staticmethod
    def _format_ts(total_ms: int) -> str:
        total_ms = max(0, int(total_ms))
        hours, rem = divmod(total_ms, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds, ms = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"

    @classmethod
    def parse_srt(cls, srt_path: str) -> List[Dict]:
        """Parses a UTF-8 (or UTF-8-SIG) SRT file into segment dicts."""
        raw = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
        blocks = re.split(r"\r?\n\r?\n+", raw.strip())
        segments = []

        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 2:
                continue

            # Handle optional sequence number on line 0
            time_line_idx = 1 if TIME_PATTERN.search(lines[1]) else 0
            match = TIME_PATTERN.search(lines[time_line_idx])
            if not match:
                continue

            start_ms = cls._to_ms(*match.groups()[:4])
            end_ms = cls._to_ms(*match.groups()[4:])
            text = " ".join(lines[time_line_idx + 1 :]).strip()

            if text:
                segments.append({
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": text,
                })

        return segments

    @classmethod
    def export_srt(cls, segments: List[Dict], out_path: str, mode: str = "kh"):
        """
        Exports segments to a UTF-8 SRT file.
        mode: 'kh' (Khmer only), 'zh' (Chinese only), or 'both' (ZH + KH stacked)
        """
        out_lines = []
        idx = 1
        for seg in segments:
            zh = (seg.get("zh_text") or "").strip()
            kh = (seg.get("kh_text") or "").strip()

            if mode == "kh":
                body = kh
            elif mode == "zh":
                body = zh
            else:
                body = f"{zh}\n{kh}".strip()

            if not body:
                continue

            start_str = cls._format_ts(seg["start_ms"])
            end_str = cls._format_ts(seg["end_ms"])
            out_lines.append(f"{idx}\n{start_str} --> {end_str}\n{body}\n")
            idx += 1

        Path(out_path).write_text("\n".join(out_lines), encoding="utf-8")
        return idx - 1
