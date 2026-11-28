# -*- coding: utf-8 -*-
"""
core/dependency_checker.py
Audits system & AI runtime dependencies:
  1. FFmpeg & FFprobe binaries (PATH or ./bin/)
  2. Python AI runtime packages (faster_whisper, funasr, paddleocr, scenedetect, edge_tts, cv2)
  3. Local Ollama server reachability (GET http://localhost:11434/api/tags) + auto-starting `ollama serve`
  4. One-click Ollama Windows Installer download & launch if Ollama is not installed on the PC
  5. Translation LLM models (qwen2.5:7b, gemma2:9b, or Built-in Free Google Translate `google-free`)
"""

import importlib.util
import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
import requests

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class DependencyChecker:
    """
    Central audit, auto-start, and auto-install utility for FFmpeg, AI packages, and Ollama models.
    """

    RECOMMENDED_MODELS = (
        "google-free (Built-in Free Translator - No Ollama Needed)",
        "qwen2.5:7b",
        "qwen2.5:3b",
        "gemma2:9b",
        "llama3.2:3b",
    )
    FFMPEG_ZIP_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"

    @classmethod
    def find_ollama_exe(cls) -> str:
        found = shutil.which("ollama")
        if found:
            return str(found)
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(r"C:\Program Files\Ollama\ollama.exe"),
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return ""

    @classmethod
    def ensure_ollama_running(cls, ollama_url: str = "http://localhost:11434") -> bool:
        """
        Checks if Ollama server is reachable; if not, attempts to start `ollama serve` in the background.
        """
        ok, _ = cls.check_ollama(ollama_url)
        if ok:
            return True

        exe = cls.find_ollama_exe()
        if not exe:
            return False

        try:
            subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            for _ in range(10):
                time.sleep(0.5)
                ok, _ = cls.check_ollama(ollama_url)
                if ok:
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def check_all(cls, ollama_url: str = "http://localhost:11434", target_model: str = "qwen2.5:7b") -> Dict[str, Any]:
        ffmpeg_ok, ffmpeg_path = cls.check_ffmpeg()
        ai_pkgs = cls.check_python_packages()
        ollama_exe = cls.find_ollama_exe()
        ollama_ok, installed_models = cls.check_ollama(ollama_url)
        if not ollama_ok and ollama_exe:
            ollama_ok = cls.ensure_ollama_running(ollama_url)
            if ollama_ok:
                ollama_ok, installed_models = cls.check_ollama(ollama_url)

        is_builtin_free = "google-free" in (target_model or "").lower()
        model_ready = is_builtin_free
        if not model_ready and ollama_ok and installed_models:
            t_base = (target_model or "qwen2.5:7b").split(":")[0].lower()
            model_ready = any(m.lower() == target_model.lower() or m.lower().startswith(t_base) for m in installed_models)

        any_asr_ocr = any(ai_pkgs.get(k, False) for k in ("faster_whisper", "paddleocr", "funasr", "cv2"))
        overall_healthy = ffmpeg_ok and any_asr_ocr

        return {
            "overall_healthy": overall_healthy,
            "ffmpeg": {
                "ok": ffmpeg_ok,
                "path": ffmpeg_path or "Missing (Click Auto-Fix or Browse)",
            },
            "ai_engines": {
                "ok": any_asr_ocr,
                "packages": ai_pkgs,
            },
            "ollama_server": {
                "ok": ollama_ok,
                "installed": bool(ollama_exe),
                "exe_path": ollama_exe,
                "url": ollama_url,
                "models": installed_models,
            },
            "llm_model": {
                "ok": model_ready,
                "is_builtin_free": is_builtin_free,
                "target": target_model,
                "installed": installed_models,
            },
        }

    @classmethod
    def check_ffmpeg(cls) -> tuple[bool, str]:
        local_bin = Path("bin")
        if (local_bin / "ffmpeg.exe").exists():
            os.environ["PATH"] = str(local_bin.resolve()) + os.pathsep + os.environ.get("PATH", "")
        ff = shutil.which("ffmpeg")
        fp = shutil.which("ffprobe")
        if ff and fp:
            return True, str(ff)
        return False, ""

    @classmethod
    def check_python_packages(cls) -> Dict[str, bool]:
        pkgs = ("faster_whisper", "funasr", "paddleocr", "scenedetect", "edge_tts", "cv2")
        status: Dict[str, bool] = {}
        for name in pkgs:
            try:
                status[name] = importlib.util.find_spec(name) is not None
            except Exception:
                status[name] = False
        return status

    @classmethod
    def check_ollama(cls, ollama_url: str = "http://localhost:11434") -> tuple[bool, List[str]]:
        base = (ollama_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            resp = requests.get(f"{base}/api/tags", timeout=2.0)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
                return True, models
        except Exception:
            pass
        return False, []

    @classmethod
    def download_and_install_ollama(
        cls,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        If Ollama is not installed on the PC, downloads OllamaSetup.exe and launches the installer,
        then starts `ollama serve`.
        """
        if cls.find_ollama_exe():
            if progress_cb:
                progress_cb(80, "Ollama is installed — starting local Ollama server...")
            ok = cls.ensure_ollama_running()
            if progress_cb:
                progress_cb(100 if ok else 0, "Ollama server is now Online!" if ok else "Could not start Ollama server.")
            return ok

        bin_dir = Path("bin")
        bin_dir.mkdir(parents=True, exist_ok=True)
        installer_path = bin_dir / "OllamaSetup.exe"

        try:
            if progress_cb:
                progress_cb(5, "Downloading official Ollama for Windows (OllamaSetup.exe)...")
            with requests.get(cls.OLLAMA_SETUP_URL, stream=True, timeout=180) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                downloaded = 0
                with open(installer_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=262144):
                        if is_cancelled and is_cancelled():
                            return False
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0 and progress_cb:
                                pct = int((downloaded / total) * 80)
                                progress_cb(pct, f"Downloading OllamaSetup.exe ({downloaded // (1024*1024)} MB / {total // (1024*1024)} MB)...")

            if progress_cb:
                progress_cb(85, "Installing Ollama silently in the background...")
            subprocess.run([str(installer_path), "/SILENT"], timeout=180)
            time.sleep(2.0)
            ok = cls.ensure_ollama_running()
            if progress_cb:
                progress_cb(100 if ok else 90, "✅ Ollama installed and running!" if ok else "✅ Ollama installer launched — complete setup if prompted.")
            return ok
        except Exception as e:
            if progress_cb:
                progress_cb(0, f"មិនអាចទាញយក Ollama បានទេ ({e}) — អ្នកអាចប្រើ 'google-free' ដោយមិនបាច់មាន Ollama!")
            return False

    @classmethod
    def pull_ollama_model(
        cls,
        model_name: str = "qwen2.5:7b",
        ollama_url: str = "http://localhost:11434",
        progress_cb: Optional[Callable[[int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Streams model pull from local Ollama REST API (`POST /api/pull`).
        Automatically starts or installs Ollama first if localhost:11434 is offline!
        """
        clean_model = (model_name or "qwen2.5:7b").split()[0].strip()
        if "google-free" in clean_model.lower():
            if progress_cb:
                progress_cb(100, "✅ 'google-free' (Free Google Translate) is built-in and ready immediately — no download needed!")
            return True

        # Ensure Ollama server is running first (or auto-install if missing)
        if not cls.ensure_ollama_running(ollama_url):
            if not cls.find_ollama_exe():
                if progress_cb:
                    progress_cb(5, "រកមិនឃើញកម្មវិធី Ollama ក្នុងម៉ាស៊ីនទេ — កំពុងទាញយក និងដំឡើង Ollama ដោយស្វ័យប្រវត្តិ...")
                installed_ok = cls.download_and_install_ollama(progress_cb=progress_cb, is_cancelled=is_cancelled)
                if not installed_ok:
                    return False
            else:
                if progress_cb:
                    progress_cb(0, "⚠️ Ollama Server មិនទាន់ដំណើរការទេ។ សូមបើកកម្មវិធី Ollama ឬជ្រើសរើស 'google-free' (មិនបាច់ប្រើ Ollama)។")
                return False

        base = (ollama_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            if progress_cb:
                progress_cb(10, f"Connecting to Ollama to pull '{clean_model}'...")
            with requests.post(
                f"{base}/api/pull",
                json={"name": clean_model, "stream": True},
                stream=True,
                timeout=600,
            ) as resp:
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if is_cancelled and is_cancelled():
                        return False
                    if not raw_line:
                        continue
                    data = json.loads(raw_line.decode("utf-8", errors="replace"))
                    if data.get("error"):
                        if progress_cb:
                            progress_cb(0, f"Ollama Error: {data['error']}")
                        return False
                    status_txt = data.get("status", "Pulling...")
                    total = int(data.get("total") or 0)
                    completed = int(data.get("completed") or 0)
                    pct = int((completed / total) * 100) if total > 0 else 50
                    if progress_cb:
                        progress_cb(min(99, pct), f"Ollama Pull ({clean_model}): {status_txt}")
            if progress_cb:
                progress_cb(100, f"✅ Model '{clean_model}' pulled and ready!")
            return True
        except Exception as e:
            if progress_cb:
                progress_cb(0, f"⚠️ មិនអាចភ្ជាប់ទៅ Ollama (localhost:11434) បានទេ។ អ្នកអាចជ្រើសរើស 'google-free' ដើម្បីបកប្រែឥតគិតថ្លៃភ្លាមៗ!")
            return False

    @classmethod
    def download_portable_ffmpeg(
        cls,
        dest_bin_dir: str = "bin",
        progress_cb: Optional[Callable[[int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Downloads portable Windows FFmpeg build into `./bin/` if missing.
        """
        bin_path = Path(dest_bin_dir)
        bin_path.mkdir(parents=True, exist_ok=True)
        zip_tmp = bin_path / "ffmpeg_portable.zip"

        try:
            if progress_cb:
                progress_cb(5, "Connecting to FFmpeg release server...")
            with requests.get(cls.FFMPEG_ZIP_URL, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                downloaded = 0
                with open(zip_tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=262144):
                        if is_cancelled and is_cancelled():
                            return False
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0 and progress_cb:
                                pct = int((downloaded / total) * 85)
                                progress_cb(pct, f"Downloading FFmpeg ({downloaded // (1024*1024)} MB)...")

            if progress_cb:
                progress_cb(90, "Extracting ffmpeg.exe and ffprobe.exe...")
            with zipfile.ZipFile(zip_tmp, "r") as zf:
                for member in zf.namelist():
                    fname = Path(member).name.lower()
                    if fname in ("ffmpeg.exe", "ffprobe.exe"):
                        with zf.open(member) as src, open(bin_path / fname, "wb") as dst:
                            shutil.copyfileobj(src, dst)

            zip_tmp.unlink(missing_ok=True)
            os.environ["PATH"] = str(bin_path.resolve()) + os.pathsep + os.environ.get("PATH", "")
            if progress_cb:
                progress_cb(100, "FFmpeg & FFprobe installed in ./bin/")
            return (bin_path / "ffmpeg.exe").exists()
        except Exception as e:
            zip_tmp.unlink(missing_ok=True)
            if progress_cb:
                progress_cb(0, f"FFmpeg download failed: {e}")
            return False
