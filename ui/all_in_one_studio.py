# -*- coding: utf-8 -*-
"""
ui/all_in_one_studio.py
4-Zone CapCut-Inspired Desktop Workspace upgraded with 5 Production Modules:
  1. Batch Queue & Auto-Episode Splitter (`BatchQueueDrawer` + `BatchManager`)
  2. Multi-Speaker Role Mapping & Voice FX (`SpeakerMapperDialog` + `VoiceFXProcessor`)
  3. `.vfxproj` Save/Resume + Smart SHA-256 TTS Audio Cache (`ProjectManager` + `SmartTTSCache`)
  4. Dependency & Model Setup Manager (`SetupManagerDialog` + health indicator dot)
  5. GPU Hardware Encoding (`NVENC`/`AMF`/`QSV`) & PC Performance Profiles (`High-Spec` vs `Low-Spec`)
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QPushButton, QComboBox, QLabel, QSplitter, QProgressBar,
    QFileDialog, QMessageBox
)

from config.settings import SubtitleSettings
from core.engine_factory import EngineFactory
from core.batch_manager import BatchManager
from core.project_manager import ProjectManager
from core.hardware_profiler import HardwareProfiler
from core.dependency_checker import DependencyChecker
from core.videofx.text_animator import TextAnimator
from workers.pipeline_worker import StudioPipelineWorker
from ui.widgets.preview_canvas import PreviewCanvas
from ui.widgets.segment_table import SegmentTable
from ui.widgets.inspector_tabs import InspectorTabs
from ui.widgets.batch_queue_drawer import BatchQueueDrawer
from ui.dialogs.speaker_mapper_dialog import SpeakerMapperDialog
from ui.dialogs.setup_manager_dialog import SetupManagerDialog

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class AllInOneStudioWindow(QMainWindow):
    """
    4-Zone All-in-One AI Video, Dubbing, Recap & FX Studio Desktop Shell.
    """

    def __init__(self, parent=None, initial_video_path: Optional[str] = None):
        super().__init__(parent)
        self.setObjectName("StudioRoot")
        self.setWindowTitle("Ai Summarai — All-in-One AI Video, Dubbing, Recap & FX Studio")
        self.resize(1420, 860)
        self.setMinimumSize(1080, 680)
        self.setAcceptDrops(True)

        self.settings = SubtitleSettings.load()
        self.video_path: Optional[str] = initial_video_path if (initial_video_path and os.path.exists(initial_video_path)) else None
        self.current_project_path: Optional[str] = None
        self.output_dir = Path("data/studio_outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="aisummarai_aio_"))
        self.compositor = EngineFactory.create_compositor()
        self.batch_manager = BatchManager()
        self.pipeline_worker: Optional[StudioPipelineWorker] = None

        self._load_theme()
        self._build_4zone_ui()
        self._bind_shortcuts()

        # Debounce timer for live preview updates
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self.render_preview_frame)

        if self.video_path:
            self.load_video(self.video_path)

    def _load_theme(self) -> None:
        qss_path = Path("config/theme.qss")
        if qss_path.exists():
            try:
                self.setStyleSheet(qss_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _build_4zone_ui(self) -> None:
        root = QWidget()
        root.setObjectName("StudioRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # =================================================================
        # ZONE 1: TOP ACTION TOOLBAR (48px height)
        # =================================================================
        toolbar = QFrame()
        toolbar.setObjectName("TopActionToolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 6, 8, 6)
        tb_layout.setSpacing(6)

        self.btn_open = QPushButton("📂 Open Video (Ctrl+O)")
        self.btn_open.clicked.connect(self._on_open_video_dialog)
        tb_layout.addWidget(self.btn_open)

        self.btn_save_proj = QPushButton("💾 Save Project (Ctrl+S)")
        self.btn_save_proj.clicked.connect(self.save_vfxproj_dialog)
        tb_layout.addWidget(self.btn_save_proj)

        self.btn_load_proj = QPushButton("📁 Load Project")
        self.btn_load_proj.clicked.connect(self.load_vfxproj_dialog)
        tb_layout.addWidget(self.btn_load_proj)

        self.combo_preset = QComboBox()
        self.combo_preset.addItems([
            "Full Movie Dubbing",
            "AI Story Recap",
            "Subtitle Extraction Only",
            "VideoFX & LUT Polish",
        ])
        self.combo_preset.currentTextChanged.connect(self._on_preset_changed)
        tb_layout.addWidget(self.combo_preset)

        self.combo_perf_profile = QComboBox()
        self.combo_perf_profile.addItems([
            "High-Spec PC (Max Quality)",
            "Low-Spec PC (4GB VRAM Safe)",
        ])
        if self.settings.get("hardware_profile") == "low":
            self.combo_perf_profile.setCurrentIndex(1)
        self.combo_perf_profile.currentTextChanged.connect(self._on_perf_profile_changed)
        tb_layout.addWidget(self.combo_perf_profile)

        self.btn_setup_models = QPushButton("🟢 Setup & Models")
        self.btn_setup_models.clicked.connect(self.open_setup_manager)
        tb_layout.addWidget(self.btn_setup_models)

        self.lbl_video_badge = QLabel("Ready")
        self.lbl_video_badge.setStyleSheet("color: #9CA3AF; padding-left: 4px;")
        tb_layout.addWidget(self.lbl_video_badge, 1)

        self.btn_render_preview = QPushButton("🖼️ Render Preview Frame")
        self.btn_render_preview.setObjectName("SuccessCTA")
        self.btn_render_preview.clicked.connect(self.render_preview_frame)
        tb_layout.addWidget(self.btn_render_preview)

        self.btn_start = QPushButton("🚀 Start Pipeline (F5)")
        self.btn_start.setObjectName("PrimaryCTA")
        self.btn_start.clicked.connect(self.start_pipeline)
        tb_layout.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("🛑 Cancel (Esc)")
        self.btn_cancel.setObjectName("DangerCTA")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_pipeline)
        tb_layout.addWidget(self.btn_cancel)

        root_layout.addWidget(toolbar)

        # =================================================================
        # ZONE 2 & ZONE 3: WORKSPACE (65%) + 3-TAB INSPECTOR (35%)
        # =================================================================
        main_splitter = QSplitter(Qt.Horizontal)

        # Zone 2: Left/Center Workspace (PreviewCanvas + SegmentTable + BatchQueueDrawer)
        workspace_splitter = QSplitter(Qt.Vertical)
        self.preview_canvas = PreviewCanvas(self)
        self.preview_canvas.time_scrubbed.connect(lambda _ts: self._preview_timer.start())
        workspace_splitter.addWidget(self.preview_canvas)

        self.segment_table = SegmentTable(self)
        self.segment_table.row_selected.connect(self._on_table_row_selected)
        self.segment_table.open_speaker_mapper_requested.connect(self.open_speaker_mapper)
        workspace_splitter.addWidget(self.segment_table)

        self.batch_drawer = BatchQueueDrawer(batch_manager=self.batch_manager, parent=self)
        self.batch_drawer.queue_item_selected.connect(self._on_batch_item_clicked)
        workspace_splitter.addWidget(self.batch_drawer)

        workspace_splitter.setStretchFactor(0, 4)
        workspace_splitter.setStretchFactor(1, 3)
        workspace_splitter.setStretchFactor(2, 2)

        main_splitter.addWidget(workspace_splitter)

        # Zone 3: Right 3-Tab Inspector
        self.inspector_tabs = InspectorTabs(initial_settings=self.settings, parent=self)
        self.inspector_tabs.settings_changed.connect(self._on_inspector_settings_changed)
        self.inspector_tabs.speaker_mapper_requested.connect(self.open_speaker_mapper)
        self.inspector_tabs.emotion_tag_selected.connect(self.segment_table.apply_emotion_to_selected_row)
        main_splitter.addWidget(self.inspector_tabs)

        main_splitter.setStretchFactor(0, 65)
        main_splitter.setStretchFactor(1, 35)
        root_layout.addWidget(main_splitter, 1)

        # =================================================================
        # ZONE 4: BOTTOM STATUS BAR (28-32px height)
        # =================================================================
        status_bar = QFrame()
        status_bar.setObjectName("BottomStatusBar")
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(10, 4, 10, 4)
        sb_layout.setSpacing(10)

        self.lbl_stage = QLabel("Ready — Load a video or click 'Render Preview Frame'")
        self.lbl_stage.setStyleSheet("color: #E5E7EB; font-weight: 600;")
        sb_layout.addWidget(self.lbl_stage)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(220)
        sb_layout.addWidget(self.progress_bar)

        sb_layout.addStretch()

        self.lbl_gpu_badge = QLabel(HardwareProfiler.get_encoder_badge_text())
        self.lbl_gpu_badge.setStyleSheet(
            "background-color: #1E293B; color: #38BDF8; border: 1px solid #334155; "
            "border-radius: 4px; padding: 2px 8px; font-weight: 700; font-size: 11px;"
        )
        sb_layout.addWidget(self.lbl_gpu_badge)

        self.btn_export_srt = QPushButton("📝 Export .SRT")
        self.btn_export_srt.clicked.connect(self._on_export_srt)
        sb_layout.addWidget(self.btn_export_srt)

        self.btn_open_folder = QPushButton("📁 Open Output Folder")
        self.btn_open_folder.clicked.connect(self._on_open_output_folder)
        sb_layout.addWidget(self.btn_open_folder)

        root_layout.addWidget(status_bar)
        self.setCentralWidget(root)

        self._refresh_setup_health_dot()

        # Seed sample preview row so user can immediately test "Render Preview Frame" & ".vfxproj"
        self.segment_table.set_segments([
            {
                "id": 1,
                "start": 0.0,
                "end": 4.0,
                "speaker": "SPEAKER_00",
                "voice_fx": "normal",
                "text": "天道酬勤，万剑归宗！",
                "translated": "សូមស្វាគមន៍មកកាន់ Ai Summarai — ស្ទូឌីយោ AI កាត់ត និងបញ្ចូលសំឡេងខ្មែរ!",
                "dub_audio": "",
            },
            {
                "id": 2,
                "start": 4.2,
                "end": 8.0,
                "speaker": "SPEAKER_01",
                "voice_fx": "inner_thought",
                "text": "难道这就是传说中的神剑？",
                "translated": "តើនេះពិតជាដាវទេពក្នុងរឿងព្រេងមែនទេ?",
                "dub_audio": "",
            },
        ])

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._on_open_video_dialog)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_vfxproj_dialog)
        QShortcut(QKeySequence("F5"), self, activated=self.start_pipeline)
        QShortcut(QKeySequence("Escape"), self, activated=self.cancel_pipeline)

    def _refresh_setup_health_dot(self) -> None:
        ff_ok, _ = DependencyChecker.check_ffmpeg()
        self.btn_setup_models.setText("🟢 Setup & Models" if ff_ok else "🟠 Setup & Models")

    # ------------------------------------------------------------------
    # Modals: Setup & Models Manager + Multi-Speaker Voice Role Mapper
    # ------------------------------------------------------------------
    def open_setup_manager(self) -> None:
        dlg = SetupManagerDialog(
            ollama_url=self.settings.get("ollama_url", "http://localhost:11434"),
            target_model=self.settings.get("model_name", "qwen2.5:7b"),
            parent=self,
        )
        dlg.health_updated.connect(lambda ok: self.btn_setup_models.setText("🟢 Setup & Models" if ok else "🟠 Setup & Models"))
        dlg.exec()

    def open_speaker_mapper(self) -> None:
        dlg = SpeakerMapperDialog(
            speaker_map=self.settings.get("speaker_map", {}),
            detected_speakers=self.segment_table.get_detected_speakers(),
            parent=self,
        )
        dlg.speaker_map_saved.connect(self._on_speaker_map_saved)
        dlg.exec()

    def _on_speaker_map_saved(self, new_map: Dict[str, Dict[str, str]]) -> None:
        self.settings["speaker_map"] = new_map
        SubtitleSettings.save(self.settings)
        self.lbl_stage.setText(f"Updated Speaker Role Mapping ({len(new_map)} speakers).")

    # ------------------------------------------------------------------
    # Save / Load .vfxproj Workspace Persistence
    # ------------------------------------------------------------------
    def save_vfxproj_dialog(self) -> None:
        default_p = self.current_project_path or str(self.output_dir / "movie_project.vfxproj")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Studio Project (.vfxproj)",
            default_p,
            "VideoFX Studio Project (*.vfxproj)",
        )
        if out_path:
            self.save_project_file(out_path)

    def save_project_file(self, project_path: str) -> str:
        self.settings.update(self.inspector_tabs.get_settings())
        self.settings["auto_split_minutes"] = self.batch_drawer.get_auto_split_minutes()
        saved = ProjectManager.save_project(
            project_file_path=project_path,
            video_path=self.video_path or "",
            segments=self.segment_table.get_segments(),
            settings=self.settings,
            speaker_map=self.settings.get("speaker_map", {}),
            batch_items=[it.to_dict() for it in self.batch_manager.items],
        )
        self.current_project_path = saved
        self.lbl_stage.setText(f"💾 Project saved: {Path(saved).name}")
        return saved

    def load_vfxproj_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Studio Project (.vfxproj)",
            str(self.output_dir),
            "VideoFX Studio Project (*.vfxproj)",
        )
        if path and os.path.exists(path):
            self.load_project_file(path)

    def load_project_file(self, project_path: str) -> Dict[str, Any]:
        data = ProjectManager.load_project(project_path)
        self.current_project_path = project_path
        loaded_settings = data.get("settings", {})
        if loaded_settings:
            self.settings.update(loaded_settings)
        if data.get("speaker_map"):
            self.settings["speaker_map"] = data["speaker_map"]
        SubtitleSettings.save(self.settings)

        vpath = data.get("video_path", "")
        if vpath and os.path.exists(vpath):
            self.load_video(vpath)
        self.segment_table.set_segments(data.get("segments", []))
        self.lbl_stage.setText(f"📁 Project loaded: {Path(project_path).name}")
        self.render_preview_frame()
        return data

    # ------------------------------------------------------------------
    # Performance Profile & Drag/Drop Video Loading
    # ------------------------------------------------------------------
    def _on_perf_profile_changed(self, text: str) -> None:
        mode = "low" if "Low-Spec" in text else "high"
        self.settings = HardwareProfiler.apply_performance_profile(mode, self.settings)
        SubtitleSettings.save(self.settings)
        self.lbl_stage.setText(f"Performance Profile switched to: {text}")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return
        if len(paths) == 1 and Path(paths[0]).suffix.lower() == ".vfxproj":
            self.load_project_file(paths[0])
            return
        for p in paths:
            if Path(p).is_dir():
                self.batch_manager.add_folder(p, auto_split_minutes=self.batch_drawer.get_auto_split_minutes())
            else:
                self.batch_manager.add_files([p], auto_split_minutes=self.batch_drawer.get_auto_split_minutes())
        self.batch_drawer.refresh_table()
        if self.batch_manager.items:
            self.load_video(self.batch_manager.items[0].video_path)

    def _on_open_video_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Video File",
            "",
            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm);;All Files (*.*)",
        )
        if path and os.path.exists(path):
            self.batch_manager.add_files([path], auto_split_minutes=self.batch_drawer.get_auto_split_minutes())
            self.batch_drawer.refresh_table()
            self.load_video(path)

    def _on_batch_item_clicked(self, item_dict: Dict[str, Any]) -> None:
        vpath = item_dict.get("video_path", "")
        if vpath and os.path.exists(vpath):
            self.load_video(vpath)
        segs = item_dict.get("segments")
        if segs:
            self.segment_table.set_segments(segs)

    def load_video(self, path: str) -> None:
        self.video_path = path
        dur = BatchManager.probe_duration(path) or 15.0
        self.preview_canvas.set_duration(dur)
        self.lbl_video_badge.setText(f"📹 {Path(path).name} ({dur:.1f}s)")
        self.lbl_stage.setText(f"Loaded: {Path(path).name}")
        self.render_preview_frame()

    # ------------------------------------------------------------------
    # Live Preview Rendering (< 0.5s)
    # ------------------------------------------------------------------
    def render_preview_frame(self) -> bool:
        self.settings.update(self.inspector_tabs.get_settings())
        SubtitleSettings.save(self.settings)

        ass_path = str(self.temp_dir / "preview_overlay.ass")
        TextAnimator.generate_studio_ass(
            segments=self.segment_table.get_segments(),
            out_ass_path=ass_path,
            style_mode=self.settings.get("text_fx_style", "Static Styled Subtitles"),
            bottom_cover_box=bool(self.settings.get("bottom_cover_box", True)),
            font_name=self.settings.get("font_family", "Noto Sans Khmer"),
            font_size=int(self.settings.get("font_size", 46)),
            primary_color=self.settings.get("text_color", "#FFFFFF"),
            outline_color=self.settings.get("outline_color", "#000000"),
            video_duration=max(10.0, self.preview_canvas.duration_sec),
        )

        out_jpg = str(self.temp_dir / "preview_frame.jpg")
        pv_w = int(self.settings.get("preview_w", 960))
        pv_h = int(self.settings.get("preview_h", 540))
        ok = self.compositor.render_preview_frame(
            video_path=self.video_path or "",
            timestamp_sec=self.preview_canvas.current_sec,
            out_jpg_path=out_jpg,
            settings=self.settings,
            ass_path=ass_path,
            target_w=pv_w,
            target_h=pv_h,
        )
        if ok and os.path.exists(out_jpg):
            self.preview_canvas.display_frame(out_jpg)
            self.lbl_stage.setText(f"Preview rendered at {self.preview_canvas.current_sec:.1f}s (LUT + Mask + .ASS)")
            return True
        return False

    # ------------------------------------------------------------------
    # Pipeline Execution & Signals
    # ------------------------------------------------------------------
    def _on_preset_changed(self, preset_name: str) -> None:
        self.inspector_tabs.apply_workflow_preset(preset_name)

    def _on_inspector_settings_changed(self, new_settings: Dict[str, Any]) -> None:
        self.settings.update(new_settings)
        SubtitleSettings.save(self.settings)
        self._preview_timer.start()

    def _on_table_row_selected(self, start_sec: float) -> None:
        self.preview_canvas.current_sec = start_sec
        self.render_preview_frame()

    def start_pipeline(self) -> None:
        pending_batch = self.batch_manager.get_pending_items()
        if not pending_batch and (not self.video_path or not os.path.exists(self.video_path)):
            QMessageBox.information(
                self,
                "Open Video First",
                "សូមជ្រើសរើសវីដេអូជាមុនសិន (Click 'Open Video (Ctrl+O)' or add files to the Batch Queue).",
            )
            return

        if self.pipeline_worker and self.pipeline_worker.isRunning():
            return

        self.settings.update(self.inspector_tabs.get_settings())
        SubtitleSettings.save(self.settings)

        self.btn_start.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.progress_bar.setValue(0)

        self.pipeline_worker = StudioPipelineWorker(
            video_path=self.video_path or (pending_batch[0].video_path if pending_batch else ""),
            settings=self.settings,
            existing_segments=self.segment_table.get_segments(),
            output_dir=str(self.output_dir),
            batch_queue=pending_batch if len(pending_batch) > 1 else None,
            parent=self,
        )
        self.pipeline_worker.progress_updated.connect(self._on_pipeline_progress)
        self.pipeline_worker.stage_changed.connect(self.lbl_stage.setText)
        self.pipeline_worker.preview_ready.connect(lambda jpg, _ts: self.preview_canvas.display_frame(jpg))
        self.pipeline_worker.segment_updated.connect(self.segment_table.set_segments)
        self.pipeline_worker.batch_item_updated.connect(self.batch_drawer.update_item_status)
        self.pipeline_worker.finished.connect(self._on_pipeline_finished)
        self.pipeline_worker.failed.connect(self._on_pipeline_failed)
        self.pipeline_worker.start()

    def cancel_pipeline(self) -> None:
        if self.pipeline_worker and self.pipeline_worker.isRunning():
            self.pipeline_worker.cancel()
            self.pipeline_worker.wait(1500)
        self.btn_start.setVisible(True)
        self.btn_cancel.setVisible(False)
        self.lbl_stage.setText("Pipeline cancelled by user.")

    def _on_pipeline_progress(self, pct: int, msg: str) -> None:
        self.progress_bar.setValue(pct)
        self.lbl_stage.setText(msg)

    def _on_pipeline_finished(self, out_mp4: str, final_segments: List[Dict[str, Any]]) -> None:
        self.btn_start.setVisible(True)
        self.btn_cancel.setVisible(False)
        self.progress_bar.setValue(100)
        self.segment_table.set_segments(final_segments)
        self.render_preview_frame()
        QMessageBox.information(
            self,
            "Pipeline Complete",
            f"ការផលិតវីដេអូបានបញ្ចប់ដោយជោគជ័យ!\nOutput: {out_mp4}",
        )

    def _on_pipeline_failed(self, err_msg: str) -> None:
        self.btn_start.setVisible(True)
        self.btn_cancel.setVisible(False)
        self.lbl_stage.setText(f"Error: {err_msg}")
        QMessageBox.warning(self, "Pipeline Notice", err_msg)

    def _on_export_srt(self) -> None:
        segs = self.segment_table.get_segments()
        if not segs:
            QMessageBox.information(self, "Export .SRT", "គ្មានទិន្នន័យ Subtitle ក្នុងតារាងទេ។")
            return
        default_path = str(self.output_dir / "subtitles_kh.srt")
        out_path, _ = QFileDialog.getSaveFileName(self, "Export .SRT", default_path, "SRT Subtitle (*.srt)")
        if out_path:
            self.segment_table.export_srt(out_path, use_translated=True)
            self.lbl_stage.setText(f"Exported SRT: {Path(out_path).name}")

    def _on_open_output_folder(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_dir.resolve())))
