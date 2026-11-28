# -*- coding: utf-8 -*-
"""
core/recap_dubbing/scene_cutter.py
Automated Scene Boundary Detection & Anti-Copyright Transform Engine.
Uses PySceneDetect (if installed) with built-in FFmpeg scdet fallback so it never fails on clean machines.
"""

import gc
import os
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class SceneCutter:
    """
    Auto Scene Boundary Detection & Anti-Copyright Video Filter Builder:
    - Detects scene cuts using PySceneDetect (ContentDetector) or FFmpeg `scdet`.
    - Builds anti-copyright FFmpeg filter chains (Horizontal Mirror Flip, Micro-Zoom 1.05x, Color Shift).
    """

    def __init__(self, threshold: float = 27.0, min_scene_len_sec: float = 1.5):
        self.threshold = float(threshold)
        self.min_scene_len_sec = float(min_scene_len_sec)

    def detect_scenes(self, video_path: str, max_duration: float = 0.0) -> List[Tuple[float, float]]:
        """
        Returns a list of (start_sec, end_sec) scene intervals.
        """
        if not video_path or not os.path.exists(video_path):
            return []

        # 1. Try PySceneDetect first if available
        try:
            from scenedetect import detect, ContentDetector
            scene_list = detect(video_path, ContentDetector(threshold=self.threshold))
            intervals: List[Tuple[float, float]] = []
            for start_tc, end_tc in scene_list:
                s = round(start_tc.get_seconds(), 2)
                e = round(end_tc.get_seconds(), 2)
                if e - s >= self.min_scene_len_sec:
                    intervals.append((s, e))
            if intervals:
                return intervals
        except Exception:
            pass

        # 2. Pure FFmpeg scdet fallback
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats",
            "-i", str(video_path),
            "-vf", f"scdet=threshold={max(8.0, min(40.0, self.threshold / 2.5)):.1f}",
            "-an", "-f", "null", "-"
        ]
        cut_points: List[float] = [0.0]
        total_dur = max_duration
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=90,
            )
            for line in (res.stderr or "").splitlines():
                m = re.search(r"lavfi\.scdet\.time:\s*([0-9.]+)", line)
                if m:
                    t = round(float(m.group(1)), 2)
                    if t - cut_points[-1] >= self.min_scene_len_sec:
                        cut_points.append(t)
                dm = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", line)
                if dm and total_dur <= 0:
                    total_dur = int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + float(dm.group(3))
        except Exception:
            pass

        if total_dur <= cut_points[-1]:
            total_dur = cut_points[-1] + 10.0
        cut_points.append(round(total_dur, 2))

        scenes: List[Tuple[float, float]] = []
        for i in range(len(cut_points) - 1):
            s, e = cut_points[i], cut_points[i + 1]
            if e - s >= 0.5:
                scenes.append((s, e))
        return scenes

    @staticmethod
    def build_anti_copyright_filter(
        input_label: str = "0:v",
        output_label: str = "ac_out",
        mirror_flip: bool = False,
        micro_zoom: bool = False,
        zoom_factor: float = 1.05,
    ) -> str:
        """
        Builds FFmpeg video filter expressions for copyright-safe micro-crop, mirror flip, and subtle eq.
        """
        ops: List[str] = []
        if mirror_flip:
            ops.append("hflip")
        if micro_zoom and zoom_factor > 1.001:
            zf = round(float(zoom_factor), 3)
            ops.append(f"scale=iw*{zf}:ih*{zf},crop=iw/{zf}:ih/{zf}")

        if not ops:
            return f"[{input_label}]copy[{output_label}]"
        return f"[{input_label}]{','.join(ops)}[{output_label}]"

    def unload(self) -> None:
        gc.collect()
