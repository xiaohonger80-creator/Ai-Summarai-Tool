# -*- coding: utf-8 -*-
"""
core/recap_dubbing/recap_writer.py
LLM Story Recap Script Generator turning raw movie transcripts into engaging,
timestamped 3rd-person movie narration scripts (Khmer / Multi-language).
"""

import gc
import json
import re
from typing import List, Dict, Any, Optional, Callable

from core.schema import normalize_segments
from core.translators.providers import UnifiedLLMClient


class RecapWriter:
    """
    Converts raw subtitle segments into cohesive Movie Story Recap narration segments
    aligned to key scene timestamps.
    """

    def __init__(self, client: UnifiedLLMClient, target_minutes: float = 3.0):
        self.client = client
        self.target_minutes = max(0.5, float(target_minutes))

    def generate_recap_segments(
        self,
        segments: List[Dict[str, Any]],
        target_lang: str = "Khmer (ភាសាខ្មែរ)",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Groups dialogue into narrative story beats and uses the selected LLM
        (Local Ollama or Cloud API) to write natural 3rd-person movie recap narration.
        """
        norm_segs = normalize_segments(segments)
        if not norm_segs:
            return []

        # Group segments into narrative blocks (~5 segments per story beat)
        group_size = 5
        recap_groups: List[Dict[str, Any]] = []
        for idx in range(0, len(norm_segs), group_size):
            chunk = norm_segs[idx : idx + group_size]
            combined_src = " ".join(s.get("text", "") for s in chunk if s.get("text", "").strip())
            if not combined_src:
                continue
            recap_groups.append({
                "id": len(recap_groups) + 1,
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "speaker": "NARRATOR",
                "text": combined_src,
                "translated": "",
                "dub_audio": "",
            })

        system_prompt = (
            f"You are a veteran Movie Recap Narrator writing an engaging, dramatic 3rd-person story recap in {target_lang}.\n"
            "Rules:\n"
            "1. Turn each scene's raw dialogue into smooth, hook-driven 3rd-person storytelling narration.\n"
            "2. Keep each narration concise so it fits naturally within the timestamp window.\n"
            "3. Return ONLY a JSON array of objects: [{\"id\": 1, \"translated\": \"...\"}]."
        )

        batch_size = 6
        total_batches = max(1, (len(recap_groups) + batch_size - 1) // batch_size)

        for b_idx in range(total_batches):
            if is_cancelled and is_cancelled():
                break

            start_i = b_idx * batch_size
            batch = recap_groups[start_i : start_i + batch_size]

            if progress_callback:
                pct = int(((b_idx + 1) / total_batches) * 100)
                progress_callback(pct, f"Writing Story Recap beat {b_idx + 1}/{total_batches}...")

            payload = [
                {"id": item["id"], "duration_sec": round(item["end"] - item["start"], 1), "dialogue": item["text"]}
                for item in batch
            ]
            user_prompt = (
                f"Write 3rd-person movie recap narration in {target_lang} for these {len(batch)} scene beats:\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
            )

            try:
                raw_resp = self.client.generate(system_prompt=system_prompt, user_prompt=user_prompt, json_mode=True)
                parsed = self._parse_json_response(raw_resp)
                for item in batch:
                    sid = item["id"]
                    if sid in parsed and parsed[sid]:
                        item["translated"] = parsed[sid]
                    elif not item.get("translated"):
                        item["translated"] = item["text"]
            except Exception:
                for item in batch:
                    if not item.get("translated"):
                        item["translated"] = item["text"]

        return recap_groups

    @staticmethod
    def _parse_json_response(raw_text: str) -> Dict[int, str]:
        result: Dict[int, str] = {}
        if not raw_text:
            return result
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
        try:
            data = json.loads(cleaned)
            items = data.get("translations") or data.get("items") or data.get("recap") if isinstance(data, dict) else data
            if isinstance(items, list):
                for entry in items:
                    if isinstance(entry, dict) and "id" in entry:
                        val = entry.get("translated") or entry.get("narration") or entry.get("text") or ""
                        result[int(entry["id"])] = str(val).strip()
        except Exception:
            pass
        return result

    def unload(self) -> None:
        gc.collect()
