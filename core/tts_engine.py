import asyncio
import re
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional
import edge_tts
import requests

from core.voice_clone_engine import VoiceCloneEngine
from core.translator import normalize_dub_khmer_text

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class KhmerTTSEngine:
    # ៤ ប្រភេទសំឡេងគោល៖ មនុស្សស្រី (female), មនុស្សប្រុស (male), សំឡេងក្នុងចិត្ត (inner_thought) និង សំឡេងទូរស័ព្ទ (phone_call)
    VOICE_PROFILES = {
        "female": {
            "label_en": "Female (Sreymom)",
            "label_kh": "ស្រី (Sreymom)",
            "voice": "km-KH-SreymomNeural",
            "pitch": "+0Hz",
            "rate": "+0%",
            "fx": "",
        },
        "male": {
            "label_en": "Male (Piseth)",
            "label_kh": "ប្រុស (Piseth)",
            "voice": "km-KH-PisethNeural",
            "pitch": "+0Hz",
            "rate": "+0%",
            "fx": "",
        },
        "inner_thought": {
            "label_en": "Inner Thought",
            "label_kh": "សំឡេងក្នុងចិត្ត",
            "voice": "km-KH-SreymomNeural",
            "pitch": "-4Hz",
            "rate": "-2%",
            "fx": "aecho=0.8:0.88:65:0.42,lowpass=f=4500",
        },
        "phone_call": {
            "label_en": "Phone Call",
            "label_kh": "សំឡេងទូរស័ព្ទ",
            "voice": "km-KH-PisethNeural",
            "pitch": "+2Hz",
            "rate": "+4%",
            "fx": "highpass=f=360,lowpass=f=3200,acompressor=threshold=-18dB:ratio=4:attack=10:release=100",
        },
    }

    VOICES = {
        "Female (Sreymom)": "female",
        "Male (Piseth)": "male",
    }

    @classmethod
    def get_all_voice_profiles(cls, db=None) -> Dict[str, Dict[str, Any]]:
        """
        ទាញយកបញ្ជីសំឡេងទាំងអស់រួមមាន៖
        ១. សំឡេងគោល (Default Sreymom, Piseth, Inner Thought, Phone Call)
        ២. សំឡេងមនុស្សពិត ១០ ប្រភេទ (Human Presets)
        ៣. សំឡេងក្លូនផ្ទាល់ខ្លួនរបស់អ្នកប្រើប្រាស់ (User Cloned Voices ពី Database)
        """
        profiles = dict(cls.VOICE_PROFILES)

        # បន្ថែម 10 Human Presets
        for p_key, p_val in VoiceCloneEngine.HUMAN_PRESETS.items():
            profiles[p_key] = {
                "label_en": p_val.get("name_en", p_key),
                "label_kh": p_val.get("name", p_key),
                "voice": p_val.get("base_voice", "km-KH-PisethNeural"),
                "pitch": f"{p_val.get('pitch_shift', 0):+d}Hz",
                "rate": "+0%",
                "fx": p_val.get("fx", ""),
                "is_human": True,
            }

        # បន្ថែម User Cloned Voices ពី Database
        if db is not None:
            try:
                cloned = db.get_cloned_voices()
                for cv in cloned:
                    c_id = f"clone_{cv['id']}"
                    fx = cv.get("fx") or VoiceCloneEngine.build_acoustic_filter(
                        pitch_shift_hz=cv.get("pitch_shift", 0),
                        formant_shift=cv.get("formant_shift", 1.0),
                        warmth=cv.get("warmth", 1.2),
                        brightness=cv.get("brightness", 1.1),
                    )
                    profiles[c_id] = {
                        "label_en": f"👤 Clone: {cv['name']}",
                        "label_kh": f"👤 សំឡេងក្លូន: {cv['name']}",
                        "voice": cv.get("base_voice", "km-KH-PisethNeural"),
                        "pitch": f"{cv.get('pitch_shift', 0):+d}Hz",
                        "rate": "+0%",
                        "fx": fx,
                        "is_cloned": True,
                        "api_voice_id": cv.get("api_voice_id", ""),
                    }
            except Exception as e:
                print(f"[TTS Profiles Error] {e}")

        return profiles

    @staticmethod
    def _clean_text(text: str) -> str:
        """Uses shared canonicalizer so spoken TTS text matches displayed kh_text subtitle 100% word-for-word."""
        return normalize_dub_khmer_text(text)

    @staticmethod
    def _build_atempo_chain(speed: float) -> str:
        parts = []
        s = speed
        while s > 2.0:
            parts.append("atempo=2.0")
            s /= 2.0
        while s < 0.5:
            parts.append("atempo=0.5")
            s /= 0.5
        parts.append(f"atempo={s:.4f}")
        return ",".join(parts)

    async def _synth_async(self, text: str, voice: str, pitch: str, rate: str, out_mp3: str):
        communicate = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
        await communicate.save(out_mp3)

    def _synth_edge_tts(self, text: str, voice: str, pitch: str, rate: str, out_mp3: str):
        asyncio.run(
            self._synth_async(
                text=text,
                voice=voice,
                pitch=pitch,
                rate=rate,
                out_mp3=out_mp3,
            )
        )

    @staticmethod
    def _synth_google_khmer(text: str, out_mp3: str):
        url = (
            "https://translate.googleapis.com/translate_tts"
            f"?ie=UTF-8&client=tw-ob&tl=km&q={urllib.parse.quote(text[:200])}"
        )
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        Path(out_mp3).write_bytes(resp.content)

    def generate_fallback_clip(self, target_ms: int, out_wav: str):
        target_sec = max(0.1, target_ms / 1000.0)
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-threads", "1",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={target_sec:.4f}",
            "-af", f"apad,atrim=0:{target_sec:.4f}",
            "-ar", "44100", "-ac", "2",
            out_wav
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

    def generate_clip(self, text: str, profile_key: str, target_ms: int, out_wav: str, db=None, speed_mult: float = 1.0):
        target_ms = max(250, int(target_ms))
        speed_mult = max(0.5, min(2.5, float(speed_mult or 1.0)))
        cleaned = self._clean_text(text)
        if not cleaned:
            self.generate_fallback_clip(target_ms, out_wav)
            return

        # គាំទ្រសំឡេងចាស់ៗ
        if profile_key in ("km-KH-PisethNeural", "boy", "old_male"):
            profile_key = "male"
        elif profile_key == "distant_call":
            profile_key = "phone_call"

        # ពិនិត្យមើលសំឡេងក្នុង Voice Profiles (Default, Human Presets, Cloned Voices)
        all_profiles = self.get_all_voice_profiles(db)
        if profile_key in all_profiles:
            cfg = all_profiles[profile_key]
        elif profile_key in self.VOICE_PROFILES:
            cfg = self.VOICE_PROFILES[profile_key]
        else:
            cfg = self.VOICE_PROFILES["female"]

        # ប្រសិនបើជាសំឡេងក្លូនតាម ElevenLabs API
        api_voice_id = cfg.get("api_voice_id", "")
        if api_voice_id and db is not None:
            el_key = db.get_setting("elevenlabs_api_key", "").strip()
            if el_key:
                ok = VoiceCloneEngine.synthesize_with_elevenlabs(
                    text=cleaned,
                    api_key=el_key,
                    voice_id=api_voice_id,
                    out_wav=out_wav,
                )
                if ok and Path(out_wav).exists() and Path(out_wav).stat().st_size > 500:
                    return

        raw_mp3 = str(Path(out_wav).with_suffix(".raw.mp3"))
        trimmed_wav = str(Path(out_wav).with_suffix(".trim.wav"))
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)

        # គណនាប្រវែងអក្សរខ្មែរធៀបនឹង target_ms ដើម្បីបង្កើនល្បឿនអានស្វ័យប្រវត្តិ (Adaptive Speed) ពេលតួអង្គនិយាយលឿន
        kh_char_len = len(re.sub(r"\s+", "", cleaned))
        estimated_natural_ms = int(kh_char_len * 70) + 280

        base_rate_str = cfg.get("rate", "+0%")
        dynamic_rate = base_rate_str
        if estimated_natural_ms > target_ms:
            speed_boost = int(min(42, max(6, ((estimated_natural_ms - target_ms) / float(target_ms)) * 65)))
            dynamic_rate = f"+{speed_boost}%"

        stripped_punct = cleaned.strip("។៕?!.,;:'\"«»()[]{}-— ")
        candidates = [cleaned]
        if stripped_punct and stripped_punct != cleaned:
            candidates.append(stripped_punct)

        synthesized = False
        last_err = None

        kh_voices = [cfg["voice"], "km-KH-SreymomNeural" if cfg["voice"] != "km-KH-SreymomNeural" else "km-KH-PisethNeural"]
        for v_name in kh_voices:
            for candidate in candidates:
                for attempt in range(2):
                    try:
                        self._synth_edge_tts(
                            text=candidate,
                            voice=v_name,
                            pitch=cfg["pitch"],
                            rate=dynamic_rate,
                            out_mp3=raw_mp3,
                        )
                        if Path(raw_mp3).exists() and Path(raw_mp3).stat().st_size > 100:
                            synthesized = True
                            break
                    except Exception as err:
                        last_err = err
                        time.sleep(0.30 * (attempt + 1))
                if synthesized:
                    break
            if synthesized:
                break

        if not synthesized:
            try:
                self._synth_google_khmer(stripped_punct or cleaned, raw_mp3)
                if Path(raw_mp3).exists() and Path(raw_mp3).stat().st_size > 100:
                    synthesized = True
            except Exception as g_err:
                last_err = g_err

        if not synthesized:
            print(f"[TTS Warning] Khmer synthesis failed for '{cleaned}' ({last_err}), using timed fallback clip.")
            self.generate_fallback_clip(target_ms, out_wav)
            return

        # 1. Trim leading & trailing silence tightly down to 10ms (zero dead-air lag before actor speaks!)
        trim_cmd = [
            "ffmpeg", "-y", "-threads", "2", "-i", raw_mp3,
            "-af", "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-40dB,"
                   "areverse,silenceremove=start_periods=1:start_duration=0.01:start_threshold=-40dB,areverse",
            "-ar", "44100", "-ac", "2",
            trimmed_wav
        ]
        subprocess.run(trim_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

        if not Path(trimmed_wav).exists() or Path(trimmed_wav).stat().st_size < 200:
            subprocess.run(
                ["ffmpeg", "-y", "-threads", "2", "-i", raw_mp3, "-ar", "44100", "-ac", "2", trimmed_wav],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
            )

        try:
            probe = subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", trimmed_wav
            ], stderr=subprocess.DEVNULL, timeout=5.0, creationflags=CREATE_NO_WINDOW).decode().strip()
            actual_ms = max(50, int(float(probe) * 1000))
        except Exception:
            actual_ms = max(250, target_ms)

        # 2. Measure exact spoken duration and dynamically adjust atempo within [0.85x, 1.90x]
        #    so even fast dialogue finishes cleanly inside its exact [start_ms, end_ms] lip-sync window!
        safe_slot_ms = max(180, target_ms - 15)
        raw_ratio = (actual_ms / float(safe_slot_ms)) * speed_mult
        if raw_ratio > 1.01:
            speed = min(1.90, max(0.85, raw_ratio * 1.015))
        elif raw_ratio < 0.85:
            speed = max(0.85, min(1.90, speed_mult))
        else:
            speed = max(0.85, min(1.90, raw_ratio))

        filters = []
        if abs(speed - 1.0) > 0.012:
            filters.append(self._build_atempo_chain(speed))
        if cfg.get("fx"):
            filters.append(cfg["fx"])

        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        target_sec = target_ms / 1000.0
        fade_out_st = max(0.015, target_sec - 0.012)
        filters.append(
            f"afade=t=in:d=0.008,apad,atrim=0:{target_sec:.4f},afade=t=out:st={fade_out_st:.4f}:d=0.012"
        )

        final_cmd = [
            "ffmpeg", "-y", "-threads", "2", "-i", trimmed_wav,
            "-filter:a", ",".join(filters),
            "-ar", "44100", "-ac", "2",
            out_wav,
        ]
        subprocess.run(final_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

        Path(raw_mp3).unlink(missing_ok=True)
        Path(trimmed_wav).unlink(missing_ok=True)
        time.sleep(0.01)
