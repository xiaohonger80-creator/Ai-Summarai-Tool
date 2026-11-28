import json
import time
from typing import List, Dict, Any, Callable, Optional

from core.translators.base import BaseTranslator
from core.translators.providers import UnifiedLLMClient


class StoryContextTranslator(BaseTranslator):
    """
    Story-Context Translation Strategy (Inspired by VideoLingo):
    Step 1: Performs a global pre-pass over the full Chinese transcript to generate:
            - A 4-sentence plot summary
            - Character/pronoun/honorific glossary
    Step 2: Injects that glossary & context into every 8-line batch so tone, idioms,
            and character relationships remain consistent throughout the entire film/drama.
    """

    def __init__(self, client: UnifiedLLMClient, batch_size: int = 8):
        self.client = client
        self.batch_size = batch_size
        self.plot_summary: str = ""
        self.character_glossary: Dict[str, str] = {}

    def _extract_story_context(self, segments: List[Dict[str, Any]], target_lang: str) -> tuple[str, Dict[str, str]]:
        """Pre-pass over sample of transcript to deduce plot and character names."""
        sample_text = "\n".join([
            f"{s.get('id', idx + 1)}: {s.get('text', s.get('zh_text', ''))}"
            for idx, s in enumerate(segments[:120])
        ])

        prompt = (
            f"Analyze this Chinese movie/drama dialogue transcript:\n\n{sample_text}\n\n"
            f"Provide a JSON response with:\n"
            f'1. "plot_summary": 3-4 sentence overview of the setting, conflict, and relationships.\n'
            f'2. "glossary": A mapping of character names, royal titles, honorifics, and relationships to spoken {target_lang}.\n'
            f'Format: {{"plot_summary": "...", "glossary": {{"NameOrTerm": "TranslatedTerm"}}}}\n'
        )
        system_prompt = f"You are a master film dramaturg and multilingual dubbing director for {target_lang}."

        try:
            data = self.client.generate_json(prompt, system_prompt=system_prompt, timeout=25)
            if isinstance(data, dict):
                summary = str(data.get("plot_summary", "")).strip()
                glossary = data.get("glossary", {})
                if not isinstance(glossary, dict):
                    glossary = {}
                return summary, glossary
        except Exception as e:
            print(f"[Story Context Pre-pass Note] {e}")

        return "", {}

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

        # Step 1: Pre-pass context extraction
        if progress_cb:
            progress_cb(5, "Analyzing overall movie plot & character relationships (Pre-Pass)...")

        self.plot_summary, self.character_glossary = self._extract_story_context(segments, target_lang)

        # Enforce known mandatory glossary terms if Khmer
        if "khmer" in target_lang.lower() or "ភាសាខ្មែរ" in target_lang:
            default_mandatory = {
                "Chu Wei": "ឈូ វៃ",
                "Zhengfei": "ព្រះមហេសី",
                "Xianggong": "ស្វាមី",
                "Yu'er": "អ៊ីអឺ",
                "皇上": "ព្រះអង្គម្ចាស់",
                "王爷": "ព្រះអង្គម្ចាស់",
            }
            default_mandatory.update(self.character_glossary)
            self.character_glossary = default_mandatory

        glossary_str = "\n".join([f"- {k} -> {v}" for k, v in self.character_glossary.items()])

        system_prompt = (
            f"You are a veteran film subtitle director and dubbing translator for {target_lang}.\n"
            f"STORY CONTEXT:\n{self.plot_summary}\n\n"
            f"MANDATORY CHARACTER & HONORIFIC GLOSSARY:\n{glossary_str}\n\n"
            f"RULES:\n"
            f"1. Interpret speaker emotion and relationships rather than translating word-by-word literally.\n"
            f"2. Use natural, conversational spoken {target_lang} phrasing.\n"
            f"3. Strict JSON output: {{\"translations\": [{{\"id\": 1, \"translated\": \"...\"}}]}}.\n"
            f"4. Keep line IDs strictly synchronized."
        )

        # Step 2: Contextual batch translation
        for b_idx in range(0, total, self.batch_size):
            if cancel_event and cancel_event.is_set():
                break

            batch_chunk = results[b_idx : b_idx + self.batch_size]
            payload_lines = [
                {"id": s.get("id", idx + 1), "text": s.get("text", s.get("zh_text", ""))}
                for idx, s in enumerate(batch_chunk)
            ]

            current_batch_no = (b_idx // self.batch_size) + 1
            if progress_cb:
                pct = 15 + int((b_idx / total) * 82)
                progress_cb(pct, f"Contextual Translation batch {current_batch_no}/{total_batches} ({target_lang})...")

            prompt = json.dumps({"lines": payload_lines}, ensure_ascii=False)
            data = self.client.generate_json(prompt, system_prompt=system_prompt)

            mapped = {}
            if isinstance(data, dict):
                items = data.get("translations", [])
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict) and "id" in it and "translated" in it:
                            try:
                                mapped[int(it["id"])] = str(it["translated"]).strip()
                            except (ValueError, TypeError):
                                pass

            for idx, s in enumerate(batch_chunk):
                sid = int(s.get("id", idx + 1))
                if sid in mapped and mapped[sid]:
                    s["translated"] = mapped[sid]
                else:
                    fallback_text = self.client.fallback_translate_single(s.get("text", s.get("zh_text", "")), target_lang=target_lang)
                    s["translated"] = fallback_text or s.get("text", s.get("zh_text", ""))

            time.sleep(0.05)

        if progress_cb:
            progress_cb(100, f"Story-Context Translation complete ({len(results)} lines).")

        return results
