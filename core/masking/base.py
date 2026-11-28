# -*- coding: utf-8 -*-
"""
core/masking/base.py
Abstract Base Class for all video masking engines in VideoFX Studio.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import numpy as np


class BaseMasker(ABC):
    """
    Abstract Base Masker:
    - Provides standardized interface for both fast FFmpeg filter-based masking
      and frame-by-frame AI segmentation (RobustVideoMatting, Rembg).
    - Enforces mandatory unload() to release GPU VRAM and system RAM.
    """

    def __init__(self, name: str = "BaseMasker"):
        self.name = name
        self.is_loaded = False

    @abstractmethod
    def build_ffmpeg_filter(
        self,
        input_label: str = "0:v",
        output_label: str = "masked",
        width: int = 1920,
        height: int = 1080,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Builds an FFmpeg filter_complex snippet for real-time hardware-accelerated masking.
        """
        pass

    def process_frame(self, frame_bgr: np.ndarray, params: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        Processes a single BGR frame and returns a grayscale alpha mask (0..255)
        or 4-channel BGRA frame. Default fallback returns full white alpha mask.
        """
        h, w = frame_bgr.shape[:2]
        return np.full((h, w), 255, dtype=np.uint8)

    @abstractmethod
    def unload(self) -> None:
        """
        Mandatory VRAM and memory cleanup.
        Must release PyTorch CUDA caches, ONNX sessions, or large buffer arrays.
        """
        self.is_loaded = False
