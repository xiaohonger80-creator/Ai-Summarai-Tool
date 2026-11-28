import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
        QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QComboBox,
        QGroupBox, QSplitter, QMessageBox, QAbstractItemView
    )
    from PyQt5.QtGui import QFont, QColor
except ImportError:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
        QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QComboBox,
        QGroupBox, QSplitter, QMessageBox, QAbstractItemView
    )
    from PySide6.QtGui import QFont, QColor

from config.settings import SubtitleSettings
from core.srt_exporter import SRTExporter
from core.translators.providers import UnifiedLLMClient
from workers.subtitle_worker import SubtitleWorker


class SubtitleStudioWidget(QWidget):
    """
    Complete Modular AI Video Subtitle Studio Desktop UI:
    Combines FunASR, Faster-Whisper, PaddleOCR, Story-Context translation, and Ollama/Cloud.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = SubtitleSettings.load()
        self.video_path: str = ""
        self.segments: List[Dict[str, Any]] = []
        self.worker: Optional[SubtitleWorker] = None

        self.setWindowTitle("AI Video Subtitle & Translation Studio")
        self.resize(1200, 750)
        self.setAcceptDrops(True)

        self._apply_dark_theme()
        self._build_ui()
        self._load_saved_settings()

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #121417;
                color: #E2E8F0;
                font-family: "Segoe UI", "Kantumruy Pro", sans-serif;
                font-size: 12px;
            }
            QGroupBox {
                background-color: #1B1F24;
                border: 1px solid #2D333B;
                border-radius: 8px;
                margin-top: 18px;
                padding: 12px;
                font-weight: 700;
                color: #60A5FA;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
                color: #60A5FA;
            }
            QPushButton {
                background-color: #2D333B;
                color: #F8FAFC;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #374151;
                border-color: #60A5FA;
            }
            QPushButton#PrimaryBtn {
                background-color: #2563EB;
                border-color: #3B82F6;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 700;
                padding: 8px 18px;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #1D4ED8;
            }
            QPushButton#DangerBtn {
                background-color: #DC2626;
                border-color: #EF4444;
                color: #FFFFFF;
            }
            QComboBox {
                background-color: #161A20;
                border: 1px solid #2D333B;
                border-radius: 6px;
                padding: 5px 8px;
                color: #F1F5F9;
                font-weight: 500;
            }
            QComboBox:focus {
                border-color: #3B82F6;
            }
            QComboBox QAbstractItemView {
                background-color: #161A20;
                color: #F1F5F9;
                selection-background-color: #2563EB;
                border: 1px solid #2D333B;
            }
            QTableWidget {
                background-color: #161A20;
                border: 1px solid #2D333B;
                border-radius: 8px;
                gridline-color: #242B35;
                color: #F8FAFC;
                selection-background-color: #1E3A8A;
            }
            QHeaderView::section {
                background-color: #1F242C;
                color: #94A3B8;
                font-weight: 700;
                padding: 6px;
                border: 1px solid #2D333B;
            }
            QProgressBar {
                background-color: #1B1F24;
                border: 1px solid #2D333B;
                border-radius: 6px;
                height: 14px;
                text-align: center;
                color: #FFFFFF;
                font-size: 10px;
                font-weight: 700;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 5px;
            }
        """)

    def _build_ui(self):
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(12, 12, 12, 12)
        root_lay.setSpacing(10)

        # =====================================================================
        # 1. TOP BAR (File Dropzone & Process Toggle)
        # =====================================================================
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.btn_select_video = QPushButton("📂 Open Video (Drop File Here)")
        self.btn_select_video.clicked.connect(self._on_choose_video)
        top_bar.addWidget(self.btn_select_video)

        self.lbl_video_info = QLabel("No video selected. Drop MP4, MKV, MOV, or AVI.")
        self.lbl_video_info.setStyleSheet("color: #94A3B8; font-weight: 500;")
        top_bar.addWidget(self.lbl_video_info, 1)

        self.lbl_badge = QLabel("⚡ Ready")
        self.lbl_badge.setStyleSheet("background: #1E293B; color: #38BDF8; padding: 4px 10px; border-radius: 6px; font-weight: 700;")
        top_bar.addWidget(self.lbl_badge)

        self.btn_start = QPushButton("▶ Start Processing")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.clicked.connect(self._toggle_processing)
        top_bar.addWidget(self.btn_start)

        root_lay.addLayout(top_bar)

        # =====================================================================
        # 2. LEFT / RIGHT SPLIT WORKSPACE
        # =====================================================================
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # Left 70%: Live Subtitle Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Timecode", "Original Chinese", "Translated Subtitle"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(2, 340)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._on_table_item_edited)
        splitter.addWidget(self.table)

        # Right 30%: Options Inspector Panel
        inspector = QWidget()
        insp_lay = QVBoxLayout(inspector)
        insp_lay.setContentsMargins(6, 0, 0, 0)
        insp_lay.setSpacing(12)

        grp_opts = QGroupBox("⚙ Extraction & AI Options")
        opts_lay = QVBoxLayout(grp_opts)
        opts_lay.setSpacing(10)

        # Extractor dropdown
        opts_lay.addWidget(QLabel("Extraction Engine:"))
        self.cb_extractor = QComboBox()
        self.cb_extractor.addItems([
            "Hybrid (OCR Primary + ASR Check)",
            "Hard-Subtitle OCR (PaddleOCR)",
            "Audio ASR (FunASR - Fast & Accurate)",
            "Audio ASR (Faster-Whisper Large-v3)",
        ])
        opts_lay.addWidget(self.cb_extractor)

        # Translator strategy dropdown
        opts_lay.addWidget(QLabel("Translation Strategy:"))
        self.cb_strategy = QComboBox()
        self.cb_strategy.addItems([
            "Story Context Mode (Movie/Drama Glossary)",
            "Fast Batch Mode (8 Lines/Batch)",
        ])
        opts_lay.addWidget(self.cb_strategy)

        # AI Provider
        opts_lay.addWidget(QLabel("AI Provider Backend:"))
        self.cb_provider = QComboBox()
        self.cb_provider.addItems([
            "100% Local Offline (Ollama)",
            "Cloud API (Gemini / OpenAI)",
        ])
        opts_lay.addWidget(self.cb_provider)

        # Model Selector
        lbl_mod = QHBoxLayout()
        lbl_mod.addWidget(QLabel("Model Name:"))
        btn_refresh_ollama = QPushButton("🔄 Refresh")
        btn_refresh_ollama.setFixedHeight(22)
        btn_refresh_ollama.clicked.connect(self._refresh_ollama_models)
        lbl_mod.addWidget(btn_refresh_ollama)
        opts_lay.addLayout(lbl_mod)

        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)
        self.cb_model.addItems(["qwen2.5:7b", "qwen2.5:14b", "gemma2:9b", "qwen2.5:3b", "gemini-2.5-flash", "gpt-4o-mini"])
        opts_lay.addWidget(self.cb_model)

        # Target Language
        opts_lay.addWidget(QLabel("Target Language:"))
        self.cb_target_lang = QComboBox()
        self.cb_target_lang.addItems([
            "Khmer (ភាសាខ្មែរ - Natural Spoken)",
            "English",
            "Thai",
            "Vietnamese",
        ])
        opts_lay.addWidget(self.cb_target_lang)

        insp_lay.addWidget(grp_opts)
        insp_lay.addStretch(1)

        splitter.addWidget(inspector)
        splitter.setSizes([850, 350])
        root_lay.addWidget(splitter, 1)

        # =====================================================================
        # 3. BOTTOM STATUS & EXPORT BAR
        # =====================================================================
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(10)

        v_status = QVBoxLayout()
        self.lbl_status = QLabel("Ready — Open a video to begin.")
        self.lbl_status.setStyleSheet("color: #94A3B8; font-size: 11.5px;")
        self.pbar = QProgressBar()
        self.pbar.setValue(0)
        v_status.addWidget(self.lbl_status)
        v_status.addWidget(self.pbar)
        bottom_bar.addLayout(v_status, 1)

        self.btn_export_translated = QPushButton("💾 Export Translated .SRT")
        self.btn_export_translated.clicked.connect(self._export_translated_srt)
        bottom_bar.addWidget(self.btn_export_translated)

        self.btn_export_bilingual = QPushButton("🌐 Export Bilingual .SRT")
        self.btn_export_bilingual.clicked.connect(self._export_bilingual_srt)
        bottom_bar.addWidget(self.btn_export_bilingual)

        root_lay.addLayout(bottom_bar)

    def _load_saved_settings(self):
        s = self.settings
        idx = self.cb_extractor.findText(s.get("extraction_engine", ""))
        if idx >= 0:
            self.cb_extractor.setCurrentIndex(idx)

        idx = self.cb_strategy.findText(s.get("translation_strategy", ""))
        if idx >= 0:
            self.cb_strategy.setCurrentIndex(idx)

        idx = self.cb_provider.findText(s.get("ai_provider", ""))
        if idx >= 0:
            self.cb_provider.setCurrentIndex(idx)

        self.cb_model.setCurrentText(s.get("model_name", "qwen2.5:7b"))

        idx = self.cb_target_lang.findText(s.get("target_language", ""))
        if idx >= 0:
            self.cb_target_lang.setCurrentIndex(idx)

    def _save_current_settings(self):
        self.settings["extraction_engine"] = self.cb_extractor.currentText()
        self.settings["translation_strategy"] = self.cb_strategy.currentText()
        self.settings["ai_provider"] = self.cb_provider.currentText()
        self.settings["model_name"] = self.cb_model.currentText()
        self.settings["target_language"] = self.cb_target_lang.currentText()
        SubtitleSettings.save(self.settings)

    def _refresh_ollama_models(self):
        models = UnifiedLLMClient.list_ollama_models(self.settings.get("ollama_url", "http://localhost:11434"))
        self.cb_model.clear()
        self.cb_model.addItems(models)
        self.lbl_status.setText(f"✓ Found {len(models)} models from local Ollama.")

    def _on_choose_video(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm);;All Files (*.*)"
        )
        if fpath:
            self._load_video(fpath)

    def _load_video(self, fpath: str):
        self.video_path = fpath
        p = Path(fpath)
        self.lbl_video_info.setText(f"🎬 {p.name} ({p.stat().st_size / (1024*1024):.1f} MB)")
        self.lbl_badge.setText("Ready to Process")
        self.lbl_status.setText(f"Loaded '{p.name}'. Click 'Start Processing' to extract and translate.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            fpath = urls[0].toLocalFile()
            if Path(fpath).suffix.lower() in (".mp4", ".mkv", ".mov", ".avi", ".webm"):
                self._load_video(fpath)

    def _toggle_processing(self):
        if self.worker and self.worker.isRunning():
            self.btn_start.setEnabled(False)
            self.lbl_status.setText("⏹ Cancelling gracefully...")
            self.worker.request_cancel()
            return

        if not self.video_path or not Path(self.video_path).exists():
            QMessageBox.warning(self, "No Video", "Please open or drag-and-drop a video file first!")
            return

        self._save_current_settings()
        self.btn_start.setText("⏹ Cancel")
        self.btn_start.setObjectName("DangerBtn")
        self.btn_start.setStyle(self.btn_start.style())
        self.pbar.setValue(2)

        self.worker = SubtitleWorker(
            video_path=self.video_path,
            extraction_engine=self.cb_extractor.currentText(),
            translation_strategy=self.cb_strategy.currentText(),
            ai_provider=self.cb_provider.currentText(),
            model_name=self.cb_model.currentText(),
            target_language=self.cb_target_lang.currentText(),
            settings=self.settings,
        )
        self.worker.progress_updated.connect(self._on_worker_progress)
        self.worker.extraction_done.connect(self._on_extraction_done)
        self.worker.all_completed.connect(self._on_all_completed)
        self.worker.error_occurred.connect(self._on_worker_error)
        self.worker.stopped.connect(self._on_worker_stopped)
        self.worker.start()

    def _on_worker_progress(self, pct: int, msg: str):
        self.pbar.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_extraction_done(self, segments: list):
        self.segments = segments
        self._populate_table(segments)

    def _on_all_completed(self, segments: list, msg: str):
        self.segments = segments
        self._populate_table(segments)
        self._reset_process_button()
        self.pbar.setValue(100)
        self.lbl_status.setText(msg)
        QMessageBox.information(self, "Done", f"Subtitle Processing Finished!\n{len(segments)} segments ready to export.")

    def _on_worker_error(self, err_msg: str):
        self._reset_process_button()
        self.pbar.setValue(0)
        self.lbl_status.setText(f"❌ {err_msg}")
        QMessageBox.critical(self, "Error", err_msg)

    def _on_worker_stopped(self):
        self._reset_process_button()
        self.lbl_status.setText("⏹ Cancelled by user.")

    def _reset_process_button(self):
        self.btn_start.setText("▶ Start Processing")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.setEnabled(True)
        self.btn_start.setStyle(self.btn_start.style())

    def _populate_table(self, segments: list):
        self.table.blockSignals(True)
        self.table.setRowCount(len(segments))
        for r_idx, s in enumerate(segments):
            # 0: #
            it_num = QTableWidgetItem(str(s.get("id", r_idx + 1)))
            it_num.setTextAlignment(Qt.AlignCenter)
            it_num.setFlags(it_num.flags() & ~Qt.ItemIsEditable)

            # 1: Timecode
            s_sec = float(s.get("start", 0.0))
            e_sec = float(s.get("end", 0.0))
            s_mins, s_secs = int(s_sec // 60), int(s_sec % 60)
            e_mins, e_secs = int(e_sec // 60), int(e_sec % 60)
            tc_str = f"{s_mins:02d}:{s_secs:02d} -> {e_mins:02d}:{e_secs:02d}"
            it_tc = QTableWidgetItem(tc_str)
            it_tc.setTextAlignment(Qt.AlignCenter)
            it_tc.setFlags(it_tc.flags() & ~Qt.ItemIsEditable)

            # 2: Original Chinese
            it_orig = QTableWidgetItem(s.get("text", ""))

            # 3: Translated Subtitle
            it_trans = QTableWidgetItem(s.get("translated", ""))
            it_trans.setForeground(QColor("#38BDF8"))

            self.table.setItem(r_idx, 0, it_num)
            self.table.setItem(r_idx, 1, it_tc)
            self.table.setItem(r_idx, 2, it_orig)
            self.table.setItem(r_idx, 3, it_trans)

        self.table.blockSignals(False)

    def _on_table_item_edited(self, item: QTableWidgetItem):
        row = item.row()
        col = item.column()
        if 0 <= row < len(self.segments):
            if col == 2:
                self.segments[row]["text"] = item.text().strip()
            elif col == 3:
                self.segments[row]["translated"] = item.text().strip()

    def _export_translated_srt(self):
        if not self.segments:
            QMessageBox.warning(self, "No Subtitles", "No subtitle segments available to export!")
            return
        default_name = f"{Path(self.video_path).stem}_translated.srt" if self.video_path else "subtitles_translated.srt"
        out_p, _ = QFileDialog.getSaveFileName(self, "Export Translated .SRT", default_name, "SubRip Subtitles (*.srt)")
        if out_p:
            saved = SRTExporter.export_translated_only(self.segments, out_p)
            QMessageBox.information(self, "Exported", f"Successfully saved translated .SRT to:\n{saved}")

    def _export_bilingual_srt(self):
        if not self.segments:
            QMessageBox.warning(self, "No Subtitles", "No subtitle segments available to export!")
            return
        default_name = f"{Path(self.video_path).stem}_bilingual.srt" if self.video_path else "subtitles_bilingual.srt"
        out_p, _ = QFileDialog.getSaveFileName(self, "Export Bilingual .SRT", default_name, "SubRip Subtitles (*.srt)")
        if out_p:
            saved = SRTExporter.export_bilingual(self.segments, out_p)
            QMessageBox.information(self, "Exported", f"Successfully saved bilingual .SRT to:\n{saved}")
