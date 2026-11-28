# -*- coding: utf-8 -*-
"""
core/batch_manager.py
Multi-file/folder Batch Queue Manager + FFmpeg Fast Stream-Copy Auto-Episode Splitter.
Supports:
  - Adding single videos, multi-selected files, or entire folders recursively (MP4, MKV, MOV, AVI).
  - split_long_video(video_path, chunk_minutes=15) using near-instant `-c copy -f segment`.
  - Per-item queue states: Pending, Splitting, Processing, Completed, Failed (Error Tooltip).
"""

import os
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


@dataclass
class BatchQueueItem:
    id: int
    video_path: str
    status: str = "Pending"          # Pending | Splitting | Processing | Completed | Failed
    duration_sec: float = 0.0
    output_path: str = ""
    error_tooltip: str = ""
    segments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BatchManager:
    """
    Manages the multi-video processing queue and automatic long-episode splitting.
    """

    def __init__(self, split_output_dir: str = "data/batch_splits"):
        self.items: List[BatchQueueItem] = []
        self._next_id = 1
        self.split_output_dir = Path(split_output_dir)
        self.split_output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def probe_duration(video_path: str) -> float:
        if not video_path or not os.path.exists(video_path):
            return 0.0
        try:
            res = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=8,
            )
            return max(0.0, round(float((res.stdout or "0").strip() or 0.0), 2))
        except Exception:
            return 0.0

    def add_files(self, file_paths: List[str], auto_split_minutes: int = 0) -> List[BatchQueueItem]:
        added: List[BatchQueueItem] = []
        existing_paths = {Path(it.video_path).resolve() for it in self.items if os.path.exists(it.video_path)}

        for raw_p in file_paths or []:
            p = Path(raw_p)
            if not p.exists() or p.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if p.resolve() in existing_paths:
                continue

            dur = self.probe_duration(str(p))
            if auto_split_minutes > 0 and dur > (auto_split_minutes * 60 + 15):
                parts = self.split_long_video(str(p), chunk_minutes=auto_split_minutes)
                for part_path in parts:
                    part_dur = self.probe_duration(part_path)
                    item = BatchQueueItem(
                        id=self._next_id,
                        video_path=str(Path(part_path).resolve()),
                        status="Pending",
                        duration_sec=part_dur,
                    )
                    self._next_id += 1
                    self.items.append(item)
                    added.append(item)
            else:
                item = BatchQueueItem(
                    id=self._next_id,
                    video_path=str(p.resolve()),
                    status="Pending",
                    duration_sec=dur,
                )
                self._next_id += 1
                self.items.append(item)
                added.append(item)
                existing_paths.add(p.resolve())

        return added

    def add_folder(self, folder_path: str, auto_split_minutes: int = 0) -> List[BatchQueueItem]:
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return []
        video_files = sorted(
            str(p) for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        )
        return self.add_files(video_files, auto_split_minutes=auto_split_minutes)

    def split_long_video(self, video_path: str, chunk_minutes: int = 15) -> List[str]:
        """
        Near-instant stream-copy episode splitter:
        ffmpeg -i input.mp4 -c copy -map 0 -segment_time {seconds} -f segment -reset_timestamps 1 part_%03d.mp4
        """
        src = Path(video_path)
        if not src.exists():
            return []

        dur = self.probe_duration(str(src))
        seg_seconds = max(60, int(chunk_minutes) * 60)
        if dur <= seg_seconds:
            return [str(src.resolve())]

        target_dir = self.split_output_dir / src.stem
        target_dir.mkdir(parents=True, exist_ok=True)
        for old in target_dir.glob(f"{src.stem}_part_*.mp4"):
            try:
                old.unlink()
            except Exception:
                pass

        pattern = str(target_dir / f"{src.stem}_part_%03d.mp4")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-c", "copy",
            "-map", "0:v:0",
            "-map", "0:a?",
            "-segment_time", str(seg_seconds),
            "-f", "segment",
            "-reset_timestamps", "1",
            pattern,
        ]
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
                timeout=180,
            )
        except Exception:
            return [str(src.resolve())]

        parts = sorted(str(p.resolve()) for p in target_dir.glob(f"{src.stem}_part_*.mp4") if p.stat().st_size > 1024)
        return parts if parts else [str(src.resolve())]

    def clear_completed(self) -> None:
        self.items = [it for it in self.items if it.status != "Completed"]

    def get_pending_items(self) -> List[BatchQueueItem]:
        return [it for it in self.items if it.status in ("Pending", "Failed")]

    def update_status(self, item_id: int, status: str, error_tooltip: str = "", output_path: str = "") -> None:
        for it in self.items:
            if it.id == item_id:
                it.status = status
                if error_tooltip:
                    it.error_tooltip = error_tooltip
                if output_path:
                    it.output_path = output_path
                break
