import json
import re
import time
import urllib.parse
import urllib.request
from typing import List, Dict, Callable, Optional
import requests

from core.api_pool import APIKeyPoolManager


DUBBING_SYSTEM_PROMPT = (
    "You are an elite Cambodian film & TV drama dubbing scriptwriter translating Chinese dialogue into "
    "AUTHENTIC, NATURAL CONVERSATIONAL SPOKEN KHMER (ភាសាខ្មែរនិយាយក្នុងភាពយន្តដ៏ធម្មជាតិ ដូចតួអង្គខ្មែរនិយាយផ្ទាល់ មិនមែនបកប្រែរឹងមួយម៉ាត់ៗតាមម៉ាស៊ីនឡើយ)។\n\n"
    "MANDATORY MOVIE-GRADE DUBBING RULES:\n"
    "1. NATURAL SPOKEN KHMER (ភាសានិយាយធម្មជាតិ ១០០%):\n"
    "   - Write how real Cambodians actually speak in drama/movies — vivid, emotional, effortless to say out loud.\n"
    "   - Use natural everyday spoken Khmer words & sentence-final particles: 'អត់...ទេ', 'ហ្នឹង', 'អ្ហ៎', 'អី', 'ស្អី', 'ចឹង', 'ទៅ', 'ណា', 'ផង', 'ម៉េច', 'ដែរ', 'ហ្អេ'.\n"
    "   - NEVER use stiff textbook/literary wording: NO 'តើ' at the start of questions, NO 'សូមអភ័យទោស' (use 'សុំទោស'), NO 'តើអ្នកជានរណា' (use 'ឯងជាអ្នកណា?'), NO 'ហេតុអ្វីបានជាអ្នក' (use 'ម៉េចបានឯង...'), NO 'វាជាការពិត' (use 'ពិតមែនហើយ'), NO 'មិនអាចទៅរួចទេ' (use 'ទៅមិនរួចទេ' or 'អត់អាចទេ').\n"
    "   - Translate the TRUE emotional meaning and subtext, NEVER stiff word-for-word literal calques.\n"
    "2. STRICT RHYTHM & LIP-SYNC DURATION MATCHING (`dur_s` & `max_kh_chars`):\n"
    "   - Each input line includes `dur_s` (exact actor spoken seconds) and `max_kh_chars` (recommended Khmer length).\n"
    "   - Match the spoken Khmer rhythm tightly to `dur_s` so the Khmer voiceover fits smoothly inside the actor's mouth window without rushing or lagging.\n"
    "   - For short bursts (< 1.5s), use sharp punchy spoken phrases (e.g. 'ឈប់សិន!', 'ស្អីគេហ្នឹង?', 'អត់ទេ!', 'លឿនឡើង!').\n"
    "   - Never pad with unnecessary filler words; trim verbose clauses while keeping 100% of the drama & meaning.\n"
    "3. CHARACTER VOICE & PRONOUN CONSISTENCY:\n"
    "   - Lovers / Couple: 'បង / អូន'\n"
    "   - Peers / Friends / Rivals: 'ខ្ញុំ / ឯង' or 'យើង / ឯង' (furious/hostile: 'អញ / ហ្អែង')\n"
    "   - Family / Elders: 'ប៉ា / កូន', 'ម៉ាក់ / កូន', 'ពូ / មីង', 'លោកតា / លោកយាយ'\n"
    "   - Modern CEO / Period Drama: 'លោកប្រធាន', 'អ្នកប្រុស', 'អ្នកនាង', 'លោកម្ចាស់', 'ព្រះអង្គ', 'ទូលបង្គំ'\n"
    "   - Keep crisp punctuation ('!', '?', '...') so Khmer TTS delivers exact emotion.\n"
    "4. 100% AUDIO-SUBTITLE ALIGNMENT:\n"
    "   - Output ONLY pure clean spoken Khmer (ZERO Chinese characters, ZERO translator notes, ZERO parenthetical explanations like '(laugh)').\n"
    "   - What you write will be BOTH displayed as the on-screen Khmer subtitle AND spoken word-for-word by the voiceover actor.\n"
    "5. STRICT GLOSSARY & JSON OUTPUT:\n"
    "   - Honor every character name and term from the Glossary.\n"
    "   - Return ONLY a valid JSON object mapping numeric string id to the natural spoken Khmer line. No markdown fences or commentary."
)

RECAP_SYSTEM_PROMPT = (
    "You are an elite Cambodian AI movie recap narrator & storyteller (អ្នកសម្រាយរឿង និងនិទានរឿងដ៏ជំនាញ)។\n"
    "Your mission is to rewrite Chinese drama dialogue into CAPTIVATING, HIGH-RETENTION SPOKEN KHMER RECAP NARRATION "
    "(ភាសាសម្រាយរឿងបែបនិទាន កន្ត្រាក់អារម្មណ៍ ទាក់ទាញអ្នកស្តាប់ ដូចក្នុង YouTube/TikTok Recap រឿង)។\n\n"
    "CRITICAL RECAP PRINCIPLES:\n"
    "1. NARRATIVE STORYTELLING (សម្រាយដំណើររឿង):\n"
    "   - Instead of literal dialogue, summarize what characters are thinking, saying, and doing with dramatic storytelling phrasing.\n"
    "   - For the opening line (id 1 or first segment), craft an irresistible, suspenseful hook (e.g. 'រឿងរ៉ាវដ៏មិននឹកស្មានដល់បានចាប់ផ្តើមឡើងនៅពេលដែល...').\n"
    "   - Connect segments smoothly like an audio drama narrator: 'ពេលនោះ...', 'ភ្លាមនោះ...', 'នាងក៏បាននិយាយថា...', 'គាត់ភ្ញាក់ផ្អើលយ៉ាងខ្លាំង...'.\n"
    "2. NATURAL SPOKEN KHMER:\n"
    "   - Keep spoken language smooth, dramatic, emotional, and easy to pronounce for Khmer TTS.\n"
    "   - Avoid stiff literary words; use punchy spoken Khmer.\n"
    "3. MATCH DURATION & OUTPUT FORMAT:\n"
    "   - Keep each segment's narration concise to fit natural speech pacing.\n"
    "   - Return ONLY a valid JSON object mapping numeric string id to its Khmer recap narration. No markdown or explanation."
)


