import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox


def _suppress_windows_console_windows():
    """Globally hide any black CMD/Console windows spawned by FFmpeg, FFprobe, or yt-dlp on Windows."""
    if sys.platform != "win32":
        return
    CREATE_NO_WINDOW = 0x08000000
    _orig_popen = subprocess.Popen

    class _NoConsolePopen(_orig_popen):
        def __init__(self, *args, **kwargs):
            if "creationflags" not in kwargs:
                kwargs["creationflags"] = CREATE_NO_WINDOW
            else:
                kwargs["creationflags"] |= CREATE_NO_WINDOW
            if "startupinfo" not in kwargs:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                kwargs["startupinfo"] = si
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoConsolePopen


_suppress_windows_console_windows()

# Priority import path + meta_path hook so hot-updated .py files on disk ALWAYS override PyInstaller frozen PYZ bytecode
_app_install_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
for _p in [str(_app_install_dir / "_internal"), str(_app_install_dir)]:
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

if getattr(sys, "frozen", False):
    import importlib.machinery as _imp_machinery

    class _HotUpdateDiskFinder:
        _PREFIXES = ("core", "ui")

        @classmethod
        def find_spec(cls, fullname, path=None, target=None):
            top = fullname.split(".", 1)[0]
            if top not in cls._PREFIXES:
                return None
            search_locs = [str(_app_install_dir)] if path is None else list(path)
            return _imp_machinery.PathFinder.find_spec(fullname, search_locs, target)

    sys.meta_path.insert(0, _HotUpdateDiskFinder)

from core.database import Database
from ui.main_window import MainWindow
from ui.theme import build_stylesheet
from ui.license_dialog import enforce_license_or_exit


def _get_app_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _get_user_data_root() -> Path:
    r"""When installed in C:\Program Files\AiSummarai, store user projects & DB in %LOCALAPPDATA%\AiSummarai so Windows UAC never blocks writes."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            user_root = Path(local_app) / "AiSummarai"
            user_root.mkdir(parents=True, exist_ok=True)
            return user_root
    return _get_app_install_dir()


def _ensure_bundled_ffmpeg(install_dir: Path):
    candidates = [install_dir, install_dir / "bin", install_dir / "_internal" / "bin"]
    extra_paths = [str(p) for p in candidates if p.exists()]
    if extra_paths:
        os.environ["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + os.environ.get("PATH", "")


def main():
    install_dir = _get_app_install_dir()
    user_root = _get_user_data_root()
    os.chdir(user_root)
    _ensure_bundled_ffmpeg(install_dir)

    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("aisummarai.dubstudio.installer.2")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Ai Summarai")
    app.setStyle("Fusion")
    default_font = QFont("Inter", 10)
    default_font.setFamilies(["Inter", "Kantumruy Pro", "Noto Sans Khmer", "Khmer OS Battambang", "Segoe UI", "Microsoft YaHei", "sans-serif"])
    app.setFont(default_font)

    db = Database()
    saved_theme = db.get_setting("ui_theme", "capcut")
    app.setStyleSheet(build_stylesheet(saved_theme))

    bundle_dir = Path(getattr(sys, "_MEIPASS", install_dir))
    icon_path = bundle_dir / "assets" / "icon.ico"
    if not icon_path.exists():
        icon_path = install_dir / "assets" / "icon.ico"
    if not icon_path.exists():
        icon_path = install_dir / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        QMessageBox.critical(
            None,
            "FFmpeg Missing — រកមិនឃើញ FFmpeg",
            "សូមដាក់ឯកសារ ffmpeg.exe និង ffprobe.exe ទៅក្នុង Folder 'bin' នៃកម្មវិធី "
            "ឬដំឡើង FFmpeg ក្នុង Windows PATH មុនពេលប្រើប្រាស់។"
        )
        sys.exit(1)

    # Security & License Enforcement Gate
    if not enforce_license_or_exit():
        sys.exit(0)

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))

    screen_geo = app.primaryScreen().availableGeometry()
    if screen_geo.width() <= 1440 or screen_geo.height() <= 820:
        window.showMaximized()
    else:
        w = int(screen_geo.width() * 0.92)
        h = int(screen_geo.height() * 0.90)
        window.resize(w, h)
        window.move(
            screen_geo.x() + (screen_geo.width() - w) // 2,
            screen_geo.y() + (screen_geo.height() - h) // 2,
        )
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
