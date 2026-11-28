# -*- coding: utf-8 -*-
"""
core/engine_factory.py
Central Factory instantiating user-selected Extractor, Translator, Recap/Dubber,
and VideoFX modules using the Strategy & Factory Patterns + EngineRegistry & LegacyCompatibilityAdapter.
"""

from typing import Dict, Any, Optional, Callable

from core.engine_registry import EngineRegistry
from core.legacy_bridge import LegacyCompatibilityAdapter

from core.extractors.base import BaseExtractor
from core.extractors.asr_funasr import FunASRExtractor
from core.extractors.asr_whisper import WhisperExtractor
from core.extractors.asr_whisper_cpp import WhisperCppExtractor
from core.extractors.ocr_paddle import PaddleOCRExtractor
from core.extractors.hybrid_extractor import HybridExtractor

from core.translators.base import BaseTranslator
from core.translators.providers import UnifiedLLMClient
from core.translators.fast_batch import FastBatchTranslator
from core.translators.story_context import StoryContextTranslator

from core.recap_dubbing.scene_cutter import SceneCutter
from core.recap_dubbing.recap_writer import RecapWriter
from core.recap_dubbing.vocal_separator import VocalSeparator
from core.recap_dubbing.tts_dubber import TTSDubber

from core.videofx.lut_engine import LUTEngine
from core.videofx.text_animator import TextAnimator
from core.videofx.mask_engine import VideoMaskEngine
from core.videofx.compositor import MasterCompositor


class EngineFactory:
    """
    Central Factory creating concrete Extractor, Translator, RecapWriter, VocalSeparator,
    TTSDubber, VideoMaskEngine, and MasterCompositor strategy instances.
    """

    @classmethod
    def create_extractor(cls, engine_name: str, settings: Dict[str, Any] = None) -> BaseExtractor:
        s = settings or {}
        resolved = LegacyCompatibilityAdapter.resolve_engine_key(
            engine_name,
            "Hybrid (OCR Primary + ASR Check)",
        ).lower()
        if "whisper.cpp" in resolved or "low-vram" in resolved:
            return WhisperCppExtractor(model_size="base")
        elif "funasr" in resolved:
            return FunASRExtractor()
        elif "whisper" in resolved:
            model_sz = "base" if s.get("hardware_profile") == "low" else "large-v3"
            return WhisperExtractor(model_size=model_sz)
        elif "ocr" in resolved and "hybrid" not in resolved:
            return PaddleOCRExtractor(
                confidence_threshold=float(s.get("ocr_confidence_threshold", 0.75)),
                sample_fps=float(s.get("sample_fps", 2.0)),
            )
        else:
            return HybridExtractor(
                confidence_threshold=float(s.get("ocr_confidence_threshold", 0.75)),
                sample_fps=float(s.get("sample_fps", 2.0)),
            )

    @classmethod
    def create_llm_client(
        cls,
        provider_name: str,
        model_name: str,
        settings: Dict[str, Any] = None,
    ) -> UnifiedLLMClient:
        s = settings or {}
        return UnifiedLLMClient(
            provider=provider_name,
            model_name=model_name,
            ollama_url=s.get("ollama_url", "http://localhost:11434"),
            cloud_api_url=s.get("cloud_api_url", ""),
            cloud_api_key=s.get("cloud_api_key", ""),
        )

    @classmethod
    def create_translator(
        cls,
        strategy_name: str,
        provider_name: str,
        model_name: str,
        settings: Dict[str, Any] = None,
    ) -> BaseTranslator:
        s = settings or {}
        client = cls.create_llm_client(provider_name, model_name, s)
        batch_size = int(s.get("batch_size", 8))

        if "story" in (strategy_name or "").lower():
            return StoryContextTranslator(client=client, batch_size=batch_size)
        else:
            return FastBatchTranslator(client=client, batch_size=batch_size)

    @classmethod
    def create_recap_writer(cls, settings: Dict[str, Any] = None) -> RecapWriter:
        s = settings or {}
        client = cls.create_llm_client(
            provider_name=s.get("ai_provider", "100% Local Offline (Ollama)"),
            model_name=s.get("model_name", "qwen2.5:7b"),
            settings=s,
        )
        return RecapWriter(client=client, target_minutes=float(s.get("recap_target_minutes", 3.0)))

    @classmethod
    def create_vocal_separator(
        cls,
        settings: Dict[str, Any] = None,
        fallback_notice_cb: Optional[Callable[[str], None]] = None,
    ) -> VocalSeparator:
        s = settings or {}
        return VocalSeparator(
            mode=s.get("vocal_removal_engine", "FFmpeg Vocal Suppression"),
            duck_db=float(s.get("bgm_duck_db", -18.0)),
            fallback_notice_cb=fallback_notice_cb,
        )

    @classmethod
    def create_tts_dubber(
        cls,
        settings: Dict[str, Any] = None,
        fallback_notice_cb: Optional[Callable[[str], None]] = None,
    ) -> TTSDubber:
        s = settings or {}
        return TTSDubber(
            engine_name=s.get("tts_engine", "Edge-TTS (Fast Online/Fallback)"),
            voice_id=s.get("default_voice", "km-KH-SreymomNeural"),
            auto_rate_sync=bool(s.get("auto_rate_sync", True)),
            gpt_sovits_url=s.get("gpt_sovits_url", "http://127.0.0.1:9880"),
            fish_speech_url=s.get("fish_speech_url", "http://127.0.0.1:8080"),
            cache_dir=s.get("cache_dir", "data/cache/tts"),
            speaker_map=s.get("speaker_map", {}),
            ref_voice_wav=s.get("ref_voice_wav", ""),
            ref_voice_transcript=s.get("ref_voice_transcript", ""),
            fallback_notice_cb=fallback_notice_cb,
        )

    @classmethod
    def create_mask_engine(cls, settings: Dict[str, Any] = None) -> VideoMaskEngine:
        s = settings or {}
        return VideoMaskEngine(
            engine_name=s.get("mask_engine", "Shape Mask - Portrait/Circle"),
            bg_mode=s.get("mask_bg_mode", "Blur BG"),
            blur_radius=int(s.get("mask_blur_radius", 24)),
        )

    @classmethod
    def create_compositor(cls) -> MasterCompositor:
        return MasterCompositor(lut_engine=LUTEngine())
