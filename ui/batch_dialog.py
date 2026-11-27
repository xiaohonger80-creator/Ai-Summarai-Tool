import gc
from pathlib import Path
from typing import List
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QLabel, QLineEdit,
    QProgressBar, QComboBox, QMessageBox
)
from core.database import Database, DB_PATH
from core.long_video_engine import LongVideoStreamEngine
from core.media_engine import MediaEngine
from core.ocr_scanner import SubtitleOCRScanner
from core.transcriber import SpeechTranscriber
from core.translator import ZHtoKHTranslator
from core.tts_engine import KhmerTTSEngine
from core.srt_handler import SRTHandler
from ui.i18n import tr


class BatchDubbingWorker(QThread):
    row_status = Signal(int, str)          # (row_index, status_text)
    overall_progress = Signal(int, str)    # (percent, status_message)
    finished_batch = Signal(int, int)      # (success_count, total_count)

    def __init__(
        self,
        video_paths: List[str],
        out_dir: str,
        extract_mode: str,
        bgm_volume: float,
        db_path: Path,
    ):
        super().__init__()
        self.video_paths = video_paths
        self.out_dir = Path(out_dir)
        self.extract_mode = extract_mode
        self.bgm_volume = bgm_volume
        self.db_path = db_path
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        db = Database(self.db_path)
        asr_mode = int(db.get_setting("asr_mode", "0"))
        api_url = db.get_setting("api_url", "google-free")
        api_key = db.get_setting("api_key", "")
        model = db.get_setting("model", "google-free")
        voice_label = db.get_setting("kh_voice_label", "Female (Sreymom)")
        default_voice = KhmerTTSEngine.VOICES.get(voice_label, "km-KH-SreymomNeural")
        crop_y = int(db.get_setting("ocr_y_pct", "72")) / 100.0
        crop_h = int(db.get_setting("ocr_h_pct", "28")) / 100.0

        translator = ZHtoKHTranslator(api_key=api_key, base_url=api_url, model=model)
        tts = KhmerTTSEngine()
        asr = SpeechTranscriber() if self.extract_mode == "voice" else None
        ocr = SubtitleOCRScanner() if self.extract_mode == "ocr" else None

        total = len(self.video_paths)
        ok_count = 0

        for idx, vpath in enumerate(self.video_paths):
            if self._stop_requested:
                self.row_status.emit(idx, "⏹ Stopped")
                continue

            vfile = Path(vpath)
            base_pct = int((idx / max(1, total)) * 100)

            try:
                # 1. Create Project in SQLite
                self.row_status.emit(idx, "1/4 Scanning ZH...")
                self.overall_progress.emit(base_pct + 5, f"[{idx+1}/{total}] Scanning: {vfile.name}")
                proj_id = db.create_project(vfile.stem, str(vfile), self.extract_mode)
                work_dir = Path(f"data/workspace/proj_{proj_id}")

                if self.extract_mode == "voice":
                    items = LongVideoStreamEngine.stream_voice_long_video(
                        video_path=str(vfile),
                        work_dir=str(work_dir),
                        transcriber=asr,
                        mode="local" if asr_mode == 0 else "api",
                        api_cfg={"api_key": api_key, "base_url": api_url, "whisper_model": "base"},
                    )
                else:
                    items = LongVideoStreamEngine.stream_ocr_long_video(
                        video_path=str(vfile),
                        work_dir=str(work_dir),
                        scanner=ocr,
                        fps=4,
                        crop_ratio=crop_h,
                        crop_y_offset=crop_y,
                    )

                if not items:
                    self.row_status.emit(idx, "⚠ No speech/text found")
                    continue

                db.insert_segments(proj_id, items)

                if self._stop_requested:
                    self.row_status.emit(idx, "⏹ Stopped")
                    continue

                # 2. Translate ZH -> KH
                self.row_status.emit(idx, f"2/4 Translating ({len(items)} lines)...")
                self.overall_progress.emit(base_pct + 10, f"[{idx+1}/{total}] Translating: {vfile.name}")
                saved_segs = db.get_segments(proj_id)
                translated = translator.translate_batch(saved_segs)
                for seg_id, kh_text in translated.items():
                    db.update_segment(seg_id, kh_text=kh_text, status="Ready")

                if self._stop_requested:
                    self.row_status.emit(idx, "⏹ Stopped")
                    continue

                # 3. Synthesize Khmer TTS (Using Auto-Detected Male/Female voice per line)
                self.row_status.emit(idx, "3/4 Generating KH Voice...")
                self.overall_progress.emit(base_pct + 15, f"[{idx+1}/{total}] Generating Voice: {vfile.name}")
                clip_dir = work_dir / "tts"
                clip_dir.mkdir(parents=True, exist_ok=True)

                for seg in db.get_segments(proj_id):
                    if self._stop_requested:
                        break
                    kh_text = (seg.get("kh_text") or "").strip()
                    if not kh_text:
                        continue
                    chosen_voice = seg.get("voice_override") or default_voice
                    clip_path = str(clip_dir / f"seg_{seg['id']}.wav")
                    dur_ms = seg["end_ms"] - seg["start_ms"]
                    tts.generate_clip(kh_text, chosen_voice, dur_ms, clip_path)
                    db.update_segment(seg["id"], tts_audio_path=clip_path, status="Voiced")

                if self._stop_requested:
                    self.row_status.emit(idx, "⏹ Stopped")
                    continue

                # 4. Export Video + Khmer SRT
                self.row_status.emit(idx, "4/4 Exporting MP4 + SRT...")
                self.overall_progress.emit(base_pct + 20, f"[{idx+1}/{total}] Exporting: {vfile.name}")
                self.out_dir.mkdir(parents=True, exist_ok=True)
                out_mp4 = str(self.out_dir / f"{vfile.stem}_KH.mp4")
                out_srt = str(self.out_dir / f"{vfile.stem}_KH.srt")

                final_segs = db.get_segments(proj_id)
                MediaEngine.render_final_video(
                    str(vfile), final_segs, out_mp4, bgm_volume=self.bgm_volume
                )
                SRTHandler.export_srt(final_segs, out_srt, mode="kh")

                ok_count += 1
                self.row_status.emit(idx, "✅ Done")

            except Exception as e:
                self.row_status.emit(idx, f"❌ Error: {str(e)[:35]}")

            # Free memory after each video to keep low-spec laptops smooth
            gc.collect()

        self.overall_progress.emit(100, "Finished")
        self.finished_batch.emit(ok_count, total)


