# -*- coding: utf-8 -*-
"""
ui/widgets/preview_canvas.py
High-DPI Live Video Frame Previewer + Interactive Timeline Scrubber Slider.
"""

import os
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton
)


class PreviewCanvas(QWidget):
    """
    Top-half workspace widget showing the live processed frame (3D LUT + Mask + Animated Text)
    with a timeline scrubber slider and frame stepping buttons.
    """

    time_scrubbed = Signal(float)  # Emits target timestamp in seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration_sec = 10.0
        self.current_sec = 0.0
        self._current_pixmap: QPixmap = QPixmap()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Video frame display canvas
        self.canvas_lbl = QLabel("🎬 Live Preview Canvas — Click 'Render Preview Frame' or Open a Video")
        self.canvas_lbl.setAlignment(Qt.AlignCenter)
        self.canvas_lbl.setMinimumSize(480, 260)
        self.canvas_lbl.setStyleSheet(
            "background-color: #0B0D10; border: 1px solid #262B33; "
            "border-radius: 8px; color: #9CA3AF; font-weight: 600;"
        )
        layout.addWidget(self.canvas_lbl, 1)

        # Scrubber controls bar
        bar = QHBoxLayout()
        bar.setContentsMargins(2, 0, 2, 0)
        bar.setSpacing(8)

        self.btn_step_back = QPushButton("◀ -1s")
        self.btn_step_back.setFixedWidth(56)
        self.btn_step_back.clicked.connect(lambda: self.step_by(-1.0))
        bar.addWidget(self.btn_step_back)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self._on_slider_moved)
        bar.addWidget(self.slider, 1)

        self.btn_step_fwd = QPushButton("+1s ▶")
        self.btn_step_fwd.setFixedWidth(56)
        self.btn_step_fwd.clicked.connect(lambda: self.step_by(1.0))
        bar.addWidget(self.btn_step_fwd)

        self.lbl_time = QLabel("00:00.0 / 00:10.0")
        self.lbl_time.setStyleSheet("font-family: Consolas, monospace; color: #9CA3AF; font-size: 11px;")
        bar.addWidget(self.lbl_time)

        layout.addLayout(bar)

    def set_duration(self, duration_sec: float) -> None:
        self.duration_sec = max(0.5, float(duration_sec))
        self._update_time_label()

    def step_by(self, delta_sec: float) -> None:
        self.current_sec = max(0.0, min(self.duration_sec, self.current_sec + delta_sec))
        self.slider.blockSignals(True)
        self.slider.setValue(int((self.current_sec / self.duration_sec) * 1000))
        self.slider.blockSignals(False)
        self._update_time_label()
        self.time_scrubbed.emit(self.current_sec)

    def _on_slider_moved(self, val: int) -> None:
        self.current_sec = (val / 1000.0) * self.duration_sec
        self._update_time_label()
        self.time_scrubbed.emit(self.current_sec)

    def _update_time_label(self) -> None:
        def fmt(s: float) -> str:
            m = int(s // 60)
            sec = s % 60
            return f"{m:02d}:{sec:04.1f}"
        self.lbl_time.setText(f"{fmt(self.current_sec)} / {fmt(self.duration_sec)}")

    def display_frame(self, image_path: str) -> None:
        if image_path and os.path.exists(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                self._current_pixmap = pix
                self._rescale_pixmap()

    def _rescale_pixmap(self) -> None:
        if not self._current_pixmap.isNull():
            scaled = self._current_pixmap.scaled(
                self.canvas_lbl.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.canvas_lbl.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale_pixmap()
