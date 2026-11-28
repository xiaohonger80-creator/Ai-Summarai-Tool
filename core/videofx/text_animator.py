# -*- coding: utf-8 -*-
"""
core/videofx/text_animator.py
Advanced SubStation Alpha (.ass) UTF-8-SIG Text & Subtitle Animation Engine.
Supports:
  - Horizontal Scrolling Marquee
  - Vertical Credits Roll
  - Kinetic Pop-In
  - Static Styled Subtitles
  - Bottom Hardsub Cover Box (Opaque/Translucent bar covering hardcoded Chinese subtitles)
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from core.text_animator import TextAnimator as BaseTextAnimator


class TextAnimator(BaseTextAnimator):
    """
    Extended TextAnimator supporting both animated overlay banners and
    timestamped segment-by-segment `.ass` subtitles with optional Bottom Hardsub Cover Box.
    """

    STYLE_OPTIONS = [
        "Static Styled Subtitles",
        "Horizontal Scrolling Marquee",
        "Vertical Credits Roll",
        "Kinetic Pop-In",
    ]

    @classmethod
    def generate_studio_ass(
        cls,
        segments: List[Dict[str, Any]],
        out_ass_path: str,
        style_mode: str = "Static Styled Subtitles",
        bottom_cover_box: bool = True,
        font_name: str = "Noto Sans Khmer",
        font_size: int = 46,
        primary_color: str = "#FFFFFF",
        outline_color: str = "#000000",
        speed_factor: float = 1.0,
        video_w: int = 1920,
        video_h: int = 1080,
        video_duration: float = 15.0,
        fallback_banner_text: str = "Ai Summarai — All-in-One AI Video, Dubbing, Recap & FX Studio",
    ) -> str:
        """
        Generates a UTF-8-SIG `.ass` subtitle script from segment dicts or fallback banner text.
        """
        # Map style_mode to BaseTextAnimator mode
        if "Horizontal" in style_mode:
            anim_mode = cls.ANIMATION_MODES[0]
        elif "Vertical" in style_mode:
            anim_mode = cls.ANIMATION_MODES[1]
        elif "Kinetic" in style_mode:
            anim_mode = cls.ANIMATION_MODES[2]
        elif bottom_cover_box:
            anim_mode = cls.ANIMATION_MODES[3]  # Boxed Banner mode (BorderStyle=3 opaque cover box)
        else:
            anim_mode = cls.ANIMATION_MODES[2]

        norm_segs: List[Dict[str, Any]] = []
        for s in segments or []:
            txt = (s.get("translated") or s.get("kh_text") or s.get("text") or "").strip()
            if txt:
                norm_segs.append({
                    "start": float(s.get("start", 0.0)),
                    "end": float(s.get("end", 3.0)),
                    "translated": txt,
                    "text": txt,
                })

        return cls.generate_ass_script(
            text_content=fallback_banner_text,
            animation_mode=anim_mode,
            video_duration_sec=max(5.0, float(video_duration)),
            out_ass_path=out_ass_path,
            width=video_w,
            height=video_h,
            font_name=font_name,
            font_size=font_size,
            primary_color=primary_color,
            outline_color=outline_color,
            box_bg_color="#0B0D10",
            position="Bottom",
            speed_factor=speed_factor,
            segments=norm_segs if norm_segs else None,
        )
