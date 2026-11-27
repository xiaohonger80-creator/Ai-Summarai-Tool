import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QIcon, QFont, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QSlider,
    QComboBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFrame,
    QGroupBox,
    QFormLayout,
    QSplitter,
)

from core.database import Database
from core.tts_engine import KhmerTTSEngine
from core.voice_clone_engine import VoiceCloneEngine


class AnalyzeWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, audio_path: str):
        super().__init__()
        self.audio_path = audio_path

    def run(self):
        try:
            res = VoiceCloneEngine.analyze_audio_sample(self.audio_path)
            self.finished.emit(res)
        except Exception as e:
            self.failed.emit(str(e))


class TestVoiceWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, text: str, voice_cfg: dict, out_wav: str, db: Database):
        super().__init__()
        self.text = text
        self.voice_cfg = voice_cfg
        self.out_wav = out_wav
        self.db = db

    def run(self):
        try:
            tts = KhmerTTSEngine()
            fx = self.voice_cfg.get("fx") or VoiceCloneEngine.build_acoustic_filter(
                pitch_shift_hz=self.voice_cfg.get("pitch_shift", 0),
                formant_shift=self.voice_cfg.get("formant_shift", 1.0),
                warmth=self.voice_cfg.get("warmth", 1.2),
                brightness=self.voice_cfg.get("brightness", 1.1),
            )
            profile_key = "_temp_preview_voice"
            tts.VOICE_PROFILES[profile_key] = {
                "label_en": "Temp Preview",
                "label_kh": "សំឡេងសាកល្បង",
                "voice": self.voice_cfg.get("base_voice", "km-KH-PisethNeural"),
                "pitch": f"{self.voice_cfg.get('pitch_shift', 0):+d}Hz",
                "rate": "+0%",
                "fx": fx,
            }
            tts.generate_clip(self.text, profile_key, 4500, self.out_wav, db=self.db)
            if Path(self.out_wav).exists() and Path(self.out_wav).stat().st_size > 500:
                self.finished.emit(self.out_wav)
            else:
                self.failed.emit("មិនអាចបង្កើតឯកសារសំឡេងសាកល្បងបានទេ!")
        except Exception as e:
            self.failed.emit(str(e))


