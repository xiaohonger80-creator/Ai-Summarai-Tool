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
        self.model_input = QLineEdit(self.db.get_setting("model", "qwen2.5:7b"))

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
        self.db.set_setting("model", self.model_input.text().strip())
        self.db.set_setting("default_voice", self.voice_combo.currentText())
        self.db.set_setting("ocr_crop_ratio", f"{self.crop_spin.value():.2f}")
        self.db.set_setting("bgm_volume", f"{self.bgm_spin.value():.2f}")
        self.accept()
