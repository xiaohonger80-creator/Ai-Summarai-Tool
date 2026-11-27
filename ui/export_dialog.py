# -*- coding: utf-8 -*-
"""
Ai Summarai — Video Export Studio Dialog
-----------------------------------------
Features:
- Live video player to preview the dubbed video before exporting
- Resolution selector: 2K (1440p), 1080p (FHD), 720p (HD), or Original
- Quality & Bitrate options (High, Balanced, Small Size)
- FPS selection (Original, 60 FPS, 30 FPS)
- GPU Hardware Acceleration indicator
- Output path picker with auto-suffix updates
- Real-time progress bar and one-click 'Open Folder' / 'Play Video' buttons
"""

import os
import subprocess
import threading
import traceback
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QFont, QColor, QPalette
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QLineEdit, QProgressBar, QFileDialog, QFrame, QMessageBox,
    QSlider, QSizePolicy, QCheckBox, QScrollArea, QListView
)
from core.media_engine import MediaEngine
from core.lut_presets import LUT_PRESETS
from core.system_monitor import get_hardware_profile


class ExportWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, task_fn):
        super().__init__()
        self.task_fn = task_fn

    def run(self):
        try:
            msg = self.task_fn(self.progress.emit)
            self.finished_ok.emit(str(msg or ""))
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e))


