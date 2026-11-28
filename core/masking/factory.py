# -*- coding: utf-8 -*-
"""
core/masking/factory.py
Factory pattern to instantiate masking engines in VideoFX Studio.
"""

from typing import Optional
from core.masking.base import BaseMasker
from core.masking.shape_masker import ShapeMasker
from core.masking.rvm_masker import RVMMasker
from core.masking.rembg_masker import RembgMasker


class MaskerFactory:
    """Creates video masking engines based on UI selection."""

    MASKER_OPTIONS = [
        "Fast Shape & Blur Mask (FFmpeg)",
        "AI Human Matting (RVM)",
        "AI Object Cutout (Rembg / BiRefNet)",
    ]

    @classmethod
    def create(cls, mode: str) -> BaseMasker:
        if "RVM" in mode or "Human" in mode:
            return RVMMasker()
        elif "Rembg" in mode or "Object" in mode:
            return RembgMasker()
        else:
            return ShapeMasker()
