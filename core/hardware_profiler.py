# -*- coding: utf-8 -*-
"""
core/hardware_profiler.py
GPU Hardware Encoder Prober & PC Performance Profile Engine:
  - Accurately detects NVIDIA / AMD / Intel GPUs via `nvidia-smi`, Windows WMI/DXGI, and PyTorch CUDA.
  - Accurately detects total System RAM via Windows Kernel32 `GlobalMemoryStatusEx` (fallback to psutil).
  - Probes FFmpeg hardware encoders at 256x256:
    h264_nvenc -> h264_amf -> h264_qsv -> h264_mf (Windows GPU MediaFoundation) -> libx264.
  - Applies High-Spec PC vs Low-Spec PC (4GB VRAM Safe) tuning parameters.
"""

import gc
import re
import subprocess
from typing import Dict, Any, List, Optional

from core.system_monitor import get_system_ram_info, get_system_gpu_info

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class HardwareProfiler:
    """
    Detects GPU model, VRAM, System RAM, and available FFmpeg hardware video encoders.
    Provides optimized FFmpeg encoding arguments and PC performance presets.
    """

    _cached_info: Optional[Dict[str, Any]] = None

    @classmethod
    def detect_hardware(cls, force_refresh: bool = False) -> Dict[str, Any]:
        if cls._cached_info is not None and not force_refresh:
            return cls._cached_info

        cuda_available = False
        gpu_name = "CPU Only"
        vram_gb = 0.0
        ram_gb = 8.0

        # 1. Accurate Windows System RAM via ctypes GlobalMemoryStatusEx
        try:
            _used_gb, total_gb, _pct = get_system_ram_info()
            if total_gb > 0.5:
                ram_gb = round(total_gb, 1)
        except Exception:
            pass

        if ram_gb == 8.0:
            try:
                import psutil
                ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
            except Exception:
                pass

        # 2. Accurate GPU & VRAM detection via nvidia-smi first (works even without CUDA torch)
        try:
            gpu_util, vram_str, nv_name = get_system_gpu_info()
            if nv_name and nv_name != "N/A":
                cuda_available = True
                gpu_name = nv_name.strip()
                m = re.search(r"/\s*(\d+)\s*MB", str(vram_str))
                if m:
                    vram_gb = round(int(m.group(1)) / 1024.0, 1)
        except Exception:
            pass

        # 3. Fallback to PyTorch CUDA if nvidia-smi didn't populate
        if not cuda_available:
            try:
                import torch
                if torch.cuda.is_available():
                    cuda_available = True
                    gpu_name = torch.cuda.get_device_name(0)
                    props = torch.cuda.get_device_properties(0)
                    vram_gb = round(props.total_memory / (1024 ** 3), 1)
            except Exception:
                pass

        # 4. Probe FFmpeg hardware encoders at valid 256x256 resolution
        available_encoders = cls._probe_ffmpeg_encoders()
        best_encoder = "libx264"
        for candidate in ("h264_nvenc", "h264_amf", "h264_qsv", "h264_mf"):
            if candidate in available_encoders and cls._test_encoder_works(candidate):
                best_encoder = candidate
                break

        recommended_profile = "high" if (vram_gb >= 4.0 or ram_gb >= 16.0) else "low"

        cls._cached_info = {
            "cuda_available": cuda_available,
            "gpu_name": gpu_name,
            "vram_gb": vram_gb,
            "ram_gb": ram_gb,
            "available_encoders": available_encoders,
            "best_encoder": best_encoder,
            "recommended_profile": recommended_profile,
        }
        return cls._cached_info

    @classmethod
    def _probe_ffmpeg_encoders(cls) -> List[str]:
        found: List[str] = ["libx264"]
        try:
            res = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=6,
            )
            out = res.stdout or ""
            for enc in ("h264_nvenc", "hevc_nvenc", "h264_amf", "h264_qsv", "h264_mf"):
                if enc in out:
                    found.append(enc)
        except Exception:
            pass
        return found

    @classmethod
    def _test_encoder_works(cls, encoder: str) -> bool:
        """Verifies the hardware encoder can initialize on a standard 256x256 frame."""
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
            "-vframes", "1", "-c:v", encoder, "-f", "null", "-",
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
                timeout=4,
            )
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def get_encoder_args(cls, preferred: str = "auto") -> List[str]:
        info = cls.detect_hardware()
        enc = info["best_encoder"] if (not preferred or preferred == "auto") else preferred
        if enc == "h264_nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20", "-pix_fmt", "yuv420p"]
        elif enc == "h264_amf":
            return ["-c:v", "h264_amf", "-quality", "balanced", "-pix_fmt", "yuv420p"]
        elif enc == "h264_qsv":
            return ["-c:v", "h264_qsv", "-global_quality", "20", "-pix_fmt", "yuv420p"]
        elif enc == "h264_mf":
            return ["-c:v", "h264_mf", "-b:v", "4500k", "-pix_fmt", "yuv420p"]
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]

    @classmethod
    def get_encoder_badge_text(cls) -> str:
        info = cls.detect_hardware()
        enc = info["best_encoder"]
        gpu = info["gpu_name"]
        short_gpu = gpu.replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "")[:18]
        if enc == "h264_nvenc":
            return f"⚡ NVENC GPU Ready ({short_gpu})"
        elif enc == "h264_amf":
            return f"⚡ AMD AMF GPU Ready ({short_gpu})"
        elif enc == "h264_qsv":
            return f"⚡ Intel QSV GPU Ready ({short_gpu})"
        elif enc == "h264_mf" and info["cuda_available"]:
            return f"⚡ GPU HW Ready ({short_gpu} | {info['vram_gb']}GB VRAM)"
        elif info["cuda_available"]:
            return f"⚡ {short_gpu} ({info['vram_gb']}GB VRAM) + Fast x264"
        return f"🖥️ CPU Encode (x264 | {info['ram_gb']}GB RAM)"

    @classmethod
    def apply_performance_profile(cls, profile_mode: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Applies High-Spec PC vs Low-Spec PC (4GB VRAM Safe) optimizations to settings dict.
        """
        updated = dict(settings or {})
        is_low = "low" in str(profile_mode or "").lower()
        updated["hardware_profile"] = "low" if is_low else "high"

        if is_low:
            updated["sample_fps"] = 0.5
            updated["batch_size"] = 4
            updated["preview_w"] = 854
            updated["preview_h"] = 480
            updated["compute_type"] = "int8"
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
        else:
            updated["sample_fps"] = 2.0
            updated["batch_size"] = 10
            updated["preview_w"] = 1280
            updated["preview_h"] = 720
            updated["compute_type"] = "float16"

        return updated
