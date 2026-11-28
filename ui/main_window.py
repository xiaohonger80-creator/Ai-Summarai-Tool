import re
import shutil
import threading
import time
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QEvent, QTimer, QPoint
from PySide6.QtGui import QIcon, QPixmap, QFont, QColor, QBrush, QCursor, QPainter
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QComboBox, QProgressBar, QLabel, QLineEdit, QMessageBox,
    QDialog, QFormLayout, QFrame, QStackedWidget, QStackedLayout, QMenu, QSlider, QSplitter, QSpinBox,
    QPlainTextEdit, QTextEdit, QAbstractItemView, QInputDialog
)
from core.database import Database
from core.long_video_engine import LongVideoStreamEngine
from core.media_engine import MediaEngine
from core.srt_handler import SRTHandler
from ui.i18n import tr
from ui.theme import THEMES, build_stylesheet, apply_app_palette
from ui.video_editor import VideoPreviewEditor
from ui.batch_dialog import BatchDubbingDialog
from ui.timeline_widget import CapCutTimelineWidget
from ui.multi_clip_dialog import MultiClipComposerDialog

# Static default voices to avoid importing heavy AI modules at startup
DEFAULT_VOICES = {
    "Female (Sreymom)": "female",
    "Male (Piseth)": "male",
    "Somleng Khmer Female (Telecom)": "somleng_female",
    "Somleng Khmer Male (Telecom)": "somleng_male",
}
from ui.glossary_dialog import GlossaryDialog
from ui.find_replace_dialog import FindReplaceDialog
from ui.updater_dialog import PackageUpdaterDialog
from ui.social_link_dialog import SocialLinkImportDialog
from core.license_manager import get_active_license_status
from ui.license_dialog import LicenseActivationDialog
from ui.export_dialog import ExportVideoDialog
from ui.workflow_view import WorkflowViewDialog


class PipelineWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)
    stopped = Signal(str)

    def __init__(self, task_fn):
        super().__init__()
        self.task_fn = task_fn

    def _emit_progress(self, pct: int, msg: str):
        if self.isInterruptionRequested():
            raise InterruptedError("⏹ បានបញ្ឈប់ដោយសុវត្ថិភាព — ទិន្នន័យដែលធ្វើរួចត្រូវបានរក្សាទុក!")
        self.progress.emit(pct, msg)

    def run(self):
        try:
            msg = self.task_fn(self._emit_progress)
            if self.isInterruptionRequested():
                self.stopped.emit("⏹ បានបញ្ឈប់ដោយសុវត្ថិភាព — ទិន្នន័យដែលធ្វើរួចត្រូវបានរក្សាទុក!")
            else:
                self.finished_ok.emit(msg)
        except InterruptedError as ie:
            self.stopped.emit(str(ie))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(f"កំហុសដំណើរការ (Process Error): {e}")


class SettingsDialog(QDialog):
    """Bilingual popup for Cloud API or Local Ollama/Whisper settings."""
    def __init__(self, db: Database, lang: str = "en", parent=None):
        super().__init__(parent)
        self.db = db
        self.lang = lang
        self.setWindowTitle(tr(lang, "dlg_title"))
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "Custom / Saved",
            "Free Google Translate (No API Key Needed)",
            "Local Ollama (Free, Offline)",
            "OpenAI API",
            "Google Gemini API (OpenAI-Compatible)"
        ])
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)

        saved_api_url = self.db.get_setting("api_url", "google-free")
        self.api_url = QLineEdit(saved_api_url)

        api_key_widget = QWidget()
        api_key_container = QVBoxLayout(api_key_widget)
        api_key_container.setContentsMargins(0, 0, 0, 0)
        api_key_container.setSpacing(6)
        self.api_key = QPlainTextEdit()
        self.api_key.setMinimumWidth(0)
        self.api_key.setFixedHeight(78)
        self.api_key.setPlaceholderText(
            "Paste 1 or more Gemini / OpenAI API Keys (1 key per line for Round-Robin & 429 Auto-Failover)\n"
            "Leave empty for Free Google Translate or Local Ollama"
        )
        self.api_key.setStyleSheet(
            "background: #141820; border: 1px solid #343B4C; border-radius: 6px; "
            "padding: 5px 8px; color: #F4F6FB; font-family: 'Consolas', monospace; font-size: 11.5px;"
        )
        saved_keys_list = self.db.get_api_keys()
        if saved_keys_list:
            self.api_key.setPlainText("\n".join(saved_keys_list))
        self.api_key.textChanged.connect(self._update_key_pool_badge)

        pool_bar = QHBoxLayout()
        pool_bar.setContentsMargins(0, 0, 0, 0)
        pool_bar.setSpacing(8)
        self.lbl_pool_count = QLabel("")
        self.lbl_pool_count.setWordWrap(True)
        self.lbl_pool_count.setStyleSheet("font-size: 10.5px; color: #34D399; font-weight: 600;")

        self.btn_pool = QPushButton("🔑 Test / Pool")
        self.btn_pool.setToolTip("សាកល្បង និងគ្រប់គ្រង Multi-API Key Pool (Round-Robin & 429 Auto-Failover)")
        self.btn_pool.clicked.connect(self._open_api_pool)
        pool_bar.addWidget(self.lbl_pool_count, 1)
        pool_bar.addWidget(self.btn_pool)

        api_key_container.addWidget(self.api_key)
        api_key_container.addLayout(pool_bar)
        self._update_key_pool_badge()

        saved_model = self.db.get_setting("model", "google-free")
        if not saved_model or saved_model.strip() == "":
            saved_model = "google-free" if (saved_api_url.lower() == "google-free" or not saved_keys_list) else "gemini-2.5-flash"

        # AI Models Dropdown: Latest & Recommended Models (Gemini, Local Ollama, OpenAI, Groq)
        RECOMMENDED_MODELS = [
            ("🌐 google-free (Free Google Translate - No API Key Needed / មិនគិតថ្លៃ)", "google-free"),
            ("⚡ gemini-2.5-flash (Google Flagship Ultra-Fast / ឆ្លាតវៃ & លឿន)", "gemini-2.5-flash"),
            ("✨ gemini-2.0-flash (Google Standard Flash / ស្ថិរភាពខ្ពស់)", "gemini-2.0-flash"),
            ("🚀 gemini-1.5-flash (Google Long Context / សន្សំ Quota)", "gemini-1.5-flash"),
            ("✨ gemini-3.1-flash-lite (Experimental / ម៉ូដែលសាកល្បង)", "gemini-3.1-flash-lite"),
            ("🦙 qwen2.5:7b (⭐ Recommended Local Ollama for Chinese / ម៉ូដែលចិន-ខ្មែរល្អដាច់គេ)", "qwen2.5:7b"),
            ("🦙 qwen2.5:3b (Fast & Lightweight Local / ស្រាលសម្រាប់ PC ខ្សោយ)", "qwen2.5:3b"),
            ("🦙 qwen2.5:14b (Studio High Accuracy / ភាពសុក្រិតខ្ពស់)", "qwen2.5:14b"),
            ("💎 gemma2:9b (Google Local Ollama / ម៉ូដែល Google ក្នុងស្រុក)", "gemma2:9b"),
            ("🦙 llama3.2:3b (Ultra Low-RAM Local / ស្រាលបំផុត)", "llama3.2:3b"),
            ("🚀 gpt-4o-mini (OpenAI Fast & Cost-Effective)", "gpt-4o-mini"),
            ("👑 gpt-4o (OpenAI Flagship Studio Quality)", "gpt-4o"),
            ("⚡ llama-3.3-70b-versatile (Groq Ultra Fast)", "llama-3.3-70b-versatile"),
        ]

        self.model_name = QComboBox()
        self.model_name.setEditable(True)
        self.model_name.setInsertPolicy(QComboBox.NoInsert)
        self.model_name.setFixedHeight(30)
        self.model_name.setStyleSheet("""
            QComboBox {
                background: #161920;
                border: 1.5px solid #343B4C;
                border-radius: 6px;
                padding: 3px 28px 3px 10px;
                color: #F4F6FB;
                font-size: 11.5px;
                font-weight: 600;
            }
            QComboBox:focus, QComboBox:hover {
                border-color: #00E5FF;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #252A36;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: #1A1F2C;
            }
            QComboBox::down-arrow {
                width: 0;
                height: 0;
                border-left: 4.5px solid transparent;
                border-right: 4.5px solid transparent;
                border-top: 5.5px solid #00E5FF;
            }
            QComboBox QAbstractItemView {
                background: #161920;
                color: #F4F6FB;
                selection-background-color: #00E5FF;
                selection-color: #0B0D10;
                border: 1px solid #343B4C;
                outline: none;
                padding: 4px;
            }
        """)
        for label, mid in RECOMMENDED_MODELS:
            self.model_name.addItem(label, mid)

        matched_idx = -1
        for i in range(self.model_name.count()):
            if self.model_name.itemData(i) == saved_model:
                matched_idx = i
                break
        if matched_idx >= 0:
            self.model_name.setCurrentIndex(matched_idx)
        else:
            self.model_name.insertItem(0, f"⚙️ {saved_model} (Custom / Saved)", saved_model)
            self.model_name.setCurrentIndex(0)

        # Auto-detect preset index
        self.preset_combo.blockSignals(True)
        if saved_api_url.lower() == "google-free" or saved_model.lower() == "google-free":
            self.preset_combo.setCurrentIndex(1)
            if saved_api_url.lower() == "google-free" and not saved_keys_list:
                saved_model = "google-free"
        elif "localhost" in saved_api_url or "127.0.0.1" in saved_api_url:
            self.preset_combo.setCurrentIndex(2)
        elif "api.openai.com" in saved_api_url:
            self.preset_combo.setCurrentIndex(3)
        elif "googleapis.com" in saved_api_url:
            self.preset_combo.setCurrentIndex(4)
        else:
            self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

        # Ensure model dropdown matches if google-free
        if saved_api_url.lower() == "google-free" and not saved_keys_list:
            self._set_model_by_id("google-free")

        self.api_url.textChanged.connect(self._on_api_url_changed)
        self.model_name.currentIndexChanged.connect(self._on_model_changed)

        self.asr_combo = QComboBox()
        self.asr_combo.addItems(["Local Whisper (int8 CPU - Low RAM)", "Cloud Whisper API"])
        self.asr_combo.setCurrentIndex(int(self.db.get_setting("asr_mode", "0")))

        self.voice_combo = QComboBox()
        self.voice_combo.addItems(list(DEFAULT_VOICES.keys()))
        saved_voice = self.db.get_setting("kh_voice_label", "Female (Sreymom)")
        if saved_voice in DEFAULT_VOICES:
            self.voice_combo.setCurrentText(saved_voice)

        self.ocr_y_spin = QSpinBox()
        self.ocr_y_spin.setRange(0, 90)
        self.ocr_y_spin.setSuffix("%")
        self.ocr_y_spin.setValue(int(self.db.get_setting("ocr_y_pct", "72")))

        self.ocr_h_spin = QSpinBox()
        self.ocr_h_spin.setRange(8, 60)
        self.ocr_h_spin.setSuffix("%")
        self.ocr_h_spin.setValue(int(self.db.get_setting("ocr_h_pct", "28")))

        form.addRow(tr(lang, "lbl_preset"), self.preset_combo)
        form.addRow(tr(lang, "lbl_url"), self.api_url)
        form.addRow(tr(lang, "lbl_key"), api_key_widget)
        form.addRow(tr(lang, "lbl_model"), self.model_name)
        form.addRow(tr(lang, "lbl_asr"), self.asr_combo)
        form.addRow(tr(lang, "lbl_voice"), self.voice_combo)
        form.addRow(tr(lang, "lbl_ocr_y"), self.ocr_y_spin)
        form.addRow(tr(lang, "lbl_ocr_h"), self.ocr_h_spin)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton(tr(lang, "btn_cancel"))
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr(lang, "btn_save"))
        save_btn.setObjectName("PrimaryBtn")
        save_btn.clicked.connect(self._save)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    def _update_key_pool_badge(self):
        raw = self.api_key.toPlainText().strip()
        keys = [k.strip() for k in re.split(r"[\r\n,;]+", raw) if k.strip()]
        n = len(dict.fromkeys(keys))
        if n == 0:
            self.lbl_pool_count.setText("⚪ 0 Keys (Free Google Translate / Local Ollama)")
            self.lbl_pool_count.setStyleSheet("font-size: 10.5px; color: #94A3B8;")
        elif n == 1:
            self.lbl_pool_count.setText("🔑 1 Key Active (បន្ថែម ១ បន្ទាត់ទៀតដើម្បីបើក Round-Robin & 429 Failover)")
            self.lbl_pool_count.setStyleSheet("font-size: 10.5px; color: #38BDF8; font-weight: 600;")
        else:
            self.lbl_pool_count.setText(f"🔄 {n} Keys Active — Auto Round-Robin & Instant 429 Failover Ready!")
            self.lbl_pool_count.setStyleSheet("font-size: 10.5px; color: #34D399; font-weight: 700;")

    def _open_api_pool(self):
        from ui.api_pool_dialog import APIKeyPoolDialog
        self.db.set_api_keys(self.api_key.toPlainText())
        dlg = APIKeyPoolDialog(self.db, parent=self, lang=self.lang)
        dlg.keys_saved.connect(self._on_pool_keys_saved)
        dlg.exec()

    def _on_pool_keys_saved(self, keys_str: str):
        self.api_key.setPlainText(keys_str)

    def _get_current_model(self) -> str:
        idx = self.model_name.currentIndex()
        if idx >= 0:
            data = self.model_name.itemData(idx)
            if data:
                return str(data).strip()
        raw = self.model_name.currentText().strip()
        if raw:
            token = re.split(r"[\s\(\[\{]+", raw)[0].strip()
            token = re.sub(r"^[^\w\-:\.]+", "", token)
            return token or raw
        return "google-free" if self.api_url.text().strip().lower() == "google-free" else "gemini-2.5-flash"

    def _set_model_by_id(self, model_id: str):
        for i in range(self.model_name.count()):
            if self.model_name.itemData(i) == model_id:
                self.model_name.setCurrentIndex(i)
                return
        self.model_name.setEditText(model_id)

    def _apply_preset(self, idx: int):
        if idx == 1:
            self.api_url.setText("google-free")
            self.api_key.clear()
            self._set_model_by_id("google-free")
        elif idx == 2:
            self.api_url.setText("http://localhost:11434/v1")
            self.api_key.clear()
            self._set_model_by_id("qwen2.5:7b")
        elif idx == 3:
            self.api_url.setText("https://api.openai.com/v1")
            self._set_model_by_id("gpt-4o-mini")
        elif idx == 4:
            self.api_url.setText("https://generativelanguage.googleapis.com/v1beta/openai/")
            self._set_model_by_id("gemini-2.5-flash")

    def _on_api_url_changed(self, text: str):
        url = text.strip().lower()
        if url == "google-free":
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(1)
            self.preset_combo.blockSignals(False)
            self._set_model_by_id("google-free")
        elif "localhost" in url or "127.0.0.1" in url:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(2)
            self.preset_combo.blockSignals(False)
        elif "googleapis.com" in url:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(4)
            self.preset_combo.blockSignals(False)
        elif "openai.com" in url:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(3)
            self.preset_combo.blockSignals(False)

    def _on_model_changed(self, idx: int):
        mid = self.model_name.itemData(idx)
        if not mid:
            return
        mid_str = str(mid).lower()
        cur_url = self.api_url.text().strip().lower()
        if mid_str == "google-free":
            if cur_url != "google-free":
                self.api_url.setText("google-free")
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(1)
                self.preset_combo.blockSignals(False)
        elif mid_str.startswith("gemini"):
            if cur_url == "google-free" or cur_url == "":
                self.api_url.setText("https://generativelanguage.googleapis.com/v1beta/openai/")
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(4)
                self.preset_combo.blockSignals(False)
        elif mid_str.startswith("qwen") or mid_str.startswith("llama") or mid_str.startswith("gemma"):
            if cur_url == "google-free" or cur_url == "":
                self.api_url.setText("http://localhost:11434/v1")
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(2)
                self.preset_combo.blockSignals(False)
        elif mid_str.startswith("gpt-"):
            if cur_url == "google-free" or cur_url == "":
                self.api_url.setText("https://api.openai.com/v1")
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(3)
                self.preset_combo.blockSignals(False)

    def _save(self):
        try:
            final_url = self.api_url.text().strip()
            final_model = self._get_current_model()
            if final_url.lower() == "google-free":
                final_model = "google-free"
            self.db.set_setting("api_url", final_url)
            self.db.set_api_keys(self.api_key.toPlainText())
            self.db.set_setting("model", final_model)
            self.db.set_setting("asr_mode", str(self.asr_combo.currentIndex()))
            self.db.set_setting("kh_voice_label", self.voice_combo.currentText())
            self.db.set_setting("ocr_y_pct", str(self.ocr_y_spin.value()))
            self.db.set_setting("ocr_h_pct", str(self.ocr_h_spin.value()))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"មិនអាចរក្សាទុកការកំណត់បានទេ: {e}")


