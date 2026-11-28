from typing import Dict, Any, Tuple

from core.extractors.base import BaseExtractor
from core.extractors.asr_funasr import FunASRExtractor
from core.extractors.asr_whisper import WhisperExtractor
from core.extractors.ocr_paddle import PaddleOCRExtractor
from core.extractors.hybrid_extractor import HybridExtractor

from core.translators.base import BaseTranslator
from core.translators.providers import UnifiedLLMClient
from core.translators.fast_batch import FastBatchTranslator
from core.translators.story_context import StoryContextTranslator


class EngineFactory:
    """
    Factory creating concrete Extractor & Translator strategy instances
    based on user-selected UI parameters.
    """

    @classmethod
    def create_extractor(cls, engine_name: str, settings: Dict[str, Any] = None) -> BaseExtractor:
        s = settings or {}
        en = engine_name.lower()
        if "funasr" in en:
            return FunASRExtractor()
        elif "whisper" in en:
            return WhisperExtractor(model_size="large-v3")
        elif "ocr" in en and "hybrid" not in en:
            return PaddleOCRExtractor(
                confidence_threshold=float(s.get("ocr_confidence_threshold", 0.75)),
                sample_fps=float(s.get("sample_fps", 2.0)),
            )
        else:
            # Hybrid default
            return HybridExtractor(
                confidence_threshold=float(s.get("ocr_confidence_threshold", 0.75)),
                sample_fps=float(s.get("sample_fps", 2.0)),
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
        client = UnifiedLLMClient(
            provider=provider_name,
            model_name=model_name,
            ollama_url=s.get("ollama_url", "http://localhost:11434"),
            cloud_api_url=s.get("cloud_api_url", ""),
            cloud_api_key=s.get("cloud_api_key", ""),
        )
        batch_size = int(s.get("batch_size", 8))

        if "story" in strategy_name.lower():
            return StoryContextTranslator(client=client, batch_size=batch_size)
        else:
            return FastBatchTranslator(client=client, batch_size=batch_size)
