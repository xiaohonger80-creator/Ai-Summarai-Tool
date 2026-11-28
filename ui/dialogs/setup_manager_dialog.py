# -*- coding: utf-8 -*-
"""
ui/dialogs/setup_manager_dialog.py
Startup / Menu Dependency & Model Setup Manager Modal:
  - Displays accurate NVIDIA/AMD/Intel GPU, VRAM, System RAM, and Active Hardware Encoder.
  - 4-Row Checklist:
    1. FFmpeg && FFprobe Binaries
    2. ASR / OCR AI Engines (faster-whisper, PaddleOCR, FunASR, Edge-TTS)
    3. Ollama Local Server (Auto-Start / Auto-Install Ollama or use Built-in Free Translator)
    4. Translation LLM Model (google-free Built-in, qwen2.5:7b, qwen2.5:3b, gemma2:9b)
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QProgressBar, QComboBox, QFileDialog, QGroupBox
)

from config.settings import SubtitleSettings
from core.hardware_profiler import HardwareProfiler
from workers.setup_worker import SetupWorker


class SetupManagerDialog(QDialog):
    """
    4-Row Dependency & Model Setup Manager with One-Click Auto-Install / Ollama Pull / Free Mode.
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
        self.resize(780, 440)
        self.ollama_url = ollama_url
        self.target_model = target_model
        self._worker: Optional[SetupWorker] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Hardware Profiler Summary Card (escaped && so Qt doesn't show _GPU)
        hw = HardwareProfiler.detect_hardware(force_refresh=True)
        hw_grp = QGroupBox("Detected Hardware && GPU Video Encoder")
        hw_lay = QHBoxLayout(hw_grp)
        self.lbl_hw_summary = QLabel(
            f"GPU: {hw['gpu_name']} ({hw['vram_gb']} GB VRAM)  |  "
            f"System RAM: {hw['ram_gb']} GB  |  "
            f"Active Encoder: {HardwareProfiler.get_encoder_badge_text()}"
        )
        self.lbl_hw_summary.setStyleSheet("color: #38BDF8; font-weight: 700; font-size: 12.5px;")
        hw_lay.addWidget(self.lbl_hw_summary)
        layout.addWidget(hw_grp)

        # 4-Row Checklist Grid (escaped && so Qt doesn't show _Local)
        chk_grp = QGroupBox("Runtime Dependencies && Local AI Models Checklist")
        grid = QGridLayout(chk_grp)
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(10)

        # Row 1: FFmpeg Binaries
        grid.addWidget(QLabel("1. FFmpeg && FFprobe Binaries:"), 0, 0)
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
        self.lbl_ai_detail.setStyleSheet("color: #9CA3AF; font-size: 11.5px;")
        grid.addWidget(self.lbl_ai_detail, 1, 2, 1, 2)

        # Row 3: Ollama Local Server
        grid.addWidget(QLabel("3. Ollama Local Server:"), 2, 0)
        self.pill_ollama = self._make_status_pill("Checking...")
        grid.addWidget(self.pill_ollama, 2, 1)
        self.btn_install_ollama = QPushButton("⬇️ Install / Start Ollama")
        self.btn_install_ollama.clicked.connect(self._on_install_or_start_ollama)
        grid.addWidget(self.btn_install_ollama, 2, 2)
        self.btn_recheck = QPushButton("🔄 Re-Check Server")
        self.btn_recheck.clicked.connect(self.run_audit)
        grid.addWidget(self.btn_recheck, 2, 3)

        # Row 4: Translation LLM Model
        grid.addWidget(QLabel("4. Translation Engine / Model:"), 3, 0)
        self.pill_model = self._make_status_pill("Checking...")
        grid.addWidget(self.pill_model, 3, 1)
        self.combo_pull_model = QComboBox()
        self.combo_pull_model.setEditable(True)
        self.combo_pull_model.addItems([
            "google-free (Built-in Free Translator - No Ollama Needed)",
            "qwen2.5:7b",
            "qwen2.5:3b",
            "gemma2:9b",
            "llama3.2:3b",
        ])
        if "google-free" in (self.target_model or "").lower():
            self.combo_pull_model.setCurrentIndex(0)
        else:
            self.combo_pull_model.setCurrentText(self.target_model)
        self.combo_pull_model.currentTextChanged.connect(lambda _t: self.run_audit())
        grid.addWidget(self.combo_pull_model, 3, 2)

        self.btn_pull_model = QPushButton("Activate / Pull Model")
        self.btn_pull_model.setObjectName("PrimaryCTA")
        self.btn_pull_model.clicked.connect(self._on_pull_model)
        grid.addWidget(self.btn_pull_model, 3, 3)

        layout.addWidget(chk_grp)

        # Progress bar & status
        self.lbl_progress = QLabel("Ready to verify system dependencies.")
        self.lbl_progress.setWordWrap(True)
        self.lbl_progress.setStyleSheet("color: #D1D5DB; font-weight: 500;")
        layout.addWidget(self.lbl_progress)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Bottom buttons
        footer = QHBoxLayout()
        btn_use_free = QPushButton("🌐 Use Built-in Free Translator (No Ollama Needed)")
        btn_use_free.setObjectName("SuccessCTA")
        btn_use_free.clicked.connect(self._on_switch_to_free_translator)
        footer.addWidget(btn_use_free)
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
        lbl.setFixedWidth(155)
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

    def _on_switch_to_free_translator(self) -> None:
        self.combo_pull_model.blockSignals(True)
        self.combo_pull_model.setCurrentIndex(0)
        self.combo_pull_model.blockSignals(False)
        SubtitleSettings.set("model_name", "google-free")
        SubtitleSettings.set("ai_provider", "Cloud API (Gemini / OpenAI)")
        self._style_pill(self.pill_model, True, "Built-in Ready", "")
        self.progress_bar.setValue(100)
        self.lbl_progress.setText("✅ បានប្តូរទៅប្រើ Free Google Translate (google-free) រួចរាល់ — អាចបកប្រែបានភ្លាមដោយមិនបាច់ដំឡើង Ollama!")
        self.health_updated.emit(True)

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

    def _on_install_or_start_ollama(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.btn_install_ollama.setEnabled(False)
        self._worker = SetupWorker(
            action="install_ollama",
            ollama_url=self.ollama_url,
            model_name=self.combo_pull_model.currentText().strip(),
            parent=self,
        )
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.audit_ready.connect(self._apply_audit_report)
        self._worker.task_finished.connect(lambda _ok, _m: self.btn_install_ollama.setEnabled(True))
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
        if "google-free" in model.lower():
            self._on_switch_to_free_translator()
            return
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

        ol_info = report.get("ollama_server", {})
        ol_ok = bool(ol_info.get("ok"))
        ol_installed = bool(ol_info.get("installed"))
        if ol_ok:
            self._style_pill(self.pill_ollama, True, "Online", "")
            self.btn_install_ollama.setText("✅ Ollama Running")
        elif ol_installed:
            self._style_pill(self.pill_ollama, False, "", "Stopped (Click Start)")
            self.btn_install_ollama.setText("▶️ Start Ollama Server")
        else:
            self._style_pill(self.pill_ollama, False, "", "Not Installed (Optional)")
            self.btn_install_ollama.setText("⬇️ Auto-Install Ollama")

        m_info = report.get("llm_model", {})
        m_ok = bool(m_info.get("ok"))
        is_free = bool(m_info.get("is_builtin_free"))
        if is_free:
            self._style_pill(self.pill_model, True, "Built-in Ready", "")
        else:
            self._style_pill(self.pill_model, m_ok, "Model Ready", "Not Pulled")

        self.health_updated.emit(bool(report.get("overall_healthy")))
