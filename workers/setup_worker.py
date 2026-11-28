# -*- coding: utf-8 -*-
"""
workers/setup_worker.py
Background QThread Worker for DependencyChecker tasks:
  - Auditing FFmpeg, Python AI packages, and Ollama models
  - Downloading portable FFmpeg binaries into ./bin/
  - Streaming Ollama model pulls (`POST /api/pull`) without freezing UI
"""

from typing import Dict, Any
from PySide6.QtCore import QThread, Signal

from core.dependency_checker import DependencyChecker


class SetupWorker(QThread):
    """
    Non-blocking QThread executing Setup Manager tasks (audit, pull_model, download_ffmpeg).
    """

    progress_updated = Signal(int, str)
    audit_ready = Signal(dict)
    task_finished = Signal(bool, str)

    def __init__(
        self,
        action: str = "audit",  # "audit" | "pull_model" | "download_ffmpeg"
        ollama_url: str = "http://localhost:11434",
        model_name: str = "qwen2.5:7b",
        parent=None,
    ):
        super().__init__(parent)
        self.action = action
        self.ollama_url = ollama_url
        self.model_name = model_name
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        if self.action == "audit":
            self.progress_updated.emit(30, "Auditing FFmpeg, Hardware Encoders & Ollama...")
            report: Dict[str, Any] = DependencyChecker.check_all(
                ollama_url=self.ollama_url,
                target_model=self.model_name,
            )
            self.progress_updated.emit(100, "System audit completed.")
            self.audit_ready.emit(report)
            self.task_finished.emit(True, "Audit complete.")

        elif self.action == "pull_model":
            ok = DependencyChecker.pull_ollama_model(
                model_name=self.model_name,
                ollama_url=self.ollama_url,
                progress_cb=lambda p, m: self.progress_updated.emit(p, m),
                is_cancelled=self.is_cancelled,
            )
            report = DependencyChecker.check_all(self.ollama_url, self.model_name)
            self.audit_ready.emit(report)
            self.task_finished.emit(ok, f"Model '{self.model_name}' pull {'succeeded' if ok else 'failed'}.")

        elif self.action == "download_ffmpeg":
            ok = DependencyChecker.download_portable_ffmpeg(
                dest_bin_dir="bin",
                progress_cb=lambda p, m: self.progress_updated.emit(p, m),
                is_cancelled=self.is_cancelled,
            )
            report = DependencyChecker.check_all(self.ollama_url, self.model_name)
            self.audit_ready.emit(report)
            self.task_finished.emit(ok, "FFmpeg download complete." if ok else "FFmpeg download failed.")