class VoiceCloneDialog(QDialog):
    """
    ផ្ទាំង Voice Clone Studio (បន្ទប់ក្លូន និងបង្កើតសំឡេងមនុស្សពិតខ្មែរ)
    """

    voice_saved = Signal(str)  # បញ្ជូន voice_id ឬឈ្មោះសំឡេងដែលទើបតែរក្សាទុក

    def __init__(self, db: Database, parent=None, lang: str = "kh"):
        super().__init__(parent)
        self.db = db
        self.lang = lang
        self.sample_audio_path = ""
        self.preview_wav_path = str(Path("data/_temp_voice_preview.wav").resolve())

        # Media player សម្រាប់ preview សំឡេង
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)

        self._init_ui()
        self._load_saved_voices()

    def _init_ui(self):
        kh = self.lang == "kh"
        self.setWindowTitle("🎙️ Voice Clone Studio — ក្លូន និងបង្កើតសំឡេងមនុស្សពិតខ្មែរ" if kh else "🎙️ Voice Clone Studio")
        self.resize(920, 680)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Poppins', 'Khmer OS Battambang', 'Segoe UI';
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 14px;
                font-weight: 700;
                color: #38BDF8;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
            }
            QLineEdit, QComboBox {
                background: #1E293B;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 10px;
                color: #F8FAFC;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #38BDF8;
            }
            QPushButton {
                background: #1E293B;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 7px 14px;
                color: #F8FAFC;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #334155;
                border-color: #64748B;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #334155;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #0EA5E9;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #38BDF8;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            QTableWidget {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                gridline-color: #334155;
                color: #F1F5F9;
                font-size: 12px;
            }
            QTableWidget::item:selected {
                background-color: #0369A1;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #94A3B8;
                padding: 6px;
                border: none;
                font-weight: 600;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # Header Title Banner
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E293B, stop:1 #0F172A); border: 1px solid #334155; border-radius: 8px; padding: 10px 14px;")
        hdr_layout = QVBoxLayout(hdr_frame)
        hdr_layout.setContentsMargins(0, 0, 0, 0)
        hdr_layout.setSpacing(4)

        lbl_title = QLabel("🎙️ Voice Clone Studio — ក្លូនសំឡេងមនុស្សពិត ជំនួសសំឡេង AI" if kh else "🎙️ Voice Clone Studio — Real Human Voice Cloning")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #38BDF8;")
        lbl_desc = QLabel(
            "អ្នកអាច Upload ឯកសារសំឡេងមនុស្សពិត ឬថតសំឡេង ដើម្បីបង្កើតសំឡេងតួអង្គខ្មែរគ្រប់វ័យ និងគ្រប់ចរិត (ស្រី ប្រុស ក្មេង ចាស់) ដោយមិនប្រើសំឡេង AI ធម្មតា!"
            if kh else
            "Clone any real human voice from audio files or recordings to replace default robot AI voices with realistic Cambodian voices!"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 11px; color: #94A3B8;")
        hdr_layout.addWidget(lbl_title)
        hdr_layout.addWidget(lbl_desc)
        main_layout.addWidget(hdr_frame)

        # Splitter between Editor and Saved List
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ==========================================
        # LEFT PANE: VOICE CREATOR & CONTROLS
        # ==========================================
        left_widget = QFrame()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)

        # 1. Reference Audio Group
        grp_sample = QGroupBox("១. ឯកសារសំឡេងគំរូមនុស្សពិត (Reference Voice Audio)" if kh else "1. Reference Audio Sample")
        sample_layout = QVBoxLayout(grp_sample)
        sample_layout.setSpacing(8)

        row_file = QHBoxLayout()
        self.lbl_sample_path = QLabel("មិនទាន់បានជ្រើសរើសឯកសារ (.mp3, .wav)" if kh else "No sample file selected")
        self.lbl_sample_path.setStyleSheet("color: #94A3B8; font-style: italic;")
        btn_upload = QPushButton("📂 ជ្រើសរើសឯកសារ..." if kh else "📂 Browse File...")
        btn_upload.setStyleSheet("background-color: #0284C7; color: white;")
        btn_upload.clicked.connect(self._browse_sample_file)

        btn_play_sample = QPushButton("▶️ ស្តាប់សំឡេងដើម" if kh else "▶️ Play Sample")
        btn_play_sample.clicked.connect(self._play_sample_audio)

        row_file.addWidget(self.lbl_sample_path, 1)
        row_file.addWidget(btn_upload)
        row_file.addWidget(btn_play_sample)
        sample_layout.addLayout(row_file)

        self.btn_auto_analyze = QPushButton("⚡ វិភាគលក្ខណៈសំឡេងស្វ័យប្រវត្តិ (Auto-Detect Pitch & Tone)" if kh else "⚡ Auto-Detect Pitch & Tone")
        self.btn_auto_analyze.setStyleSheet("background-color: #059669; color: white; font-weight: 700;")
        self.btn_auto_analyze.clicked.connect(self._analyze_sample)
        sample_layout.addWidget(self.btn_auto_analyze)

        left_layout.addWidget(grp_sample)

        # 2. Voice Parameters Group
        grp_params = QGroupBox("២. កំណត់លក្ខណៈសំឡេង (Vocal Timbre & Resonance)" if kh else "2. Vocal Timbre & Pitch Settings")
        form = QFormLayout(grp_params)
        form.setSpacing(10)

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("ឧ. សំឡេង ពូណយ, សំឡេង តួឯកស្រី, សំឡេង ខ្ញុំផ្ទាល់..." if kh else "e.g. My Real Voice, Hero Male...")
        form.addRow("ឈ្មោះសំឡេង៖" if kh else "Voice Name:", self.txt_name)

        self.combo_base = QComboBox()
        self.combo_base.addItem("សំឡេងប្រុស (Piseth Neural)", "km-KH-PisethNeural")
        self.combo_base.addItem("សំឡេងស្រី (Sreymom Neural)", "km-KH-SreymomNeural")
        form.addRow("សំឡេងគោល៖" if kh else "Base Voice:", self.combo_base)

        # Pitch Shift Slider
        row_pitch = QHBoxLayout()
        self.slider_pitch = QSlider(Qt.Orientation.Horizontal)
        self.slider_pitch.setRange(-35, 35)
        self.slider_pitch.setValue(0)
        self.lbl_pitch_val = QLabel("0 Hz")
        self.lbl_pitch_val.setFixedWidth(50)
        self.slider_pitch.valueChanged.connect(lambda v: self.lbl_pitch_val.setText(f"{v:+d} Hz"))
        row_pitch.addWidget(self.slider_pitch, 1)
        row_pitch.addWidget(self.lbl_pitch_val)
        form.addRow("គ្រលរ / ស្រាល (Pitch):" if kh else "Pitch Shift:", row_pitch)

        # Chest Warmth Slider
        row_warmth = QHBoxLayout()
        self.slider_warmth = QSlider(Qt.Orientation.Horizontal)
        self.slider_warmth.setRange(70, 180)
        self.slider_warmth.setValue(125)
        self.lbl_warmth_val = QLabel("1.25x")
        self.lbl_warmth_val.setFixedWidth(50)
        self.slider_warmth.valueChanged.connect(lambda v: self.lbl_warmth_val.setText(f"{v/100:.2f}x"))
        row_warmth.addWidget(self.slider_warmth, 1)
        row_warmth.addWidget(self.lbl_warmth_val)
        form.addRow("ភាពកក់ក្តៅទ្រូង (Warmth):" if kh else "Chest Warmth:", row_warmth)

        # Clarity / Presence Slider
        row_clarity = QHBoxLayout()
        self.slider_clarity = QSlider(Qt.Orientation.Horizontal)
        self.slider_clarity.setRange(70, 160)
        self.slider_clarity.setValue(115)
        self.lbl_clarity_val = QLabel("1.15x")
        self.lbl_clarity_val.setFixedWidth(50)
        self.slider_clarity.valueChanged.connect(lambda v: self.lbl_clarity_val.setText(f"{v/100:.2f}x"))
        row_clarity.addWidget(self.slider_clarity, 1)
        row_clarity.addWidget(self.lbl_clarity_val)
        form.addRow("ភាពច្បាស់ (Clarity):" if kh else "Speech Clarity:", row_clarity)

        # Formant Shift
        row_formant = QHBoxLayout()
        self.slider_formant = QSlider(Qt.Orientation.Horizontal)
        self.slider_formant.setRange(75, 130)
        self.slider_formant.setValue(100)
        self.lbl_formant_val = QLabel("1.00x")
        self.lbl_formant_val.setFixedWidth(50)
        self.slider_formant.valueChanged.connect(lambda v: self.lbl_formant_val.setText(f"{v/100:.2f}x"))
        row_formant.addWidget(self.slider_formant, 1)
        row_formant.addWidget(self.lbl_formant_val)
        form.addRow("ទំហំបំពង់ក (Formant):" if kh else "Formant Shift:", row_formant)

        # Optional Cloud Voice ID (ElevenLabs)
        self.txt_api_id = QLineEdit()
        self.txt_api_id.setPlaceholderText("ស្រេចចិត្ត (Optional: ElevenLabs Voice ID)" if kh else "Optional: Cloud Voice ID")
        form.addRow("Cloud Voice ID:" if kh else "Cloud Voice ID:", self.txt_api_id)

        left_layout.addWidget(grp_params)

        # 3. Test & Save Row
        grp_test = QGroupBox("៣. សាកល្បងនិយាយ និងរក្សាទុក (Live Test & Save)" if kh else "3. Test Sample & Save")
        test_layout = QVBoxLayout(grp_test)
        test_layout.setSpacing(8)

        self.txt_test_sentence = QLineEdit("ជំរាបសួរ! នេះជាសំឡេងខ្មែរពិតដែលបានក្លូនរួច សម្រាប់បញ្ចាំងក្នុងខ្សែភាពយន្ត។")
        test_layout.addWidget(self.txt_test_sentence)

        row_test_btns = QHBoxLayout()
        self.btn_test = QPushButton("🔊 សាកល្បងនិយាយ (Test Voice)" if kh else "🔊 Test Voice")
        self.btn_test.setStyleSheet("background-color: #0284C7; color: white; font-weight: 700; padding: 8px;")
        self.btn_test.clicked.connect(self._test_voice)

        self.btn_save_voice = QPushButton("💾 រក្សាទុកសំឡេងនេះ (Save Voice)" if kh else "💾 Save Voice")
        self.btn_save_voice.setStyleSheet("background-color: #10B981; color: white; font-weight: 700; padding: 8px;")
        self.btn_save_voice.clicked.connect(self._save_voice)

        row_test_btns.addWidget(self.btn_test)
        row_test_btns.addWidget(self.btn_save_voice)
        test_layout.addLayout(row_test_btns)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #38BDF8; font-size: 11px;")
        test_layout.addWidget(self.lbl_status)

        left_layout.addWidget(grp_test)
        splitter.addWidget(left_widget)

        # ==========================================
        # RIGHT PANE: SAVED VOICES & PRESETS
        # ==========================================
        right_widget = QFrame()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        lbl_saved_title = QLabel("📋 បញ្ជីសំឡេងមនុស្សពិត និងសំឡេងក្លូន (Voice Library)" if kh else "📋 Voice Library")
        lbl_saved_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #38BDF8;")
        right_layout.addWidget(lbl_saved_title)

        self.tbl_voices = QTableWidget(0, 4)
        self.tbl_voices.setHorizontalHeaderLabels(
            ["ID", "ឈ្មោះសំឡេង", "កម្រិត Pitch", "សកម្មភាព"] if kh else
            ["ID", "Voice Name", "Pitch", "Actions"]
        )
        self.tbl_voices.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_voices.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_voices.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_voices.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.tbl_voices)

        row_list_btns = QHBoxLayout()
        btn_refresh = QPushButton("🔄 Refresh" if not kh else "🔄 ផ្ទុកឡើងវិញ")
        btn_refresh.clicked.connect(self._load_saved_voices)

        btn_select_voice = QPushButton("✅ ជ្រើសរើសប្រើសំឡេងនេះ (Use Selected)" if kh else "✅ Use Selected")
        btn_select_voice.setStyleSheet("background-color: #059669; color: white; font-weight: 700;")
        btn_select_voice.clicked.connect(self._use_selected_voice)

        row_list_btns.addWidget(btn_refresh)
        row_list_btns.addWidget(btn_select_voice)
        right_layout.addLayout(row_list_btns)

        splitter.addWidget(right_widget)
        splitter.setSizes([480, 400])
        main_layout.addWidget(splitter, 1)

        # Bottom Close Button
        btn_close_row = QHBoxLayout()
        btn_close_row.addStretch()
        btn_close = QPushButton("បិទ (Close)" if kh else "Close")
        btn_close.clicked.connect(self.accept)
        btn_close_row.addWidget(btn_close)
        main_layout.addLayout(btn_close_row)

    def _browse_sample_file(self):
        kh = self.lang == "kh"
        path, _ = QFileDialog.getOpenFileName(
            self,
            "ជ្រើសរើសឯកសារសំឡេងគំរូ" if kh else "Select Reference Voice Audio",
            "",
            "Audio Files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)",
        )
        if path:
            self.sample_audio_path = path
            self.lbl_sample_path.setText(f"📁 {Path(path).name}")
            self.lbl_sample_path.setStyleSheet("color: #38BDF8; font-weight: 600;")
            if not self.txt_name.text().strip():
                clean_stem = Path(path).stem.replace("_", " ").title()
                self.txt_name.setText(f"សំឡេង {clean_stem}")

    def _play_sample_audio(self):
        if not self.sample_audio_path or not Path(self.sample_audio_path).exists():
            kh = self.lang == "kh"
            QMessageBox.warning(self, "Audio Sample", "សូមជ្រើសរើសឯកសារសំឡេងគំរូជាមុនសិន!" if kh else "Please select an audio sample first!")
            return
        self.player.setSource(QUrl.fromLocalFile(str(Path(self.sample_audio_path).resolve())))
        self.player.play()

    def _analyze_sample(self):
        kh = self.lang == "kh"
        if not self.sample_audio_path or not Path(self.sample_audio_path).exists():
            QMessageBox.warning(self, "Analyze", "សូមជ្រើសរើសឯកសារសំឡេងគំរូជាមុនសិន!" if kh else "Please select an audio sample first!")
            return

        self.btn_auto_analyze.setEnabled(False)
        self.lbl_status.setText("⏳ កំពុងវិភាគប្រេកង់ និងពណ៌សំឡេង..." if kh else "⏳ Analyzing pitch & vocal timbre...")

        self._analyzer = AnalyzeWorker(self.sample_audio_path)
        self._analyzer.finished.connect(self._on_analyze_finished)
        self._analyzer.failed.connect(self._on_analyze_failed)
        self._analyzer.start()

    def _on_analyze_finished(self, res: dict):
        self.btn_auto_analyze.setEnabled(True)
        kh = self.lang == "kh"
        pitch_hz = res.get("detected_pitch_hz", 150)
        gender = res.get("gender", "male")
        p_shift = res.get("pitch_shift", 0)
        f_shift = res.get("formant_shift", 1.0)
        warmth = res.get("warmth", 1.2)
        clarity = res.get("brightness", 1.1)

        # កំណត់លើផ្ទាំង Controls
        idx = self.combo_base.findData(res.get("base_voice", "km-KH-PisethNeural"))
        if idx >= 0:
            self.combo_base.setCurrentIndex(idx)

        self.slider_pitch.setValue(int(p_shift))
        self.slider_formant.setValue(int(f_shift * 100))
        self.slider_warmth.setValue(int(warmth * 100))
        self.slider_clarity.setValue(int(clarity * 100))

        gender_str = "មនុស្សស្រី (Female)" if gender == "female" else "មនុស្សប្រុស (Male)"
        msg = f"✅ បានវិភាគជោគជ័យ! ប្រេកង់ F0: {pitch_hz}Hz ({gender_str})" if kh else f"✅ Analysis complete! F0: {pitch_hz}Hz ({gender})"
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #10B981; font-weight: 700;")

    def _on_analyze_failed(self, err: str):
        self.btn_auto_analyze.setEnabled(True)
        self.lbl_status.setText(f"❌ កំហុសវិភាគ៖ {err}")
        self.lbl_status.setStyleSheet("color: #EF4444;")

    def _get_current_voice_config(self) -> dict:
        return {
            "name": self.txt_name.text().strip() or "Custom Cloned Voice",
            "base_voice": self.combo_base.currentData(),
            "pitch_shift": self.slider_pitch.value(),
            "formant_shift": self.slider_formant.value() / 100.0,
            "warmth": self.slider_warmth.value() / 100.0,
            "brightness": self.slider_clarity.value() / 100.0,
            "api_voice_id": self.txt_api_id.text().strip(),
            "sample_path": self.sample_audio_path,
        }

    def _test_voice(self):
        kh = self.lang == "kh"
        text = self.txt_test_sentence.text().strip()
        if not text:
            text = "ជំរាបសួរ! នេះជាសំឡេងខ្មែរពិតដែលបានក្លូនរួច។"

        self.btn_test.setEnabled(False)
        self.lbl_status.setText("⏳ កំពុងបង្កើតសំឡេងសាកល្បង..." if kh else "⏳ Synthesizing test audio...")

        cfg = self._get_current_voice_config()
        self._tester = TestVoiceWorker(text, cfg, self.preview_wav_path, self.db)
        self._tester.finished.connect(self._on_test_finished)
        self._tester.failed.connect(self._on_test_failed)
        self._tester.start()

    def _on_test_finished(self, wav_path: str):
        self.btn_test.setEnabled(True)
        kh = self.lang == "kh"
        self.lbl_status.setText("🔊 កំពុងចាក់សំឡេងសាកល្បង..." if kh else "🔊 Playing sample audio...")
        self.lbl_status.setStyleSheet("color: #38BDF8; font-weight: 600;")
        self.player.setSource(QUrl.fromLocalFile(wav_path))
        self.player.play()

    def _on_test_failed(self, err: str):
        self.btn_test.setEnabled(True)
        self.lbl_status.setText(f"❌ កំហុស៖ {err}")
        self.lbl_status.setStyleSheet("color: #EF4444;")

    def _save_voice(self):
        kh = self.lang == "kh"
        name = self.txt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Save Voice", "សូមបញ្ចូលឈ្មោះសំឡេងជាមុនសិន!" if kh else "Please enter voice name!")
            return

        cfg = self._get_current_voice_config()
        dest_sample = ""
        if self.sample_audio_path and Path(self.sample_audio_path).exists():
            v_dir = Path("data/cloned_voices")
            v_dir.mkdir(parents=True, exist_ok=True)
            dest_sample = str(v_dir / f"sample_{int(time.time())}_{Path(self.sample_audio_path).name}")
            try:
                shutil.copy2(self.sample_audio_path, dest_sample)
            except Exception:
                dest_sample = self.sample_audio_path

        fx = VoiceCloneEngine.build_acoustic_filter(
            pitch_shift_hz=cfg["pitch_shift"],
            formant_shift=cfg["formant_shift"],
            warmth=cfg["warmth"],
            brightness=cfg["brightness"],
        )

        new_id = self.db.add_cloned_voice(
            name=name,
            sample_path=dest_sample,
            gender="male" if "Piseth" in cfg["base_voice"] else "female",
            base_voice=cfg["base_voice"],
            pitch_shift=cfg["pitch_shift"],
            formant_shift=cfg["formant_shift"],
            warmth=cfg["warmth"],
            brightness=cfg["brightness"],
            tempo_rate=1.0,
            voice_color="custom",
            fx=fx,
            api_voice_id=cfg["api_voice_id"],
            is_preset=0,
        )

        self._load_saved_voices()
        self.lbl_status.setText(f"✅ បានរក្សាទុកសំឡេង '{name}' ជោគជ័យ!" if kh else f"✅ Voice '{name}' saved successfully!")
        self.lbl_status.setStyleSheet("color: #10B981; font-weight: 700;")
        self.voice_saved.emit(f"clone_{new_id}")
        QMessageBox.information(
            self,
            "Saved" if not kh else "ជោគជ័យ",
            f"បានរក្សាទុកសំឡេង '{name}' ជោគជ័យ!\nអ្នកអាចជ្រើសរើសសំឡេងនេះក្នុងតារាង Dubbing បានភ្លាមៗ។" if kh else f"Voice '{name}' saved successfully!"
        )

    def _load_saved_voices(self):
        kh = self.lang == "kh"
        self.tbl_voices.setRowCount(0)

        # 1. Add 10 Human Presets
        for p_key, p_val in VoiceCloneEngine.HUMAN_PRESETS.items():
            r = self.tbl_voices.rowCount()
            self.tbl_voices.insertRow(r)

            id_item = QTableWidgetItem("Preset")
            id_item.setForeground(QColor("#64748B"))
            self.tbl_voices.setItem(r, 0, id_item)

            name_item = QTableWidgetItem(p_val.get("name", p_key) if kh else p_val.get("name_en", p_key))
            name_item.setData(Qt.ItemDataRole.UserRole, p_key)
            self.tbl_voices.setItem(r, 1, name_item)

            pitch_item = QTableWidgetItem(f"{p_val.get('pitch_shift', 0):+d} Hz")
            self.tbl_voices.setItem(r, 2, pitch_item)

            btn_test_p = QPushButton("▶️ Play")
            btn_test_p.setFixedHeight(24)
            btn_test_p.clicked.connect(lambda _, k=p_key: self._test_preset_voice(k))
            self.tbl_voices.setCellWidget(r, 3, btn_test_p)

        # 2. Add User Cloned Voices
        cloned = self.db.get_cloned_voices()
        for cv in cloned:
            r = self.tbl_voices.rowCount()
            self.tbl_voices.insertRow(r)

            id_item = QTableWidgetItem(str(cv["id"]))
            id_item.setForeground(QColor("#38BDF8"))
            self.tbl_voices.setItem(r, 0, id_item)

            name_item = QTableWidgetItem(f"👤 {cv['name']}")
            name_item.setData(Qt.ItemDataRole.UserRole, f"clone_{cv['id']}")
            self.tbl_voices.setItem(r, 1, name_item)

            pitch_item = QTableWidgetItem(f"{cv.get('pitch_shift', 0):+d} Hz")
            self.tbl_voices.setItem(r, 2, pitch_item)

            act_widget = QFrame()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(0, 0, 0, 0)
            act_layout.setSpacing(4)

            btn_test_c = QPushButton("▶️")
            btn_test_c.setFixedSize(26, 24)
            btn_test_c.clicked.connect(lambda _, vid=cv["id"]: self._test_cloned_db_voice(vid))

            btn_del = QPushButton("🗑️")
            btn_del.setFixedSize(26, 24)
            btn_del.setStyleSheet("background-color: #991B1B; color: white;")
            btn_del.clicked.connect(lambda _, vid=cv["id"]: self._delete_voice(vid))

            act_layout.addWidget(btn_test_c)
            act_layout.addWidget(btn_del)
            self.tbl_voices.setCellWidget(r, 3, act_widget)

    def _test_preset_voice(self, preset_key: str):
        p_val = VoiceCloneEngine.HUMAN_PRESETS.get(preset_key, {})
        cfg = {
            "name": p_val.get("name", preset_key),
            "base_voice": p_val.get("base_voice", "km-KH-PisethNeural"),
            "pitch_shift": p_val.get("pitch_shift", 0),
            "fx": p_val.get("fx", ""),
        }
        text = self.txt_test_sentence.text().strip() or "ជំរាបសួរ! នេះជាសំឡេងមនុស្សពិតខ្មែរ។"
        self._tester = TestVoiceWorker(text, cfg, self.preview_wav_path, self.db)
        self._tester.finished.connect(self._on_test_finished)
        self._tester.failed.connect(self._on_test_failed)
        self._tester.start()

    def _test_cloned_db_voice(self, vid: int):
        cv = self.db.get_cloned_voice(vid)
        if not cv:
            return
        cfg = {
            "name": cv["name"],
            "base_voice": cv["base_voice"],
            "pitch_shift": cv["pitch_shift"],
            "formant_shift": cv["formant_shift"],
            "warmth": cv["warmth"],
            "brightness": cv["brightness"],
            "fx": cv.get("fx", ""),
            "api_voice_id": cv.get("api_voice_id", ""),
        }
        text = self.txt_test_sentence.text().strip() or "ជំរាបសួរ! នេះជាសំឡេងមនុស្សពិតដែលបានក្លូនរួច។"
        self._tester = TestVoiceWorker(text, cfg, self.preview_wav_path, self.db)
        self._tester.finished.connect(self._on_test_finished)
        self._tester.failed.connect(self._on_test_failed)
        self._tester.start()

    def _delete_voice(self, vid: int):
        kh = self.lang == "kh"
        ret = QMessageBox.question(
            self,
            "Delete Voice" if not kh else "លុបសំឡេង",
            "តើអ្នកពិតជាចង់លុបសំឡេងក្លូននេះចេញមែនទេ?" if kh else "Are you sure you want to delete this cloned voice?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.db.delete_cloned_voice(vid)
            self._load_saved_voices()

    def _use_selected_voice(self):
        r = self.tbl_voices.currentRow()
        if r < 0:
            kh = self.lang == "kh"
            QMessageBox.warning(self, "Select Voice", "សូមចុចជ្រើសរើសជួរសំឡេងណាមួយជាមុនសិន!" if kh else "Please select a voice row first!")
            return
        name_item = self.tbl_voices.item(r, 1)
        if name_item:
            v_code = name_item.data(Qt.ItemDataRole.UserRole)
            self.voice_saved.emit(v_code)
            self.accept()
