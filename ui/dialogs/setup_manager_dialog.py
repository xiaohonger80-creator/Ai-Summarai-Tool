# -*- coding: utf-8 -*-
"""
ui/dialogs/setup_manager_dialog.py
Startup / Menu Dependency & Model Setup Manager Modal:
  - 4-Row Checklist:
    1. FFmpeg & FFprobe Binaries
    2. ASR / OCR AI Engines (faster-whisper, PaddleOCR, FunASR)
    3. Ollama Local Server (http://localhost:11434)
    4. Translation LLM Model (qwen2.5:7b / gemma2:9b)
  - Status badges, 'Auto-Fix / Download' buttons, 'Browse...' path pickers,
    GPU Hardware Encoder summary, and live QProgressBar driven by SetupWorker.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QProgressBar, QComboBox, QFileDialog, QGroupBox
)

from core.hardware_profiler import HardwareProfiler
from workers.setup_worker import SetupWorker


class SetupManagerDialog(QDialog):
    """
    4-Row Dependency & Model Setup Manager with One-Click Auto-Fix / Ollama Pull.
    """

    health_updated = Signal(bool)

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        target_model: str = "qwen2.5:7b",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("🛠️ Setup & Model Manager — Hardware, FFmpeg & Local AI")
        self.resize(720, 420)
        self.ollama_url = ollama_url
        self.target_model = target_model
        self._worker: Optional[SetupWorker] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Hardware Profiler Summary Card
        hw = HardwareProfiler.detect_hardware()
        hw_grp = QGroupBox("Detected Hardware & GPU Video Encoder")
        hw_lay = QHBoxLayout(hw_grp)
        self.lbl_hw_summary = QLabel(
            f"GPU: {hw['gpu_name']} ({hw['vram_gb']} GB VRAM)  |  "
            f"System RAM: {hw['ram_gb']} GB  |  "
            f"Active Encoder: {HardwareProfiler.get_encoder_badge_text()}"
        )
        self.lbl_hw_summary.setStyleSheet("color: #38BDF8; font-weight: 700;")
        hw_lay.addWidget(self.lbl_hw_summary)
        layout.addWidget(hw_grp)

        # 4-Row Checklist Grid
        chk_grp = QGroupBox("Runtime Dependencies & Local AI Models Checklist")
        grid = QGridLayout(chk_grp)
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(10)

        # Row 1: FFmpeg Binaries
        grid.addWidget(QLabel("1. FFmpeg & FFprobe Binaries:"), 0, 0)
        self.pill_ffmpeg = self._make_status_pill("Checking...")
        grid.addWidget(self.pill_ffmpeg, 0, 1)
        self.btn_fix_ffmpeg = QPushButton("Auto-Download FFmpeg")
        self.btn_fix_ffmpeg.clicked.connect(self._on_download_ffmpeg)
        grid.addWidget(self.btn_fix_ffmpeg, 0, 2)
        self.btn_browse_ffmpeg = QPushButton("Browse...")
        self.btn_browse_ffmpeg.clicked.connect(self._on_browse_ffmpeg)
        grid.addWidget(self.btn_browse_ffmpeg, 0, 3)

        # Row 2: ASR / OCR Engines
        grid.addWidget(QLabel("2. ASR / OCR AI Engines:"), 1, 0)
        self.pill_ai = self._make_status_pill("Checking...")
        grid.addWidget(self.pill_ai, 1, 1)
        self.lbl_ai_detail = QLabel("faster-whisper / PaddleOCR / Edge-TTS")
        self.lbl_ai_detail.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        grid.addWidget(self.lbl_ai_detail, 1, 2, 1, 2)

        # Row 3: Ollama Local Server
        grid.addWidget(QLabel("3. Ollama Local Server:"), 2, 0)
        self.pill_ollama = self._make_status_pill("Checking...")
        grid.addWidget(self.pill_ollama, 2, 1)
        self.btn_recheck = QPushButton("Re-Check Server")
        self.btn_recheck.clicked.connect(self.run_audit)
        grid.addWidget(self.btn_recheck, 2, 2, 1, 2)

        # Row 4: Translation LLM Model
        grid.addWidget(QLabel("4. Translation LLM Model:"), 3, 0)
        self.pill_model = self._make_status_pill("Checking...")
        grid.addWidget(self.pill_model, 3, 1)
        self.combo_pull_model = QComboBox()
        self.combo_pull_model.setEditable(True)
        self.combo_pull_model.addItems(["qwen2.5:7b", "gemma2:9b", "qwen2.5:3b", "llama3.2:3b"])
        self.combo_pull_model.setCurrentText(self.target_model)
        grid.addWidget(self.combo_pull_model, 3, 2)
        self.btn_pull_model = QPushButton("Pull Model via Ollama")
        self.btn_pull_model.setObjectName("PrimaryCTA")
        self.btn_pull_model.clicked.connect(self._on_pull_model)
        grid.addWidget(self.btn_pull_model, 3, 3)

        layout.addWidget(chk_grp)

        # Progress bar & status
        self.lbl_progress = QLabel("Ready to verify system dependencies.")
        self.lbl_progress.setStyleSheet("color: #D1D5DB;")
        layout.addWidget(self.lbl_progress)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Bottom buttons
        footer = QHBoxLayout()
        footer.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        layout.addLayout(footer)

        self.run_audit()

    @staticmethod
    def _make_status_pill(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedWidth(135)
        lbl.setStyleSheet(
            "background-color: #1F2937; color: #9CA3AF; border-radius: 4px; padding: 3px 6px; font-weight: 700;"
        )
        return lbl

    @staticmethod
    def _style_pill(lbl: QLabel, ok: bool, ok_text: str, warn_text: str) -> None:
        if ok:
            lbl.setText(f"✅ {ok_text}")
            lbl.setStyleSheet(
                "background-color: #064E3B; color: #34D399; border: 1px solid #059669; "
                "border-radius: 4px; padding: 3px 6px; font-weight: 700;"
            )
        else:
            lbl.setText(f"⚠️ {warn_text}")
            lbl.setStyleSheet(
                "background-color: #78350F; color: #FBBF24; border: 1px solid #D97706; "
                "border-radius: 4px; padding: 3px 6px; font-weight: 700;"
            )

    def run_audit(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._worker = SetupWorker(
            action="audit",
            ollama_url=self.ollama_url,
            model_name=self.combo_pull_model.currentText().strip(),
            parent=self,
        )
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.audit_ready.connect(self._apply_audit_report)
        self._worker.start()

    def _on_download_ffmpeg(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.btn_fix_ffmpeg.setEnabled(False)
        self._worker = SetupWorker(action="download_ffmpeg", ollama_url=self.ollama_url, parent=self)
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.audit_ready.connect(self._apply_audit_report)
        self._worker.task_finished.connect(lambda _ok, _m: self.btn_fix_ffmpeg.setEnabled(True))
        self._worker.start()

    def _on_browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffmpeg.exe", "", "Executable (ffmpeg.exe);;All Files (*.*)")
        if path and os.path.exists(path):
            folder = str(Path(path).resolve().parent)
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            self.run_audit()

    def _on_pull_model(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        model = self.combo_pull_model.currentText().strip() or "qwen2.5:7b"
        self.btn_pull_model.setEnabled(False)
        self._worker = SetupWorker(action="pull_model", ollama_url=self.ollama_url, model_name=model, parent=self)
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.audit_ready.connect(self._apply_audit_report)
        self._worker.task_finished.connect(lambda _ok, _m: self.btn_pull_model.setEnabled(True))
        self._worker.start()

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress_bar.setValue(pct)
        self.lbl_progress.setText(msg)

    def _apply_audit_report(self, report: Dict[str, Any]) -> None:
        ff_ok = bool(report.get("ffmpeg", {}).get("ok"))
        self._style_pill(self.pill_ffmpeg, ff_ok, "Ready", "Missing")

        ai_info = report.get("ai_engines", {})
        ai_ok = bool(ai_info.get("ok"))
        self._style_pill(self.pill_ai, ai_ok, "Installed", "Partial")
        pkgs = ai_info.get("packages", {})
        active_list = [k for k, v in pkgs.items() if v]
        self.lbl_ai_detail.setText("Active: " + (", ".join(active_list) if active_list else "Standard Fallback"))

        ol_ok = bool(report.get("ollama_server", {}).get("ok"))
        self._style_pill(self.pill_ollama, ol_ok, "Online", "Offline (Cloud/Free OK)")

        m_ok = bool(report.get("llm_model", {}).get("ok"))
        self._style_pill(self.pill_model, m_ok, "Model Ready", "Not Pulled")

        self.health_updated.emit(bool(report.get("overall_healthy")))
