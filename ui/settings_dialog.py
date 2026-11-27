from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QDoubleSpinBox,
    QDialogButtonBox, QVBoxLayout
)
from core.database import Database
from core.tts_engine import KhmerTTSEngine


class SettingsDialog(QDialog):
    """Advanced settings dialog for API keys, Local URL, Voice & OCR crop box config."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Studio Configuration")
        self.resize(480, 260)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.api_url_input = QLineEdit(self.db.get_setting("api_url", "http://localhost:11434/v1"))
        self.api_key_input = QLineEdit(self.db.get_setting("api_key", ""))
        self.api_key_input.setEchoMode(QLineEdit.Password)
        saved_model = self.db.get_setting("model", "gemini-3.1-flash-lite")
        if saved_model in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "google-free", ""):
            saved_model = "gemini-3.1-flash-lite"

        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.setInsertPolicy(QComboBox.NoInsert)
        self.model_input.setStyleSheet("""
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

        models = [
            ("✨ gemini-3.1-flash-lite (⭐ Recommended / ថ្មីបំផុត - លឿន & សន្សំ Quota)", "gemini-3.1-flash-lite"),
            ("⚡ gemini-3.8-flash (High Speed & Accuracy / ឆ្លាតវៃ & គុណភាពខ្ពស់)", "gemini-3.8-flash"),
            ("🧠 gemini-3.7-flash (Deep Reasoning & Drama / វិភាគស៊ីជម្រៅ)", "gemini-3.7-flash"),
            ("🦙 qwen2.5:7b (⭐ Recommended Local Ollama for Chinese / ម៉ូដែលចិន-ខ្មែរល្អដាច់គេ)", "qwen2.5:7b"),
            ("🦙 qwen2.5:3b (Fast & Lightweight Local / ស្រាលសម្រាប់ PC ខ្សោយ)", "qwen2.5:3b"),
            ("🦙 qwen2.5:14b (Studio High Accuracy / ភាពសុក្រិតខ្ពស់)", "qwen2.5:14b"),
            ("💎 gemma2:9b (Google Local Ollama / ម៉ូដែល Google ក្នុងស្រុក)", "gemma2:9b"),
            ("🦙 llama3.2:3b (Ultra Low-RAM Local / ស្រាលបំផុត)", "llama3.2:3b"),
            ("🚀 gpt-4o-mini (OpenAI Fast & Cost-Effective)", "gpt-4o-mini"),
            ("👑 gpt-4o (OpenAI Flagship Studio Quality)", "gpt-4o"),
            ("⚡ llama-3.3-70b-versatile (Groq Ultra Fast)", "llama-3.3-70b-versatile"),
            ("🌐 google-free (Free Google Translate - No API Key Needed)", "google-free"),
        ]
        for label, mid in models:
            self.model_input.addItem(label, mid)

        matched_idx = -1
        for i in range(self.model_input.count()):
            if self.model_input.itemData(i) == saved_model:
                matched_idx = i
                break
        if matched_idx >= 0:
            self.model_input.setCurrentIndex(matched_idx)
        else:
            self.model_input.insertItem(0, f"⚙️ {saved_model} (Custom / Saved)", saved_model)
            self.model_input.setCurrentIndex(0)

        self.voice_combo = QComboBox()
        self.voice_combo.addItems(list(KhmerTTSEngine.VOICES.keys()))
        saved_voice = self.db.get_setting("default_voice", "Female (Sreymom)")
        idx = self.voice_combo.findText(saved_voice)
        if idx >= 0:
            self.voice_combo.setCurrentIndex(idx)

        self.crop_spin = QDoubleSpinBox()
        self.crop_spin.setRange(0.10, 0.50)
        self.crop_spin.setSingleStep(0.02)
        self.crop_spin.setValue(float(self.db.get_setting("ocr_crop_ratio", "0.22")))

        self.bgm_spin = QDoubleSpinBox()
        self.bgm_spin.setRange(0.0, 1.0)
        self.bgm_spin.setSingleStep(0.05)
        self.bgm_spin.setValue(float(self.db.get_setting("bgm_volume", "0.25")))

        form.addRow("Base URL:", self.api_url_input)
        form.addRow("API Key:", self.api_key_input)
        form.addRow("LLM Model:", self.model_input)
        form.addRow("Default Khmer Voice:", self.voice_combo)
        form.addRow("OCR Bottom Crop Ratio:", self.crop_spin)
        form.addRow("Original BGM Duck Volume:", self.bgm_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        self.db.set_setting("api_url", self.api_url_input.text().strip())
        self.db.set_setting("api_key", self.api_key_input.text().strip())
        idx = self.model_input.currentIndex()
        mid = self.model_input.itemData(idx) if idx >= 0 else None
        if not mid:
            raw = self.model_input.currentText().strip()
            mid = raw.split()[0].strip() if raw else "gemini-3.1-flash-lite"
        self.db.set_setting("model", str(mid))
        self.db.set_setting("default_voice", self.voice_combo.currentText())
        self.db.set_setting("ocr_crop_ratio", f"{self.crop_spin.value():.2f}")
        self.db.set_setting("bgm_volume", f"{self.bgm_spin.value():.2f}")
        self.accept()
