# -*- coding: utf-8 -*-
"""
ui/dialogs/speaker_mapper_dialog.py
Modal Dialog mapping detected speakers (SPEAKER_00, SPEAKER_01, SPEAKER_02, NARRATOR)
to distinct TTS voices, pitch, and speed with a 'Test Voice' preview button.
"""

import tempfile
from pathlib import Path
from typing import Dict, Any, List
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QPushButton, QLabel
)

from core.tts_engine import KhmerTTSEngine
from core.recap_dubbing.voice_fx import VoiceFXProcessor


class SpeakerMapperDialog(QDialog):
    """
    Speaker Role to TTS Voice, Rate & Pitch Mapping Dialog.
    """

    speaker_map_saved = Signal(dict)

    VOICE_CHOICES = [
        ("Female — Sreymom (km-KH-SreymomNeural)", "km-KH-SreymomNeural"),
        ("Male — Piseth (km-KH-PisethNeural)", "km-KH-PisethNeural"),
        ("Chinese Male — Yunxi (zh-CN-YunxiNeural)", "zh-CN-YunxiNeural"),
        ("English Male — Andrew (en-US-AndrewNeural)", "en-US-AndrewNeural"),
    ]

    RATE_CHOICES = ["-15%", "-10%", "-5%", "+0%", "+5%", "+10%", "+15%", "+20%"]
    PITCH_CHOICES = ["-6Hz", "-4Hz", "-2Hz", "+0Hz", "+2Hz", "+4Hz", "+6Hz"]

    def __init__(
        self,
        speaker_map: Dict[str, Dict[str, Any]] = None,
        detected_speakers: List[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("🎙️ Multi-Speaker Voice Role Mapper")
        self.resize(680, 360)

        self.speaker_map = dict(VoiceFXProcessor.DEFAULT_SPEAKER_MAP)
        if speaker_map:
            self.speaker_map.update(speaker_map)
        for spk in detected_speakers or []:
            if spk and spk not in self.speaker_map:
                self.speaker_map[spk] = {"voice": "km-KH-SreymomNeural", "rate": "+0%", "pitch": "+0Hz"}

        self.tts_engine = KhmerTTSEngine()
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        lbl_info = QLabel("Assign distinct AI voices, speaking rates, and pitches to each detected character or narrator:")
        lbl_info.setStyleSheet("color: #9CA3AF; font-weight: 600;")
        layout.addWidget(lbl_info)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Speaker ID", "Assigned TTS Voice", "Speed / Rate", "Pitch", "Preview"])
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 125)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 95)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 95)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 100)
        layout.addWidget(self.table, 1)

        self._populate_rows()

        btn_bar = QHBoxLayout()
        btn_add_spk = QPushButton("+ Add Speaker Role")
        btn_add_spk.clicked.connect(self._on_add_speaker)
        btn_bar.addWidget(btn_add_spk)
        btn_bar.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(btn_cancel)

        btn_save = QPushButton("Save Speaker Mapping")
        btn_save.setObjectName("PrimaryCTA")
        btn_save.clicked.connect(self._on_save)
        btn_bar.addWidget(btn_save)
        layout.addLayout(btn_bar)

    def _populate_rows(self) -> None:
        speakers = list(self.speaker_map.keys())
        self.table.setRowCount(len(speakers))
        for r, spk in enumerate(speakers):
            cfg = self.speaker_map[spk]
            self._insert_row_widgets(r, spk, cfg)

    def _insert_row_widgets(self, row: int, spk: str, cfg: Dict[str, Any]) -> None:
        spk_item = QTableWidgetItem(spk)
        spk_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, spk_item)

        v_combo = QComboBox()
        for label, vid in self.VOICE_CHOICES:
            v_combo.addItem(label, vid)
        saved_v = cfg.get("voice", "km-KH-SreymomNeural")
        for i in range(v_combo.count()):
            if v_combo.itemData(i) == saved_v:
                v_combo.setCurrentIndex(i)
                break
        self.table.setCellWidget(row, 1, v_combo)

        r_combo = QComboBox()
        r_combo.addItems(self.RATE_CHOICES)
        r_combo.setCurrentText(str(cfg.get("rate", "+0%")))
        self.table.setCellWidget(row, 2, r_combo)

        p_combo = QComboBox()
        p_combo.addItems(self.PITCH_CHOICES)
        p_combo.setCurrentText(str(cfg.get("pitch", "+0Hz")))
        self.table.setCellWidget(row, 3, p_combo)

        btn_test = QPushButton("▶ Test Voice")
        btn_test.clicked.connect(lambda _checked=False, idx=row: self._test_row_voice(idx))
        self.table.setCellWidget(row, 4, btn_test)

    def _on_add_speaker(self) -> None:
        r = self.table.rowCount()
        new_spk = f"SPEAKER_{r:02d}"
        self.table.insertRow(r)
        self._insert_row_widgets(r, new_spk, {"voice": "km-KH-SreymomNeural", "rate": "+0%", "pitch": "+0Hz"})

    def _test_row_voice(self, row: int) -> None:
        v_combo: QComboBox = self.table.cellWidget(row, 1)
        voice_id = v_combo.currentData() if v_combo else "km-KH-SreymomNeural"
        tmp_wav = str(Path(tempfile.gettempdir()) / f"test_spk_{row}.wav")
        self.tts_engine.generate_clip(
            "សួស្តី! នេះគឺជាការសាកល្បងសំឡេងតួអង្គក្នុងកម្មវិធី Ai Summarai។",
            voice_id,
            2500,
            tmp_wav,
        )
        if Path(tmp_wav).exists():
            self.player.setSource(QUrl.fromLocalFile(tmp_wav))
            self.player.play()

    def get_mapping(self) -> Dict[str, Dict[str, str]]:
        mapping: Dict[str, Dict[str, str]] = {}
        for r in range(self.table.rowCount()):
            spk_it = self.table.item(r, 0)
            v_combo: QComboBox = self.table.cellWidget(r, 1)
            r_combo: QComboBox = self.table.cellWidget(r, 2)
            p_combo: QComboBox = self.table.cellWidget(r, 3)
            if spk_it and spk_it.text().strip():
                mapping[spk_it.text().strip()] = {
                    "voice": str(v_combo.currentData() if v_combo else "km-KH-SreymomNeural"),
                    "rate": str(r_combo.currentText() if r_combo else "+0%"),
                    "pitch": str(p_combo.currentText() if p_combo else "+0Hz"),
                }
        return mapping

    def _on_save(self) -> None:
        self.speaker_map = self.get_mapping()
        self.speaker_map_saved.emit(self.speaker_map)
        self.accept()
