import re
import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QMessageBox,
    QFrame,
)

from core.api_pool import APIKeyPoolManager
from core.database import Database


class KeyTestWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, key: str, base_url: str):
        super().__init__()
        self.key = key
        self.base_url = base_url

    def run(self):
        try:
            if not self.key:
                self.finished.emit(False, "គ្មាន Key ត្រូវបានបញ្ចូលទេ!")
                return

            if "googleapis.com" in self.base_url.lower() or self.key.startswith("AIza") or self.key.startswith("AQ."):
                # Test with Gemini
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.key}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    self.finished.emit(True, "✅ Gemini API Key ត្រឹមត្រូវ និងដំណើរការល្អ!")
                elif resp.status_code == 429:
                    self.finished.emit(False, "⚠️ Key នេះបានអស់ Quota (429 Rate Limit) ជាបណ្តោះអាសន្ន!")
                elif resp.status_code == 400 or resp.status_code == 403:
                    self.finished.emit(False, f"❌ Key មិនត្រឹមត្រូវ ({resp.status_code})!")
                else:
                    self.finished.emit(False, f"⚠️ Server Error ({resp.status_code})")
            else:
                # Test with OpenAI/Other
                url = self.base_url.rstrip("/") + "/models" if self.base_url else "https://api.openai.com/v1/models"
                headers = {"Authorization": f"Bearer {self.key}"}
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    self.finished.emit(True, "✅ API Key ត្រឹមត្រូវ និងដំណើរការល្អ!")
                else:
                    self.finished.emit(False, f"❌ Key បរាជ័យ ({resp.status_code})!")
        except Exception as e:
            self.finished.emit(False, f"❌ កំហុសភ្ជាប់៖ {str(e)[:120]}")


