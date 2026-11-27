import subprocess
from pathlib import Path
from typing import Dict, List, Optional

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class SFXEngine:
    SFX_DIR = Path("data/sfx_library")

    # Mapping of 5 detected Khmer dialogue emotions -> matching SFX preset & smart ducked volume
    EMOTION_SFX_MAP: Dict[str, Dict] = {
        "dramatic_shock": {"preset": "boom", "volume": 0.44, "label": "💥 Shock (Boom)"},
        "sad_emotional": {"preset": "heartbeat", "volume": 0.38, "label": "💓 Sad (Heartbeat)"},
        "action_fight": {"preset": "whoosh", "volume": 0.42, "label": "💨 Action (Whoosh)"},
        "funny_awkward": {"preset": "alert", "volume": 0.36, "label": "⚠️ Funny/Awkward (Alert)"},
        "romantic": {"preset": "ding", "volume": 0.34, "label": "🔔 Romantic (Ding)"},
    }

    PRESETS: Dict[str, Dict] = {
        "whoosh": {
            "label_kh": "💨 Whoosh (ហោះកាត់)",
            "label_en": "💨 Whoosh",
            "cmd": "anoisesrc=d=0.45:c=pink:a=0.6,bandpass=f=900:w=700,afade=t=in:d=0.12,afade=t=out:st=0.22:d=0.23",
        },
        "boom": {
            "label_kh": "💥 Boom (ភ្ញាក់ផ្អើល)",
            "label_en": "💥 Dramatic Boom",
            "cmd": "aevalsrc='0.8*sin(2*PI*55*t)*exp(-4*t)+0.4*sin(2*PI*110*t)*exp(-6*t)':d=0.9,afade=t=out:st=0.5:d=0.4",
        },
        "ding": {
            "label_kh": "🔔 Ding (នឹកឃើញ)",
            "label_en": "🔔 Idea Ding",
            "cmd": "aevalsrc='0.5*sin(2*PI*1318*t)*exp(-4*t)+0.3*sin(2*PI*2637*t)*exp(-6*t)':d=0.65",
        },
        "pop": {
            "label_kh": "🫧 Pop (លោតចេញ)",
            "label_en": "🫧 Bubble Pop",
            "cmd": "aevalsrc='0.7*sin(2*PI*(300+1800*t)*t)*exp(-28*t)':d=0.18",
        },
        "heartbeat": {
            "label_kh": "💓 Heartbeat (បេះដូងលោត)",
            "label_en": "💓 Heartbeat",
            "cmd": "aevalsrc='0.8*sin(2*PI*60*t)*exp(-14*t)+0.6*sin(2*PI*60*(t-0.25))*exp(-14*max(0,t-0.25))*gte(t,0.25)':d=0.8",
        },
        "alert": {
            "label_kh": "⚠️ Alert (រន្ធត់/ប្រុងប្រយ័ត្ន)",
            "label_en": "⚠️ Tension Alert",
            "cmd": "aevalsrc='0.45*sin(2*PI*440*t)+0.45*sin(2*PI*466*t)':d=0.6,afade=t=in:d=0.05,afade=t=out:st=0.35:d=0.25",
        },
    }

    @classmethod
    def get_preset_wav(cls, key: str) -> str:
        """បង្កើតឯកសារ .wav សំឡេង Effect ដោយស្វ័យប្រវត្តិ (ប្រើទំហំត្រឹម 50KB)"""
        cls.SFX_DIR.mkdir(parents=True, exist_ok=True)
        out_wav = cls.SFX_DIR / f"{key}.wav"
        if out_wav.exists() and out_wav.stat().st_size > 256:
            return str(out_wav)

        cfg = cls.PRESETS.get(key, cls.PRESETS["ding"])
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", cfg["cmd"], "-ar", "44100", "-ac", "2", str(out_wav)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        return str(out_wav)

    @classmethod
    def auto_match_emotion_sfx(
        cls,
        segments: List[Dict],
        db,
        project_id: int,
        translator=None,
        min_gap_ms: int = 3500,
        replace_auto: bool = True,
        progress_cb=None,
    ) -> List[Dict]:
        """
        AI Emotion SFX & BGM Auto-Matcher:
        Analyzes each Khmer dialogue segment's emotional tone (`dramatic_shock`, `sad_emotional`,
        `action_fight`, `funny_awkward`, `romantic`) and places matching sound effects
        (`boom.wav`, `heartbeat.wav`, `whoosh.wav`, `alert.wav`, `ding.wav`) onto the timeline
        `sfx_events` track with smart spacing and gentle volume ducking so effects never drown
        out the Khmer voiceover.
        """
        if not segments or not db or not project_id:
            return []

        if progress_cb:
            progress_cb(15, "🎵 កំពុងវិភាគអារម្មណ៍សាច់រឿង (Shock / Sad / Action / Funny / Romantic)...")

        if translator is None:
            from core.translator import ZHtoKHTranslator
            translator = ZHtoKHTranslator(api_key="", base_url="google-free", model="google-free")

        emotion_map = translator.classify_segment_emotions(segments)

        if replace_auto:
            existing_sfx = db.get_sfx_events(project_id)
            for ex in existing_sfx:
                if str(ex.get("name") or "").startswith("[Auto]"):
                    db.delete_sfx_event(ex["id"])

        placed = []
        last_placed_ms = -min_gap_ms
        total = max(1, len(segments))

        for idx, seg in enumerate(segments):
            sid = int(seg.get("id") or idx)
            emo = emotion_map.get(sid)
            if not emo or emo not in cls.EMOTION_SFX_MAP:
                continue

            start_ms = max(0, int(seg.get("start_ms", 0)) - 120)
            if start_ms - last_placed_ms < min_gap_ms:
                continue

            spec = cls.EMOTION_SFX_MAP[emo]
            wav_path = cls.get_preset_wav(spec["preset"])
            ev_name = f"[Auto] {spec['label']}"
            vol = float(spec["volume"])

            ev_id = db.add_sfx_event(project_id, ev_name, start_ms, wav_path, volume=vol)
            placed.append({
                "id": ev_id,
                "project_id": project_id,
                "name": ev_name,
                "emotion": emo,
                "preset": spec["preset"],
                "start_ms": start_ms,
                "audio_path": wav_path,
                "volume": vol,
            })
            last_placed_ms = start_ms

            if progress_cb and idx % 10 == 0:
                progress_cb(25 + int(((idx + 1) / total) * 70), f"🎵 បានដាក់ Emotion SFX ចំនួន {len(placed)} ចំណុច...")

        # Ensure smart Auto-Ducking is enabled so BGM & SFX never overpower Khmer speech
        try:
            db.update_project_edits(project_id, auto_ducking=1)
        except Exception:
            pass

        if progress_cb:
            progress_cb(100, f"🎵 បានដាក់ Emotion SFX ស្វ័យប្រវត្តិចំនួន {len(placed)} ចំណុចរួចរាល់!")
        return placed
