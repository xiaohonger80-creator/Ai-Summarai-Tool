"""
Dub Voice Selection Modal Dialog
Allows the user to choose between:
1. Original AI Voices (Sreymom / Piseth)
2. Real Cloned Voices (User Recorded/Uploaded Audio Samples or Studio Human Presets)
With direct button to launch the Voice Clone Studio to add/record new real human voice samples.
"""

from typing import Tuple, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGroupBox,
)

from core.database import Database
from core.tts_engine import KhmerTTSEngine
from core.voice_clone_engine import VoiceCloneEngine
from ui.voice_clone_dialog import VoiceCloneDialog


class DubVoiceSelectionDialog(QDialog):
    """
    ផ្ទាំងជ្រើសរើសប្រភេទសំឡេងបញ្ចូល (Dub Voice Selection Modal)
    - ជ្រើសរើសរវាង: សំឡេង AI ដើម (Sreymom / Piseth) vs សំឡេង Clone មនុស្សពិត (Real Voice / Human Presets)
    - បញ្ចូលតែជួរដែលខ្វះ (Dub Missing) vs បញ្ចូលឡើងវិញទាំងអស់ (Redub All)
    - អាចចុចបើក Voice Clone Studio ដើម្បីថត ឬដាក់សំឡេងពិតថ្មីភ្លាមៗ
    """

    def __init__(
        self,
        db: Database,
        unvoiced_count: int = 0,
        total_count: int = 0,
        lang: str = "kh",
        parent=None,
    ):
        super().__init__(parent)
        self.db = db
        self.unvoiced_count = unvoiced_count
        self.total_count = total_count
        self.lang = lang

        self.setWindowTitle("Ai Summarai — ជ្រើសរើសសំឡេងបញ្ចូល (Select Dubbing Voice)")
        self.setFixedWidth(560)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F1218;
                color: #F4F6FB;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #2B3345;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 14px;
                background-color: #141822;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #00E5FF;
            }
            QRadioButton {
                font-size: 12px;
                color: #F4F6FB;
                spacing: 8px;
            }
            QRadioButton:hover {
                color: #00E5FF;
            }
            QComboBox {
                background-color: #1A1F2C;
                color: #F4F6FB;
                border: 1px solid #3B455B;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 26px;
                font-size: 12px;
                font-weight: 500;
            }
            QComboBox:focus, QComboBox:hover {
                border-color: #00E5FF;
            }
            QComboBox QAbstractItemView {
                background-color: #161920;
                color: #F4F6FB;
                selection-background-color: #00E5FF;
                selection-color: #0B0D10;
                border: 1px solid #343B4C;
                outline: none;
                padding: 4px;
            }
            QPushButton#PrimaryBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00E5FF, stop:1 #10B981);
                color: #0B0D10;
                font-weight: bold;
                border-radius: 6px;
                padding: 7px 18px;
                font-size: 12px;
            }
            QPushButton#PrimaryBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38BDF8, stop:1 #34D399);
            }
            QPushButton#SecondaryBtn {
                background-color: #1C2230;
                color: #F4F6FB;
                border: 1px solid #343B4C;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11.5px;
            }
            QPushButton#SecondaryBtn:hover {
                border-color: #00E5FF;
                color: #00E5FF;
            }
        """)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # Title Header
        header = QLabel("🎙️ កំណត់ប្រភេទសំឡេងបញ្ចូល (Khmer Dubbing Setup)")
        header.setFont(QFont("Inter", 13, QFont.Bold))
        header.setStyleSheet("color: #F4F6FB;")
        root.addWidget(header)

        sub_header = QLabel("ជ្រើសរើសសំឡេង AI ធម្មតា ឬប្រើប្រាស់សំឡេងមនុស្សពិតដែលបានក្លូន (Cloned Voice)")
        sub_header.setStyleSheet("color: #8E95A5; font-size: 11px;")
        root.addWidget(sub_header)

        # -------------------------------------------------------------
        # 1. VOICE SOURCE SELECTION (AI vs Real Cloned Voice)
        # -------------------------------------------------------------
        self.voice_type_group = QButtonGroup(self)

        # BOX 1: Original AI Voice
        grp_ai = QGroupBox("🤖 សំឡេង AI ដើម (Original AI Voice - Fast & Free)")
        v_ai = QVBoxLayout(grp_ai)
        v_ai.setSpacing(8)

        self.rb_ai = QRadioButton("ប្រើសំឡេង Neural AI ធម្មតា (Edge-TTS 100% ឥតគិតថ្លៃ)")
        self.rb_ai.setChecked(True)
        self.voice_type_group.addButton(self.rb_ai, 1)
        v_ai.addWidget(self.rb_ai)

        ai_row = QHBoxLayout()
        ai_row.setSpacing(8)
        lbl_ai_choose = QLabel("តួអង្គ AI:")
        lbl_ai_choose.setStyleSheet("color: #8E95A5; font-size: 11px;")
        self.combo_ai = QComboBox()
        self.combo_ai.addItem("👩 នារីផ្អែមល្ហែម — Female (Sreymom)", "female")
        self.combo_ai.addItem("👨 បុរសរឹងមាំ — Male (Piseth)", "male")
        self.combo_ai.addItem("📡 Somleng នារីទូរគមនាគមន៍ — Somleng Telecom Female", "somleng_female")
        self.combo_ai.addItem("📡 Somleng បុរសទូរគមនាគមន៍ — Somleng Telecom Male", "somleng_male")

        saved_voice = self.db.get_setting("kh_voice_label", "Female (Sreymom)")
        if "Piseth" in saved_voice or "Male" in saved_voice:
            self.combo_ai.setCurrentIndex(1)
        else:
            self.combo_ai.setCurrentIndex(0)

        ai_row.addWidget(lbl_ai_choose)
        ai_row.addWidget(self.combo_ai, 1)
        v_ai.addLayout(ai_row)
        root.addWidget(grp_ai)

        # BOX 2: Real Cloned Voice & Human Presets
        grp_clone = QGroupBox("👤 សំឡេង Clone មនុស្សពិត (Real Cloned Voice & Human Presets)")
        v_clone = QVBoxLayout(grp_clone)
        v_clone.setSpacing(8)

        self.rb_clone = QRadioButton("ប្រើប្រាស់សំឡេងមនុស្សពិត (Acoustic Filter & Human Resonance)")
        self.voice_type_group.addButton(self.rb_clone, 2)
        v_clone.addWidget(self.rb_clone)

        clone_row = QHBoxLayout()
        clone_row.setSpacing(8)
        lbl_clone_choose = QLabel("ជ្រើសរើសសំឡេង:")
        lbl_clone_choose.setStyleSheet("color: #8E95A5; font-size: 11px;")
        self.combo_clone = QComboBox()
        self._populate_clone_voices()

        clone_row.addWidget(lbl_clone_choose)
        clone_row.addWidget(self.combo_clone, 1)
        v_clone.addLayout(clone_row)

        # Button to add/record real voice in Studio
        btn_studio_row = QHBoxLayout()
        btn_studio_row.addStretch()
        self.btn_open_studio = QPushButton("🎙️ ថត ឬដាក់សំឡេងពិតថ្មី (Voice Clone Studio)")
        self.btn_open_studio.setObjectName("SecondaryBtn")
        self.btn_open_studio.setToolTip("បើក Voice Clone Studio ដើម្បី upload ឯកសារសំឡេង ឬថតសំឡេងមនុស្សពិតផ្ទាល់")
        self.btn_open_studio.clicked.connect(self._open_voice_clone_studio)
        btn_studio_row.addWidget(self.btn_open_studio)
        v_clone.addLayout(btn_studio_row)

        root.addWidget(grp_clone)

        # Toggle combo enablement based on selected radio
        self.rb_ai.toggled.connect(self._on_voice_type_toggled)
        self.rb_clone.toggled.connect(self._on_voice_type_toggled)
        self._on_voice_type_toggled()

        # -------------------------------------------------------------
        # 2. DUBBING SCOPE (Missing Only vs Redub All)
        # -------------------------------------------------------------
        grp_scope = QGroupBox("🎯 វិសាលភាពនៃការបញ្ចូលសំឡេង (Dubbing Scope)")
        v_scope = QVBoxLayout(grp_scope)
        v_scope.setSpacing(8)

        self.scope_group = QButtonGroup(self)
        if self.unvoiced_count > 0 and self.unvoiced_count < self.total_count:
            self.rb_missing = QRadioButton(f"🎙️ បញ្ចូលតែជួរដែលខ្វះសំឡេង ({self.unvoiced_count} ជួរ)")
            self.rb_missing.setChecked(True)
            self.scope_group.addButton(self.rb_missing, 1)
            v_scope.addWidget(self.rb_missing)

            self.rb_all = QRadioButton(f"🔄 បញ្ចូលឡើងវិញគ្រប់ជួរទាំងអស់ ({self.total_count} ជួរ)")
            self.scope_group.addButton(self.rb_all, 2)
            v_scope.addWidget(self.rb_all)
        else:
            self.rb_missing = None
            self.rb_all = QRadioButton(f"🔄 បញ្ចូលសំឡេងគ្រប់ {self.total_count} ជួរទាំងអស់")
            self.rb_all.setChecked(True)
            self.scope_group.addButton(self.rb_all, 2)
            v_scope.addWidget(self.rb_all)

        root.addWidget(grp_scope)

        # -------------------------------------------------------------
        # 3. ACTION BUTTONS (Cancel & Start Dubbing)
        # -------------------------------------------------------------
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        self.btn_cancel = QPushButton("❌ បោះបង់ (Cancel)")
        self.btn_cancel.setObjectName("SecondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("🚀 ចាប់ផ្តើមបញ្ចូលសំឡេង (Start Dubbing)")
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_confirm)

        root.addLayout(btn_box)

    def _on_voice_type_toggled(self):
        is_clone = self.rb_clone.isChecked()
        self.combo_ai.setEnabled(not is_clone)
        self.combo_clone.setEnabled(is_clone)

    def _populate_clone_voices(self, select_id: str = ""):
        self.combo_clone.clear()

        # 1. User Cloned Voices from SQLite
        try:
            cloned = self.db.get_cloned_voices()
            if cloned:
                for cv in cloned:
                    label = f"⭐ [សំឡេងពិតផ្ទាល់ខ្លួន] {cv['name']} ({cv.get('gender', 'voice')})"
                    self.combo_clone.addItem(label, f"clone_{cv['id']}")
        except Exception as e:
            print(f"[DubVoice] Load cloned voices error: {e}")

        # 2. Studio Human Presets
        for p_key, p_val in VoiceCloneEngine.HUMAN_PRESETS.items():
            label = f"{p_val.get('name', p_key)} — {p_val.get('name_en', '')}"
            self.combo_clone.addItem(label, p_key)

        if select_id:
            for i in range(self.combo_clone.count()):
                if self.combo_clone.itemData(i) == select_id:
                    self.combo_clone.setCurrentIndex(i)
                    break

    def _open_voice_clone_studio(self):
        """Opens VoiceCloneDialog and auto-selects newly created voice upon return"""
        dlg = VoiceCloneDialog(self.db, parent=self)
        if dlg.exec() == QDialog.Accepted:
            # Re-read cloned voices and auto-select latest
            cloned = self.db.get_cloned_voices()
            if cloned:
                latest = cloned[-1]
                target_key = f"clone_{latest['id']}"
                self._populate_clone_voices(select_id=target_key)
                self.rb_clone.setChecked(True)

    def get_selection(self) -> Tuple[str, str, str, bool]:
        """
        Returns:
            (voice_type, profile_key, voice_label, force_all)
            voice_type: 'ai' or 'clone'
            profile_key: 'female', 'male', 'clone_<id>', or 'human_*'
            voice_label: user visible label string
            force_all: bool (whether to redub all lines or only missing)
        """
        is_clone = self.rb_clone.isChecked()
        if is_clone:
            voice_type = "clone"
            profile_key = str(self.combo_clone.currentData() or "human_male_deep")
            voice_label = self.combo_clone.currentText()
        else:
            voice_type = "ai"
            profile_key = str(self.combo_ai.currentData() or "female")
            labels_map = {
                "female": "Female (Sreymom)",
                "male": "Male (Piseth)",
                "somleng_female": "Somleng Khmer Female (Telecom)",
                "somleng_male": "Somleng Khmer Male (Telecom)",
            }
            voice_label = labels_map.get(profile_key, "Female (Sreymom)")

        force_all = self.rb_all.isChecked() if self.rb_all is not None else False
        return voice_type, profile_key, voice_label, force_all
