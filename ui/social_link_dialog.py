"""
ui/social_link_dialog.py - Dialog for importing videos from Social Links
Supports TikTok, Douyin (抖音), YouTube / Shorts, Facebook, Instagram, X (Twitter), Bilibili.
Extracts up to 50 links, downloads high-quality MP4s without watermarks, and imports to workspace.
"""

import threading
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QPlainTextEdit, QProgressBar, QRadioButton, QButtonGroup,
    QMessageBox, QApplication, QFrame
)

from core.social_downloader import SocialVideoDownloader


class SocialDownloadWorker(QThread):
    progress_signal = Signal(dict)
    log_signal = Signal(str)
    completed_signal = Signal(list)
    failed_signal = Signal(str)

    def __init__(self, urls: list, output_dir: str):
        super().__init__()
        self.urls = urls
        self.output_dir = output_dir
        self.stop_event = threading.Event()

    def run(self):
        try:
            files = SocialVideoDownloader.download_urls(
                urls=self.urls,
                output_dir=self.output_dir,
                progress_cb=lambda data: self.progress_signal.emit(data),
                log_cb=lambda msg: self.log_signal.emit(msg),
                stop_event=self.stop_event
            )
            self.completed_signal.emit(files)
        except Exception as e:
            self.failed_signal.emit(str(e))

    def cancel(self):
        self.stop_event.set()


