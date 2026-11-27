from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QProgressBar, QMessageBox, QTextEdit, QFrame
)
from core.updater import (
    InAppPackageUpdater, APP_VERSION,
    GITHUB_REPO_URL, GITHUB_MANIFEST_URL,
    get_updater_config,
)


class CheckUpdateWorker(QThread):
    finished = Signal(object)

    def __init__(self, url_or_path: str):
        super().__init__()
        self.url_or_path = url_or_path

    def run(self):
        try:
            res = InAppPackageUpdater.check_for_updates(self.url_or_path)
            self.finished.emit(res)
        except Exception as e:
            self.finished.emit(e)


class DownloadUpdateWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, url_or_path: str):
        super().__init__()
        self.url_or_path = url_or_path

    def run(self):
        try:
            res = InAppPackageUpdater.download_and_apply_package(
                self.url_or_path,
                progress_cb=lambda p, msg: self.progress.emit(p, msg),
            )
            self.finished_ok.emit(res or "")
        except Exception as e:
            self.failed.emit(str(e))


class PackageUpdaterDialog(QDialog):
    """
    ផ្ទាំងទាញយកការ Update កូដ (In-App GitHub Hot-Update Package)
    - ភ្ជាប់ផ្ទាល់ទៅកាន់ GitHub Official Server (xiaohonger80-creator/Ai-Summarai-Tool)
    - User អាចចុចពិនិត្យកំណែថ្មីពី GitHub ឬជ្រើសរើសឯកសារ .zip ដោយផ្ទាល់
    """

    def __init__(self, db, lang: str = "kh", run_worker_fn=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.lang = lang
        self.run_worker_fn = run_worker_fn
        self.cfg = get_updater_config()
        self.selected_local_zip = ""
        self._check_worker = None
        self._dl_worker = None

        kh = lang == "kh"
        self.setWindowTitle(
            f"🔄 ប្រព័ន្ធទាញយកការ Update កូដ (GitHub) — v{APP_VERSION}" if kh
            else f"🔄 In-App Code Updater (GitHub) — v{APP_VERSION}"
        )
        self.resize(640, 520)
        self._build_ui()

    def _get_cloud_url(self) -> str:
        """Returns the official GitHub manifest/repository update URL."""
        return (
            self.cfg.get("manifest_url")
            or self.cfg.get("github_repo_url")
            or GITHUB_MANIFEST_URL
        )

    def _get_repo_display(self) -> str:
        repo = self.cfg.get("github_repo_url") or GITHUB_REPO_URL
        return repo.replace("https://github.com/", "").rstrip("/")

    def _build_ui(self):
        kh = self.lang == "kh"
        self.setStyleSheet(
            "QDialog { background-color: #0B0D10; color: #F4F6FB; "
            "font-family: 'Inter', 'Kantumruy Pro', 'Noto Sans Khmer', 'Segoe UI'; }"
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(22, 22, 22, 22)

        # 1. Header Info Card
        header = QFrame()
        header.setObjectName("UpdateHeaderCard")
        header.setStyleSheet(
            "QFrame#UpdateHeaderCard { background: rgba(16, 185, 129, 0.08); "
            "border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 8px; padding: 12px; }"
        )
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 8)
        h_layout.setSpacing(4)

        lbl_title = QLabel(
            f"🚀 Ai Summarai Studio — កំណែបច្ចុប្បន្ន៖ v{APP_VERSION}" if kh
            else f"🚀 Ai Summarai Studio — Current Version: v{APP_VERSION}"
        )
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #10B981; border: none; background: transparent;")

        lbl_desc = QLabel(
            "អាប់ដេតមុខងារ និងកូដថ្មីភ្លាមៗដោយស្វ័យប្រវត្តិពី GitHub "
            "និងរក្សាទុកទិន្នន័យគម្រោងចាស់ៗរបស់អ្នក ១០០%!" if kh else
            "Update code instantly from GitHub without re-downloading the full installer. "
            "100% of your projects and settings are preserved!"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #8E95A5; font-size: 12px; line-height: 1.4; border: none; background: transparent;")

        h_layout.addWidget(lbl_title)
        h_layout.addWidget(lbl_desc)
        layout.addWidget(header)

        # 2. GitHub Server Status Card
        repo_slug = self._get_repo_display()
        server_card = QFrame()
        server_card.setObjectName("UpdateServerCard")
        server_card.setStyleSheet(
            "QFrame#UpdateServerCard { background: #12151B; border: 1px solid #252A36; border-radius: 8px; padding: 12px; }"
        )
        s_layout = QVBoxLayout(server_card)
        s_layout.setContentsMargins(10, 8, 10, 8)
        s_layout.setSpacing(6)

        lbl_server_title = QLabel(
            f"🐙 ប្រភពទាញយក៖ GitHub Official Server ({repo_slug})" if kh
            else f"🐙 Source: Official GitHub Server ({repo_slug})"
        )
        lbl_server_title.setStyleSheet("font-weight: 700; color: #00E5FF; font-size: 13px; border: none; background: transparent;")

        lbl_server_info = QLabel(
            "• ភ្ជាប់ដោយផ្ទាល់ទៅកាន់ GitHub Repository ផ្លូវការ (លឿន មានស្ថេរភាព និងគ្មានដែនកំណត់ Google Drive)\n"
            "• អ្នកអាចចុច 'ពិនិត្យមើលកំណែថ្មី' ពី GitHub ឬជ្រើសរើសឯកសារ .zip ពីកុំព្យូទ័រដោយផ្ទាល់"
            if kh else
            "• Directly connected to the official GitHub Repository (fast, reliable, no Google Drive limits)\n"
            "• Check for updates directly from GitHub or select a local .zip archive"
        )
        lbl_server_info.setStyleSheet("color: #8E95A5; font-size: 11px; line-height: 1.4; border: none; background: transparent;")
        lbl_server_info.setWordWrap(True)

        s_layout.addWidget(lbl_server_title)
        s_layout.addWidget(lbl_server_info)
        layout.addWidget(server_card)

        # 3. Local Zip Selector Row
        local_row = QHBoxLayout()
        local_row.setSpacing(8)

        self.btn_browse = QPushButton("📂 ជ្រើសរើសឯកសារ .zip ដោយផ្ទាល់" if kh else "📂 Select Local .zip File")
        self.btn_browse.setStyleSheet(
            "background-color: #181C24; color: #F4F6FB; border: 1px solid #252A36; "
            "padding: 8px 14px; font-weight: 600; border-radius: 6px;"
        )
        self.btn_browse.clicked.connect(self._browse_zip)

        self.lbl_selected_file = QLabel(
            "🐙 ប្រើប្រាស់ GitHub Official Server (លំនាំដើម)" if kh
            else "🐙 Using Official GitHub Server (Default)"
        )
        self.lbl_selected_file.setStyleSheet("color: #10B981; font-size: 12px; font-weight: 600;")
        self.lbl_selected_file.setWordWrap(True)

        self.btn_clear_local = QPushButton("✕")
        self.btn_clear_local.setToolTip("ត្រឡប់ទៅប្រើ GitHub Server វិញ")
        self.btn_clear_local.setFixedWidth(28)
        self.btn_clear_local.setVisible(False)
        self.btn_clear_local.setStyleSheet(
            "background: #252A36; color: #EF4444; border-radius: 4px; font-weight: 800;"
        )
        self.btn_clear_local.clicked.connect(self._clear_local_selection)

        local_row.addWidget(self.btn_browse)
        local_row.addWidget(self.lbl_selected_file, 1)
        local_row.addWidget(self.btn_clear_local)
        layout.addLayout(local_row)

        # 4. Check Updates Button & Status
        check_row = QHBoxLayout()
        check_row.setSpacing(10)

        self.btn_check = QPushButton(
            "🔍 ពិនិត្យមើលកំណែថ្មី (Check GitHub)" if kh else "🔍 Check GitHub Updates"
        )
        self.btn_check.setStyleSheet(
            "padding: 8px 16px; font-weight: 700; background-color: #7C3AED; "
            "color: white; border-radius: 6px; border: none;"
        )
        self.btn_check.clicked.connect(self._check_for_updates)

        self.lbl_check_status = QLabel("")
        self.lbl_check_status.setStyleSheet("font-weight: 700; font-size: 12px;")

        check_row.addWidget(self.btn_check)
        check_row.addWidget(self.lbl_check_status, 1)
        layout.addLayout(check_row)

        # 5. Changelog / Release Info Area
        self.txt_changelog = QTextEdit()
        self.txt_changelog.setReadOnly(True)
        self.txt_changelog.setPlaceholderText(
            "ព័ត៌មានពីការកែប្រែថ្មីៗ (Changelog) ពី GitHub នឹងបង្ហាញនៅទីនេះ..." if kh
            else "Changelog and release details from GitHub will appear here..."
        )
        self.txt_changelog.setFixedHeight(130)
        self.txt_changelog.setStyleSheet(
            "background: #12151B; border: 1px solid #252A36; border-radius: 6px; "
            "font-size: 12px; line-height: 1.5; color: #F4F6FB;"
        )
        layout.addWidget(self.txt_changelog)

        # 6. Progress Section
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { height: 14px; border-radius: 7px; background: #181C24; "
            "text-align: center; color: #F4F6FB; } "
            "QProgressBar::chunk { background-color: #10B981; border-radius: 7px; }"
        )
        layout.addWidget(self.progress)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #00E5FF; font-weight: 600; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        # 7. Bottom Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_close = QPushButton("បិទ" if kh else "Close")
        btn_close.setStyleSheet(
            "background: #181C24; color: #8E95A5; border: 1px solid #252A36; "
            "padding: 8px 16px; border-radius: 6px;"
        )
        btn_close.clicked.connect(self.reject)

        self.btn_install_pkg = QPushButton(
            "⬇️ ទាញយក និងអាប់ដេតឥឡូវនេះ" if kh else "⬇️ Download && Apply Update"
        )
        self.btn_install_pkg.setObjectName("BtnGreen")
        self.btn_install_pkg.setStyleSheet(
            "background-color: #10B981; color: #0B0D10; font-weight: 700; "
            "padding: 8px 20px; border-radius: 6px; border: none;"
        )
        self.btn_install_pkg.clicked.connect(self._start_update)

        btn_row.addWidget(btn_close)
        btn_row.addWidget(self.btn_install_pkg)
        layout.addLayout(btn_row)

    def closeEvent(self, event):
        for attr in ("_check_worker", "_dl_worker"):
            th = getattr(self, attr, None)
            if th is not None and th.isRunning():
                th.quit()
                th.wait(1000)
        super().closeEvent(event)

    def _browse_zip(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select Update Package (.zip)", "", "ZIP Archives (*.zip)")
        if p and Path(p).exists():
            self.selected_local_zip = p
            fname = Path(p).name
            kh = self.lang == "kh"
            self.lbl_selected_file.setText(f"📦 ឯកសារ Local៖ {fname}")
            self.lbl_selected_file.setStyleSheet("color: #38BDF8; font-weight: 700;")
            self.btn_clear_local.setVisible(True)
            self.lbl_check_status.setText("📦 បានជ្រើសរើសឯកសារ .zip ពីម៉ាស៊ីន!" if kh else "📦 Local .zip selected!")
            self.lbl_check_status.setStyleSheet("color: #38BDF8; font-weight: 700;")
            self.txt_changelog.setText(
                f"✅ បានជ្រើសរើសកញ្ចប់កូដ Local:\n{p}\n\n"
                f"👉 ចុច 'ទាញយក និងអាប់ដេតឥឡូវនេះ' ដើម្បីដំឡើងកូដថ្មីពីឯកសារនេះ។"
            )

    def _clear_local_selection(self):
        self.selected_local_zip = ""
        kh = self.lang == "kh"
        self.lbl_selected_file.setText(
            "🐙 ប្រើប្រាស់ GitHub Official Server (លំនាំដើម)" if kh
            else "🐙 Using Official GitHub Server (Default)"
        )
        self.lbl_selected_file.setStyleSheet("color: #10B981; font-size: 12px; font-weight: 600;")
        self.btn_clear_local.setVisible(False)
        self.lbl_check_status.clear()

    def _get_active_target(self) -> str:
        """Returns local zip if selected, otherwise official GitHub update URL."""
        if self.selected_local_zip and Path(self.selected_local_zip).exists():
            return self.selected_local_zip
        return self._get_cloud_url()

    def _check_for_updates(self):
        target = self._get_active_target()
        kh = self.lang == "kh"
        self.btn_check.setEnabled(False)
        self.lbl_check_status.setText("⏳ កំពុងពិនិត្យកំណែថ្មីពី GitHub..." if kh else "⏳ Checking GitHub...")
        self.lbl_check_status.setStyleSheet("color: #F59E0B;")

        self._check_worker = CheckUpdateWorker(target)
        self._check_worker.finished.connect(self._on_check_finished)
        self._check_worker.start()

    def _on_check_finished(self, res):
        kh = self.lang == "kh"
        self.btn_check.setEnabled(True)

        if isinstance(res, Exception) or res is None:
            self.lbl_check_status.setText("⚠️ មិនអាចទាញព័ត៌មានពី GitHub បានទេ" if kh else "⚠️ Could not reach GitHub")
            self.lbl_check_status.setStyleSheet("color: #F59E0B; font-weight: 700;")
            self.txt_changelog.setText(
                f"⚠️ មិនអាចអាន version.json ពី GitHub ({self._get_repo_display()}) បានទេ!\n"
                "• សូមពិនិត្យការភ្ជាប់អ៊ីនធឺណិត ឬប្រាកដថា GitHub Repository ត្រូវបានបើកជា Public។\n"
                "• អ្នកក៏អាចជ្រើសរើសឯកសារ .zip ពីកុំព្យូទ័រផ្ទាល់ ឬចុច 'ទាញយក និងអាប់ដេតឥឡូវនេះ' ដើម្បីសាកល្បងទាញយកម្តងទៀត។"
                if kh else
                f"⚠️ Could not read version.json from GitHub ({self._get_repo_display()}).\n"
                "• Check your internet connection and verify the repository is set to Public.\n"
                "• You can also select a local .zip file or click 'Download & Apply Update' to retry."
            )
            return

        if res.get("has_update"):
            rem_v = res.get("remote_version")
            date = res.get("release_date", "")
            size_kb = res.get("file_size_kb", 0)
            size_str = f" (~{round(size_kb / 1024, 1)} MB)" if size_kb > 1024 else (f" (~{size_kb} KB)" if size_kb else "")

            self.lbl_check_status.setText(
                f"🎉 រកឃើញកំណែថ្មី v{rem_v}{size_str} នៅលើ GitHub!" if kh
                else f"🎉 New version v{rem_v}{size_str} on GitHub!"
            )
            self.lbl_check_status.setStyleSheet("color: #10B981; font-weight: 700;")

            info_text = f"កំណែថ្មី៖ v{rem_v} ({date})\n" if date else f"កំណែថ្មី៖ v{rem_v}\n"
            info_text += f"កំណែបច្ចុប្បន្ន៖ v{APP_VERSION}\n\n"
            info_text += f"ចំណុចកែប្រែថ្មីៗ (Changelog)៖\n{res.get('changelog', '')}"
            self.txt_changelog.setText(info_text)
            self.btn_install_pkg.setStyleSheet(
                "background-color: #10B981; color: white; font-weight: 700; padding: 8px 20px; border-radius: 6px;"
            )
        else:
            rem_v = res.get("remote_version", APP_VERSION)
            self.lbl_check_status.setText(
                f"✅ កម្មវិធីជាកំណែចុងក្រោយបង្អស់ហើយ (v{APP_VERSION})" if kh
                else f"✅ You have the latest version (v{APP_VERSION})"
            )
            self.lbl_check_status.setStyleSheet("color: #38BDF8; font-weight: 700;")
            self.txt_changelog.setText(
                f"គ្មានកំណែថ្មីជាងនេះទេ (Current: v{APP_VERSION}, GitHub: v{rem_v})។\n\n"
                f"ចំណុចកែប្រែចុងក្រោយ៖\n{res.get('changelog', '• ដំណើរការប្រក្រតី')}"
            )

    def _start_update(self):
        target = self._get_active_target()
        kh = self.lang == "kh"

        self.btn_install_pkg.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(10)
        self.lbl_status.setText("កំពុងចាប់ផ្តើមទាញយក និងដំឡើងកញ្ចប់កូដពី GitHub..." if kh else "Starting GitHub update...")
        self.lbl_status.setStyleSheet("color: #38BDF8; font-weight: 600; font-size: 12px;")

        self._dl_worker = DownloadUpdateWorker(target)
        self._dl_worker.progress.connect(self._on_download_progress)
        self._dl_worker.failed.connect(self._on_download_failed)
        self._dl_worker.finished_ok.connect(self._on_download_finished)
        self._dl_worker.start()

    def _on_download_progress(self, pct: int, msg: str):
        self.progress.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_download_failed(self, err: str):
        self.btn_install_pkg.setEnabled(True)
        self.btn_check.setEnabled(True)
        self.progress.setValue(0)
        self.lbl_status.setText("❌ ការអាប់ដេតបរាជ័យ!")
        self.lbl_status.setStyleSheet("color: #EF4444; font-weight: 700; font-size: 12px;")
        QMessageBox.critical(self, "Update Error", f"ការអាប់ដេតកូដបរាជ័យ:\n{err}")

    def _on_download_finished(self, msg: str):
        self.progress.setValue(100)
        self.lbl_status.setText("✅ " + (msg or "អាប់ដេតជោគជ័យ! កំពុងបើកកម្មវិធីឡើងវិញ..."))
        self.lbl_status.setStyleSheet("color: #10B981; font-weight: 700; font-size: 12px;")
