import sys
import os
import traceback

# Enforce UTF-8 on Windows console & subprocess environments
if sys.platform == "win32":
    import codecs
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except Exception:
        pass
    os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
except ImportError:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

from ui.subtitle_studio_widget import SubtitleStudioWidget


def global_exception_hook(exctype, value, tb):
    print("=" * 60)
    print("UNHANDLED SUBTITLE STUDIO EXCEPTION:")
    traceback.print_exception(exctype, value, tb)
    print("=" * 60)
    sys.__excepthook__(exctype, value, tb)


def main():
    sys.excepthook = global_exception_hook

    # Enable High-DPI Scaling for Crisp 4K / Retina Displays
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("AI Video Subtitle & Translation Studio")
    app.setOrganizationName("AiSummaraiStudio")

    win = SubtitleStudioWidget()
    win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
