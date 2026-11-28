# -*- coding: utf-8 -*-
"""
core/videofx/compositor.py
Master FFmpeg filter_complex builder chaining:
  Video Cuts / Anti-Copyright -> 3D LUT (0-100% blend) -> Video Mask / Blur BG ->
  Animated .ass Text -> Dubbed Audio + BGM Mix -> Output MP4 / Fast Preview Frame.
"""

import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from core.videofx.lut_engine import LUTEngine
from core.videofx.mask_engine import VideoMaskEngine
from core.recap_dubbing.scene_cutter import SceneCutter
from core.hardware_profiler import HardwareProfiler

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class MasterCompositor:
    """
    Chains all visual and audio pipeline stages into a single hardware-friendly FFmpeg command.
    Supports sub-second (< 0.5s) single-frame preview rendering for live canvas scrubbing.
    """

    def __init__(self, lut_engine: Optional[LUTEngine] = None):
        self.lut_engine = lut_engine or LUTEngine()

    @staticmethod
    def escape_ffmpeg_path(path: str) -> str:
        p_str = str(Path(path).resolve()).replace("\\", "/")
        return p_str.replace(":", r"\:")

    def build_video_filter_chain(
        self,
        settings: Dict[str, Any],
        ass_path: Optional[str] = None,
        video_w: int = 1920,
        video_h: int = 1080,
    ) -> Tuple[str, str]:
        """
        Builds unified video filter_complex string:
          [0:v] -> Anti-Copyright -> 3D LUT -> Mask/Blur -> .ass Subtitles -> [v_final]
        """
        s = settings or {}
        parts: List[str] = []
        cur = "0:v"

        # Stage A: Anti-Copyright Mirror / Micro-Zoom
        mirror = bool(s.get("anti_cr_mirror", False))
        zoom = bool(s.get("anti_cr_zoom", False))
        if mirror or zoom:
            ac_f = SceneCutter.build_anti_copyright_filter(
                input_label=cur,
                output_label="v_ac",
                mirror_flip=mirror,
                micro_zoom=zoom,
                zoom_factor=1.05,
            )
            parts.append(ac_f)
            cur = "v_ac"

        # Stage B: 3D Color LUT Grading
        if s.get("lut_enabled", False):
            lut_name = s.get("lut_preset", "Cinematic_Teal_Orange.cube")
            lut_intensity = float(s.get("lut_intensity", 80)) / 100.0
            if lut_name and lut_intensity > 0.001:
                lut_f = self.lut_engine.build_ffmpeg_filter(
                    lut_name=lut_name,
                    intensity=lut_intensity,
                    input_label=cur,
                    output_label="v_lut",
                )
                parts.append(lut_f)
                cur = "v_lut"

        # Stage C: Video Masking or Bottom Hardsub Cover Blur
        mask_enabled = bool(s.get("mask_enabled", False))
        bottom_cover = bool(s.get("bottom_cover_box", False))
        if mask_enabled or bottom_cover:
            masker = VideoMaskEngine(
                engine_name=s.get("mask_engine", "Shape Mask - Portrait/Circle"),
                bg_mode=s.get("mask_bg_mode", "Blur BG"),
                blur_radius=int(s.get("mask_blur_radius", 24)),
            )
            mask_f = masker.build_ffmpeg_filter(
                input_label=cur,
                output_label="v_mask",
                width=video_w,
                height=video_h,
                bottom_cover_blur=(bottom_cover and not mask_enabled),
            )
            parts.append(mask_f)
            cur = "v_mask"
            masker.unload()

        # Stage D: Animated .ass Text / Subtitles
        if s.get("text_fx_enabled", True) and ass_path and os.path.exists(ass_path):
            safe_ass = self.escape_ffmpeg_path(ass_path)
            parts.append(f"[{cur}]ass='{safe_ass}'[v_sub]")
            cur = "v_sub"

        if not parts:
            return "[0:v]copy[v_final]", "v_final"

        return ";".join(parts), cur

    def render_preview_frame(
        self,
        video_path: str,
        timestamp_sec: float,
        out_jpg_path: str,
        settings: Dict[str, Any],
        ass_path: Optional[str] = None,
        target_w: int = 960,
        target_h: int = 540,
    ) -> bool:
        """
        Renders a single processed video frame at timestamp_sec in < 0.5s.
        If video_path is None or missing, generates a synthetic dark-slate preview card so
        'Render Preview Frame' works immediately on startup!
        """
        Path(out_jpg_path).parent.mkdir(parents=True, exist_ok=True)
        vf_chain, last_label = self.build_video_filter_chain(
            settings=settings,
            ass_path=ass_path,
            video_w=target_w,
            video_h=target_h,
        )
        full_filter = f"{vf_chain};[{last_label}]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[pv_out]"

        if video_path and os.path.exists(video_path):
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{max(0.0, float(timestamp_sec)):.3f}",
                "-i", str(video_path),
                "-filter_complex", full_filter,
                "-map", "[pv_out]",
                "-vframes", "1",
                "-q:v", "2",
                str(out_jpg_path),
            ]
        else:
            # Synthetic test pattern when user clicks 'Render Preview Frame' before opening a video
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"testsrc2=size={target_w}x{target_h}:rate=25:duration=2",
                "-filter_complex", full_filter,
                "-map", "[pv_out]",
                "-vframes", "1",
                "-q:v", "2",
                str(out_jpg_path),
            ]

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
                timeout=8.0,
            )
            return res.returncode == 0 and os.path.exists(out_jpg_path)
        except Exception:
            return False

    def compose_final_video(
        self,
        video_path: str,
        out_video_path: str,
        settings: Dict[str, Any],
        ass_path: Optional[str] = None,
        bgm_wav_path: Optional[str] = None,
        segments: Optional[List[Dict[str, Any]]] = None,
        video_w: int = 1920,
        video_h: int = 1080,
    ) -> List[str]:
        """
        Builds the complete FFmpeg command for final video + dubbed audio compositing.
        """
        Path(out_video_path).parent.mkdir(parents=True, exist_ok=True)
        vf_chain, last_v = self.build_video_filter_chain(
            settings=settings,
            ass_path=ass_path,
            video_w=video_w,
            video_h=video_h,
        )

        inputs: List[str] = ["-i", str(video_path)]
        audio_map = "0:a?"

        # Optional BGM track replacement
        if bgm_wav_path and os.path.exists(bgm_wav_path):
            inputs.extend(["-i", str(bgm_wav_path)])
            audio_map = "1:a"

        preferred_enc = (settings or {}).get("preferred_encoder", "auto")
        encoder_args = HardwareProfiler.get_encoder_args(preferred=preferred_enc)

        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            *inputs,
            "-filter_complex", vf_chain,
            "-map", f"[{last_v}]",
            "-map", audio_map,
            *encoder_args,
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out_video_path),
        ]
        return cmd
