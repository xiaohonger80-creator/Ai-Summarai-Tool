# -*- coding: utf-8 -*-
"""
core/engine_registry.py
Extensible Dynamic Engine Registry organizing all AI capabilities into 4 functional categories:
  1. extraction: Speech & Hard-Subtitle Extraction (FunASR, WhisperX, PaddleOCR, Hybrid, whisper.cpp)
  2. separation: Vocal & BGM/SFX Stem Separation (Demucs htdemucs, UVR5 ONNX, FFmpeg Vocal Suppression, Ducking)
  3. dubbing: AI Dubbing & Voice Cloning (Edge-TTS, GPT-SoVITS, Fish-Speech, Khmer-XTTS / F5-TTS Khmer, Meta MMS-TTS Khmer)
  4. translation: Context-Aware Translation & Story Intelligence (Story Context Mode, Fast Batch Mode, AI Story Recap)
Preserves 100% of existing option keys while auto-populating UI dropdowns and Smart Workflow Presets.
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional


@dataclass
class EngineDescriptor:
    key: str
    label: str
    category: str
    hardware_tag: str = "[CPU Safe]"
    supports_voice_clone: bool = False
    is_offline: bool = True
    fallback_key: str = ""


class EngineRegistry:
    """
    Central Registry for all Extraction, Separation, Dubbing/Voice-Cloning, and Translation engines.
    Allows non-destructive registration of new engines while keeping legacy keys 100% valid.
    """

    _ENGINES: Dict[str, List[EngineDescriptor]] = {
        "extraction": [
            EngineDescriptor(
                key="Audio ASR (FunASR SenseVoice)",
                label="Audio ASR (FunASR SenseVoice)",
                category="extraction",
                hardware_tag="[GPU/CPU]",
                fallback_key="whisper.cpp (Ultra-Fast CPU / Low-VRAM Fallback)",
            ),
            EngineDescriptor(
                key="Audio ASR + Speaker ID (WhisperX)",
                label="Audio ASR + Speaker ID (WhisperX)",
                category="extraction",
                hardware_tag="[GPU/CPU]",
                fallback_key="whisper.cpp (Ultra-Fast CPU / Low-VRAM Fallback)",
            ),
            EngineDescriptor(
                key="Hard-Subtitle OCR (PaddleOCR)",
                label="Hard-Subtitle OCR (PaddleOCR)",
                category="extraction",
                hardware_tag="[CPU Safe]",
            ),
            EngineDescriptor(
                key="Hybrid (OCR Primary + ASR Check)",
                label="Hybrid (OCR Primary + ASR Check)",
                category="extraction",
                hardware_tag="[Recommended]",
            ),
            EngineDescriptor(
                key="whisper.cpp (Ultra-Fast CPU / Low-VRAM Fallback)",
                label="whisper.cpp (Ultra-Fast CPU / Low-VRAM Fallback)",
                category="extraction",
                hardware_tag="[CPU Safe / Offline]",
            ),
        ],
        "separation": [
            EngineDescriptor(
                key="Demucs (htdemucs - True Vocal & BGM/SFX Stem Separation)",
                label="Demucs (htdemucs - True Vocal & BGM/SFX Stem Separation)",
                category="separation",
                hardware_tag="[Stems / BGM+SFX]",
                fallback_key="FFmpeg Vocal Suppression",
            ),
            EngineDescriptor(
                key="UVR5 Instrumental Keep",
                label="UVR5 Instrumental Keep",
                category="separation",
                hardware_tag="[ONNX]",
                fallback_key="FFmpeg Vocal Suppression",
            ),
            EngineDescriptor(
                key="FFmpeg Vocal Suppression",
                label="FFmpeg Vocal Suppression",
                category="separation",
                hardware_tag="[CPU Safe]",
            ),
            EngineDescriptor(
                key="Duck Original Audio -18dB",
                label="Duck Original Audio -18dB",
                category="separation",
                hardware_tag="[CPU Safe]",
            ),
        ],
        "dubbing": [
            EngineDescriptor(
                key="Edge-TTS (Fast Online/Fallback)",
                label="Edge-TTS (Fast Online/Fallback)",
                category="dubbing",
                hardware_tag="[Khmer / Fast]",
                supports_voice_clone=False,
                is_offline=False,
            ),
            EngineDescriptor(
                key="Khmer-XTTS / F5-TTS Khmer (Local Khmer Voice Cloning)",
                label="Khmer-XTTS / F5-TTS Khmer (Local Khmer Voice Cloning)",
                category="dubbing",
                hardware_tag="[Voice Clone / Khmer]",
                supports_voice_clone=True,
                fallback_key="Edge-TTS (Fast Online/Fallback)",
            ),
            EngineDescriptor(
                key="GPT-SoVITS (Local Voice Clone)",
                label="GPT-SoVITS (Local Voice Clone)",
                category="dubbing",
                hardware_tag="[Voice Clone / GPU]",
                supports_voice_clone=True,
                fallback_key="Edge-TTS (Fast Online/Fallback)",
            ),
            EngineDescriptor(
                key="Fish-Speech (Local Natural TTS)",
                label="Fish-Speech (Local Natural TTS)",
                category="dubbing",
                hardware_tag="[Voice Clone / GPU]",
                supports_voice_clone=True,
                fallback_key="Edge-TTS (Fast Online/Fallback)",
            ),
            EngineDescriptor(
                key="Meta MMS-TTS Khmer (facebook/mms-tts-khm)",
                label="Meta MMS-TTS Khmer (facebook/mms-tts-khm)",
                category="dubbing",
                hardware_tag="[Offline / Khmer]",
                supports_voice_clone=False,
                fallback_key="Edge-TTS (Fast Online/Fallback)",
            ),
        ],
        "translation": [
            EngineDescriptor(
                key="Story Context Mode (Plot + Character Glossary)",
                label="Story Context Mode (Plot + Character Glossary)",
                category="translation",
                hardware_tag="[2-Pass Context]",
            ),
            EngineDescriptor(
                key="Fast Batch Mode (8 Lines/Batch)",
                label="Fast Batch Mode (8 Lines/Batch)",
                category="translation",
                hardware_tag="[Fast]",
            ),
            EngineDescriptor(
                key="AI Story Recap (PySceneDetect + Narration)",
                label="AI Story Recap (PySceneDetect + Narration)",
                category="translation",
                hardware_tag="[Recap Script]",
            ),
        ],
    }

    SMART_WORKFLOW_PRESETS: Dict[str, Dict[str, Any]] = {
        "Chinese Drama -> Khmer Dubbing (Demucs + Story Context + Khmer TTS)": {
            "extraction_engine": "Hybrid (OCR Primary + ASR Check)",
            "translation_strategy": "Story Context Mode (Plot + Character Glossary)",
            "dub_mode": "AI Movie Dubbing (Replace Dialogue)",
            "vocal_removal_engine": "Demucs (htdemucs - True Vocal & BGM/SFX Stem Separation)",
            "tts_engine": "Edge-TTS (Fast Online/Fallback)",
            "bottom_cover_box": True,
            "text_fx_enabled": True,
        },
        "Zero-Shot Character Voice Clone Dubbing (WhisperX + GPT-SoVITS/Fish-Speech)": {
            "extraction_engine": "Audio ASR + Speaker ID (WhisperX)",
            "translation_strategy": "Story Context Mode (Plot + Character Glossary)",
            "dub_mode": "AI Movie Dubbing (Replace Dialogue)",
            "vocal_removal_engine": "Demucs (htdemucs - True Vocal & BGM/SFX Stem Separation)",
            "tts_engine": "Khmer-XTTS / F5-TTS Khmer (Local Khmer Voice Cloning)",
            "bottom_cover_box": True,
            "text_fx_enabled": True,
        },
        "AI Movie Recap & Narration (PySceneDetect + LLM Recap + Voice)": {
            "extraction_engine": "Hybrid (OCR Primary + ASR Check)",
            "translation_strategy": "Story Context Mode (Plot + Character Glossary)",
            "dub_mode": "AI Story Recap (Auto Scene Cut + Narration)",
            "vocal_removal_engine": "Duck Original Audio -18dB",
            "tts_engine": "Edge-TTS (Fast Online/Fallback)",
            "scene_auto_cut": True,
            "anti_cr_zoom": True,
        },
        "Low-Spec / CPU-Only Safe Mode (whisper.cpp + FFmpeg + Edge-TTS)": {
            "extraction_engine": "whisper.cpp (Ultra-Fast CPU / Low-VRAM Fallback)",
            "translation_strategy": "Fast Batch Mode (8 Lines/Batch)",
            "dub_mode": "AI Movie Dubbing (Replace Dialogue)",
            "vocal_removal_engine": "FFmpeg Vocal Suppression",
            "tts_engine": "Edge-TTS (Fast Online/Fallback)",
            "hardware_profile": "low",
        },
        "Custom (Manual Category Selection)": {},
    }

    EMOTION_TAGS: List[str] = ["normal", "whisper", "laughing", "angry", "sad"]

    @classmethod
    def register_engine(cls, descriptor: EngineDescriptor) -> None:
        cat_list = cls._ENGINES.setdefault(descriptor.category, [])
        for idx, existing in enumerate(cat_list):
            if existing.key == descriptor.key:
                cat_list[idx] = descriptor
                return
        cat_list.append(descriptor)

    @classmethod
    def list_engines(cls, category: str) -> List[str]:
        return [d.key for d in cls._ENGINES.get(category, [])]

    @classmethod
    def list_descriptors(cls, category: str) -> List[EngineDescriptor]:
        return list(cls._ENGINES.get(category, []))

    @classmethod
    def get_descriptor(cls, category: str, key_or_label: str) -> Optional[EngineDescriptor]:
        k = (key_or_label or "").strip().lower()
        for d in cls._ENGINES.get(category, []):
            if d.key.lower() == k or d.label.lower() == k or d.key.lower() in k:
                return d
        return None

    @classmethod
    def is_voice_cloning_engine(cls, engine_name: str) -> bool:
        desc = cls.get_descriptor("dubbing", engine_name)
        if desc is not None:
            return desc.supports_voice_clone
        en = (engine_name or "").lower()
        return any(tok in en for tok in ("sovits", "fish", "xtts", "f5-tts", "clone"))

    @classmethod
    def list_smart_presets(cls) -> List[str]:
        return list(cls.SMART_WORKFLOW_PRESETS.keys())

    @classmethod
    def get_preset_config(cls, preset_name: str) -> Dict[str, Any]:
        return dict(cls.SMART_WORKFLOW_PRESETS.get(preset_name, {}))