class RecentProjectsDialog(QDialog):
    """Modal dialog to browse, reopen, or delete saved SQLite dubbing projects."""
    def __init__(self, db: Database, lang: str = "en", parent=None):
        super().__init__(parent)
        self.db = db
        self.lang = lang
        self.selected_project = None

        self.setWindowTitle(tr(lang, "proj_dlg_title"))
        self.resize(720, 420)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.table = QTableWidget(0, 5)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setHorizontalHeaderLabels([
            "ID",
            tr(lang, "proj_col_name"),
            tr(lang, "proj_col_lines"),
            tr(lang, "proj_col_date"),
            tr(lang, "proj_col_file"),
        ])
        self.table.setColumnHidden(0, True)
        self.table.setColumnWidth(2, 75)
        self.table.setColumnWidth(3, 145)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._accept_selected)
        layout.addWidget(self.table)

        btns = QHBoxLayout()
        self.btn_delete = QPushButton(tr(lang, "btn_del_proj"))
        self.btn_delete.clicked.connect(self._delete_selected)

        btns.addWidget(self.btn_delete)
        btns.addStretch()

        btn_cancel = QPushButton(tr(lang, "btn_cancel"))
        btn_cancel.clicked.connect(self.reject)

        self.btn_open = QPushButton(tr(lang, "btn_load_proj"))
        self.btn_open.setObjectName("PrimaryBtn")
        self.btn_open.clicked.connect(self._accept_selected)

        btns.addWidget(btn_cancel)
        btns.addWidget(self.btn_open)
        layout.addLayout(btns)

        self._populate()

    def _populate(self):
        self.projects = self.db.list_projects()
        self.table.setRowCount(len(self.projects))
        for row, p in enumerate(self.projects):
            vpath = p.get("video_path") or ""
            exists = bool(vpath and Path(vpath).exists())
            file_display = Path(vpath).name if exists else (f"⚠ Missing: {Path(vpath).name}" if vpath else "SRT Only")

            lines_item = QTableWidgetItem(str(p["line_count"]))
            lines_item.setTextAlignment(Qt.AlignCenter)

            date_item = QTableWidgetItem(str(p["created_at"])[:16])
            date_item.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(row, 0, QTableWidgetItem(str(p["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(p["name"]))
            self.table.setItem(row, 2, lines_item)
            self.table.setItem(row, 3, date_item)
            self.table.setItem(row, 4, QTableWidgetItem(file_display))

        if self.projects:
            self.table.selectRow(0)

    def _accept_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.projects):
            return
        self.selected_project = self.projects[row]
        self.accept()

    def _delete_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.projects):
            return
        proj = self.projects[row]
        self.db.delete_project(proj["id"])
        # Clean up cached audio/frames folder to keep low-spec disk space free
        shutil.rmtree(f"data/workspace/proj_{proj['id']}", ignore_errors=True)
        self._populate()


class AICaptionDialog(QDialog):
    """Generates Viral Khmer Title, Hook, Description & Hashtags ready to copy-paste."""
    def __init__(self, caption_text: str, lang: str = "en", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr(lang, "tools_caption"))
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit(caption_text)
        self.editor.setStyleSheet(
            "background-color: #161A23; color: #F8FAFC; border: 1px solid #262C3A; "
            "border-radius: 8px; padding: 10px; font-size: 13px;"
        )
        layout.addWidget(self.editor, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_copy = QPushButton("📋 Copy All")
        btn_copy.setObjectName("BtnGreen")
        btn_copy.clicked.connect(lambda: (QApplication.clipboard().setText(self.editor.toPlainText()), self.accept()))
        btn_close = QPushButton(tr(lang, "btn_cancel"))
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_close)
        btns.addWidget(btn_copy)
        layout.addLayout(btns)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.lang = self.db.get_setting("ui_lang", "en")
        self.project_id = None
        self.video_path = ""
        self._clip_markers = []
        self.worker = None
        self._cancel_event = threading.Event()
        self._hw_encoder_label = "🚀 Fast Engine"

        # Lightweight Audio Preview Player for individual row TTS playback
        self.row_player = QMediaPlayer(self)
        self.row_audio_out = QAudioOutput(self)
        self.row_audio_out.setVolume(1.0)
        self.row_player.setAudioOutput(self.row_audio_out)

        self.setMinimumSize(1024, 640)
        self.resize(1180, 700)
        self.setAcceptDrops(True)

        self._bg_pixmap = None
        bg_candidate = Path("assets/app_bg_blurred.jpg")
        if bg_candidate.exists():
            self._bg_pixmap = QPixmap(str(bg_candidate))

        self._build_ui()
        try:
            apply_app_palette(QApplication.instance(), self.db.get_setting("ui_theme", "capcut"))
        except Exception:
            pass
        self._apply_language()
        self._probe_encoder_async()

        # Real-time System Hardware Performance Monitor (CPU, RAM, GPU)
        from core.system_monitor import SystemMonitorWorker
        self.sys_monitor = SystemMonitorWorker(self)
        self.sys_monitor.metrics_updated.connect(self._on_sys_metrics_updated)
        self.sys_monitor.start()

        QApplication.instance().installEventFilter(self)
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setSingleShot(True)
        self._update_check_timer.timeout.connect(self._check_update_silently)
        self._update_check_timer.start(2500)

    def _on_sys_metrics_updated(self, badge_text: str, tooltip_text: str):
        if hasattr(self, "lbl_encoder"):
            self.lbl_encoder.setText(badge_text)
            self.lbl_encoder.setToolTip(tooltip_text)
        wf = getattr(self, "_workflow_dialog", None)
        if wf is not None:
            try:
                wf.update_hw_metrics(badge_text)
            except Exception:
                pass

    def closeEvent(self, event):
        wf = getattr(self, "_workflow_dialog", None)
        if wf is not None:
            try:
                wf.close()
            except Exception:
                pass
        if hasattr(self, "_update_check_timer"):
            try:
                self._update_check_timer.stop()
            except Exception:
                pass
        if hasattr(self, "_cancel_event"):
            self._cancel_event.set()
        try:
            MediaEngine.cancel_all_processes()
        except Exception:
            pass
        for attr in ("worker", "_probe_thread"):
            th = getattr(self, attr, None)
            if th is not None:
                try:
                    if th.isRunning():
                        th.requestInterruption()
                        th.quit()
                        if not th.wait(3000):
                            th.terminate()
                            th.wait(500)
                except Exception:
                    pass
        if hasattr(self, "sys_monitor") and self.sys_monitor.isRunning():
            self.sys_monitor.stop()
            if not self.sys_monitor.wait(2500):
                self.sys_monitor.terminate()
                self.sys_monitor.wait(500)
        try:
            if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
                self.video_editor.player.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "db") and self.db is not None:
                self.db.close()
        except Exception:
            pass
        super().closeEvent(event)

    def paintEvent(self, event):
        if hasattr(self, "_bg_pixmap") and self._bg_pixmap and not self._bg_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(self.rect(), self._bg_pixmap)
            # Luxury dark translucent tint (#0B0D10DE) so text and timeline maintain 100% clarity
            painter.fillRect(self.rect(), QColor(11, 13, 16, 210))
            painter.end()
        super().paintEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            # ពិនិត្យមើលថាតើអ្នកកំពុងវាយអក្សរក្នុងប្រអប់ Input ឬកំពុងកែ Cell ក្នុងតារាងឬអត់
            focus_w = QApplication.focusWidget()
            is_typing = (
                isinstance(focus_w, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox))
                or self.table.state() == QAbstractItemView.EditingState
            )

            key = event.key()
            mods = event.modifiers()

            # 1. Ctrl + Space៖ លេង/ផ្អាក (Play/Pause) បានគ្រប់ពេល ទោះកំពុងវាយអក្សរក៏ដោយ
            if key == Qt.Key_Space and (mods & Qt.ControlModifier):
                self.video_editor.toggle_play()
                return True

            # 2. បើមិនកំពុងវាយអក្សរទេ អនុញ្ញាតឲ្យប្រើក្តារចុចបញ្ជាវីដេអូពេញលេញដូច CapCut!
            if not is_typing:
                if key == Qt.Key_Space or key == Qt.Key_K:
                    # Play / Pause
                    self.video_editor.toggle_play()
                    return True

                elif key == Qt.Key_Left:
                    if mods & Qt.ShiftModifier:
                        # Shift + Left៖ ខារថយក្រោយលឿន 5 វិនាទី
                        self.video_editor.step_ms(-5000)
                    elif mods & Qt.ControlModifier:
                        # Ctrl + Left៖ លោតទៅជួរអត្ថបទមុន (|<)
                        self.video_editor.prev_segment()
                    else:
                        # Left Arrow៖ ខារថយក្រោយ 2 វិនាទី (<)
                        self.video_editor.step_ms(-2000)
                    return True

                elif key == Qt.Key_Right:
                    if mods & Qt.ShiftModifier:
                        # Shift + Right៖ ខារទៅមុខលឿន 5 វិនាទី
                        self.video_editor.step_ms(5000)
                    elif mods & Qt.ControlModifier:
                        # Ctrl + Right៖ លោតទៅជួរបន្ទាប់ (>|)
                        self.video_editor.next_segment()
                    else:
                        # Right Arrow៖ ខារទៅមុខ 2 វិនាទី (>)
                        self.video_editor.step_ms(2000)
                    return True

                elif key == Qt.Key_J:
                    # J៖ ខារថយក្រោយ 3 វិនាទី (ស្តង់ដារកាត់ត CapCut/Premiere)
                    self.video_editor.step_ms(-3000)
                    return True

                elif key == Qt.Key_L:
                    # L៖ ខារទៅមុខ 3 វិនាទី (ស្តង់ដារកាត់ត CapCut/Premiere)
                    self.video_editor.step_ms(3000)
                    return True

                elif key == Qt.Key_Comma:
                    # គ្រាប់ចុច < (,)៖ ថយក្រោយ 1 ហ្វ្រេម / 0.1 វិនាទី (ស៊ីម៉ោងឲ្យចំបបូរមាត់)
                    self.video_editor.step_ms(-100)
                    return True

                elif key == Qt.Key_Period:
                    # គ្រាប់ចុច > (.)៖ ទៅមុខ 1 ហ្វ្រេម / 0.1 វិនាទី
                    self.video_editor.step_ms(100)
                    return True

                elif key == Qt.Key_Home:
                    # Home៖ ត្រឡប់ទៅដើមវីដេអូ 00:00
                    self.video_editor.seek_to_ms(0)
                    return True

        return super().eventFilter(obj, event)

    def _set_short_filename(self, filename: str):
        elided = self.lbl_file.fontMetrics().elidedText(filename, Qt.ElideMiddle, 175)
        self.lbl_file.setText(elided)
        self.lbl_file.setToolTip(filename)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # =====================================================================
        # 1. CAPCUT TOP HEADER BAR (44px Fixed Height — Zero Overflow)
        # =====================================================================
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(44)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 4, 12, 4)
        top_layout.setSpacing(8)

        # 1A. Left Group: Logo + Title + Filename Pill + GPU Status Badge
        logo_path = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
        if logo_path.exists():
            self.lbl_logo = QLabel()
            pix = QPixmap(str(logo_path)).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_logo.setPixmap(pix)
            top_layout.addWidget(self.lbl_logo)

        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("AppTitle")
        self.lbl_title.setMinimumWidth(148)
        top_layout.addWidget(self.lbl_title)

        self.lbl_file = QLabel()
        self.lbl_file.setObjectName("FilePill")
        self.lbl_file.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.lbl_file.setFixedHeight(28)
        self.lbl_file.setMaximumWidth(205)
        top_layout.addWidget(self.lbl_file)

        self.lbl_encoder = QLabel(tr(self.lang, "mode_fast_copy"))
        self.lbl_encoder.setStyleSheet(
            "background-color: #181C24; color: #00E5FF; border: 1px solid #252A36; "
            "border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 700;"
        )
        top_layout.addWidget(self.lbl_encoder)

        # Extracted Quick-Action Buttons directly on Top Bar (Re-do Workflow, All-in-One Studio, VideoFX, Setup & AI)
        self.btn_top_redo = QPushButton("🔄 កំណត់ឡើងវិញ" if self.lang == "kh" else "🔄 Re-do / Reset")
        self.btn_top_redo.setObjectName("BtnGlass")
        self.btn_top_redo.setFixedHeight(30)
        self.btn_top_redo.setStyleSheet(
            "QPushButton { background: #1F1624; border: 1.5px solid #F59E0B; border-radius: 6px; "
            "padding: 2px 10px; color: #FBBF24; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #3B2314; border-color: #FDE68A; color: #FFFFFF; }"
        )
        self.btn_top_redo.setToolTip("🔄 កំណត់ឡើងវិញ / Re-do Workflow (Reset Steps — លុប ឬធ្វើឡើងវិញតាមជំហាន)")
        self.btn_top_redo.clicked.connect(self._open_reset_project_dialog)
        top_layout.addWidget(self.btn_top_redo)

        self.btn_top_aio = QPushButton("🚀 AI Studio")
        self.btn_top_aio.setObjectName("BtnGlass")
        self.btn_top_aio.setFixedHeight(30)
        self.btn_top_aio.setStyleSheet(
            "QPushButton { background: #132238; border: 1.5px solid #3B82F6; border-radius: 6px; "
            "padding: 2px 10px; color: #60A5FA; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #1E3A8A; border-color: #93C5FD; color: #FFFFFF; }"
        )
        self.btn_top_aio.setToolTip("🚀 បើកផ្ទាំង All-in-One AI Studio (Recap, Dubbing, Batch Auto-Splitter & VideoFX)")
        self.btn_top_aio.clicked.connect(self._open_all_in_one_studio)
        top_layout.addWidget(self.btn_top_aio)

        self.btn_top_videofx = QPushButton("🎬 VideoFX")
        self.btn_top_videofx.setObjectName("BtnGlass")
        self.btn_top_videofx.setFixedHeight(30)
        self.btn_top_videofx.setStyleSheet(
            "QPushButton { background: #1A162B; border: 1.5px solid #A855F7; border-radius: 6px; "
            "padding: 2px 10px; color: #C084FC; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #3B0764; border-color: #E9D5FF; color: #FFFFFF; }"
        )
        self.btn_top_videofx.setToolTip("🎬 បើកផ្ទាំង VideoFX Studio (3D LUTs, Masking & Animated Text)")
        self.btn_top_videofx.clicked.connect(self._open_videofx_studio)
        top_layout.addWidget(self.btn_top_videofx)

        self.btn_top_setup = QPushButton("🟢 Setup && AI")
        self.btn_top_setup.setObjectName("BtnGlass")
        self.btn_top_setup.setFixedHeight(30)
        self.btn_top_setup.setStyleSheet(
            "QPushButton { background: #0F241D; border: 1.5px solid #10B981; border-radius: 6px; "
            "padding: 2px 10px; color: #34D399; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #064E3B; border-color: #6EE7B7; color: #FFFFFF; }"
        )
        self.btn_top_setup.setToolTip("🛠️ ពិនិត្យប្រព័ន្ធ & ម៉ូដែល AI (Setup & Models Manager — RTX GPU, FFmpeg & Ollama)")
        self.btn_top_setup.clicked.connect(self._open_setup_manager_dialog)
        top_layout.addWidget(self.btn_top_setup)

        top_layout.addStretch()

        # Direct Workflow View Button on Top Bar (1-Click Access)
        self.btn_top_workflow = QPushButton("🔀 មើលដំណើរការ" if self.lang == "kh" else "🔀 Workflow View")
        self.btn_top_workflow.setObjectName("BtnGlass")
        self.btn_top_workflow.setFixedHeight(30)
        self.btn_top_workflow.setStyleSheet(
            "QPushButton { background: #141B29; border: 1.5px solid #00E5FF; border-radius: 6px; "
            "padding: 2px 12px; color: #00E5FF; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #083344; border-color: #38BDF8; color: #FFFFFF; }"
        )
        self.btn_top_workflow.setToolTip("បើកផ្ទាំងមើលដំណើរការ Real-Time Workflow Views (Flowchart / Metrics / Live Logs)")
        self.btn_top_workflow.clicked.connect(lambda: self._open_workflow_view(0, False))
        top_layout.addWidget(self.btn_top_workflow)

        # 1B. Center Group: Consolidated Tools Menu Button
        self.btn_tools = QPushButton("🛠️ Tools ▾" if self.lang != "kh" else "🛠️ ឧបករណ៍ ▾")
        self.btn_tools.setObjectName("BtnTools")
        self.tools_menu = QMenu(self)

        # Subtitle SRT Menu
        self.srt_menu = QMenu("📝 ឯកសារ SRT (Subtitles)" if self.lang == "kh" else "📝 SRT Subtitles", self)
        self.act_imp_zh = self.srt_menu.addAction("", lambda: self._import_srt("zh"))
        self.act_imp_kh = self.srt_menu.addAction("", lambda: self._import_srt("kh"))
        self.srt_menu.addSeparator()
        self.act_exp_kh = self.srt_menu.addAction("", lambda: self._export_srt("kh"))
        self.act_exp_zh = self.srt_menu.addAction("", lambda: self._export_srt("zh"))
        self.act_exp_both = self.srt_menu.addAction("", lambda: self._export_srt("both"))
        self.act_exp_ass = self.srt_menu.addAction("", self._export_ass)
        self.srt_menu.addSeparator()
        self.act_glossary = self.srt_menu.addAction("", self._open_glossary)
        self.act_caption = self.srt_menu.addAction("", self._open_ai_caption)

        # Tools Menu Actions (using && so Qt never turns & into _ underscore)
        self.act_tool_projects = self.tools_menu.addAction("📁 គម្រោងចាស់ៗ (Projects)", self._open_projects_dialog)
        self.act_tool_batch = self.tools_menu.addAction("🎞️ បញ្ចូលច្រើន (Batch Composer)", self._open_multi_video_composer)
        self.act_tool_viral_shorts = self.tools_menu.addAction("⚡ Auto-Cut Viral Shorts (កាត់ឈុតខ្លីៗស្វ័យប្រវត្តិ)", self._run_auto_cut_viral_shorts)
        self.tools_menu.addMenu(self.srt_menu)
        self.act_tool_glossary = self.tools_menu.addAction("📖 វចនានុក្រម (Glossary)", self._open_glossary)
        self.act_tool_find_replace = self.tools_menu.addAction("🔍 កែពាក្យខុស (Find && Replace)", self._open_find_replace)
        self.act_tool_clean_zh = self.tools_menu.addAction("🧹 សម្អាតអក្សរចិនចេញពីតារាង (Clean Chinese in Script)", self._clean_chinese_from_khmer_script)
        self.act_tool_voice_clone = self.tools_menu.addAction("🎙️ ក្លូនសំឡេងមនុស្ស (Voice Clone)", self._open_voice_clone_studio)
        self.act_tool_speaker_map = self.tools_menu.addAction("🗣️ កំណត់សំឡេងតួអង្គ (Multi-Speaker Role Mapper)", self._open_speaker_mapper_dialog)
        self.act_tool_setup_mgr = self.tools_menu.addAction("🛠️ ពិនិត្យប្រព័ន្ធ && ម៉ូដែល AI (Setup && Models Manager)", self._open_setup_manager_dialog)
        self.act_tool_videofx = self.tools_menu.addAction("🎬 VideoFX Studio (3D LUTs, Masking && Text)", self._open_videofx_studio)
        self.act_tool_aio_studio = self.tools_menu.addAction("🚀 All-in-One AI Studio (Recap, Dub && FX)", self._open_all_in_one_studio)
        self.act_tool_caption = self.tools_menu.addAction("🔥 ចំណងជើង && Hook សង្ខេប (AI Social Caption)", self._open_ai_caption)
        self.act_tool_redo = self.tools_menu.addAction("🔄 កំណត់ឡើងវិញ / Re-do Workflow (Reset Steps)", self._open_reset_project_dialog)
        self.workflow_submenu = self.tools_menu.addMenu("🔀 Workflow Views (មើលដំណើរការផ្ទាល់)")
        self.workflow_submenu.addAction("🔀 Visual Pipeline Flow (Flowchart ផ្ទាល់)", lambda: self._open_workflow_view(0, False))
        self.workflow_submenu.addAction("📊 Live Stage Metrics (ស្ថិតិដំណើរការ)", lambda: self._open_workflow_view(1, False))
        self.workflow_submenu.addAction("📜 Live Process Log (កំណត់ត្រាផ្ទាល់)", lambda: self._open_workflow_view(2, False))
        self.workflow_submenu.addSeparator()
        self.workflow_submenu.addAction("📌 Mini Live Monitor (ផ្ទាំងតូចជាប់លើអេក្រង់)", lambda: self._open_workflow_view(0, True))
        self.tools_menu.addSeparator()
        self.act_tool_settings = self.tools_menu.addAction("⚙️ ការកំណត់ AI (Settings)", self._open_settings)
        self.btn_tools.setMenu(self.tools_menu)
        top_layout.addWidget(self.btn_tools)

        # 1B-2. Series Profile & Character Voice Memory Selector (Feature 1)
        self.active_series_profile_id = int(self.db.get_setting("active_series_profile_id", "0") or 0)
        self.combo_series_profile = QComboBox()
        self.combo_series_profile.setFixedHeight(28)
        self.combo_series_profile.setMinimumWidth(145)
        self.combo_series_profile.setMaximumWidth(185)
        self.combo_series_profile.setStyleSheet(
            "QComboBox { background: #181C24; border: 1px solid #3B4258; border-radius: 6px; "
            "padding: 2px 8px; color: #E2E8F0; font-size: 11px; font-weight: 700; } "
            "QComboBox:hover { border-color: #A78BFA; } "
            "QComboBox::drop-down { border: none; width: 18px; } "
            "QComboBox QAbstractItemView { background: #12151B; color: #F4F6FB; selection-background-color: #6D28D9; }"
        )
        self.combo_series_profile.setToolTip(
            "📚 Series Profile (សំណុំរឿងភាគ): ផ្ទុកសំឡេងតួអង្គ, Glossary, Subtitle/Mask Layout និង Intro/Outro ដោយស្វ័យប្រវត្តិគ្រប់ភាគ"
        )
        self.combo_series_profile.currentIndexChanged.connect(self._on_series_profile_selected)
        top_layout.addWidget(self.combo_series_profile)

        self.btn_save_series_profile = QPushButton("💾")
        self.btn_save_series_profile.setObjectName("BtnGlass")
        self.btn_save_series_profile.setFixedSize(28, 28)
        self.btn_save_series_profile.setStyleSheet(
            "QPushButton { background: #181C24; border: 1px solid #3B4258; border-radius: 6px; padding: 2px 4px; font-size: 12px; color: #A78BFA; } "
            "QPushButton:hover { border-color: #A78BFA; background: #221B38; }"
        )
        self.btn_save_series_profile.setToolTip("រក្សាទុក / អាប់ដេតសំណុំរឿងភាគបច្ចុប្បន្ន (Save Series Profile)")
        self.btn_save_series_profile.clicked.connect(self._on_save_series_profile)
        top_layout.addWidget(self.btn_save_series_profile)

        self.btn_del_series_profile = QPushButton("🗑")
        self.btn_del_series_profile.setObjectName("BtnGlass")
        self.btn_del_series_profile.setFixedSize(28, 28)
        self.btn_del_series_profile.setStyleSheet(
            "QPushButton { background: #181C24; border: 1px solid #3B4258; border-radius: 6px; padding: 2px 4px; font-size: 12px; color: #F87171; } "
            "QPushButton:hover { border-color: #F87171; background: #2D161A; }"
        )
        self.btn_del_series_profile.setToolTip("លុបសំណុំរឿងភាគដែលកំពុងជ្រើសរើស (Delete Series Profile)")
        self.btn_del_series_profile.clicked.connect(self._on_delete_series_profile)
        top_layout.addWidget(self.btn_del_series_profile)
        self._reload_series_profiles_combo()

        # Retain references for signal and backward compatibility
        self.btn_projects = QPushButton()
        self.btn_projects.clicked.connect(self._open_projects_dialog)
        self.btn_batch = QPushButton()
        self.btn_batch.clicked.connect(self._open_multi_video_composer)
        self.btn_srt = QPushButton()
        self.btn_srt.setMenu(self.srt_menu)
        self.btn_glossary = QPushButton()
        self.btn_glossary.clicked.connect(self._open_glossary)
        self.btn_find_replace = QPushButton()
        self.btn_find_replace.clicked.connect(self._open_find_replace)
        self.btn_voice_clone = QPushButton()
        self.btn_voice_clone.clicked.connect(self._open_voice_clone_studio)
        self.btn_settings = QPushButton()
        self.btn_settings.clicked.connect(self._open_settings)

        top_layout.addStretch()

        # 1C. Right Group: API Keys + Update + Theme + License + Language + Emerald Export CTA
        self.btn_api_pool = QPushButton("🔑 API Keys" if self.lang != "kh" else "🔑 កូនសោ API")
        self.btn_api_pool.setObjectName("BtnGlass")
        self.btn_api_pool.setToolTip("គ្រប់គ្រង API Keys ច្រើន (Multi-API Auto-Failover ពេលអស់ Quota)")
        self.btn_api_pool.clicked.connect(self._open_api_pool)

        self.btn_update_pkg = QPushButton("🔄 អាប់ដេត" if self.lang == "kh" else "🔄 Update")
        self.btn_update_pkg.setObjectName("BtnGlass")
        self.btn_update_pkg.setToolTip("ទាញយកកញ្ចប់កូដអាប់ដេតថ្មី")
        self.btn_update_pkg.clicked.connect(self._open_package_updater)

        self.btn_theme = QPushButton("🎨 Theme ▾" if self.lang == "en" else "🎨 រូបរាង ▾")
        self.btn_theme.setObjectName("BtnGlass")
        self.btn_theme.setFixedWidth(82)
        self.btn_theme.setToolTip("Switch Theme (Obsidian / Midnight / Daylight)")
        self.theme_menu = QMenu(self)
        self.theme_actions = {}
        for key, info in THEMES.items():
            if key == "capcut":
                continue
            act = self.theme_menu.addAction(info["name_en"], lambda k=key: self._set_theme(k))
            self.theme_actions[key] = act
        self.btn_theme.setMenu(self.theme_menu)

        self.btn_license = QPushButton("🛡️ License")
        self.btn_license.setObjectName("BtnGlass")
        self.btn_license.setToolTip("ព័ត៌មានអាជ្ញាប័ណ្ណ (License Info & Activation)")
        self.btn_license.clicked.connect(self._open_license_dialog)
        self._update_license_badge()

        self.btn_lang = QPushButton()
        self.btn_lang.setObjectName("BtnGlass")
        self.btn_lang.setFixedWidth(68)
        self.btn_lang.setToolTip("Switch UI Language (English / ខ្មែរ)")
        self.btn_lang.clicked.connect(self._toggle_language)

        self.btn_export = QPushButton()
        self.btn_export.setObjectName("BtnGreen")
        self.btn_export.setEnabled(False)
        self.export_menu = QMenu(self)
        self.act_export_single = self.export_menu.addAction("🎬 Export Single Combined Video (.mp4)", self._run_export_video)
        self.act_export_split = self.export_menu.addAction("📦 Export Split by Episode (EP01.mp4, EP02.mp4...)", self._run_export_split_episodes)
        self.act_export_shorts = self.export_menu.addAction("⚡ Auto-Cut Viral Shorts 9:16 (កាត់ឈុតខ្លីៗ ១០–២០ ឈុត)", self._run_auto_cut_viral_shorts)
        self.export_menu.addSeparator()
        self.act_export_ac = self.export_menu.addAction("🛡️ Export ជាមួយ AI Anti-Copyright (កាត់ផ្តាច់ Copyright)...", self._open_export_with_anti_copyright)
        self.act_export_social = self.export_menu.addAction("📲 Export Social Pack (រៀបចំផុស && ចំណងជើង .txt/.json)", self._run_export_social_pack)
        self.btn_export.setMenu(self.export_menu)

        for w in (self.btn_api_pool, self.btn_update_pkg, self.btn_theme, self.btn_license, self.btn_lang, self.btn_export):
            top_layout.addWidget(w)

        root.addWidget(top_bar)

        # =====================================================================
        # 2. CONNECTED 4-STEP WORKFLOW STEPPER BAR (40px Height)
        # =====================================================================
        self.step_bar = QFrame()
        self.step_bar.setObjectName("StepBar")
        self.step_bar.setFixedHeight(40)
        step_layout = QHBoxLayout(self.step_bar)
        step_layout.setContentsMargins(10, 3, 10, 3)
        step_layout.setSpacing(6)

        # Step 1: Open Video
        self.btn_open = QPushButton()
        self.btn_open.setObjectName("BtnBlue")
        self.btn_open.clicked.connect(self._browse_video)
        step_layout.addWidget(self.btn_open)

        lbl_sep1 = QLabel("›")
        lbl_sep1.setStyleSheet("color: #343B4C; font-size: 16px; font-weight: 800;")
        step_layout.addWidget(lbl_sep1)

        # Step 2: Mode + Scan
        self.extract_mode = QComboBox()
        self.extract_mode.addItems(["", ""])
        self.extract_mode.setMinimumWidth(138)
        self.extract_mode.setFixedHeight(28)
        self.extract_mode.setStyleSheet(
            "background: #181C24; border: 1px solid #252A36; border-radius: 6px; padding: 2px 8px; font-size: 11px;"
        )
        step_layout.addWidget(self.extract_mode)

        self.btn_extract = QPushButton()
        self.btn_extract.setObjectName("BtnCyan")
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self._run_extract)
        step_layout.addWidget(self.btn_extract)

        lbl_sep2 = QLabel("›")
        lbl_sep2.setStyleSheet("color: #343B4C; font-size: 16px; font-weight: 800;")
        step_layout.addWidget(lbl_sep2)

        # Step 3: Translate
        self.btn_translate = QPushButton()
        self.btn_translate.setObjectName("BtnViolet")
        self.btn_translate.setEnabled(False)
        self.btn_translate.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_translate.customContextMenuRequested.connect(self._show_translate_context_menu)
        self.btn_translate.clicked.connect(self._run_translate)
        step_layout.addWidget(self.btn_translate)

        self.combo_trans_style = QComboBox()
        self.combo_trans_style.setFixedHeight(30)
        self.combo_trans_style.setStyleSheet(
            "QComboBox { background: #181C24; border: 1px solid #343B4C; border-radius: 6px; "
            "padding: 2px 8px; color: #F4F6FB; font-size: 11px; font-weight: 600; } "
            "QComboBox::drop-down { border: none; } "
            "QComboBox QAbstractItemView { background: #12151B; color: #F4F6FB; selection-background-color: #7C3AED; }"
        )
        self.combo_trans_style.addItem("🎭 Literal Dub", "literal")
        self.combo_trans_style.addItem("🔥 AI Recap", "recap")
        self.combo_trans_style.setToolTip("រចនាប័ទ្មបកប្រែ៖ បញ្ចូលសំឡេងតាមតួ (Literal) ឬ សម្រាយសាច់រឿង (AI Recap Narration)")
        step_layout.addWidget(self.combo_trans_style)

        lbl_sep3 = QLabel("›")
        lbl_sep3.setStyleSheet("color: #343B4C; font-size: 16px; font-weight: 800;")
        step_layout.addWidget(lbl_sep3)

        # Step 4: Dub
        self.btn_dub = QPushButton()
        self.btn_dub.setObjectName("BtnAmber")
        self.btn_dub.setEnabled(False)
        self.btn_dub.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_dub.customContextMenuRequested.connect(self._show_dub_context_menu)
        self.btn_dub.clicked.connect(self._run_dub_voice)
        step_layout.addWidget(self.btn_dub)

        lbl_sep4 = QLabel("›")
        lbl_sep4.setStyleSheet("color: #343B4C; font-size: 16px; font-weight: 800;")
        step_layout.addWidget(lbl_sep4)

        # AI Anti-Copyright Button & Level Selector
        self.btn_anti_copyright = QPushButton("🛡️ កាត់ផ្តាច់ Copyright (Auto) ▾")
        self.btn_anti_copyright.setObjectName("BtnGlass")
        self.btn_anti_copyright.setFixedHeight(30)
        self.btn_anti_copyright.setStyleSheet(
            "QPushButton { background: #181C24; border: 1.5px solid #00E5FF; border-radius: 6px; "
            "padding: 2px 10px; color: #00E5FF; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #003640; border-color: #67E8F9; color: #FFFFFF; } "
            "QPushButton:disabled { color: #555E70; border-color: #252A36; background: #12151B; }"
        )
        self.btn_anti_copyright.setEnabled(False)
        self.anti_copyright_menu = QMenu(self)
        self.anti_copyright_menu.setStyleSheet("""
            QMenu { background: #161920; color: #F4F6FB; border: 1px solid #343B4C; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 14px; border-radius: 4px; font-size: 11px; }
            QMenu::item:selected { background: #202530; color: #00E5FF; }
        """)
        self.act_ac_light = self.anti_copyright_menu.addAction("🟢 កម្រិតស្រាល (Natural Safe)", lambda: self._apply_anti_copyright_preset("light"))
        self.act_ac_medium = self.anti_copyright_menu.addAction("🟡 កម្រិតមធ្យម (Standard Bypass - Recom.)", lambda: self._apply_anti_copyright_preset("medium"))
        self.act_ac_strong = self.anti_copyright_menu.addAction("🔴 កម្រិតខ្លាំង (Max Fingerprint Break)", lambda: self._apply_anti_copyright_preset("strong"))
        self.anti_copyright_menu.addSeparator()
        self.act_ac_custom = self.anti_copyright_menu.addAction("⚙️ កំណត់ជម្រើសលម្អិត (Advanced Anti-Copyright Settings)...", self._open_anti_copyright_dialog)
        self.btn_anti_copyright.setMenu(self.anti_copyright_menu)
        step_layout.addWidget(self.btn_anti_copyright)

        # 5. 1-Click Full-Auto Hands-Free Pipeline Button (Feature 5)
        self.btn_one_click_auto = QPushButton("🚀 1-Click Auto Dub && Export")
        self.btn_one_click_auto.setFixedHeight(30)
        self.btn_one_click_auto.setCursor(Qt.PointingHandCursor)
        self.btn_one_click_auto.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #0891B2); "
            "color: #FFFFFF; border: 1px solid #34D399; border-radius: 6px; padding: 2px 11px; "
            "font-size: 11px; font-weight: 800; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #06B6D4); } "
            "QPushButton:disabled { background: #181C24; color: #555E70; border-color: #252A36; }"
        )
        self.btn_one_click_auto.setToolTip(
            "🚀 1-Click Auto Dub & Export (ដំណើរការស្វ័យប្រវត្តិទាំងអស់):\n"
            "[Step 1/5] ស្កេនចិន → [Step 2/5] សម្អាតសំរាម → [Step 3/5] បកប្រែខ្មែរ → [Step 4/5] បង្កើតសំឡេង → [Step 5/5] Export .mp4 ដោយស្វ័យប្រវត្តិ!"
        )
        self.btn_one_click_auto.clicked.connect(self._run_one_click_auto_pipeline)
        step_layout.addWidget(self.btn_one_click_auto)

        step_layout.addStretch()

        # Quick-Access Studio Buttons extracted from Tools Menu
        self.btn_step_projects = QPushButton("📁 Projects")
        self.btn_step_projects.setObjectName("BtnGlass")
        self.btn_step_projects.setFixedHeight(30)
        self.btn_step_projects.setToolTip("📁 បើកគម្រោងចាស់ៗ (Recent Projects)")
        self.btn_step_projects.clicked.connect(self._open_projects_dialog)
        step_layout.addWidget(self.btn_step_projects)

        self.btn_step_voice_clone = QPushButton("🎙️ Voice Clone")
        self.btn_step_voice_clone.setObjectName("BtnGlass")
        self.btn_step_voice_clone.setFixedHeight(30)
        self.btn_step_voice_clone.setToolTip("🎙️ ក្លូនសំឡេងមនុស្សពិត (Voice Clone Studio)")
        self.btn_step_voice_clone.clicked.connect(self._open_voice_clone_studio)
        step_layout.addWidget(self.btn_step_voice_clone)

        self.btn_step_roles = QPushButton("🗣️ Roles")
        self.btn_step_roles.setObjectName("BtnGlass")
        self.btn_step_roles.setFixedHeight(30)
        self.btn_step_roles.setToolTip("🗣️ កំណត់សំឡេងតួអង្គ (Multi-Speaker Role Mapper)")
        self.btn_step_roles.clicked.connect(self._open_speaker_mapper_dialog)
        step_layout.addWidget(self.btn_step_roles)

        # Ghost utility buttons
        self.btn_workflow_views = QPushButton("🔀 Workflow Views ▾")
        self.btn_workflow_views.setObjectName("BtnGlass")
        self.btn_workflow_views.setFixedHeight(30)
        self.btn_workflow_views.setStyleSheet(
            "QPushButton { background: #141B29; border: 1.5px solid #38BDF8; border-radius: 6px; "
            "padding: 2px 10px; color: #38BDF8; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #102C42; border-color: #7DD3FC; color: #FFFFFF; }"
        )
        self.btn_workflow_views.setToolTip("បើកផ្ទាំងមើលដំណើរការកម្មវិធីផ្ទាល់ Real-Time (Flowchart / Metrics / Console Log / Mini HUD)")
        self.workflow_views_menu = QMenu(self)
        self.workflow_views_menu.setStyleSheet("""
            QMenu { background: #161920; color: #F4F6FB; border: 1px solid #343B4C; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 14px; border-radius: 4px; font-size: 11px; }
            QMenu::item:selected { background: #202530; color: #00E5FF; }
        """)
        self.act_wf_flow = self.workflow_views_menu.addAction("🔀 Visual Pipeline Flow (Flowchart ផ្ទាល់)", lambda: self._open_workflow_view(0, False))
        self.act_wf_metrics = self.workflow_views_menu.addAction("📊 Live Stage Metrics (តារាងស្ថិតិផ្ទាល់)", lambda: self._open_workflow_view(1, False))
        self.act_wf_log = self.workflow_views_menu.addAction("📜 Live Process Log (កំណត់ត្រា Real-Time)", lambda: self._open_workflow_view(2, False))
        self.workflow_views_menu.addSeparator()
        self.act_wf_mini = self.workflow_views_menu.addAction("📌 Mini Live Monitor (ផ្ទាំងតូចជាប់លើអេក្រង់)", lambda: self._open_workflow_view(0, True))
        self.act_wf_auto = self.workflow_views_menu.addAction("⚡ Auto-Open Workflow ពេលចាប់ផ្តើមដំណើរការ")
        self.act_wf_auto.setCheckable(True)
        self.act_wf_auto.setChecked(False)
        self.btn_workflow_views.setMenu(self.workflow_views_menu)
        step_layout.addWidget(self.btn_workflow_views)

        self.btn_import_social = QPushButton("🔗 Social Link")
        self.btn_import_social.setObjectName("BtnGlass")
        self.btn_import_social.setToolTip("នាំចូលវីដេអូពី TikTok, Douyin, YouTube, FB, IG (Paste Link)")
        self.btn_import_social.clicked.connect(self._open_social_link_importer)
        step_layout.addWidget(self.btn_import_social)

        self.btn_clean_noise = QPushButton("🧹 សម្អាតសំរាម" if self.lang == "kh" else "🧹 Clean Noise")
        self.btn_clean_noise.setObjectName("BtnGlass")
        self.btn_clean_noise.setToolTip("លុបអក្សរ Watermark ដដែលៗ និងជួរសំរាមដោយស្វ័យប្រវត្តិ")
        self.btn_clean_noise.clicked.connect(self._run_clean_noise)
        step_layout.addWidget(self.btn_clean_noise)

        root.addWidget(self.step_bar)

        # =====================================================================
        # 3. CAPCUT 3-COLUMN STUDIO WORKSPACE (42% Left | 34% Center | 24% Right)
        # =====================================================================
        top_split = QSplitter(Qt.Horizontal)
        top_split.setChildrenCollapsible(False)

        # --- PANE 1 (LEFT 42%): Media & Bilingual Script Studio ---
        left_pane = QFrame()
        left_pane.setObjectName("TopBar")
        left_v = QVBoxLayout(left_pane)
        left_v.setContentsMargins(6, 6, 6, 6)
        left_v.setSpacing(4)

        # Left Stack: Page 0 = CapCut "+ Import" DropZone | Page 1 = Subtitle & Voice Table
        self.stack = QStackedWidget()

        drop_zone = QFrame()
        drop_zone.setObjectName("DropZone")
        dz_layout = QVBoxLayout(drop_zone)
        dz_layout.setAlignment(Qt.AlignCenter)
        dz_layout.setSpacing(10)

        dz_icon = QLabel()
        if logo_path.exists():
            dz_pix = QPixmap(str(logo_path)).scaled(135, 135, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dz_icon.setPixmap(dz_pix)
        else:
            dz_icon.setText("🎬")
            dz_icon.setStyleSheet("font-size: 42px;")
        dz_icon.setAlignment(Qt.AlignCenter)

        self.dz_text = QLabel()
        self.dz_text.setObjectName("DropTitle")
        self.dz_text.setAlignment(Qt.AlignCenter)

        self.dz_hint = QLabel()
        self.dz_hint.setObjectName("DropHint")
        self.dz_hint.setAlignment(Qt.AlignCenter)

        self.dz_btn = QPushButton()
        self.dz_btn.setObjectName("BtnBlue")
        self.dz_btn.setFixedWidth(200)
        self.dz_btn.clicked.connect(self._browse_video)

        self.dz_social_btn = QPushButton("🔗 នាំចូលពី Social Link (TikTok/Douyin/YT)")
        self.dz_social_btn.setObjectName("BtnGlass")
        self.dz_social_btn.setFixedWidth(270)
        self.dz_social_btn.clicked.connect(self._open_social_link_importer)

        dz_layout.addWidget(dz_icon)
        dz_layout.addWidget(self.dz_text)
        dz_layout.addWidget(self.dz_hint)
        dz_layout.addSpacing(6)
        dz_layout.addWidget(self.dz_btn, alignment=Qt.AlignCenter)
        dz_layout.addWidget(self.dz_social_btn, alignment=Qt.AlignCenter)

        self.table = QTableWidget(0, 7)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setColumnHidden(0, True)
        self.table.setColumnWidth(1, 74)    # Timecode stacked (00:00.2 / 00:05.6)
        self.table.setColumnWidth(4, 115)   # Voice (Female/Male/Inner Thought)
        self.table.setColumnWidth(5, 34)    # Play button (▶)
        self.table.setColumnWidth(6, 72)    # State (● Voiced)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table.itemChanged.connect(self._on_cell_edited)
        self.table.cellClicked.connect(self._on_row_clicked)

        # Transcript Table Container with Studio Quick Toolbar & Centered Empty State Overlay
        table_container = QWidget()
        table_container_v = QVBoxLayout(table_container)
        table_container_v.setContentsMargins(0, 0, 0, 0)
        table_container_v.setSpacing(4)

        # Compact Studio Quick Toolbar above Script Table
        script_toolbar = QHBoxLayout()
        script_toolbar.setContentsMargins(2, 2, 2, 2)
        script_toolbar.setSpacing(6)

        # 1. Bulk Voice Selector
        self.combo_bulk_voice = QComboBox()
        self.combo_bulk_voice.setFixedHeight(27)
        self.combo_bulk_voice.setStyleSheet(
            "QComboBox { background: #181C24; border: 1px solid #2A3142; border-radius: 5px; "
            "padding: 2px 6px; color: #F4F6FB; font-size: 11px; } "
            "QComboBox::drop-down { border: none; width: 14px; }"
        )
        self.combo_bulk_voice.addItem("🎙 Bulk Voice...", "")
        self.combo_bulk_voice.addItem("🎙 Set Selected -> Female", "female")
        self.combo_bulk_voice.addItem("🎙 Set Selected -> Male", "male")
        self.combo_bulk_voice.addItem("🎙 Set Selected -> Inner Thought", "inner_thought")
        self.combo_bulk_voice.addItem("🎙 Set Selected -> Phone Call", "phone_call")
        self.combo_bulk_voice.addItem("🎙 Set ALL Rows -> Female", "all_female")
        self.combo_bulk_voice.addItem("🎙 Set ALL Rows -> Male", "all_male")
        self.combo_bulk_voice.setToolTip("កំណត់សំឡេងតួអង្គច្រើនជួរព្រមគ្នា (Bulk Voice Assignment)")
        self.combo_bulk_voice.currentIndexChanged.connect(self._on_bulk_voice_selected)

        # 2. Global Khmer TTS Speed Multiplier
        self.combo_tts_speed = QComboBox()
        self.combo_tts_speed.setFixedHeight(27)
        self.combo_tts_speed.setStyleSheet(
            "QComboBox { background: #181C24; border: 1px solid #2A3142; border-radius: 5px; "
            "padding: 2px 6px; color: #F4F6FB; font-size: 11px; } "
            "QComboBox::drop-down { border: none; width: 14px; }"
        )
        self.combo_tts_speed.addItem("⚡ 0.90x", 0.90)
        self.combo_tts_speed.addItem("⚡ 1.00x", 1.00)
        self.combo_tts_speed.addItem("⚡ 1.10x", 1.10)
        self.combo_tts_speed.addItem("⚡ 1.20x", 1.20)
        self.combo_tts_speed.addItem("⚡ 1.30x", 1.30)
        self.combo_tts_speed.setCurrentIndex(1)
        self.combo_tts_speed.setToolTip("ល្បឿនអានសំឡេងខ្មែរទូទៅ (Global Khmer TTS Speed Multiplier)")
        self.combo_tts_speed.currentIndexChanged.connect(self._on_tts_speed_changed)
        self.tts_speed_mult = 1.0

        # 3. Auto Chinese Subtitle Blur Toggle
        self.btn_bottom_blur = QPushButton("🌫 Auto Blur Chinese")
        self.btn_bottom_blur.setObjectName("BtnGlass")
        self.btn_bottom_blur.setFixedHeight(27)
        self.btn_bottom_blur.setStyleSheet(
            "QPushButton { background: #181C24; border: 1px solid #2A3142; border-radius: 5px; "
            "padding: 2px 8px; color: #F4F6FB; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: #202634; border-color: #00E5FF; color: #00E5FF; } "
            "QPushButton:checked { background: #004D5A; border-color: #00E5FF; color: #00E5FF; }"
        )
        self.btn_bottom_blur.setCheckable(True)
        self.btn_bottom_blur.setToolTip("បើក/បិទ Blur បាំងអក្សរចិនក្នុងវីដេអូដោយស្វ័យប្រវត្តិតែ 1 Click (Auto Blur Chinese Subtitles)")
        self.btn_bottom_blur.clicked.connect(self._toggle_bottom_blur)

        # 3B. Auto Clean Leaked Chinese Text in Script Table
        self.btn_clean_chinese = QPushButton("🧹 Clean ZH")
        self.btn_clean_chinese.setObjectName("BtnGlass")
        self.btn_clean_chinese.setFixedHeight(27)
        self.btn_clean_chinese.setStyleSheet(
            "QPushButton { background: #181C24; border: 1px solid #2A3142; border-radius: 5px; "
            "padding: 2px 8px; color: #F4F6FB; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: #202634; border-color: #34D399; color: #34D399; }"
        )
        self.btn_clean_chinese.setToolTip("លុបអក្សរចិនដែលជ្រុះក្នុងជួរខ្មែរទាំងអស់ដោយស្វ័យប្រវត្តិតែ 1 Click (Auto Clean Chinese in Script)")
        self.btn_clean_chinese.clicked.connect(self._clean_chinese_from_khmer_script)

        # 4. Table Filter
        self.combo_table_filter = QComboBox()
        self.combo_table_filter.setFixedHeight(27)
        self.combo_table_filter.setStyleSheet(
            "QComboBox { background: #181C24; border: 1px solid #2A3142; border-radius: 5px; "
            "padding: 2px 6px; color: #F4F6FB; font-size: 11px; } "
            "QComboBox::drop-down { border: none; width: 14px; }"
        )
        self.combo_table_filter.addItem("🔍 All Lines", "all")
        self.combo_table_filter.addItem("⚠️ Untranslated Only", "untranslated")
        self.combo_table_filter.addItem("🎙️ Missing Audio", "unvoiced")
        self.combo_table_filter.addItem("👩 Female Only", "female")
        self.combo_table_filter.addItem("👨 Male Only", "male")
        self.combo_table_filter.addItem("💭 Inner Thought", "inner_thought")
        self.combo_table_filter.addItem("📞 Phone Call", "phone_call")
        self.combo_table_filter.setToolTip("ចម្រាញ់មើលតែជួរដែលត្រូវការ (Table Filter)")
        self.combo_table_filter.currentIndexChanged.connect(self._apply_table_filter)

        script_toolbar.addWidget(self.combo_bulk_voice)
        script_toolbar.addWidget(self.combo_tts_speed)
        script_toolbar.addWidget(self.btn_bottom_blur)
        script_toolbar.addWidget(self.btn_clean_chinese)
        script_toolbar.addStretch()
        script_toolbar.addWidget(self.combo_table_filter)

        table_container_v.addLayout(script_toolbar)

        table_stack_w = QWidget()
        table_stack = QStackedLayout(table_stack_w)
        table_stack.setStackingMode(QStackedLayout.StackAll)
        table_stack.addWidget(self.table)

        self.table_empty_state = QFrame()
        self.table_empty_state.setObjectName("EmptyStateFrame")
        self.table_empty_state.setStyleSheet(
            "QFrame#EmptyStateFrame { background: rgba(18, 21, 27, 0.95); border: 1px dashed #252A36; border-radius: 8px; }"
        )
        empty_layout = QVBoxLayout(self.table_empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(8)

        lbl_empty_icon = QLabel("📝")
        lbl_empty_icon.setStyleSheet("font-size: 36px;")
        lbl_empty_icon.setAlignment(Qt.AlignCenter)

        self.lbl_empty_title = QLabel("មិនទាន់មានអត្ថបទរត់នៅឡើយទេ" if self.lang == "kh" else "No transcript loaded yet")
        self.lbl_empty_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #F4F6FB;")
        self.lbl_empty_title.setAlignment(Qt.AlignCenter)

        self.lbl_empty_sub = QLabel(
            "ចុច 'បើកវីដេអូ' និង 'ស្កេនសំឡេង' ដើម្បីទាញយកអក្សរស្វ័យប្រវត្តិ" if self.lang == "kh"
            else "Click 'Open Video' and run 'Scan ZH' to auto-generate bilingual lines"
        )
        self.lbl_empty_sub.setStyleSheet("font-size: 11.5px; color: #8E95A5;")
        self.lbl_empty_sub.setAlignment(Qt.AlignCenter)

        empty_layout.addWidget(lbl_empty_icon)
        empty_layout.addWidget(self.lbl_empty_title)
        empty_layout.addWidget(self.lbl_empty_sub)

        table_stack.addWidget(self.table_empty_state)
        table_container_v.addWidget(table_stack_w, 1)

        self.stack.addWidget(drop_zone)
        self.stack.addWidget(table_container)
        left_v.addWidget(self.stack, 1)

        # --- PANE 2 (CENTER): Video Preview Player ---
        self.video_editor = VideoPreviewEditor()
        self.video_editor.set_database(self.db)
        self.video_editor.edits_changed.connect(self._on_edits_changed)
        self.video_editor.generate_hook_requested.connect(self._run_generate_viral_hook)

        center_pane = QFrame()
        center_pane.setObjectName("TopBar")
        center_v = QVBoxLayout(center_pane)
        center_v.setContentsMargins(8, 6, 8, 8)
        center_v.setSpacing(4)
        lbl_player_hdr = QLabel("🎬 Player — Live Khmer Dubbing Preview")
        lbl_player_hdr.setObjectName("SubTitle")
        center_v.addWidget(lbl_player_hdr)
        center_v.addWidget(self.video_editor, 1)

        # ប៊ូតុង 🔔 SFX ▾ នៅជាប់ប៊ូតុងបញ្ជា Player (|< < ▶ > >|)
        self.btn_sfx = QPushButton("🔔 SFX ▾")
        self.btn_sfx.setToolTip("បន្ថែមសំឡេង Effect ត្រង់ម៉ោងវីដេអូបច្ចុប្បន្ន")
        self.btn_sfx.setStyleSheet(
            "background-color: #6D28D9; color: #FFFFFF; border-radius: 5px; padding: 4px 10px; font-weight: 700;"
        )
        self.btn_sfx.clicked.connect(self._open_sfx_menu)
        self.video_editor.transport_layout.addWidget(self.btn_sfx)

        # --- PANE 3 (RIGHT): Details & Visual Inspector (Logo | Subtitle | Audio FX | LUTs 20+ | Cut & Ratio | Mask) ---
        right_pane = QFrame()
        right_pane.setObjectName("TopBar")
        right_pane.setMinimumWidth(320)
        right_pane.setMaximumWidth(420)
        right_v = QVBoxLayout(right_pane)
        right_v.setContentsMargins(10, 8, 10, 8)
        right_v.setSpacing(6)

        lbl_det = QLabel("⚙ Details & Visual Inspector")
        lbl_det.setStyleSheet("color: #00C4CC; font-weight: 800; font-size: 13px;")
        right_v.addWidget(lbl_det)

        # Move the Preset Toolbar, 2x3 Tab Switcher, and 6-Tab Inspector into the dedicated Right Details Pane
        right_v.addWidget(self.video_editor.preset_widget)
        if hasattr(self.video_editor, "inspector_nav_widget"):
            right_v.addWidget(self.video_editor.inspector_nav_widget)
        self.video_editor.tabs.setMaximumHeight(16777215)
        right_v.addWidget(self.video_editor.tabs, 1)

        # Original Video Sound Slider + Keep BGM Only Vocal Remover Toggle (Feature 2)
        self.btn_keep_bgm_only = QPushButton("🎼 Keep BGM Only (បំបាត់សំឡេងនិយាយដើម)")
        self.btn_keep_bgm_only.setCheckable(True)
        self.btn_keep_bgm_only.setCursor(Qt.PointingHandCursor)
        self.btn_keep_bgm_only.setFixedHeight(28)
        self.btn_keep_bgm_only.setStyleSheet(
            "QPushButton { background: #181C24; border: 1px solid #2D3548; border-radius: 6px; "
            "padding: 3px 8px; color: #CBD5E1; font-size: 10.5px; font-weight: 700; } "
            "QPushButton:hover { border-color: #10B981; color: #34D399; } "
            "QPushButton:checked { background: #064E3B; border: 1.5px solid #10B981; color: #34D399; }"
        )
        self.btn_keep_bgm_only.setToolTip(
            "បំបាត់សំឡេងនិយាយចិនដើម (AI Vocal Remover) ដោយរក្សាទុកតែភ្លេង BGM និងសំឡេង Effect ដើមនៅក្រោមសំឡេងខ្មែរ"
        )
        self.btn_keep_bgm_only.toggled.connect(self._on_toggle_keep_bgm_only)
        right_v.addWidget(self.btn_keep_bgm_only)

        bgm_box = QHBoxLayout()
        self.lbl_bgm = QLabel()
        self.lbl_bgm.setObjectName("BgmLbl")
        saved_bgm = int(self.db.get_setting("bgm_volume_pct", "0"))
        self.bgm_slider = QSlider(Qt.Horizontal)
        self.bgm_slider.setRange(0, 100)
        self.bgm_slider.setValue(saved_bgm)
        self.bgm_slider.valueChanged.connect(self._on_bgm_changed)
        self.bgm_slider.sliderReleased.connect(self._rebuild_smooth_preview)
        self.lbl_bgm_val = QLabel(f"{saved_bgm}%")
        self.lbl_bgm_val.setFixedWidth(38)
        self.lbl_bgm_val.setObjectName("BgmValLbl")
        bgm_box.addWidget(self.lbl_bgm)
        bgm_box.addWidget(self.bgm_slider, 1)
        bgm_box.addWidget(self.lbl_bgm_val)
        right_v.addLayout(bgm_box)

        right_pane.setMinimumWidth(320)
        top_split.addWidget(left_pane)
        top_split.addWidget(center_pane)
        top_split.addWidget(right_pane)
        top_split.setStretchFactor(0, 45)
        top_split.setStretchFactor(1, 30)
        top_split.setStretchFactor(2, 25)
        top_split.setSizes([540, 370, 340])

        # =====================================================================
        # 3. BOTTOM MULTI-TRACK VISUAL TIMELINE (Video + KH Sub + KH Dub Tracks)
        # =====================================================================
        self.timeline_tracks = CapCutTimelineWidget()
        self.timeline = self.timeline_tracks
        self.timeline_tracks.seek_requested.connect(self.video_editor.seek_to_ms)
        self.timeline_tracks.segment_selected.connect(self._on_timeline_segment_clicked)
        self.timeline_tracks.gap_action_requested.connect(self._on_timeline_gap_action)
        self.timeline_tracks.segment_action_requested.connect(self._on_timeline_segment_action)
        self.timeline_tracks.fill_gaps_clicked.connect(lambda: self._run_fill_timeline_gaps())
        self.timeline_tracks.dub_missing_clicked.connect(self._show_dub_missing_menu)
        self.timeline_tracks.auto_sfx_clicked.connect(self._run_auto_place_emotion_sfx)
        self.timeline_tracks.play_pause_requested.connect(self.video_editor.toggle_play)
        self.video_editor.playback_state_changed.connect(self.timeline_tracks.set_playing)
        self.video_editor.position_ms_changed.connect(self.timeline_tracks.set_position)
        self.video_editor.position_synced.connect(self.timeline_tracks.set_position)
        self.video_editor.duration_ms_changed.connect(
            lambda dur: self.timeline_tracks.set_data(dur, self.db.get_segments(self.project_id) if self.project_id else [])
        )

        main_v_split = QSplitter(Qt.Vertical)
        main_v_split.setChildrenCollapsible(False)
        main_v_split.addWidget(top_split)
        main_v_split.addWidget(self.timeline_tracks)
        main_v_split.setStretchFactor(0, 72)
        main_v_split.setStretchFactor(1, 28)
        main_v_split.setSizes([490, 165])

        root.addWidget(main_v_split, 1)

        # =====================================================================
        # 4. SLIM STATUS & PROGRESS FOOTER
        # =====================================================================
        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        footer.setSpacing(10)

        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("StatusLbl")

        self.pbar = QProgressBar()
        self.pbar.setFixedWidth(180)
        self.pbar.setValue(0)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setObjectName("BtnRose")
        self.btn_stop.setFixedHeight(26)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("បញ្ឈប់ការស្កេន/បកប្រែភ្លាមៗ និងរក្សាទុកទិន្នន័យដែលធ្វើរួច")
        self.btn_stop.clicked.connect(self._stop_worker)

        footer.addWidget(self.status_lbl, 1)
        footer.addWidget(self.pbar)
        footer.addWidget(self.btn_stop)
        root.addLayout(footer)

        self._apply_button_cursors(central)

    def _apply_button_cursors(self, parent_widget):
        from PySide6.QtWidgets import QPushButton, QToolButton
        for btn in parent_widget.findChildren(QPushButton):
            btn.setCursor(Qt.PointingHandCursor)
        for btn in parent_widget.findChildren(QToolButton):
            btn.setCursor(Qt.PointingHandCursor)

    def _probe_encoder_async(self):
        """Runs the 0.1s FFmpeg GPU check in a tiny background thread on startup."""
        class ProbeThread(QThread):
            done = Signal(str)
            def run(self):
                self.done.emit(MediaEngine.get_encoder_label())

        self._probe_thread = ProbeThread(self)
        self._probe_thread.done.connect(self._on_encoder_probed)
        self._probe_thread.start()

    def _on_encoder_probed(self, label: str):
        self._hw_encoder_label = label
        self._update_encoder_badge()

    def _on_edits_changed(self, ed: dict):
        if self.project_id:
            ed_to_save = {k: v for k, v in ed.items() if k != "project_id"}
            self.db.update_project_edits(self.project_id, edits_dict=ed_to_save)
        self._update_encoder_badge()

    def _update_encoder_badge(self):
        if not hasattr(self, "lbl_encoder"):
            return
        edits = self.db.get_project_edits(self.project_id) if self.project_id else {}
        is_rendering = MediaEngine.needs_video_render(edits)
        if not getattr(self, "sys_monitor", None) or not self.sys_monitor.isRunning():
            if is_rendering:
                hw_label = getattr(self, "_hw_encoder_label", "🚀 Fast Engine")
                self.lbl_encoder.setText(hw_label)
            else:
                self.lbl_encoder.setText(tr(self.lang, "mode_fast_copy"))
        if is_rendering:
            self.lbl_encoder.setStyleSheet(
                "background-color: #1E293B; color: #34D399; border: 1.5px solid #10B981; "
                "border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 700;"
            )
        else:
            self.lbl_encoder.setStyleSheet(
                "background-color: #181C24; color: #00E5FF; border: 1px solid #252A36; "
                "border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 700;"
            )

    def _set_theme(self, theme_key: str):
        self.db.set_setting("ui_theme", theme_key)
        app = QApplication.instance()
        apply_app_palette(app, theme_key)
        app.setStyleSheet(build_stylesheet(theme_key))

    def _toggle_language(self):
        self.lang = "kh" if self.lang == "en" else "en"
        self.db.set_setting("ui_lang", self.lang)
        self._apply_language()

    def _apply_language(self):
        L = self.lang
        from core.updater import get_effective_app_version
        cur_ver = get_effective_app_version()
        title_text = f"{tr(L, 'app_title')} v{cur_ver}"
        self.setWindowTitle(title_text)
        self.lbl_title.setText(title_text)
        self.btn_lang.setText(tr(L, "lang_btn"))

        if not self.video_path and not self.project_id:
            self.lbl_file.setText(tr(L, "no_video"))
            self.status_lbl.setText(tr(L, "status_ready"))
        elif self.video_path:
            self._set_short_filename(Path(self.video_path).name)
            self.status_lbl.setText(tr(L, "status_loaded", name=Path(self.video_path).name))

        self.btn_open.setText(tr(L, "btn_open"))
        if hasattr(self, "btn_top_redo"):
            self.btn_top_redo.setText("🔄 កំណត់ឡើងវិញ" if L == "kh" else "🔄 Re-do / Reset")
        if hasattr(self, "btn_top_workflow"):
            self.btn_top_workflow.setText("🔀 មើលដំណើរការ" if L == "kh" else "🔀 Workflow View")
        if hasattr(self, "btn_workflow_views"):
            self.btn_workflow_views.setText("🔀 មើលដំណើរការ ▾" if L == "kh" else "🔀 Workflow Views ▾")
        self.btn_import_social.setText("🔗 Social Link")
        if hasattr(self, "btn_tools"):
            self.btn_tools.setText("🛠️ Tools ▾" if L != "kh" else "🛠️ ឧបករណ៍ ▾")
        if hasattr(self, "act_tool_projects"):
            self.act_tool_projects.setText(tr(L, "btn_projects"))
            self.act_tool_batch.setText(tr(L, "btn_batch"))
            self.act_tool_glossary.setText("📖 វចនានុក្រម" if L == "kh" else "📖 Glossary")
            self.act_tool_find_replace.setText("🔍 កែពាក្យខុស" if L == "kh" else "🔍 Find && Replace")
            self.act_tool_voice_clone.setText("🎙️ ក្លូនសំឡេងមនុស្ស" if L == "kh" else "🎙️ Voice Clone")
            self.act_tool_settings.setText(tr(L, "btn_settings"))
        self.btn_projects.setText(tr(L, "btn_projects"))
        self.btn_batch.setText(tr(L, "btn_batch"))
        self.extract_mode.setItemText(0, tr(L, "mode_voice"))
        self.extract_mode.setItemText(1, tr(L, "mode_ocr"))
        self.btn_extract.setText(tr(L, "btn_extract"))
        self.btn_clean_noise.setText("🧹 សម្អាតសំរាម" if L == "kh" else "🧹 Clean Noise")
        self.btn_translate.setText(tr(L, "btn_translate"))
        self.btn_dub.setText(tr(L, "btn_dub"))
        self.btn_export.setText(tr(L, "btn_export") + " ▾")
        self.btn_glossary.setText("📖 វចនានុក្រម" if L == "kh" else "📖 Glossary")
        self.btn_find_replace.setText("🔍 កែពាក្យខុស (Replace)" if L == "kh" else "🔍 Find & Replace")
        self.btn_voice_clone.setText("🎙️ ក្លូនសំឡេងមនុស្ស" if L == "kh" else "🎙️ Voice Clone")
        self.btn_api_pool.setText("🔑 API Keys" if L != "kh" else "🔑 កូនសោ API")
        self.btn_settings.setText(tr(L, "btn_settings"))
        self.btn_update_pkg.setText("🔄 អាប់ដេតកូដ" if L == "kh" else "🔄 Update")
        self.btn_theme.setText("🎨 Theme ▾" if L == "en" else "🎨 រូបរាង ▾")
        if hasattr(self, "lbl_empty_title"):
            if L == "kh":
                self.lbl_empty_title.setText("មិនទាន់មានអត្ថបទរត់នៅឡើយទេ")
                self.lbl_empty_sub.setText("ចុច 'បើកវីដេអូ' និង 'ស្កេនសំឡេង' ដើម្បីទាញយកអក្សរស្វ័យប្រវត្តិ")
            else:
                self.lbl_empty_title.setText("No transcript loaded yet")
                self.lbl_empty_sub.setText("Click 'Open Video' and run 'Scan ZH' to auto-generate bilingual lines")

        self.btn_srt.setText(tr(L, "btn_srt"))
        self.act_imp_zh.setText(tr(L, "srt_imp_zh"))
        self.act_imp_kh.setText(tr(L, "srt_imp_kh"))
        self.act_exp_kh.setText(tr(L, "srt_exp_kh"))
        self.act_exp_zh.setText(tr(L, "srt_exp_zh"))
        self.act_exp_both.setText(tr(L, "srt_exp_both"))
        self.act_exp_ass.setText(tr(L, "srt_exp_ass"))
        self.act_glossary.setText(tr(L, "tools_glossary"))
        self.act_caption.setText(tr(L, "tools_caption"))

        self.dz_text.setText(tr(L, "dz_title"))
        self.dz_hint.setText(tr(L, "dz_hint"))
        self.dz_btn.setText(tr(L, "dz_btn"))
        self.dz_social_btn.setText("🔗 នាំចូលពី Social Link (TikTok/Douyin/YT)" if L == "kh" else "🔗 Import from Social Link (TikTok/Douyin/YT)")
        self.lbl_bgm.setText(tr(L, "lbl_bgm"))

        name_field = "name_kh" if L == "kh" else "name_en"
        for key, act in self.theme_actions.items():
            act.setText(THEMES[key][name_field])

        self._update_encoder_badge()

        self.table.setHorizontalHeaderLabels([
            "ID",
            tr(L, "col_time"),
            tr(L, "col_zh"),
            tr(L, "col_kh"),
            tr(L, "col_voice"),
            tr(L, "col_preview"),
            tr(L, "col_state"),
        ])
        # Refresh existing row dropdown labels when switching EN <-> KH
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 4)
            if isinstance(combo, QComboBox):
                cur_data = combo.currentData()
                combo.blockSignals(True)
                self._populate_voice_combo(combo, cur_data)
                combo.blockSignals(False)

    # --- Drag & Drop (Supports dropping 1 or up to 50 videos at once!) ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        valid_exts = {".mp4", ".mkv", ".mov", ".avi", ".flv"}
        files = [
            u.toLocalFile() for u in urls
            if Path(u.toLocalFile()).suffix.lower() in valid_exts
        ][:50]
        if len(files) == 1:
            self._load_video(files[0])
        elif len(files) > 1:
            self._merge_multiple_videos_into_workspace(files)

    def _browse_video(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr(self.lang, "btn_open"), "", "Videos (*.mp4 *.mkv *.mov *.avi *.flv)"
        )
        if not files:
            return
        if len(files) == 1:
            self._load_video(files[0])
        else:
            self._merge_multiple_videos_into_workspace(files[:50])

    def _open_social_link_importer(self):
        output_dir = Path("data/downloads")
        output_dir.mkdir(parents=True, exist_ok=True)
        dlg = SocialLinkImportDialog(self, output_dir=str(output_dir))
        dlg.import_requested.connect(self._on_social_download_completed)
        dlg.exec()

    def _on_social_download_completed(self, downloaded_files: list, should_merge: bool):
        if not downloaded_files:
            return
        if should_merge and len(downloaded_files) > 1:
            self._merge_multiple_videos_into_workspace(downloaded_files)
        else:
            self._load_video(downloaded_files[0])
            if len(downloaded_files) > 1:
                QMessageBox.information(
                    self, "Social Links Imported",
                    f"បានទាញយកវីដេអូទាំង {len(downloaded_files)} រួចរាល់!\n"
                    f"វីដេអូដំបូងត្រូវបានបើកលើ Timeline ហើយវីដេអូឯទៀតត្រូវបានរក្សាទុកក្នុង:\n"
                    f"{Path(downloaded_files[0]).parent}"
                )

    def _load_video(self, path: str):
        if not path or not Path(path).exists():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.video_path = path
            self._clip_markers = []
            self.project_id = self.db.create_project(Path(path).stem, path, "voice")
            self._set_short_filename(Path(path).name)
            self.table.setRowCount(0)
            self.stack.setCurrentIndex(1)
            # Auto-apply active Series Profile (glossary, voice memory, edits layout, Intro/Outro) to newly loaded episode
            if getattr(self, "active_series_profile_id", 0) > 0:
                self._apply_series_profile_to_current_project(self.active_series_profile_id, quiet=True)
            edits = self.db.get_project_edits(self.project_id)

            # Probe duration + resolution in ONE fast call with timeout 2.5s (Zero UI Freeze)
            dur_ms, vw, vh = MediaEngine.probe_video_info(path)

            self.video_editor.load_video(self.video_path, edits, [], pre_wh=(vw, vh), pre_dur_ms=dur_ms)
            self.video_editor.set_original_volume(self.bgm_slider.value())
            if hasattr(self, "btn_keep_bgm_only"):
                self.btn_keep_bgm_only.blockSignals(True)
                self.btn_keep_bgm_only.setChecked(bool(edits.get("keep_bgm_only", 0)))
                self.btn_keep_bgm_only.blockSignals(False)
            if hasattr(self, "btn_bottom_blur"):
                self.btn_bottom_blur.setChecked(bool(edits.get("mask_enabled", 0) or edits.get("auto_blur_chinese", 0)))
            self.timeline_tracks.set_data(dur_ms, [], clip_markers=[])
            self._update_encoder_badge()
            self.btn_extract.setEnabled(True)
            self.btn_translate.setEnabled(False)
            self.btn_dub.setEnabled(False)
            self.btn_export.setEnabled(False)
            self.status_lbl.setText(tr(self.lang, "status_loaded", name=Path(path).name))
        finally:
            QApplication.restoreOverrideCursor()

    def _merge_multiple_videos_into_workspace(self, files: list):
        """តភ្ជាប់វីដេអូរហូតដល់ 50 ឈុតចូលគ្នាជា Timeline & Preview តែមួយដូច CapCut"""
        first_name = f"{Path(files[0]).stem}_Merged_{len(files)}Clips"
        proj_id = self.db.create_project(first_name, files[0], "voice")
        merged_mp4 = str(Path(f"data/workspace/proj_{proj_id}") / "merged_timeline.mp4")
        holder = {"markers": []}

        def task(emit):
            emit(20, f"កំពុងតភ្ជាប់វីដេអូចំនួន {len(files)} ឈុតចូល Timeline តែមួយ (-c copy)...")
            markers = MediaEngine.merge_clips_to_timeline(files, merged_mp4)
            holder["markers"] = markers
            with self.db.conn:
                self.db.conn.execute("UPDATE projects SET video_path=? WHERE id=?", (merged_mp4, proj_id))
            emit(100, "Done")
            return f"បានតភ្ជាប់វីដេអូចំនួន {len(files)} ឈុតចូលគ្នារួចរាល់! អាចចាក់ Preview ឬចុច 'Scan ZH' បានភ្លាម។"

        def on_merged():
            markers = holder["markers"]
            self.project_id = proj_id
            self.video_path = merged_mp4
            self._clip_markers = markers
            self._set_short_filename(f"{len(files)} Clips — {Path(files[0]).name}")
            self.table.setRowCount(0)
            self.stack.setCurrentIndex(1)
            if getattr(self, "active_series_profile_id", 0) > 0:
                self._apply_series_profile_to_current_project(self.active_series_profile_id, quiet=True)
            edits = self.db.get_project_edits(proj_id)
            self.video_editor.load_video(merged_mp4, edits, [])
            self.video_editor.set_original_volume(self.bgm_slider.value())
            if hasattr(self, "btn_keep_bgm_only"):
                self.btn_keep_bgm_only.blockSignals(True)
                self.btn_keep_bgm_only.setChecked(bool(edits.get("keep_bgm_only", 0)))
                self.btn_keep_bgm_only.blockSignals(False)
            if hasattr(self, "btn_bottom_blur"):
                self.btn_bottom_blur.setChecked(bool(edits.get("mask_enabled", 0) or edits.get("auto_blur_chinese", 0)))
            total_ms = markers[-1]["end_ms"] if markers else 60000
            self.timeline_tracks.set_data(total_ms, [], clip_markers=markers)
            self._update_encoder_badge()
            self.btn_extract.setEnabled(True)
            self.btn_translate.setEnabled(False)
            self.btn_dub.setEnabled(False)
            self.btn_export.setEnabled(False)

        self._run_worker(task, on_merged)

    def _open_multi_video_composer(self):
        has_active = bool(self.project_id and self.video_path and Path(self.video_path).exists())
        dlg = MultiClipComposerDialog(self.lang, parent=self, has_active_project=has_active)
        if dlg.exec() != QDialog.Accepted:
            return
        files = dlg.selected_files
        if dlg.action_mode == "viral_shorts":
            target_vid = files[0] if files else self.video_path
            self._run_auto_cut_viral_shorts(
                video_path=target_vid,
                max_clips=dlg.shorts_max_clips,
                min_sec=dlg.shorts_min_sec,
                max_sec=dlg.shorts_max_sec,
            )
            return
        if not files:
            return
        if dlg.action_mode == "batch":
            bgm_vol = round(self.bgm_slider.value() / 100.0, 2)
            bdlg = BatchDubbingDialog(self.db, self.lang, bgm_volume=bgm_vol, parent=self)
            bdlg.video_paths = list(files)
            bdlg._refresh_table()
            bdlg.exec()
        else:
            self._merge_multiple_videos_into_workspace(files)

    def _import_srt(self, target_lang: str):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr(self.lang, "srt_imp_zh" if target_lang == "zh" else "srt_imp_kh"),
            "",
            "Subtitle Files (*.srt)"
        )
        if not path:
            return

        parsed = SRTHandler.parse_srt(path)
        if not parsed:
            QMessageBox.warning(self, "Empty SRT", "No valid subtitle entries found in this SRT file.")
            return

        # Allow importing SRT even if no video is loaded yet (creates a script-only project)
        if not self.project_id:
            self.project_id = self.db.create_project(Path(path).stem, "", "srt")
            self._set_short_filename(Path(path).name)
            self.stack.setCurrentIndex(1)

        existing = self.db.get_segments(self.project_id)

        if target_lang == "kh" and existing:
            # Map imported Khmer lines onto existing Chinese timestamps by row order
            count = min(len(existing), len(parsed))
            for i in range(count):
                self.db.update_segment(existing[i]["id"], kh_text=parsed[i]["text"], status="Ready")
            # Append any extra Khmer lines if the SRT has more rows
            if len(parsed) > len(existing):
                extra = [
                    {
                        "start_ms": item["start_ms"],
                        "end_ms": item["end_ms"],
                        "zh_text": "",
                        "kh_text": item["text"],
                        "status": "Ready",
                    }
                    for item in parsed[len(existing):]
                ]
                with self.db.conn:
                    self.db.conn.executemany(
                        """INSERT INTO segments (project_id, seq_index, start_ms, end_ms, zh_text, kh_text, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        [
                            (self.project_id, len(existing) + idx + 1, e["start_ms"], e["end_ms"], "", e["kh_text"], "Ready")
                            for idx, e in enumerate(extra)
                        ],
                    )
        else:
            # Load fresh timeline from SRT
            items = [
                {
                    "start_ms": item["start_ms"],
                    "end_ms": item["end_ms"],
                    "zh_text": item["text"] if target_lang == "zh" else "",
                    "kh_text": item["text"] if target_lang == "kh" else "",
                    "status": "Ready" if target_lang == "kh" else "pending",
                }
                for item in parsed
            ]
            self.db.insert_segments(self.project_id, items)

        self._refresh_table()
        self._update_button_states()
        self.status_lbl.setText(tr(self.lang, "status_srt_imported", count=len(parsed)))

    def _export_srt(self, mode: str):
        if not self.project_id:
            return
        segments = self.db.get_segments(self.project_id)
        if not segments:
            return

        default_name = f"{Path(self.video_path).stem}_{mode}.srt" if self.video_path else f"subtitles_{mode}.srt"
        out_path, _ = QFileDialog.getSaveFileName(self, "Export SRT", default_name, "Subtitle Files (*.srt)")
        if not out_path:
            return

        written = SRTHandler.export_srt(segments, out_path, mode=mode)
        self.status_lbl.setText(tr(self.lang, "status_srt_exported", count=written, name=Path(out_path).name))

    def _export_ass(self):
        if not self.project_id:
            return
        segments = self.db.get_segments(self.project_id)
        if not segments:
            return
        default_name = f"{Path(self.video_path).stem}_kh.ass" if self.video_path else "subtitles_kh.ass"
        out_path, _ = QFileDialog.getSaveFileName(self, tr(self.lang, "srt_exp_ass"), default_name, "ASS Subtitle (*.ass)")
        if not out_path:
            return
        edits = self.db.get_project_edits(self.project_id)
        MediaEngine.write_ass_subtitles(segments, edits, out_path)
        self.status_lbl.setText(tr(self.lang, "status_srt_exported", count=len(segments), name=Path(out_path).name))

    def _open_glossary(self):
        dlg = GlossaryDialog(self.db, self.lang, self)
        if dlg.exec():
            self.status_lbl.setText("Character Name Glossary saved.")

    def _open_ai_caption(self):
        segments = self.db.get_segments(self.project_id) if self.project_id else []
        api_url = self.db.get_setting("api_url", "google-free")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "google-free")
        from core.translator import ZHtoKHTranslator
        translator = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=self.db.get_glossary())
        caption = translator.generate_social_caption(segments)
        dlg = AICaptionDialog(caption, self.lang, self)
        dlg.exec()

    def _open_api_pool(self):
        from ui.api_pool_dialog import APIKeyPoolDialog
        dlg = APIKeyPoolDialog(self.db, parent=self, lang=self.lang)
        dlg.exec()

    def _open_settings(self):
        dlg = SettingsDialog(self.db, self.lang, self)
        if dlg.exec():
            self.status_lbl.setText(tr(self.lang, "status_settings_saved"))

    def _open_batch_dialog(self):
        bgm_vol = round(self.bgm_slider.value() / 100.0, 2)
        dlg = BatchDubbingDialog(self.db, self.lang, bgm_volume=bgm_vol, parent=self)
        dlg.exec()

    def _open_projects_dialog(self):
        dlg = RecentProjectsDialog(self.db, self.lang, self)
        if not dlg.exec() or not dlg.selected_project:
            return

        # 0. បញ្ឈប់ការចាក់សំឡេង និងវីដេអូចាស់ទាំងអស់ រួចដោះលែង File Lock
        if hasattr(self, "row_player"):
            self.row_player.stop()
            self.row_player.setSource(QUrl())
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
            self.video_editor.pause()
            self.video_editor.player.stop()
            self.video_editor.player.setSource(QUrl())

        # 1. សម្អាតតារាងចាស់ចេញទាំងអស់ ការពារកុំឲ្យជាន់ Signal/Widget ចាស់
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.blockSignals(False)

        proj = dlg.selected_project
        self.project_id = proj["id"]
        raw_video_path = proj.get("video_path") or ""

        # If the original video moved, let the user relink it immediately
        if raw_video_path and not Path(raw_video_path).exists():
            QMessageBox.warning(self, tr(self.lang, "proj_dlg_title"), tr(self.lang, "proj_video_missing"))
            new_path, _ = QFileDialog.getOpenFileName(
                self, tr(self.lang, "btn_open"), "", "Videos (*.mp4 *.mkv *.mov *.avi)"
            )
            if new_path and Path(new_path).exists():
                raw_video_path = new_path
                with self.db.conn:
                    self.db.conn.execute("UPDATE projects SET video_path=? WHERE id=?", (new_path, self.project_id))
            else:
                raw_video_path = ""
                self.status_lbl.setText("⚠️ វីដេអូដើមត្រូវបានប្តូរទីតាំង — បើកក្នុងរបៀបអត្ថបទ និងសំឡេង")

        self.video_path = raw_video_path
        self._set_short_filename(Path(self.video_path).name if self.video_path else proj["name"])
        self.stack.setCurrentIndex(1)
        self._refresh_table()

        edits = self.db.get_project_edits(self.project_id)
        segments = self.db.get_segments(self.project_id)
        
        # គណនា Duration ដោយសុវត្ថិភាពបំផុត មិនឲ្យធ្លាក់កូដជាដាច់ខាត
        dur = 60000
        if self.video_path and Path(self.video_path).exists():
            dur = MediaEngine.get_duration_ms(self.video_path)
        elif segments:
            max_end = max((int(s.get("end_ms") or 0) for s in segments), default=0)
            dur = max(60000, max_end + 2000)

        # ស្វែងរកឯកសារ Preview ណាដែលមានទំហំត្រឹមត្រូវ (> 1024 bytes)
        work_dir = Path(f"data/workspace/proj_{self.project_id}")
        preview_mp4 = None
        if work_dir.exists():
            valid_previews = sorted(
                [p for p in work_dir.glob("preview_stream_*.mp4") if p.exists() and p.stat().st_size > 1024],
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if valid_previews:
                preview_mp4 = valid_previews[0]
            elif (work_dir / "_tmp_preview.mp4").exists() and (work_dir / "_tmp_preview.mp4").stat().st_size > 1024:
                preview_mp4 = work_dir / "_tmp_preview.mp4"
            elif (work_dir / "preview_muxed.mp4").exists() and (work_dir / "preview_muxed.mp4").stat().st_size > 1024:
                preview_mp4 = work_dir / "preview_muxed.mp4"

        # ផ្ទុកវីដេអូតែម្តងគត់ (Zero Double-Switch Crash)
        self.video_editor.load_video(
            self.video_path,
            edits,
            segments,
            pre_dur_ms=dur,
            preview_path=str(preview_mp4) if preview_mp4 else "",
        )
        self.video_editor.set_original_volume(self.bgm_slider.value())
        if hasattr(self, "btn_keep_bgm_only"):
            self.btn_keep_bgm_only.blockSignals(True)
            self.btn_keep_bgm_only.setChecked(bool(edits.get("keep_bgm_only", 0)))
            self.btn_keep_bgm_only.blockSignals(False)
        if hasattr(self, "combo_series_profile"):
            sp_id = int(edits.get("series_profile_id") or 0)
            if sp_id > 0:
                self.combo_series_profile.blockSignals(True)
                idx_sp = self.combo_series_profile.findData(sp_id)
                if idx_sp >= 0:
                    self.combo_series_profile.setCurrentIndex(idx_sp)
                    self.active_series_profile_id = sp_id
                self.combo_series_profile.blockSignals(False)
        if hasattr(self, "btn_bottom_blur"):
            self.btn_bottom_blur.setChecked(bool(edits.get("mask_enabled", 0) or edits.get("auto_blur_chinese", 0)))
        self.timeline_tracks.set_data(dur, segments)
        self.timeline_tracks.set_sfx_events(self.db.get_sfx_events(self.project_id))
        self._update_encoder_badge()
        self._update_button_states()
        self.status_lbl.setText(
            tr(self.lang, "status_proj_loaded", name=proj["name"], count=len(segments))
        )

    def _open_reset_project_dialog(self):
        """កំណត់ឡើងវិញនូវជំហាននានាក្នុងគម្រោងចាស់ (Reset & Re-do Workflow Steps)"""
        if not self.project_id:
            QMessageBox.information(self, "Ai Summarai", "សូមបើកគម្រោងជាមុនសិន!")
            return

        kh = self.lang == "kh"
        msg = QMessageBox(self)
        msg.setWindowTitle("🔄 Re-do / Reset Project Steps" if not kh else "🔄 កំណត់ឡើងវិញ / Re-do Workflow")
        msg.setText(
            "សូមជ្រើសរើសជំហានដែលអ្នកចង់កំណត់ឡើងវិញ (Reset) ក្នុងគម្រោងនេះ៖" if kh else
            "Choose which workflow steps you would like to reset in this project:"
        )
        btn_reset_audio = msg.addButton(
            "🎙️ 1. លុបតែសំឡេង (Reset Audio Only)" if kh else "🎙️ 1. Reset Audio Only",
            QMessageBox.ActionRole
        )
        btn_reset_trans = msg.addButton(
            "📝 2. លុបការបកប្រែ & សំឡេង (Reset Translate & Audio)" if kh else "📝 2. Reset Translate & Audio",
            QMessageBox.ActionRole
        )
        btn_reset_all = msg.addButton(
            "⚠️ 3. លុបគ្រប់ជួរទាំងអស់ (Full Project Reset)" if kh else "⚠️ 3. Full Project Reset",
            QMessageBox.ActionRole
        )
        btn_cancel = msg.addButton("❌ បោះបង់ (Cancel)" if kh else "❌ Cancel", QMessageBox.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_cancel or not clicked:
            return

        work_dir = Path(f"data/workspace/proj_{self.project_id}")
        clip_dir = work_dir / "tts"

        # Release player handles
        if hasattr(self, "row_player"):
            self.row_player.stop()
            self.row_player.setSource(QUrl())
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
            self.video_editor.pause()

        if clicked == btn_reset_audio:
            with self.db.conn:
                self.db.conn.execute("UPDATE segments SET tts_audio_path='', status='Ready' WHERE project_id=?", (self.project_id,))
            if clip_dir.exists():
                for f in clip_dir.glob("*.wav"):
                    try: f.unlink(missing_ok=True)
                    except Exception: pass
            for p in work_dir.glob("preview_stream_*.mp4"):
                try: p.unlink(missing_ok=True)
                except Exception: pass
            (work_dir / "_tmp_preview.mp4").unlink(missing_ok=True)
            (work_dir / "preview_muxed.mp4").unlink(missing_ok=True)
            self.video_editor.set_dubbed_video_preview("")
            QMessageBox.information(self, "Ai Summarai", "✓ បានសម្អាតសំឡេងទាំងអស់រួចរាល់! អ្នកអាចចុច '៤. បញ្ចូលសំឡេងខ្មែរ' ឡើងវិញបាន។")

        elif clicked == btn_reset_trans:
            with self.db.conn:
                self.db.conn.execute("UPDATE segments SET kh_text='', tts_audio_path='', status='pending' WHERE project_id=?", (self.project_id,))
            if clip_dir.exists():
                for f in clip_dir.glob("*.wav"):
                    try: f.unlink(missing_ok=True)
                    except Exception: pass
            for p in work_dir.glob("preview_stream_*.mp4"):
                try: p.unlink(missing_ok=True)
                except Exception: pass
            (work_dir / "_tmp_preview.mp4").unlink(missing_ok=True)
            (work_dir / "preview_muxed.mp4").unlink(missing_ok=True)
            self.video_editor.set_dubbed_video_preview("")
            QMessageBox.information(self, "Ai Summarai", "✓ បានសម្អាតការបកប្រែ និងសំឡេងរួចរាល់! អ្នកអាចចុច '៣. បកប្រែជាខ្មែរ' ឡើងវិញបាន។")

        elif clicked == btn_reset_all:
            with self.db.conn:
                self.db.conn.execute("DELETE FROM segments WHERE project_id=?", (self.project_id,))
            if clip_dir.exists():
                for f in clip_dir.glob("*.wav"):
                    try: f.unlink(missing_ok=True)
                    except Exception: pass
            for p in work_dir.glob("preview_stream_*.mp4"):
                try: p.unlink(missing_ok=True)
                except Exception: pass
            (work_dir / "_tmp_preview.mp4").unlink(missing_ok=True)
            (work_dir / "preview_muxed.mp4").unlink(missing_ok=True)
            self.video_editor.set_dubbed_video_preview("")
            QMessageBox.information(self, "Ai Summarai", "✓ បានសម្អាតគ្រប់ជួរទាំងអស់ក្នុងគម្រោងនេះរួចរាល់! អ្នកអាចចុច '២. ស្រង់អត្ថបទចិន' ឡើងវិញបាន។")

        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self._refresh_table()
        segs = self.db.get_segments(self.project_id)
        dur = MediaEngine.get_duration_ms(self.video_path) if (self.video_path and Path(self.video_path).exists()) else 60000
        if segs:
            dur = max(dur, int(segs[-1].get("end_ms") or 0) + 1000)
        self.timeline_tracks.set_data(dur, segs, clip_markers=getattr(self, "_clip_markers", []))
        if hasattr(self, "video_editor"):
            self.video_editor.set_segments(segs)
        self._update_button_states()

    def _update_button_states(self):
        """ធ្វើសមកាលកម្មស្ថានភាពប៊ូតុងទាំង ៥ ឲ្យត្រូវតាមទិន្នន័យជាក់ស្តែងជានិច្ច ជាមួយនឹង Visual Stepper Bar"""
        has_video = bool(self.video_path and Path(self.video_path).exists())
        segments = self.db.get_segments(self.project_id) if self.project_id else []
        has_lines = len(segments) > 0
        has_kh = any(bool((s.get("kh_text") or "").strip()) for s in segments)
        has_voiced = any(
            bool((s.get("tts_audio_path") or "") and Path(s["tts_audio_path"]).exists() and Path(s["tts_audio_path"]).stat().st_size > 512)
            for s in segments
        )

        self.btn_extract.setEnabled(has_video)
        self.btn_translate.setEnabled(has_lines)
        self.btn_dub.setEnabled(has_kh)
        self.btn_anti_copyright.setEnabled(has_video)
        self.btn_export.setEnabled(has_video and has_voiced)

        # Style Stepper Pills: Completed (#10B981 green), Active/Next (#00E5FF / #7C3AED), Pending (#8E95A5)
        # Includes attractive tactile lift on hover and pointer cursor
        style_completed = (
            "QPushButton { background: #181C24; color: #34D399; border: 1.5px solid #10B981; "
            "border-radius: 6px; padding: 4px 12px; font-weight: 700; font-size: 11.5px; } "
            "QPushButton:hover { background: #202632; border: 1.5px solid #34D399; color: #6EE7B7; padding: 3px 13px 5px 11px; } "
            "QPushButton:pressed { padding: 5px 11px 3px 13px; }"
        )
        style_active_cyan = (
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0891B2, stop:1 #06B6D4); "
            "color: #FFFFFF; border: 1.5px solid #00E5FF; border-radius: 6px; padding: 4px 12px; "
            "font-weight: 800; font-size: 11.5px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06B6D4, stop:1 #22D3EE); "
            "border: 1.5px solid #67E8F9; padding: 3px 13px 5px 11px; } "
            "QPushButton:pressed { padding: 5px 11px 3px 13px; }"
        )
        style_active_violet = (
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #6D28D9); "
            "color: #FFFFFF; border: 1.5px solid #A78BFA; border-radius: 6px; padding: 4px 12px; "
            "font-weight: 800; font-size: 11.5px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8B5CF6, stop:1 #7C3AED); "
            "border: 1.5px solid #C4B5FD; padding: 3px 13px 5px 11px; } "
            "QPushButton:pressed { padding: 5px 11px 3px 13px; }"
        )
        style_active_amber = (
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #D97706, stop:1 #B45309); "
            "color: #FFFFFF; border: 1.5px solid #FBBF24; border-radius: 6px; padding: 4px 12px; "
            "font-weight: 800; font-size: 11.5px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F59E0B, stop:1 #D97706); "
            "border: 1.5px solid #FDE68A; padding: 3px 13px 5px 11px; } "
            "QPushButton:pressed { padding: 5px 11px 3px 13px; }"
        )
        style_pending = (
            "QPushButton { background: #12151B; color: #8E95A5; border: 1px solid #252A36; "
            "border-radius: 6px; padding: 4px 10px; font-weight: 600; font-size: 11.5px; } "
            "QPushButton:hover { background: #181C24; border: 1px solid #3E4656; color: #BAC2D1; padding: 3px 11px 5px 9px; } "
            "QPushButton:pressed { padding: 5px 9px 3px 11px; }"
        )

        kh = self.lang == "kh"

        # Step: Open Video
        self.btn_open.setCursor(Qt.PointingHandCursor)
        if has_video:
            self.btn_open.setText("✓ បើកវីដេអូ" if kh else "✓ Open Video")
            self.btn_open.setStyleSheet(style_completed)
        else:
            self.btn_open.setText("បើកវីដេអូ" if kh else "Open Video")
            self.btn_open.setStyleSheet(style_active_cyan)

        # Step: Scan Subtitles
        self.btn_extract.setCursor(Qt.PointingHandCursor)
        if has_lines:
            self.btn_extract.setText("✓ ស្កេនភាសាចិន" if kh else "✓ Scan ZH")
            self.btn_extract.setStyleSheet(style_completed)
        elif has_video:
            self.btn_extract.setText("ស្កេនភាសាចិន" if kh else "Scan ZH")
            self.btn_extract.setStyleSheet(style_active_cyan)
        else:
            self.btn_extract.setText("ស្កេនភាសាចិន" if kh else "Scan ZH")
            self.btn_extract.setStyleSheet(style_pending)

        # Step: AI Translate
        self.btn_translate.setCursor(Qt.PointingHandCursor)
        if has_kh:
            self.btn_translate.setText("✓ បកប្រែជាខ្មែរ" if kh else "✓ Translate KH")
            self.btn_translate.setStyleSheet(style_completed)
        elif has_lines:
            self.btn_translate.setText("បកប្រែជាខ្មែរ" if kh else "Translate KH")
            self.btn_translate.setStyleSheet(style_active_violet)
        else:
            self.btn_translate.setText("បកប្រែជាខ្មែរ" if kh else "Translate KH")
            self.btn_translate.setStyleSheet(style_pending)

        # Step: AI Dubbing
        self.btn_dub.setCursor(Qt.PointingHandCursor)
        if has_voiced:
            self.btn_dub.setText("✓ បង្កើតសំឡេងខ្មែរ" if kh else "✓ Generate Voice")
            self.btn_dub.setStyleSheet(style_completed)
        elif has_kh:
            self.btn_dub.setText("បង្កើតសំឡេងខ្មែរ" if kh else "Generate Voice")
            self.btn_dub.setStyleSheet(style_active_amber)
        else:
            self.btn_dub.setText("បង្កើតសំឡេងខ្មែរ" if kh else "Generate Voice")
            self.btn_dub.setStyleSheet(style_pending)

    def _ensure_workflow_dialog(self) -> WorkflowViewDialog:
        if getattr(self, "_workflow_dialog", None) is None:
            self._workflow_dialog = WorkflowViewDialog(lang=self.lang, parent=self)
            self._workflow_dialog.stop_requested.connect(self._stop_worker)
            self._workflow_dialog.stage_triggered.connect(self._on_workflow_stage_clicked)
            if hasattr(self, "lbl_encoder"):
                self._workflow_dialog.update_hw_metrics(self.lbl_encoder.text())
        return self._workflow_dialog

    def _open_workflow_view(self, tab_idx: int = 0, compact: bool = False):
        wf = self._ensure_workflow_dialog()
        wf.lang = self.lang
        self._sync_workflow_snapshot()
        wf.set_view_mode(tab_index=tab_idx, compact=compact)
        wf.show()
        wf.raise_()
        wf.activateWindow()

    def _on_workflow_stage_clicked(self, stage_key: str):
        if stage_key == "input":
            self._browse_video()
        elif stage_key == "scan":
            self._run_extract()
        elif stage_key == "translate":
            self._run_translate()
        elif stage_key == "dub":
            self._run_dub_voice()
        elif stage_key == "fx":
            self._open_anti_copyright_dialog()
        elif stage_key == "export":
            self._run_export_video()

    def _sync_workflow_snapshot(self, exported_name: str = ""):
        wf = getattr(self, "_workflow_dialog", None)
        if wf is None:
            return
        try:
            proj_name = Path(self.video_path).name if self.video_path else ""
            segs = self.db.get_segments(self.project_id) if self.project_id else []
            total_s = len(segs)
            trans_s = sum(1 for s in segs if (s.get("kh_text") or "").strip())
            dub_s = sum(1 for s in segs if s.get("tts_audio_path") and Path(s["tts_audio_path"]).exists())
            edits = self.db.get_project_edits(self.project_id) if self.project_id else {}
            fx_bits = []
            if edits.get("lut_preset") and edits.get("lut_preset") != "none":
                fx_bits.append(f"LUT:{edits['lut_preset']}")
            if edits.get("anti_copyright_enabled"):
                fx_bits.append(f"AC:{edits.get('anti_copyright_level', 'medium')}")
            if edits.get("auto_timed_blur"):
                fx_bits.append("TimedBlur")
            if edits.get("keep_bgm_only"):
                fx_bits.append("BGM-Only")
            if edits.get("hd_upscale_enabled"):
                fx_bits.append("HD-Up")
            wf.sync_project_snapshot(
                project_name=proj_name,
                video_info=f"Project #{self.project_id}" if self.project_id else "",
                total_segs=total_s,
                translated_segs=trans_s,
                dubbed_segs=dub_s,
                fx_summary=" • ".join(fx_bits),
                exported_name=exported_name,
            )
        except Exception:
            pass

    def _run_worker(self, fn, on_complete_extra=None, stage_key: str = ""):
        if self.worker and self.worker.isRunning():
            return
        self._cancel_event.clear()
        self.pbar.setValue(5)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setVisible(True)
        wf = getattr(self, "_workflow_dialog", None)
        if wf is None and hasattr(self, "act_wf_auto") and self.act_wf_auto.isChecked():
            self._open_workflow_view(0, False)
            wf = self._workflow_dialog
        if wf is not None:
            self._sync_workflow_snapshot()
            wf.on_stage_started(stage_key, "កំពុងចាប់ផ្តើមដំណើរការ...")
        self.worker = PipelineWorker(fn)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished_ok.connect(lambda msg: self._on_done(msg, on_complete_extra))
        self.worker.stopped.connect(self._on_stopped)
        self.worker.failed.connect(self._on_error)
        self.worker.start()

    def _stop_worker(self):
        self._cancel_event.set()
        MediaEngine.cancel_all_processes()
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.btn_stop.setEnabled(False)
            self.status_lbl.setText("⏹ កំពុងបញ្ឈប់ដោយសុវត្ថិភាព និងរក្សាទុកទិន្នន័យ...")

    def _on_worker_progress(self, pct: int, msg: str):
        self.pbar.setValue(pct)
        self.status_lbl.setText(msg)
        self._update_table_cells_live()
        wf = getattr(self, "_workflow_dialog", None)
        if wf is not None:
            wf.on_stage_progress(pct, msg)

    def _on_done(self, msg: str, extra_fn=None):
        self.btn_stop.setEnabled(False)
        self.pbar.setValue(100)
        self.status_lbl.setText(msg)
        self._refresh_table()
        if extra_fn:
            extra_fn()
        self._update_button_states()
        self._ensure_preview_visible()
        wf = getattr(self, "_workflow_dialog", None)
        if wf is not None:
            wf.on_stage_finished(msg)
            self._sync_workflow_snapshot()

    def _on_stopped(self, msg: str):
        self.btn_stop.setEnabled(False)
        self.status_lbl.setText(msg)
        self._refresh_table()
        self._update_button_states()
        self._ensure_preview_visible()
        wf = getattr(self, "_workflow_dialog", None)
        if wf is not None:
            wf.on_stage_stopped(msg)
            self._sync_workflow_snapshot()

    def _on_error(self, err: str):
        self.btn_stop.setEnabled(False)
        self.pbar.setValue(0)
        self.status_lbl.setText(tr(self.lang, "status_error"))
        self._refresh_table()
        self._update_button_states()
        self._ensure_preview_visible()
        wf = getattr(self, "_workflow_dialog", None)
        if wf is not None:
            wf.on_stage_failed(err)
            self._sync_workflow_snapshot()
        QMessageBox.critical(self, "Error", err)

    def _ensure_preview_visible(self):
        """ធានាថាផ្ទាំង Video Preview មិនដែលក្លាយជាពណ៌ខ្មៅឡើយ ទោះបីមាន Error ក៏ដោយ"""
        if not hasattr(self, "video_editor") or not self.video_path or not Path(self.video_path).exists():
            return
        if self.video_editor.player.source().isEmpty():
            work_dir = Path(f"data/workspace/proj_{self.project_id}") if self.project_id else None
            previews = sorted(work_dir.glob("preview_stream_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if work_dir and work_dir.exists() else []
            preview_mp4 = previews[0] if previews else None
            if not preview_mp4 or not preview_mp4.exists():
                if work_dir and (work_dir / "_tmp_preview.mp4").exists():
                    preview_mp4 = work_dir / "_tmp_preview.mp4"
                elif work_dir and (work_dir / "preview_muxed.mp4").exists():
                    preview_mp4 = work_dir / "preview_muxed.mp4"

            if preview_mp4 and preview_mp4.exists():
                self.video_editor.set_dubbed_video_preview(str(preview_mp4))
            else:
                self.video_editor.set_dubbed_video_preview(self.video_path)

    def _run_extract(self):
        if not self.project_id:
            return
        if not self.video_path or not Path(self.video_path).exists():
            QMessageBox.warning(self, "Ai Summarai", "សូមបើកវីដេអូជាមុនសិន មុននឹងស្កេនអត្ថបទចិន!")
            return

        existing_segs = self.db.get_segments(self.project_id)
        replace_all = False
        if existing_segs:
            msg = QMessageBox(self)
            msg.setWindowTitle("Ai Summarai — ស្កេនអត្ថបទចិន (Scan ZH)")
            msg.setText(
                f"គម្រោងនេះមានអត្ថបទស្រង់រួចចំនួន {len(existing_segs)} ជួរហើយ!\n"
                "តើអ្នកចង់ស្កេនថ្មីជំនួសទាំងអស់ (Replace All) ឬស្កេនបន្ថែម (Append)?"
                if self.lang == "kh" else
                f"This project already has {len(existing_segs)} extracted lines.\n"
                "Do you want to Rescan & Replace All, or Append new lines?"
            )
            btn_replace = msg.addButton("🔄 ស្កេនថ្មីជំនួសទាំងអស់ (Replace All)" if self.lang == "kh" else "🔄 Replace All", QMessageBox.ActionRole)
            btn_append = msg.addButton("➕ ស្កេនបន្ថែម (Append)" if self.lang == "kh" else "➕ Append", QMessageBox.ActionRole)
            btn_cancel = msg.addButton("❌ បោះបង់ (Cancel)" if self.lang == "kh" else "❌ Cancel", QMessageBox.RejectRole)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == btn_cancel or not clicked:
                return
            replace_all = (clicked == btn_replace)

        mode = "voice" if self.extract_mode.currentIndex() == 0 else "ocr"
        asr_mode = int(self.db.get_setting("asr_mode", "0"))
        api_url = self.db.get_setting("api_url", "http://localhost:11434/v1")
        api_key = self.db.get_setting("api_key", "")

        def task(emit):
            work_dir = Path(f"data/workspace/proj_{self.project_id}")
            work_dir.mkdir(parents=True, exist_ok=True)
            if replace_all:
                emit(5, "កំពុងសម្អាតទិន្នន័យចាស់...")
                with self.db.conn:
                    self.db.conn.execute("DELETE FROM segments WHERE project_id=?", (self.project_id,))
                clip_dir = work_dir / "tts"
                if clip_dir.exists():
                    for f in clip_dir.glob("*.wav"):
                        try:
                            f.unlink(missing_ok=True)
                        except Exception:
                            pass
                for p in work_dir.glob("preview_stream_*.mp4"):
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                (work_dir / "_tmp_preview.mp4").unlink(missing_ok=True)
                (work_dir / "preview_muxed.mp4").unlink(missing_ok=True)

            if mode == "voice":
                emit(15, "Streaming audio in 10-minute windows...")
                from core.transcriber import SpeechTranscriber
                asr = SpeechTranscriber()
                items = LongVideoStreamEngine.stream_voice_long_video(
                    video_path=self.video_path,
                    work_dir=str(work_dir),
                    transcriber=asr,
                    mode="local" if asr_mode == 0 else "api",
                    api_cfg={"api_key": api_key, "base_url": api_url, "whisper_model": "base"},
                    progress_cb=lambda p, msg: emit(15 + int(p * 0.80), msg),
                    stop_event=self._cancel_event,
                )
            else:
                emit(15, "Streaming subtitle area in 10-minute windows (2 FPS)...")
                crop_y = int(self.db.get_setting("ocr_y_pct", "72")) / 100.0
                crop_h = int(self.db.get_setting("ocr_h_pct", "28")) / 100.0
                from core.ocr_scanner import SubtitleOCRScanner
                scanner = SubtitleOCRScanner()
                items = LongVideoStreamEngine.stream_ocr_long_video(
                    video_path=self.video_path,
                    work_dir=str(work_dir),
                    scanner=scanner,
                    fps=2,
                    crop_ratio=crop_h,
                    crop_y_offset=crop_y,
                    progress_cb=lambda p, msg: emit(15 + int(p * 0.80), msg),
                    stop_event=self._cancel_event,
                )
            self.db.insert_segments(self.project_id, items)
            self.db.fix_all_overlaps(self.project_id)
            return f"Done — {len(items)} short, accurate lines extracted."

        def on_extract_done():
            if getattr(self, "active_series_profile_id", 0) > 0:
                prof = self.db.get_series_profile(self.active_series_profile_id)
                if prof and prof.get("default_voice_map"):
                    self._apply_series_voice_memory_to_segments(self.project_id, prof["default_voice_map"])
            self.btn_translate.setEnabled(True)
            self.table.blockSignals(True)
            self.table.clearContents()
            self.table.setRowCount(0)
            self.table.blockSignals(False)
            self._refresh_table()
            segs = self.db.get_segments(self.project_id)
            dur = MediaEngine.get_duration_ms(self.video_path) if (self.video_path and Path(self.video_path).exists()) else 60000
            if segs:
                dur = max(dur, int(segs[-1].get("end_ms") or 0) + 1000)
            self.timeline_tracks.set_data(dur, segs, clip_markers=getattr(self, "_clip_markers", []))
            if hasattr(self, "video_editor"):
                self.video_editor.set_segments(segs)
            self._update_button_states()
            if self.lang == "kh":
                self.status_lbl.setText(f"✓ ស្រង់អត្ថបទបានជោគជ័យ {len(segs)} ជួរ!")
            else:
                self.status_lbl.setText(f"✓ Extracted {len(segs)} lines successfully!")

        self._run_worker(task, on_extract_done)

    def _open_package_updater(self):
        dlg = PackageUpdaterDialog(
            self.db,
            lang=self.lang,
            run_worker_fn=self._run_worker,
            parent=self,
        )
        dlg.exec()

    def _update_license_badge(self):
        ok, msg, days, info = get_active_license_status()
        if ok:
            if days >= 30000:
                self.btn_license.setText("🛡️ Lifetime VIP")
                self.btn_license.setStyleSheet("border: 1px solid #10B981; color: #10B981; font-weight: 700; border-radius: 6px; padding: 4px 10px;")
            else:
                self.btn_license.setText(f"🛡️ {days} ថ្ងៃ" if self.lang == "kh" else f"🛡️ {days} Days")
                color = "#10B981" if days > 7 else ("#F59E0B" if days > 2 else "#EF4444")
                self.btn_license.setStyleSheet(f"border: 1px solid {color}; color: {color}; font-weight: 700; border-radius: 6px; padding: 4px 10px;")
        else:
            self.btn_license.setText("🛡️ ផុតកំណត់" if self.lang == "kh" else "🛡️ Expired")
            self.btn_license.setStyleSheet("border: 1px solid #EF4444; color: #EF4444; font-weight: 700; border-radius: 6px; padding: 4px 10px;")

    def _open_license_dialog(self):
        dlg = LicenseActivationDialog(parent=self, is_forced=False)
        if dlg.exec():
            self._update_license_badge()

    def _check_update_silently(self):
        try:
            from core.updater import InAppPackageUpdater, get_updater_config, GITHUB_MANIFEST_URL
            cfg = get_updater_config()
            if not cfg.get("auto_check_updates", True):
                return
            src = cfg.get("manifest_url") or cfg.get("github_repo_url") or GITHUB_MANIFEST_URL
            if not src:
                return

            def _bg():
                res = InAppPackageUpdater.check_for_updates(src)
                if res and res.get("has_update"):
                    rem_v = res.get("remote_version")
                    kh = self.lang == "kh"
                    QTimer.singleShot(0, lambda: self._apply_update_badge(rem_v, kh))

            t = threading.Thread(target=_bg, daemon=True)
            t.start()
        except Exception:
            pass

    def _apply_update_badge(self, rem_v: str, kh: bool):
        try:
            self.btn_update_pkg.setText(f"🔔 កំណែថ្មី v{rem_v}" if kh else f"🔔 Update v{rem_v}")
            self.btn_update_pkg.setStyleSheet("background-color: #059669; color: #FFFFFF; font-weight: bold; border-radius: 6px; padding: 4px 10px;")
            self.btn_update_pkg.setToolTip(
                f"មានកំណែអាប់ដេតថ្មី v{rem_v} នៅលើ GitHub!\nចុចទីនេះដើម្បីទាញយកកូដថ្មីភ្លាមៗ" if kh
                else f"New version v{rem_v} available on GitHub!\nClick here to update code."
            )
            if hasattr(self, "status_lbl"):
                self.status_lbl.setText(f"🎉 មានកំណែថ្មី v{rem_v} នៅលើ GitHub! សូមចុចប៊ូតុង Update ដើម្បីបញ្ចូលកូដថ្មី។")
        except Exception:
            pass

    def _open_find_replace(self):
        if not self.project_id:
            return

        def on_updated(count: int, single: bool):
            self._refresh_table()
            segs = self.db.get_segments(self.project_id)
            total_ms = self.video_editor.player.duration() or 60000
            if segs:
                total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
            self.timeline_tracks.set_data(total_ms, segs)
            if self.lang == "kh":
                self.status_lbl.setText(f"✏️ បានកែពាក្យខុសចំនួន {count} ជួររួចរាល់!")
            else:
                self.status_lbl.setText(f"✏️ Replaced text in {count} row(s)!")

        def on_jump_row(row_idx: int):
            if 0 <= row_idx < self.table.rowCount():
                self.table.selectRow(row_idx)
                item = self.table.item(row_idx, 2) or self.table.item(row_idx, 1)
                if item:
                    self.table.scrollToItem(item)

        dlg = FindReplaceDialog(
            self.db,
            self.project_id,
            lang=self.lang,
            on_updated_cb=on_updated,
            on_jump_row_cb=on_jump_row,
            parent=self,
        )
        dlg.exec()

    def _open_voice_clone_studio(self):
        """បើកផ្ទាំង Voice Clone Studio (ក្លូន និងបង្កើតសំឡេងមនុស្សពិតខ្មែរ)"""
        from ui.voice_clone_dialog import VoiceCloneDialog
        dlg = VoiceCloneDialog(self.db, parent=self, lang=self.lang)
        dlg.voice_saved.connect(self._on_voice_cloned_or_selected)
        dlg.exec()

    def _open_videofx_studio(self):
        """បើកផ្ទាំង VideoFX Studio (3D LUTs, Masking, Animated Text)"""
        try:
            from ui.video_fx_studio import VideoFXStudioWindow
            self._fx_studio = VideoFXStudioWindow(parent=self, initial_video_path=self.video_path)
            self._fx_studio.show()
        except Exception as e:
            QMessageBox.critical(self, "VideoFX Studio Error", f"មិនអាចបើក VideoFX Studio បានទេ: {e}")

    def _open_all_in_one_studio(self):
        """បើកផ្ទាំង 4-Zone All-in-One AI Video, Dubbing, Recap & FX Studio"""
        try:
            from ui.all_in_one_studio import AllInOneStudioWindow
            self._aio_studio = AllInOneStudioWindow(parent=self, initial_video_path=self.video_path)
            self._aio_studio.show()
        except Exception as e:
            QMessageBox.critical(self, "All-in-One Studio Error", f"មិនអាចបើក All-in-One Studio បានទេ: {e}")

    def _open_speaker_mapper_dialog(self):
        """បើកផ្ទាំង Multi-Speaker Role Mapper Dialog"""
        try:
            from ui.dialogs.speaker_mapper_dialog import SpeakerMapperDialog
            from config.settings import SubtitleSettings
            cfg = SubtitleSettings.load()
            dlg = SpeakerMapperDialog(speaker_map=cfg.get("speaker_map", {}), parent=self)
            dlg.speaker_map_saved.connect(lambda m: SubtitleSettings.set("speaker_map", m))
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Speaker Mapper Error", f"មិនអាចបើក Speaker Mapper បានទេ: {e}")

    def _open_setup_manager_dialog(self):
        """បើកផ្ទាំង Setup & Model Manager Modal (FFmpeg, NVENC GPU, Ollama)"""
        try:
            from ui.dialogs.setup_manager_dialog import SetupManagerDialog
            from config.settings import SubtitleSettings
            cfg = SubtitleSettings.load()
            dlg = SetupManagerDialog(
                ollama_url=cfg.get("ollama_url", "http://localhost:11434"),
                target_model=cfg.get("model_name", "qwen2.5:7b"),
                parent=self,
            )
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Setup Manager Error", f"មិនអាចបើក Setup Manager បានទេ: {e}")

    def _on_voice_cloned_or_selected(self, voice_key: str):
        """ពេលរក្សាទុកសំឡេងក្លូនថ្មី ឬជ្រើសរើសសំឡេង -> Refresh តារាង Subtitle ភ្លាមៗ"""
        self._refresh_table()
        if voice_key:
            kh = self.lang == "kh"
            self.status_lbl.setText(
                f"🎙️ បានបន្ថែមសំឡេងមនុស្សថ្មី ({voice_key})! អាចជ្រើសរើសក្នុងតារាងបានហើយ។" if kh
                else f"🎙️ New voice ({voice_key}) ready in table!"
            )

    def _run_clean_noise(self):
        if not self.project_id:
            return
        removed = self.db.clean_noise_segments(self.project_id)
        self._refresh_table()
        segs = self.db.get_segments(self.project_id)
        total_ms = self.video_editor.player.duration() or 60000
        if segs:
            total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
        self.timeline_tracks.set_data(total_ms, segs)

        if self.lang == "kh":
            self.status_lbl.setText(f"🧹 បានសម្អាតជួរសំរាម និង Watermark ចំនួន {removed} ជួររួចរាល់!")
        else:
            self.status_lbl.setText(f"🧹 Cleaned {removed} noise/watermark rows!")

    def _release_preview_audio_lock(self):
        """ដោះ File Lock ពី Player តែមួយភ្លែត (0.05s) មុននឹងប្តូរឈ្មោះ _tmp_preview.mp4 -> preview_muxed.mp4"""
        self.row_player.stop()
        self.row_player.setSource(QUrl())
        if hasattr(self, "video_editor"):
            self.video_editor.pause()
            self.video_editor.player.stop()
            self.video_editor.player.setSource(QUrl())

    def _apply_tmp_preview_to_player(self):
        """ប្តូរឯកសារ _tmp_preview.mp4 ទៅជា preview video ថ្មី ដោយមិនឲ្យជាន់ File Lock លើ Windows"""
        if not self.project_id or not self.video_path or not Path(self.video_path).exists():
            return
        work_dir = Path(f"data/workspace/proj_{self.project_id}")
        tmp_mp4 = work_dir / "_tmp_preview.mp4"
        if tmp_mp4.exists() and tmp_mp4.stat().st_size > 1024:
            new_preview_path = work_dir / f"preview_stream_{int(time.time() * 1000)}.mp4"
            try:
                shutil.move(str(tmp_mp4), str(new_preview_path))
            except Exception:
                try:
                    shutil.copy2(str(tmp_mp4), str(new_preview_path))
                    tmp_mp4.unlink(missing_ok=True)
                except Exception:
                    new_preview_path = tmp_mp4

            if new_preview_path.exists() and new_preview_path.stat().st_size > 1024:
                self.video_editor.set_dubbed_video_preview(str(new_preview_path))
                for old in work_dir.glob("preview_stream_*.mp4"):
                    if str(old.resolve()) != str(new_preview_path.resolve()):
                        try:
                            old.unlink(missing_ok=True)
                        except Exception:
                            pass
        else:
            previews = sorted(
                [p for p in work_dir.glob("preview_stream_*.mp4") if p.exists() and p.stat().st_size > 1024],
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if previews:
                self.video_editor.set_dubbed_video_preview(str(previews[0]))
            elif (work_dir / "preview_muxed.mp4").exists() and (work_dir / "preview_muxed.mp4").stat().st_size > 1024:
                self.video_editor.set_dubbed_video_preview(str(work_dir / "preview_muxed.mp4"))

    def _update_table_cells_live(self):
        """អាប់ដេតអក្សរខ្មែរក្នុងតារាងភ្លាមៗរៀងរាល់ ១០ ជួរ ដោយមិនបាច់សង់តារាងថ្មីទាំងមូល"""
        if not self.project_id:
            return
        now = time.time()
        if hasattr(self, "_last_live_cell_time") and now - self._last_live_cell_time < 0.25:
            return
        self._last_live_cell_time = now
        try:
            segs = self.db.get_segments(self.project_id)
            if len(segs) != self.table.rowCount():
                return
            self.table.blockSignals(True)
            font_kh = QFont("Kantumruy Pro", 9)
            font_kh.setFamilies(["Kantumruy Pro", "Noto Sans Khmer", "Khmer OS Battambang", "Segoe UI"])

            for row, seg in enumerate(segs):
                kh_item = self.table.item(row, 3)
                if kh_item:
                    if kh_item.text() != seg["kh_text"]:
                        kh_item.setText(seg["kh_text"])
                else:
                    kh_item = QTableWidgetItem(seg["kh_text"])
                    kh_item.setFont(font_kh)
                    self.table.setItem(row, 3, kh_item)

                st_item = self.table.item(row, 6)
                if st_item:
                    if st_item.text() != seg["status"]:
                        st_item.setText(seg["status"])
                        self._style_state_item(st_item, seg["status"])
                else:
                    st_item = QTableWidgetItem(seg["status"])
                    self._style_state_item(st_item, seg["status"])
                    self.table.setItem(row, 6, st_item)
            self.table.blockSignals(False)
        except Exception:
            pass

    def _rebuild_smooth_preview(self):
        """បង្កើត preview_muxed.mp4 ដោយមិនធ្វើឲ្យបាត់រូបភាពលើផ្ទាំង Preview ឡើយ"""
        if not self.project_id or not self.video_path or not Path(self.video_path).exists():
            return
        if self.worker and self.worker.isRunning():
            return

        segs = self.db.get_segments(self.project_id)
        sfx_list = self.db.get_sfx_events(self.project_id)
        edits = self.db.get_project_edits(self.project_id)
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        valid_audio = [s for s in segs if (s.get("tts_audio_path") or "") and Path(s["tts_audio_path"]).exists()]
        if not valid_audio and not sfx_list and not keep_bgm_only:
            self.video_editor.set_original_volume(self.bgm_slider.value())
            self._ensure_preview_visible()
            return

        tmp_mp4 = str(Path(f"data/workspace/proj_{self.project_id}") / "_tmp_preview.mp4")
        bgm_vol = round(self.bgm_slider.value() / 100.0, 2)
        if keep_bgm_only and bgm_vol <= 0.01:
            bgm_vol = 0.35

        def task(emit):
            msg_pv = "🎼 កំពុងបំបាត់សំឡេងនិយាយដើម & អាប់ដេត Clean BGM Preview..." if keep_bgm_only else "កំពុងអាប់ដេតសំឡេង Preview (-c:v copy)..."
            emit(40, msg_pv)
            MediaEngine.build_fast_preview_video(
                self.video_path,
                segs,
                tmp_mp4,
                bgm_volume=bgm_vol,
                voice_gain=2.2,
                edits=self.db.get_project_edits(self.project_id),
                sfx_events=self.db.get_sfx_events(self.project_id),
            )
            return (
                f"🎼 បើក Keep BGM Only ជោគជ័យ (ភ្លេងដើម {int(bgm_vol * 100)}%, បំបាត់សំឡេងនិយាយចិន)!"
                if keep_bgm_only
                else f"បានអាប់ដេតកម្រិតសំឡេងវីដេអូដើម ({self.bgm_slider.value()}%) រួចរាល់!"
            )

        self._run_worker(task, self._apply_tmp_preview_to_player)

    def _run_translate(self, force_all: bool = False, target_segment_ids: list = None):
        segments = self.db.get_segments(self.project_id)
        if not segments:
            return
        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "gemini-2.5-flash")

        # ពិនិត្យរកមើលប្រយោគដែលមានអក្សរខ្មែរពិតប្រាកដ (Unicode \u1780-\u17FF)
        def is_valid_khmer(t: str) -> bool:
            return bool(t and re.search(r"[\u1780-\u17ff]", t))

        if target_segment_ids is not None:
            t_set = set(target_segment_ids)
            target_segs = [s for s in segments if s["id"] in t_set]
        elif force_all:
            target_segs = segments
        else:
            pending_segs = [s for s in segments if not is_valid_khmer(s.get("kh_text") or "")]
            if not pending_segs:
                ret = QMessageBox.question(
                    self,
                    "Ai Summarai",
                    "គ្រប់ជួរទាំងអស់ត្រូវបានបកប្រែជាភាសាខ្មែររួចរាល់ហើយ!\nតើអ្នកចង់បកប្រែឡើងវិញទាំងអស់ (Retranslate All Lines) ឬទេ?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if ret == QMessageBox.Yes:
                    target_segs = segments
                else:
                    return
            else:
                target_segs = pending_segs

        if not target_segs:
            return

        def task(emit):
            # ជំហានទី ៣៖ បកប្រែ ចិន -> ខ្មែរ រក្សាទុកចូល SQLite រៀងរាល់ ១០ ជួរម្តង (Live Checkpoint)
            from core.translator import ZHtoKHTranslator
            glossary = self.db.get_glossary()
            dub_style = self.combo_trans_style.currentData() if hasattr(self, "combo_trans_style") else "literal"
            translator = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=glossary, dub_style=dub_style)

            def _save_chunk_to_db(chunk_map: dict):
                from core.translator import strip_chinese_from_khmer
                for seg_id, kh_text in chunk_map.items():
                    clean_kh = strip_chinese_from_khmer(kh_text) if kh_text else ""
                    if is_valid_khmer(clean_kh):
                        self.db.update_segment(seg_id, kh_text=clean_kh, status="Ready", tts_audio_path="")

            if force_all:
                work_dir = Path(f"data/workspace/proj_{self.project_id}")
                for p in work_dir.glob("preview_stream_*.mp4"):
                    try: p.unlink(missing_ok=True)
                    except Exception: pass
                (work_dir / "_tmp_preview.mp4").unlink(missing_ok=True)
                (work_dir / "preview_muxed.mp4").unlink(missing_ok=True)

            translated = translator.translate_segments(
                target_segs,
                progress_cb=lambda p: emit(int(p), f"កំពុងបកប្រែ ចិន → ខ្មែរ... {p}% (រក្សាទុកស្វ័យប្រវត្តិ)"),
                batch_done_cb=_save_chunk_to_db,
                stop_event=self._cancel_event,
            )
            from core.translator import strip_chinese_from_khmer
            for seg_id, kh_text in translated.items():
                clean_kh = strip_chinese_from_khmer(kh_text) if kh_text else ""
                if is_valid_khmer(clean_kh):
                    self.db.update_segment(seg_id, kh_text=clean_kh, status="Ready", tts_audio_path="")

            if self._cancel_event.is_set():
                return "⏹ បានផ្អាកការបកប្រែ! ទិន្នន័យដែលធ្វើរួចត្រូវបានរក្សាទុកក្នុងគម្រោង។"

            return f"បកប្រែជាខ្មែររួចរាល់ ({len(target_segs)} ជួរ)។ សូមចុចប៊ូតុង ៤. បញ្ចូលសំឡេងខ្មែរ (Dub)!"

        def on_complete():
            self.btn_dub.setEnabled(True)
            self.table.blockSignals(True)
            self.table.clearContents()
            self.table.setRowCount(0)
            self.table.blockSignals(False)
            self._refresh_table()
            segs = self.db.get_segments(self.project_id)
            dur = MediaEngine.get_duration_ms(self.video_path) if (self.video_path and Path(self.video_path).exists()) else 60000
            if segs:
                dur = max(dur, int(segs[-1].get("end_ms") or 0) + 1000)
            self.timeline_tracks.set_data(dur, segs, clip_markers=getattr(self, "_clip_markers", []))
            if hasattr(self, "video_editor"):
                self.video_editor.set_segments(segs)
            self._update_button_states()

        self._run_worker(task, on_complete)

    def _run_dub_voice(self, force_all: bool = False, target_segment_ids: list = None):
        """ជំហានទី ៤៖ បង្កើតតែឯកសារសំឡេងខ្មែរ (TTS) និងអាប់ដេតសំឡេងក្នុង Video Preview (គាំទ្រ Dub Missing & Redub All)"""
        if not self.project_id:
            return
        segments = self.db.get_segments(self.project_id)
        if not segments:
            return

        # បញ្ឈប់ការចាក់សំឡេងជាមុន ដោះលែង File Lock [WinError 32] លើ Windows
        if hasattr(self, "row_player"):
            self.row_player.stop()
            self.row_player.setSource(QUrl())
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
            self.video_editor.pause()

        def _is_unvoiced(s):
            w = s.get("tts_audio_path") or ""
            return s.get("status") != "Voiced" or not w or not Path(w).exists() or Path(w).stat().st_size <= 512

        unvoiced_count = sum(1 for s in segments if _is_unvoiced(s))
        if target_segment_ids is None:
            from ui.dub_voice_dialog import DubVoiceSelectionDialog
            dlg = DubVoiceSelectionDialog(
                self.db,
                unvoiced_count=unvoiced_count,
                total_count=len(segments),
                lang=self.lang,
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return
            voice_type, profile_key, voice_label, force_all = dlg.get_selection()
            if voice_type == "ai":
                self.db.set_setting("kh_voice_label", voice_label)
                default_voice = DEFAULT_VOICES.get(voice_label, "km-KH-SreymomNeural")
            else:
                default_voice = profile_key
        else:
            voice_label = self.db.get_setting("kh_voice_label", "Female (Sreymom)")
            default_voice = DEFAULT_VOICES.get(voice_label, "km-KH-SreymomNeural")

        bgm_vol = round(self.bgm_slider.value() / 100.0, 2)

        def task(emit):
            # ១. តម្រៀបម៉ោងគ្រប់ជួរឲ្យមិនជាន់គ្នាជាមុន (Strict Monotonic Slots)
            self.db.fix_all_overlaps(self.project_id)
            if force_all:
                with self.db.conn:
                    self.db.conn.execute("UPDATE segments SET tts_audio_path='', status='Ready' WHERE project_id=?", (self.project_id,))
            segments = self.db.get_segments(self.project_id)

            if target_segment_ids is not None:
                t_set = set(target_segment_ids)
                segs_to_process = [s for s in segments if s["id"] in t_set]
            else:
                segs_to_process = segments

            # ២. បកប្រែបន្ថែមដោយស្វ័យប្រវត្តិសម្រាប់ជួរណាដែលនៅខ្វះអត្ថបទខ្មែរ (ការពារកុំឲ្យមានចន្លោះមិនឮសំឡេង)
            missing_kh = [
                s for s in segs_to_process
                if (s.get("zh_text") or "").strip() and not re.search(r"[\u1780-\u17ff]", s.get("kh_text") or "")
            ]
            if missing_kh:
                emit(3, f"កំពុងបកប្រែបំពេញ {len(missing_kh)} ជួរដែលនៅខ្វះ...")
                api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
                api_key = self.db.get_setting("api_key", "")
                model = self.db.get_setting("model", "gemini-3.1-flash-lite")
                from core.translator import ZHtoKHTranslator
                auto_tr = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=self.db.get_glossary())
                from core.translator import strip_chinese_from_khmer
                filled_map = auto_tr.translate_segments(missing_kh, stop_event=self._cancel_event)
                for sid, kht in filled_map.items():
                    clean_kht = strip_chinese_from_khmer(kht) if kht else ""
                    if clean_kht and re.search(r"[\u1780-\u17ff]", clean_kht):
                        self.db.update_segment(sid, kh_text=clean_kht, status="Ready")
                segments = self.db.get_segments(self.project_id)
                if target_segment_ids is not None:
                    t_set = set(target_segment_ids)
                    segs_to_process = [s for s in segments if s["id"] in t_set]
                else:
                    segs_to_process = segments

            from core.tts_engine import KhmerTTSEngine
            tts = KhmerTTSEngine()
            clip_dir = Path(f"data/workspace/proj_{self.project_id}/tts")
            clip_dir.mkdir(parents=True, exist_ok=True)

            total = len(segs_to_process)
            generated_count = 0

            for i, seg in enumerate(segs_to_process):
                if self._cancel_event.is_set():
                    return "⏹ បានផ្អាកការបង្កើតសំឡេង! ជួរដែលធ្វើរួចត្រូវបានរក្សាទុក។"

                clip_path = str(clip_dir / f"seg_{seg['id']}.wav")
                # Lock TTS duration strictly to the exact [start_ms, end_ms] speech window (zero lip-sync drift!)
                raw_dur_ms = max(250, int(seg["end_ms"]) - int(seg["start_ms"]))
                seg_idx = -1
                for idx_s, s in enumerate(segments):
                    if s["id"] == seg["id"]:
                        seg_idx = idx_s
                        break
                if seg_idx >= 0 and seg_idx + 1 < len(segments):
                    max_slot_ms = max(250, int(segments[seg_idx + 1]["start_ms"]) - int(seg["start_ms"]) - 20)
                    dur_ms = min(raw_dur_ms, max_slot_ms)
                else:
                    dur_ms = raw_dur_ms
                from core.translator import normalize_dub_khmer_text
                raw_kh = (seg.get("kh_text") or "").strip()
                kh_text = normalize_dub_khmer_text(raw_kh)
                if kh_text != raw_kh:
                    self.db.update_segment(seg["id"], kh_text=kh_text)

                if not kh_text:
                    if not Path(clip_path).exists() or Path(clip_path).stat().st_size <= 512:
                        tts.generate_fallback_clip(dur_ms, clip_path)
                    self.db.update_segment(seg["id"], tts_audio_path=clip_path, status="Voiced")
                    generated_count += 1
                    continue

                existing_wav = seg.get("tts_audio_path") or ""
                needs_synth = (
                    force_all
                    or target_segment_ids is not None
                    or seg.get("status") != "Voiced"
                    or not existing_wav
                    or not Path(existing_wav).exists()
                    or Path(existing_wav).stat().st_size <= 512
                )

                if needs_synth:
                    chosen_voice = seg.get("voice_override") or default_voice
                    success = False
                    for attempt in range(3):
                        try:
                            tts.generate_clip(kh_text, chosen_voice, dur_ms, clip_path, db=self.db, speed_mult=getattr(self, "tts_speed_mult", 1.0))
                            if Path(clip_path).exists() and Path(clip_path).stat().st_size > 512:
                                success = True
                                break
                        except Exception as tts_err:
                            print(f"[TTS Retry {attempt+1}/3] Segment {seg['id']}: {tts_err}")
                            time.sleep(0.3 * (attempt + 1))

                    if not success or not Path(clip_path).exists() or Path(clip_path).stat().st_size <= 512:
                        print(f"[TTS Fallback] Generating timed fallback clip for Segment {seg['id']}")
                        tts.generate_fallback_clip(dur_ms, clip_path)

                    self.db.update_segment(seg["id"], tts_audio_path=clip_path, status="Voiced")

                generated_count += 1
                emit(int(((i + 1) / max(1, total)) * 90), f"បង្កើតសំឡេងខ្មែរបាន {i+1}/{total} ជួរ...")
                time.sleep(0.04)

            if self.video_path and Path(self.video_path).exists():
                emit(94, "កំពុងអាប់ដេតសំឡេងខ្មែរក្នុង Video Preview (-c:v copy)...")
                try:
                    tmp_mp4 = str(Path(f"data/workspace/proj_{self.project_id}") / "_tmp_preview.mp4")
                    MediaEngine.build_fast_preview_video(
                        self.video_path,
                        self.db.get_segments(self.project_id),
                        tmp_mp4,
                        bgm_volume=0.0,
                        voice_gain=2.2,
                        edits=self.db.get_project_edits(self.project_id),
                        sfx_events=self.db.get_sfx_events(self.project_id),
                    )
                except Exception as prev_err:
                    print(f"[Preview Warning] Failed to update preview: {prev_err}")

            return tr(self.lang, "status_dub_done", count=generated_count)

        def after_dub():
            # បិទសំឡេងដើម (0%) ស្វ័យប្រវត្តិតាមការស្នើសុំ ធានាឮតែសំឡេងខ្មែរ 100% គ្មានសំឡេងចិនដើមលេចឮឡើយ
            self.bgm_slider.blockSignals(True)
            self.bgm_slider.setValue(0)
            self.bgm_slider.blockSignals(False)
            self.lbl_bgm_val.setText("0%")
            self.db.set_setting("bgm_volume_pct", "0")
            if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
                self.video_editor.edits["orig_volume"] = 0.0
                self.video_editor.edits["mute_original_audio"] = 1
                self.video_editor.edits["dubbed_no_orig_audio"] = 1
                self.video_editor.set_original_volume(0)
            if self.project_id:
                self.db.update_project_edits(self.project_id, orig_volume=0.0, mute_original_audio=1)
            self._apply_tmp_preview_to_player()
            self.table.blockSignals(True)
            self.table.clearContents()
            self.table.setRowCount(0)
            self.table.blockSignals(False)
            self._refresh_table()
            self._update_button_states()
            if self.video_path and Path(self.video_path).exists():
                self.btn_export.setEnabled(True)

        self._run_worker(task, after_dub)

    def _show_translate_context_menu(self, pos):
        if not self.project_id:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #161920; color: #F4F6FB; border: 1px solid #343B4C; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 14px; border-radius: 4px; font-size: 11px; }
            QMenu::item:selected { background: #202530; color: #00E5FF; }
        """)
        kh = self.lang == "kh"
        act_missing = menu.addAction("🌐 បកប្រែតែជួរដែលខ្វះ (Translate Missing)" if kh else "🌐 Translate Missing Lines")
        act_missing.triggered.connect(lambda: self._run_translate(force_all=False))

        act_all = menu.addAction("🔄 បកប្រែឡើងវិញទាំងអស់ (Retranslate All)" if kh else "🔄 Retranslate All Lines")
        act_all.triggered.connect(lambda: self._run_translate(force_all=True))

        menu.addSeparator()
        act_gaps = menu.addAction("🔍 ស្កេន និងបំពេញចន្លោះ Timeline (Fill Gaps)" if kh else "🔍 Scan & Fill Timeline Gaps")
        act_gaps.triggered.connect(lambda: self._run_fill_timeline_gaps())

        menu.exec(self.btn_translate.mapToGlobal(pos))

    def _show_dub_context_menu(self, pos):
        if not self.project_id:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #161920; color: #F4F6FB; border: 1px solid #343B4C; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 14px; border-radius: 4px; font-size: 11px; }
            QMenu::item:selected { background: #202530; color: #00E5FF; }
        """)
        kh = self.lang == "kh"
        act_missing = menu.addAction("🎙️ បង្កើតតែសំឡេងដែលខ្វះ (Dub Missing Audio)" if kh else "🎙️ Dub Missing Audio")
        act_missing.triggered.connect(lambda: self._run_dub_voice(force_all=False))

        act_all = menu.addAction("🔄 បង្កើតសំឡេងឡើងវិញទាំងអស់ (Redub All Lines)" if kh else "🔄 Redub All Lines")
        act_all.triggered.connect(lambda: self._run_dub_voice(force_all=True))

        menu.exec(self.btn_dub.mapToGlobal(pos))

    def _show_dub_missing_menu(self):
        """Called when clicking '🎙️ Dub Missing' on timeline toolbar"""
        if not self.project_id:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #161920; color: #F4F6FB; border: 1px solid #343B4C; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 14px; border-radius: 4px; font-size: 11px; }
            QMenu::item:selected { background: #202530; color: #00E5FF; }
        """)
        kh = self.lang == "kh"
        act_missing = menu.addAction("🎙️ បង្កើតតែសំឡេងដែលខ្វះ (Dub Missing)" if kh else "🎙️ Dub Missing Audio")
        act_missing.triggered.connect(lambda: self._run_dub_voice(force_all=False))

        act_all = menu.addAction("🔄 បង្កើតសំឡេងឡើងវិញទាំងអស់ (Redub All)" if kh else "🔄 Redub All Audio")
        act_all.triggered.connect(lambda: self._run_dub_voice(force_all=True))

        menu.addSeparator()
        act_gaps = menu.addAction("🔍 ស្កេន និងបំពេញចន្លោះ Timeline (Fill Gaps)" if kh else "🔍 Scan & Fill Timeline Gaps")
        act_gaps.triggered.connect(lambda: self._run_fill_timeline_gaps())

        btn = getattr(self.timeline_tracks, "btn_dub_missing", None)
        if btn:
            menu.exec(btn.mapToGlobal(QPoint(0, btn.height())))
        else:
            menu.exec(QCursor.pos())

    def _detect_timeline_gaps(self, min_gap_ms: int = 1800) -> list:
        """រកមើលចន្លោះទំនេរលើ Timeline ដែលគ្មាន Subtitle / Dub Audio"""
        if not self.project_id:
            return []
        segs = self.db.get_segments(self.project_id)
        if not segs:
            return []
        segs = sorted(segs, key=lambda s: int(s.get("start_ms", 0)))
        total_dur_ms = 0
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
            total_dur_ms = self.video_editor.player.duration()
        if not total_dur_ms and self.video_path and Path(self.video_path).exists():
            from core.media_engine import MediaEngine
            total_dur_ms = MediaEngine.get_duration_ms(self.video_path)
        if not total_dur_ms and segs:
            total_dur_ms = segs[-1]["end_ms"] + 5000

        gaps = []
        # 1. Lead gap (ពី 0ms ដល់ជួរទីមួយ)
        if segs[0]["start_ms"] >= min_gap_ms:
            gaps.append((0, segs[0]["start_ms"]))

        # 2. Inter-segment gaps (ចន្លោះរវាងជួរនីមួយៗ)
        for i in range(len(segs) - 1):
            cur_end = int(segs[i]["end_ms"])
            next_start = int(segs[i + 1]["start_ms"])
            if (next_start - cur_end) >= min_gap_ms:
                gaps.append((cur_end, next_start))

        # 3. Trailing gap (ពីជួរចុងក្រោយ ដល់ចប់វីដេអូ)
        if total_dur_ms - segs[-1]["end_ms"] >= min_gap_ms:
            gaps.append((segs[-1]["end_ms"], total_dur_ms))

        return gaps

    def _run_fill_timeline_gaps(self, target_gap: tuple = None):
        """
        ស្កេន និងបកប្រែចន្លោះទំនេរលើ Timeline (Fill Missing Gaps)
        target_gap=(start_ms, end_ms) បើចង់ស្កេនតែចន្លោះជាក់លាក់មួយ ឬ None បើស្កេនគ្រប់ចន្លោះ >= 1.8s
        """
        if not self.project_id or not self.video_path or not Path(self.video_path).exists():
            QMessageBox.information(self, "Ai Summarai", "សូមបើកវីដេអូជាមុនសិន!")
            return

        existing_segs = self.db.get_segments(self.project_id)
        has_untranslated = any(
            (s.get("zh_text") or "").strip() and not re.search(r"[\u1780-\u17ff]", s.get("kh_text") or "")
            for s in existing_segs
        )
        has_unvoiced = any(
            s.get("status") != "Voiced" and (s.get("kh_text") or "").strip()
            for s in existing_segs
        )

        if target_gap is not None:
            gaps = [target_gap]
        else:
            gaps = self._detect_timeline_gaps(min_gap_ms=800)

        if not gaps and not has_untranslated and not has_unvoiced:
            QMessageBox.information(
                self,
                "Ai Summarai",
                "គ្មានចន្លោះទំនេរណាលើសពី 0.8 វិនាទីលើ Timeline ទេ!\n(គ្រប់វិនាទីទាំងអស់សុទ្ធតែមាន Subtitle/Dub រួចរាល់)",
            )
            return

        work_dir = Path(f"data/workspace/proj_{self.project_id}")
        work_dir.mkdir(parents=True, exist_ok=True)
        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "gemini-2.5-flash")
        voice_label = self.db.get_setting("kh_voice_label", "Female (Sreymom)")
        default_voice = DEFAULT_VOICES.get(voice_label, "km-KH-SreymomNeural")

        def task(emit):
            try:
                import subprocess
                from core.transcriber import SpeechTranscriber
                from core.translator import ZHtoKHTranslator
                from core.tts_engine import KhmerTTSEngine
                from core.media_engine import MediaEngine

                asr = SpeechTranscriber()
                translator = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=self.db.get_glossary())
                tts = KhmerTTSEngine()
                clip_dir = work_dir / "tts"
                clip_dir.mkdir(parents=True, exist_ok=True)

                total_gaps = len(gaps)
                total_added_segs = 0

                # ក. បកប្រែបំពេញជួរដែលមានស្រាប់តែមិនទាន់បកប្រែ (Fill Untranslated Existing Lines)
                untrans = [
                    s for s in self.db.get_segments(self.project_id)
                    if (s.get("zh_text") or "").strip() and not re.search(r"[\u1780-\u17ff]", s.get("kh_text") or "")
                ]
                if untrans:
                    emit(5, f"កំពុងបកប្រែបំពេញ {len(untrans)} ជួរដែលមិនទាន់បកប្រែ...")
                    from core.translator import strip_chinese_from_khmer
                    untrans_res = translator.translate_segments(untrans, stop_event=self._cancel_event)
                    for s in untrans:
                        sid = s.get("id")
                        if not sid:
                            continue
                        raw_k = untrans_res.get(sid, "") or untrans_res.get(s.get("start_ms"), "")
                        clean_k = strip_chinese_from_khmer(raw_k) if raw_k else ""
                        if clean_k and re.search(r"[\u1780-\u17ff]", clean_k):
                            self.db.update_segment(sid, kh_text=clean_k, status="Ready")
                            total_added_segs += 1

                # ខ. ស្កេន និងកាត់សំឡេងចន្លោះទំនេរលើ Timeline (Scan Audio Gaps)
                for g_idx, (g_start, g_end) in enumerate(gaps):
                    if self._cancel_event.is_set():
                        return "⏹ បានផ្អាកការបំពេញចន្លោះ!"

                    dur_ms = g_end - g_start
                    if dur_ms < 600:
                        continue

                    emit(int((g_idx / max(1, total_gaps)) * 75) + 10, f"កំពុងស្កេនចន្លោះ {g_idx+1}/{total_gaps} ({g_start//1000}s - {g_end//1000}s)...")

                    gap_wav = work_dir / f"_gap_{g_start}_{g_end}.wav"
                    cmd = [
                        "ffmpeg", "-y",
                        "-ss", f"{g_start / 1000.0:.3f}",
                        "-t", f"{dur_ms / 1000.0:.3f}",
                        "-i", str(self.video_path),
                        "-vn", "-acodec", "pcm_s16le",
                        "-ar", "16000", "-ac", "1",
                        str(gap_wav)
                    ]
                    try:
                        MediaEngine.run_ffmpeg_safe(cmd, fallback_cpu=False, cancel_event=self._cancel_event)
                    except Exception as ex:
                        print(f"[Gap Slice Error] {ex}")
                        continue

                    if not gap_wav.exists() or gap_wav.stat().st_size <= 1000:
                        continue

                    try:
                        raw_items = asr.transcribe_local(str(gap_wav), model_size="base")
                    except Exception as asr_err:
                        print(f"[Gap Transcribe Error] {asr_err}")
                        raw_items = []

                    try:
                        gap_wav.unlink(missing_ok=True)
                    except Exception:
                        pass

                    if not raw_items:
                        continue

                    adjusted_items = []
                    for it_idx, it in enumerate(raw_items):
                        abs_s = g_start + it.get("start_ms", 0)
                        abs_e = min(g_end, g_start + it.get("end_ms", 0))
                        if abs_e - abs_s >= 350:
                            seg_id = abs_s
                            adjusted_items.append({
                                "id": seg_id,
                                "start_ms": abs_s,
                                "end_ms": abs_e,
                                "zh_text": it.get("zh_text", ""),
                                "voice_override": it.get("voice_override", ""),
                                "status": "Ready",
                            })

                    if not adjusted_items:
                        continue

                    emit(int((g_idx / max(1, total_gaps)) * 75) + 15, f"កំពុងបកប្រែ {len(adjusted_items)} ជួរក្នុងចន្លោះនេះ...")
                    from core.translator import strip_chinese_from_khmer
                    translated_map = translator.translate_segments(adjusted_items, stop_event=self._cancel_event)
                    for it in adjusted_items:
                        sid = it.get("id") or it.get("start_ms")
                        raw_k = (
                            translated_map.get(sid, "")
                            or translated_map.get(it.get("start_ms"), "")
                            or it.get("kh_text", "")
                        )
                        it["kh_text"] = strip_chinese_from_khmer(raw_k)

                    self.db.append_segments(self.project_id, adjusted_items)
                    self.db.fix_all_overlaps(self.project_id)
                    total_added_segs += len(adjusted_items)

                # គ. បង្កើតសំឡេងខ្មែរ (TTS) សម្រាប់គ្រប់ជួរដែលនៅខ្វះសំឡេង (Unvoiced Segments)
                latest_segs = self.db.get_segments(self.project_id)
                unvoiced_segs = [
                    s for s in latest_segs
                    if s.get("status") != "Voiced" and (s.get("kh_text") or "").strip()
                ]
                if unvoiced_segs or total_added_segs > 0:
                    emit(85, f"កំពុងបង្កើតសំឡេងខ្មែរសម្រាប់ {len(unvoiced_segs)} ជួរដែលនៅខ្វះ...")
                    from core.translator import strip_chinese_from_khmer
                    for s in unvoiced_segs:
                        sid = s.get("id") or s.get("start_ms")
                        if not sid:
                            continue
                        clean_kh = strip_chinese_from_khmer(s.get("kh_text") or "")
                        if clean_kh:
                            cpath = str(clip_dir / f"seg_{sid}.wav")
                            d_ms = max(400, s.get("end_ms", 0) - s.get("start_ms", 0) + 300)
                            voice = s.get("voice_override") or default_voice
                            try:
                                tts.generate_clip(clean_kh, voice, d_ms, cpath, db=self.db, speed_mult=getattr(self, "tts_speed_mult", 1.0))
                                self.db.update_segment(sid, kh_text=clean_kh, tts_audio_path=cpath, status="Voiced")
                            except Exception as e:
                                print(f"[TTS Error in Gap] {e}")

                    emit(94, "កំពុងអាប់ដេតសំឡេងក្នុង Video Preview...")
                    try:
                        tmp_mp4 = str(Path(f"data/workspace/proj_{self.project_id}") / "_tmp_preview.mp4")
                        MediaEngine.build_fast_preview_video(
                            self.video_path,
                            self.db.get_segments(self.project_id),
                            tmp_mp4,
                            bgm_volume=0.0,
                            voice_gain=2.2,
                            edits=self.db.get_project_edits(self.project_id),
                            sfx_events=self.db.get_sfx_events(self.project_id),
                        )
                    except Exception as pe:
                        print(f"[Preview Error] {pe}")

                    return f"ជោគជ័យ! បានស្កេន បកប្រែ និងបញ្ចូលសំឡេង {total_added_segs} ជួរក្នុងចន្លោះ Timeline!"
                else:
                    return "ពុំឃើញមានពាក្យនិយាយក្នុងចន្លោះដែលបានស្កេនទេ (អាចជាភ្លេង ឬសំឡេងស្ងាត់)។ អ្នកអាច Right-Click លើចន្លោះនោះដើម្បីបន្ថែមជួរនិយាយដោយដៃបាន!"
            except Exception as ex:
                import traceback
                traceback.print_exc()
                return f"⚠️ ដំណើរការបំពេញចន្លោះបានរក្សាទុកទិន្នន័យ (Notice): {ex}"

        def on_done():
            self._refresh_table()
            segs = self.db.get_segments(self.project_id)
            if hasattr(self, "video_editor"):
                self.video_editor.set_segments(segs)
            total_ms = self.video_editor.player.duration() or 60000
            if segs:
                total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
            self.timeline_tracks.set_data(total_ms, segs)
            self._apply_tmp_preview_to_player()
            self._update_button_states()

        self._run_worker(task, on_done)

    def _add_line_at_gap(self, start_ms: int, end_ms: int):
        """បន្ថែមជួរនិយាយថ្មីលើចន្លោះ Timeline ជាក់លាក់មួយ"""
        if not self.project_id:
            return
        dur_s = (end_ms - start_ms) / 1000.0
        text, ok = QInputDialog.getText(
            self,
            "បន្ថែមជួរនិយាយថ្មីលើ Timeline",
            f"ចន្លោះម៉ោង: {start_ms//1000}s ដល់ {end_ms//1000}s ({dur_s:.1f}s)\nសូមវាយអត្ថបទខ្មែរ (ឬចិន):",
            text="",
        )
        if ok and text.strip():
            clean_t = text.strip()
            is_khmer = bool(re.search(r"[\u1780-\u17ff]", clean_t))
            zh_text = "" if is_khmer else clean_t
            kh_text = clean_t if is_khmer else ""
            seg_id = self.db.add_single_segment(
                self.project_id,
                start_ms=start_ms,
                end_ms=end_ms,
                zh_text=zh_text,
                kh_text=kh_text,
                status="Ready" if kh_text else "Pending",
            )
            self.db.fix_all_overlaps(self.project_id)
            self._refresh_table()
            segs = self.db.get_segments(self.project_id)
            total_ms = self.video_editor.player.duration() or 60000
            if segs:
                total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
            self.timeline_tracks.set_data(total_ms, segs)
            if hasattr(self, "video_editor"):
                self.video_editor.set_segments(segs)

            if kh_text:
                self._run_dub_voice(force_all=False, target_segment_ids=[seg_id])
            elif zh_text:
                self._run_translate(force_all=False, target_segment_ids=[seg_id])

    def _on_timeline_gap_action(self, action: str, start_ms: int, end_ms: int):
        """ទទួល Action ពី Right-Click លើចន្លោះទំនេរនៃ Timeline"""
        if action == "scan":
            self._run_fill_timeline_gaps(target_gap=(start_ms, end_ms))
        elif action == "add":
            self._add_line_at_gap(start_ms, end_ms)

    def _on_timeline_segment_action(self, action: str, target_idx: int):
        """ទទួល Action ពី Right-Click លើ Segment Block នៃ Timeline"""
        segs = self.db.get_segments(self.project_id)
        if 0 <= target_idx < len(segs):
            seg = segs[target_idx]
            sid = seg["id"]
            if action == "redub":
                self._run_dub_voice(force_all=True, target_segment_ids=[sid])
            elif action == "retranslate":
                self._run_translate(force_all=True, target_segment_ids=[sid])
            elif action == "split":
                self._split_row_at_playhead(sid)
            elif action == "delete":
                self._delete_single_segment(sid)

    def _delete_single_segment(self, seg_id: int):
        """លុប Segment មួយជាក់លាក់ចេញពីគម្រោង"""
        self.db.delete_segments([seg_id])
        self._refresh_table()
        segs = self.db.get_segments(self.project_id)
        total_ms = self.video_editor.player.duration() or 60000
        if segs:
            total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
        self.timeline_tracks.set_data(total_ms, segs)
        self.status_lbl.setText(f"🗑️ បានលុបជួរ ID #{seg_id} រួចរាល់!")

    def _on_bgm_changed(self, value: int):
        self.lbl_bgm_val.setText(f"{value}%")
        self.db.set_setting("bgm_volume_pct", str(value))
        # ប្តូរកម្រិតសំឡេងដើមលើ Video Preview ភ្លាមៗ (0% = ស្ងាត់សំឡេងចិនដើមទាំងស្រុង!)
        if hasattr(self, "video_editor"):
            self.video_editor.set_original_volume(value)

    # =========================================================================
    # FEATURE 1: SERIES PROFILE & CHARACTER VOICE MEMORY
    # =========================================================================
    def _reload_series_profiles_combo(self):
        if not hasattr(self, "combo_series_profile"):
            return
        self.combo_series_profile.blockSignals(True)
        self.combo_series_profile.clear()
        self.combo_series_profile.addItem("📚 Series Profile (សំណុំរឿងភាគ)", 0)
        try:
            for p in self.db.list_series_profiles():
                self.combo_series_profile.addItem(f"📚 {p['series_name']}", int(p["id"]))
        except Exception:
            pass
        cur_id = int(getattr(self, "active_series_profile_id", 0) or 0)
        idx = self.combo_series_profile.findData(cur_id)
        self.combo_series_profile.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_series_profile.blockSignals(False)

    def _apply_series_voice_memory_to_segments(self, project_id: int, voice_map: dict) -> int:
        """Applies remembered Series Profile character voice overrides & speed settings to matching segments."""
        if not project_id or not isinstance(voice_map, dict):
            return 0
        def_label = voice_map.get("default_voice_label")
        if def_label:
            self.db.set_setting("kh_voice_label", str(def_label))
        if voice_map.get("tts_speed_mult"):
            try:
                spd = float(voice_map["tts_speed_mult"])
                self.tts_speed_mult = spd
                if hasattr(self, "combo_tts_speed"):
                    self.combo_tts_speed.blockSignals(True)
                    for i in range(self.combo_tts_speed.count()):
                        if abs(float(self.combo_tts_speed.itemData(i) or 1.0) - spd) < 0.02:
                            self.combo_tts_speed.setCurrentIndex(i)
                            break
                    self.combo_tts_speed.blockSignals(False)
            except Exception:
                pass

        speaker_voices = voice_map.get("speaker_voices") or {}
        if not speaker_voices:
            return 0

        segs = self.db.get_segments(project_id)
        applied = 0
        # Sort longest character name/cue first to avoid partial match collisions
        sorted_cues = sorted(
            [(str(k).strip(), str(v).strip()) for k, v in speaker_voices.items() if str(k).strip() and str(v).strip()],
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        for seg in segs:
            if (seg.get("voice_override") or "").strip():
                continue
            hay = f"{seg.get('zh_text') or ''} {seg.get('kh_text') or ''}"
            for cue, v_code in sorted_cues:
                if cue in hay:
                    self.db.update_segment(seg["id"], voice_override=v_code)
                    applied += 1
                    break
        return applied

    def _apply_series_profile_to_current_project(self, profile_id: int, quiet: bool = False):
        prof = self.db.get_series_profile(profile_id)
        if not prof:
            return

        # 1. Merge series glossary terms into DB
        g_list = prof.get("glossary") or []
        if g_list:
            tuples = [
                (
                    str(g.get("src_term") or g.get("zh_term") or "").strip(),
                    str(g.get("kh_term") or "").strip(),
                    str(g.get("category") or "series").strip(),
                )
                for g in g_list
                if (g.get("src_term") or g.get("zh_term")) and g.get("kh_term")
            ]
            if tuples:
                self.db.bulk_upsert_glossary(tuples)

        # 2. Apply default voice map & character voice memory
        v_map = prof.get("default_voice_map") or {}
        voiced_applied = 0
        if self.project_id:
            voiced_applied = self._apply_series_voice_memory_to_segments(self.project_id, v_map)

        # 3. Apply edits layout + Intro/Outro clips
        edits_preset = dict(prof.get("edits_preset") or {})
        edits_preset["series_profile_id"] = int(profile_id)
        intro_p = str(prof.get("intro_path") or "").strip()
        outro_p = str(prof.get("outro_path") or "").strip()
        if intro_p:
            edits_preset["intro_path"] = intro_p
            edits_preset.setdefault("intro_enabled", 1 if Path(intro_p).exists() else 0)
        if outro_p:
            edits_preset["outro_path"] = outro_p
            edits_preset.setdefault("outro_enabled", 1 if Path(outro_p).exists() else 0)

        if self.project_id:
            self.db.update_project_edits(self.project_id, edits_dict=edits_preset)
            merged_edits = self.db.get_project_edits(self.project_id)
            if hasattr(self, "video_editor"):
                self.video_editor.edits = dict(merged_edits)
                self.video_editor._load_edits_into_controls()
            if hasattr(self, "btn_keep_bgm_only"):
                self.btn_keep_bgm_only.blockSignals(True)
                self.btn_keep_bgm_only.setChecked(bool(merged_edits.get("keep_bgm_only", 0)))
                self.btn_keep_bgm_only.blockSignals(False)
            if hasattr(self, "btn_bottom_blur"):
                self.btn_bottom_blur.setChecked(bool(merged_edits.get("mask_enabled", 0) or merged_edits.get("auto_blur_chinese", 0)))
            if not quiet:
                self._refresh_table()

        if not quiet and hasattr(self, "status_lbl"):
            self.status_lbl.setText(
                f"📚 បានផ្ទុកសំណុំរឿងភាគ '{prof['series_name']}' (Glossary {len(g_list)} ពាក្យ, Voice Memory {voiced_applied} ជួរ)!"
            )

    def _on_series_profile_selected(self, idx: int):
        if idx < 0 or not hasattr(self, "combo_series_profile"):
            return
        pid = int(self.combo_series_profile.currentData() or 0)
        self.active_series_profile_id = pid
        self.db.set_setting("active_series_profile_id", str(pid))
        if pid > 0:
            self._apply_series_profile_to_current_project(pid, quiet=False)
        elif self.project_id:
            self.db.update_project_edits(self.project_id, series_profile_id=0)
            self.status_lbl.setText("📚 បានបិទការប្រើសំណុំរឿងភាគ (Series Profile: None)")

    def _on_save_series_profile(self):
        cur_name = ""
        if getattr(self, "active_series_profile_id", 0) > 0:
            cur_p = self.db.get_series_profile(self.active_series_profile_id)
            if cur_p:
                cur_name = cur_p["series_name"]
        elif self.video_path:
            cur_name = re.sub(r"[\s_\-]*(ep|episode|part|ភាគ|第)[\s_\-]*\d+.*$", "", Path(self.video_path).stem, flags=re.IGNORECASE).strip()

        name, ok = QInputDialog.getText(
            self,
            "📚 Save Series Profile (រក្សាទុកសំណុំរឿងភាគ)",
            "បញ្ចូលឈ្មោះរឿងភាគ (សម្រាប់ផ្ទុកសំឡេងតួអង្គ, Glossary, Style & Intro/Outro គ្រប់ភាគ ១-៥០):",
            text=cur_name,
        )
        if not ok or not name.strip():
            return
        series_name = name.strip()

        # Sync live UI edits first
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor._sync_ui_to_edits()
            if self.project_id:
                self._on_edits_changed(dict(self.video_editor.edits))

        edits = self.db.get_project_edits(self.project_id) if self.project_id else dict(getattr(self.video_editor, "edits", {}) or {})
        segs = self.db.get_segments(self.project_id) if self.project_id else []

        # Build character voice memory from glossary names + explicit voice overrides
        all_glossary = self.db.get_glossary()
        project_corpus = " ".join(f"{s.get('zh_text') or ''} {s.get('kh_text') or ''}" for s in segs)
        series_glossary = []
        speaker_voices = {}
        for g in all_glossary:
            src = (g.get("src_term") or "").strip()
            kh = (g.get("kh_term") or "").strip()
            cat = (g.get("category") or "general").strip()
            in_proj = bool(src and (src in project_corpus or (kh and kh in project_corpus)))
            if cat in ("series", "custom", "character", "names") or in_proj:
                series_glossary.append({"src_term": src, "kh_term": kh, "category": cat})
                if in_proj and segs:
                    for s in segs:
                        v_ov = (s.get("voice_override") or "").strip()
                        if v_ov and (src in (s.get("zh_text") or "") or (kh and kh in (s.get("kh_text") or ""))):
                            speaker_voices[src] = v_ov
                            if kh:
                                speaker_voices[kh] = v_ov
                            break

        # Also capture explicit speaker prefix patterns like "王总：" or "ឈ្មោះ："
        for s in segs:
            v_ov = (s.get("voice_override") or "").strip()
            if not v_ov:
                continue
            zh = (s.get("zh_text") or "").strip()
            m_sp = re.match(r"^([\u4e00-\u9fff]{2,5})\s*[:：]", zh)
            if m_sp:
                speaker_voices[m_sp.group(1)] = v_ov

        voice_map = {
            "default_voice_label": self.db.get_setting("kh_voice_label", "Female (Sreymom)"),
            "tts_speed_mult": float(getattr(self, "tts_speed_mult", 1.0)),
            "speaker_voices": speaker_voices,
        }

        preset_keys = [
            "logo_path", "logo_x", "logo_y", "logo_scale", "logo_opacity",
            "burn_subs", "sub_style", "sub_font_family", "sub_y", "sub_font_size", "sub_color", "sub_bg",
            "brightness", "contrast", "saturation", "lut_preset", "aspect_ratio",
            "mask_enabled", "mask_mode", "mask_x", "mask_y", "mask_w", "mask_h", "mask_strength", "mask_color",
            "masks_json", "auto_blur_chinese", "auto_timed_blur",
            "anti_copyright_enabled", "anti_copyright_level", "anti_copyright_flip", "anti_copyright_border",
            "custom_bgm_path", "custom_bgm_vol", "auto_ducking", "dub_volume", "keep_bgm_only",
            "hook_enabled", "hook_pos", "hook_bg_color", "hook_text_color", "hook_height_pct", "hook_font_size",
            "intro_enabled", "outro_enabled", "hd_upscale_enabled", "hd_upscale_1080p",
        ]
        edits_preset = {k: edits.get(k) for k in preset_keys if k in edits}
        intro_path = str(edits.get("intro_path") or "").strip()
        outro_path = str(edits.get("outro_path") or "").strip()

        try:
            pid = self.db.save_series_profile(
                series_name=series_name,
                default_voice_map=voice_map,
                glossary=series_glossary[:300],
                edits_preset=edits_preset,
                intro_path=intro_path,
                outro_path=outro_path,
            )
            self.active_series_profile_id = pid
            self.db.set_setting("active_series_profile_id", str(pid))
            if self.project_id:
                self.db.update_project_edits(self.project_id, series_profile_id=pid)
            self._reload_series_profiles_combo()
            self.status_lbl.setText(
                f"📚 បានរក្សាទុកសំណុំរឿងភាគ '{series_name}' រួចរាល់ (Voices: {len(speaker_voices)}, Glossary: {len(series_glossary)})!"
            )
        except Exception as e:
            QMessageBox.critical(self, "Series Profile Error", f"មិនអាចរក្សាទុកសំណុំរឿងភាគបានទេ:\n{e}")

    def _on_delete_series_profile(self):
        pid = int(self.combo_series_profile.currentData() or 0) if hasattr(self, "combo_series_profile") else 0
        if pid <= 0:
            QMessageBox.information(self, "Series Profile", "សូមជ្រើសរើសសំណុំរឿងភាគដែលចង់លុបជាមុនសិន!")
            return
        prof = self.db.get_series_profile(pid)
        pname = prof["series_name"] if prof else f"#{pid}"
        ret = QMessageBox.question(
            self,
            "Delete Series Profile",
            f"តើអ្នកពិតជាចង់លុបសំណុំរឿងភាគ '{pname}' មែនទេ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self.db.delete_series_profile(pid)
            self.active_series_profile_id = 0
            self.db.set_setting("active_series_profile_id", "0")
            self._reload_series_profiles_combo()
            self.status_lbl.setText(f"🗑 បានលុបសំណុំរឿងភាគ '{pname}' រួចរាល់!")

    # =========================================================================
    # FEATURE 2: AI VOCAL REMOVER & KEEP BGM ONLY TOGGLE
    # =========================================================================
    def _on_toggle_keep_bgm_only(self, checked: bool):
        val = 1 if checked else 0
        if checked and self.bgm_slider.value() < 10:
            self.bgm_slider.blockSignals(True)
            self.bgm_slider.setValue(35)
            self.lbl_bgm_val.setText("35%")
            self.db.set_setting("bgm_volume_pct", "35")
            self.bgm_slider.blockSignals(False)

        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor.edits["keep_bgm_only"] = val
            self.video_editor.edits["mute_original_audio"] = 0 if checked else (1 if self.bgm_slider.value() <= 0 else 0)
        if self.project_id:
            self.db.update_project_edits(
                self.project_id,
                keep_bgm_only=val,
                mute_original_audio=0 if checked else (1 if self.bgm_slider.value() <= 0 else 0),
            )
            self._rebuild_smooth_preview()
        self.status_lbl.setText(
            "🎼 បើក AI Vocal Remover (Keep BGM Only) — បំបាត់សំឡេងនិយាយចិន រក្សាទុកតែភ្លេងដើម!"
            if checked else "🔇 បានបិទ Keep BGM Only!"
        )

    # =========================================================================
    # FEATURE 3: ASYNC AI VIRAL HOOK BANNER TITLE GENERATOR
    # =========================================================================
    def _run_generate_viral_hook(self):
        if not self.project_id:
            QMessageBox.warning(self, "AI Hook Banner", "សូមបើកវីដេអូ និងស្កេន/បកប្រែអត្ថបទជាមុនសិន!")
            return
        segs = self.db.get_segments(self.project_id)
        if not segs:
            QMessageBox.warning(self, "AI Hook Banner", "មិនទាន់មានអត្ថបទក្នុងគម្រោងទេ! សូមចុច 'Scan ZH' និង 'Translate KH' ជាមុនសិន។")
            return
        if hasattr(self, "_hook_worker") and self._hook_worker and self._hook_worker.isRunning():
            return

        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "gemini-3.1-flash-lite")
        glossary = self.db.get_glossary()
        ep_title = Path(self.video_path).stem if self.video_path else ""

        self.video_editor.set_hook_generating(True)
        self.status_lbl.setText("✨ AI កំពុងសង្ខេបសាច់រឿងបង្កើត Viral Hook Banner Title...")

        def _task(_emit):
            from core.translator import ZHtoKHTranslator
            tr_engine = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=glossary)
            return tr_engine.generate_viral_hook(segs, episode_title=ep_title)

        def _on_ok(hook_str: str):
            self.video_editor.set_hook_generating(False)
            if hook_str:
                self.video_editor.set_generated_hook_text(hook_str)
                self.status_lbl.setText(f"✨ បានបង្កើត Viral Hook Title: {hook_str}")

        def _on_err(err_msg: str):
            self.video_editor.set_hook_generating(False)
            self.status_lbl.setText(f"⚠️ មិនអាចបង្កើត Hook Title: {err_msg}")

        self._hook_worker = PipelineWorker(_task)
        self._hook_worker.finished_ok.connect(_on_ok)
        self._hook_worker.failed.connect(_on_err)
        self._hook_worker.start()

    # =========================================================================
    # FEATURE 5: 1-CLICK FULL-AUTO HANDS-FREE PIPELINE (STEP 1/5 -> STEP 5/5)
    # =========================================================================
    def _run_one_click_auto_pipeline(self):
        """
        Hands-free chained 5-stage pipeline:
        [Step 1/5] Scan ZH -> [Step 2/5] Clean Noise -> [Step 3/5] Translate KH ->
        [Step 4/5] Generate Voice -> [Step 5/5] Render & Export final .mp4 automatically.
        """
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Ai Summarai", "កំពុងដំណើរការកិច្ចការមួយផ្សេងទៀត! សូមរង់ចាំ ឬចុច 'Stop' ជាមុនសិន។")
            return

        batch_files = []
        if not self.video_path or not Path(self.video_path).exists():
            picked, _ = QFileDialog.getOpenFileNames(
                self,
                "🚀 ជ្រើសរើសវីដេអូ ១ ឬច្រើនភាគសម្រាប់ 1-Click Auto Dub & Export",
                "",
                "Videos (*.mp4 *.mkv *.mov *.avi *.flv)",
            )
            if not picked:
                return
            if len(picked) == 1:
                self._load_video(picked[0])
            else:
                batch_files = list(picked[:50])

        is_split_mode = bool(len(getattr(self, "_clip_markers", []) or []) > 1)
        out_target_file = ""
        out_target_dir = ""

        if batch_files or is_split_mode:
            out_target_dir = QFileDialog.getExistingDirectory(
                self,
                "📁 ជ្រើសរើសថតរក្សាទុកវីដេអូ Export ស្វ័យប្រវត្តិ (Output Folder)",
                str(Path.home() / "Videos"),
            )
            if not out_target_dir:
                return
        else:
            default_dir = Path.home() / "Videos"
            if not default_dir.exists():
                default_dir = Path(self.video_path).parent
            stem = "".join(c for c in Path(self.video_path).stem if c.isalnum() or c in ("-", "_", " ")).strip() or "video"
            out_target_file, _ = QFileDialog.getSaveFileName(
                self,
                "📁 ជ្រើសរើសទីតាំងរក្សាទុកវីដេអូ Export (.mp4)",
                str(default_dir / f"{stem}_KhmerDub_Auto.mp4"),
                "MP4 Video (*.mp4)",
            )
            if not out_target_file:
                return
            if not out_target_file.lower().endswith(".mp4"):
                out_target_file += ".mp4"

        # Release media player handles & sync live edits before background render
        self._release_preview_audio_lock()
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor._sync_ui_to_edits()
            if self.project_id:
                self._on_edits_changed(dict(self.video_editor.edits))

        extract_mode = "voice" if self.extract_mode.currentIndex() == 0 else "ocr"
        asr_mode = int(self.db.get_setting("asr_mode", "0"))
        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "gemini-2.5-flash")
        dub_style = self.combo_trans_style.currentData() if hasattr(self, "combo_trans_style") else "literal"
        crop_y = int(self.db.get_setting("ocr_y_pct", "72")) / 100.0
        crop_h = int(self.db.get_setting("ocr_h_pct", "28")) / 100.0
        voice_label = self.db.get_setting("kh_voice_label", "Female (Sreymom)")
        default_voice = DEFAULT_VOICES.get(voice_label, "km-KH-SreymomNeural")
        tts_speed_mult = float(getattr(self, "tts_speed_mult", 1.0))
        bgm_slider_vol = round(self.bgm_slider.value() / 100.0, 2)
        active_sp_id = int(getattr(self, "active_series_profile_id", 0) or 0)
        clip_markers = list(getattr(self, "_clip_markers", []) or [])
        result_holder = {"outputs": [], "last_proj_id": self.project_id, "last_video": self.video_path}

        def _process_single_project(emit, proj_id: int, vid_path: str, dest_mp4: str, ep_prefix: str = "", base_pct: int = 0, span_pct: int = 100):
            def _sub_emit(local_pct: int, text: str):
                g_pct = min(99, base_pct + int((max(0, min(100, local_pct)) / 100.0) * span_pct))
                emit(g_pct, f"{ep_prefix}{text}")

            work_dir = Path(f"data/workspace/proj_{proj_id}")
            work_dir.mkdir(parents=True, exist_ok=True)
            edits = self.db.get_project_edits(proj_id)

            # Apply Series Profile glossary/edits/voice memory if active
            prof = self.db.get_series_profile(active_sp_id) if active_sp_id > 0 else None
            if prof:
                g_list = prof.get("glossary") or []
                if g_list:
                    tuples = [
                        (str(g.get("src_term") or "").strip(), str(g.get("kh_term") or "").strip(), str(g.get("category") or "series"))
                        for g in g_list if g.get("src_term") and g.get("kh_term")
                    ]
                    if tuples:
                        self.db.bulk_upsert_glossary(tuples)
                ep_preset = dict(prof.get("edits_preset") or {})
                if prof.get("intro_path") and Path(prof["intro_path"]).exists():
                    ep_preset["intro_path"] = prof["intro_path"]
                    ep_preset.setdefault("intro_enabled", 1)
                if prof.get("outro_path") and Path(prof["outro_path"]).exists():
                    ep_preset["outro_path"] = prof["outro_path"]
                    ep_preset.setdefault("outro_enabled", 1)
                if ep_preset and batch_files:
                    self.db.update_project_edits(proj_id, edits_dict=ep_preset)
                    edits = self.db.get_project_edits(proj_id)

            # --- [Step 1/5] Scan Chinese Dialogue ---
            if self._cancel_event.is_set():
                raise InterruptedError("⏹ បានបញ្ឈប់នៅ Step 1/5។")
            existing = self.db.get_segments(proj_id)
            if not existing:
                _sub_emit(5, "[Step 1/5] កំពុងស្រង់សំឡេង / អត្ថបទចិន (Scan ZH)...")
                if extract_mode == "voice":
                    from core.transcriber import SpeechTranscriber
                    asr = SpeechTranscriber()
                    items = LongVideoStreamEngine.stream_voice_long_video(
                        video_path=vid_path,
                        work_dir=str(work_dir),
                        transcriber=asr,
                        mode="local" if asr_mode == 0 else "api",
                        api_cfg={"api_key": api_key, "base_url": api_url, "whisper_model": "base"},
                        progress_cb=lambda p, m: _sub_emit(5 + int(p * 0.20), f"[Step 1/5] {m}"),
                    )
                else:
                    from core.ocr_scanner import SubtitleOCRScanner
                    scanner = SubtitleOCRScanner()
                    items = LongVideoStreamEngine.stream_ocr_long_video(
                        video_path=vid_path,
                        work_dir=str(work_dir),
                        scanner=scanner,
                        fps=2,
                        crop_ratio=crop_h,
                        crop_y_offset=crop_y,
                        progress_cb=lambda p, m: _sub_emit(5 + int(p * 0.20), f"[Step 1/5] {m}"),
                    )
                self.db.insert_segments(proj_id, items)
            else:
                _sub_emit(20, f"[Step 1/5] មានអត្ថបទចិនស្រាប់ ({len(existing)} ជួរ) — បន្តទៅជំហានបន្ទាប់...")

            # --- [Step 2/5] Clean Noise & Fix Overlaps ---
            if self._cancel_event.is_set():
                raise InterruptedError("⏹ បានបញ្ឈប់នៅ Step 2/5។")
            _sub_emit(26, "[Step 2/5] កំពុងសម្អាតជួរសំរាម & Watermark (Clean Noise)...")
            removed = self.db.clean_noise_segments(proj_id)
            self.db.fix_all_overlaps(proj_id)
            if prof and prof.get("default_voice_map"):
                self._apply_series_voice_memory_to_segments(proj_id, prof["default_voice_map"])
            _sub_emit(30, f"[Step 2/5] សម្អាតរួចរាល់ (លុប {removed} ជួរសំរាម)...")

            # --- [Step 3/5] Translate to Natural Khmer ---
            if self._cancel_event.is_set():
                raise InterruptedError("⏹ បានបញ្ឈប់នៅ Step 3/5។")
            segs = self.db.get_segments(proj_id)
            pending_tr = [s for s in segs if (s.get("zh_text") or "").strip() and not re.search(r"[\u1780-\u17ff]", s.get("kh_text") or "")]
            if pending_tr:
                _sub_emit(32, f"[Step 3/5] កំពុងបកប្រែ ចិន → ខ្មែរធម្មជាតិ ({len(pending_tr)} ជួរ)...")
                from core.translator import ZHtoKHTranslator, strip_chinese_from_khmer
                translator = ZHtoKHTranslator(
                    api_key=api_key, base_url=api_url, model=model,
                    glossary=self.db.get_glossary(), dub_style=dub_style
                )

                def _save_chunk(chunk_map: dict):
                    for sid, kht in chunk_map.items():
                        ck = strip_chinese_from_khmer(kht) if kht else ""
                        if ck and re.search(r"[\u1780-\u17ff]", ck):
                            self.db.update_segment(sid, kh_text=ck, status="Ready", tts_audio_path="")

                res_tr = translator.translate_segments(
                    pending_tr,
                    progress_cb=lambda p: _sub_emit(32 + int(p * 0.22), f"[Step 3/5] បកប្រែខ្មែរ... {p}%"),
                    batch_done_cb=_save_chunk,
                    stop_event=self._cancel_event,
                )
                _save_chunk(res_tr)
            else:
                _sub_emit(54, "[Step 3/5] អត្ថបទខ្មែរត្រូវបានបកប្រែរួចរាល់!")

            # --- [Step 4/5] Synthesize All Khmer Voices ---
            if self._cancel_event.is_set():
                raise InterruptedError("⏹ បានបញ្ឈប់នៅ Step 4/5។")
            from core.tts_engine import KhmerTTSEngine
            from core.translator import normalize_dub_khmer_text
            tts = KhmerTTSEngine()
            clip_dir = work_dir / "tts"
            clip_dir.mkdir(parents=True, exist_ok=True)
            segs = self.db.get_segments(proj_id)
            total_s = max(1, len(segs))
            for idx_s, seg in enumerate(segs):
                if self._cancel_event.is_set():
                    raise InterruptedError("⏹ បានបញ្ឈប់នៅ Step 4/5 — ទិន្នន័យត្រូវបានរក្សាទុក។")
                clip_path = str(clip_dir / f"seg_{seg['id']}.wav")
                raw_dur = max(250, int(seg["end_ms"]) - int(seg["start_ms"]))
                if idx_s + 1 < len(segs):
                    max_slot = max(250, int(segs[idx_s + 1]["start_ms"]) - int(seg["start_ms"]) - 20)
                    dur_ms = min(raw_dur, max_slot)
                else:
                    dur_ms = raw_dur
                kh_text = normalize_dub_khmer_text(seg.get("kh_text") or "")
                existing_wav = seg.get("tts_audio_path") or ""
                needs_tts = (
                    seg.get("status") != "Voiced"
                    or not existing_wav
                    or not Path(existing_wav).exists()
                    or Path(existing_wav).stat().st_size <= 512
                )
                if needs_tts:
                    if not kh_text:
                        tts.generate_fallback_clip(dur_ms, clip_path)
                    else:
                        chosen_v = seg.get("voice_override") or default_voice
                        ok_tts = False
                        for att in range(3):
                            try:
                                tts.generate_clip(kh_text, chosen_v, dur_ms, clip_path, db=self.db, speed_mult=tts_speed_mult)
                                if Path(clip_path).exists() and Path(clip_path).stat().st_size > 512:
                                    ok_tts = True
                                    break
                            except Exception:
                                time.sleep(0.25 * (att + 1))
                        if not ok_tts:
                            tts.generate_fallback_clip(dur_ms, clip_path)
                    self.db.update_segment(seg["id"], tts_audio_path=clip_path, status="Voiced")
                _sub_emit(55 + int(((idx_s + 1) / total_s) * 23), f"[Step 4/5] បង្កើតសំឡេងខ្មែរ {idx_s + 1}/{total_s}...")

            # --- [Step 5/5] Render & Export Final .mp4 ---
            if self._cancel_event.is_set():
                raise InterruptedError("⏹ បានបញ្ឈប់នៅ Step 5/5។")
            segs = self.db.get_segments(proj_id)
            sfx_list = self.db.get_sfx_events(proj_id)
            edits = self.db.get_project_edits(proj_id)
            keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
            eff_bgm_vol = (max(0.20, bgm_slider_vol) if keep_bgm_only else 0.0)
            if not keep_bgm_only:
                edits["mute_original_audio"] = 1

            _sub_emit(80, "[Step 5/5] កំពុង Render និង Export វីដេអូសម្រេច (.mp4)...")
            if is_split_mode and not batch_files and out_target_dir:
                exported = MediaEngine.export_split_episodes(
                    video_path=vid_path,
                    segments=segs,
                    clip_markers=clip_markers,
                    output_dir=out_target_dir,
                    edits=edits,
                    bgm_volume=eff_bgm_vol,
                    sfx_events=sfx_list,
                    cancel_event=self._cancel_event,
                    progress_cb=lambda p, m: _sub_emit(80 + int(p * 0.19), f"[Step 5/5] {m}"),
                )
                result_holder["outputs"].extend(exported)
            else:
                MediaEngine.render_final_video(
                    video_path=vid_path,
                    segments=segs,
                    output_mp4=dest_mp4,
                    bgm_volume=eff_bgm_vol,
                    edits=edits,
                    sfx_events=sfx_list,
                    cancel_event=self._cancel_event,
                    progress_cb=lambda p, m: _sub_emit(80 + int(p * 0.19), f"[Step 5/5] {m}"),
                )
                result_holder["outputs"].append(dest_mp4)

        def task(emit):
            if batch_files:
                n_files = len(batch_files)
                span = max(1, int(100 / n_files))
                for idx_f, vf in enumerate(batch_files, start=1):
                    if self._cancel_event.is_set():
                        raise InterruptedError("⏹ បានបញ្ឈប់ដំណើរការ 1-Click Batch!")
                    pid = self.db.create_project(Path(vf).stem, vf, extract_mode)
                    result_holder["last_proj_id"] = pid
                    result_holder["last_video"] = vf
                    safe_stem = "".join(c for c in Path(vf).stem if c.isalnum() or c in ("-", "_", " ")).strip() or f"ep_{idx_f:02d}"
                    dest = str(Path(out_target_dir) / f"{idx_f:02d}_{safe_stem}_KhmerDub.mp4")
                    _process_single_project(
                        emit, pid, vf, dest,
                        ep_prefix=f"[EP {idx_f}/{n_files}] ",
                        base_pct=(idx_f - 1) * span,
                        span_pct=span,
                    )
            else:
                _process_single_project(emit, self.project_id, self.video_path, out_target_file, ep_prefix="", base_pct=0, span_pct=100)

            emit(100, "🎉 1-Click Auto Dub & Export បានបញ្ចប់ដោយជោគជ័យ ១០០%!")
            return f"🎉 1-Click Auto Dub & Export ជោគជ័យ ({len(result_holder['outputs'])} ឯកសារ)!"

        def on_auto_done():
            if batch_files and result_holder["last_proj_id"]:
                self.project_id = result_holder["last_proj_id"]
                self.video_path = result_holder["last_video"]
                self._set_short_filename(Path(self.video_path).name)
                self.stack.setCurrentIndex(1)
            self._refresh_table()
            segs = self.db.get_segments(self.project_id) if self.project_id else []
            dur = MediaEngine.get_duration_ms(self.video_path) if (self.video_path and Path(self.video_path).exists()) else 60000
            if segs:
                dur = max(dur, int(segs[-1].get("end_ms") or 0) + 1000)
            self.timeline_tracks.set_data(dur, segs, clip_markers=clip_markers)
            if hasattr(self, "video_editor"):
                self.video_editor.set_segments(segs)
            self._update_button_states()

            outs = result_holder["outputs"]
            if outs:
                first_out = outs[0]
                dest_label = out_target_dir if (batch_files or is_split_mode) else first_out
                reply = QMessageBox.information(
                    self,
                    "🚀 1-Click Auto Dub & Export Complete",
                    f"🎉 ដំណើរការស្វ័យប្រវត្តិទាំង ៥ ជំហានបានជោគជ័យ ({len(outs)} វីដេអូ)!\nទីតាំង៖ {dest_label}",
                    QMessageBox.Open | QMessageBox.Ok,
                )
                if reply == QMessageBox.Open:
                    import os
                    open_target = out_target_dir if (batch_files or is_split_mode) else str(Path(first_out).parent)
                    os.startfile(open_target)

        self._run_worker(task, on_auto_done)

    # =========================================================================
    # BATCH 2 FEATURE 1: AI VIRAL SHORTS CLIPPER (9:16 AUTO-CUT 10-20 CLIPS)
    # =========================================================================
    def _run_auto_cut_viral_shorts(self, video_path: str = "", max_clips: int = 12, min_sec: int = 45, max_sec: int = 90):
        target_vid = video_path or self.video_path
        if not target_vid or not Path(target_vid).exists():
            QMessageBox.warning(self, "Auto-Cut Viral Shorts", "សូមបើកវីដេអូរឿងវែងជាមុនសិន មុននឹងកាត់ឈុតខ្លីៗស្វ័យប្រវត្តិ!")
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Ai Summarai", "កំពុងដំណើរការកិច្ចការមួយផ្សេងទៀត! សូមរង់ចាំ ឬចុច Stop។")
            return

        out_dir = QFileDialog.getExistingDirectory(
            self,
            "⚡ ជ្រើសរើសថតរក្សាទុក Viral Shorts 9:16 (Short_01_HookTitle.mp4...)",
            str(Path.home() / "Videos"),
        )
        if not out_dir:
            return

        self._release_preview_audio_lock()
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor._sync_ui_to_edits()
            if self.project_id:
                self._on_edits_changed(dict(self.video_editor.edits))

        edits = self.db.get_project_edits(self.project_id) if self.project_id else {}
        segments = self.db.get_segments(self.project_id) if self.project_id else []
        sfx_events = self.db.get_sfx_events(self.project_id) if self.project_id else []
        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "gemini-3.1-flash-lite")
        glossary = self.db.get_glossary()
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        bgm_vol = round(max(0.20, self.bgm_slider.value() / 100.0), 2) if keep_bgm_only else 0.0
        holder = {"files": []}

        def task(emit):
            from core.translator import ZHtoKHTranslator
            tr_ai = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=glossary)
            files = LongVideoStreamEngine.cut_viral_shorts(
                video_path=target_vid,
                segments=segments,
                output_dir=out_dir,
                edits=edits,
                translator=tr_ai,
                max_clips=max_clips,
                min_sec=min_sec,
                max_sec=max_sec,
                bgm_volume=bgm_vol,
                sfx_events=sfx_events,
                cancel_event=self._cancel_event,
                progress_cb=emit,
            )
            holder["files"] = files
            return f"⚡ កាត់ឈុតខ្លីៗ Viral Shorts (9:16) បានជោគជ័យចំនួន {len(files)} ឈុត!"

        def on_done():
            files = holder["files"]
            reply = QMessageBox.information(
                self,
                "⚡ AI Viral Shorts Clipper Complete",
                f"🎉 បានកាត់ឈុតខ្លីៗ 9:16 ចំនួន {len(files)} ឈុត (TikTok / Reels Ready) ដោយជោគជ័យ!\nទីតាំង៖ {out_dir}",
                QMessageBox.Open | QMessageBox.Ok,
            )
            if reply == QMessageBox.Open:
                import os
                os.startfile(out_dir)

        self._run_worker(task, on_done)

    # =========================================================================
    # BATCH 2 FEATURE 2: AI EMOTION SFX & BGM AUTO-MATCHER
    # =========================================================================
    def _run_auto_place_emotion_sfx(self):
        if not self.project_id:
            QMessageBox.warning(self, "Auto-Place Emotion SFX", "សូមបើកវីដេអូ និងស្កេន/បកប្រែអត្ថបទជាមុនសិន!")
            return
        segs = self.db.get_segments(self.project_id)
        if not segs:
            QMessageBox.warning(self, "Auto-Place Emotion SFX", "មិនទាន់មានជួរអត្ថបទសម្រាប់វិភាគអារម្មណ៍ទេ!")
            return
        if self.worker and self.worker.isRunning():
            return

        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "gemini-3.1-flash-lite")
        glossary = self.db.get_glossary()
        holder = {"count": 0}

        def task(emit):
            from core.sfx_engine import SFXEngine
            from core.translator import ZHtoKHTranslator
            tr_ai = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=glossary)
            placed = SFXEngine.auto_match_emotion_sfx(
                segments=segs,
                db=self.db,
                project_id=self.project_id,
                translator=tr_ai,
                min_gap_ms=3500,
                replace_auto=True,
                progress_cb=emit,
            )
            holder["count"] = len(placed)
            return f"🎵 បានដាក់ Emotion SFX ស្វ័យប្រវត្តិចំនួន {len(placed)} ចំណុចលើ Timeline ជាមួយ Smart Ducking!"

        def on_done():
            sfx_all = self.db.get_sfx_events(self.project_id)
            self.timeline_tracks.set_sfx_events(sfx_all)
            if hasattr(self, "video_editor") and hasattr(self.video_editor, "chk_ducking"):
                self.video_editor.chk_ducking.setChecked(True)
            if holder["count"] > 0:
                self._rebuild_smooth_preview()

        self._run_worker(task, on_done)

    # =========================================================================
    # BATCH 2 FEATURE 5: SOCIAL MEDIA EXPORT BUNDLE & CAPTION PACK
    # =========================================================================
    def _run_export_social_pack(self):
        if not self.project_id:
            QMessageBox.warning(self, "Export Social Pack", "សូមបើកគម្រោង និងស្កេន/បកប្រែអត្ថបទជាមុនសិន!")
            return
        segs = self.db.get_segments(self.project_id)
        if not segs:
            QMessageBox.warning(self, "Export Social Pack", "មិនទាន់មានអត្ថបទសម្រាប់បង្កើត Social Pack ទេ!")
            return

        default_dir = Path(self.video_path).parent if (self.video_path and Path(self.video_path).exists()) else (Path.home() / "Videos")
        stem = Path(self.video_path).stem if self.video_path else f"project_{self.project_id}"
        clean_stem = "".join(c for c in stem if c.isalnum() or c in ("-", "_", " ")).strip() or "episode"
        chosen_txt, _ = QFileDialog.getSaveFileName(
            self,
            "📲 រក្សាទុក Social Media Export Pack (.txt + .json)",
            str(default_dir / f"{clean_stem}_SocialPack.txt"),
            "Text Files (*.txt)",
        )
        if not chosen_txt:
            return
        # Normalize base path so save_social_pack_files writes <base>_SocialPack.txt & .json
        base_out = re.sub(r"_SocialPack$", "", Path(chosen_txt).stem)
        base_path = str(Path(chosen_txt).parent / f"{base_out}.mp4")

        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        api_key = self.db.get_setting("api_key", "")
        model = self.db.get_setting("model", "gemini-3.1-flash-lite")
        glossary = self.db.get_glossary()
        holder = {"txt_path": "", "json_path": "", "preview": ""}

        def task(emit):
            emit(25, "📲 AI កំពុងរៀបចំ Social Pack (3 Viral Titles + 2-Sentence Recap + Hashtags)...")
            from core.translator import ZHtoKHTranslator
            tr_ai = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=glossary)
            pack = tr_ai.generate_social_pack(segs, video_name=clean_stem)
            txt_p, json_p = tr_ai.save_social_pack_files(pack, base_path)
            holder["txt_path"] = txt_p
            holder["json_path"] = json_p
            holder["preview"] = tr_ai.format_social_pack_txt(pack)
            emit(100, f"📲 រក្សាទុក Social Pack រួចរាល់: {Path(txt_p).name} & {Path(json_p).name}")
            return f"📲 បានរក្សាទុក Social Pack (.txt & .json) ទៅ {Path(txt_p).parent}!"

        def on_done():
            preview_body = (
                f"📁 Saved Files:\n• {holder['txt_path']}\n• {holder['json_path']}\n\n"
                + holder["preview"]
            )
            dlg = AICaptionDialog(preview_body, self.lang, self)
            dlg.setWindowTitle("📲 Social Media Export Pack (TikTok / Reels / Shorts)")
            dlg.exec()

        self._run_worker(task, on_done)

    def _run_export_video(self):
        """Step 5: Open Video Export Studio Dialog with live preview and 2K/1080p/720p resolution options."""
        if not self.project_id or not self.video_path or not Path(self.video_path).exists():
            QMessageBox.warning(self, "Ai Summarai", "សូមបើកវីដេអូជាមុនសិន!")
            return

        # 1. ផ្អាក video player ធំដើម្បីកុំឲ្យជាន់សំឡេងគ្នា
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
            self.video_editor.pause()

        # 2. ធ្វើសមកាលកម្ម Edits ផ្ទាល់ពី Video Preview Controls មុនពេល Export ដើម្បីធានាថា Mask / Logo / Subs ជាប់ជានិច្ច
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor._sync_ui_to_edits()
            live_edits = dict(self.video_editor.edits)
            self._on_edits_changed(live_edits)

        # 3. រកមើលឯកសារ preview video ដែលមានសំឡេងខ្មែរស្រាប់
        preview_path = ""
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
            src_url = self.video_editor.player.source()
            if src_url.isValid() and src_url.isLocalFile():
                candidate = src_url.toLocalFile()
                if Path(candidate).exists() and Path(candidate).stat().st_size > 1000:
                    preview_path = candidate

        if not preview_path or not Path(preview_path).exists():
            work_dir = Path(f"data/workspace/proj_{self.project_id}")
            tmp_p = work_dir / "_tmp_preview.mp4"
            if tmp_p.exists() and tmp_p.stat().st_size > 1000:
                preview_path = str(tmp_p)
            else:
                stream_files = sorted(work_dir.glob("preview_stream_*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
                if stream_files and stream_files[0].exists() and stream_files[0].stat().st_size > 1000:
                    preview_path = str(stream_files[0])
                else:
                    preview_path = self.video_path

        dlg = ExportVideoDialog(
            parent=self,
            project_id=self.project_id,
            video_path=self.video_path,
            preview_video_path=preview_path,
            db=self.db,
            lang=self.lang,
        )
        dlg.workflow_progress.connect(
            lambda p, m: self._workflow_dialog.on_stage_progress(p, m, "export")
            if getattr(self, "_workflow_dialog", None) else None
        )
        dlg.workflow_finished.connect(
            lambda m: (
                self._workflow_dialog.on_stage_finished(m, "export"),
                self._sync_workflow_snapshot(exported_name=m),
            ) if getattr(self, "_workflow_dialog", None) else None
        )
        dlg.workflow_failed.connect(
            lambda e: self._workflow_dialog.on_stage_failed(e)
            if getattr(self, "_workflow_dialog", None) else None
        )
        dlg.exec()

    def _run_export_split_episodes(self):
        """Step 5B: Export split episodes by chapter markers into a folder."""
        if not self.project_id or not self.video_path or not Path(self.video_path).exists():
            QMessageBox.warning(self, "Ai Summarai", "សូមបើកវីដេអូជាមុនសិន!")
            return

        out_dir = QFileDialog.getExistingDirectory(
            self,
            "ជ្រើសរើសថតរក្សាទុកវីដេអូជាភាគៗ (Select Folder to Export Split Episodes)",
            str(Path.home() / "Videos"),
        )
        if not out_dir:
            return

        if hasattr(self, "video_editor") and hasattr(self.video_editor, "player"):
            self.video_editor.pause()

        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor._sync_ui_to_edits()
            live_edits = dict(self.video_editor.edits)
            self._on_edits_changed(live_edits)

        edits = self.db.get_project_edits(self.project_id) if self.db else {}
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        if keep_bgm_only:
            edits["mute_original_audio"] = 0
            bgm_vol = round(max(0.20, self.bgm_slider.value() / 100.0), 2)
        else:
            edits["mute_original_audio"] = 1
            bgm_vol = 0.0
        edits["anti_copyright_enabled"] = int(edits.get("anti_copyright_enabled", 1))
        edits["auto_blur_chinese"] = int(edits.get("auto_blur_chinese", 1))
        segments = self.db.get_segments(self.project_id) if self.db else []
        clip_markers = list(getattr(self, "_clip_markers", []) or [])

        def task(emit):
            emit(10, "កំពុងចាប់ផ្តើមបែងចែកវីដេអូ និង Render ជាភាគៗ...")
            exported = MediaEngine.export_split_episodes(
                video_path=self.video_path,
                segments=segments,
                clip_markers=clip_markers,
                output_dir=out_dir,
                edits=edits,
                bgm_volume=bgm_vol,
                cancel_event=self._cancel_event,
                progress_cb=emit,
            )
            return exported

        def on_done(exported):
            count = len(exported) if isinstance(exported, list) else 0
            reply = QMessageBox.information(
                self,
                "Ai Summarai",
                f"🎉 បាន Render វីដេអូចំនួន {count} ភាគដោយជោគជ័យ!\nទីតាំង: {out_dir}",
                QMessageBox.Open | QMessageBox.Ok,
            )
            if reply == QMessageBox.Open:
                import os
                os.startfile(out_dir)

        self._run_worker(task, on_done)

    def _open_export_with_anti_copyright(self):
        """Enable Anti-Copyright and open Export Video Dialog."""
        if not self.project_id:
            QMessageBox.warning(self, "Ai Summarai", "សូមបើកវីដេអូជាមុនសិន!")
            return
        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor.edits["anti_copyright_enabled"] = 1
            self.video_editor.edits["auto_blur_chinese"] = 1
            if not self.video_editor.edits.get("mask_enabled", 0):
                self.video_editor.toggle_bottom_blur_mask()
            if hasattr(self, "btn_bottom_blur"):
                self.btn_bottom_blur.setChecked(True)
        if self.db and self.project_id:
            self.db.update_project_edits(self.project_id, anti_copyright_enabled=1, auto_blur_chinese=1)
        self._run_export_video()

    def _apply_anti_copyright_preset(self, level: str):
        """Applies chosen AI anti-copyright preset and prompts to preview immediately."""
        if not self.project_id or not self.video_path or not Path(self.video_path).exists():
            QMessageBox.warning(self, "Ai Summarai", "សូមបើកវីដេអូជាមុនសិន!")
            return

        level = str(level or "medium").lower()
        mirror = (level == "strong")

        if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
            self.video_editor.edits["anti_copyright_enabled"] = 1
            self.video_editor.edits["anti_copyright_level"] = level
            self.video_editor.edits["anti_copyright_flip"] = 1 if mirror else 0
            self.video_editor.edits["auto_blur_chinese"] = 1
            if not self.video_editor.edits.get("mask_enabled", 0):
                self.video_editor.toggle_bottom_blur_mask()
            if hasattr(self, "btn_bottom_blur"):
                self.btn_bottom_blur.setChecked(True)
        if self.db and self.project_id:
            self.db.update_project_edits(
                self.project_id,
                anti_copyright_enabled=1,
                anti_copyright_level=level,
                anti_copyright_flip=1 if mirror else 0,
                auto_blur_chinese=1,
            )

        level_kh = "កម្រិតស្រាល (Light)" if level == "light" else ("កម្រិតខ្លាំង (Strong)" if level == "strong" else "កម្រិតមធ្យម (Medium)")
        reply = QMessageBox.question(
            self,
            "Ai Summarai — AI Anti-Copyright",
            f"🛡️ បានកំណត់ AI Anti-Copyright {level_kh} រួចរាល់!\n\n"
            "តើអ្នកចង់អនុវត្តលើ Video Preview ឥឡូវនេះ ដើម្បីចាក់ស្តាប់ និងផ្ទៀងផ្ទាត់មើលភ្លាមៗឬទេ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._render_anti_copyright_preview(level, mirror)
        else:
            self.status_lbl.setText(f"🛡️ បានបើក AI Anti-Copyright: {level_kh} (នឹងដំណើរការពេល Export)")

    def _render_anti_copyright_preview(self, level: str, mirror: bool = False, border: bool = False):
        """Renders AI Anti-Copyright directly on preview video and updates player."""
        work_dir = Path(f"data/workspace/proj_{self.project_id}")
        work_dir.mkdir(parents=True, exist_ok=True)

        in_video = ""
        tmp_p = work_dir / "_tmp_preview.mp4"
        if tmp_p.exists() and tmp_p.stat().st_size > 1000:
            in_video = str(tmp_p)
        else:
            stream_files = sorted(work_dir.glob("preview_stream_*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
            if stream_files and stream_files[0].exists() and stream_files[0].stat().st_size > 1000:
                in_video = str(stream_files[0])
            else:
                in_video = self.video_path

        out_ac = str(work_dir / "_tmp_preview_anticopyright.mp4")

        def task(emit):
            emit(15, f"🛡️ កំពុងអនុវត្ត AI Anti-Copyright ({level.upper()}) លើ Video Preview...")
            edits = self.db.get_project_edits(self.project_id) if self.db else {}
            auto_blur = bool(edits.get("auto_blur_chinese", 1))
            auto_timed = bool(edits.get("auto_timed_blur", 1))
            lut_preset = str(edits.get("lut_preset", "none") or "none")
            segments = self.db.get_segments(self.project_id) if self.db else []
            MediaEngine.apply_anti_copyright(
                video_path=in_video,
                output_mp4=out_ac,
                level=level,
                mirror_flip=mirror,
                add_frame_border=border,
                auto_blur_chinese=auto_blur,
                auto_timed_blur=auto_timed,
                lut_preset=lut_preset,
                segments=segments,
                cancel_event=self._cancel_event,
                progress_cb=emit,
            )
            return out_ac

        def on_done(res_path):
            if hasattr(self, "video_editor") and Path(res_path).exists():
                self.video_editor.set_dubbed_video_preview(res_path)
                self.status_lbl.setText("🛡️ បានអនុវត្ត AI Anti-Copyright លើ Video Preview រួចរាល់! អាចចាក់មើលបានភ្លាម។")
                QMessageBox.information(
                    self,
                    "Ai Summarai",
                    "🎉 បានកាត់ផ្តាច់ Copyright លើ Video Preview ជោគជ័យ!\n"
                    "អ្នកអាចចាក់មើលលើ Player ដើម្បីស្តាប់សំឡេង និងពិនិត្យរូបភាពបាន។",
                )

        self._run_worker(task, on_done)

    def _open_anti_copyright_dialog(self):
        """Dialog to customize Anti-Copyright settings and apply to preview or export."""
        if not self.project_id:
            QMessageBox.warning(self, "Ai Summarai", "សូមបើកវីដេអូជាមុនសិន!")
            return

        edits = self.db.get_project_edits(self.project_id) if self.db else {}
        dlg = QDialog(self)
        dlg.setWindowTitle("🛡️ AI Anti-Copyright Studio (កាត់ផ្តាច់ Copyright)")
        dlg.setFixedSize(520, 420)
        dlg.setStyleSheet("background-color: #0B0D10; color: #F4F6FB;")

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        lbl_title = QLabel("🛡️ កំណត់កម្រិត AI Anti-Copyright (Content ID Bypass)")
        lbl_title.setStyleSheet("font-size: 13.5px; font-weight: 800; color: #00E5FF;")
        lay.addWidget(lbl_title)

        lbl_desc = QLabel(
            "ផ្លាស់ប្តូរ Digital Fingerprint ទាំងរូបភាព (Dynamic Sin/Cos Zoom & Pan, Color Matrix, Grain)\n"
            "និងរលកសំឡេង (Pitch Shift, EQ, Pink Noise) ដោយរក្សាសំឡេងនិយាយខ្មែរឲ្យនៅច្បាស់ល្អ។"
        )
        lbl_desc.setStyleSheet("font-size: 11px; color: #94A3B8; line-height: 1.4;")
        lay.addWidget(lbl_desc)

        lbl_lvl = QLabel("ជ្រើសរើសកម្រិតការពារ (Protection Level):")
        lbl_lvl.setStyleSheet("font-size: 11px; font-weight: 600; color: #F4F6FB;")
        lay.addWidget(lbl_lvl)

        cb_level = QComboBox()
        cb_level.setFixedHeight(32)
        cb_level.setStyleSheet(
            "QComboBox { background: #181C24; border: 1px solid #343B4C; border-radius: 6px; padding: 4px 10px; font-size: 11.5px; color: #F4F6FB; }"
        )
        cb_level.addItem("🟢 កម្រិតស្រាល (Natural Safe - Zoom 1.04x / Subtle Shift)", "light")
        cb_level.addItem("🟡 កម្រិតមធ្យម (Standard Bypass - Zoom 1.07x / Recom.)", "medium")
        cb_level.addItem("🔴 កម្រិតខ្លាំង (Max Fingerprint Break - Mirror + Grain)", "strong")

        cur_l = edits.get("anti_copyright_level", "medium")
        idx = cb_level.findData(cur_l)
        cb_level.setCurrentIndex(idx if idx >= 0 else 1)
        lay.addWidget(cb_level)

        from PySide6.QtWidgets import QCheckBox
        chk_flip = QCheckBox("🪞 ត្រឡប់ឆ្វេងស្តាំ (Horizontal Mirror Flip)")
        chk_flip.setStyleSheet("font-size: 11.5px; color: #F4F6FB;")
        chk_flip.setChecked(bool(edits.get("anti_copyright_flip", 0)))
        lay.addWidget(chk_flip)

        chk_border = QCheckBox("🖼️ ស៊ុមព្រិលព័ទ្ធជុំវិញ (Gaussian-Blurred Frame Border)")
        chk_border.setStyleSheet("font-size: 11.5px; color: #F4F6FB;")
        chk_border.setChecked(bool(edits.get("anti_copyright_border", 0)))
        lay.addWidget(chk_border)

        chk_auto_blur = QCheckBox("🌫️ Auto-Blur បាំងអក្សរចិនក្នុងវីដេអូស្វ័យប្រវត្តិ (Auto-Blur Chinese Subtitles)")
        chk_auto_blur.setStyleSheet("font-size: 11.5px; color: #38BDF8; font-weight: 600;")
        chk_auto_blur.setChecked(bool(edits.get("auto_blur_chinese", 1)))
        lay.addWidget(chk_auto_blur)

        chk_preview_now = QCheckBox("🎬 អនុវត្តលើ Live Preview Player ឥឡូវនេះ (ដើម្បីចាក់មើលភ្លាមៗ)")
        chk_preview_now.setStyleSheet("font-size: 11.5px; font-weight: 700; color: #34D399;")
        chk_preview_now.setChecked(True)
        lay.addWidget(chk_preview_now)

        lay.addStretch()

        btn_box = QHBoxLayout()
        btn_save = QPushButton("💾 រក្សាទុក & អនុវត្ត (Save & Apply)")
        btn_save.setObjectName("BtnCyan")
        btn_save.setFixedHeight(34)

        btn_cancel = QPushButton("បោះបង់ (Cancel)")
        btn_cancel.setObjectName("BtnGlass")
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(dlg.reject)

        def on_save_clicked():
            sel_l = cb_level.currentData()
            sel_flip = 1 if chk_flip.isChecked() else 0
            sel_border = 1 if chk_border.isChecked() else 0
            sel_blur = 1 if chk_auto_blur.isChecked() else 0
            do_preview = chk_preview_now.isChecked()

            if hasattr(self, "video_editor") and hasattr(self.video_editor, "edits"):
                self.video_editor.edits["anti_copyright_enabled"] = 1
                self.video_editor.edits["anti_copyright_level"] = sel_l
                self.video_editor.edits["anti_copyright_flip"] = sel_flip
                self.video_editor.edits["anti_copyright_border"] = sel_border
                self.video_editor.edits["auto_blur_chinese"] = sel_blur
                if sel_blur and not self.video_editor.edits.get("mask_enabled", 0):
                    self.video_editor.toggle_bottom_blur_mask()
                if hasattr(self, "btn_bottom_blur"):
                    self.btn_bottom_blur.setChecked(bool(sel_blur))

            if self.db and self.project_id:
                self.db.update_project_edits(
                    self.project_id,
                    anti_copyright_enabled=1,
                    anti_copyright_level=sel_l,
                    anti_copyright_flip=sel_flip,
                    anti_copyright_border=sel_border,
                    auto_blur_chinese=sel_blur,
                )

            dlg.accept()
            if do_preview:
                self._render_anti_copyright_preview(sel_l, bool(sel_flip), bool(sel_border))
            else:
                self.status_lbl.setText("🛡️ បានរក្សាទុកការកំណត់ AI Anti-Copyright រួចរាល់!")

        btn_save.clicked.connect(on_save_clicked)
        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        lay.addLayout(btn_box)

        dlg.exec()

    def _on_bulk_voice_selected(self, idx: int):
        val = self.combo_bulk_voice.currentData()
        if not val or not self.project_id:
            return

        self.combo_bulk_voice.blockSignals(True)
        self.combo_bulk_voice.setCurrentIndex(0)
        self.combo_bulk_voice.blockSignals(False)

        if val in ("all_female", "all_male"):
            target_voice = "female" if val == "all_female" else "male"
            reply = QMessageBox.question(
                self,
                "Ai Summarai",
                f"តើអ្នកពិតជាចង់ប្តូរសំឡេងគ្រប់ជួរទាំងអស់ក្នុងវីដេអូទៅជា '{target_voice.upper()}' ឬទេ?\n(សំឡេងចាស់នឹងត្រូវកំណត់ឡើងវិញ)",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            with self.db.conn:
                self.db.conn.execute(
                    "UPDATE segments SET voice_override=?, tts_audio_path='', status='Edited' WHERE project_id=?",
                    (target_voice, self.project_id),
                )
        else:
            selected_indexes = self.table.selectionModel().selectedRows()
            selected_rows = set(idx.row() for idx in selected_indexes)
            if not selected_rows:
                for it in self.table.selectedItems():
                    selected_rows.add(it.row())

            if not selected_rows:
                QMessageBox.information(self, "Ai Summarai", "សូមជ្រើសរើសជួរក្នុងតារាងជាមុនសិន (Please select rows in the table first)!")
                return

            with self.db.conn:
                for r in selected_rows:
                    id_it = self.table.item(r, 0)
                    if id_it:
                        seg_id = int(id_it.text())
                        self.db.conn.execute(
                            "UPDATE segments SET voice_override=?, tts_audio_path='', status='Edited' WHERE id=?",
                            (val, seg_id),
                        )

        self._refresh_table()
        self._update_timeline()
        self.status_lbl.setText("🎙️ បានប្តូរសំឡេងរួចរាល់! អាចចុច '4. Generate Voice' ដើម្បីបង្កើតសំឡេងឡើងវិញ។")

    def _on_tts_speed_changed(self, idx: int):
        speed = float(self.combo_tts_speed.currentData() or 1.0)
        self.tts_speed_mult = speed
        self.status_lbl.setText(f"⚡ បានកំណត់ល្បឿនអានសំឡេងខ្មែរ: {speed:.2f}x")

    def _toggle_bottom_blur(self):
        if not hasattr(self, "video_editor"):
            return
        is_active = self.video_editor.toggle_bottom_blur_mask()
        self.btn_bottom_blur.setChecked(is_active)
        if hasattr(self.video_editor, "edits"):
            self.video_editor.edits["auto_blur_chinese"] = 1 if is_active else 0
        if self.project_id:
            self.db.update_project_edits(self.project_id, auto_blur_chinese=1 if is_active else 0)
            self.db.save_project_edits(self.project_id, self.video_editor.edits)
        state_txt = "បើក (ON)" if is_active else "បិទ (OFF)"
        self.status_lbl.setText(f"🌫 Auto Blur Chinese: {state_txt}")

    def _clean_chinese_from_khmer_script(self):
        """
        1-Click Auto Delete Chinese Text in Khmer Dub Script:
        Scans all segments in the active project in SQLite.
        Strips residual Chinese characters, bracketed notes, and Chinese punctuation
        from 'kh_text', updates SQLite, syncs the table, and reloads video player subtitles.
        """
        if not self.project_id:
            QMessageBox.warning(self, "Ai Summarai", "សូមបើកវីដេអូ ឬគម្រោងជាមុនសិន!")
            return

        from core.translator import strip_chinese_from_khmer
        segments = self.db.get_segments(self.project_id)
        if not segments:
            QMessageBox.information(self, "Ai Summarai", "មិនមានជួរអត្ថបទក្នុងគម្រោងនេះទេ!")
            return

        cleaned_count = 0
        zh_pattern = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef]")

        for s in segments:
            sid = s["id"]
            raw_kh = s.get("kh_text") or ""
            if zh_pattern.search(raw_kh):
                clean_kh = strip_chinese_from_khmer(raw_kh)
                if clean_kh != raw_kh:
                    self.db.update_segment(sid, kh_text=clean_kh)
                    cleaned_count += 1

        self._refresh_table()
        if hasattr(self, "video_editor"):
            self.video_editor.set_segments(self.db.get_segments(self.project_id))

        if cleaned_count > 0:
            QMessageBox.information(
                self,
                "Ai Summarai",
                f"🧹 បានសម្អាត និងលុបអក្សរចិនចេញពីតារាងខ្មែរចំនួន {cleaned_count} ជួរដោយជោគជ័យ!\n"
                "ពេលនេះអត្ថបទទាំងអស់ជាភាសាខ្មែរសុទ្ធ ១០០% គ្មានអក្សរចិនសេសសល់ឡើយ។",
            )
            self.status_lbl.setText(f"🧹 បានសម្អាតអក្សរចិនចេញពី {cleaned_count} ជួរ")
        else:
            QMessageBox.information(
                self,
                "Ai Summarai",
                "✨ តារាងភាសាខ្មែរគ្មានអក្សរចិនជ្រុះសេសសល់ទេ! អត្ថបទទាំងអស់ស្អាត ១០០% រួចរាល់។",
            )
            self.status_lbl.setText("✨ អត្ថបទខ្មែរស្អាតល្អ ១០០% គ្មានអក្សរចិនឡើយ")

    def _apply_table_filter(self):
        f_val = self.combo_table_filter.currentData() if hasattr(self, "combo_table_filter") else "all"
        kh_regex = re.compile(r"[\u1780-\u17FF]")

        self.table.setUpdatesEnabled(False)
        try:
            total_rows = self.table.rowCount()
            for r in range(total_rows):
                if f_val == "all":
                    self.table.setRowHidden(r, False)
                    continue

                kh_it = self.table.item(r, 3)
                kh_text = kh_it.text().strip() if kh_it else ""
                state_it = self.table.item(r, 6)
                state_text = state_it.text() if state_it else ""

                voice_cb = self.table.cellWidget(r, 4)
                v_key = voice_cb.currentData() if (voice_cb and isinstance(voice_cb, QComboBox)) else ""

                hide = False
                if f_val == "untranslated":
                    hide = bool(kh_regex.search(kh_text))
                elif f_val == "unvoiced":
                    hide = ("Voiced" in state_text or "●" in state_text)
                elif f_val == "female":
                    hide = (v_key != "female")
                elif f_val == "male":
                    hide = (v_key != "male")
                elif f_val == "inner_thought":
                    hide = (v_key != "inner_thought")
                elif f_val == "phone_call":
                    hide = (v_key != "phone_call")

                self.table.setRowHidden(r, hide)
        finally:
            self.table.setUpdatesEnabled(True)

    @staticmethod
    def _style_state_item(item: QTableWidgetItem, status: str):
        st = (status or "").strip()
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setTextAlignment(Qt.AlignCenter)
        if st == "Voiced":
            item.setForeground(QBrush(QColor("#34D399")))
            item.setText("● Voiced")
        elif st == "Ready":
            item.setForeground(QBrush(QColor("#60A5FA")))
            item.setText("● Ready")
        elif "Updating" in st or "Edited" in st:
            item.setForeground(QBrush(QColor("#FBBF24")))
            item.setText(f"● {st}")
        elif st.lower() in ("pending", "waiting", ""):
            item.setForeground(QBrush(QColor("#94A3B8")))
            item.setText("● Pending")
        else:
            item.setForeground(QBrush(QColor("#94A3B8")))
            item.setText(f"● {st}")

    def _populate_voice_combo(self, combo: QComboBox, selected_key: str = ""):
        combo.clear()
        label_field = "label_kh" if self.lang == "kh" else "label_en"
        default_lbl = "លំនាំដើម" if self.lang == "kh" else "Default"
        combo.addItem(default_lbl, "")

        all_profiles = getattr(self, "_cached_voice_profiles", None)
        if not all_profiles:
            from core.tts_engine import KhmerTTSEngine
            all_profiles = KhmerTTSEngine.get_all_voice_profiles(self.db)
            self._cached_voice_profiles = all_profiles

        for key, info in all_profiles.items():
            k_lower = key.lower()
            dot = "🔵 " if ("male" in k_lower or "boy" in k_lower or "piseth" in k_lower) else (
                "🌸 " if ("female" in k_lower or "girl" in k_lower or "sreymom" in k_lower) else (
                    "🟣 " if ("thought" in k_lower or "whisper" in k_lower) else "🎙️ "
                )
            )
            combo.addItem(f"{dot}{info.get(label_field, key)}", key)

        # គាំទ្រទិន្នន័យចាស់ៗក្នុង Database
        if selected_key in ("km-KH-SreymomNeural", "girl", "old_female"):
            selected_key = "female"
        elif selected_key in ("km-KH-PisethNeural", "boy", "old_male"):
            selected_key = "male"
        elif selected_key == "distant_call":
            selected_key = "inner_thought"

        idx = combo.findData(selected_key)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _refresh_table(self):
        if not self.project_id:
            return
        self.table.blockSignals(True)
        from core.tts_engine import KhmerTTSEngine
        self._cached_voice_profiles = KhmerTTSEngine.get_all_voice_profiles(self.db)
        segments = self.db.get_segments(self.project_id)
        current_rows = self.table.rowCount()
        new_count = len(segments)

        def _fmt_ts(ms: int) -> str:
            s = max(0, int(ms or 0)) / 1000.0
            m = int(s // 60)
            sec = s % 60
            return f"{m:02d}:{sec:04.1f}"

        font_mono = QFont("JetBrains Mono", 8, QFont.Bold)
        font_mono.setFamilies(["JetBrains Mono", "Consolas", "Courier New"])

        font_kh = QFont("Kantumruy Pro", 9)
        font_kh.setFamilies(["Kantumruy Pro", "Noto Sans Khmer", "Khmer OS Battambang", "Segoe UI"])

        font_zh = QFont("Microsoft YaHei", 9)
        font_zh.setFamilies(["Microsoft YaHei", "PingFang SC", "Segoe UI"])

        if current_rows != new_count:
            self.table.setRowCount(new_count)

        for row, seg in enumerate(segments):
            seg_id = int(seg.get("id") or 0)
            start_ms = int(seg.get("start_ms") or 0)
            end_ms = int(seg.get("end_ms") or 0)
            zh_text = str(seg.get("zh_text") or "")
            kh_text = str(seg.get("kh_text") or "")
            status_text = str(seg.get("status") or "pending")
            voice_val = str(seg.get("voice_override") or "")
            tts_path = str(seg.get("tts_audio_path") or "")

            t_str = f"{_fmt_ts(start_ms)}\n{_fmt_ts(end_ms)}"

            # 0. ID (Hidden)
            id_item = self.table.item(row, 0)
            if not id_item:
                id_item = QTableWidgetItem(str(seg_id))
                self.table.setItem(row, 0, id_item)
            else:
                id_item.setText(str(seg_id))

            # 1. Timecode
            time_item = self.table.item(row, 1)
            if not time_item:
                time_item = QTableWidgetItem(t_str)
                time_item.setTextAlignment(Qt.AlignCenter)
                time_item.setFont(font_mono)
                time_item.setFlags(time_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 1, time_item)
            elif time_item.text() != t_str:
                time_item.setText(t_str)

            # 2. Chinese Text
            zh_item = self.table.item(row, 2)
            if not zh_item:
                zh_item = QTableWidgetItem(zh_text)
                zh_item.setFont(font_zh)
                self.table.setItem(row, 2, zh_item)
            elif zh_item.text() != zh_text:
                zh_item.setText(zh_text)

            # 3. Khmer Translated Dub Script
            kh_item = self.table.item(row, 3)
            if not kh_item:
                kh_item = QTableWidgetItem(kh_text)
                kh_item.setFont(font_kh)
                self.table.setItem(row, 3, kh_item)
            elif kh_item.text() != kh_text:
                kh_item.setText(kh_text)

            # 4. Voice Character Preset
            voice_box = self.table.cellWidget(row, 4)
            if not voice_box or not isinstance(voice_box, QComboBox) or getattr(voice_box, "_bound_seg_id", None) != seg_id:
                voice_box = QComboBox()
                voice_box._bound_seg_id = seg_id
                voice_box.setFixedHeight(28)
                voice_box.setStyleSheet(
                    "background: #181C24; border: 1px solid #252A36; border-radius: 6px; "
                    "padding: 2px 6px; font-size: 11px;"
                )
                self._populate_voice_combo(voice_box, voice_val)
                voice_box.currentIndexChanged.connect(
                    lambda _, sid=seg_id, cb=voice_box: self._on_voice_changed(sid, cb.currentData())
                )
                self.table.setCellWidget(row, 4, voice_box)
            else:
                cur_idx = voice_box.findData(voice_val)
                if cur_idx >= 0 and voice_box.currentIndex() != cur_idx:
                    voice_box.blockSignals(True)
                    voice_box.setCurrentIndex(cur_idx)
                    voice_box.blockSignals(False)

            # 5. Play Voice Button
            btn_play = self.table.cellWidget(row, 5)
            has_clip = bool(tts_path and Path(tts_path).exists() and Path(tts_path).stat().st_size > 512)
            can_play = has_clip or bool(kh_text.strip())
            if not btn_play or not isinstance(btn_play, QPushButton) or getattr(btn_play, "_bound_seg_id", None) != seg_id:
                btn_play = QPushButton("▶")
                btn_play._bound_seg_id = seg_id
                btn_play.setObjectName("RowPlayBtn")
                btn_play.setFixedSize(26, 26)
                btn_play.setStyleSheet("border-radius: 13px; font-size: 10px; font-weight: 800;")
                btn_play.setToolTip("Play Khmer voice clip for this row")
                btn_play.clicked.connect(lambda _, sid=seg_id: self._play_single_line(sid))
                self.table.setCellWidget(row, 5, btn_play)
            btn_play.setEnabled(can_play)

            # 6. Status Badge
            state_item = self.table.item(row, 6)
            if not state_item:
                state_item = QTableWidgetItem(status_text)
                self._style_state_item(state_item, status_text)
                self.table.setItem(row, 6, state_item)
            elif state_item.text() != status_text:
                state_item.setText(status_text)
                self._style_state_item(state_item, status_text)

        self.table.blockSignals(False)
        if hasattr(self, "table_empty_state"):
            if new_count == 0:
                self.table_empty_state.show()
                self.table.clearSelection()
                self.table.setCurrentItem(None)
            else:
                self.table_empty_state.hide()

        self._apply_table_filter()

        if hasattr(self, "video_editor"):
            self.video_editor.set_segments(segments)
        if hasattr(self, "timeline_tracks"):
            dur = max(1000, self.video_editor.player.duration())
            if segments:
                dur = max(dur, segments[-1]["end_ms"] + 1000)
            self.timeline_tracks.set_data(dur, segments)
            self.timeline_tracks.set_sfx_events(self.db.get_sfx_events(self.project_id))
        self._update_button_states()

    def _open_sfx_menu(self):
        if not self.project_id:
            return
        menu = QMenu(self)
        kh = self.lang == "kh"
        label_key = "label_kh" if kh else "label_en"

        from core.sfx_engine import SFXEngine
        for key, info in SFXEngine.PRESETS.items():
            act = menu.addAction(info[label_key])
            act.triggered.connect(lambda _, k=key, lbl=info[label_key]: self._insert_sfx_at_playhead(k, lbl))

        menu.addSeparator()
        act_custom = menu.addAction("📂 ជ្រើសរើសឯកសារ SFX (.mp3/.wav)..." if kh else "📂 Custom SFX File...")
        act_custom.triggered.connect(self._insert_custom_sfx)

        sfx_list = self.db.get_sfx_events(self.project_id)
        if sfx_list:
            menu.addSeparator()
            del_menu = menu.addMenu("🗑 លុប SFX ដែលបានដាក់" if kh else "🗑 Remove Added SFX")
            for item in sfx_list:
                sec = item["start_ms"] / 1000.0
                a_del = del_menu.addAction(f"{item['name']} ({sec:.1f}s)")
                a_del.triggered.connect(lambda _, sid=item["id"]: self._remove_sfx(sid))

        menu.exec(self.btn_sfx.mapToGlobal(self.btn_sfx.rect().bottomLeft()))

    def _insert_sfx_at_playhead(self, key: str, label: str):
        cur_ms = self.video_editor.player.position()
        from core.sfx_engine import SFXEngine
        wav_path = SFXEngine.get_preset_wav(key)
        self.db.add_sfx_event(self.project_id, label, cur_ms, wav_path, volume=0.90)
        self.timeline_tracks.set_sfx_events(self.db.get_sfx_events(self.project_id))
        # ចាក់សំឡេង Effect ភ្លាមៗឲ្យអ្នកប្រើឮសាកល្បង
        if Path(wav_path).exists():
            self.row_player.stop()
            self.row_player.setSource(QUrl())
            self.row_audio_out.setMuted(False)
            self.row_audio_out.setVolume(0.95)
            self.row_player.setSource(QUrl.fromLocalFile(str(Path(wav_path).resolve())))
            self.row_player.play()
        self._rebuild_smooth_preview()
        self.status_lbl.setText(f"បានបន្ថែមសំឡេង {label} នៅវិនាទីទី {cur_ms / 1000.0:.1f}s!")

    def _insert_custom_sfx(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select SFX", "", "Audio (*.mp3 *.wav *.m4a)")
        if path:
            cur_ms = self.video_editor.player.position()
            self.db.add_sfx_event(self.project_id, Path(path).stem[:14], cur_ms, path, volume=0.90)
            self.timeline_tracks.set_sfx_events(self.db.get_sfx_events(self.project_id))
            self._rebuild_smooth_preview()

    def _remove_sfx(self, sfx_id: int):
        self.db.delete_sfx_event(sfx_id)
        self.timeline_tracks.set_sfx_events(self.db.get_sfx_events(self.project_id))
        self._rebuild_smooth_preview()

    def _on_timeline_segment_clicked(self, row: int):
        if 0 <= row < self.table.rowCount():
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 1))

    def _play_single_line(self, seg_id: int):
        """ចុចប៊ូតុង ▶ លើជួរណាមួយ ដើម្បីស្តាប់សំឡេងខ្មែរជួរនោះភ្លាមៗ"""
        if not self.project_id:
            return
        segs = self.db.get_segments(self.project_id)
        target = next((s for s in segs if s["id"] == seg_id), None)
        if not target:
            return

        # ផ្អាកវីដេអូសិន ហើយលោតទៅត្រង់ម៉ោងនៃជួរនោះ
        self.video_editor.pause()
        self.video_editor.seek_to_ms(target["start_ms"])

        clip_path = target.get("tts_audio_path") or ""
        if clip_path and Path(clip_path).exists():
            self.row_player.stop()
            self.row_player.setSource(QUrl())
            self.row_audio_out.setMuted(False)
            self.row_audio_out.setVolume(1.0)
            self.row_player.setSource(QUrl.fromLocalFile(str(Path(clip_path).resolve())))
            self.row_player.play()
        else:
            # បើមិនទាន់មានសំឡេងទេ បង្កើតភ្លាមៗរួចចាក់ស្តាប់តែម្តង
            self._regenerate_single_line(seg_id, auto_play=True)

    def _regenerate_single_line(self, seg_id: int, auto_play: bool = False):
        """បង្កើតសំឡេងខ្មែរឡើងវិញតែ ១ ជួរដែលបានកែ ក្នុង ~0.3s ដោយមិនធ្វើឲ្យគាំង Player"""
        if self.worker and self.worker.isRunning():
            return

        voice_label = self.db.get_setting("kh_voice_label", "Female (Sreymom)")
        default_voice = DEFAULT_VOICES.get(voice_label, "km-KH-SreymomNeural")

        def task(emit):
            segs = self.db.get_segments(self.project_id)
            seg = next((s for s in segs if s["id"] == seg_id), None)
            if not seg or not (seg.get("kh_text") or "").strip():
                return "Empty line"

            from core.translator import normalize_dub_khmer_text
            raw_kh = (seg.get("kh_text") or "").strip()
            clean_kh = normalize_dub_khmer_text(raw_kh)
            if not clean_kh:
                return "Empty line"
            if clean_kh != raw_kh:
                self.db.update_segment(seg_id, kh_text=clean_kh)

            emit(30, f"កំពុងបង្កើតសំឡេងជួរ #{seg['seq_index']} ឡើងវិញ...")
            from core.tts_engine import KhmerTTSEngine
            tts = KhmerTTSEngine()
            clip_dir = Path(f"data/workspace/proj_{self.project_id}/tts")
            clip_dir.mkdir(parents=True, exist_ok=True)
            clip_path = str(clip_dir / f"seg_{seg_id}.wav")

            chosen_voice = seg.get("voice_override") or default_voice
            dur_ms = max(250, int(seg["end_ms"]) - int(seg["start_ms"]))
            tts.generate_clip(clean_kh, chosen_voice, dur_ms, clip_path, db=self.db, speed_mult=getattr(self, "tts_speed_mult", 1.0))
            self.db.update_segment(seg_id, tts_audio_path=clip_path, status="Voiced")
            return f"បានបង្កើតសំឡេងជួរ #{seg['seq_index']} រួចរាល់!"

        def after_replace():
            self._update_button_states()
            self._refresh_table()
            if auto_play:
                self._play_single_line(seg_id)

        self._run_worker(task, after_replace)

    def _show_table_context_menu(self, pos):
        """Right-click menu to bulk-assign voices, merge lines, or delete selected rows."""
        if not self.project_id or self.table.rowCount() == 0:
            return
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
        if not selected_rows:
            return

        menu = QMenu(self)
        kh = self.lang == "kh"

        # 1. ម៉ឺនុយរងសម្រាប់ប្តូរសំឡេងតួអង្គទាំងអស់ម្តង (Submenu + Direct Items)
        voice_menu = menu.addMenu("🎙 ប្តូរសំឡេងជួរដែលបានរើសទាំងអស់" if kh else "🎙 Set Voice for Selected Rows")
        act_default = voice_menu.addAction(tr(self.lang, "ctx_set_default"))
        act_default.triggered.connect(lambda _, rows=selected_rows: self._bulk_set_voice(rows, ""))
        voice_menu.addSeparator()

        label_field = "label_kh" if kh else "label_en"
        from core.tts_engine import KhmerTTSEngine
        all_profiles = KhmerTTSEngine.get_all_voice_profiles(self.db)

        # Basic voices
        for key in ("female", "male", "inner_thought", "phone_call"):
            if key in all_profiles:
                act = voice_menu.addAction(all_profiles[key][label_field])
                act.triggered.connect(lambda _, k=key, rows=selected_rows: self._bulk_set_voice(rows, k))

        # Human Presets Submenu
        human_menu = voice_menu.addMenu("👤 សំឡេងមនុស្សពិត (10 Presets)" if kh else "👤 Human Presets")
        for key, info in all_profiles.items():
            if info.get("is_human"):
                act = human_menu.addAction(info[label_field])
                act.triggered.connect(lambda _, k=key, rows=selected_rows: self._bulk_set_voice(rows, k))

        # Cloned Voices Submenu
        clone_menu = voice_menu.addMenu("✨ សំឡេងក្លូនផ្ទាល់ខ្លួន (Cloned)" if kh else "✨ Cloned Voices")
        has_cloned = False
        for key, info in all_profiles.items():
            if info.get("is_cloned"):
                has_cloned = True
                act = clone_menu.addAction(info[label_field])
                act.triggered.connect(lambda _, k=key, rows=selected_rows: self._bulk_set_voice(rows, k))
        if not has_cloned:
            act_none = clone_menu.addAction("— មិនទាន់មាន (ចុច Voice Clone ដើម្បីបង្កើត) —" if kh else "— No Cloned Voices —")
            act_none.setEnabled(False)

        menu.addSeparator()

        selected_seg_ids = [int(self.table.item(r, 0).text()) for r in selected_rows if self.table.item(r, 0)]
        if selected_seg_ids:
            act_redub_sel = menu.addAction(
                f"🎙️ បង្កើតសំឡេងឡើងវិញ ({len(selected_seg_ids)} ជួរ)" if kh else f"🎙️ Redub Selected ({len(selected_seg_ids)} Rows)"
            )
            act_redub_sel.triggered.connect(lambda: self._run_dub_voice(force_all=True, target_segment_ids=selected_seg_ids))

            act_retrans_sel = menu.addAction(
                f"🌐 បកប្រែឡើងវិញ ({len(selected_seg_ids)} ជួរ)" if kh else f"🌐 Retranslate Selected ({len(selected_seg_ids)} Rows)"
            )
            act_retrans_sel.triggered.connect(lambda: self._run_translate(force_all=True, target_segment_ids=selected_seg_ids))

            menu.addSeparator()

        # 2. បញ្ចូលជួរដែលបានរើសចូលគ្នា (Merge Lines)
        if len(selected_rows) >= 2:
            act_merge = menu.addAction("🔗 បញ្ចូលជួរទាំងនេះជាប្រយោគតែមួយ" if kh else "🔗 Merge Selected Lines")
            act_merge.triggered.connect(lambda: self._merge_selected_rows(selected_rows))

        # 2b. កាត់បំបែកជួរត្រង់ Playhead (Split Line at Current Playhead)
        if len(selected_rows) == 1 and self.table.item(selected_rows[0], 0):
            sid = int(self.table.item(selected_rows[0], 0).text())
            act_split = menu.addAction(
                "✂ កាត់បំបែកជួរត្រង់ម៉ោងវីដេអូបច្ចុប្បន្ន (Split)" if kh
                else "✂ Split Line at Current Playhead"
            )
            act_split.triggered.connect(lambda _, s=sid: self._split_row_at_playhead(s))

        # 2c. តម្រៀបម៉ោងគ្រប់ជួរកុំឲ្យជាន់គ្នា (Fix All Overlapping Timecodes)
        act_fix_ov = menu.addAction(
            "⚡ តម្រៀបម៉ោងគ្រប់ជួរកុំឲ្យជាន់គ្នា (Fix Overlaps)" if kh
            else "⚡ Fix All Overlapping Timecodes"
        )
        act_fix_ov.triggered.connect(self._run_fix_overlaps)

        # 2d. កាត់ប្រយោគវែងៗទាំងអស់ឲ្យនៅខ្លីៗ (Auto-Split All Long Sentences)
        act_auto_split = menu.addAction(
            "✂️ កាត់ប្រយោគវែងៗទាំងអស់ឲ្យនៅខ្លីៗ (Auto-Split Long Sentences)" if kh
            else "✂️ Auto-Split All Long Sentences"
        )
        act_auto_split.triggered.connect(self._run_auto_split_long)

        menu.addSeparator()

        # 3. លុបជួរដែលបានរើស (Delete Rows)
        act_del = menu.addAction("🗑 លុបជួរដែលបានរើស" if kh else "🗑 Delete Selected Rows")
        act_del.triggered.connect(lambda: self._delete_selected_rows(selected_rows))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _split_row_at_playhead(self, seg_id: int):
        cur_ms = self.video_editor.player.position()
        ok = self.db.split_segment_at_ms(seg_id, cur_ms)
        if ok:
            self._refresh_table()
            segs = self.db.get_segments(self.project_id)
            total_ms = self.video_editor.player.duration() or 60000
            if segs:
                total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
            self.timeline_tracks.set_data(total_ms, segs)
            self.status_lbl.setText(f"✂ បានកាត់បំបែកជួរត្រង់វិនាទី {cur_ms / 1000.0:.2f}s រួចរាល់!")
        else:
            self.status_lbl.setText("⚠️ សូមរំកិល Playhead វីដេអូឲ្យស្ថិតនៅចន្លោះកណ្តាលនៃជួរនេះជាមុនសិន!")

    def _run_fix_overlaps(self):
        if not self.project_id:
            return
        fixed = self.db.fix_all_overlaps(self.project_id)
        self._refresh_table()
        segs = self.db.get_segments(self.project_id)
        total_ms = self.video_editor.player.duration() or 60000
        if segs:
            total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
        self.timeline_tracks.set_data(total_ms, segs)
        self.status_lbl.setText(f"⚡ បានតម្រៀបម៉ោងជួរដែលជាន់គ្នាចំនួន {fixed} កន្លែងរួចរាល់!")

    def _run_auto_split_long(self):
        if not self.project_id:
            return
        extra = self.db.auto_split_long_segments(self.project_id, max_chars=12, max_duration_ms=3800)
        self._refresh_table()
        segs = self.db.get_segments(self.project_id)
        total_ms = self.video_editor.player.duration() or 60000
        if segs:
            total_ms = max(total_ms, segs[-1]["end_ms"] + 1000)
        self.timeline_tracks.set_data(total_ms, segs)
        if extra > 0:
            msg = f"✂️ បានកាត់បំបែកប្រយោគវែងៗបង្កើតបានចំនួន {extra} ជួរខ្លីៗបន្ថែមរួចរាល់!" if self.lang == "kh" else f"✂️ Split long sentences into {extra} additional short lines!"
        else:
            msg = "✅ រាល់ប្រយោគទាំងអស់មានប្រវែងខ្លីល្មមរួចរាល់ហើយ មិនបាច់កាត់បន្ថែមទេ!" if self.lang == "kh" else "✅ All sentences are already short and optimal!"
        self.status_lbl.setText(msg)

    def _bulk_set_voice(self, rows: list, voice_key: str):
        seg_ids = [int(self.table.item(r, 0).text()) for r in rows if self.table.item(r, 0)]
        if not seg_ids:
            return
        with self.db.conn:
            for sid in seg_ids:
                self.db.conn.execute(
                    "UPDATE segments SET voice_override=?, tts_audio_path='', status='Edited' WHERE id=?",
                    (voice_key, sid),
                )
        self._refresh_table()
        self.status_lbl.setText(
            f"បានប្តូរសំឡេងចំនួន {len(seg_ids)} ជួររួចរាល់! ចុច '៤. បង្កើតសំឡេងខ្មែរ' ដើម្បីផលិតសំឡេងថ្មី។"
        )

    def _merge_selected_rows(self, rows: list):
        seg_ids = [int(self.table.item(r, 0).text()) for r in rows if self.table.item(r, 0)]
        if len(seg_ids) < 2:
            return
        merged_id = self.db.merge_segments(seg_ids)
        self._refresh_table()
        if merged_id:
            self._regenerate_single_line(merged_id, auto_play=False)

    def _delete_selected_rows(self, rows: list):
        seg_ids = [int(self.table.item(r, 0).text()) for r in rows if self.table.item(r, 0)]
        if not seg_ids:
            return
        self.db.delete_segments(seg_ids)
        self._refresh_table()

    def _on_row_clicked(self, row: int, _col: int):
        if not self.project_id:
            return
        segments = self.db.get_segments(self.project_id)
        if 0 <= row < len(segments):
            self.video_editor.seek_to_ms(segments[row]["start_ms"])
            if hasattr(self, "timeline_tracks"):
                self.timeline_tracks.selected_idx = row
                self.timeline_tracks.set_position(segments[row]["start_ms"])

    def _on_voice_changed(self, seg_id: int, voice_code: str):
        self.db.update_segment(seg_id, voice_override=voice_code, status="Updating...")
        self._regenerate_single_line(seg_id, auto_play=True)

    def _on_cell_edited(self, item: QTableWidgetItem):
        row = item.row()
        seg_id = int(self.table.item(row, 0).text())
        if item.column() == 1:
            # អនុញ្ញាតឲ្យកែ Timecode ផ្ទាល់ក្នុងតារាង (ឧទាហរណ៍៖ "1.2s - 4.5s" ឬ "1.2s – 4.5s")
            try:
                raw_t = item.text().lower().replace("s", "").replace("–", "-")
                parts = raw_t.split("-")
                new_start = int(float(parts[0].strip()) * 1000)
                new_end = int(float(parts[1].strip()) * 1000)
                if new_end > new_start >= 0:
                    self.db.update_segment(seg_id, start_ms=new_start, end_ms=new_end, status="Edited")
                    state_item = self.table.item(row, 6)
                    if state_item:
                        self.table.blockSignals(True)
                        self._style_state_item(state_item, "Edited")
                        self.table.blockSignals(False)
            except Exception:
                pass
        elif item.column() == 2:
            self.db.update_segment(seg_id, zh_text=item.text())
        elif item.column() == 3:
            raw_kh = item.text().strip()
            from core.translator import strip_chinese_from_khmer
            new_kh = strip_chinese_from_khmer(raw_kh)
            if new_kh != raw_kh:
                self.table.blockSignals(True)
                item.setText(new_kh)
                self.table.blockSignals(False)
            self.db.update_segment(seg_id, kh_text=new_kh, status="Edited", tts_audio_path="")
            state_item = self.table.item(row, 6)
            if state_item:
                self.table.blockSignals(True)
                self._style_state_item(state_item, "Edited")
                self.table.blockSignals(False)
            if hasattr(self, "video_editor"):
                self.video_editor.set_segments(self.db.get_segments(self.project_id))
            self._update_button_states()
            btn_play = self.table.cellWidget(row, 5)
            if btn_play:
                btn_play.setEnabled(bool(new_kh))
