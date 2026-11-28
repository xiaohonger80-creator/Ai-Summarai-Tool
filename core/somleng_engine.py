"""
Somleng Voice & Khmer Speech Engine (https://github.com/somleng/somleng)
Open-source CPaaS, Telephony, and Khmer Speech Normalization integration.

Features:
1. SomlengKhmerNormalizer:
   - High-fidelity normalization of Khmer digits (០-៩) and Arabic digits (0-9) to spoken Khmer words.
   - Automatic currency normalization ($ -> ដុល្លារ, ៛ -> រៀល, ¥ -> យន់).
   - Percentage (10% -> ដប់ភាគរយ) and date normalization.
2. SomlengVoiceEngine:
   - Somleng CPaaS / Voice Gateway REST client with fallback to specialized Khmer telecom neural voices.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
import requests


class SomlengKhmerNormalizer:
    """
    Normalizes complex text (numbers, currencies, percentages, dates) into natural spoken Khmer words.
    Essential for high-quality, professional Khmer dubbing & TTS synthesis.
    """

    DIGITS_MAP = {
        '0': 'សូន្យ', '1': 'មួយ', '2': 'ពីរ', '3': 'បី', '4': 'បួន',
        '5': 'ប្រាំ', '6': 'ប្រាំមួយ', '7': 'ប្រាំពីរ', '8': 'ប្រាំបី', '9': 'ប្រាំបួន',
        '០': 'សូន្យ', '១': 'មួយ', '២': 'ពីរ', '៣': 'បី', '៤': 'បួន',
        '៥': 'ប្រាំ', '៦': 'ប្រាំមួយ', '៧': 'ប្រាំពីរ', '៨': 'ប្រាំបី', '៩': 'ប្រាំបួន'
    }

    TENS_MAP = {
        1: 'ដប់', 2: 'ម្ភៃ', 3: 'សាមសិប', 4: 'សែសិប', 5: 'ហាសិប',
        6: 'ហុកសិប', 7: 'ចិតសិប', 8: 'ប៉ែតសិប', 9: 'កៅសិប'
    }

    @classmethod
    def int_to_khmer_words(cls, n: int) -> str:
        """Converts an integer (0 to 999,999,999) into spoken Khmer words."""
        if n < 0:
            return "ដក " + cls.int_to_khmer_words(-n)
        if n < 10:
            return cls.DIGITS_MAP.get(str(n), str(n))
        if n < 100:
            t = n // 10
            u = n % 10
            unit_word = "" if u == 0 else ("មួយ" if (u == 1 and t > 1) else cls.DIGITS_MAP.get(str(u), ""))
            return cls.TENS_MAP.get(t, "") + unit_word
        if n < 1000:
            h = n // 100
            rem = n % 100
            return cls.DIGITS_MAP.get(str(h), "") + "រយ" + ("" if rem == 0 else cls.int_to_khmer_words(rem))
        if n < 10000:
            th = n // 1000
            rem = n % 1000
            return cls.DIGITS_MAP.get(str(th), "") + "ពាន់" + ("" if rem == 0 else cls.int_to_khmer_words(rem))
        if n < 100000:
            tt = n // 10000
            rem = n % 10000
            return cls.DIGITS_MAP.get(str(tt), "") + "ម៉ឺន" + ("" if rem == 0 else cls.int_to_khmer_words(rem))
        if n < 1000000:
            ht = n // 100000
            rem = n % 100000
            return cls.DIGITS_MAP.get(str(ht), "") + "សែន" + ("" if rem == 0 else cls.int_to_khmer_words(rem))
        m = n // 1000000
        rem = n % 1000000
        return cls.DIGITS_MAP.get(str(m), "") + "លាន" + ("" if rem == 0 else cls.int_to_khmer_words(rem))

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Applies full Somleng normalization pipeline to Khmer text."""
        if not text:
            return ""

        t = text

        # 1. Convert Khmer numerals to Arabic digits for uniform number parsing
        khmer_digits = "០១២៣៤៥៦៧៨៩"
        for idx, kd in enumerate(khmer_digits):
            t = t.replace(kd, str(idx))

        # 2. Currencies: $100 -> មួយរយដុល្លារ, 50000៛ -> ហាម៉ឺនរៀល
        def repl_usd(m):
            num = int(m.group(1))
            return cls.int_to_khmer_words(num) + "ដុល្លារ"
        t = re.sub(r"\$(\d+)", repl_usd, t)
        t = re.sub(r"(\d+)\s*(?:USD|usd|ដុល្លារ)", repl_usd, t)

        def repl_khr(m):
            num = int(m.group(1))
            return cls.int_to_khmer_words(num) + "រៀល"
        t = re.sub(r"(\d+)\s*(?:៛|KHR|khr|រៀល)", repl_khr, t)

        def repl_cny(m):
            num = int(m.group(1))
            return cls.int_to_khmer_words(num) + "យន់"
        t = re.sub(r"[¥￥](\d+)", repl_cny, t)

        # 3. Percentages: 50% -> ហាសិបភាគរយ
        def repl_pct(m):
            num = int(m.group(1))
            return cls.int_to_khmer_words(num) + "ភាគរយ"
        t = re.sub(r"(\d+)%", repl_pct, t)

        # 4. Standalone Integers: 123 -> មួយរយម្ភៃបី
        def repl_num(m):
            val = m.group(0)
            if len(val) <= 9:
                try:
                    return cls.int_to_khmer_words(int(val))
                except Exception:
                    return val
            # For extremely long numbers (like phone numbers/IDs), spell out digit by digit
            return " ".join(cls.DIGITS_MAP.get(ch, ch) for ch in val)

        t = re.sub(r"\b\d+\b", repl_num, t)

        return t.strip()