class SocialLinkImportDialog(QDialog):
    """
    Dialog សម្រាប់បិទភ្ជាប់ Links ពី TikTok, Douyin, YouTube, Facebook...
    រួចទាញយកវីដេអូ MP4 ស្អាតឥត Watermark ចូលក្នុង Timeline ភ្លាមៗ!
    """
    import_requested = Signal(list, bool)  # (paths, should_merge)

    def __init__(self, parent=None, output_dir: str = "data/downloads"):
        super().__init__(parent)
        self.output_dir = output_dir
        self.worker = None

        self.setWindowTitle("🔗 នាំចូលវីដេអូពី Social Link (TikTok, Douyin, YouTube, FB...)")
        self.setMinimumSize(580, 500)
        self.setStyleSheet("""
            QDialog { background-color: #111318; color: #FFFFFF; font-family: 'Segoe UI', 'Khmer OS Siemreap'; }
            QLabel { color: #E5E7EB; }
            QPlainTextEdit {
                background-color: #1A1D24;
                color: #00F5D4;
                border: 1px solid #2D3748;
                border-radius: 6px;
                padding: 8px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
            }
            QPushButton {
                background-color: #1E232E;
                color: #E2E8F0;
                border: 1px solid #3B4252;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #2E3440; border-color: #00F5D4; }
            QPushButton#BtnPrimary {
                background-color: #00C4CC;
                color: #0B0E14;
                border: none;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 18px;
            }
            QPushButton#BtnPrimary:hover { background-color: #00F5D4; }
            QProgressBar {
                border: 1px solid #2D3748;
                border-radius: 5px;
                text-align: center;
                background-color: #1A1D24;
                color: #FFFFFF;
                font-weight: bold;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #00C4CC;
                border-radius: 4px;
            }
            QRadioButton {
                color: #E2E8F0;
                font-size: 12px;
                spacing: 8px;
            }
            QRadioButton::indicator:checked {
                background-color: #00C4CC;
                border: 2px solid #FFFFFF;
                border-radius: 6px;
            }
        """)

        self._build_ui()
        self._check_clipboard_on_start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        # Header
        lbl_hdr = QLabel("📥 នាំចូលវីដេអូពី Social Link (TikTok / Douyin / YouTube / FB / IG)")
        lbl_hdr.setStyleSheet("font-size: 14px; font-weight: bold; color: #00C4CC;")
        layout.addWidget(lbl_hdr)

        lbl_sub = QLabel(
            "កម្មវិធីនឹងស្រង់យក Links ស្អាតៗដោយស្វ័យប្រវត្តិ (គាំទ្ររហូតដល់ ៥០ Links ព្រមគ្នា) "
            "ហើយទាញយកវីដេអូកម្រិតច្បាស់ឥត Watermark!"
        )
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addWidget(lbl_sub)

        # Tool strip for Text Edit
        action_bar = QHBoxLayout()
        self.lbl_count = QLabel("រកឃើញ: 0 Links")
        self.lbl_count.setStyleSheet("color: #F59E0B; font-weight: bold;")

        btn_paste = QPushButton("📋 បិទភ្ជាប់ (Paste)")
        btn_paste.clicked.connect(self._paste_clipboard)

        btn_clear = QPushButton("🧹 សម្អាត (Clear)")
        btn_clear.clicked.connect(self._clear_text)

        action_bar.addWidget(self.lbl_count)
        action_bar.addStretch()
        action_bar.addWidget(btn_paste)
        action_bar.addWidget(btn_clear)
        layout.addLayout(action_bar)

        # Multi-line Text Area
        self.txt_urls = QPlainTextEdit()
        self.txt_urls.setPlaceholderText(
            "បិទភ្ជាប់ Link វីដេអូនៅទីនេះ... ឧទាហរណ៍៖\n"
            "https://v.douyin.com/xyz/\n"
            "https://www.tiktok.com/@user/video/123456789\n"
            "https://www.youtube.com/shorts/abcdef123\n"
            "(អាច Copy អត្ថបទដែលមាន Link មក Paste បាន កម្មវិធីនឹងរើសតែ Link សុទ្ធដោយស្វ័យប្រវត្តិ)"
        )
        self.txt_urls.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.txt_urls, 1)

        # Import Mode Options
        mode_box = QFrame()
        mode_box.setStyleSheet("background-color: #161A22; border-radius: 6px; padding: 6px;")
        mode_v = QVBoxLayout(mode_box)
        mode_v.setContentsMargins(8, 6, 8, 6)
        mode_v.setSpacing(6)

        lbl_mode = QLabel("⚙ ជម្រើសនៃការបញ្ចូលទៅកាន់ Studio:")
        lbl_mode.setStyleSheet("font-weight: bold; color: #E5E7EB; font-size: 11px;")
        mode_v.addWidget(lbl_mode)

        self.radio_merge = QRadioButton("🎬 បញ្ចូលជាភាគបន្តគ្នាលើ Timeline តែមួយ (Auto-Merge All)")
        self.radio_merge.setChecked(True)
        self.radio_merge.setToolTip("ភ្ជាប់វីដេអូទាំងអស់បញ្ចូលគ្នាជាគម្រោងសម្រាយរឿងតែមួយដោយស្វ័យប្រវត្តិ")

        self.radio_single = QRadioButton("📁 បើកវីដេអូដំបូង ហើយរក្សាទុកវីដេអូផ្សេងទៀតក្នុង Folder")
        self.radio_single.setToolTip("បើកវីដេអូទីមួយមកកាត់តភ្លាមៗ ហើយឯកសារផ្សេងទៀតរក្សាទុកក្នុងកុំព្យូទ័រ")

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_merge)
        self.mode_group.addButton(self.radio_single)

        mode_v.addWidget(self.radio_merge)
        mode_v.addWidget(self.radio_single)
        layout.addWidget(mode_box)

        # Progress Section
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #10B981; font-size: 11px; font-weight: 600;")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_cancel = QPushButton("បោះបង់ (Cancel)")
        self.btn_cancel.clicked.connect(self._on_cancel)

        self.btn_start = QPushButton("🚀 ចាប់ផ្តើមទាញយក (Download)")
        self.btn_start.setObjectName("BtnPrimary")
        self.btn_start.clicked.connect(self._start_download)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_start)
        layout.addLayout(btn_layout)

    def _check_clipboard_on_start(self):
        cb = QApplication.clipboard()
        text = cb.text()
        if text and ("http://" in text or "https://" in text):
            urls = SocialVideoDownloader.extract_urls(text, max_count=50)
            if urls:
                self.txt_urls.setPlainText("\n".join(urls))

    def _paste_clipboard(self):
        cb = QApplication.clipboard()
        text = cb.text()
        if text:
            urls = SocialVideoDownloader.extract_urls(text, max_count=50)
            if urls:
                cur_text = self.txt_urls.toPlainText().strip()
                if cur_text:
                    self.txt_urls.setPlainText(cur_text + "\n" + "\n".join(urls))
                else:
                    self.txt_urls.setPlainText("\n".join(urls))
            else:
                self.txt_urls.appendPlainText(text)

    def _clear_text(self):
        self.txt_urls.clear()

    def _on_text_changed(self):
        text = self.txt_urls.toPlainText()
        urls = SocialVideoDownloader.extract_urls(text, max_count=50)
        self.lbl_count.setText(f"រកឃើញ: {len(urls)} Links" + (" (កម្រិតអតិបរមា 50)" if len(urls) >= 50 else ""))
        if len(urls) > 1:
            self.radio_merge.setText(f"🎬 បញ្ចូលវីដេអូទាំង {len(urls)} ជាភាគបន្តគ្នាលើ Timeline តែមួយ (Auto-Merge All)")
        else:
            self.radio_merge.setText("🎬 បញ្ចូលជាភាគបន្តគ្នាលើ Timeline តែមួយ (Auto-Merge All)")

    def _start_download(self):
        text = self.txt_urls.toPlainText()
        urls = SocialVideoDownloader.extract_urls(text, max_count=50)

        if not urls:
            QMessageBox.warning(
                self, "គ្មាន Link",
                "សូមបិទភ្ជាប់ Link វីដេអូយ៉ាងតិចមួយ (TikTok, Douyin, YouTube, FB, IG...)"
            )
            return

        self.btn_start.setEnabled(False)
        self.btn_cancel.setText("⏹ ផ្អាកការទាញយក (Stop)")
        self.txt_urls.setReadOnly(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(f"កំពុងរៀបចំទាញយក {len(urls)} វីដេអូ...")

        self.worker = SocialDownloadWorker(urls, self.output_dir)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.log_signal.connect(self._on_log)
        self.worker.completed_signal.connect(self._on_completed)
        self.worker.failed_signal.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, data: dict):
        idx = data.get("index", 1)
        tot = data.get("total", 1)
        pct = data.get("percent", 0.0)
        spd = data.get("speed_bytes", 0) or 0
        eta = data.get("eta_sec", 0) or 0
        fn = data.get("filename", "")

        spd_mb = round(spd / (1024 * 1024), 2)
        overall_pct = int(((idx - 1) / float(tot)) * 100.0 + (pct / float(tot)))
        self.progress_bar.setValue(min(100, max(0, overall_pct)))

        self.lbl_status.setText(
            f"កំពុងទាញយក [{idx}/{tot}]: {pct:.1f}% ({spd_mb} MB/s, ETA: {eta}s) — {fn[:30]}"
        )

    def _on_log(self, msg: str):
        self.lbl_status.setText(msg)

    def _on_completed(self, downloaded_files: list):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setText("បិទ (Close)")
        self.txt_urls.setReadOnly(False)

        if not downloaded_files:
            QMessageBox.warning(
                self, "ទាញយកមិនបាន",
                "មិនអាចទាញយកវីដេអូបានទេ។ សូមពិនិត្យមើល Link ឬការតភ្ជាប់ Internet ឡើងវិញ។"
            )
            return

        should_merge = self.radio_merge.isChecked() and len(downloaded_files) > 1
        self.import_requested.emit(downloaded_files, should_merge)
        self.accept()

    def _on_failed(self, err_msg: str):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setText("បោះបង់ (Cancel)")
        self.txt_urls.setReadOnly(False)
        QMessageBox.critical(self, "កំហុស", f"ការទាញយកជួបបញ្ហា: {err_msg}")

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lbl_status.setText("កំពុងផ្អាក...")
            self.worker.wait(2000)
        self.reject()
