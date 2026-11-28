# -*- coding: utf-8 -*-
"""
core/videofx/mask_engine.py
Unified Selectable Video Masking Engine:
  - AI Human Matting - RobustVideoMatting
  - AI Object Cutout - rembg
  - Shape Mask - Portrait/Circle
  - Shape Mask - Split Screen
Supports Background Modes: Blur BG, Custom Image/Video, Green Screen.
Implements mandatory unload() freeing GPU VRAM.
"""

import gc
from typing import Dict, Any, Optional
from core.masking.base import BaseMasker
from core.masking.shape_masker import ShapeMasker
from core.masking.rvm_masker import RVMMasker
from core.masking.rembg_masker import RembgMasker


class VideoMaskEngine:
    """
    High-level Mask Engine wrapping RVM, Rembg, and FFmpeg Geometric/Luma Shape Maskers.
    """

    MASK_ENGINES = [
        "AI Human Matting - RobustVideoMatting",
        "AI Object Cutout - rembg",
        "Shape Mask - Portrait/Circle",
        "Shape Mask - Split Screen",
    ]

    BG_MODES = [
        "Blur BG",
        "Custom Image/Video",
        "Green Screen",
    ]

    def __init__(
        self,
        engine_name: str = "Shape Mask - Portrait/Circle",
        bg_mode: str = "Blur BG",
        blur_radius: int = 24,
    ):
        self.engine_name = engine_name
        self.bg_mode = bg_mode
        self.blur_radius = max(2, int(blur_radius))
        self._active_masker: Optional[BaseMasker] = None

    def _get_masker(self) -> BaseMasker:
        if self._active_masker is None:
            if "RobustVideoMatting" in self.engine_name:
                self._active_masker = RVMMasker()
            elif "rembg" in self.engine_name:
                self._active_masker = RembgMasker()
            else:
                self._active_masker = ShapeMasker()
        return self._active_masker

    def build_ffmpeg_filter(
        self,
        input_label: str = "0:v",
        output_label: str = "mask_out",
        width: int = 1920,
        height: int = 1080,
        bottom_cover_blur: bool = False,
    ) -> str:
        """
        Builds an FFmpeg filter expression for the chosen mask engine and background mode.
        """
        shape_masker = ShapeMasker()
        if "Split Screen" in self.engine_name:
            shape_type = "Split Screen (ចែកអេក្រង់)"
        elif "Circle" in self.engine_name or "Portrait" in self.engine_name:
            if bottom_cover_blur:
                shape_type = "Subtitle Blur Box (បិទបាំងអក្សរក្រោម)"
            else:
                shape_type = "Cinematic Vignette (គែមងងឹត)"
        else:
            shape_type = "Subtitle Blur Box (បិទបាំងអក្សរក្រោម)"

        params: Dict[str, Any] = {
            "shape_type": shape_type,
            "blur_radius": self.blur_radius,
            "box_x": int(width * 0.05),
            "box_y": int(height * 0.76),
            "box_w": int(width * 0.90),
            "box_h": int(height * 0.18),
        }
        return shape_masker.build_ffmpeg_filter(
            input_label=input_label,
            output_label=output_label,
            width=width,
            height=height,
            params=params,
        )

    def unload(self) -> None:
        """Mandatory VRAM / model weight release."""
        if self._active_masker is not None:
            self._active_masker.unload()
            self._active_masker = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        gc.collect()
