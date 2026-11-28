import threading
from typing import Dict, Any, List

try:
    from PyQt5.QtCore import QThread, pyqtSignal as Signal
except ImportError:
    from PySide6.QtCore import QThread, Signal

from core.engine_factory import EngineFactory
from core.extractors.base import BaseExtractor
from core.translators.base import BaseTranslator


class SubtitleWorker(QThread):
    """
    Non-blocking background worker for Subtitle Extraction & Translation.
    Enforces Sequential VRAM clearance between extraction and translation.
    """
    progress_updated = Signal(int, str)
    extraction_done = Signal(list)
    segment_translated = Signal(int, str)
    all_completed = Signal(list, str)
    error_occurred = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        video_path: str,
        extraction_engine: str,
        translation_strategy: str,
        ai_provider: str,
        model_name: str,
        target_language: str,
        settings: Dict[str, Any] = None,
    ):
        super().__init__()
        self.video_path = video_path
        self.extraction_engine = extraction_engine
        self.translation_strategy = translation_strategy
        self.ai_provider = ai_provider
        self.model_name = model_name
        self.target_language = target_language
        self.settings = settings or {}
        self._cancel_event = threading.Event()

    def request_cancel(self):
        self._cancel_event.set()
        self.requestInterruption()

    def run(self):
        try:
            # 1. Instantiate selected Extractor
            self.progress_updated.emit(5, f"Initializing Extractor: {self.extraction_engine}...")
            extractor = EngineFactory.create_extractor(self.extraction_engine, self.settings)

            # 2. Execute Extraction
            if self._cancel_event.is_set():
                self.stopped.emit()
                return

            def on_extract_progress(pct: int, msg: str):
                if self._cancel_event.is_set():
                    return
                # Extraction occupies 0% - 50% of the total pipeline bar
                self.progress_updated.emit(int(pct * 0.50), f"[1/3 Extracting] {msg}")

            segments = extractor.extract(
                self.video_path,
                progress_cb=on_extract_progress,
                cancel_event=self._cancel_event,
            )

            # 3. Sequential VRAM Guard: Unload Extractor from GPU VRAM before starting LLM
            self.progress_updated.emit(52, "[2/3 VRAM Guard] Unloading Extractor & clearing GPU VRAM...")
            extractor.unload()

            if self._cancel_event.is_set():
                self.stopped.emit()
                return

            if not segments:
                self.error_occurred.emit("No subtitles or speech detected in video.")
                return

            self.extraction_done.emit(segments)

            # 4. Instantiate selected Translator Strategy
            self.progress_updated.emit(55, f"[3/3 Translating] Loading Translator: {self.translation_strategy}...")
            translator = EngineFactory.create_translator(
                strategy_name=self.translation_strategy,
                provider_name=self.ai_provider,
                model_name=self.model_name,
                settings=self.settings,
            )

            # 5. Execute Translation
            def on_trans_progress(pct: int, msg: str):
                if self._cancel_event.is_set():
                    return
                # Translation occupies 55% - 100% of the total pipeline bar
                total_pct = 55 + int(pct * 0.45)
                self.progress_updated.emit(min(99, total_pct), f"[3/3 Translating] {msg}")

            translated_segments = translator.translate(
                segments,
                target_lang=self.target_language,
                progress_cb=on_trans_progress,
                cancel_event=self._cancel_event,
            )

            if self._cancel_event.is_set():
                self.stopped.emit()
                return

            self.progress_updated.emit(100, f"Completed! {len(translated_segments)} lines extracted & translated.")
            self.all_completed.emit(translated_segments, f"Success! {len(translated_segments)} subtitles ready.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(f"Processing Error: {str(e)}")
