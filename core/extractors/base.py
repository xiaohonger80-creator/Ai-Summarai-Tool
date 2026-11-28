import abc
import gc
from typing import List, Dict, Any, Callable, Optional


class BaseExtractor(abc.ABC):
    """
    Abstract Base Extractor for Video Subtitle Extraction.
    Mandates:
    1. extract(): Returns a List of Dicts adhering to the unified schema.
    2. unload(): Clears all neural model weights and empties GPU VRAM before translation starts.
    """

    def __init__(self):
        self.model = None

    @abc.abstractmethod
    def extract(
        self,
        video_path: str,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        cancel_event=None,
    ) -> List[Dict[str, Any]]:
        """Extract subtitles from video and return unified schema list."""
        pass

    def unload(self):
        """
        Sequential VRAM Guard:
        Explicitly free model from VRAM so local LLM (Ollama) has full GPU memory available.
        """
        if self.model is not None:
            del self.model
            self.model = None

        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
