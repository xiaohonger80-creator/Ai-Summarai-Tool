import json
import os
from pathlib import Path
from typing import Dict, Any

SETTINGS_FILE = Path("data/subtitle_settings.json")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "extraction_engine": "Hybrid (OCR Primary + ASR Check)",
    "translation_strategy": "Story Context Mode (Movie/Drama Glossary)",
    "ai_provider": "100% Local Offline (Ollama)",
    "model_name": "qwen2.5:7b",
    "ollama_url": "http://localhost:11434",
    "cloud_api_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "cloud_api_key": "",
    "target_language": "Khmer (ភាសាខ្មែរ - Natural Spoken)",
    "ocr_confidence_threshold": 0.75,
    "ocr_crop_bottom_pct": 0.35,
    "sample_fps": 2.0,
    "batch_size": 8,
}


class SubtitleSettings:
    """Manages persistent JSON settings for the Subtitle & Translation Studio."""

    @classmethod
    def load(cls) -> Dict[str, Any]:
        if not SETTINGS_FILE.exists():
            cls.save(DEFAULT_SETTINGS)
            return dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except Exception:
            return dict(DEFAULT_SETTINGS)

    @classmethod
    def save(cls, settings: Dict[str, Any]):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Settings Save Error] {e}")

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        return cls.load().get(key, default)

    @classmethod
    def set(cls, key: str, value: Any):
        cfg = cls.load()
        cfg[key] = value
        cls.save(cfg)
