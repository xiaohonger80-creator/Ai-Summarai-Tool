# -*- coding: utf-8 -*-
"""
core/project_manager.py
Save and Load `.vfxproj` JSON workspace project files (UTF-8) preserving:
  - Relative & absolute video media paths
  - Auto-Episode Split configuration
  - All segment rows (with speaker, voice_fx, translated script, and audio_hash)
  - Speaker voice mappings (speaker_map)
  - Active VideoFX / 3D LUT / Masking parameters
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.schema import normalize_segments
from config.settings import SubtitleSettings


class ProjectManager:
    """
    Handles serialization and deserialization of `.vfxproj` studio project files.
    """

    FORMAT_VERSION = "1.7.8"

    @classmethod
    def save_project(
        cls,
        project_file_path: str,
        video_path: str,
        segments: List[Dict[str, Any]],
        settings: Dict[str, Any],
        speaker_map: Optional[Dict[str, Dict[str, Any]]] = None,
        batch_items: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Saves the current workspace state to a `.vfxproj` UTF-8 JSON file.
        """
        proj_p = Path(project_file_path)
        if proj_p.suffix.lower() != ".vfxproj":
            proj_p = proj_p.with_suffix(".vfxproj")
        proj_p.parent.mkdir(parents=True, exist_ok=True)

        abs_video = str(Path(video_path).resolve()) if video_path and os.path.exists(video_path) else str(video_path or "")
        rel_video = ""
        if abs_video:
            try:
                rel_video = os.path.relpath(abs_video, start=str(proj_p.parent.resolve()))
            except Exception:
                rel_video = abs_video

        payload: Dict[str, Any] = {
            "format": "AiSummarai.vfxproj",
            "version": cls.FORMAT_VERSION,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "video_path": abs_video,
            "relative_video_path": rel_video,
            "auto_split_minutes": int((settings or {}).get("auto_split_minutes", 0)),
            "speaker_map": speaker_map or (settings or {}).get("speaker_map", {}),
            "settings": dict(settings or {}),
            "segments": normalize_segments(segments or []),
            "batch_queue": list(batch_items or []),
        }

        with open(proj_p, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        SubtitleSettings.add_recent_project(str(proj_p.resolve()))
        return str(proj_p.resolve())

    @classmethod
    def load_project(cls, project_file_path: str) -> Dict[str, Any]:
        """
        Loads a `.vfxproj` JSON file and resolves relative media paths if moved.
        """
        proj_p = Path(project_file_path)
        if not proj_p.exists():
            raise FileNotFoundError(f"Project file not found: {project_file_path}")

        with open(proj_p, "r", encoding="utf-8") as f:
            data = json.load(f)

        video_path = data.get("video_path", "")
        rel_video = data.get("relative_video_path", "")
        if video_path and not os.path.exists(video_path) and rel_video:
            candidate = (proj_p.parent / rel_video).resolve()
            if candidate.exists():
                video_path = str(candidate)

        data["video_path"] = video_path
        data["segments"] = normalize_segments(data.get("segments", []))
        SubtitleSettings.add_recent_project(str(proj_p.resolve()))
        return data
