import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class VoiceCloneEngine:
    """
    ម៉ាស៊ីនក្លូនសំឡេងមនុស្សពិត (Voice Clone Engine) សម្រាប់ភាសាខ្មែរ៖
    ១. វិភាគលក្ខណៈសំឡេងដើម (Acoustic Pitch, Formant, Warmth & Timbre Analyzer)
    ២. ផ្លាស់ប្តូរពណ៌សំឡេងខ្មែរឲ្យដូចមនុស្សពិត ១០០% តាមរយៈ Formant Shifting, Chest Resonance & Acoustic EQ
    ៣. បង្កើតសំឡេងមនុស្សខ្មែរ ១០ ប្រភេទ (Human Presets) ជំនួសសំឡេង AI ធម្មតា
    ៤. គាំទ្រការប្រើប្រាស់ Cloud Zero-Shot Voice Clone API (ElevenLabs) ប្រសិនបើមាន API Key
    """

    HUMAN_PRESETS: Dict[str, Dict[str, Any]] = {
        "human_male_deep": {
            "name": "👤 លោកពូ (សំឡេងគ្រលរ-ធ្ងន់)",
            "name_en": "Warm Resonant Male (Deep)",
            "gender": "male",
            "base_voice": "km-KH-PisethNeural",
            "pitch_shift": -18,
            "formant_shift": 0.88,
            "warmth": 1.45,
            "brightness": 1.05,
            "tempo_rate": 0.98,
            "fx": "equalizer=f=180:t=q:w=1.2:g=+4.5dB,equalizer=f=320:t=q:w=1.5:g=+2.8dB,equalizer=f=3200:t=q:w=1.8:g=+1.5dB",
            "is_preset": 1,
        },
        "human_female_gentle": {
            "name": "👩 អ្នកមីង (សំឡេងទន់ភ្លន់-កក់ក្តៅ)",
            "name_en": "Warm Gentle Female",
            "gender": "female",
            "base_voice": "km-KH-SreymomNeural",
            "pitch_shift": -6,
            "formant_shift": 0.94,
            "warmth": 1.30,
            "brightness": 1.10,
            "tempo_rate": 0.96,
            "fx": "equalizer=f=240:t=q:w=1.3:g=+3.2dB,equalizer=f=2800:t=q:w=1.6:g=+2.2dB,lowpass=f=7500",
            "is_preset": 1,
        },
        "human_young_male": {
            "name": "👦 យុវជនរួសរាយ (សំឡេងក្មេងប្រុស)",
            "name_en": "Energetic Young Male",
            "gender": "male",
            "base_voice": "km-KH-PisethNeural",
            "pitch_shift": +14,
            "formant_shift": 1.12,
            "warmth": 0.90,
            "brightness": 1.35,
            "tempo_rate": 1.04,
            "fx": "equalizer=f=450:t=q:w=1.4:g=+2.0dB,equalizer=f=3800:t=q:w=1.5:g=+3.5dB",
            "is_preset": 1,
        },
        "human_sweet_female": {
            "name": "👧 យុវតីស្រស់ស្រាយ (សំឡេងក្មេងស្រី)",
            "name_en": "Bright Sweet Young Female",
            "gender": "female",
            "base_voice": "km-KH-SreymomNeural",
            "pitch_shift": +16,
            "formant_shift": 1.14,
            "warmth": 0.85,
            "brightness": 1.40,
            "tempo_rate": 1.03,
            "fx": "equalizer=f=500:t=q:w=1.5:g=+1.5dB,equalizer=f=4200:t=q:w=1.6:g=+4.0dB",
            "is_preset": 1,
        },
        "human_elder_male": {
            "name": "👴 លោកតា (សំឡេងចាស់-មានបទពិសោធន៍)",
            "name_en": "Wise Grandfather (Raspy)",
            "gender": "male",
            "base_voice": "km-KH-PisethNeural",
            "pitch_shift": -24,
            "formant_shift": 0.84,
            "warmth": 1.60,
            "brightness": 0.95,
            "tempo_rate": 0.90,
            "fx": "equalizer=f=150:t=q:w=1.0:g=+5.0dB,equalizer=f=800:t=q:w=2.0:g=-2.5dB,equalizer=f=2500:t=q:w=1.5:g=+1.8dB,aecho=0.6:0.7:35:0.25",
            "is_preset": 1,
        },
        "human_elder_female": {
            "name": "👵 លោកយាយ (សំឡេងចាស់-ចិត្តល្អ)",
            "name_en": "Kind Grandmother",
            "gender": "female",
            "base_voice": "km-KH-SreymomNeural",
            "pitch_shift": -14,
            "formant_shift": 0.90,
            "warmth": 1.35,
            "brightness": 0.90,
            "tempo_rate": 0.92,
            "fx": "equalizer=f=220:t=q:w=1.2:g=+3.8dB,equalizer=f=1200:t=q:w=1.8:g=-2.0dB,equalizer=f=2900:t=q:w=1.5:g=+1.5dB",
            "is_preset": 1,
        },
        "human_heroic_male": {
            "name": "🦸‍♂️ តួឯកប្រុស (សំឡេងអង់អាច-ម៉ឺងម៉ាត់)",
            "name_en": "Heroic Action Male Lead",
            "gender": "male",
            "base_voice": "km-KH-PisethNeural",
            "pitch_shift": -8,
            "formant_shift": 0.95,
            "warmth": 1.35,
            "brightness": 1.25,
            "tempo_rate": 1.02,
            "fx": "equalizer=f=160:t=q:w=1.2:g=+3.5dB,equalizer=f=2400:t=q:w=1.5:g=+2.8dB,acompressor=threshold=-16dB:ratio=3:attack=10:release=120",
            "is_preset": 1,
        },
        "human_romantic_female": {
            "name": "👸 តួឯកស្រី (សំឡេងមនោសញ្ចេតនា-ស្រទន់)",
            "name_en": "Emotional Romantic Female Lead",
            "gender": "female",
            "base_voice": "km-KH-SreymomNeural",
            "pitch_shift": +4,
            "formant_shift": 1.02,
            "warmth": 1.20,
            "brightness": 1.25,
            "tempo_rate": 0.97,
            "fx": "equalizer=f=280:t=q:w=1.3:g=+2.5dB,equalizer=f=3400:t=q:w=1.6:g=+3.0dB,aecho=0.7:0.75:40:0.2",
            "is_preset": 1,
        },
        "human_villain": {
            "name": "😈 តួចិត្តអាក្រក់ (សំឡេងគ្រលរ-កាច)",
            "name_en": "Dark Gritty Villain",
            "gender": "male",
            "base_voice": "km-KH-PisethNeural",
            "pitch_shift": -32,
            "formant_shift": 0.80,
            "warmth": 1.70,
            "brightness": 0.90,
            "tempo_rate": 0.94,
            "fx": "equalizer=f=120:t=q:w=1.0:g=+6.0dB,equalizer=f=450:t=q:w=1.6:g=+2.5dB,equalizer=f=3000:t=q:w=2.0:g=-3.0dB",
            "is_preset": 1,
        },
        "human_narrator": {
            "name": "🎙️ អ្នកអត្ថាធិប្បាយភាពយន្ត (សំឡេងស្ដង់ដារកុន)",
            "name_en": "Movie Narrator / Dubbing Master",
            "gender": "male",
            "base_voice": "km-KH-PisethNeural",
            "pitch_shift": -10,
            "formant_shift": 0.92,
            "warmth": 1.40,
            "brightness": 1.30,
            "tempo_rate": 0.99,
            "fx": "equalizer=f=140:t=q:w=1.2:g=+4.0dB,equalizer=f=2600:t=q:w=1.5:g=+3.2dB,acompressor=threshold=-15dB:ratio=4:attack=8:release=100",
            "is_preset": 1,
        },
    }

    @classmethod
    def analyze_audio_sample(cls, audio_path: str) -> Dict[str, Any]:
        """
        វិភាគឯកសារសំឡេងគំរូ (.wav, .mp3, .m4a) របស់មនុស្សពិត៖
        - រក Pitch ជាមធ្យម (Mean Frequency in Hz)
        - ប៉ាន់ស្មានភេទ (Gender: Male vs Female)
        - កម្រិតភាពកក់ក្តៅ (Chest Warmth) និងភាពភ្លឺ (Spectral Brightness)
        """
        p = Path(audio_path)
        if not p.exists() or p.stat().st_size < 1000:
            raise FileNotFoundError(f"ឯកសារសំឡេងគំរូមិនត្រឹមត្រូវ: {audio_path}")

        # បម្លែងជា 16kHz mono WAV បណ្តោះអាសន្នសម្រាប់វិភាគ
        tmp_wav = p.parent / f"_analyze_{p.stem}_{int(time.time())}.wav"
        try:
            conv_cmd = [
                "ffmpeg", "-y", "-i", str(p),
                "-t", "20",  # វិភាគត្រឹម 20 វិនាទីដំបូង
                "-ar", "16000", "-ac", "1",
                str(tmp_wav)
            ]
            subprocess.run(conv_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

            # ប្រើ ffprobe ឬ ffmpeg astats ដើម្បីវិភាគប្រេកង់
            cmd = [
                "ffmpeg", "-i", str(tmp_wav),
                "-af", "astats=metadata=1:reset=1",
                "-f", "null", "-"
            ]
            res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW)
            stats_out = res.stderr

            # គណនា Pitch តាមរយៈ autocorrelation សាមញ្ញលើ raw PCM
            pitch_hz = cls._estimate_pitch_hz(str(tmp_wav))
            gender = "female" if pitch_hz > 165 else "male"

            # គណនា Pitch Shift ធៀបនឹងសំឡេងស្តង់ដារ Edge-TTS
            # Base Female (Sreymom) ~ 210 Hz, Base Male (Piseth) ~ 125 Hz
            if gender == "female":
                base_ref = 210
                base_voice = "km-KH-SreymomNeural"
            else:
                base_ref = 125
                base_voice = "km-KH-PisethNeural"

            delta_hz = int(pitch_hz - base_ref)
            delta_hz = max(-35, min(35, delta_hz))

            # Formant shift factor
            formant_shift = round(math.pow(pitch_hz / max(80, base_ref), 0.35), 2)
            formant_shift = max(0.80, min(1.25, formant_shift))

            warmth = 1.35 if pitch_hz < 140 else 1.15
            brightness = 1.25 if pitch_hz > 180 else 1.10

            return {
                "detected_pitch_hz": round(pitch_hz, 1),
                "gender": gender,
                "base_voice": base_voice,
                "pitch_shift": delta_hz,
                "formant_shift": formant_shift,
                "warmth": warmth,
                "brightness": brightness,
                "tempo_rate": 1.0,
            }
        finally:
            tmp_wav.unlink(missing_ok=True)

    @classmethod
    def _estimate_pitch_hz(cls, mono_16k_wav: str) -> float:
        """
        គណនាប្រេកង់សំឡេងមនុស្សពិត (Fundamental Frequency F0)
        ដោយប្រើ Autocorrelation algorithm ល្បឿនលឿនលើ 16kHz audio buffer
        """
        try:
            import wave
            import struct

            with wave.open(mono_16k_wav, "rb") as wf:
                sample_rate = wf.getframerate()
                n_frames = min(sample_rate * 6, wf.getnframes())  # យក 6 វិនាទី
                raw_data = wf.readframes(n_frames)

            fmt = f"{len(raw_data)//2}h"
            samples = list(struct.unpack(fmt, raw_data))
            if not samples:
                return 150.0

            # ស្វែងរក Frame ណាដែលមានសំឡេងខ្លាំង (voiced frame)
            frame_size = 1024
            best_frame = None
            max_energy = 0
            for i in range(0, len(samples) - frame_size, 512):
                frame = samples[i:i + frame_size]
                energy = sum(abs(x) for x in frame)
                if energy > max_energy:
                    max_energy = energy
                    best_frame = frame

            if not best_frame or max_energy < 50000:
                return 150.0

            # Normalized Autocorrelation ក្នុងជួរ F0 មនុស្ស (70 Hz - 320 Hz)
            # lag = sample_rate / f
            min_lag = int(sample_rate / 320)  # ~50
            max_lag = int(sample_rate / 70)   # ~228

            best_lag = min_lag
            best_corr = -1
            n = len(best_frame)

            for lag in range(min_lag, max_lag):
                corr = 0
                norm_a = 0
                norm_b = 0
                for k in range(n - lag):
                    a = best_frame[k]
                    b = best_frame[k + lag]
                    corr += a * b
                    norm_a += a * a
                    norm_b += b * b
                denom = math.sqrt(norm_a * norm_b)
                if denom > 0:
                    r = corr / denom
                    if r > best_corr:
                        best_corr = r
                        best_lag = lag

            if best_corr > 0.35 and best_lag > 0:
                f0 = sample_rate / float(best_lag)
                return max(70.0, min(350.0, f0))
        except Exception as e:
            print(f"[VoiceClone] Pitch estimation fallback: {e}")
        return 145.0

    @classmethod
    def build_acoustic_filter(
        cls,
        pitch_shift_hz: int = 0,
        formant_shift: float = 1.0,
        warmth: float = 1.2,
        brightness: float = 1.1,
        fx_override: str = "",
    ) -> str:
        """
        បង្កើត FFmpeg Audio Filter Chain ដើម្បីកែសម្រួលពណ៌សំឡេង (Acoustic Timbre)
        ឲ្យក្លាយជាសំឡេងមនុស្សពិត៖
        - Chest Warmth: បង្កើន resonance ក្នុងកម្រិត 160-250 Hz
        - Throat / Articulation: គ្រប់គ្រងកម្រិត 800-1400 Hz
        - Vocal Clarity: បង្កើន presence ក្នុងកម្រិត 2800-3800 Hz
        - Sibilance De-essing: កាត់បន្ថយសំឡេងស្រួយរំខានលើស 7500 Hz
        - Studio Compression: រក្សាកម្រិតសំឡេងឲ្យរលូនដូចនៅក្នុង Studio
        """
        if fx_override:
            return fx_override

        filters = []

        # 1. Chest Body Warmth Resonance (resonance ទ្រូងមនុស្ស)
        if warmth > 1.05:
            gain_db = min(5.5, (warmth - 1.0) * 8.0)
            filters.append(f"equalizer=f=190:t=q:w=1.2:g=+{gain_db:.1f}dB")
        elif warmth < 0.95:
            cut_db = max(-4.0, (warmth - 1.0) * 8.0)
            filters.append(f"equalizer=f=200:t=q:w=1.2:g={cut_db:.1f}dB")

        # 2. Formant / Throat Tone (ជម្រៅបំពង់ក)
        if formant_shift < 0.95:
            # ສຽງជ្រៅ (Deeper male / mature resonance)
            filters.append("equalizer=f=350:t=q:w=1.4:g=+2.5dB,equalizer=f=1200:t=q:w=2.0:g=-1.8dB")
        elif formant_shift > 1.05:
            # សំឡេងខ្ចី (Younger / brighter throat)
            filters.append("equalizer=f=450:t=q:w=1.4:g=-1.5dB,equalizer=f=1400:t=q:w=1.8:g=+2.0dB")

        # 3. Speech Clarity & Presence (ភាពច្បាស់នៃអក្សរខ្មែរ)
        if brightness > 1.05:
            bright_gain = min(5.0, (brightness - 1.0) * 7.5)
            filters.append(f"equalizer=f=3300:t=q:w=1.5:g=+{bright_gain:.1f}dB")
        elif brightness < 0.95:
            bright_cut = max(-4.0, (brightness - 1.0) * 6.0)
            filters.append(f"equalizer=f=3500:t=q:w=1.5:g={bright_cut:.1f}dB")

        # 4. De-essing / Anti-harshness filter (កាត់បន្ថយភាពរឹងរបស់ AI robot)
        filters.append("lowpass=f=8200,highpass=f=70")

        # 5. Studio Vocal Leveler (Dynamic Studio Compressor)
        filters.append("acompressor=threshold=-17dB:ratio=3:attack=12:release=110")

        return ",".join(filters)

    @classmethod
    def synthesize_with_elevenlabs(
        cls,
        text: str,
        api_key: str,
        voice_id: str,
        out_wav: str,
    ) -> bool:
        """
        បង្កើតសំឡេងតាមរយៈ Cloud Voice Clone (ElevenLabs Instant Voice Clone API)
        ជាមួយ Eleven Multilingual v2 Model
        """
        if not api_key or not voice_id:
            return False

        try:
            import requests

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.50,
                    "similarity_boost": 0.85,
                    "style": 0.15,
                    "use_speaker_boost": True,
                },
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=25)
            if resp.status_code == 200 and len(resp.content) > 500:
                tmp_mp3 = Path(out_wav).with_suffix(".el.mp3")
                tmp_mp3.write_bytes(resp.content)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(tmp_mp3), "-ar", "44100", "-ac", "2", out_wav],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
                tmp_mp3.unlink(missing_ok=True)
                return True
        except Exception as e:
            print(f"[ElevenLabs Clone Error] {e}")
        return False