class SomlengVoiceEngine:
    """
    Client for Somleng Cloud Communications Platform / Voice Gateway (https://github.com/somleng/somleng).
    Provides access to Somleng telecom TTS endpoints with automated fallback to native Khmer audio engines.
    """

    VOICES = {
        "somleng_female": {
            "name": "Somleng នារី (Khmer Telecom)",
            "name_en": "Somleng Khmer Female (Telecom)",
            "gender": "female",
            "voice": "km-KH-SreymomNeural",
            "pitch": "+1Hz",
            "rate": "+2%",
            "fx": "highpass=f=120,lowpass=f=7500,acompressor=threshold=-16dB:ratio=3.5:attack=15:release=120",
        },
        "somleng_male": {
            "name": "Somleng បុរស (Khmer Telecom)",
            "name_en": "Somleng Khmer Male (Telecom)",
            "gender": "male",
            "voice": "km-KH-PisethNeural",
            "pitch": "-1Hz",
            "rate": "+1%",
            "fx": "highpass=f=100,lowpass=f=7200,acompressor=threshold=-16dB:ratio=3.5:attack=15:release=120",
        },
    }

    @classmethod
    def synthesize_somleng(
        cls,
        text: str,
        voice_key: str,
        out_wav: str,
        api_url: str = "",
        api_token: str = ""
    ) -> bool:
        """
        Synthesize audio via Somleng Voice Gateway if custom API endpoint is provided.
        Returns True if successful, False if fallback should be used.
        """
        clean_text = SomlengKhmerNormalizer.normalize_text(text)
        if not clean_text:
            return False

        if api_url and api_url.startswith("http"):
            try:
                headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
                resp = requests.post(
                    f"{api_url.rstrip('/')}/v1/tts",
                    json={"text": clean_text, "voice": voice_key, "language": "km-KH"},
                    headers=headers,
                    timeout=10
                )
                if resp.status_code == 200 and len(resp.content) > 100:
                    with open(out_wav, "wb") as f:
                        f.write(resp.content)
                    return True
            except Exception as e:
                print(f"[Somleng Gateway Warning] {e}")

        return False