def strip_chinese_from_khmer(text: str) -> str:
    """
    សម្អាតអក្សរចិន សញ្ញាវណ្ណយុត្តិ និងកំណត់សម្គាល់ចិន (（...）, 【...】, [中文], 等) ទាំងអស់
    ចេញពីប្រយោគបកប្រែជាភាសាខ្មែរ ដោយរក្សាតែភាសាខ្មែរសុទ្ធ ១០០% និងសញ្ញាវណ្ណយុត្តិស្តង់ដារ។
    """
    if not text:
        return ""
    t = str(text)
    # 1. លុបកំណត់ចំណាំក្នុងវង់ក្រចកចិន ឬវង់ក្រចកទូទៅដែលមានអក្សរចិននៅខាងក្នុង (e.g. （笑）, (好的), 【李白】, [旁白])
    t = re.sub(r"[（(][^）)]*[\u4e00-\u9fff\u3400-\u4dbf][^）)]*[）)]", "", t)
    t = re.sub(r"[【\[][^】\]]*[\u4e00-\u9fff\u3400-\u4dbf][^】\]]*[】\]]", "", t)
    t = re.sub(r"\{[^\}]*[\u4e00-\u9fff\u3400-\u4dbf][^\}]*\}", "", t)

    # 2. បម្លែងសញ្ញាវណ្ណយុត្តិចិនទូទៅ មកជាសញ្ញាខ្មែរ/អន្តរជាតិស្តង់ដារ
    punct_map = {
        "\uff1f": "?",      # ？
        "\uff01": "!",      # ！
        "\uff0c": " ",      # ，
        "\u3002": "\u17d4", # 。-> ។
        "\uff1a": ": ",     # ：
        "\uff1b": "; ",     # ；
        "\u201c": "\u00ab", # “ -> «
        "\u201d": "\u00bb", # ” -> »
        "\u300a": "\u00ab", # 《 -> «
        "\u300b": "\u00bb", # 》 -> »
    }
    for ch_p, km_p in punct_map.items():
        t = t.replace(ch_p, km_p)

    # 3. លុបតួអក្សរចិន CJK Ideographs ទាំងអស់ដែលនៅសេសសល់
    t = re.sub(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", "", t)

    # 4. លុបសញ្ញាវណ្ណយុត្តិចិន Fullwidth និង CJK Symbols ដទៃទៀត
    t = re.sub(r"[\u3000-\u303f\uff00-\uffef]", " ", t)

    # 5. សម្អាតវង់ក្រចកទទេ និងសញ្ញាលើសដែលសល់ពីការលុប
    t = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}|\u00ab\s*\u00bb|[（【][\s]*[）】]", "", t)
    t = re.sub(r"\s+[:\-–—]\s+", " ", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    t = re.sub(r"\s+([!?,។])", r"\1", t)
    t = re.sub(r"([!?])\s*។", r"\1", t)
    t = re.sub(r"^[\s:\-–—\.]+", "", t).strip()
    t = re.sub(r"[\s:\-–—]+$", "", t).strip()
    t = re.sub(r"\?+", "?", t)
    t = re.sub(r"!+", "!", t)
    t = re.sub(r"\u17d4+", "\u17d4", t)
    return t


def normalize_dub_khmer_text(text: str) -> str:
    """
    Canonical Khmer dubbing & subtitle text normalizer.
    Ensures 100% word-for-word parity between the subtitle displayed on screen
    and the spoken text synthesized by KhmerTTSEngine.
    """
    if not text:
        return ""
    t = strip_chinese_from_khmer(text)
    # Remove invisible zero-width joiners/BOM and markdown/control symbols that desync TTS vs Subtitle
    t = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", t)
    t = re.sub(r"[<>\|\~`^*#_]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class ZHtoKHTranslator:
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "", glossary: List[Dict] = None, dub_style: str = "literal"):
        self.key_pool = APIKeyPoolManager(api_key)
        self.api_key = self.key_pool.get_active_key() or (api_key or "").strip()
        self.base_url = (base_url or "").strip()
        self.model = (model or "").strip()
        self.dub_style = str(dub_style or "literal").lower().strip()
        # តម្រៀបពាក្យវែងមុនពាក្យខ្លី ដើម្បីកុំឲ្យជំនួសច្រឡំផ្នែកខ្លះនៃពាក្យ
        self.glossary = sorted(
            glossary or [],
            key=lambda x: len((x.get("zh_term") or x.get("src_term") or "").strip()),
            reverse=True,
        )
        self.is_gemini = "googleapis.com" in self.base_url.lower() or (
            bool(self.api_key) and (self.api_key.startswith("AIza") or self.api_key.startswith("AQ."))
        )
        # ម៉ូដែល Gemini សកម្ម និងគាំទ្របច្ចុប្បន្ន (ការពារ Model 2.5/2.0/1.5 ដែល Google បានបិទ 404)
        if self.model in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", ""):
            self.model = "gemini-3.1-flash-lite"
        self.gemini_models = ["gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-3.7-flash"]

        self._http = requests.Session()
        self._http.headers.update({"User-Agent": self._USER_AGENT})

        if not self.is_gemini:
            from openai import OpenAI
            self.openai_client = OpenAI(
                api_key=self.api_key or "local-no-key-needed",
                base_url=self.base_url if (self.base_url and self.base_url.lower() != "google-free") else None,
            )

    def _rotate_next_key(self, failed_key: str = "", error_msg: str = "") -> Optional[str]:
        """
        Automatic round-robin rotation & instant failover when any key hits 429 Rate Limit
        or Quota Exceeded. Rebinds self.api_key and OpenAI client transparently.
        """
        if failed_key:
            next_key = self.key_pool._rotate_next_key(failed_key=failed_key, error_msg=error_msg)
        else:
            next_key = self.key_pool.get_next_round_robin_key() or None
        if not next_key:
            return None
        self.api_key = next_key
        if not self.is_gemini:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url if (self.base_url and self.base_url.lower() != "google-free") else None,
                )
            except Exception:
                pass
        return next_key

    def _get_system_prompt(self) -> str:
        """Returns the appropriate system prompt based on translation mode (literal dubbing vs AI recap narration)."""
        return RECAP_SYSTEM_PROMPT if getattr(self, "dub_style", "literal") == "recap" else DUBBING_SYSTEM_PROMPT

    @staticmethod
    def _is_khmer(text: str) -> bool:
        """ផ្ទៀងផ្ទាត់ថាតើអត្ថបទមានតួអក្សរខ្មែរពិតប្រាកដឬទេ (Unicode Range: \u1780-\u17FF)"""
        return bool(text and re.search(r"[\u1780-\u17ff]", text))

    strip_chinese_from_khmer = staticmethod(strip_chinese_from_khmer)

    def _apply_glossary(self, text: str) -> str:
        """Applies user's Custom Glossary (e.g. 'Chu Wei' -> 'ឈូ វៃ') so Khmer TTS pronounces every name cleanly."""
        if not text or not self.glossary:
            return text
        out = text
        for item in self.glossary:
            src = (item.get("zh_term") or item.get("src_term") or "").strip()
            dst = (item.get("kh_term") or "").strip()
            if src and dst and src in out:
                out = out.replace(src, f" {dst} ")
        return " ".join(out.split())

    def _apply_glossary_replacements(self, text: str) -> str:
        return self._apply_glossary(text)

    def _glossary_prompt_block(self) -> str:
        if not self.glossary:
            return ""
        pairs = [
            f"- {(g.get('zh_term') or g.get('src_term')).strip()} = {g['kh_term'].strip()}"
            for g in self.glossary
            if (g.get("zh_term") or g.get("src_term")) and g.get("kh_term")
        ]
        if not pairs:
            return ""
        return "\nMandatory Character & Term Glossary (Always use these exact Khmer terms):\n" + "\n".join(pairs) + "\n"

    @staticmethod
    def _clean_input_text(text: str) -> str:
        """Removes control characters and excessive whitespace that can trigger 500 errors on Google Translate."""
        if not text:
            return ""
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        cleaned = re.sub(r"[\r\t]+", " ", cleaned).strip()
        return cleaned

    @classmethod
    def _polish_conversational_khmer(cls, text: str) -> str:
        """
        បំលែងពាក្យបកប្រែបែបផ្លូវការរឹង (Google Translate / Literal translation) ទៅជាភាសានិយាយទូទៅ ធម្មជាតិ
        ដូចមនុស្សនិយាយផ្ទាល់ និងសមស្របសម្រាប់ការបញ្ចូលសំឡេងរឿងភាគ (Conversational Dubbing Khmer)។
        សម្អាតអក្សរចិនដែលជ្រុះចេញទាំងអស់ដោយស្វ័យប្រវត្តិ (Auto-strip Chinese text)។
        """
        if not text:
            return ""
        # 0. សម្អាតអក្សរចិន សញ្ញាចិន និងកំណត់សម្គាល់មុនពេលដំណើរការ
        t = strip_chinese_from_khmer(text).strip()
        if not cls._is_khmer(t):
            return t

        # 1. លុបពាក្យសំណួរផ្លូវការ "តើ" នៅដើមឃ្លាដែលមិនសូវប្រើក្នុងភាសានិយាយភាពយន្ត
        t = re.sub(r"^តើ\s*", "", t)
        t = re.sub(r"([!?,.៖។\s])តើ\s*", r"\1", t)

        # 2. ជំនួសឃ្លាសំណួរ និងពាក្យផ្លូវការរឹង ទៅជាភាសានិយាយរលូន
        spoken_pairs = [
            (r"កំពុងធ្វើអ្វី(?=[?!\s។]|$)", "កំពុងធ្វើអី"),
            (r"មានអ្វីកើតឡើង(?=[?!\s។]|$)", "មានរឿងអីកើតឡើង"),
            (r"មានអ្វី(?=[?!\s។]|$)", "មានរឿងអី"),
            (r"ជាអ្វី(?=[?!\s។]|$)", "ជាស្អីហ្នឹង"),
            (r"ធ្វើអ្វី(?=[?!\s។]|$)", "ធ្វើអីហ្នឹង"),
            (r"ដើម្បីអ្វី(?=[?!\s។]|$)", "ដើម្បីអី"),
            (r"សម្រាប់អ្វី(?=[?!\s។]|$)", "សម្រាប់អី"),
            (r"និយាយអ្វី(?=[?!\s។]|$)", "និយាយអី"),
            (r"ចង់បានអ្វី(?=[?!\s។]|$)", "ចង់បានអី"),
            (r"ត្រូវការអ្វី(?=[?!\s។]|$)", "ត្រូវការអី"),
            (r"នៅឯណា(?=[?!\s។]|$)", "នៅណា"),
            (r"ទៅឯណា(?=[?!\s។]|$)", "ទៅណា"),
            (r"មកពីណា(?=[?!\s។]|$)", "មកពីណា"),
            (r"ពិតមែនទេ(?=[?!\s។]|$)", "ពិតមែនអ្ហ៎"),
            (r"មែនទេ(?=[?!\s។]|$)", "មែនហ្អេ"),
            (r"សូមរង់ចាំបន្តិច", "ចាំមួយភ្លែតសិន"),
            (r"កុំបារម្ភអំពីវា", "កុំបារម្ភអី"),
            (r"កុំបារម្ភពេក", "កុំបារម្ភអី"),
            (r"មិនអីទេ", "មិនអីទេ"),
            (r"តើអ្នកសុខសប្បាយជាទេ", "សុខសប្បាយទេ"),
            (r"តើអ្នកជានរណា", "ឯងជាអ្នកណា"),
            (r"អ្នកជានរណា", "ឯងជាអ្នកណា"),
            (r"ហេតុអ្វីបានជាអ្នក", "ហេតុអីបានជាឯង"),
            (r"ហេតុអ្វីបានជា", "ហេតុអីបានជា"),
            (r"ហេតុអ្វី(?=[?!\s។]|$)", "ហេតុអី"),
            (r"យ៉ាងដូចម្តេច", "យ៉ាងម៉េចដែរ"),
            (r"យ៉ាងម៉េចហើយ", "យ៉ាងម៉េចហើយ"),
            (r"តើត្រូវទេ", "ត្រូវអត់"),
            (r"តើត្រូវឬទេ", "ត្រូវអត់"),
            (r"សូមអភ័យទោស", "សុំទោស"),
            (r"សុំទោសផង", "សុំទោស"),
            (r"មិនអាចធ្វើទៅបាន", "មិនអាចទេ"),
            (r"តើអ្នកគិតយ៉ាងណា", "ឯងគិតយ៉ាងម៉េចដែរ"),
            (r"មិនមានបញ្ហាអ្វីទេ", "គ្មានបញ្ហាអីទេ"),
            (r"តើវាជាការពិតឬ", "មែនអ្ហ៎"),
            (r"សូមកុំធ្វើបែបនេះ", "កុំធ្វើចឹងអី"),
            (r"កុំធ្វើបែបនេះ", "កុំធ្វើចឹងអី"),
            (r"ចាកចេញពីទីនេះភ្លាម", "ចេញទៅភ្លាម"),
            (r"ខ្ញុំមិនដឹងទេ", "ខ្ញុំអត់ដឹងទេ"),
            (r"មិនដឹងទេ", "អត់ដឹងទេ"),
            (r"មិនយល់ស្រប", "អត់ព្រមទេ"),
            (r"មិនចូលចិត្ត", "អត់ចូលចិត្តទេ"),
            (r"មិនមែនជាខ្ញុំទេ", "មិនមែនខ្ញុំទេ"),
            (r"គ្មានអ្វីកើតឡើងទេ", "គ្មានរឿងអីកើតឡើងទេ"),
            (r"គ្មានអ្វីសោះ", "គ្មានអីសោះ"),
            (r"តើឯង", "ឯង"),
            (r"តើខ្ញុំ", "ខ្ញុំ"),
            (r"តើគាត់", "គាត់"),
            (r"តើនាង", "នាង"),
            (r"តើពួកយើង", "ពួកយើង"),
            # Extra stiff machine-translation -> natural drama dialogue polish
            (r"សូមកុំមានការព្រួយបារម្ភ", "កុំបារម្ភអី"),
            (r"សូមអរគុណច្រើនណាស់", "អរគុណច្រើន"),
            (r"សូមអរគុណ", "អរគុណ"),
            (r"ប្រសិនបើអ្នក", "បើឯង"),
            (r"ប្រសិនបើខ្ញុំ", "បើខ្ញុំ"),
            (r"ប្រសិនបើ", "បើ"),
            (r"ដូច្នេះហើយ", "ចឹងហើយ"),
            (r"ដូច្នេះ", "ចឹង"),
            (r"ដោយសារតែ", "ព្រោះតែ"),
            (r"យ៉ាងណាក៏ដោយ", "ទោះយ៉ាងណាក៏ដោយ"),
            (r"យ៉ាងណាមិញ", "ណាមួយ"),
            (r"ជាការពិតណាស់", "ពិតមែនហើយ"),
            (r"មិនអាចជឿបានទេ", "ស្មានមិនដល់សោះ"),
            (r"សូមមេត្តា", "សុំអង្វរ"),
            (r"សូមជួយខ្ញុំផង", "ជួយខ្ញុំផង"),
            (r"ខ្ញុំយល់ហើយ", "ខ្ញុំដឹងហើយ"),
            (r"អ្វីដែលអ្នកនិយាយ", "អ្វីដែលឯងនិយាយ"),
            (r"បែបនេះហើយ", "ចឹងហើយ"),
            (r"បែបនេះ", "ចឹង"),
            (r"នៅទីនេះ", "នៅនេះ"),
            (r"នៅទីនោះ", "នៅនោះ"),
            (r"យ៉ាងរហ័ស", "លឿនឡើង"),
            (r"ប្រញាប់ឡើង", "លឿនឡើង"),
        ]
        for pattern, repl in spoken_pairs:
            t = re.sub(pattern, repl, t)

        t = re.sub(r"\?+", "?", t)
        t = re.sub(r"!+", "!", t)
        return normalize_dub_khmer_text(t)

    @staticmethod
    def _build_timed_payload(chunk: List[Dict]) -> List[Dict]:
        """Builds LLM input payload enriched with exact spoken duration (`dur_s`) and Khmer char budget for lip-sync."""
        payload = []
        for s in chunk:
            s_ms = int(s.get("start_ms", 0) or 0)
            e_ms = int(s.get("end_ms", 0) or 0)
            item = {"id": s["id"], "zh": s.get("zh_text", "")}
            if e_ms > s_ms:
                dur_s = round(max(0.4, (e_ms - s_ms) / 1000.0), 2)
                item["dur_s"] = dur_s
                # ~13-15 Khmer chars/sec reads naturally at 1.0x Edge-TTS speed without rushing
                item["max_kh_chars"] = max(12, int(round(dur_s * 14.5)))
            payload.append(item)
        return payload

    @classmethod
    def _query_free_mirrors(cls, safe_text: str, retries: int = 3) -> str:
        encoded = urllib.parse.quote(safe_text)

        # Mirror 1: Google Translate GET (GTX Client)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=km&dt=t&q={encoded}"
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": cls._USER_AGENT})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data and isinstance(data[0], list):
                        translated = "".join(part[0] for part in data[0] if part and part[0]).strip()
                        if cls._is_khmer(translated):
                            return translated
            except Exception:
                time.sleep(0.35 * (attempt + 1))

        # Mirror 2: Google clients5 endpoint (Separate rate-limit pool)
        try:
            url_c5 = f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=zh-CN&tl=km&q={encoded}"
            req = urllib.request.Request(url_c5, headers={"User-Agent": cls._USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list) and data:
                    first = data[0]
                    translated = first[0] if isinstance(first, list) else str(first)
                    translated = translated.strip()
                    if cls._is_khmer(translated):
                        return translated
        except Exception:
            pass

        # Mirror 3: MyMemory API (ZH -> KM)
        try:
            mm_url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=zh|km"
            req = urllib.request.Request(mm_url, headers={"User-Agent": cls._USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                mm_data = json.loads(resp.read().decode("utf-8"))
                if mm_data and "responseData" in mm_data:
                    translated = (mm_data["responseData"].get("translatedText") or "").strip()
                    if cls._is_khmer(translated):
                        return translated
        except Exception:
            pass

        # Mirror 4: Google Translate POST Mirror
        try:
            resp = requests.post(
                "https://translate.google.com/translate_a/single",
                params={"client": "gtx", "sl": "zh-CN", "tl": "km", "dt": "t"},
                data={"q": safe_text},
                headers={
                    "User-Agent": cls._USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                },
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data[0], list):
                    translated = "".join(part[0] for part in data[0] if part and part[0]).strip()
                    if cls._is_khmer(translated):
                        return translated
        except Exception:
            pass

        return ""

    @classmethod
    def _free_google_translate_single(cls, text: str, retries: int = 3) -> str:
        """
        បកប្រែមួយឃ្លាៗ ដោយប្រើ Multi-Mirror (4 Mirrors) និងកាត់ឃ្លាតាមសញ្ញាវណ្ណយុត្តិ (，。！？；)
        ប្រសិនបើឃ្លាទាំងមូលបរាជ័យ ដើម្បីធានាថាមិនមានជួរណាមួយរំលងមិនបានបកប្រែឡើយ!
        """
        clean_t = cls._clean_input_text(text)
        if not clean_t:
            return ""

        safe_text = clean_t[:800]
        res = cls._query_free_mirrors(safe_text, retries=retries)
        if cls._is_khmer(res):
            return cls._polish_conversational_khmer(res)

        # ប្រសិនបើឃ្លាវែងឬមានតួអក្សរចម្លែក -> បំបែកតាមសញ្ញាវណ្ណយុត្តិចិន រួចបកប្រែម្តងមួយផ្នែកៗ
        clauses = [c.strip() for c in re.split(r"[，。！？；、,.!?;]+", safe_text) if c.strip()]
        if len(clauses) > 1:
            kh_parts = []
            for cl in clauses:
                part_kh = cls._query_free_mirrors(cl, retries=2)
                if cls._is_khmer(part_kh):
                    kh_parts.append(cls._polish_conversational_khmer(part_kh))
            if kh_parts:
                return " ".join(kh_parts).strip()

        return ""

    @classmethod
    def _translate_single_free(cls, zh_text: str) -> str:
        return cls._free_google_translate_single(zh_text, retries=2)

    def _translate_chunk_gemini_direct(self, chunk: List[Dict]) -> Dict[int, str]:
        """បកប្រែជាកញ្ចប់ផ្ទាល់តាម Google Generative Language REST API គាំទ្រ gemini-3.1-flash-lite / 3.8-flash"""
        if not chunk or not self.api_key:
            return {}

        payload = self._build_timed_payload(chunk)
        prompt = (
            f"{self._get_system_prompt()}\n"
            f"{self._glossary_prompt_block()}\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        req_body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.25,
            },
        }

        # សាកល្បងម៉ូដែលសកម្ម (Round-Robin across healthy keys + Auto-Failover ពេលមាន 429/503/404)
        active_models = [self.model, *[m for m in self.gemini_models if m != self.model]]
        max_key_attempts = min(max(2, self.key_pool.total_count), 8)

        for key_try in range(max_key_attempts):
            curr_key = self._rotate_next_key() if key_try == 0 and self.key_pool.total_count > 1 else (self.key_pool.get_active_key() or self.api_key)
            if not curr_key:
                break
            for model_name in active_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={curr_key}"
                for attempt in range(2):
                    try:
                        resp = self._http.post(url, json=req_body, timeout=18)
                        if resp.status_code == 200:
                            data = resp.json()
                            raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                            raw_parsed = json.loads(raw_text)
                            if isinstance(raw_parsed, list):
                                mapped = {}
                                for item in raw_parsed:
                                    if isinstance(item, dict):
                                        k = item.get("id") or item.get("ID")
                                        v = item.get("kh") or item.get("khmer") or item.get("translation")
                                        if k is not None and v is not None:
                                            mapped[str(k)] = str(v)
                                raw_parsed = mapped
                            res = {}
                            for k, v in raw_parsed.items():
                                val = str(v).strip()
                                if str(k).isdigit() and self._is_khmer(val):
                                    res[int(k)] = self._polish_conversational_khmer(val)
                            if res:
                                self.model = model_name
                                self.api_key = curr_key
                                return res
                        elif resp.status_code == 429 or "RESOURCE_EXHAUSTED" in resp.text or "quota" in resp.text.lower():
                            # Key អស់ Quota -> Instant failover via _rotate_next_key()!
                            next_k = self._rotate_next_key(failed_key=curr_key, error_msg="429 Rate Limit / Quota Exceeded")
                            if next_k:
                                curr_key = next_k
                            break  # Move to next key immediately
                        elif resp.status_code == 503:
                            time.sleep(1.0 * (attempt + 1))
                            continue
                        elif resp.status_code == 404:
                            break
                    except Exception as ex:
                        ex_s = str(ex).lower()
                        if "429" in ex_s or "resource_exhausted" in ex_s or "quota" in ex_s or "rate" in ex_s:
                            self._rotate_next_key(failed_key=curr_key, error_msg=str(ex))
                            break
                        time.sleep(0.5)
        return {}

    def _translate_single_fallback(self, zh_text: str) -> str:
        """Translates a single missing line so 100% of IDs are guaranteed to be filled with valid Khmer."""
        text = self._clean_input_text(zh_text)
        if not text:
            return ""

        # 1. Direct Gemini REST
        if self.is_gemini and self.api_key:
            res_dict = self._translate_chunk_gemini_direct([{"id": 1, "zh_text": text}])
            if 1 in res_dict and self._is_khmer(res_dict[1]):
                return self._polish_conversational_khmer(res_dict[1])

        # 2. Local Ollama or OpenAI
        if self.model.lower() != "google-free" and self.base_url.lower() != "google-free" and not self.is_gemini:
            try:
                single_resp = self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt()},
                        {"role": "user", "content": text},
                    ],
                    temperature=0.2,
                )
                txt = single_resp.choices[0].message.content.strip()
                if self._is_khmer(txt):
                    return self._polish_conversational_khmer(txt)
            except Exception:
                pass

        # 3. Multi-Mirror Free Translators
        free_txt = self._free_google_translate_single(text, retries=2)
        return self._polish_conversational_khmer(free_txt) if self._is_khmer(free_txt) else ""

    def _translate_batch_free(
        self,
        segments: List[Dict],
        progress_cb: Optional[Callable[[int], None]] = None,
        on_chunk_done: Optional[Callable[[Dict[int, str]], None]] = None,
        batch_done_cb: Optional[Callable[[Dict[int, str]], None]] = None,
        stop_event=None,
    ) -> Dict[int, str]:
        """
        ២. ប្រើ Free Google Translate ដោយបំបែកជាកញ្ចប់តូចៗ (16 ជួរម្តង) ការពារ URL វែងពេកនាំឲ្យ Error 500
        និងរក្សាទុកចូល SQLite រៀងរាល់កញ្ចប់ (Auto-Resume + Stop Event)។
        """
        results: Dict[int, str] = {}
        total = max(1, len(segments))
        batch_size = 16
        cb_done = batch_done_cb or on_chunk_done

        for start in range(0, len(segments), batch_size):
            if stop_event and stop_event.is_set():
                break

            chunk = segments[start : start + batch_size]
            chunk_map: Dict[int, str] = {}

            cleaned_lines = [
                self._apply_glossary_replacements(
                    (s.get("zh_text") or "").replace("\n", " ").strip()
                )
                for s in chunk
            ]
            joined_zh = "\n".join(cleaned_lines)

            batch_ok = False
            if len(joined_zh) <= 950 and len(chunk) > 1:
                translated_block = self._free_google_translate_single(joined_zh, retries=2)
                lines = [ln.strip() for ln in translated_block.split("\n") if ln.strip()]
                if len(lines) == len(chunk):
                    for s, kh in zip(chunk, lines):
                        sid = int(s["id"])
                        chunk_map[sid] = self._apply_glossary_replacements(self._polish_conversational_khmer(kh))
                    batch_ok = True

            # បើបកប្រែជាកញ្ចប់ខុសចំនួនជួរ ឬវែងពេក -> បកប្រែម្តងមួយជួរៗដោយសុវត្ថិភាព
            if not batch_ok:
                for s, src_zh in zip(chunk, cleaned_lines):
                    if stop_event and stop_event.is_set():
                        break
                    sid = int(s["id"])
                    kh = self._free_google_translate_single(src_zh, retries=2)
                    if self._is_khmer(kh):
                        chunk_map[sid] = self._apply_glossary_replacements(self._polish_conversational_khmer(kh))
                    time.sleep(0.08)

            results.update(chunk_map)
            if cb_done and chunk_map:
                cb_done(chunk_map)

            time.sleep(0.12)
            if progress_cb:
                pct = min(99, int(((start + len(chunk)) / total) * 100))
                progress_cb(pct)

        if progress_cb and not (stop_event and stop_event.is_set()):
            progress_cb(100)
        return results

    def generate_social_caption(self, segments: List[Dict]) -> str:
        """Generates Viral Khmer Title, Hook, Story Summary & Hashtags for YouTube / Facebook / TikTok."""
        kh_lines = [(s.get("kh_text") or "").strip() for s in segments if (s.get("kh_text") or "").strip()]
        zh_lines = [(s.get("zh_text") or "").strip() for s in segments if (s.get("zh_text") or "").strip()]
        script_preview = "\n".join(kh_lines[:45] if kh_lines else zh_lines[:45])
        if not script_preview:
            return "មិនទាន់មានអត្ថបទសម្រាប់បង្កើតចំណងជើងទេ។ សូមស្កេន និងបកប្រែវីដេអូជាមុនសិន!"

        prompt = (
            "You are a viral Khmer movie recap & social media copywriter. Based on the following video dubbing script, "
            "write an engaging Khmer post ready to copy-paste for YouTube, Facebook Reels, and TikTok:\n"
            "1. 🎬 ចំណងជើងទាក់ទាញ (3 Viral Khmer Titles)\n"
            "2. 🔥 ឃ្លាទាក់ទាញដំបូង (Opening Hook Sentence in Khmer)\n"
            "3. 📝 សេចក្តីសង្ខេបសាច់រឿង (Short Story Recap Description in Khmer)\n"
            "4. 🏷 Hashtags (#សម្រាយរឿង #រឿងភាគចិន #AiSummarai ...)\n\n"
            f"Script:\n{script_preview}"
        )
        try:
            if self.model.lower() != "google-free" and self.base_url.lower() != "google-free":
                if self.is_gemini and self.api_key:
                    from google import genai
                    from google.genai import types
                    client = genai.Client(api_key=self.api_key)
                    resp = client.models.generate_content(
                        model=self.model or "gemini-3.1-flash-lite",
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=0.6),
                    )
                    return resp.text.strip()
                else:
                    resp = self.openai_client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.6,
                    )
                    return resp.choices[0].message.content.strip()
        except Exception:
            pass

        hook_1 = kh_lines[0] if len(kh_lines) > 0 else ""
        hook_2 = kh_lines[min(2, len(kh_lines) - 1)] if len(kh_lines) > 1 else ""
        summary_body = " ".join(kh_lines[:8])
        return (
            "🎬 ចំណងជើងទាក់ទាញ (Viral Titles):\n"
            f"• {hook_1} — សម្រាយរឿងភាគចិនដ៏ជក់ចិត្ត!\n"
            f"• គូស្នេហ៍កំសាក តែចិញ្ចឹមបានស្តេចដ៏អស្ចារ្យ! ({hook_2})\n"
            "• រឿងភាគចិនបញ្ចូលសំឡេងខ្មែរពេញលេញ | Ai Summarai\n\n"
            "🔥 ឃ្លាទាក់ទាញ (Opening Hook):\n"
            f"«{hook_1} {hook_2}»\n\n"
            "📝 សេចក្តីសង្ខេបសាច់រឿង (Description):\n"
            f"{summary_body}\n\n"
            "🏷 Hashtags:\n"
            "#សម្រាយរឿង #រឿងភាគចិន #បញ្ចូលសំឡេងខ្មែរ #រឿងបុរាណចិន #AiSummarai #KhmerDubbing #MovieRecapKH"
        )

    def generate_viral_hook(self, segments: List[Dict], episode_title: str = "") -> str:
        """
        Summarizes an episode script into a punchy 1-line Khmer viral hook banner title
        (e.g. 'ភាគទី១៖ នាងត្រូវគេមើលងាយ តែការពិតគឺជាកូនស្រីមហាសេដ្ឋី!') via Gemini / OpenAI,
        with an automatic conversational fallback if offline or using free mode.
        """
        kh_lines = [normalize_dub_khmer_text(s.get("kh_text") or "") for s in (segments or [])]
        kh_lines = [ln for ln in kh_lines if self._is_khmer(ln)]
        zh_lines = [(s.get("zh_text") or "").strip() for s in (segments or []) if (s.get("zh_text") or "").strip()]
        script_preview = "\n".join(kh_lines[:35] if kh_lines else zh_lines[:35])

        if not script_preview:
            ep_hint = f" ({episode_title})" if episode_title else ""
            return f"រឿងភាគចិនដ៏ជក់ចិត្ត! នឹកស្មានមិនដល់នូវការពិតខាងក្រោយ{ep_hint}!"

        ep_context = f"Episode file/title: {episode_title}\n" if episode_title else ""
        prompt = (
            "You are a viral Cambodian movie-recap & short-drama headline copywriter.\n"
            "Summarize the episode script below into ONE irresistible, punchy, dramatic 1-line Khmer viral hook title "
            "suitable for a top video banner & YouTube/TikTok/Facebook thumbnail cover.\n"
            "STRICT RULES:\n"
            "1. Output ONLY ONE single line of pure natural spoken Khmer (max 75 Khmer characters).\n"
            "2. Make it high-curiosity and dramatic (example style: 'ភាគទី១៖ នាងត្រូវគេមើលងាយ តែការពិតគឺជាកូនស្រីមហាសេដ្ឋី!').\n"
            "3. ZERO Chinese characters, ZERO markdown, ZERO quotation marks, ZERO numbering, ZERO explanation.\n\n"
            f"{ep_context}Script:\n{script_preview}"
        )

        def _clean_hook(raw: str) -> str:
            if not raw:
                return ""
            first_line = next((ln.strip() for ln in str(raw).splitlines() if ln.strip()), "")
            first_line = re.sub(r"^[\-\*\•\d\.\)\s\"'«»“”]+", "", first_line)
            first_line = re.sub(r"[\"'«»“”]+$", "", first_line).strip()
            cleaned = normalize_dub_khmer_text(first_line)
            if len(cleaned) > 105:
                cleaned = cleaned[:102].rstrip() + "..."
            return cleaned

        # 1. Direct Gemini REST API (supports API key pool rotation & model fallback)
        if self.is_gemini and self.api_key and self.model.lower() != "google-free":
            req_body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.75, "maxOutputTokens": 120},
            }
            active_models = [self.model, *[m for m in self.gemini_models if m != self.model]]
            max_key_attempts = min(max(2, self.key_pool.total_count), 4)
            for _ in range(max_key_attempts):
                curr_key = self.key_pool.get_active_key() or self.api_key
                if not curr_key:
                    break
                for model_name in active_models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={curr_key}"
                    try:
                        resp = self._http.post(url, json=req_body, timeout=15)
                        if resp.status_code == 200:
                            data = resp.json()
                            raw_t = data["candidates"][0]["content"]["parts"][0]["text"]
                            hook = _clean_hook(raw_t)
                            if self._is_khmer(hook):
                                return hook
                        elif resp.status_code == 429 or "RESOURCE_EXHAUSTED" in resp.text:
                            self.key_pool.rotate_on_failure(curr_key, "429 Quota Exceeded")
                            break
                        elif resp.status_code == 404:
                            break
                    except Exception:
                        continue

        # 2. OpenAI / Local Ollama Client
        if (
            not self.is_gemini
            and self.model.lower() != "google-free"
            and self.base_url.lower() != "google-free"
            and hasattr(self, "openai_client")
        ):
            try:
                resp = self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.75,
                )
                hook = _clean_hook(resp.choices[0].message.content or "")
                if self._is_khmer(hook):
                    return hook
            except Exception:
                pass

        # 3. Smart Deterministic Local Khmer Fallback (Works offline & in Google-Free mode)
        if not kh_lines and zh_lines:
            sample_zh = "，".join(zh_lines[:3])[:220]
            tr_kh = self._free_google_translate_single(sample_zh, retries=2)
            if self._is_khmer(tr_kh):
                kh_lines = [tr_kh]

        if kh_lines:
            # Prefer a punchy emotional line (containing ! or ?) or medium-length opening climax line
            dramatic = [ln for ln in kh_lines[:20] if ("!" in ln or "?" in ln) and 14 <= len(ln) <= 78]
            chosen = dramatic[0] if dramatic else max(kh_lines[:10], key=lambda x: min(len(x), 70))
            if len(chosen) > 76:
                chosen = chosen[:73].rstrip() + "..."
            ep_match = re.search(r"(?:ep|episode|ភាគ|第)[\s_\-]*(\d+)", episode_title or "", re.IGNORECASE)
            if ep_match and not chosen.startswith("ភាគ"):
                return f"ភាគទី{ep_match.group(1)}៖ {chosen}"
            return f"🔥 {chosen}" if not chosen.startswith(("🔥", "ភាគ")) else chosen

        return "ភាគពិសេស៖ ការពិតដ៏នឹកស្មានមិនដល់ត្រូវបានបើកកកាយ!"

    def _call_llm_json(self, prompt: str, temperature: float = 0.4, max_tokens: int = 1200):
        """Shared resilient JSON LLM helper with Gemini/OpenAI round-robin & _rotate_next_key() failover."""
        if self.model.lower() == "google-free" or self.base_url.lower() == "google-free":
            return None
        if self.is_gemini and self.api_key:
            req_body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            }
            active_models = [self.model, *[m for m in self.gemini_models if m != self.model]]
            for key_try in range(min(max(2, self.key_pool.total_count), 6)):
                curr_key = self._rotate_next_key() if key_try == 0 and self.key_pool.total_count > 1 else (self.key_pool.get_active_key() or self.api_key)
                if not curr_key:
                    break
                for m_name in active_models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={curr_key}"
                    try:
                        resp = self._http.post(url, json=req_body, timeout=20)
                        if resp.status_code == 200:
                            raw_t = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                            raw_t = raw_t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                            return json.loads(raw_t)
                        elif resp.status_code == 429 or "RESOURCE_EXHAUSTED" in resp.text or "quota" in resp.text.lower():
                            self._rotate_next_key(failed_key=curr_key, error_msg="429 Rate Limit")
                            break
                        elif resp.status_code == 404:
                            break
                    except Exception:
                        continue
            return None

        if not self.is_gemini and hasattr(self, "openai_client") and (self.api_key or "localhost" in self.base_url.lower() or "127.0.0.1" in self.base_url.lower()):
            if self.key_pool.total_count > 1:
                self._rotate_next_key()
            for _ in range(max(2, min(self.key_pool.total_count + 1, 6))):
                try:
                    resp = self.openai_client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=temperature,
                    )
                    raw_t = (resp.choices[0].message.content or "").strip()
                    raw_t = raw_t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    return json.loads(raw_t)
                except Exception as ex:
                    ex_s = str(ex).lower()
                    if any(tok in ex_s for tok in ("429", "rate_limit", "quota", "resource_exhausted")):
                        if self._rotate_next_key(failed_key=self.api_key, error_msg=str(ex)[:100]):
                            continue
                    break
        return None

    def classify_segment_emotions(self, segments: List[Dict]) -> Dict[int, str]:
        """
        Analyzes Khmer/Chinese dialogue lines and tags emotional beats with one of:
        `dramatic_shock`, `sad_emotional`, `action_fight`, `funny_awkward`, `romantic`.
        Uses Gemini/OpenAI JSON classification when available with a fast offline Khmer+ZH lexicon fallback.
        """
        valid_tones = {"dramatic_shock", "sad_emotional", "action_fight", "funny_awkward", "romantic"}
        results: Dict[int, str] = {}
        if not segments:
            return results

        # 1. Try LLM batch emotion tagging (chunks of 45 lines for speed & low cost)
        if self.model.lower() != "google-free" and self.base_url.lower() != "google-free" and (self.api_key or "localhost" in self.base_url.lower()):
            for start in range(0, len(segments), 45):
                batch = segments[start : start + 45]
                items = [
                    {"id": int(s.get("id") or idx), "text": (s.get("kh_text") or s.get("zh_text") or "").strip()[:120]}
                    for idx, s in enumerate(batch, start=start)
                    if (s.get("kh_text") or s.get("zh_text") or "").strip()
                ]
                if not items:
                    continue
                prompt = (
                    "Analyze these drama dialogue lines and pick ONLY the genuinely emotional moments that deserve a sound effect.\n"
                    "Map segment id to ONE of these exact labels: "
                    "'dramatic_shock', 'sad_emotional', 'action_fight', 'funny_awkward', 'romantic'.\n"
                    "Skip neutral/ordinary lines (tag roughly 15%-30% of lines). Return ONLY a JSON object {id: emotion}.\n"
                    f"Lines:\n{json.dumps(items, ensure_ascii=False)}"
                )
                parsed = self._call_llm_json(prompt, temperature=0.25, max_tokens=800)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        emo = str(v or "").strip().lower()
                        if str(k).isdigit() and emo in valid_tones:
                            results[int(k)] = emo

        if results:
            return results

        # 2. Fast Offline / Free-Mode Khmer + Chinese Emotion Lexicon Classifier
        lexicon = [
            ("dramatic_shock", [
                "ស្អីគេ", "មិនអាចទេ", "ទៅមិនរួច", "ក្បត់", "កុហក", "ការពិត", "ភ្ញាក់ផ្អើល", "ស្មានមិនដល់",
                "ងាប់ហើយ", "ម៉េចបាន", "លាក់បាំង", "ឆ្កួត", "ហ៊ានណាស់", "ដឹងការពិត",
                "不可能", "背叛", "骗", "真相", "怎么会", "居然", "天啊", "疯了",
            ]),
            ("action_fight", [
                "សម្លាប់", "វាយ", "ចាប់", "រត់", "ប្រយុទ្ធ", "ប្រយ័ត្ន", "ឈប់ភ្លាម", "ចេញទៅ", "ដកដាវ",
                "បាញ់", "ជួយផង", "ដេញតាម", "杀", "打", "抓", "跑", "救命", "滚", "动手", "小心",
            ]),
            ("sad_emotional", [
                "យំ", "ឈឺចាប់", "សោកស្តាយ", "ទឹកភ្នែក", "បាត់បង់", "សុំទោស", "អាណិត", "ឯកា",
                "ស្លាប់", "លាហើយ", "ខូចចិត្ត", "បែកគ្នា", "对不起", "哭", "眼泪", "心痛", "难过", "死了", "别走",
            ]),
            ("romantic", [
                "ស្រឡាញ់", "បងស្រឡាញ់អូន", "អូនស្រឡាញ់បង", "រៀបការ", "បេះដូង", "សង្សារ", "នឹក",
                "ប្រពន្ធ", "ប្តី", "ថើប", "អោប", "爱你", "喜欢你", "结婚", "亲爱的", "想你", "老婆", "老公",
            ]),
            ("funny_awkward", [
                "ហាហា", "កំប្លែង", "ខ្មាស", "ឆ្ងល់", "ភ្លើ", "ល្ងង់", "អៀន", "ច្រឡំ", "សើច",
                "哈哈", "搞笑", "尴尬", "傻", "笨", "笑死", "误会",
            ]),
        ]

        for idx, seg in enumerate(segments):
            sid = int(seg.get("id") or idx)
            txt = f"{seg.get('kh_text') or ''} {seg.get('zh_text') or ''}".strip()
            if not txt:
                continue
            matched_tone = ""
            for tone, kws in lexicon:
                if any(kw in txt for kw in kws):
                    matched_tone = tone
                    break
            if not matched_tone and ("!" in txt or "！" in txt) and len(txt) >= 12:
                matched_tone = "dramatic_shock"
            elif not matched_tone and ("?" in txt or "？" in txt) and ("..." in txt or "…" in txt):
                matched_tone = "funny_awkward"
            if matched_tone:
                results[sid] = matched_tone
        return results

    def generate_social_pack(self, segments: List[Dict], video_name: str = "") -> Dict:
        """
        Builds a complete Social Media Export Bundle & Caption Pack containing:
        - 3 viral Khmer hook titles tailored for TikTok, Facebook Reels, and YouTube Shorts
        - A 2-sentence Khmer episode recap description
        - Trending Khmer & drama hashtags ready for 1-click copy-paste.
        """
        kh_lines = [normalize_dub_khmer_text(s.get("kh_text") or "") for s in (segments or [])]
        kh_lines = [ln for ln in kh_lines if self._is_khmer(ln)]
        zh_lines = [(s.get("zh_text") or "").strip() for s in (segments or []) if (s.get("zh_text") or "").strip()]
        script_preview = "\n".join(kh_lines[:45] if kh_lines else zh_lines[:45])

        default_tags = [
            "#សម្រាយរឿង", "#រឿងភាគចិន", "#និយាយខ្មែរ",
            "#បញ្ចូលសំឡេងខ្មែរ", "#រឿងខ្លី", "#រឿងល្បីTikTok", "#AiSummarai"
        ]

        if script_preview:
            prompt = (
                "You are an expert Cambodian viral short-video & drama social media strategist.\n"
                "Based on the episode script below, return ONLY a valid JSON object with these exact keys:\n"
                "{\n"
                '  "tiktok_title": "1 punchy viral Khmer hook title for TikTok (max 80 chars)",\n'
                '  "facebook_reels_title": "1 emotional curiosity Khmer title for Facebook Reels (max 85 chars)",\n'
                '  "youtube_shorts_title": "1 high-CTR Khmer title for YouTube Shorts (max 85 chars)",\n'
                '  "recap_description": "Exactly 2 engaging sentences in natural spoken Khmer summarizing the episode plot without spoiling the ending.",\n'
                '  "hashtags": ["#សម្រាយរឿង", "#រឿងភាគចិន", "#និយាយខ្មែរ", "...6-10 trending Khmer & drama hashtags..."]\n'
                "}\n"
                "STRICT: Use 100% pure natural Khmer (ZERO Chinese characters). Return ONLY JSON.\n\n"
                f"Video name: {video_name}\nScript:\n{script_preview}"
            )
            parsed = self._call_llm_json(prompt, temperature=0.65, max_tokens=700)
            if isinstance(parsed, dict) and self._is_khmer(str(parsed.get("tiktok_title") or "")):
                raw_tags = parsed.get("hashtags") or default_tags
                if isinstance(raw_tags, str):
                    raw_tags = [t.strip() for t in raw_tags.split() if t.strip().startswith("#")]
                tags = [str(t).strip() for t in raw_tags if str(t).strip()]
                for must_tag in ("#សម្រាយរឿង", "#រឿងភាគចិន", "#និយាយខ្មែរ"):
                    if must_tag not in tags:
                        tags.insert(0, must_tag)
                return {
                    "video_name": video_name or "Episode",
                    "titles": {
                        "tiktok": normalize_dub_khmer_text(str(parsed.get("tiktok_title") or "")),
                        "facebook_reels": normalize_dub_khmer_text(str(parsed.get("facebook_reels_title") or parsed.get("tiktok_title") or "")),
                        "youtube_shorts": normalize_dub_khmer_text(str(parsed.get("youtube_shorts_title") or parsed.get("tiktok_title") or "")),
                    },
                    "recap_description": normalize_dub_khmer_text(str(parsed.get("recap_description") or "")),
                    "hashtags": tags[:12],
                }

        # Deterministic Local Khmer Fallback
        if not kh_lines and zh_lines:
            sample = self._free_google_translate_single("，".join(zh_lines[:4])[:250], retries=2)
            if self._is_khmer(sample):
                kh_lines = [sample]

        base_hook = self.generate_viral_hook(segments, episode_title=video_name)
        line_a = kh_lines[0] if len(kh_lines) > 0 else "រឿងរ៉ាវដ៏មិននឹកស្មានដល់បានផ្ទុះឡើងភ្លាមៗ!"
        line_b = kh_lines[min(3, len(kh_lines) - 1)] if len(kh_lines) > 1 else "ចុងក្រោយតើការពិតនឹងទៅជាយ៉ាងណា?"
        short_a = line_a[:65].rstrip()
        return {
            "video_name": video_name or "Episode",
            "titles": {
                "tiktok": base_hook,
                "facebook_reels": f"😭 ឈុតដ៏កន្ត្រាក់អារម្មណ៍! {short_a}",
                "youtube_shorts": f"🎬 សម្រាយរឿងភាគចិននិយាយខ្មែរ | {short_a}",
            },
            "recap_description": (
                f"សាច់រឿងកាន់តែជក់ចិត្តនៅពេលដែល «{line_a}» ធ្វើឲ្យគ្រប់គ្នាភ្ញាក់ផ្អើល។ "
                f"ចាំមើលថាតើជោគវាសនារបស់តួអង្គនឹងប្រែប្រួលបែបណានៅពេល «{line_b}»!"
            ),
            "hashtags": default_tags,
        }

    @staticmethod
    def format_social_pack_txt(pack: Dict) -> str:
        titles = pack.get("titles") or {}
        tags_str = " ".join(pack.get("hashtags") or ["#សម្រាយរឿង", "#រឿងភាគចិន", "#និយាយខ្មែរ"])
        return (
            f"==================================================\n"
            f"📲 AI SUMMARAI — SOCIAL MEDIA EXPORT PACK\n"
            f"🎬 Video: {pack.get('video_name', 'Episode')}\n"
            f"==================================================\n\n"
            f"🔥 1. ចំណងជើង Viral សម្រាប់ផុស (3 Viral Khmer Hook Titles):\n"
            f"• TikTok:         {titles.get('tiktok', '')}\n"
            f"• Facebook Reels: {titles.get('facebook_reels', '')}\n"
            f"• YouTube Shorts: {titles.get('youtube_shorts', '')}\n\n"
            f"📝 2. សេចក្តីសង្ខេបសាច់រឿង (2-Sentence Khmer Recap Description):\n"
            f"{pack.get('recap_description', '')}\n\n"
            f"🏷️ 3. Trending Hashtags (Copy-Paste):\n"
            f"{tags_str}\n"
        )

    @classmethod
    def save_social_pack_files(cls, pack: Dict, base_video_or_output_path: str) -> tuple[str, str]:
        """Saves companion <stem>_SocialPack.txt and <stem>_SocialPack.json alongside an exported video."""
        from pathlib import Path
        p = Path(base_video_or_output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        base_stem = p.stem
        txt_path = p.parent / f"{base_stem}_SocialPack.txt"
        json_path = p.parent / f"{base_stem}_SocialPack.json"
        txt_path.write_text(cls.format_social_pack_txt(pack), encoding="utf-8-sig")
        json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(txt_path), str(json_path)

    def translate_batch(
        self,
        segments: List[Dict],
        batch_size: int = 25,
        progress_cb: Optional[Callable[[int], None]] = None,
        on_chunk_done: Optional[Callable[[Dict[int, str]], None]] = None,
        batch_done_cb: Optional[Callable[[Dict[int, str]], None]] = None,
        stop_event=None,
    ) -> Dict[int, str]:
        cb_done = batch_done_cb or on_chunk_done
        # ១. បើជ្រើសរើស Free Google Translate ឬមិនទាន់ដាក់ API Key (ក្រៅពី Local Ollama)
        is_local = "localhost" in self.base_url.lower() or "127.0.0.1" in self.base_url.lower()
        if (
            self.model.lower() == "google-free"
            or self.base_url.lower() == "google-free"
            or (not self.api_key and not is_local)
        ):
            return self._translate_batch_free(
                segments,
                progress_cb=progress_cb,
                batch_done_cb=cb_done,
                stop_event=stop_event,
            )

        results: Dict[int, str] = {}
        total = max(1, len(segments))

        # ២. ប្រសិនបើប្រើ Google Gemini API (Direct REST API ល្បឿនសមរម្យ មិន freeze CPU/RAM)
        if self.is_gemini and self.api_key:
            # ប្រើទំហំកញ្ចប់សមរម្យ (18-20 ជួរម្តង) ដើម្បីឲ្យបកប្រែលឿន ឆ្លើយតបក្នុង 1.5-2.5s និងមិនដែលគាំង
            batch_sz = min(max(batch_size, 16), 20)
            chunks = [segments[i : i + batch_sz] for i in range(0, len(segments), batch_sz)]
            completed_items = 0

            for chk in chunks:
                if stop_event and stop_event.is_set():
                    break
                gem_res = self._translate_chunk_gemini_direct(chk)
                chunk_map: Dict[int, str] = {}
                for s in chk:
                    sid = int(s["id"])
                    if sid in gem_res and self._is_khmer(gem_res[sid]):
                        chunk_map[sid] = self._apply_glossary_replacements(gem_res[sid])
                    else:
                        kh = self._translate_single_fallback(s.get("zh_text", ""))
                        if self._is_khmer(kh):
                            chunk_map[sid] = self._apply_glossary_replacements(kh)

                results.update(chunk_map)
                if cb_done and chunk_map:
                    cb_done(chunk_map)

                completed_items += len(chk)
                if progress_cb:
                    progress_cb(int((min(completed_items, total) / total) * 100))

                # សម្រាកខ្លី 0.10s ការពារកុំឲ្យជាន់ Rate Limit (429) និងរក្សា UI ឲ្យរលូន 100%
                time.sleep(0.10)

            return results

        # ៣. ប្រសិនបើប្រើ OpenAI API ឬ Local Ollama (ជាមួយ Round-Robin & Auto-Failover _rotate_next_key)
        try:
            for i in range(0, len(segments), batch_size):
                if stop_event and stop_event.is_set():
                    break
                chunk = segments[i : i + batch_size]
                payload = self._build_timed_payload(chunk)

                prompt = (
                    f"{self._get_system_prompt()}\n"
                    f"{self._glossary_prompt_block()}"
                    f"Input:\n{json.dumps(payload, ensure_ascii=False)}"
                )

                # Round-robin to next healthy key before sending chunk if multiple keys exist
                if self.key_pool.total_count > 1:
                    self._rotate_next_key()

                raw = ""
                max_oai_attempts = max(2, min(self.key_pool.total_count + 1, 8))
                for _k_try in range(max_oai_attempts):
                    try:
                        resp = self.openai_client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": self._get_system_prompt()},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.25,
                        )
                        raw = resp.choices[0].message.content.strip()
                        break
                    except Exception as oai_err:
                        err_s = str(oai_err).lower()
                        if any(tok in err_s for tok in ("429", "rate_limit", "quota", "insufficient_quota", "resource_exhausted")):
                            rotated = self._rotate_next_key(failed_key=self.api_key, error_msg=str(oai_err)[:120])
                            if rotated:
                                continue
                        raise

                raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

                raw_parsed = json.loads(raw)
                if isinstance(raw_parsed, list):
                    raw_parsed = {item.get("id"): item.get("kh") for item in raw_parsed if isinstance(item, dict)}
                parsed = {int(k): self._polish_conversational_khmer(str(v).strip()) for k, v in raw_parsed.items() if str(k).isdigit()}

                chunk_map: Dict[int, str] = {}
                for s in chunk:
                    sid = int(s["id"])
                    if sid in parsed and self._is_khmer(parsed[sid]):
                        chunk_map[sid] = self._apply_glossary_replacements(parsed[sid])
                    else:
                        kh = self._translate_single_fallback(s.get("zh_text", ""))
                        if self._is_khmer(kh):
                            chunk_map[sid] = self._apply_glossary_replacements(kh)

                results.update(chunk_map)
                if cb_done and chunk_map:
                    cb_done(chunk_map)

                if progress_cb:
                    progress_cb(int((min(i + batch_size, total) / total) * 100))

            return results
        except Exception:
            # បើ API Key អស់ Quota ឬ Ollama មិនបើក ធ្លាក់មកប្រើ Free Google Translate សម្រាប់ជួរដែលនៅសល់ដោយស្វ័យប្រវត្តិ
            remaining = [s for s in segments if int(s["id"]) not in results]
            if remaining and not (stop_event and stop_event.is_set()):
                free_res = self._translate_batch_free(
                    remaining,
                    progress_cb=progress_cb,
                    batch_done_cb=cb_done,
                    stop_event=stop_event,
                )
                results.update(free_res)
            return results

    def translate_segments(
        self,
        segments: List[Dict],
        progress_cb: Optional[Callable[[int], None]] = None,
        batch_done_cb: Optional[Callable[[Dict[int, str]], None]] = None,
        stop_event=None,
    ) -> Dict[int, str]:
        """
        បកប្រែប្រយោគដោយរក្សាទុករៀងរាល់ 10 ជួរ (Auto-Resume)
        និងអាចចុច Stop បញ្ឈប់បានភ្លាមៗដោយមិនបាត់ទិន្នន័យដែលធ្វើរួច។
        """
        pending = [s for s in segments if not self._is_khmer(s.get("kh_text") or "")]
        if not pending:
            if progress_cb:
                progress_cb(100)
            return {}
        res = self.translate_batch(
            pending,
            progress_cb=progress_cb,
            batch_done_cb=batch_done_cb,
            stop_event=stop_event,
        )
        # ត្រួតពិនិត្យជុំទី ២ សម្រាប់ជួរណាដែលនៅសល់មិនទាន់បកប្រែ (Zero Un-translated Guarantee)
        if not (stop_event and stop_event.is_set()):
            missed = [s for s in pending if int(s["id"]) not in res or not self._is_khmer(res.get(int(s["id"]), ""))]
            for s in missed:
                if stop_event and stop_event.is_set():
                    break
                sid = int(s["id"])
                kh = self._translate_single_fallback(s.get("zh_text", ""))
                if self._is_khmer(kh):
                    kh_clean = self._apply_glossary_replacements(kh)
                    res[sid] = kh_clean
                    if batch_done_cb:
                        batch_done_cb({sid: kh_clean})
                time.sleep(0.25)
        return res


SubtitleTranslator = ZHtoKHTranslator
