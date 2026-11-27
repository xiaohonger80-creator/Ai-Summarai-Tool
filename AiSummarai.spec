# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets'), ('updater_config.json', '.'), ('version.json', '.'), ('data/dub_studio.db', 'data')]
binaries = []
hiddenimports = [
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'edge_tts',
    'yt_dlp',
    'faster_whisper',
    'rapidocr',
    'onnxruntime',
    'google.genai',
    'google.genai.types',
    'openai',
    'sqlite3',
    'requests',
    'cv2',
]

for pkg in ('rapidocr', 'faster_whisper', 'edge_tts', 'ctranslate2', 'onnxruntime', 'cv2'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'scipy', 'pandas', 'tkinter', 'PyQt5', 'PyQt6',
        'IPython', 'notebook', 'jupyter', 'pytest', 'unittest', 'tensorrt', 'torch.testing'
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AiSummarai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon='assets/icon.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AiSummarai',
)
