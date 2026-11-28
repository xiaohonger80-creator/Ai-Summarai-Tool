# -*- coding: utf-8 -*-
"""
core/hardware_profiler.py
GPU Hardware Encoder Prober & PC Performance Profile Engine:
  - Probes `ffmpeg -hide_banner -encoders` once and selects the fastest working hardware encoder:
    h264_nvenc (NVIDIA) -> h264_amf (AMD) -> h264_qsv (Intel) -> libx264 (CPU fallback).
  - Applies High-Spec PC vs Low-Spec PC (8GB RAM / 4GB VRAM Safe) tuning parameters.
"""

import gc
import subprocess
from typing import Dict, Any, List, Optional

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class HardwareProfiler:
    """
    Detects CUDA VRAM, System RAM, and available FFmpeg hardware video encoders.
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

        try:
            import psutil
            ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except Exception:
            pass

        try:
            import torch
            if torch.cuda.is_available():
                cuda_available = True
                gpu_name = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                vram_gb = round(props.total_memory / (1024 ** 3), 1)
        except Exception:
            pass

        available_encoders = cls._probe_ffmpeg_encoders()
        best_encoder = "libx264"
        for candidate in ("h264_nvenc", "h264_amf", "h264_qsv"):
            if candidate in available_encoders and cls._test_encoder_works(candidate):
                best_encoder = candidate
                break

        recommended_profile = "high" if (vram_gb >= 6.0 or ram_gb >= 16.0) else "low"

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
            for enc in ("h264_nvenc", "hevc_nvenc", "h264_amf", "h264_qsv"):
                if enc in out:
                    found.append(enc)
        except Exception:
            pass
        return found

    @classmethod
    def _test_encoder_works(cls, encoder: str) -> bool:
        """Verifies the hardware encoder can initialize on a tiny 64x64 frame."""
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
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
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]

    @classmethod
    def get_encoder_badge_text(cls) -> str:
        info = cls.detect_hardware()
        enc = info["best_encoder"]
        if enc == "h264_nvenc":
            return f"⚡ NVENC GPU Ready ({info['gpu_name'][:16]})"
        elif enc == "h264_amf":
            return "⚡ AMD AMF GPU Ready"
        elif enc == "h264_qsv":
            return "⚡ Intel QSV GPU Ready"
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
