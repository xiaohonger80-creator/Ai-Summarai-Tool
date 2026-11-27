import ctypes
import os
import subprocess
import time
from PySide6.QtCore import QThread, Signal

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000 if os.name == "nt" else 0
IDLE_PRIORITY_CLASS = 0x00000040 if os.name == "nt" else 0


_CACHED_HW_PROFILE = None


def get_hardware_profile() -> dict:
    """
    Auto-detects CPU cores and RAM to classify machine tier ('low', 'mid', 'high')
    and recommend safe thread counts & OS priority flags so Low-Spec PCs NEVER freeze
    while High-Spec PCs still maximize throughput.
    """
    global _CACHED_HW_PROFILE
    if _CACHED_HW_PROFILE is not None:
        return dict(_CACHED_HW_PROFILE)

    cores = os.cpu_count() or 4
    _, total_ram_gb, _ = get_system_ram_info()
    if total_ram_gb <= 0.1:
        total_ram_gb = 8.0

    if cores <= 4 or total_ram_gb <= 8.5:
        tier = "low"
        # Leave headroom for Windows + PySide6 GUI on low-end laptops
        ff_threads = max(1, min(3, cores - 1 if cores > 2 else cores))
        audio_chunk_size = 35
        priority_flags = CREATE_NO_WINDOW | IDLE_PRIORITY_CLASS
        label = f"🟢 Low-Spec Safe Mode ({cores}C / {total_ram_gb:.0f}GB)"
    elif cores <= 8 or total_ram_gb <= 16.5:
        tier = "mid"
        ff_threads = max(2, min(6, cores - 1))
        audio_chunk_size = 50
        priority_flags = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
        label = f"🔵 Balanced Mode ({cores}C / {total_ram_gb:.0f}GB)"
    else:
        tier = "high"
        ff_threads = max(4, min(12, cores - 2))
        audio_chunk_size = 80
        priority_flags = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
        label = f"🚀 High-Spec Boost ({cores}C / {total_ram_gb:.0f}GB)"

    _CACHED_HW_PROFILE = {
        "tier": tier,
        "cpu_cores": cores,
        "total_ram_gb": round(total_ram_gb, 1),
        "ffmpeg_threads": ff_threads,
        "audio_chunk_size": audio_chunk_size,
        "creationflags": priority_flags,
        "label": label,
    }
    return dict(_CACHED_HW_PROFILE)

class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_ulong),
        ("dwHighDateTime", ctypes.c_ulong)
    ]

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

def _filetime_to_int(ft) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

def get_system_cpu_times():
    try:
        idle = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        res = ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        if res:
            return _filetime_to_int(idle), _filetime_to_int(kernel), _filetime_to_int(user)
    except Exception:
        pass
    return 0, 0, 0

def get_system_ram_info():
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        res = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if res:
            total_gb = stat.ullTotalPhys / (1024**3)
            used_gb = (stat.ullTotalPhys - stat.ullAvailPhys) / (1024**3)
            return used_gb, total_gb, int(stat.dwMemoryLoad)
    except Exception:
        pass
    return 0.0, 0.0, 0

def get_system_gpu_info():
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,name", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1,
            creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
        if proc.returncode == 0 and proc.stdout.strip():
            parts = [p.strip() for p in proc.stdout.strip().split(",")]
            gpu_pct = int(parts[0])
            gpu_used = int(parts[1])
            gpu_total = int(parts[2])
            gpu_name = parts[3] if len(parts) > 3 else "NVIDIA GPU"
            return gpu_pct, f"{gpu_used}/{gpu_total} MB", gpu_name
    except Exception:
        pass
    return 0, "--", "Windows MediaFoundation"


class SystemMonitorWorker(QThread):
    """
    Lightweight, non-blocking background thread for real-time CPU, RAM, and GPU hardware metrics.
    Emits metrics_updated(badge_text, tooltip_text) every ~1.8 seconds with 0% UI lag.
    """
    metrics_updated = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        prev_idle, prev_kernel, prev_user = get_system_cpu_times()

        while self._running:
            # Poll interval: ~1.8 seconds in slices so thread can terminate promptly
            for _ in range(18):
                if not self._running:
                    return
                time.sleep(0.1)

            cur_idle, cur_kernel, cur_user = get_system_cpu_times()
            sys_delta = (cur_kernel - prev_kernel) + (cur_user - prev_user)
            idle_delta = cur_idle - prev_idle
            prev_idle, prev_kernel, prev_user = cur_idle, cur_kernel, cur_user

            cpu_pct = 0.0
            if sys_delta > 0:
                cpu_pct = max(0.0, min(100.0, (1.0 - (idle_delta / sys_delta)) * 100.0))

            used_gb, total_gb, ram_pct = get_system_ram_info()
            gpu_pct, gpu_vram, gpu_name = get_system_gpu_info()

            # Compact badge text (Fits comfortably in top bar)
            badge_text = f"⚡ CPU: {int(round(cpu_pct))}% | RAM: {used_gb:.1f}G ({ram_pct}%) | GPU: {gpu_pct}%"

            # Rich tooltip with full Cambodian and English hardware specs
            tooltip = (
                f"📊 ស្ថានភាពធនធានកុំព្យូទ័រផ្ទាល់ (Real-Time Hardware Monitor):\n"
                f"• CPU Load: {cpu_pct:.1f}%\n"
                f"• RAM Memory: {used_gb:.1f} GB / {total_gb:.1f} GB ({ram_pct}% ប្រើប្រាស់)\n"
                f"• GPU Engine: {gpu_name} ({gpu_pct}% Load | VRAM: {gpu_vram})\n"
                f"• Acceleration: Fast Hardware NVENC / MediaFoundation"
            )

            if self._running:
                self.metrics_updated.emit(badge_text, tooltip)
