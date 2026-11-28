# -*- coding: utf-8 -*-
"""
core/dependency_checker.py
Audits system & AI runtime dependencies:
  1. FFmpeg & FFprobe binaries (PATH or ./bin/)
  2. Python AI runtime packages (faster_whisper, funasr, paddleocr, scenedetect, edge_tts, cv2)
  3. Local Ollama server reachability (GET http://localhost:11434/api/tags)
  4. Translation LLM models (qwen2.5:7b, gemma2:9b, etc.) + streaming pull via POST /api/pull
"""

import importlib.util
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
import requests


class DependencyChecker:
    """
    Central audit and auto-fix utility for FFmpeg, AI packages, and Ollama models.
    """

    RECOMMENDED_MODELS = ("qwen2.5:7b", "gemma2:9b", "qwen2.5:3b", "llama3.2:3b")
    FFMPEG_ZIP_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

    @classmethod
    def check_all(cls, ollama_url: str = "http://localhost:11434", target_model: str = "qwen2.5:7b") -> Dict[str, Any]:
        ffmpeg_ok, ffmpeg_path = cls.check_ffmpeg()
        ai_pkgs = cls.check_python_packages()
        ollama_ok, installed_models = cls.check_ollama(ollama_url)

        model_ready = False
        if ollama_ok and installed_models:
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
                "url": ollama_url,
                "models": installed_models,
            },
            "llm_model": {
                "ok": model_ready,
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
            resp = requests.get(f"{base}/api/tags", timeout=2.5)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
                return True, models
        except Exception:
            pass
        return False, []

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
        """
        base = (ollama_url or "http://localhost:11434").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            with requests.post(
                f"{base}/api/pull",
                json={"name": model_name, "stream": True},
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
                    status_txt = data.get("status", "Pulling...")
                    total = int(data.get("total") or 0)
                    completed = int(data.get("completed") or 0)
                    pct = int((completed / total) * 100) if total > 0 else 50
                    if progress_cb:
                        progress_cb(min(99, pct), f"Ollama Pull ({model_name}): {status_txt}")
            if progress_cb:
                progress_cb(100, f"Model '{model_name}' pulled successfully!")
            return True
        except Exception as e:
            if progress_cb:
                progress_cb(0, f"Ollama Pull Failed: {e}")
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