class APIKeyPoolDialog(QDialog):
    """
    ផ្ទាំងគ្រប់គ្រង Multi-API Key Pool (ដាក់បញ្ចូល Keys ច្រើន និង Rotate ពេលអស់ Quota)
    """

    keys_saved = Signal(str)

    def __init__(self, db: Database, parent=None, lang: str = "kh"):
        super().__init__(parent)
        self.db = db
        self.lang = lang
        self._init_ui()
        self._load_keys()

    def _init_ui(self):
        kh = self.lang == "kh"
        self.setWindowTitle("🔑 គ្រប់គ្រង API Keys Pool (Multi-API Auto-Rotate)" if kh else "🔑 Manage API Keys Pool")
        self.resize(620, 480)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Poppins', 'Khmer OS Battambang', 'Segoe UI';
            }
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
            }
            QPlainTextEdit {
                background: #1E293B;
                border: 1px solid #475569;
                border-radius: 8px;
                padding: 10px;
                color: #F8FAFC;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                line-height: 1.5;
            }
            QPlainTextEdit:focus {
                border: 1px solid #38BDF8;
            }
            QPushButton {
                background: #1E293B;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 8px 16px;
                color: #F8FAFC;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #334155;
                border-color: #64748B;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header Frame
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet("background: #1E293B; border: 1px solid #334155; border-radius: 8px; padding: 10px;")
        hdr_layout = QVBoxLayout(hdr_frame)
        hdr_layout.setContentsMargins(0, 0, 0, 0)
        hdr_layout.setSpacing(4)

        lbl_title = QLabel("🔑 Multi-API Keys Pool (Auto-Rotate & Failover)" if not kh else "🔑 ប្រព័ន្ធគ្រប់គ្រង API Keys ច្រើន (ប្តូរស្វ័យប្រវត្តិកុំឱ្យទាក់)")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #38BDF8;")
        lbl_desc = QLabel(
            "អ្នកអាចបិទភ្ជាប់ (Paste) API Keys ច្រើនក្នុងប្រអប់ខាងក្រោម (១ បន្ទាត់ = ១ Key)។ "
            "នៅពេល Key ណាមួយអស់ Quota (429 Rate Limit) ប្រព័ន្ធនឹងប្តូរទៅ Key បន្ទាប់ដោយស្វ័យប្រវត្តិ ១០០% "
            "ដើម្បីកុំឱ្យដាច់ការបកប្រែ ឬការស្តាប់សំឡេង!"
            if kh else
            "Paste multiple API keys below (1 key per line). When any key hits a 429 quota or rate limit, "
            "the system automatically fails over to the next available key without interrupting your dubbing!"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 11px; color: #94A3B8;")
        hdr_layout.addWidget(lbl_title)
        hdr_layout.addWidget(lbl_desc)
        layout.addWidget(hdr_frame)

        # Text Area for Keys
        lbl_box = QLabel("បញ្ជី API Keys (១ បន្ទាត់ = ១ Key)៖" if kh else "API Keys List (1 key per line):")
        lbl_box.setStyleSheet("font-weight: 700; color: #F1F5F9;")
        layout.addWidget(lbl_box)

        self.txt_keys = QPlainTextEdit()
        self.txt_keys.setPlaceholderText(
            "AIzaSyBxxxxxxx1 (Key 1)\nAIzaSyCxxxxxxx2 (Key 2)\nAIzaSyDxxxxxxx3 (Key 3)" if kh else
            "AIzaSyBxxxxxxx1\nAIzaSyCxxxxxxx2\nAIzaSyDxxxxxxx3"
        )
        self.txt_keys.textChanged.connect(self._update_counter)
        layout.addWidget(self.txt_keys, 1)

        # Status & Count Bar
        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet("color: #10B981; font-weight: 600; font-size: 12px;")
        layout.addWidget(self.lbl_stats)

        # Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_test = QPushButton("⚡ សាកល្បង Key ដំបូង (Test First Key)" if kh else "⚡ Test First Key")
        self.btn_test.clicked.connect(self._test_first_key)

        btn_row.addWidget(self.btn_test)
        btn_row.addStretch()

        btn_cancel = QPushButton("បោះបង់ (Cancel)" if kh else "Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 រក្សាទុក Keys (Save)" if kh else "💾 Save Keys")
        btn_save.setStyleSheet("background-color: #059669; color: white; font-weight: 700;")
        btn_save.clicked.connect(self._save_keys)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _load_keys(self):
        saved = self.db.get_setting("api_key", "").strip()
        # Convert commas or semicolons to newlines for clean multi-line display
        if saved:
            tokens = re.split(r"[\r\n,;]+", saved)
            clean_lines = [t.strip() for t in tokens if t.strip()]
            self.txt_keys.setPlainText("\n".join(clean_lines))
        self._update_counter()

    def _update_counter(self):
        kh = self.lang == "kh"
        text = self.txt_keys.toPlainText().strip()
        pool = APIKeyPoolManager(text)
        count = pool.total_count
        if count == 0:
            self.lbl_stats.setText("⚠️ មិនទាន់មាន API Key ទេ (បញ្ចូល Key ដើម្បីដំណើរការ Cloud Translation/Whisper)" if kh else "⚠️ No keys entered")
            self.lbl_stats.setStyleSheet("color: #F59E0B;")
        elif count == 1:
            self.lbl_stats.setText("🔑 មាន 1 API Key សកម្ម (អ្នកអាចបន្ថែម Key ទី២ ឬទី៣ ដើម្បីប្តូរពេលអស់ Quota)" if kh else "🔑 1 active API Key")
            self.lbl_stats.setStyleSheet("color: #38BDF8;")
        else:
            self.lbl_stats.setText(f"🎉 មាន {count} API Keys ក្នុង Pool! (ប្រព័ន្ធ Auto-Failover ត្រៀមរួចរាល់)" if kh else f"🎉 {count} API Keys in Pool (Auto-Failover Ready)")
            self.lbl_stats.setStyleSheet("color: #10B981; font-weight: 700;")

    def _test_first_key(self):
        kh = self.lang == "kh"
        text = self.txt_keys.toPlainText().strip()
        pool = APIKeyPoolManager(text)
        first_key = pool.get_active_key()
        if not first_key:
            QMessageBox.warning(self, "Test Key", "សូមបញ្ចូល API Key យ៉ាងហោចណាស់មួយជាមុនសិន!" if kh else "Please enter at least one key first!")
            return

        base_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com")
        self.btn_test.setEnabled(False)
        self.lbl_stats.setText("⏳ កំពុងតេស្តសាកល្បង API Key..." if kh else "⏳ Testing API Key...")
        self.lbl_stats.setStyleSheet("color: #F59E0B;")

        self._tester = KeyTestWorker(first_key, base_url)
        self._tester.finished.connect(self._on_test_finished)
        self._tester.start()

    def _on_test_finished(self, ok: bool, msg: str):
        self.btn_test.setEnabled(True)
        self.lbl_stats.setText(msg)
        self.lbl_stats.setStyleSheet("color: #10B981; font-weight: 700;" if ok else "color: #EF4444; font-weight: 700;")

    def _save_keys(self):
        kh = self.lang == "kh"
        text = self.txt_keys.toPlainText().strip()
        pool = APIKeyPoolManager(text)
        all_keys = pool.get_all_keys()
        saved_str = "\n".join(all_keys)

        self.db.set_setting("api_key", saved_str)
        self.keys_saved.emit(saved_str)

        count = len(all_keys)
        QMessageBox.information(
            self,
            "Saved" if not kh else "ជោគជ័យ",
            f"បានរក្សាទុក {count} API Keys ជោគជ័យ!\nប្រព័ន្ធនឹងប្តូរ Key ស្វ័យប្រវត្តិកំឡុងពេលបកប្រែ ឬស្តាប់សំឡេង។" if kh else f"Saved {count} API keys successfully!"
        )
        self.accept()