class ExportVideoDialog(QDialog):
    workflow_progress = Signal(int, str)
    workflow_finished = Signal(str)
    workflow_failed = Signal(str)

    def __init__(
        self,
        parent=None,
        project_id: int = 0,
        video_path: str = "",
        preview_video_path: str = "",
        db=None,
        lang: str = "kh",
    ):
        super().__init__(parent)
        self.project_id = project_id
        self.video_path = video_path
        self.preview_video_path = preview_video_path or video_path
        self.db = db
        self.lang = lang
        self.exported_file_path = ""
        self._worker = None
        self._cancel_event = threading.Event()

        self.setWindowTitle("Ai Summarai — Video Export Studio (នាំចេញវីដេអូ)")
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            win_w = min(1080, max(920, int(geo.width() * 0.84)))
            win_h = min(750, max(600, int(geo.height() * 0.88)))
        else:
            win_w, win_h = 1060, 740
        self.setMinimumSize(920, 600)
        self.resize(win_w, win_h)
        self.setStyleSheet("""
            QDialog {
                background-color: #0B0D10;
                color: #F4F6FB;
            }
            QFrame#PanelCard {
                background-color: #12151B;
                border: 1px solid #252A36;
                border-radius: 8px;
            }
            QScrollArea#ExportSettingsScroll {
                background: transparent;
                border: none;
            }
            QScrollArea#ExportSettingsScroll QScrollBar:vertical {
                background: #12151B;
                width: 6px;
                margin: 2px 0;
                border-radius: 3px;
            }
            QScrollArea#ExportSettingsScroll QScrollBar::handle:vertical {
                background: #343B4C;
                min-height: 28px;
                border-radius: 3px;
            }
            QScrollArea#ExportSettingsScroll QScrollBar::handle:vertical:hover {
                background: #00E5FF;
            }
            QScrollArea#ExportSettingsScroll QScrollBar::add-line:vertical,
            QScrollArea#ExportSettingsScroll QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QLabel {
                color: #F4F6FB;
            }
            QComboBox {
                background-color: #181C24;
                color: #F4F6FB;
                border: 1px solid #343B4C;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 22px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBoxPrivateContainer {
                background-color: #161920;
                border: 1px solid #343B4C;
                border-radius: 6px;
            }
            QComboBox QAbstractItemView, QComboBox QListView {
                background-color: #161920;
                color: #F4F6FB;
                selection-background-color: #00E5FF;
                selection-color: #0B0D10;
                border: 1px solid #343B4C;
                outline: none;
                padding: 4px;
            }
            QComboBox QAbstractItemView::item, QComboBox QListView::item {
                background-color: #161920;
                color: #F4F6FB;
                padding: 6px 10px;
                min-height: 24px;
                border-radius: 4px;
            }
            QComboBox QAbstractItemView::item:hover,
            QComboBox QAbstractItemView::item:selected,
            QComboBox QListView::item:hover,
            QComboBox QListView::item:selected {
                background-color: #00E5FF;
                color: #0B0D10;
                font-weight: 700;
            }
            QLineEdit {
                background-color: #181C24;
                color: #F4F6FB;
                border: 1px solid #343B4C;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QCheckBox {
                spacing: 7px;
                padding: 2px 0px;
            }
            QProgressBar {
                background-color: #181C24;
                border: 1px solid #252A36;
                border-radius: 6px;
                text-align: center;
                color: #F4F6FB;
                font-weight: bold;
                height: 18px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00E5FF, stop:1 #10B981);
                border-radius: 5px;
            }
        """)

        # Probe video dimensions
        self.src_w, self.src_h = MediaEngine._probe_resolution(self.video_path) if self.video_path else (1080, 1920)
        self.is_portrait = (self.src_h > self.src_w)

        self._build_ui()
        self._apply_dark_combo_popups()
        self._init_preview_player()

    def _apply_dark_combo_popups(self):
        """Forces dark QListView + QPalette on every QComboBox popup so Windows never paints a white menu."""
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor("#161920"))
        pal.setColor(QPalette.Base, QColor("#161920"))
        pal.setColor(QPalette.AlternateBase, QColor("#1C212C"))
        pal.setColor(QPalette.Text, QColor("#F4F6FB"))
        pal.setColor(QPalette.WindowText, QColor("#F4F6FB"))
        pal.setColor(QPalette.Highlight, QColor("#00E5FF"))
        pal.setColor(QPalette.HighlightedText, QColor("#0B0D10"))
        popup_qss = (
            "QListView { background-color: #161920; color: #F4F6FB; border: 1px solid #343B4C; outline: none; padding: 3px; }"
            "QListView::item { background-color: #161920; color: #F4F6FB; padding: 6px 10px; min-height: 22px; border-radius: 4px; }"
            "QListView::item:hover, QListView::item:selected { background-color: #00E5FF; color: #0B0D10; font-weight: 700; }"
        )
        for cb in (
            self.cb_resolution, self.cb_quality, self.cb_fps,
            self.cb_encoder, self.cb_lut_preset, self.cb_anti_copyright_level,
        ):
            lv = QListView(cb)
            lv.setPalette(pal)
            lv.setStyleSheet(popup_qss)
            cb.setView(lv)
            cb.setPalette(pal)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # Header bar
        head_box = QHBoxLayout()
        title_lbl = QLabel("🎬 Video Export Studio (ផ្ទាំងកំណត់ការនាំចេញវីដេអូ)")
        title_lbl.setFont(QFont("Inter", 13, QFont.Bold))
        head_box.addWidget(title_lbl)
        head_box.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setStyleSheet("background: transparent; color: #8E95A5; font-size: 14px; font-weight: bold; border: none;")
        btn_close.clicked.connect(self.close)
        head_box.addWidget(btn_close)
        root.addLayout(head_box)

        # Main Split Content: Left = Video Preview, Right = Export Settings
        main_layout = QHBoxLayout()
        main_layout.setSpacing(14)

        # =====================================================================
        # 1. LEFT: LIVE VIDEO PREVIEW BEFORE EXPORT
        # =====================================================================
        left_card = QFrame()
        left_card.setObjectName("PanelCard")
        left_v = QVBoxLayout(left_card)
        left_v.setContentsMargins(12, 12, 12, 12)
        left_v.setSpacing(8)

        lbl_pv_title = QLabel("👁️ មើលវីដេអូសាកល្បងមុននឹង Export (Preview Before Export)")
        lbl_pv_title.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 11px;")
        left_v.addWidget(lbl_pv_title)

        # Video Player Widget
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("background-color: #000000; border-radius: 6px;")
        left_v.addWidget(self.video_widget, 1)

        # Player Controls Bar
        ctrl_box = QHBoxLayout()
        ctrl_box.setSpacing(8)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setFixedWidth(70)
        self.btn_play.setStyleSheet(
            "background: #181C24; border: 1px solid #343B4C; border-radius: 4px; padding: 4px 8px; color: #F4F6FB; font-weight: bold; font-size: 11px;"
        )
        self.btn_play.clicked.connect(self._toggle_playback)
        ctrl_box.addWidget(self.btn_play)

        self.slider_time = QSlider(Qt.Horizontal)
        self.slider_time.setRange(0, 1000)
        self.slider_time.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #252A36; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #00E5FF; border-radius: 2px; }
            QSlider::handle:horizontal { width: 12px; margin-top: -4px; margin-bottom: -4px; border-radius: 6px; background: #00E5FF; }
        """)
        self.slider_time.sliderMoved.connect(self._on_seek_moved)
        ctrl_box.addWidget(self.slider_time, 1)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setFont(QFont("JetBrains Mono", 9))
        self.lbl_time.setStyleSheet("color: #8E95A5;")
        ctrl_box.addWidget(self.lbl_time)

        left_v.addLayout(ctrl_box)

        # Video Metadata Badge
        aspect_str = "9:16 Portrait" if self.is_portrait else "16:9 Landscape"
        meta_box = QHBoxLayout()
        meta_box.setSpacing(6)
        lbl_meta = QLabel(f"📐 ទំហំដើម: {self.src_w}x{self.src_h} ({aspect_str})")
        lbl_meta.setStyleSheet("color: #8E95A5; font-size: 10px;")
        meta_box.addWidget(lbl_meta)
        meta_box.addStretch()

        left_v.addLayout(meta_box)
        main_layout.addWidget(left_card, 52)

        # =====================================================================
        # 2. RIGHT: EXPORT CONFIGURATION PANEL (Scrollable Settings + Pinned CTA)
        # =====================================================================
        right_card = QFrame()
        right_card.setObjectName("PanelCard")
        right_v = QVBoxLayout(right_card)
        right_v.setContentsMargins(14, 12, 14, 12)
        right_v.setSpacing(10)

        lbl_opt_title = QLabel("⚙️ កំណត់គុណភាពវីដេអូនាំចេញ (Export Settings)")
        lbl_opt_title.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px;")
        right_v.addWidget(lbl_opt_title)

        # Scrollable settings body so nothing ever gets squished on any screen height
        settings_scroll = QScrollArea()
        settings_scroll.setObjectName("ExportSettingsScroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setFrameShape(QFrame.NoFrame)

        settings_body = QWidget()
        settings_body.setStyleSheet("background: transparent;")
        s_v = QVBoxLayout(settings_body)
        s_v.setContentsMargins(0, 0, 6, 4)
        s_v.setSpacing(8)

        # 1. RESOLUTION SELECTOR (2k / 1080p / 720p / Original)
        lbl_res = QLabel("📐 កម្រិតច្បាស់វីដេអូ (Resolution):")
        lbl_res.setStyleSheet("font-weight: 600; font-size: 11px;")
        s_v.addWidget(lbl_res)

        self.cb_resolution = QComboBox()
        self.cb_resolution.setFixedHeight(32)
        if self.is_portrait:
            self.cb_resolution.addItem("1080p FHD - 1080x1920 (ស្តង់ដារ TikTok / Reels - Recommended)", "1080p")
            self.cb_resolution.addItem("2K QHD - 1440x2560 (កម្រិតខ្ពស់ Ultra HD)", "2k")
            self.cb_resolution.addItem("720p HD - 720x1280 (ទំហំស្រាល ល្បឿនលឿន)", "720p")
            self.cb_resolution.addItem(f"Original - {self.src_w}x{self.src_h} (គុណភាពដើម)", "original")
        else:
            self.cb_resolution.addItem("1080p FHD - 1920x1080 (ស្តង់ដារ YouTube FHD - Recommended)", "1080p")
            self.cb_resolution.addItem("2K QHD - 2560x1440 (កម្រិតខ្ពស់ 2K Ultra HD)", "2k")
            self.cb_resolution.addItem("720p HD - 1280x720 (ទំហំស្រាល ល្បឿនលឿន)", "720p")
            self.cb_resolution.addItem(f"Original - {self.src_w}x{self.src_h} (គុណភាពដើម)", "original")
        self.cb_resolution.currentIndexChanged.connect(self._on_settings_changed)
        s_v.addWidget(self.cb_resolution)

        # 2. QUALITY PRESET (Bitrate / CRF)
        lbl_qual = QLabel("💎 គុណភាពរូបភាព (Video Quality / Bitrate):")
        lbl_qual.setStyleSheet("font-weight: 600; font-size: 11px;")
        s_v.addWidget(lbl_qual)

        self.cb_quality = QComboBox()
        self.cb_quality.setFixedHeight(32)
        self.cb_quality.addItem("🚀 Ultra Fast / ល្បឿនលឿនបំផុត (GPU Acceleration / Fastest Export - 5x Speed)", "ultrafast")
        self.cb_quality.addItem("Balanced / ល្មមស្តង់ដារ (CRF 22 / 5.5 Mbps - Recommended)", "balanced")
        self.cb_quality.addItem("High Quality / គុណភាពខ្ពស់ (CRF 18 / 10 Mbps - Master)", "high")
        self.cb_quality.addItem("Small File Size / ទំហំតូចសន្សំទំហំ (CRF 26 / 3 Mbps)", "small")
        self.cb_quality.setCurrentIndex(1)
        s_v.addWidget(self.cb_quality)

        # 3. FRAME RATE (FPS)
        lbl_fps = QLabel("⚡ ល្បឿនរូបភាព (Frame Rate / FPS):")
        lbl_fps.setStyleSheet("font-weight: 600; font-size: 11px;")
        s_v.addWidget(lbl_fps)

        self.cb_fps = QComboBox()
        self.cb_fps.setFixedHeight(32)
        self.cb_fps.addItem("Auto (FPS ដើមនៃវីដេអូ)", "original")
        self.cb_fps.addItem("60 FPS (ចលនារលូន Smooth)", "60")
        self.cb_fps.addItem("30 FPS (ស្តង់ដារ Standard)", "30")
        s_v.addWidget(self.cb_fps)

        # 4. HARDWARE ACCELERATION ENCODER & LOW-SPEC AUTO-BALANCE
        hw_prof = get_hardware_profile()
        lbl_enc = QLabel(f"🚀 បច្ចេកវិទ្យា Render (Video Encoder) • {hw_prof['label']}:")
        lbl_enc.setStyleSheet("font-weight: 600; font-size: 11px;")
        s_v.addWidget(lbl_enc)

        self.cb_encoder = QComboBox()
        self.cb_encoder.setFixedHeight(32)
        enc_label = MediaEngine.get_encoder_label()
        self.cb_encoder.addItem(f"Auto ({enc_label} + CPU Auto-Fallback)", "auto")
        self.cb_encoder.addItem("CPU: Multi-Core libx264 (Universal Compatibility)", "cpu")
        s_v.addWidget(self.cb_encoder)

        # 4A. 20+ ADJUSTMENT & LUT PRESET SELECTOR
        lbl_lut = QLabel("🎨 Adjustments & LUT Preset (ការកែសម្រួលពណ៌ ២០+ ប្រភេទ):")
        lbl_lut.setStyleSheet("font-weight: 600; font-size: 11px;")
        s_v.addWidget(lbl_lut)

        self.cb_lut_preset = QComboBox()
        self.cb_lut_preset.setFixedHeight(32)
        for preset in LUT_PRESETS:
            self.cb_lut_preset.addItem(preset["name"], preset["id"])
        s_v.addWidget(self.cb_lut_preset)

        # 4B. AI ANTI-COPYRIGHT & TIMED BLUR CONTROLS (Full Unclipped Card)
        ac_card = QFrame()
        ac_card.setObjectName("AcCard")
        ac_card.setStyleSheet(
            "QFrame#AcCard { background: rgba(0, 229, 255, 0.05); "
            "border: 1px solid rgba(0, 229, 255, 0.28); border-radius: 8px; }"
        )
        ac_v = QVBoxLayout(ac_card)
        ac_v.setContentsMargins(10, 9, 10, 9)
        ac_v.setSpacing(7)

        self.chk_anti_copyright = QCheckBox("🛡️ បើក AI Anti-Copyright (កាត់ផ្តាច់ Content ID)")
        self.chk_anti_copyright.setStyleSheet("font-weight: 700; color: #00E5FF; font-size: 11.5px;")
        ac_v.addWidget(self.chk_anti_copyright)

        ac_row = QHBoxLayout()
        ac_row.setSpacing(8)
        self.cb_anti_copyright_level = QComboBox()
        self.cb_anti_copyright_level.setFixedHeight(30)
        self.cb_anti_copyright_level.addItem("🟢 កម្រិតស្រាល (Natural Safe)", "light")
        self.cb_anti_copyright_level.addItem("🟡 កម្រិតមធ្យម (Standard Bypass - Recom.)", "medium")
        self.cb_anti_copyright_level.addItem("🔴 កម្រិតខ្លាំង (Max Fingerprint Break)", "strong")
        self.cb_anti_copyright_level.setCurrentIndex(1)
        ac_row.addWidget(self.cb_anti_copyright_level, 1)

        self.chk_ac_flip = QCheckBox("🪞 Flip")
        self.chk_ac_flip.setToolTip("ត្រឡប់ឆ្វេងស្តាំ (Horizontal Mirror Flip)")
        self.chk_ac_flip.setStyleSheet("font-size: 11px; color: #F4F6FB;")
        ac_row.addWidget(self.chk_ac_flip)

        self.chk_ac_border = QCheckBox("🖼️ Frame")
        self.chk_ac_border.setToolTip("ស៊ុមព្រិលព័ទ្ធជុំវិញ (Blurred-Pillar Frame Border)")
        self.chk_ac_border.setStyleSheet("font-size: 11px; color: #F4F6FB;")
        ac_row.addWidget(self.chk_ac_border)
        ac_v.addLayout(ac_row)

        self.chk_ac_blur = QCheckBox("🌫️ Auto-Blur អក្សរចិន (បាំងអក្សររត់ចិនស្វ័យប្រវត្តិ)")
        self.chk_ac_blur.setToolTip("បាំង Blur លើតំបន់អក្សររត់ចិនដោយស្វ័យប្រវត្តិកំឡុងពេល Render")
        self.chk_ac_blur.setStyleSheet("font-size: 11px; color: #00E5FF; font-weight: 600;")
        ac_v.addWidget(self.chk_ac_blur)

        self.chk_timed_blur = QCheckBox("⏱️ Blur តាមម៉ោង និងទីតាំង (Auto Timed Blur — 0% Blur ពេលគ្មានអក្សរ)")
        self.chk_timed_blur.setToolTip("បាំង Blur តែពេលមានអក្សរលោតលើអេក្រង់ — ពេលគ្មានអក្សរ វីដេអូដើរច្បាស់ ១០០% (Direct Pass-Through)")
        self.chk_timed_blur.setStyleSheet("font-size: 11px; color: #34D399; font-weight: 700;")
        ac_v.addWidget(self.chk_timed_blur)

        self.chk_hd_upscale = QCheckBox("✨ Smart HD Clarity Enhancer (កែរូបភាពឲ្យច្បាស់មុត 1080p Lanczos)")
        self.chk_hd_upscale.setToolTip("បំបាត់ Noise និងបន្ថែមភាពច្បាស់មុត (hqdn3d + unsharp) លើវីដេអូនាំចេញ")
        self.chk_hd_upscale.setStyleSheet("font-size: 11px; color: #FBBF24; font-weight: 700;")
        ac_v.addWidget(self.chk_hd_upscale)

        s_v.addWidget(ac_card)
        s_v.addStretch()

        settings_scroll.setWidget(settings_body)
        right_v.addWidget(settings_scroll, 1)

        # Load persisted edits for anti-copyright, timed blur, HD upscale & LUT preset
        init_edits = self.db.get_project_edits(self.project_id) if self.db else {}
        self.chk_anti_copyright.setChecked(bool(init_edits.get("anti_copyright_enabled", 1)))
        ac_l = init_edits.get("anti_copyright_level", "medium")
        idx_l = self.cb_anti_copyright_level.findData(ac_l)
        if idx_l >= 0:
            self.cb_anti_copyright_level.setCurrentIndex(idx_l)
        self.chk_ac_flip.setChecked(bool(init_edits.get("anti_copyright_flip", 0)))
        self.chk_ac_border.setChecked(bool(init_edits.get("anti_copyright_border", 0)))
        self.chk_ac_blur.setChecked(bool(init_edits.get("auto_blur_chinese", 1)))
        self.chk_timed_blur.setChecked(bool(init_edits.get("auto_timed_blur", 1)))
        self.chk_hd_upscale.setChecked(bool(init_edits.get("hd_upscale_enabled", 0)))
        lut_id = init_edits.get("lut_preset", "none")
        idx_lut = self.cb_lut_preset.findData(lut_id)
        if idx_lut >= 0:
            self.cb_lut_preset.setCurrentIndex(idx_lut)

        # Clean horizontal divider before pinned footer
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background-color: #252A36; max-height: 1px; border: none;")
        right_v.addWidget(divider)

        # 5. OUTPUT SAVE PATH
        lbl_path = QLabel("📁 ទីតាំងរក្សាទុក (Output Destination):")
        lbl_path.setStyleSheet("font-weight: 600; font-size: 11px;")
        right_v.addWidget(lbl_path)

        path_box = QHBoxLayout()
        self.edit_output_path = QLineEdit()
        self.edit_output_path.setText(self._generate_default_output_path("1080p"))
        path_box.addWidget(self.edit_output_path, 1)

        self.btn_browse = QPushButton("📁 រកមើល...")
        self.btn_browse.setStyleSheet(
            "background: #181C24; border: 1px solid #343B4C; border-radius: 6px; padding: 6px 12px; color: #F4F6FB; font-weight: bold; font-size: 11px;"
        )
        self.btn_browse.clicked.connect(self._browse_save_path)
        path_box.addWidget(self.btn_browse)
        right_v.addLayout(path_box)

        self.chk_export_social_pack = QCheckBox("📲 រក្សាទុក Social Pack (.txt && .json) ជាមួយវីដេអូ (3 Viral Titles + Recap + Hashtags)")
        self.chk_export_social_pack.setChecked(True)
        self.chk_export_social_pack.setStyleSheet("font-size: 10.5px; color: #A78BFA; font-weight: 700;")
        right_v.addWidget(self.chk_export_social_pack)

        right_v.addSpacing(4)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        right_v.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #8E95A5; font-size: 11px;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        right_v.addWidget(self.lbl_status)

        # Success Action Buttons (Open Folder & Play Output)
        self.box_results = QWidget()
        box_res_l = QHBoxLayout(self.box_results)
        box_res_l.setContentsMargins(0, 0, 0, 0)
        box_res_l.setSpacing(8)

        self.btn_open_folder = QPushButton("📂 បើកថតផ្ទុក (Open Folder)")
        self.btn_open_folder.setStyleSheet(
            "background: #181C24; border: 1px solid #343B4C; border-radius: 6px; padding: 7px 12px; color: #00E5FF; font-weight: bold; font-size: 11px;"
        )
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        box_res_l.addWidget(self.btn_open_folder)

        self.btn_play_output = QPushButton("▶ ចាក់មើលវីដេអូ (Play Video)")
        self.btn_play_output.setStyleSheet(
            "background: #181C24; border: 1px solid #343B4C; border-radius: 6px; padding: 7px 12px; color: #10B981; font-weight: bold; font-size: 11px;"
        )
        self.btn_play_output.clicked.connect(self._play_output_file)
        box_res_l.addWidget(self.btn_play_output)

        self.box_results.setVisible(False)
        right_v.addWidget(self.box_results)

        # Primary Start Export CTA + Cancel Row
        cta_row = QHBoxLayout()
        cta_row.setSpacing(8)

        self.btn_start = QPushButton("🚀 ចាប់ផ្តើម Export (Start Export Video)")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #10B981);
                color: #FFFFFF;
                font-weight: 800;
                font-size: 13px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #34D399);
            }
            QPushButton:disabled {
                background: #252A36;
                color: #64748B;
            }
        """)
        self.btn_start.clicked.connect(self._start_export_process)
        cta_row.addWidget(self.btn_start, 1)

        self.btn_cancel_export = QPushButton("⏹ បញ្ឈប់")
        self.btn_cancel_export.setFixedHeight(40)
        self.btn_cancel_export.setFixedWidth(96)
        self.btn_cancel_export.setStyleSheet(
            "background: #7F1D1D; color: #FFFFFF; font-weight: 700; font-size: 12px; border: 1px solid #EF4444; border-radius: 6px;"
        )
        self.btn_cancel_export.setVisible(False)
        self.btn_cancel_export.clicked.connect(self._cancel_export_process)
        cta_row.addWidget(self.btn_cancel_export)

        right_v.addLayout(cta_row)

        main_layout.addWidget(right_card, 48)
        root.addLayout(main_layout, 1)

    def _init_preview_player(self):
        """Setup preview player for live video playback before export"""
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self._on_player_pos_changed)
        self.player.durationChanged.connect(self._on_player_dur_changed)
        self.player.playbackStateChanged.connect(self._on_player_state_changed)

        if self.preview_video_path and Path(self.preview_video_path).exists():
            self.player.setSource(QUrl.fromLocalFile(str(Path(self.preview_video_path).resolve())))
            self.audio_output.setVolume(1.0)
            # Auto play preview
            QTimer.singleShot(250, self.player.play)

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_player_state_changed(self, state):
        is_playing = (state == QMediaPlayer.PlayingState)
        self.btn_play.setText("⏸ Pause" if is_playing else "▶ Play")
        self.btn_play.setStyleSheet(
            "background: #202530; border: 1px solid #00E5FF; border-radius: 4px; padding: 4px 8px; color: #00E5FF; font-weight: bold; font-size: 11px;"
            if is_playing else
            "background: #181C24; border: 1px solid #343B4C; border-radius: 4px; padding: 4px 8px; color: #F4F6FB; font-weight: bold; font-size: 11px;"
        )

    def _on_player_pos_changed(self, pos_ms: int):
        dur_ms = self.player.duration() or 1
        if not self.slider_time.isSliderDown():
            ratio = int((pos_ms / dur_ms) * 1000)
            self.slider_time.setValue(ratio)

        cur_s = pos_ms // 1000
        dur_s = dur_ms // 1000
        self.lbl_time.setText(f"{cur_s//60:02d}:{cur_s%60:02d} / {dur_s//60:02d}:{dur_s%60:02d}")

    def _on_player_dur_changed(self, dur_ms: int):
        dur_s = (dur_ms or 0) // 1000
        self.lbl_time.setText(f"00:00 / {dur_s//60:02d}:{dur_s%60:02d}")

    def _on_seek_moved(self, value: int):
        dur_ms = self.player.duration() or 1
        target_ms = int((value / 1000.0) * dur_ms)
        self.player.setPosition(target_ms)

    def _generate_default_output_path(self, res_code: str) -> str:
        base_dir = Path.home() / "Videos"
        if not base_dir.exists():
            base_dir = Path(self.video_path).parent if self.video_path else Path.home()
        stem = Path(self.video_path).stem if self.video_path else "video"
        clean_stem = "".join(c for c in stem if c.isalnum() or c in ("-", "_", " ")).strip() or "video"
        return str(base_dir / f"{clean_stem}_KhmerDub_{res_code}.mp4")

    def _on_settings_changed(self):
        res = self.cb_resolution.currentData()
        current_path = self.edit_output_path.text()
        if current_path:
            p = Path(current_path)
            stem = p.stem
            # Replace previous resolution tag if present
            for old in ("_1080p", "_2k", "_720p", "_original"):
                if stem.endswith(old):
                    stem = stem[:-len(old)]
                    break
            new_name = f"{stem}_{res}.mp4"
            self.edit_output_path.setText(str(p.parent / new_name))

    def _browse_save_path(self):
        cur = self.edit_output_path.text()
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "ជ្រើសរើសទីតាំងរក្សាទុកវីដេអូ",
            cur or "Khmer_Dubbed.mp4",
            "MP4 Video (*.mp4)"
        )
        if chosen:
            self.edit_output_path.setText(chosen)

    def _set_controls_enabled(self, enabled: bool):
        for w in (
            self.btn_start, self.cb_resolution, self.cb_quality, self.cb_fps,
            self.cb_encoder, self.cb_lut_preset, self.btn_browse, self.edit_output_path,
            self.chk_anti_copyright, self.cb_anti_copyright_level,
            self.chk_ac_flip, self.chk_ac_border, self.chk_ac_blur, self.chk_timed_blur,
            self.chk_hd_upscale, self.chk_export_social_pack,
        ):
            if w is not None:
                w.setEnabled(enabled)
        self.btn_cancel_export.setVisible(not enabled)

    def _cancel_export_process(self):
        self._cancel_event.set()
        self.lbl_status.setText("⏹ កំពុងបញ្ឈប់ FFmpeg ដោយសុវត្ថិភាព...")
        self.btn_cancel_export.setEnabled(False)
        MediaEngine.cancel_all_processes()

    def _start_export_process(self):
        out_path = self.edit_output_path.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Ai Summarai", "សូមជ្រើសរើសទីតាំងរក្សាទុកឯកសារវីដេអូជាមុនសិន!")
            return

        out_dir = Path(out_path).parent
        if not out_dir.exists():
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Ai Summarai", f"មិនអាចបង្កើតថតផ្ទុកឯកសារបានទេ: {e}")
                return

        # Pause preview player to avoid CPU/GPU contention
        self.player.pause()
        self._cancel_event.clear()
        self.btn_cancel_export.setEnabled(True)

        resolution = self.cb_resolution.currentData()
        quality = self.cb_quality.currentData()
        fps = self.cb_fps.currentData()
        encoder = self.cb_encoder.currentData()

        # Lock UI
        self._set_controls_enabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.lbl_status.setStyleSheet("color: #8E95A5; font-size: 11px;")
        self.lbl_status.setText("កំពុងចាប់ផ្តើមរៀបចំឯកសារ Export...")
        self.box_results.setVisible(False)

        # Retrieve latest project edits
        edits = self.db.get_project_edits(self.project_id) if self.db else {}
        edits["anti_copyright_enabled"] = 1 if self.chk_anti_copyright.isChecked() else 0
        edits["anti_copyright_level"] = self.cb_anti_copyright_level.currentData()
        edits["anti_copyright_flip"] = 1 if self.chk_ac_flip.isChecked() else 0
        edits["anti_copyright_border"] = 1 if self.chk_ac_border.isChecked() else 0
        edits["auto_blur_chinese"] = 1 if self.chk_ac_blur.isChecked() else 0
        edits["auto_timed_blur"] = 1 if self.chk_timed_blur.isChecked() else 0
        edits["hd_upscale_enabled"] = 1 if self.chk_hd_upscale.isChecked() else 0
        edits["lut_preset"] = self.cb_lut_preset.currentData() or "none"
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        if keep_bgm_only:
            edits["mute_original_audio"] = 0
            saved_bgm_pct = int(self.db.get_setting("bgm_volume_pct", "35")) if self.db else 35
            bgm_vol = round(max(0.15, saved_bgm_pct / 100.0), 2) if saved_bgm_pct <= 5 else round(saved_bgm_pct / 100.0, 2)
        else:
            edits["mute_original_audio"] = 1
            bgm_vol = 0.0
        if self.db and self.project_id:
            self.db.update_project_edits(self.project_id, edits)

        segments = self.db.get_segments(self.project_id) if self.db else []
        export_social = bool(hasattr(self, "chk_export_social_pack") and self.chk_export_social_pack.isChecked())
        api_url = self.db.get_setting("api_url", "https://generativelanguage.googleapis.com/v1beta/openai/") if self.db else "google-free"
        api_key = self.db.get_setting("api_key", "") if self.db else ""
        model = self.db.get_setting("model", "gemini-3.1-flash-lite") if self.db else "google-free"
        glossary = self.db.get_glossary() if self.db else []
        cancel_ev = self._cancel_event

        def task(emit):
            emit(10, f"កំពុង Render វីដេអូចេញជាកម្រិត {resolution.upper()}...")
            MediaEngine.render_final_video(
                video_path=self.video_path,
                segments=segments,
                output_mp4=out_path,
                bgm_volume=bgm_vol,
                edits=edits,
                resolution=resolution,
                quality_preset=quality,
                fps=fps,
                encoder_choice=encoder,
                cancel_event=cancel_ev,
                progress_cb=emit,
            )
            if export_social and segments:
                try:
                    emit(97, "📲 កំពុងបង្កើត Social Pack (.txt & .json) ជាមួយវីដេអូ...")
                    from core.translator import ZHtoKHTranslator
                    tr_s = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model, glossary=glossary)
                    pack = tr_s.generate_social_pack(segments, video_name=Path(out_path).stem)
                    tr_s.save_social_pack_files(pack, out_path)
                except Exception as sp_err:
                    print(f"[Social Pack Export Warning] {sp_err}")
            return out_path

        self._worker = ExportWorker(task)
        self._worker.progress.connect(self._on_export_progress)
        self._worker.finished_ok.connect(self._on_export_finished)
        self._worker.failed.connect(self._on_export_failed)
        self._worker.start()

    def _on_export_progress(self, val: int, msg: str):
        self.progress_bar.setValue(val)
        self.lbl_status.setText(msg)
        self.workflow_progress.emit(val, msg)

    def _on_export_finished(self, out_file: str):
        self.exported_file_path = out_file
        self.progress_bar.setValue(100)
        self.lbl_status.setText(f"🎉 ជោគជ័យ! វីដេអូត្រូវបាន Export ទៅកាន់:\n{Path(out_file).name}")
        self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold; font-size: 11px;")

        self._set_controls_enabled(True)
        self.btn_start.setText("✅ Export បានជោគជ័យ!")

        self.box_results.setVisible(True)
        self.workflow_finished.emit(f"Exported: {Path(out_file).name}")

    def _on_export_failed(self, err_msg: str):
        self.progress_bar.setVisible(False)
        was_cancelled = self._cancel_event.is_set()
        self._set_controls_enabled(True)
        if was_cancelled:
            self.lbl_status.setText("⏹ បានបញ្ឈប់ការ Export ដោយសុវត្ថិភាព។")
            self.lbl_status.setStyleSheet("color: #F59E0B; font-size: 11px;")
            self.workflow_failed.emit("Export cancelled by user")
            return
        self.lbl_status.setText(f"❌ បរាជ័យក្នុងការ Export: {err_msg}")
        self.lbl_status.setStyleSheet("color: #EF4444; font-size: 11px;")
        self.workflow_failed.emit(err_msg)
        QMessageBox.critical(self, "Export Error", f"មានបញ្ហាក្នុងការ Render វីដេអូ:\n{err_msg}")

    def _open_output_folder(self):
        if self.exported_file_path and Path(self.exported_file_path).exists():
            folder = str(Path(self.exported_file_path).parent)
            cflags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(Path(self.exported_file_path).resolve())], creationflags=cflags)
            else:
                subprocess.Popen(["xdg-open", folder], creationflags=cflags)

    def _play_output_file(self):
        if self.exported_file_path and Path(self.exported_file_path).exists():
            cflags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            if os.name == "nt":
                os.startfile(str(Path(self.exported_file_path).resolve()))
            else:
                subprocess.Popen(["xdg-open", str(self.exported_file_path)], creationflags=cflags)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._cancel_event.set()
            MediaEngine.cancel_all_processes()
            self._worker.wait(2000)
        if hasattr(self, "player") and self.player:
            self.player.stop()
        super().closeEvent(event)
