# -*- coding: utf-8 -*-
"""
workers/render_worker.py
Background QThread workers for VideoFX Studio:
  - PreviewRenderWorker: Real-time non-blocking single-frame rendering for scrubber.
  - ExportRenderWorker: Full video export with stderr progress parsing & cancellation.
"""

import os
import re
import subprocess
import time
from typing import Dict, Any, Optional, List
from PySide6.QtCore import QThread, Signal

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class PreviewRenderWorker(QThread):
    """
    Renders single video frame in background thread to keep UI scrubber 100% smooth.
    """
    preview_ready = Signal(str, float)   # (jpg_path, timestamp_sec)
    preview_failed = Signal(str)

    def __init__(
        self,
        compositor,
        video_path: str,
        timestamp_sec: float,
        out_jpg_path: str,
        lut_name: Optional[str] = None,
        lut_intensity: float = 1.0,
        mask_params: Optional[Dict[str, Any]] = None,
        ass_path: Optional[str] = None,
        target_w: int = 1280,
        target_h: int = 720,
        parent=None,
    ):
        super().__init__(parent)
        self.compositor = compositor
        self.video_path = video_path
        self.timestamp_sec = timestamp_sec
        self.out_jpg_path = out_jpg_path
        self.lut_name = lut_name
        self.lut_intensity = lut_intensity
        self.mask_params = mask_params
        self.ass_path = ass_path
        self.target_w = target_w
        self.target_h = target_h
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return

        success = self.compositor.render_preview_frame(
            video_path=self.video_path,
            timestamp_sec=self.timestamp_sec,
            out_jpg_path=self.out_jpg_path,
            lut_name=self.lut_name,
            lut_intensity=self.lut_intensity,
            mask_params=self.mask_params,
            ass_path=self.ass_path,
            target_w=self.target_w,
            target_h=self.target_h,
        )

        if not self._is_cancelled and success and os.path.exists(self.out_jpg_path):
            self.preview_ready.emit(self.out_jpg_path, self.timestamp_sec)
        elif not self._is_cancelled:
            self.preview_failed.emit(f"Failed to render preview frame at {self.timestamp_sec:.2f}s")


class ExportRenderWorker(QThread):
    """
    Executes full FFmpeg export process with live progress tracking and graceful abort.
    """
    progress = Signal(int, str)       # (percent, time_string)
    status_text = Signal(str)
    finished = Signal(str)           # output_file_path
    failed = Signal(str)

    def __init__(self, cmd: List[str], total_duration_sec: float, out_path: str, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.total_duration_sec = max(0.1, float(total_duration_sec))
        self.out_path = out_path
        self._process = None
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass

    def run(self):
        self.status_text.emit("កំពុងដំណើរការផលិតវីដេអូ (Starting export)...")
        time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

        try:
            self._process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                creationflags=CREATE_NO_WINDOW,
            )

            for line in self._process.stderr:
                if self._is_cancelled:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                    self.failed.emit("ការនាំចេញត្រូវបានផ្អាកដោយអ្នកប្រើប្រាស់ (Export cancelled)")
                    return

                match = time_pattern.search(line)
                if match:
                    hrs = int(match.group(1))
                    mins = int(match.group(2))
                    secs = float(match.group(3))
                    cur_sec = hrs * 3600 + mins * 60 + secs
                    pct = min(99, int((cur_sec / self.total_duration_sec) * 100))
                    time_str = f"{hrs:02d}:{mins:02d}:{int(secs):02d}"
                    self.progress.emit(pct, time_str)

            self._process.wait()
            if self._process.stderr:
                try:
                    self._process.stderr.close()
                except Exception:
                    pass

            if self._is_cancelled:
                return

            if self._process.returncode == 0 and os.path.exists(self.out_path):
                self.progress.emit(100, "100%")
                self.finished.emit(self.out_path)
            else:
                self.failed.emit(f"FFmpeg Export failed with exit code {self._process.returncode}")

        except Exception as e:
            if not self._is_cancelled:
                self.failed.emit(f"Export Error: {e}")
