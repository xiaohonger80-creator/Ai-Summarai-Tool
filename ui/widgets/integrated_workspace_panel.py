# -*- coding: utf-8 -*-
"""
ui/widgets/integrated_workspace_panel.py
In-Window Responsive Inspector & Workspace Switcher for MainWindow:
Integrates:
  - Mode 0: Classic Visual Inspector (Logo, Sub, Audio, LUTs, Cut & Intro, Mask, Hook & Cover)
  - Mode 1: AI Studio Inspector (Extract & Translate, Story Recap & Dubbing, Smart TTS Cache, .vfxproj)
  - Mode 2: VideoFX Studio Inspector (3D .cube LUTs 0-100%, Animated .ASS Text, AI & Shape Video Masking)
  - Mode 3: Combined All-in-One Mode (Classic Visual + AI Studio + VideoFX all accessible together)
Operates 100% in-place inside MainWindow without opening any separate popup windows.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTabWidget,
    QPushButton, QLabel, QComboBox, QFrame
)

from config.settings import SubtitleSettings
from core.hardware_profiler import HardwareProfiler
from ui.widgets.inspector_tabs import InspectorTabs


class IntegratedInspectorContainer(QWidget):
    """
    Wraps MainWindow's classic Visual Inspector and the new AI Studio & VideoFX Inspectors
    into a single responsive in-window panel with a 1-click Mode Switcher header.
    """

    mode_changed = Signal(str)               # "dub" | "ai_studio" | "videofx" | "combined"
    render_preview_requested = Signal(dict)  # Emits current studio settings for live frame preview
    run_ai_pipeline_requested = Signal(dict) # Emits current studio settings to run in MainWindow
    save_vfxproj_requested = Signal()
    load_vfxproj_requested = Signal()
    speaker_mapper_requested = Signal()
    perf_profile_changed = Signal(str)

    def __init__(self, classic_inspector_widget: QWidget, parent=None):
        super().__init__(parent)
        self.classic_widget = classic_inspector_widget
        self.settings = SubtitleSettings.load()
        self.current_mode = "dub"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ------------------------------------------------------------------
        # 1. IN-WINDOW WORKSPACE MODE SWITCHER PILL BAR
        # ------------------------------------------------------------------
        mode_bar = QFrame()
        mode_bar.setStyleSheet(
            "QFrame { background: #12151C; border: 1px solid #262C3A; border-radius: 7px; }"
        )
        mb_lay = QHBoxLayout(mode_bar)
        mb_lay.setContentsMargins(3, 3, 3, 3)
        mb_lay.setSpacing(3)

        self.btn_mode_dub = self._make_mode_btn("🎙️ Dub", "dub", "#00E5FF")
        self.btn_mode_ai = self._make_mode_btn("🚀 AI Studio", "ai_studio", "#3B82F6")
        self.btn_mode_fx = self._make_mode_btn("🎬 VideoFX", "videofx", "#A855F7")
        self.btn_mode_all = self._make_mode_btn("⚡ រួមគ្នា (All)", "combined", "#10B981")

        for b in (self.btn_mode_dub, self.btn_mode_ai, self.btn_mode_fx, self.btn_mode_all):
            mb_lay.addWidget(b)

        layout.addWidget(mode_bar)

        # ------------------------------------------------------------------
        # 2. QUICK ACTION HEADER FOR AI STUDIO & VIDEOFX (.vfxproj + Perf + Live Preview)
        # ------------------------------------------------------------------
        self.studio_action_bar = QFrame()
        self.studio_action_bar.setStyleSheet(
            "QFrame { background: #161A23; border: 1px solid #283040; border-radius: 6px; }"
        )
        sab_v = QVBoxLayout(self.studio_action_bar)
        sab_v.setContentsMargins(6, 5, 6, 5)
        sab_v.setSpacing(5)

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        self.btn_save_proj = QPushButton("💾 Save .vfxproj")
        self.btn_save_proj.setFixedHeight(26)
        self.btn_save_proj.setToolTip("រក្សាទុកគម្រោងជា .vfxproj (Ctrl+S)")
        self.btn_save_proj.clicked.connect(self.save_vfxproj_requested.emit)
        row1.addWidget(self.btn_save_proj)

        self.btn_load_proj = QPushButton("📁 Load .vfxproj")
        self.btn_load_proj.setFixedHeight(26)
        self.btn_load_proj.setToolTip("បើកគម្រោង .vfxproj ដែលបានរក្សាទុក")
        self.btn_load_proj.clicked.connect(self.load_vfxproj_requested.emit)
        row1.addWidget(self.btn_load_proj)

        self.combo_perf = QComboBox()
        self.combo_perf.setFixedHeight(26)
        self.combo_perf.addItems(["⚡ High-Spec PC", "🟢 Low-Spec Safe"])
        if self.settings.get("hardware_profile") == "low":
            self.combo_perf.setCurrentIndex(1)
        self.combo_perf.currentTextChanged.connect(self._on_perf_changed)
        row1.addWidget(self.combo_perf)
        sab_v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(5)
        self.btn_render_fx_preview = QPushButton("🖼️ Apply & Render Preview")
        self.btn_render_fx_preview.setFixedHeight(28)
        self.btn_render_fx_preview.setStyleSheet(
            "QPushButton { background: #059669; color: #FFFFFF; border-radius: 5px; font-weight: 700; font-size: 11px; }"
            "QPushButton:hover { background: #10B981; }"
        )
        self.btn_render_fx_preview.clicked.connect(self._on_render_preview_clicked)
        row2.addWidget(self.btn_render_fx_preview)

        self.btn_run_ai_pipeline = QPushButton("🚀 Run AI Pipeline")
        self.btn_run_ai_pipeline.setFixedHeight(28)
        self.btn_run_ai_pipeline.setStyleSheet(
            "QPushButton { background: #2563EB; color: #FFFFFF; border-radius: 5px; font-weight: 700; font-size: 11px; }"
            "QPushButton:hover { background: #3B82F6; }"
        )
        self.btn_run_ai_pipeline.clicked.connect(self._on_run_pipeline_clicked)
        row2.addWidget(self.btn_run_ai_pipeline)
        sab_v.addLayout(row2)

        self.studio_action_bar.setVisible(False)
        layout.addWidget(self.studio_action_bar)

        # ------------------------------------------------------------------
        # 3. UNIFIED TABBED / STACKED INSPECTOR AREA
        # ------------------------------------------------------------------
        self.inspector_tabs = InspectorTabs(initial_settings=self.settings, parent=self)
        self.inspector_tabs.settings_changed.connect(self._on_inspector_settings_changed)
        self.inspector_tabs.speaker_mapper_requested.connect(self.speaker_mapper_requested.emit)

        # Master Tab Widget used when in Combined / AI Studio / VideoFX modes
        self.unified_tabs = QTabWidget()
        self.unified_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #262B36; border-radius: 6px; background: #14171E; }
            QTabBar::tab { background: #181C24; color: #94A3B8; padding: 5px 8px; font-size: 11px; font-weight: 700; border-top-left-radius: 5px; border-top-right-radius: 5px; margin-right: 2px; }
            QTabBar::tab:selected { background: #2563EB; color: #FFFFFF; }
        """)

        # Stack: Page 0 = Classic Visual Inspector | Page 1 = AI Studio & VideoFX Inspector Tabs
        self.stack = QStackedWidget()
        self.stack.addWidget(self.classic_widget)
        self.stack.addWidget(self.inspector_tabs)
        layout.addWidget(self.stack, 1)

        self.set_workspace_mode("dub", emit_signal=False)

    def _make_mode_btn(self, text: str, mode_key: str, accent_hex: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setFixedHeight(26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("accent_hex", accent_hex)
        btn.clicked.connect(lambda: self.set_workspace_mode(mode_key, emit_signal=True))
        return btn

    def _refresh_mode_btn_styles(self) -> None:
        mapping = [
            (self.btn_mode_dub, "dub", "#00E5FF"),
            (self.btn_mode_ai, "ai_studio", "#3B82F6"),
            (self.btn_mode_fx, "videofx", "#A855F7"),
            (self.btn_mode_all, "combined", "#10B981"),
        ]
        for btn, key, color in mapping:
            active = (self.current_mode == key)
            btn.blockSignals(True)
            btn.setChecked(active)
            btn.blockSignals(False)
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {color}; color: #0B0D12; border: 1px solid {color}; "
                    f"border-radius: 5px; padding: 2px 6px; font-size: 10.5px; font-weight: 800; }}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background: transparent; color: #94A3B8; border: 1px solid transparent; "
                    "border-radius: 5px; padding: 2px 6px; font-size: 10.5px; font-weight: 700; }"
                    f"QPushButton:hover {{ color: {color}; background: #1A1F2B; }}"
                )

    def set_workspace_mode(self, mode: str, emit_signal: bool = True) -> None:
        self.current_mode = mode
        self._refresh_mode_btn_styles()

        if mode == "dub":
            self.studio_action_bar.setVisible(False)
            self._ensure_classic_in_stack()
            self.stack.setCurrentWidget(self.classic_widget)
        elif mode == "ai_studio":
            self.studio_action_bar.setVisible(True)
            self._ensure_classic_in_stack()
            self.stack.setCurrentWidget(self.inspector_tabs)
            self.inspector_tabs.setCurrentIndex(0)  # Tab 1: Extract & Translate / Tab 2: Recap & Dubbing
        elif mode == "videofx":
            self.studio_action_bar.setVisible(True)
            self._ensure_classic_in_stack()
            self.stack.setCurrentWidget(self.inspector_tabs)
            self.inspector_tabs.setCurrentIndex(2)  # Tab 3: Text FX, Mask & 3D LUTs
        elif mode == "combined":
            self.studio_action_bar.setVisible(True)
            self._activate_combined_tabs()

        if emit_signal:
            self.mode_changed.emit(mode)

    def _ensure_classic_in_stack(self) -> None:
        if self.stack.indexOf(self.classic_widget) == -1:
            self.stack.insertWidget(0, self.classic_widget)
        if self.stack.indexOf(self.inspector_tabs) == -1:
            self.stack.insertWidget(1, self.inspector_tabs)

    def _activate_combined_tabs(self) -> None:
        """Places BOTH Classic Visual Inspector and AI/VideoFX Inspector into one unified QTabWidget."""
        if self.stack.indexOf(self.unified_tabs) == -1:
            self.stack.addWidget(self.unified_tabs)
        self.unified_tabs.clear()
        self.unified_tabs.addTab(self.classic_widget, "🎨 Visual & Sub/Logo")
        self.unified_tabs.addTab(self.inspector_tabs, "🚀 AI Studio & 3D LUT FX")
        self.stack.setCurrentWidget(self.unified_tabs)

    def _on_perf_changed(self, text: str) -> None:
        mode = "low" if "Low-Spec" in text else "high"
        self.settings = HardwareProfiler.apply_performance_profile(mode, self.settings)
        SubtitleSettings.save(self.settings)
        self.perf_profile_changed.emit(mode)

    def _on_inspector_settings_changed(self, new_settings: Dict[str, Any]) -> None:
        self.settings.update(new_settings)
        SubtitleSettings.save(self.settings)

    def _on_render_preview_clicked(self) -> None:
        self.settings.update(self.inspector_tabs.get_settings())
        SubtitleSettings.save(self.settings)
        self.render_preview_requested.emit(self.settings)

    def _on_run_pipeline_clicked(self) -> None:
        self.settings.update(self.inspector_tabs.get_settings())
        SubtitleSettings.save(self.settings)
        self.run_ai_pipeline_requested.emit(self.settings)
