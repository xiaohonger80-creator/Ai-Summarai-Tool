# -*- coding: utf-8 -*-
"""
config/settings.py
Persistent JSON configuration manager for the All-in-One AI Video, Dubbing, Recap & FX Studio.
Includes hardware_profile ("high" | "low"), preferred_encoder, cache_dir, speaker_map, and recent_projects.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List

SETTINGS_FILE = Path("data/subtitle_settings.json")

DEFAULT_SETTINGS: Dict[str, Any] = {
    # Hardware & Performance Profile
    "hardware_profile": "high",  # "high" | "low"
    "preferred_encoder": "auto",  # "auto" | "h264_nvenc" | "h264_amf" | "h264_qsv" | "libx264"
    "cache_dir": "data/cache/tts",
    "recent_projects": [],
    "auto_split_minutes": 0,  # 0 = Off, 10, 15, 20
    # Tab 1: Extraction & Translation
    "extraction_engine": "Hybrid (OCR Primary + ASR Check)",
    "translation_strategy": "Story Context Mode (Plot + Character Glossary)",
    "ai_provider": "100% Local Offline (Ollama)",
    "model_name": "qwen2.5:7b",
    "ollama_url": "http://localhost:11434",
    "cloud_api_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "cloud_api_key": "",
    "target_language": "Khmer (ភាសាខ្មែរ)",
    "ocr_confidence_threshold": 0.75,
    "ocr_crop_bottom_pct": 0.30,
    "sample_fps": 2.0,
    "batch_size": 8,
    # Tab 2: Story Recap & Dubbing
    "dub_mode": "AI Movie Dubbing (Replace Dialogue)",
    "scene_auto_cut": False,
    "anti_cr_mirror": False,
    "anti_cr_zoom": True,
    "recap_target_minutes": 3.0,
    "vocal_removal_engine": "FFmpeg Vocal Suppression",
    "bgm_duck_db": -16.0,
    "tts_engine": "Edge-TTS (Fast Online/Fallback)",
    "gpt_sovits_url": "http://127.0.0.1:9880",
    "fish_speech_url": "http://127.0.0.1:8080",
    "default_voice": "km-KH-SreymomNeural",
    "auto_rate_sync": True,
    "speaker_map": {
        "SPEAKER_00": {"voice": "km-KH-PisethNeural", "rate": "+0%", "pitch": "+0Hz"},
        "SPEAKER_01": {"voice": "km-KH-SreymomNeural", "rate": "+0%", "pitch": "+0Hz"},
        "NARRATOR": {"voice": "km-KH-PisethNeural", "rate": "+5%", "pitch": "-2Hz"},
    },
    # Tab 3: Text FX, Mask & LUTs
    "text_fx_enabled": True,
    "text_fx_style": "Static Styled Subtitles",
    "bottom_cover_box": True,
    "font_family": "Noto Sans Khmer",
    "font_size": 46,
    "text_color": "#FFFFFF",
    "outline_color": "#000000",
    "text_speed": 1.0,
    "mask_enabled": False,
    "mask_engine": "Shape Mask - Portrait/Circle",
    "mask_bg_mode": "Blur BG",
    "mask_blur_radius": 24,
    "lut_enabled": False,
    "lut_preset": "Cinematic_Teal_Orange.cube",
    "lut_intensity": 80,
    "luts_dir": "assets/luts",
    "use_gpu": True,
    "ui_language": "km",
}


class SubtitleSettings:
    """Manages persistent JSON settings for the All-in-One AI Video, Dubbing, Recap & FX Studio."""

    @classmethod
    def _get_settings_path(cls) -> Path:
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            return SETTINGS_FILE
        except Exception:
            appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or "."
            p = Path(appdata) / "AiSummarai" / "subtitle_settings.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            return p

    @classmethod
    def load(cls) -> Dict[str, Any]:
        path = cls._get_settings_path()
        if not path.exists():
            cls.save(DEFAULT_SETTINGS)
            return dict(DEFAULT_SETTINGS)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except Exception:
            return dict(DEFAULT_SETTINGS)

    @classmethod
    def save(cls, settings: Dict[str, Any]) -> None:
        path = cls._get_settings_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Settings Save Error] {e}")

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        return cls.load().get(key, default if default is not None else DEFAULT_SETTINGS.get(key))

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        cfg = cls.load()
        cfg[key] = value
        cls.save(cfg)

    @classmethod
    def add_recent_project(cls, project_path: str) -> List[str]:
        cfg = cls.load()
        recents: List[str] = list(cfg.get("recent_projects") or [])
        norm_p = str(Path(project_path).resolve())
        if norm_p in recents:
            recents.remove(norm_p)
        recents.insert(0, norm_p)
        cfg["recent_projects"] = recents[:15]
        cls.save(cfg)
        return cfg["recent_projects"]


StudioSettings = SubtitleSettings