class BatchDubbingDialog(QDialog):
    MAX_VIDEOS = 50

    def __init__(self, db: Database, lang: str = "en", bgm_volume: float = 0.25, parent=None):
        super().__init__(parent)
        self.db = db
        self.lang = lang
        self.bgm_volume = bgm_volume
        self.video_paths: List[str] = []
        self.worker = None

        self.setWindowTitle(tr(lang, "batch_title"))
        self.resize(760, 480)
        self._build_ui()

    def _build_ui(self):
        L = self.lang
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Top Controls: Add Videos + Mode + Clear
        top = QHBoxLayout()
        self.btn_add = QPushButton(tr(L, "batch_add"))
        self.btn_add.setObjectName("PrimaryBtn")
        self.btn_add.clicked.connect(self._add_videos)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([tr(L, "mode_voice"), tr(L, "mode_ocr")])

        self.btn_clear = QPushButton(tr(L, "batch_clear"))
        self.btn_clear.clicked.connect(self._clear_list)

        top.addWidget(self.btn_add)
        top.addWidget(self.mode_combo)
        top.addStretch()
        top.addWidget(self.btn_clear)
        layout.addLayout(top)

        # Video Queue Table
        self.table = QTableWidget(0, 3)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setHorizontalHeaderLabels([
            "#", tr(L, "batch_col_file"), tr(L, "batch_col_status")
        ])
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(2, 220)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        # Output Folder Selector
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(tr(L, "batch_folder")))
        default_out = self.db.get_setting("batch_out_dir", str(Path.home() / "Videos" / "KH_Dubbed"))
        self.out_dir_input = QLineEdit(default_out)
        btn_browse = QPushButton(tr(L, "batch_browse"))
        btn_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.out_dir_input, 1)
        folder_row.addWidget(btn_browse)
        layout.addLayout(folder_row)

        # Progress & Start/Stop Footer
        bottom = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("StatusLbl")
        self.pbar = QProgressBar()
        self.pbar.setFixedWidth(180)

        self.btn_stop = QPushButton(tr(L, "batch_stop"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_batch)

        self.btn_start = QPushButton(tr(L, "batch_start"))
        self.btn_start.setObjectName("SuccessBtn")
        self.btn_start.clicked.connect(self._start_batch)

        bottom.addWidget(self.lbl_status, 1)
        bottom.addWidget(self.pbar)
        bottom.addWidget(self.btn_stop)
        bottom.addWidget(self.btn_start)
        layout.addLayout(bottom)

    def _add_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr(self.lang, "batch_add"), "", "Videos (*.mp4 *.mkv *.mov *.avi)"
        )
        if not files:
            return

        remaining = self.MAX_VIDEOS - len(self.video_paths)
        if remaining <= 0 or len(files) > remaining:
            QMessageBox.information(self, tr(self.lang, "batch_title"), tr(self.lang, "batch_limit_warn"))

        for f in files[:max(0, remaining)]:
            if f not in self.video_paths:
                self.video_paths.append(f)

        self._refresh_table()

    def _clear_list(self):
        if self.worker and self.worker.isRunning():
            return
        self.video_paths.clear()
        self._refresh_table()

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr(self.lang, "batch_browse"), self.out_dir_input.text())
        if folder:
            self.out_dir_input.setText(folder)
            self.db.set_setting("batch_out_dir", folder)

    def _refresh_table(self):
        self.table.setRowCount(len(self.video_paths))
        for i, path in enumerate(self.video_paths):
            num = QTableWidgetItem(str(i + 1))
            num.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, num)
            self.table.setItem(i, 1, QTableWidgetItem(Path(path).name))
            self.table.setItem(i, 2, QTableWidgetItem("⏳ Waiting"))

    def _start_batch(self):
        if not self.video_paths:
            return
        out_dir = self.out_dir_input.text().strip()
        self.db.set_setting("batch_out_dir", out_dir)

        mode = "voice" if self.mode_combo.currentIndex() == 0 else "ocr"
        self.btn_start.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.pbar.setValue(0)

        self.worker = BatchDubbingWorker(
            self.video_paths, out_dir, mode, self.bgm_volume, DB_PATH
        )
        self.worker.row_status.connect(lambda r, st: self.table.setItem(r, 2, QTableWidgetItem(st)))
        self.worker.overall_progress.connect(lambda pct, msg: (self.pbar.setValue(pct), self.lbl_status.setText(msg)))
        self.worker.finished_batch.connect(self._on_batch_done)
        self.worker.start()

    def _stop_batch(self):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.btn_stop.setEnabled(False)
            self.lbl_status.setText("Stopping after current step...")

    def _on_batch_done(self, ok_count: int, total: int):
        self.btn_start.setEnabled(True)
        self.btn_add.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText(tr(self.lang, "batch_done", ok=ok_count, total=total))
