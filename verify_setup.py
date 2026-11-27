#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ai Summarai Studio — Hardware, AI Models & Dependency Health Checker
--------------------------------------------------------------------
Verifies Python, NVIDIA CUDA GPU / VRAM, FFmpeg, speech ASR (faster-whisper/funasr),
subtitle OCR (rapidocr/paddleocr), and local Ollama REST server connectivity.
"""

import os
import shutil
import subprocess
import sys
import urllib.request
import json
from pathlib import Path

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def check_python():
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    status = "OK" if (v.major == 3 and v.minor >= 10) else "WARN"
    return status, f"Python {ver_str} ({sys.executable})"


def check_gpu():
    try:
        import torch
        if torch.cuda.is_available():
            cnt = torch.cuda.device_count()
            name = torch.cuda.get_device_name(0)
            vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 2)
            return "OK", f"NVIDIA GPU Active: {name} ({vram_gb} GB VRAM, {cnt} Device(s))"
        return "INFO", "CPU Mode (No CUDA GPU detected — int8 Low-Spec CPU optimization active)"
    except ImportError:
        return "INFO", "PyTorch not installed — Pure ONNX / CPU mode active"


def check_ffmpeg():
    # Check PATH or local bin
    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        local_bin = Path(__file__).resolve().parent / "bin" / "ffmpeg.exe"
        if local_bin.exists():
            ffmpeg_exe = str(local_bin)

    if ffmpeg_exe:
        try:
            CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
            res = subprocess.run([ffmpeg_exe, "-version"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            first_line = res.stdout.splitlines()[0] if res.stdout else "Available"
            return "OK", f"{first_line} ({ffmpeg_exe})"
        except Exception as e:
            return "WARN", f"Found {ffmpeg_exe} but execution had warning: {e}"
    return "FAIL", "FFmpeg not found in PATH or bin/. Please install FFmpeg."


def check_asr_engines():
    engines = []
    # 1. faster-whisper
    try:
        import faster_whisper
        engines.append(f"faster-whisper v{getattr(faster_whisper, '__version__', 'OK')}")
    except ImportError:
        pass

    # 2. funasr
    try:
        import funasr
        engines.append("funasr (SenseVoiceSmall)")
    except ImportError:
        pass

    if engines:
        return "OK", ", ".join(engines)
    return "FAIL", "No local ASR library installed (faster-whisper recommended)"


def check_ocr_engines():
    engines = []
    # 1. RapidOCR
    try:
        import rapidocr_onnxruntime
        engines.append("RapidOCR (ONNX CPU)")
    except ImportError:
        try:
            import rapidocr
            engines.append("RapidOCR")
        except ImportError:
            pass

    # 2. PaddleOCR
    try:
        import paddleocr
        engines.append("PaddleOCR (PP-OCRv4)")
    except ImportError:
        pass

    if engines:
        return "OK", ", ".join(engines)
    return "WARN", "No local OCR library installed (RapidOCR recommended for CPU)"


def check_ollama():
    url = "http://localhost:11434/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AiSummarai-HealthCheck"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                if models:
                    return "OK", f"Running locally at {url} | Models: {', '.join(models[:4])}"
                return "OK", f"Running locally at {url} (No models pulled yet: try 'ollama pull qwen2.5:7b')"
    except Exception:
        pass
    return "INFO", "Not running (Optional — Free Google Translate & Gemini API are active)"


def main():
    print("=" * 72)
    print("  🩺 Ai Summarai Studio — Environment & AI Engine Health Check")
    print("=" * 72)

    checks = [
        ("Python Runtime", check_python),
        ("Hardware / GPU", check_gpu),
        ("Media Engine (FFmpeg)", check_ffmpeg),
        ("Speech ASR Engines", check_asr_engines),
        ("Subtitle OCR Engines", check_ocr_engines),
        ("Local Ollama Server", check_ollama),
    ]

    all_critical_ok = True
    for title, fn in checks:
        status, detail = fn()
        badge = {
            "OK": "[  OK  ]",
            "INFO": "[ INFO ]",
            "WARN": "[ WARN ]",
            "FAIL": "[ FAIL ]",
        }.get(status, "[ .... ]")

        if status == "FAIL":
            all_critical_ok = False

        print(f"{badge} {title:<24} : {detail}")

    print("=" * 72)
    if all_critical_ok:
        print("  🎉 All core requirements are healthy! Ready for AI dubbing.")
    else:
        print("  ⚠️ Some components are missing. Please see warnings above.")
    print("=" * 72)


if __name__ == "__main__":
    main()
