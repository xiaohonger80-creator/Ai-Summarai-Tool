# -*- coding: utf-8 -*-
"""
ui/video_fx_studio.py
VideoFX Studio GUI:
High-performance non-blocking desktop interface for:
  - 3D LUT Color Grading (0-100% intensity)
  - Animated & Scrolling Subtitles (.ass UTF-8)
  - Geometric & Luma Video Masking (FFmpeg / OpenCV)
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QPixmap, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QComboBox, QSpinBox, QDoubleSpinBox,
    QTabWidget, QTextEdit, QFileDialog, QMessageBox, QProgressBar,
    QGroupBox, QFormLayout, QCheckBox, QColorDialog, QSplitter
)

from core.lut_engine import LUTEngine
from core.text_animator import TextAnimator
from core.compositor import VideoFXCompositor
from core.masking.shape_masker import ShapeMasker
from workers.render_worker import PreviewRenderWorker, ExportRenderWorker

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class VideoFXStudioWindow(QMainWindow):
    """
    Modular VideoFX Studio main window.
    Can run standalone or be invoked from Ai Summarai Studio.
    """

    def __init__(self, parent=None, initial_video_path: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("🎬 VideoFX Studio — 3D LUTs, Masking & Animated Text")
        self.resize(1340, 840)
        self.setMinimumSize(1000, 680)

        # Core Engines
        self.lut_engine = LUTEngine()
        self.compositor = VideoFXCompositor(lut_engine=self.lut_engine)
        self.shape_masker = ShapeMasker()

        # State
        self.video_path = initial_video_path if (initial_video_path and os.path.exists(initial_video_path)) else None
        self.video_duration = 0.0
        self.video_w = 1920
        self.video_h = 1080
        self.current_time_sec = 0.0
        self.temp_dir = Path(tempfile.mkdtemp(prefix="videofx_"))
        self.temp_ass_path = str(self.temp_dir / "animated_text.ass")
        self.preview_jpg_path = str(self.temp_dir / "preview_frame.jpg")

        # Worker references
        self._preview_worker: Optional[PreviewRenderWorker] = None
        self._export_worker: Optional[ExportRenderWorker] = None

        # Debounce timer for smooth real-time scrubbing
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(120)
        self.preview_timer.timeout.connect(self._trigger_preview_render)

        # Build UI
        self._init_theme()
        self._build_ui()

        if self.video_path:
            self._load_video_metadata(self.video_path)

    def _init_theme(self):
        """Dark-slate modern studio theme (#121417 canvas, #1B1F24 panels, #3B82F6 accent)."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #121417;
                color: #F3F4F6;
                font-family: 'Segoe UI', 'Noto Sans Khmer', sans-serif;
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #2B303B;
                border-radius: 8px;
                margin-top: 14px;
                padding-top: 14px;
                font-weight: 600;
                color: #60A5FA;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                background-color: #121417;
            }
            QTabWidget::pane {
                border: 1px solid #2B303B;
                border-radius: 8px;
                background: #181C22;
                padding: 8px;
            }
            QTabBar::tab {
                background: #14171D;
                color: #9CA3AF;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background: #2563EB;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3B82F6;
            }
            QPushButton:pressed {
                background-color: #1D4ED8;
            }
            QPushButton#ActionBtn {
                background-color: #059669;
            }
            QPushButton#ActionBtn:hover {
                background-color: #10B981;
            }
            QPushButton#SecondaryBtn {
                background-color: #2B303B;
                color: #D1D5DB;
            }
            QPushButton#SecondaryBtn:hover {
                background-color: #374151;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #2B303B;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #3B82F6;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #60A5FA;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
            QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
                background-color: #1B1F26;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 4px 8px;
                color: #F9FAFB;
            }
            QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
                border-color: #3B82F6;
            }
            QProgressBar {
                border: 1px solid #2B303B;
                border-radius: 6px;
                background: #14171D;
                text-align: center;
                color: #FFFFFF;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2563EB;
                border-radius: 5px;
            }
        """)

    def _build_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 1. Top Header Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.btn_open = QPushButton("📂 Open Video")
        self.btn_open.clicked.connect(self._on_open_video)
        top_bar.addWidget(self.btn_open)

        self.lbl_video_info = QLabel("No video loaded. Click 'Open Video' to begin.")
        self.lbl_video_info.setStyleSheet("color: #9CA3AF; font-weight: 500;")
        top_bar.addWidget(self.lbl_video_info, 1)

        self.btn_export = QPushButton("⚡ Export Video (Render)")
        self.btn_export.setObjectName("ActionBtn")
        self.btn_export.clicked.connect(self._on_export_video)
        top_bar.addWidget(self.btn_export)

        self.btn_cancel_export = QPushButton("🛑 Stop")
        self.btn_cancel_export.setStyleSheet("background-color: #DC2626;")
        self.btn_cancel_export.setVisible(False)
        self.btn_cancel_export.clicked.connect(self._on_cancel_export)
        top_bar.addWidget(self.btn_cancel_export)

        main_layout.addLayout(top_bar)

        # Progress bar
        self.export_progress = QProgressBar()
        self.export_progress.setFixedHeight(12)
        self.export_progress.setVisible(False)
        main_layout.addWidget(self.export_progress)

        # 2. Main Center Area (Splitter: Player left, Inspector right)
        splitter = QSplitter(Qt.Horizontal)

        # --- LEFT: Player & Scrubber ---
        player_container = QWidget()
        player_layout = QVBoxLayout(player_container)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(8)

        # Viewport
        self.lbl_viewport = QLabel("Video Preview Canvas")
        self.lbl_viewport.setAlignment(Qt.AlignCenter)
        self.lbl_viewport.setStyleSheet("""
            background-color: #0A0C0E;
            border: 1px solid #1E232B;
            border-radius: 8px;
        """)
        self.lbl_viewport.setMinimumSize(540, 380)
        player_layout.addWidget(self.lbl_viewport, 1)

        # Controls & Scrubber Bar
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(8)

        self.lbl_timestamp = QLabel("00:00 / 00:00")
        self.lbl_timestamp.setStyleSheet("font-family: monospace; font-size: 11px; color: #9CA3AF;")
        ctrl_bar.addWidget(self.lbl_timestamp)

        self.scrubber = QSlider(Qt.Horizontal)
        self.scrubber.setRange(0, 1000)
        self.scrubber.setValue(0)
        self.scrubber.valueChanged.connect(self._on_scrubber_changed)
        ctrl_bar.addWidget(self.scrubber, 1)

        self.btn_prev_frame = QPushButton("◀")
        self.btn_prev_frame.setObjectName("SecondaryBtn")
        self.btn_prev_frame.setFixedWidth(32)
        self.btn_prev_frame.clicked.connect(lambda: self._step_time(-1.0))
        ctrl_bar.addWidget(self.btn_prev_frame)

        self.btn_next_frame = QPushButton("▶")
        self.btn_next_frame.setObjectName("SecondaryBtn")
        self.btn_next_frame.setFixedWidth(32)
        self.btn_next_frame.clicked.connect(lambda: self._step_time(1.0))
        ctrl_bar.addWidget(self.btn_next_frame)

        player_layout.addLayout(ctrl_bar)
        splitter.addWidget(player_container)

        # --- RIGHT: 3-Tab Inspector ---
        inspector_tabs = QTabWidget()
        inspector_tabs.setMinimumWidth(380)

        # Tab 1: 3D LUT Color Grading
        inspector_tabs.addTab(self._build_lut_tab(), "🎨 3D Color LUT")

        # Tab 2: Animated Text & Subtitles
        inspector_tabs.addTab(self._build_text_tab(), "✍️ Animated Text")

        # Tab 3: Video Masking & Blur
        inspector_tabs.addTab(self._build_mask_tab(), "🎭 Video Masking")

        splitter.addWidget(inspector_tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 1)

        self.setCentralWidget(main_widget)

    # -------------------------------------------------------------
    # Tab Builders
    # -------------------------------------------------------------
    def _build_lut_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        self.chk_lut_enable = QCheckBox("Enable 3D LUT Color Grading (បើកដំណើរការកែពណ៌)")
        self.chk_lut_enable.setChecked(True)
        self.chk_lut_enable.toggled.connect(self._request_preview)
        layout.addWidget(self.chk_lut_enable)

        form = QFormLayout()
        form.setSpacing(10)

        self.combo_luts = QComboBox()
        self.combo_luts.addItems(self.lut_engine.get_available_luts())
        self.combo_luts.addItem("📂 Load Custom .cube File...")
        self.combo_luts.currentIndexChanged.connect(self._on_lut_selected)
        form.addRow("Preset LUT:", self.combo_luts)

        # Intensity Slider
        int_box = QHBoxLayout()
        self.slider_lut_intensity = QSlider(Qt.Horizontal)
        self.slider_lut_intensity.setRange(0, 100)
        self.slider_lut_intensity.setValue(100)
        self.slider_lut_intensity.valueChanged.connect(self._on_intensity_changed)

        self.lbl_lut_intensity = QLabel("100%")
        self.lbl_lut_intensity.setFixedWidth(40)
        int_box.addWidget(self.slider_lut_intensity, 1)
        int_box.addWidget(self.lbl_lut_intensity)
        form.addRow("Intensity (កម្រិតពណ៌):", int_box)

        layout.addLayout(form)

        # Quick preset buttons
        preset_grp = QGroupBox("Quick Cinematic Styles (ស្ទីលពេញនិយម)")
        preset_layout = QVBoxLayout(preset_grp)
        btn_teal = QPushButton("🎬 Teal & Orange (ភាពយន្តហូលីវូដ)")
        btn_teal.setObjectName("SecondaryBtn")
        btn_teal.clicked.connect(lambda: self._select_lut_by_name("Cinematic_Teal_Orange.cube"))
        preset_layout.addWidget(btn_teal)

        btn_kodak = QPushButton("🎞️ Vintage Kodak (ស្ទីលហ្វីលបុរាណ)")
        btn_kodak.setObjectName("SecondaryBtn")
        btn_kodak.clicked.connect(lambda: self._select_lut_by_name("Kodak_Vintage_Film.cube"))
        preset_layout.addWidget(btn_kodak)

        btn_vivid = QPushButton("🔥 Vivid Social Pop (ស្រស់ឆើត TikTok/Reels)")
        btn_vivid.setObjectName("SecondaryBtn")
        btn_vivid.clicked.connect(lambda: self._select_lut_by_name("Vivid_Social_Pop.cube"))
        preset_layout.addWidget(btn_vivid)

        layout.addWidget(preset_grp)
        layout.addStretch()
        return widget

    def _build_text_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        self.chk_text_enable = QCheckBox("Enable Animated Text Overlay (បើកអក្សររត់)")
        self.chk_text_enable.setChecked(False)
        self.chk_text_enable.toggled.connect(self._request_preview)
        layout.addWidget(self.chk_text_enable)

        form = QFormLayout()
        form.setSpacing(8)

        self.txt_content = QTextEdit()
        self.txt_content.setPlaceholderText("បញ្ចូលអត្ថបទខ្មែរ ចិន ឬអង់គ្លេសនៅទីនេះ...\nឧទាហរណ៍៖ កំពូលភាពយន្តចិននិយាយខ្មែរ 2026")
        self.txt_content.setFixedHeight(65)
        self.txt_content.textChanged.connect(self._request_preview)
        form.addRow("Text Content:", self.txt_content)

        self.combo_text_anim = QComboBox()
        self.combo_text_anim.addItems(TextAnimator.ANIMATION_MODES)
        self.combo_text_anim.currentIndexChanged.connect(self._request_preview)
        form.addRow("Animation Mode:", self.combo_text_anim)

        self.combo_font = QComboBox()
        self.combo_font.addItems([
            "Noto Sans Khmer", "Khmer OS Battambang", "Khmer OS Muol Light",
            "Microsoft YaHei", "Arial", "Impact"
        ])
        self.combo_font.currentIndexChanged.connect(self._request_preview)
        form.addRow("Font Family:", self.combo_font)

        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(18, 140)
        self.spin_font_size.setValue(48)
        self.spin_font_size.valueChanged.connect(self._request_preview)
        form.addRow("Font Size (px):", self.spin_font_size)

        self.combo_text_pos = QComboBox()
        self.combo_text_pos.addItems(["Bottom (ខាងក្រោម)", "Top (ខាងលើ)", "Middle (កណ្តាល)"])
        self.combo_text_pos.currentIndexChanged.connect(self._request_preview)
        form.addRow("Position (ទីតាំង):", self.combo_text_pos)

        # Colors
        color_box = QHBoxLayout()
        self.btn_text_color = QPushButton("Color: White")
        self.btn_text_color.setObjectName("SecondaryBtn")
        self._cur_text_color = "#FFFFFF"
        self.btn_text_color.clicked.connect(self._pick_text_color)
        color_box.addWidget(self.btn_text_color)

        self.btn_outline_color = QPushButton("Outline: Black")
        self.btn_outline_color.setObjectName("SecondaryBtn")
        self._cur_outline_color = "#000000"
        self.btn_outline_color.clicked.connect(self._pick_outline_color)
        color_box.addWidget(self.btn_outline_color)
        form.addRow("Colors:", color_box)

        layout.addLayout(form)
        layout.addStretch()
        return widget

    def _build_mask_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        self.chk_mask_enable = QCheckBox("Enable Video Masking / Blur (បើកម៉ាស់ ឬបិទបាំង)")
        self.chk_mask_enable.setChecked(False)
        self.chk_mask_enable.toggled.connect(self._request_preview)
        layout.addWidget(self.chk_mask_enable)

        form = QFormLayout()
        form.setSpacing(8)

        self.combo_mask_shape = QComboBox()
        self.combo_mask_shape.addItems(ShapeMasker.SUPPORTED_SHAPES)
        self.combo_mask_shape.currentIndexChanged.connect(self._request_preview)
        form.addRow("Mask Type:", self.combo_mask_shape)

        self.slider_mask_blur = QSlider(Qt.Horizontal)
        self.slider_mask_blur.setRange(2, 60)
        self.slider_mask_blur.setValue(24)
        self.slider_mask_blur.valueChanged.connect(self._request_preview)
        form.addRow("Blur Strength (ភាពព្រាល):", self.slider_mask_blur)

        # Region controls
        self.spin_mask_y = QSpinBox()
        self.spin_mask_y.setRange(0, 100)
        self.spin_mask_y.setValue(75)
        self.spin_mask_y.setSuffix("%")
        self.spin_mask_y.valueChanged.connect(self._request_preview)
        form.addRow("Region Y (កម្ពស់):", self.spin_mask_y)

        self.spin_mask_h = QSpinBox()
        self.spin_mask_h.setRange(5, 50)
        self.spin_mask_h.setValue(20)
        self.spin_mask_h.setSuffix("%")
        self.spin_mask_h.valueChanged.connect(self._request_preview)
        form.addRow("Region Height (ទំហំបិទបាំង):", self.spin_mask_h)

        self.chk_mask_invert = QCheckBox("Invert Mask (បញ្ច្រាសម៉ាស់)")
        self.chk_mask_invert.setChecked(False)
        self.chk_mask_invert.toggled.connect(self._request_preview)
        form.addRow("", self.chk_mask_invert)

        layout.addLayout(form)
        layout.addStretch()
        return widget

    # -------------------------------------------------------------
    # State & Handlers
    # -------------------------------------------------------------
    def _on_open_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mkv *.mov *.webm *.avi);;All Files (*.*)"
        )
        if file_path and os.path.exists(file_path):
            self.video_path = file_path
            self._load_video_metadata(file_path)

    def _load_video_metadata(self, path: str):
        self.lbl_video_info.setText(f"Loading: {Path(path).name}...")
        try:
            # Query duration and resolution with ffprobe
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration:format=duration",
                "-of", "default=noprint_wrappers=1",
                str(path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, text=True)
            w, h, dur = 1920, 1080, 10.0
            for line in res.stdout.splitlines():
                k, _, v = line.partition("=")
                if k == "width":
                    w = int(v)
                elif k == "height":
                    h = int(v)
                elif k == "duration" and dur == 10.0:
                    try:
                        dur = float(v)
                    except ValueError:
                        pass
            self.video_w = w
            self.video_h = h
            self.video_duration = max(0.5, dur)
            self.lbl_video_info.setText(f"📹 {Path(path).name}  |  {w}x{h}  |  {int(self.video_duration)}s")
            self._update_timestamp_label(0.0)
            self._request_preview()
        except Exception as e:
            self.lbl_video_info.setText(f"📹 {Path(path).name} (Metadata error: {e})")
            self.video_duration = 30.0
            self._request_preview()

    def _on_scrubber_changed(self, val: int):
        if self.video_duration > 0:
            self.current_time_sec = (val / 1000.0) * self.video_duration
            self._update_timestamp_label(self.current_time_sec)
            self._request_preview()

    def _step_time(self, delta: float):
        self.current_time_sec = max(0.0, min(self.video_duration, self.current_time_sec + delta))
        if self.video_duration > 0:
            self.scrubber.blockSignals(True)
            self.scrubber.setValue(int((self.current_time_sec / self.video_duration) * 1000.0))
            self.scrubber.blockSignals(False)
        self._update_timestamp_label(self.current_time_sec)
        self._request_preview()

    def _update_timestamp_label(self, sec: float):
        s_cur = int(sec)
        s_tot = int(self.video_duration)
        cur_str = f"{s_cur // 60:02d}:{s_cur % 60:02d}"
        tot_str = f"{s_tot // 60:02d}:{s_tot % 60:02d}"
        self.lbl_timestamp.setText(f"{cur_str} / {tot_str}")

    def _on_intensity_changed(self, val: int):
        self.lbl_lut_intensity.setText(f"{val}%")
        self._request_preview()

    def _select_lut_by_name(self, name: str):
        idx = self.combo_luts.findText(name)
        if idx >= 0:
            self.combo_luts.setCurrentIndex(idx)
        self.chk_lut_enable.setChecked(True)
        self._request_preview()

    def _on_lut_selected(self, idx: int):
        if self.combo_luts.currentText().startswith("📂"):
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select 3D .cube LUT File", "", "LUT Files (*.cube);;All Files (*.*)"
            )
            if file_path and os.path.exists(file_path):
                copied = self.lut_engine.import_custom_lut(file_path)
                self.combo_luts.blockSignals(True)
                self.combo_luts.clear()
                self.combo_luts.addItems(self.lut_engine.get_available_luts())
                self.combo_luts.addItem("📂 Load Custom .cube File...")
                self.combo_luts.setCurrentText(copied)
                self.combo_luts.blockSignals(False)
        self._request_preview()

    def _pick_text_color(self):
        col = QColorDialog.getColor(QColor(self._cur_text_color), self, "Select Text Color")
        if col.isValid():
            self._cur_text_color = col.name().upper()
            self.btn_text_color.setText(f"Color: {self._cur_text_color}")
            self._request_preview()

    def _pick_outline_color(self):
        col = QColorDialog.getColor(QColor(self._cur_outline_color), self, "Select Outline Color")
        if col.isValid():
            self._cur_outline_color = col.name().upper()
            self.btn_outline_color.setText(f"Outline: {self._cur_outline_color}")
            self._request_preview()

    def _request_preview(self):
        """Debounced preview request so rapid UI adjustments stay ultra-smooth."""
        if not self.video_path:
            return
        self.preview_timer.start()

    def _trigger_preview_render(self):
        if not self.video_path:
            return

        # Prepare parameters
        lut_name = None
        lut_intensity = 0.0
        if self.chk_lut_enable.isChecked() and not self.combo_luts.currentText().startswith("📂"):
            lut_name = self.combo_luts.currentText()
            lut_intensity = self.slider_lut_intensity.value() / 100.0

        mask_params = None
        if self.chk_mask_enable.isChecked():
            shape_type = self.combo_mask_shape.currentText()
            by_pct = self.spin_mask_y.value() / 100.0
            bh_pct = self.spin_mask_h.value() / 100.0
            mask_params = {
                "enabled": True,
                "shape_type": shape_type,
                "blur_radius": self.slider_mask_blur.value(),
                "box_x": int(self.video_w * 0.05),
                "box_y": int(self.video_h * by_pct),
                "box_w": int(self.video_w * 0.90),
                "box_h": int(self.video_h * bh_pct),
                "invert": self.chk_mask_invert.isChecked(),
            }

        ass_file = None
        if self.chk_text_enable.isChecked() and self.txt_content.toPlainText().strip():
            raw_txt = self.txt_content.toPlainText().strip()
            anim_mode = self.combo_text_anim.currentText()
            pos = "Bottom" if "Bottom" in self.combo_text_pos.currentText() else (
                "Top" if "Top" in self.combo_text_pos.currentText() else "Middle"
            )
            try:
                TextAnimator.generate_ass_script(
                    text_content=raw_txt,
                    animation_mode=anim_mode,
                    video_duration_sec=self.video_duration,
                    out_ass_path=self.temp_ass_path,
                    width=self.video_w,
                    height=self.video_h,
                    font_name=self.combo_font.currentText(),
                    font_size=self.spin_font_size.value(),
                    primary_color=self._cur_text_color,
                    outline_color=self._cur_outline_color,
                    position=pos,
                )
                ass_file = self.temp_ass_path
            except Exception:
                ass_file = None

        # Terminate any existing preview worker
        if self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.cancel()
            self._preview_worker.wait(100)

        # Launch background preview worker
        self._preview_worker = PreviewRenderWorker(
            compositor=self.compositor,
            video_path=self.video_path,
            timestamp_sec=self.current_time_sec,
            out_jpg_path=self.preview_jpg_path,
            lut_name=lut_name,
            lut_intensity=lut_intensity,
            mask_params=mask_params,
            ass_path=ass_file,
            target_w=960,
            target_h=540,
            parent=self,
        )
        self._preview_worker.preview_ready.connect(self._on_preview_ready)
        self._preview_worker.start()

    @Slot(str, float)
    def _on_preview_ready(self, jpg_path: str, ts: float):
        if os.path.exists(jpg_path):
            pix = QPixmap(jpg_path)
            scaled = pix.scaled(
                self.lbl_viewport.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.lbl_viewport.setPixmap(scaled)

    # -------------------------------------------------------------
    # Full Video Export
    # -------------------------------------------------------------
    def _on_export_video(self):
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(self, "Warning", "សូមជ្រើសរើសវីដេអូជាមុនសិន (Please open a video first).")
            return

        default_out = str(Path(self.video_path).with_stem(f"{Path(self.video_path).stem}_VideoFX"))
        out_file, _ = QFileDialog.getSaveFileName(
            self, "Export Video As", default_out, "MP4 Video (*.mp4);;All Files (*.*)"
        )
        if not out_file:
            return

        lut_name = self.combo_luts.currentText() if (self.chk_lut_enable.isChecked() and not self.combo_luts.currentText().startswith("📂")) else None
        lut_intensity = self.slider_lut_intensity.value() / 100.0 if self.chk_lut_enable.isChecked() else 0.0

        mask_params = None
        if self.chk_mask_enable.isChecked():
            mask_params = {
                "enabled": True,
                "shape_type": self.combo_mask_shape.currentText(),
                "blur_radius": self.slider_mask_blur.value(),
                "box_x": int(self.video_w * 0.05),
                "box_y": int(self.video_h * (self.spin_mask_y.value() / 100.0)),
                "box_w": int(self.video_w * 0.90),
                "box_h": int(self.video_h * (self.spin_mask_h.value() / 100.0)),
                "invert": self.chk_mask_invert.isChecked(),
            }

        ass_file = None
        if self.chk_text_enable.isChecked() and self.txt_content.toPlainText().strip():
            ass_file = self.temp_ass_path

        cmd = self.compositor.build_export_command(
            video_path=self.video_path,
            out_video_path=out_file,
            lut_name=lut_name,
            lut_intensity=lut_intensity,
            mask_params=mask_params,
            ass_path=ass_file,
            video_w=self.video_w,
            video_h=self.video_h,
        )

        self.btn_export.setEnabled(False)
        self.btn_cancel_export.setVisible(True)
        self.export_progress.setVisible(True)
        self.export_progress.setValue(0)

        self._export_worker = ExportRenderWorker(
            cmd=cmd,
            total_duration_sec=self.video_duration,
            out_path=out_file,
            parent=self,
        )
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.status_text.connect(self.lbl_video_info.setText)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.start()

    def _on_export_progress(self, pct: int, eta: str):
        self.export_progress.setValue(pct)
        self.lbl_video_info.setText(f"⚡ កំពុងដំណើរការផលិតវីដេអូ: {pct}% ({eta})")

    def _on_export_finished(self, out_path: str):
        self.btn_export.setEnabled(True)
        self.btn_cancel_export.setVisible(False)
        self.export_progress.setVisible(False)
        self.lbl_video_info.setText(f"✅ បានផលិតរួចរាល់៖ {Path(out_path).name}")
        QMessageBox.information(self, "Export Complete", f"វីដេអូត្រូវបានផលិតដោយជោគជ័យ!\nរក្សាទុកនៅ៖\n{out_path}")

    def _on_export_failed(self, err_msg: str):
        self.btn_export.setEnabled(True)
        self.btn_cancel_export.setVisible(False)
        self.export_progress.setVisible(False)
        self.lbl_video_info.setText("❌ ការនាំចេញបានបរាជ័យ (Export Failed)")
        QMessageBox.critical(self, "Export Error", f"កំហុសក្នុងការផលិតវីដេអូ៖\n{err_msg}")

    def _on_cancel_export(self):
        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.cancel()
            self._export_worker.wait(1000)
        self.btn_export.setEnabled(True)
        self.btn_cancel_export.setVisible(False)
        self.export_progress.setVisible(False)
        self.lbl_video_info.setText("🛑 ការនាំចេញត្រូវបានផ្អាក (Cancelled)")
