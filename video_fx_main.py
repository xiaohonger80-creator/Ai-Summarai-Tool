# -*- coding: utf-8 -*-
"""
video_fx_main.py
High-DPI Desktop entry point for VideoFX Studio.
"""

import os
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.video_fx_studio import VideoFXStudioWindow


def main():
    # Enable High-DPI scaling
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("VideoFX Studio")

    initial_video = sys.argv[1] if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else None
    window = VideoFXStudioWindow(initial_video_path=initial_video)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
