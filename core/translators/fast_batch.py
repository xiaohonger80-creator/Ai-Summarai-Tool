import json
import time
from typing import List, Dict, Any, Callable, Optional

from core.translators.base import BaseTranslator
from core.translators.providers import UnifiedLLMClient


class FastBatchTranslator(BaseTranslator):
    """
    Fast Batch Translation Strategy:
    Sends 8-10 lines at a time with strict JSON ID mapping for high throughput.
    """

    def __init__(self, client: UnifiedLLMClient, batch_size: int = 8):
        self.client = client
        self.batch_size = batch_size

    def translate(
        self,
        segments: List[Dict[str, Any]],
        target_lang: str = "Khmer",
        progress_cb: Optional[Callable[[int, str], None]] = None,
        cancel_event=None,
    ) -> List[Dict[str, Any]]:
        if not segments:
            return []

        total = len(segments)
        results = [dict(s) for s in segments]
        total_batches = (total + self.batch_size - 1) // self.batch_size

        system_prompt = (
            f"You are a professional movie and subtitle translator. "
            f"Translate the following Chinese dialogue lines into natural, fluent, spoken {target_lang}. "
            f"Output MUST be strict JSON in the format: "
            f'{{"translations": [{{"id": 1, "translated": "..."}}]}}. '
            f"Preserve all original line IDs exactly."
        )

        for b_idx in range(0, total, self.batch_size):
            if cancel_event and cancel_event.is_set():
                break

            batch_chunk = results[b_idx : b_idx + self.batch_size]
            payload_lines = [{"id": s["id"], "text": s["text"]} for s in batch_chunk]

            current_batch_no = (b_idx // self.batch_size) + 1
            if progress_cb:
                pct = int((b_idx / total) * 100)
                progress_cb(pct, f"Translating batch {current_batch_no}/{total_batches} ({target_lang})...")

            prompt = json.dumps({"lines": payload_lines}, ensure_ascii=False)
            data = self.client.generate_json(prompt, system_prompt=system_prompt)

            # Map results back by ID
            mapped = {}
            if isinstance(data, dict):
                items = data.get("translations", [])
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict) and "id" in it and "translated" in it:
                            mapped[int(it["id"])] = str(it["translated"]).strip()

            for s in batch_chunk:
                sid = int(s["id"])
                if sid in mapped and mapped[sid]:
                    s["translated"] = mapped[sid]
                else:
                    # Fallback single translation to avoid blank lines
                    fallback_text = self.client.fallback_translate_single(s["text"], target_lang=target_lang)
                    s["translated"] = fallback_text or s["text"]

            time.sleep(0.05)

        if progress_cb:
            progress_cb(100, f"Finished translating {len(results)} lines into {target_lang}.")

        return results
