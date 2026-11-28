import abc
from typing import List, Dict, Any, Callable, Optional


class BaseTranslator(abc.ABC):
    """
    Abstract Base Translator for Subtitle Translation.
    Supports pluggable translation strategies (Fast Batch vs. Story Context).
    """

    @abc.abstractmethod
    def translate(
        self,
        segments: List[Dict[str, Any]],
        target_lang: str = "Khmer",
        progress_cb: Optional[Callable[[int, str], None]] = None,
        cancel_event=None,
    ) -> List[Dict[str, Any]]:
        """Translate subtitle segments and return populated unified schema."""
        pass
