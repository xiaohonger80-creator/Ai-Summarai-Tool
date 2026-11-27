import gc
import json
import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import List, Dict, Any, Optional

from core.sub_styles import KHMER_SUB_STYLES, get_sub_style
from core.lut_presets import get_lut_ffmpeg_filter
from core.system_monitor import get_hardware_profile

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class MediaEngine:
    _cached_v_encoder: List[str] = None
    _active_procs: set = set()
    _proc_lock = threading.Lock()

    ENCODER_NAMES = {
        "h264_nvenc": "🎮 GPU: NVIDIA NVENC",
        "h264_qsv": "🎮 GPU: Intel QSV",
        "h264_amf": "🎮 GPU: AMD AMF",
        "h264_mf": "🚀 GPU: Windows MediaFoundation (Ultra Fast)",
        "h264_videotoolbox": "🎮 GPU: Apple VideoToolbox",
        "libx264": "💻 CPU: Ultrafast (Multi-threaded)",
    }

    HW_CODECS = ("h264_nvenc", "h264_qsv", "h264_amf", "h264_mf", "h264_videotoolbox")

    @classmethod
    def cancel_all_processes(cls):
        """Gracefully terminates all active FFmpeg subprocesses (prevents zombies & hangs)."""
        with cls._proc_lock:
            procs = list(cls._active_procs)
        for p in procs:
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        deadline = time.monotonic() + 1.5
        for p in procs:
            try:
                if p.poll() is None:
                    rem = max(0.05, deadline - time.monotonic())
                    p.wait(timeout=rem)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    @classmethod
    def _build_cpu_fallback_cmd(cls, cmd: List[str], quality_preset: str = "balanced") -> Optional[List[str]]:
        """
        Replaces any GPU encoder block (-c:v h264_nvenc/qsv/amf/mf ...) with safe CPU libx264 flags.
        Returns None if the command does not use a GPU video encoder.
        """
        hw_codec_found = None
        for c in cls.HW_CODECS:
            if c in cmd:
                hw_codec_found = c
                break
        if not hw_codec_found:
            return None

        hw = get_hardware_profile()
        q_p = str(quality_preset or "balanced").lower()
        if q_p in ("ultrafast", "speed"):
            cpu_flags = ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode", "-crf", "25", "-threads", str(hw["ffmpeg_threads"])]
        elif q_p == "high":
            cpu_flags = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-threads", str(hw["ffmpeg_threads"])]
        elif q_p == "small":
            cpu_flags = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-threads", str(hw["ffmpeg_threads"])]
        else:
            cpu_flags = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", str(hw["ffmpeg_threads"])]

        # Strip GPU-specific option pairs associated with the GPU encoder
        gpu_only_opts = {
            "-preset", "-tune", "-cq", "-global_quality", "-quality",
            "-rc", "-qp_i", "-qp_p", "-b:v",
        }
        new_cmd = []
        i = 0
        replaced = False
        while i < len(cmd):
            tok = cmd[i]
            if tok == "-c:v" and i + 1 < len(cmd) and cmd[i + 1] == hw_codec_found:
                new_cmd.extend(cpu_flags)
                replaced = True
                i += 2
                # Skip immediately following GPU encoder parameters until next non-GPU flag
                while i < len(cmd) and cmd[i] in gpu_only_opts:
                    i += 2
                continue
            new_cmd.append(tok)
            i += 1
        return new_cmd if replaced else None

    @classmethod
    def run_ffmpeg_safe(
        cls,
        cmd: List[str],
        fallback_cpu: bool = True,
        quality_preset: str = "balanced",
        timeout_sec: Optional[float] = None,
        low_priority: bool = True,
        cancel_event: Any = None,
        progress_cb: Any = None,
    ) -> int:
        """
        Crash-proof FFmpeg runner with:
        1. Windows background priority (IDLE on low-spec PCs, BELOW_NORMAL on mid/high) so UI NEVER freezes.
        2. Async stderr tail draining (prevents pipe deadlocks and memory leaks).
        3. Watchdog timeout & cancel_event support (cleanly kills hung processes).
        4. Automatic CPU/GPU Auto-Balance: gracefully falls back to libx264 if GPU encoding fails.
        """
        hw = get_hardware_profile()
        cflags = hw["creationflags"] if low_priority else CREATE_NO_WINDOW

        def _exec_once(exec_cmd: List[str]):
            tail_lines = deque(maxlen=25)
            proc = subprocess.Popen(
                exec_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=cflags,
            )
            with cls._proc_lock:
                cls._active_procs.add(proc)

            def _drain_stderr():
                try:
                    if proc.stderr:
                        for raw in iter(proc.stderr.readline, b""):
                            if not raw:
                                break
                            line = raw.decode("utf-8", errors="ignore").strip()
                            if line:
                                tail_lines.append(line)
                except Exception:
                    pass

            reader = threading.Thread(target=_drain_stderr, daemon=True)
            reader.start()

            start_t = time.monotonic()
            try:
                while proc.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        proc.terminate()
                        try:
                            proc.wait(timeout=2.0)
                        except Exception:
                            proc.kill()
                        raise InterruptedError("⏹ ការដំណើរការ FFmpeg ត្រូវបានបញ្ឈប់ដោយអ្នកប្រើប្រាស់។")
                    if timeout_sec and (time.monotonic() - start_t) > timeout_sec:
                        proc.terminate()
                        try:
                            proc.wait(timeout=2.0)
                        except Exception:
                            proc.kill()
                        raise TimeoutError(f"FFmpeg លើសពេលកំណត់ ({int(timeout_sec)}s) ហើយត្រូវបានបិទដោយសុវត្ថិភាព។")
                    time.sleep(0.08)
                rc = proc.wait()
            finally:
                reader.join(timeout=1.0)
                try:
                    if proc.stderr:
                        proc.stderr.close()
                except Exception:
                    pass
                with cls._proc_lock:
                    cls._active_procs.discard(proc)
            return rc, "\n".join(tail_lines)

        rc, err_tail = _exec_once(cmd)
        if rc == 0:
            return 0

        if fallback_cpu:
            cpu_cmd = cls._build_cpu_fallback_cmd(cmd, quality_preset=quality_preset)
            if cpu_cmd:
                if progress_cb:
                    progress_cb(62, "🔄 GPU Encoder មិនគាំទ្រ — កំពុងប្តូរទៅ CPU libx264 ដោយស្វ័យប្រវត្តិ...")
                rc2, err_tail2 = _exec_once(cpu_cmd)
                if rc2 == 0:
                    return 0
                err_tail = err_tail2 or err_tail
                rc = rc2

        err_msg = err_tail[-600:] if err_tail else f"FFmpeg exited with code {rc}"
        raise RuntimeError(f"FFmpeg Error (code {rc}):\n{err_msg}")

    @classmethod
    def detect_video_encoder(cls) -> List[str]:
        return cls.get_optimal_video_encoder()

    @classmethod
    def get_encoder_label(cls) -> str:
        flags = cls.detect_video_encoder()
        codec = flags[1] if len(flags) > 1 else "libx264"
        return cls.ENCODER_NAMES.get(codec, f"⚙️ {codec}")

    @classmethod
    def _parse_masks(cls, edits: Dict) -> List[Dict]:
        """ទាញយកបញ្ជី Mask ទាំងអស់ (គាំទ្រទាំង Masks ច្រើន និង Mask តែមួយចាស់)"""
        if not edits:
            return []
        masks = []
        raw = edits.get("masks_json")
        if raw:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list):
                    for m in parsed:
                        if m.get("enabled", 1):
                            masks.append(m)
            except Exception:
                pass
        if not masks and edits.get("mask_enabled", 0):
            masks.append({
                "id": 1,
                "name": "Mask 1",
                "enabled": 1,
                "mode": edits.get("mask_mode", "blur"),
                "x": float(edits.get("mask_x", 0.05)),
                "y": float(edits.get("mask_y", 0.78)),
                "w": float(edits.get("mask_w", 0.90)),
                "h": float(edits.get("mask_h", 0.14)),
                "strength": float(edits.get("mask_strength", 0.75)),
                "color": edits.get("mask_color", "#000000"),
            })

        # Auto Blur Chinese Text: Inject smart multi-zone Chinese text blur masks (Bottom Subs, Actor Names, Floating Titles)
        has_blur = any(m.get("enabled", 1) and m.get("mode", "blur") == "blur" for m in masks)
        if not has_blur and (bool(edits.get("auto_blur_chinese", 1)) or bool(edits.get("anti_copyright_enabled", 1))):
            smart_zones = [
                {
                    "id": 91,
                    "name": "Auto Bottom Subtitles (អក្សររត់)",
                    "enabled": 1,
                    "mode": "blur",
                    "x": float(edits.get("mask_x", 0.03)),
                    "y": float(edits.get("mask_y", 0.74)),
                    "w": float(edits.get("mask_w", 0.94)),
                    "h": float(edits.get("mask_h", 0.20)),
                    "strength": float(edits.get("mask_strength", 0.88)),
                    "color": "#000000",
                },
                {
                    "id": 92,
                    "name": "Auto Left Character Name (ឈ្មោះតួអង្គឆ្វេង)",
                    "enabled": 1,
                    "mode": "blur",
                    "x": 0.02,
                    "y": 0.20,
                    "w": 0.18,
                    "h": 0.45,
                    "strength": 0.88,
                    "color": "#000000",
                },
                {
                    "id": 93,
                    "name": "Auto Right Character Name (ឈ្មោះតួអង្គស្តាំ)",
                    "enabled": 1,
                    "mode": "blur",
                    "x": 0.80,
                    "y": 0.20,
                    "w": 0.18,
                    "h": 0.45,
                    "strength": 0.88,
                    "color": "#000000",
                },
                {
                    "id": 94,
                    "name": "Auto Top Title Card (ចំណងជើង/ភាគលើ)",
                    "enabled": 1,
                    "mode": "blur",
                    "x": 0.02,
                    "y": 0.02,
                    "w": 0.38,
                    "h": 0.12,
                    "strength": 0.88,
                    "color": "#000000",
                },
            ]
            masks.extend(smart_zones)
        return masks

    @classmethod
    def needs_video_render(cls, edits: Dict) -> bool:
        """Returns True if any visual filter, logo, crop, or trim requires video encoding."""
        if not edits:
            return False
        bright = float(edits.get("brightness", 0.0))
        contrast = float(edits.get("contrast", 1.0))
        sat = float(edits.get("saturation", 1.0))
        has_eq = abs(bright) > 0.01 or abs(contrast - 1.0) > 0.01 or abs(sat - 1.0) > 0.01
        has_ratio = edits.get("aspect_ratio", "original") != "original"
        has_burn = bool(edits.get("burn_subs", 0))
        logo_path = edits.get("logo_path", "")
        has_logo = bool(logo_path and Path(logo_path).exists())
        has_trim = int(edits.get("trim_start_ms", 0)) > 0 or (
            int(edits.get("trim_end_ms", 0)) > int(edits.get("trim_start_ms", 0))
        )
        has_mask = bool(cls._parse_masks(edits))
        has_ac = bool(edits.get("anti_copyright_enabled", 0))
        has_auto_blur = bool(edits.get("auto_blur_chinese", 0))
        has_lut = bool(get_lut_ffmpeg_filter(edits.get("lut_preset", "none")))
        has_hook = bool(edits.get("hook_enabled", 0) and (edits.get("hook_text") or "").strip())
        has_intro = bool(edits.get("intro_enabled", 0) and edits.get("intro_path") and Path(edits["intro_path"]).exists())
        has_outro = bool(edits.get("outro_enabled", 0) and edits.get("outro_path") and Path(edits["outro_path"]).exists())
        has_hd_upscale = bool(edits.get("hd_upscale_enabled", 0))
        return any([
            has_eq, has_ratio, has_burn, has_logo, has_trim,
            has_mask, has_ac, has_auto_blur, has_lut, has_hook, has_intro, has_outro, has_hd_upscale
        ])

    @classmethod
    def get_optimal_video_encoder(cls) -> List[str]:
        """Auto-detects the fastest working H.264 encoder for low-spec PCs.

        1. GPU Offload (if available): h264_nvenc (NVIDIA), h264_qsv (Intel QuickSync), h264_amf (AMD)
        2. Old CPU Fallback: libx264 -preset ultrafast -threads N/2 (smooth background render without freezing Windows)
        """
        if cls._cached_v_encoder is not None:
            return cls._cached_v_encoder

        hw_candidates = [
            ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "23"]),
            ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"]),
            ("h264_amf", ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]),
            ("h264_mf", ["-c:v", "h264_mf", "-quality", "0", "-b:v", "4.5M"]),
        ]
        for enc_name, flags in hw_candidates:
            try:
                res = subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.1",
                        "-c:v", enc_name, "-f", "null", "-"
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=4,
                    creationflags=CREATE_NO_WINDOW,
                )
                if res.returncode == 0:
                    cls._cached_v_encoder = flags
                    return flags
            except Exception:
                continue

        hw = get_hardware_profile()
        enc_threads = str(hw["ffmpeg_threads"])
        cpu_preset = "ultrafast" if hw["tier"] == "low" else "veryfast"
        cls._cached_v_encoder = [
            "-c:v", "libx264",
            "-preset", cpu_preset,
            "-crf", "23",
            "-threads", enc_threads,
        ]
        return cls._cached_v_encoder

    @classmethod
    def probe_video_info(cls, video_path: str) -> tuple[int, int, int]:
        """
        វាស់ Duration (ms) និង Resolution (Width, Height) ក្នុង FFprobe តែមួយជុំ (timeout 2.5s)
        ការពារកុំឲ្យ UI គាំងពេល Import វីដេអូធំៗ ឬវីដេអូពី Drive ខាងក្រៅ។
        """
        if not video_path or not Path(video_path).exists():
            return 1000, 16, 9
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height:format=duration",
                "-of", "csv=s=x:p=0",
                str(video_path),
            ]
            out = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL, timeout=2.5, creationflags=CREATE_NO_WINDOW
            ).decode("utf-8", errors="ignore").strip()
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            w, h, dur_ms = 16, 9, 1000
            for l in lines:
                if "x" in l:
                    parts = l.split("x")
                    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                        w, h = int(parts[0]), int(parts[1])
                else:
                    try:
                        dur_ms = max(100, int(float(l) * 1000))
                    except Exception:
                        pass
            return dur_ms, w, h
        except Exception:
            return 1000, 16, 9

    @staticmethod
    def get_duration_ms(video_path: str) -> int:
        if not video_path:
            return 1000
        try:
            out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path
                ],
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                creationflags=CREATE_NO_WINDOW,
            ).decode().strip()
            return max(100, int(float(out) * 1000))
        except Exception:
            return 1000

    @staticmethod
    def get_duration_sec(video_path: str) -> float:
        return MediaEngine.get_duration_ms(video_path) / 1000.0

    @classmethod
    def merge_clips_to_timeline(cls, video_paths: List[str], out_merged_mp4: str) -> List[Dict]:
        """
        តភ្ជាប់វីដេអូរហូតដល់ 50 ឈុតចូលគ្នាជា Timeline តែមួយ (Continuous Sequence)
        ប្រើ '-c copy' ជាមុនដើម្បីតភ្ជាប់ក្នុង 2 វិនាទី (0% CPU/RAM) និងត្រឡប់មកវិញនូវម៉ោងចាប់ផ្តើម-បញ្ចប់នៃឈុតនីមួយៗ។
        """
        if not video_paths:
            raise ValueError("No videos provided.")

        out_path = Path(out_merged_mp4)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # ១. វាស់រយៈពេលពិតប្រាកដនៃឈុតវីដេអូនីមួយៗ ដើម្បីបង្ហាញលើ Timeline
        clip_markers = []
        cursor_ms = 0
        for idx, vp in enumerate(video_paths, start=1):
            dur_ms = cls.get_duration_ms(vp)
            clip_markers.append({
                "index": idx,
                "name": Path(vp).name,
                "start_ms": cursor_ms,
                "end_ms": cursor_ms + dur_ms,
            })
            cursor_ms += dur_ms

        if len(video_paths) == 1:
            import shutil
            shutil.copy2(video_paths[0], str(out_path))
            return clip_markers

        # ២. បង្កើតឯកសារ concat_list.txt សម្រាប់ FFmpeg
        list_file = out_path.parent / "concat_list.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for vp in video_paths:
                safe_path = str(Path(vp).resolve()).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        # ៣. សាកល្បង Fast Stream Copy (-c copy) មុនគេ (លឿនបំផុត 0% CPU!)
        fast_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path)
        ]
        hw = get_hardware_profile()
        res = subprocess.run(fast_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hw["creationflags"])

        # ៤. បើវីដេអូខ្លះខុស Resolution/Codec គ្នា ប្រើ GPU Encode បង្រួមឲ្យស្មើគ្នា (មាន CPU Fallback ស្វ័យប្រវត្តិ)
        if res.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
            vw, vh = cls._probe_resolution(video_paths[0])
            inputs = []
            vf_parts = []
            concat_in = []
            for i, vp in enumerate(video_paths):
                inputs.extend(["-i", vp])
                vf_parts.append(
                    f"[{i}:v]scale={vw}:{vh}:force_original_aspect_ratio=decrease,"
                    f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}];"
                )
                if cls._has_audio_stream(vp):
                    vf_parts.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}];")
                else:
                    dur_sec = max(0.1, (clip_markers[i]["end_ms"] - clip_markers[i]["start_ms"]) / 1000.0)
                    vf_parts.append(f"anullsrc=r=44100:cl=stereo:d={dur_sec:.3f}[a{i}];")
                concat_in.append(f"[v{i}][a{i}]")

            vf_parts.append(f"{''.join(concat_in)}concat=n={len(video_paths)}:v=1:a=1[vout][aout]")
            gpu_flags = cls.detect_video_encoder()
            norm_cmd = [
                "ffmpeg", "-y", "-threads", str(hw["ffmpeg_threads"]), *inputs,
                "-filter_complex", "".join(vf_parts),
                "-map", "[vout]", *gpu_flags,
                "-map", "[aout]", "-c:a", "aac", "-b:a", "160k",
                "-max_muxing_queue_size", "1024",
                str(out_path)
            ]
            cls.run_ffmpeg_safe(norm_cmd, fallback_cpu=True, quality_preset="ultrafast")

        list_file.unlink(missing_ok=True)
        gc.collect()
        return clip_markers

    @classmethod
    def extract_audio(cls, video_path: str, out_wav: str):
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        hw = get_hardware_profile()
        cmd = [
            "ffmpeg", "-y", "-threads", str(min(2, hw["ffmpeg_threads"])),
            "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            out_wav
        ]
        cls.run_ffmpeg_safe(cmd, fallback_cpu=False)

    @classmethod
    def extract_subtitle_frames(
        cls,
        video_path: str,
        frames_dir: str,
        fps: int = 4,
        crop_ratio: float = 0.28,
        crop_y_offset: float = None,
    ):
        """
        ស្កេន 4 FPS លើតំបន់ 28% ខាងក្រោមនៃវីដេអូ + បង្កើន Contrast
        ដើម្បីចាប់យកប្រយោគខ្លីៗ (0.3s) ដោយមិនរំលង និងមិនបាច់ប្រើ RAM ច្រើន។
        """
        out_dir = Path(frames_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.jpg"):
            old.unlink()
        crop_ratio = max(0.08, min(0.60, float(crop_ratio)))
        if crop_y_offset is None:
            crop_y_offset = 1.0 - crop_ratio
        crop_y_offset = max(0.0, min(1.0 - crop_ratio, float(crop_y_offset)))
        vf = (
            f"fps={fps},"
            f"crop=iw:ih*{crop_ratio:.3f}:0:ih*{crop_y_offset:.3f},"
            f"eq=contrast=1.25:brightness=0.02"
        )
        hw = get_hardware_profile()
        cmd = [
            "ffmpeg", "-y", "-threads", str(min(2, hw["ffmpeg_threads"])),
            "-i", video_path,
            "-vf", vf, "-q:v", "2",
            str(out_dir / "frame_%06d.jpg")
        ]
        cls.run_ffmpeg_safe(cmd, fallback_cpu=False)

    @classmethod
    def fit_audio_to_duration(cls, in_mp3: str, out_wav: str, target_ms: int):
        """Adjusts TTS playback tempo slightly so Khmer dub fits the scene window."""
        probe = subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", in_mp3
            ],
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        ).decode().strip()
        actual_ms = max(1, int(float(probe) * 1000))
        target_ms = max(300, target_ms)

        ratio = actual_ms / target_ms
        # Clamp tempo between 0.85x and 1.35x to keep Khmer speech natural
        tempo = min(1.35, max(0.85, ratio)) if ratio > 1.05 else 1.0

        cmd = [
            "ffmpeg", "-y", "-i", in_mp3,
            "-filter:a", f"atempo={tempo:.2f}",
            "-ar", "44100", "-ac", "2", out_wav
        ]
        cls.run_ffmpeg_safe(cmd, fallback_cpu=False)

    @staticmethod
    def _ms_to_ass_time(ms: int) -> str:
        ms = max(0, int(ms))
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, rem_ms = divmod(rem, 1000)
        cs = rem_ms // 10
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def _hex_to_ass_color(hex_color: str, alpha: str = "00") -> str:
        c = (hex_color or "#FFFFFF").lstrip("#")
        if len(c) != 6:
            c = "FFFFFF"
        r, g, b = c[0:2], c[2:4], c[4:6]
        return f"&H{alpha}{b}{g}{r}"

    KHMER_SUB_STYLES = KHMER_SUB_STYLES

    @staticmethod
    def _wrap_khmer_ass_lines(text: str, max_chars_per_line: int) -> List[str]:
        """
        Wraps Khmer subtitle text cleanly without breaking Khmer consonant clusters
        (subscripts \\u17D2 and dependent vowels \\u17B4-\\u17D3) so burned ASS lines
        stay strictly inside the 8% left/right safe margin across 9:16, 16:9, and 1:1.
        """
        raw = (text or "").strip()
        if not raw:
            return []
        max_c = max(10, int(max_chars_per_line))
        dependents = set(chr(c) for c in range(0x17B4, 0x17D4)) | {"\u17D2"}

        # Tokenize into indivisible Khmer grapheme clusters (or space-delimited chunks)
        def _split_clusters(word: str) -> List[str]:
            clusters = []
            i = 0
            n = len(word)
            while i < n:
                ch = word[i]
                i += 1
                while i < n:
                    if word[i] in dependents:
                        ch += word[i]
                        i += 1
                    elif i > 0 and word[i - 1] == "\u17D2":
                        ch += word[i]
                        i += 1
                    elif i + 1 < n and word[i + 1] == "\u17D2":
                        # Don't merge next base consonant into current cluster; stop before next base
                        break
                    else:
                        break
                clusters.append(ch)
            return clusters

        out_lines: List[str] = []
        for para in raw.split("\n"):
            para = para.strip()
            if not para:
                continue
            words = para.split(" ")
            cur = ""
            for w in words:
                if not w:
                    continue
                if len(w) <= max_c:
                    if not cur:
                        cur = w
                    elif len(cur) + 1 + len(w) <= max_c:
                        cur = cur + " " + w
                    else:
                        out_lines.append(cur)
                        cur = w
                else:
                    # Break long unspaced Khmer phrase cleanly at cluster boundaries
                    if cur:
                        out_lines.append(cur)
                        cur = ""
                    for cl in _split_clusters(w):
                        if len(cur) + len(cl) <= max_c:
                            cur += cl
                        else:
                            if cur:
                                out_lines.append(cur)
                            cur = cl
            if cur:
                out_lines.append(cur)
        return out_lines or [raw]

    @classmethod
    def write_khmer_ass(cls, segments: List[Dict], out_ass_path: str, edits: Dict, vid_w: int = 1080, vid_h: int = 1920) -> str:
        """
        បង្កើតឯកសារ .ass ជាមួយ Style អក្សរខ្មែរទាំង ១០០ ម៉ូដ, Custom Font Selector,
        និង 8% Safe-Zone Wrapping (WrapStyle: 1) ធានាមិនឲ្យអក្សរលៀនចេញក្រៅស៊ុមវីដេអូឡើយ!
        """
        Path(out_ass_path).parent.mkdir(parents=True, exist_ok=True)
        edits = edits or {}
        # Scale font proportionally against shortest/reference video dimension so 9:16 & 16:9 both fit cleanly
        ref_h = min(vid_h, int(vid_w * 1.15)) if vid_w < vid_h else vid_h
        base_font_size = max(18, int(round(int(edits.get("sub_font_size", 24)) * (ref_h / 480.0))))
        style_key = edits.get("sub_style", "classic_box")
        st = get_sub_style(style_key)

        custom_font = (edits.get("sub_font_family") or "").strip()
        font_name = custom_font if custom_font else st.get("font", "Khmer OS Battambang")

        hex_col = (edits.get("sub_color") or "#FFFFFF").lstrip("#")
        if style_key == "classic_box" and len(hex_col) == 6:
            primary_bgr = f"&H00{hex_col[4:6]}{hex_col[2:4]}{hex_col[0:2]}"
            border_style = 3 if int(edits.get("sub_bg", 1)) else 1
        else:
            primary_bgr = st["primary"]
            border_style = int(st.get("border_style", 1))

        outline_val = edits.get("sub_outline", st.get("outline", 2))
        if outline_val is None:
            outline_val = st.get("outline", 2)

        # CRITICAL ASS v4+ Spec:
        # - BorderStyle=3 (Opaque Box): OutlineColour renders the box background fill & Outline controls box padding!
        # - BorderStyle=1 (Outline + Shadow): OutlineColour renders text stroke & BackColour renders drop shadow!
        if border_style == 3:
            ass_outline_col = st["back_col"]
            ass_back_col = "&H80000000"
            ass_outline_w = max(5, int(outline_val) + 4)
            ass_shadow = 0
        else:
            ass_outline_col = st["outline_col"]
            ass_back_col = st["back_col"]
            ass_outline_w = max(0, int(outline_val))
            ass_shadow = max(0, int(st.get("shadow", 2)))

        # Safe-Zone Margins: at least 8% Left & Right, and MarginV safely clamped inside [24, 92% of vid_h]
        margin_l = max(24, int(round(vid_w * 0.08)))
        margin_r = max(24, int(round(vid_w * 0.08)))
        raw_margin_v = int(round((1.0 - float(edits.get("sub_y", 0.85))) * vid_h))
        margin_v = max(24, min(int(vid_h * 0.92), raw_margin_v))
        bold_flag = -1 if int(st.get("bold", 1)) else 0

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {vid_w}\n"
            f"PlayResY: {vid_h}\n"
            "WrapStyle: 1\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: KhmerDub,{font_name},{base_font_size},{primary_bgr},&H000000FF,{ass_outline_col},{ass_back_col},"
            f"{bold_flag},0,0,0,100,100,0,0,{border_style},{ass_outline_w},{ass_shadow},2,{margin_l},{margin_r},{margin_v},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        def fmt_ass_time(ms: int) -> str:
            ms = max(0, int(ms))
            h = ms // 3600000
            m = (ms % 3600000) // 60000
            s = (ms % 60000) // 1000
            cs = (ms % 1000) // 10
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

        from core.translator import normalize_dub_khmer_text
        safe_w = max(120, vid_w - margin_l - margin_r)
        # Khmer glyph average advance width is ~0.58 * font_size
        chars_per_line = max(12, int(safe_w / max(10.0, base_font_size * 0.58)))

        lines = [header]
        for seg in segments:
            raw_txt = (seg.get("kh_text") or seg.get("zh_text") or "").strip()
            txt = normalize_dub_khmer_text(raw_txt) if seg.get("kh_text") else raw_txt
            if not txt:
                continue

            wrapped = cls._wrap_khmer_ass_lines(txt, chars_per_line)
            override_prefix = ""
            # Auto-scale font down slightly if text wraps past 2 lines so it stays compact & inside frame
            if len(wrapped) > 2:
                smaller_fs = max(16, int(round(base_font_size * 0.84)))
                wider_cpl = max(14, int(safe_w / max(10.0, smaller_fs * 0.58)))
                wrapped = cls._wrap_khmer_ass_lines(txt, wider_cpl)
                override_prefix = f"{{\\fs{smaller_fs}}}"

            ass_text = override_prefix + "\\N".join(wrapped)
            lines.append(
                f"Dialogue: 0,{fmt_ass_time(seg['start_ms'])},{fmt_ass_time(seg['end_ms'])},KhmerDub,,0,0,0,,{ass_text}\n"
            )

        Path(out_ass_path).write_text("".join(lines), encoding="utf-8-sig")
        return out_ass_path

    @classmethod
    def write_ass_subtitles(cls, segments: List[Dict], edits: Dict, out_ass: str, vid_w: int = 1080, vid_h: int = 1920) -> str:
        """Generates a UTF-8-SIG ASS subtitle file styled to match the VideoPreviewEditor inspector."""
        ratio = (edits or {}).get("aspect_ratio", "original")
        if ratio == "16:9":
            vid_w, vid_h = 1920, 1080
        elif ratio == "1:1":
            vid_w, vid_h = 1080, 1080
        elif ratio == "9:16":
            vid_w, vid_h = 1080, 1920
        return cls.write_khmer_ass(segments, out_ass, edits or {}, vid_w=vid_w, vid_h=vid_h)

    @classmethod
    def write_dynamic_blur_mask_ass(
        cls,
        segments: List[Dict],
        blur_masks: List[Dict],
        vid_w: int,
        vid_h: int,
        output_ass_path: str,
        smooth_fade_ms: int = 55,
    ) -> bool:
        """
        Creates a timed ASS vector alpha mask for FFmpeg maskedmerge:
        - When dialogue / Chinese text is active (seg['start_ms'] -> seg['end_ms']):
          * If OCR captured an exact localized bounding box (`bbox_json`), blurs ONLY that localized text region
            (plus any custom user-added non-default masks).
          * Otherwise, blurs active blur_masks strictly within [start_ms, end_ms].
          * Applies smooth ASS fade-in/fade-out (\\fad) for seamless on/off transition.
        - On frames with NO active subtitle:
          * Mask remains 100% pure black -> maskedmerge passes original clean video through at 0% blur!
        """
        def _ms_to_ass(ms: int) -> str:
            ms = max(0, int(ms))
            total_sec = ms // 1000
            centisec = (ms % 1000) // 10
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            s = total_sec % 60
            return f"{h:01d}:{m:02d}:{s:02d}.{centisec:02d}"

        valid_segs = [s for s in (segments or []) if int(s.get("end_ms", 0)) > int(s.get("start_ms", 0))]
        if not valid_segs:
            return False

        active_masks = [bm for bm in (blur_masks or []) if bm.get("enabled", 1)]
        auto_zone_ids = {91, 92, 93, 94, "mask_1", "mask_2", "mask_3", "mask_4"}
        custom_masks = [bm for bm in active_masks if bm.get("id") not in auto_zone_ids]

        events = []
        for seg in valid_segs:
            s_ms = int(seg["start_ms"])
            e_ms = int(seg["end_ms"])
            seg_dur = max(100, e_ms - s_ms)
            fade_ms = max(0, min(int(smooth_fade_ms), seg_dur // 4))
            fad_tag = f"\\fad({fade_ms},{fade_ms})" if fade_ms >= 15 else ""
            t_start = _ms_to_ass(s_ms)
            t_end = _ms_to_ass(e_ms)

            # Check if OCR captured a localized bounding box for this exact subtitle segment
            seg_bbox = None
            raw_bbox = seg.get("bbox_json")
            if raw_bbox:
                try:
                    parsed = json.loads(raw_bbox) if isinstance(raw_bbox, str) else raw_bbox
                    if isinstance(parsed, dict) and all(k in parsed for k in ("x", "y", "w", "h")):
                        seg_bbox = parsed
                except Exception:
                    seg_bbox = None

            boxes_for_seg = []
            if seg_bbox is not None:
                boxes_for_seg.append(seg_bbox)
                # Also honor any custom user-drawn masks if present
                boxes_for_seg.extend(custom_masks)
            else:
                boxes_for_seg.extend(active_masks)

            for bm in boxes_for_seg:
                mx = max(0.0, min(0.98, float(bm.get("x", 0.05))))
                my = max(0.0, min(0.98, float(bm.get("y", 0.78))))
                mw = max(0.02, min(1.0, float(bm.get("w", 0.90))))
                mh = max(0.02, min(1.0, float(bm.get("h", 0.14))))
                if mx + mw > 1.0:
                    mw = max(0.02, round(1.0 - mx, 3))
                if my + mh > 1.0:
                    mh = max(0.02, round(1.0 - my, 3))

                px = int(vid_w * mx)
                py = int(vid_h * my)
                pw = max(4, int(vid_w * mw))
                ph = max(4, int(vid_h * mh))

                draw_cmd = f"m 0 0 l {pw} 0 l {pw} {ph} l 0 {ph}"
                evt_text = f"{{\\an7\\pos({px},{py}){fad_tag}\\p1\\1c&HFFFFFF&\\1a&H00&\\bord0\\shad0}}{draw_cmd}{{\\p0}}"
                events.append(f"Dialogue: 0,{t_start},{t_end},MaskBox,,0,0,0,,{evt_text}")

        if not events:
            return False

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {vid_w}
PlayResY: {vid_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MaskBox,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        full_content = header + "\n".join(events) + "\n"
        Path(output_ass_path).write_text(full_content, encoding="utf-8")
        return True

    @staticmethod
    def _probe_resolution(video_path: str) -> tuple[int, int]:
        try:
            out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
                    video_path,
                ],
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                creationflags=CREATE_NO_WINDOW,
            ).decode().strip()
            w_s, h_s = out.split("x")
            return max(200, int(w_s)), max(200, int(h_s))
        except Exception:
            return 1080, 1920

    @staticmethod
    def _has_audio_stream(video_path: str) -> bool:
        """ពិនិត្យមើលថាតើវីដេអូដើមមាន Audio Track ឬអត់ ការពារកុំឲ្យ FFmpeg Error"""
        try:
            out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                    video_path,
                ],
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                creationflags=CREATE_NO_WINDOW,
            ).decode().strip()
            return bool(out)
        except Exception:
            return False

    @staticmethod
    def _probe_audio_channels(video_path: str) -> int:
        """វាស់ចំនួន Audio Channels (1 = Mono, 2 = Stereo) ដើម្បីជ្រើសរើស Filter បំបាត់សំឡេងនិយាយឲ្យត្រឹមត្រូវ"""
        try:
            out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=channels",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                creationflags=CREATE_NO_WINDOW,
            ).decode().strip()
            first = out.splitlines()[0].strip() if out else ""
            return max(1, int(first)) if first.isdigit() else 2
        except Exception:
            return 2

    @classmethod
    def extract_clean_bgm(cls, video_path: str, out_bgm_wav: str, cancel_event: Any = None) -> str:
        """
        AI Vocal Remover & Clean BGM Extractor (🎼 បំបាត់សំឡេងនិយាយដើម រក្សាទុកតែភ្លេង BGM & SFX):
        - Stereo source (>= 2 channels): center-channel vocal cancellation + spectral bandpass isolation
          (`pan=stereo|c0=c0-c1|c1=c1-c0,highpass=f=120,lowpass=f=14000,dynaudnorm`).
        - Mono source or filter fallback: automatic fallback to
          `aformat=channel_layouts=stereo,stereotools=mlev=0.015:slev=1.2,highpass=f=120,lowpass=f=14000,dynaudnorm`.
        """
        if not video_path or not Path(video_path).exists() or not cls._has_audio_stream(video_path):
            return ""

        out_p = Path(out_bgm_wav)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        hw = get_hardware_profile()
        ff_threads = str(min(2, hw["ffmpeg_threads"]))
        channels = cls._probe_audio_channels(video_path)

        stereo_af = "pan=stereo|c0=c0-c1|c1=c1-c0,highpass=f=120,lowpass=f=14000,dynaudnorm"
        # Note: FFmpeg stereotools mlev valid range is [0.015625, 64] -> use 0.016 (-36dB center vocal cut)
        mono_fallback_af = "aformat=channel_layouts=stereo,stereotools=mlev=0.016:slev=1.2,highpass=f=120,lowpass=f=14000,dynaudnorm"
        safe_notch_af = "highpass=f=120,lowpass=f=14000,equalizer=f=1200:t=h:w=1800:g=-14,dynaudnorm"

        def _run_extract(af_chain: str):
            cmd = [
                "ffmpeg", "-y", "-threads", ff_threads,
                "-i", video_path,
                "-vn",
                "-af", af_chain,
                "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                str(out_p),
            ]
            cls.run_ffmpeg_safe(cmd, fallback_cpu=False, cancel_event=cancel_event)

        if channels >= 2:
            try:
                _run_extract(stereo_af)
            except InterruptedError:
                raise
            except Exception:
                try:
                    _run_extract(mono_fallback_af)
                except InterruptedError:
                    raise
                except Exception:
                    _run_extract(safe_notch_af)
        else:
            try:
                _run_extract(mono_fallback_af)
            except InterruptedError:
                raise
            except Exception:
                _run_extract(safe_notch_af)

        return str(out_p) if (out_p.exists() and out_p.stat().st_size > 1024) else ""

    @classmethod
    def _get_or_extract_clean_bgm(cls, video_path: str, work_dir: Path, cancel_event: Any = None) -> str:
        """Caches extracted vocal-removed BGM inside work_dir keyed by source video size + mtime."""
        if not video_path or not Path(video_path).exists():
            return ""
        src_p = Path(video_path)
        try:
            st = src_p.stat()
            sig = f"{src_p.resolve()}|{st.st_size}|{int(st.st_mtime)}"
        except Exception:
            sig = str(video_path)

        cache_wav = work_dir / "_clean_bgm_extracted.wav"
        meta_file = work_dir / "_clean_bgm_extracted.meta"
        if cache_wav.exists() and cache_wav.stat().st_size > 1024 and meta_file.exists():
            try:
                if meta_file.read_text(encoding="utf-8").strip() == sig:
                    return str(cache_wav)
            except Exception:
                pass

        extracted = cls.extract_clean_bgm(video_path, str(cache_wav), cancel_event=cancel_event)
        if extracted:
            try:
                meta_file.write_text(sig, encoding="utf-8")
            except Exception:
                pass
        return extracted

    @classmethod
    def _draw_hook_banner_on_painter(cls, painter, edits: Dict, img_w: int, img_h: int):
        """
        Draws the customizable Top/Bottom Hook Banner Overlay onto any QPainter
        at native resolution (used by both Hook Banner burn-in PNG and Thumbnail JPG capture).
        """
        from PySide6.QtCore import Qt, QRectF
        from PySide6.QtGui import QColor, QFont, QBrush, QPen, QFontMetrics

        hook_text = (edits.get("hook_text") or "").strip()
        if not hook_text:
            return

        pos = str(edits.get("hook_pos", "top") or "top").lower().strip()
        bg_hex = str(edits.get("hook_bg_color", "#D90429") or "#D90429")
        txt_hex = str(edits.get("hook_text_color", "#FFFFFF") or "#FFFFFF")
        height_pct = max(6, min(26, int(edits.get("hook_height_pct", 12) or 12)))
        base_fs = max(14, min(72, int(edits.get("hook_font_size", 28) or 28)))

        bar_h = max(36, int(round(img_h * (height_pct / 100.0))))
        bar_y = 0 if pos != "bottom" else max(0, img_h - bar_h)

        # 1. Background Banner Bar + crisp highlight divider line
        bg_col = QColor(bg_hex)
        if not bg_col.isValid():
            bg_col = QColor("#D90429")
        bg_col.setAlpha(242)
        painter.fillRect(QRectF(0, bar_y, img_w, bar_h), QBrush(bg_col))

        accent_h = max(2, int(round(bar_h * 0.05)))
        accent_y = (bar_y + bar_h - accent_h) if pos != "bottom" else bar_y
        painter.fillRect(QRectF(0, accent_y, img_w, accent_h), QBrush(QColor(255, 255, 255, 190)))

        # 2. Bold Khmer Font scaled proportionally to image resolution & auto-fitted inside bar
        custom_font = (edits.get("sub_font_family") or "").strip()
        font_family = custom_font if custom_font else "Kantumruy Pro"
        scale_ref = min(img_w, img_h) / 480.0
        px_size = max(16, int(round(base_fs * scale_ref)))
        min_px = max(12, int(round(px_size * 0.45)))

        font = QFont(font_family)
        font.setFamilies([font_family, "Kantumruy Pro", "Khmer OS Battambang", "Noto Sans Khmer", "Khmer OS", "Segoe UI"])
        font.setBold(True)

        pad_x = max(16, int(round(img_w * 0.045)))
        pad_y = max(6, int(round(bar_h * 0.12)))
        avail_w = max(80, img_w - (pad_x * 2))
        avail_h = max(20, bar_h - (pad_y * 2))

        chosen_lines = [hook_text]
        while px_size >= min_px:
            font.setPixelSize(px_size)
            fm = QFontMetrics(font)
            est_cpl = max(10, int(avail_w / max(8.0, px_size * 0.56)))
            lines = cls._wrap_khmer_ass_lines(hook_text, est_cpl)
            max_lw = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
            total_th = fm.height() * len(lines)
            if len(lines) <= 2 and max_lw <= avail_w and total_th <= avail_h:
                chosen_lines = lines
                break
            chosen_lines = lines[:2]
            px_size -= 2

        font.setPixelSize(max(min_px, px_size))
        painter.setFont(font)
        fm = QFontMetrics(font)
        line_h = fm.height()
        total_h = line_h * len(chosen_lines)
        start_y = bar_y + (bar_h - total_h) / 2.0

        txt_col = QColor(txt_hex)
        if not txt_col.isValid():
            txt_col = QColor("#FFFFFF")
        shadow_off = max(1, int(round(px_size * 0.06)))

        for i, line in enumerate(chosen_lines):
            rect_line = QRectF(pad_x, start_y + i * line_h, avail_w, line_h)
            painter.setPen(QPen(QColor(0, 0, 0, 170)))
            painter.drawText(rect_line.translated(shadow_off, shadow_off), Qt.AlignCenter, line)
            painter.setPen(QPen(txt_col))
            painter.drawText(rect_line, Qt.AlignCenter, line)

    @classmethod
    def render_hook_banner_png(cls, edits: Dict, vid_w: int, vid_h: int, out_png: str) -> str:
        """
        Renders a native-resolution transparent RGBA PNG containing the Hook Banner Overlay
        for pixel-accurate Khmer text burn-in during FFmpeg export.
        """
        edits = edits or {}
        hook_text = (edits.get("hook_text") or "").strip()
        if not hook_text:
            return ""

        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        try:
            from PySide6.QtGui import QImage, QPainter, QGuiApplication
            if QGuiApplication.instance() is None:
                return ""
            img = QImage(int(vid_w), int(vid_h), QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            painter = QPainter(img)
            try:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                cls._draw_hook_banner_on_painter(painter, edits, int(vid_w), int(vid_h))
            finally:
                painter.end()
            if img.save(out_png, "PNG"):
                return out_png
        except Exception as e:
            print(f"[Hook Banner PNG Error] {e}")
        return ""

    @classmethod
    def write_hook_banner_ass(cls, edits: Dict, vid_w: int, vid_h: int, dur_ms: int, out_ass: str) -> str:
        """Fallback pure-ASS Hook Banner renderer for headless CLI environments without QGuiApplication."""
        edits = edits or {}
        hook_text = (edits.get("hook_text") or "").strip()
        if not hook_text:
            return ""
        Path(out_ass).parent.mkdir(parents=True, exist_ok=True)
        pos = str(edits.get("hook_pos", "top") or "top").lower().strip()
        bg_ass = cls._hex_to_ass_color(edits.get("hook_bg_color", "#D90429"), alpha="10")
        txt_ass = cls._hex_to_ass_color(edits.get("hook_text_color", "#FFFFFF"), alpha="00")
        height_pct = max(6, min(26, int(edits.get("hook_height_pct", 12) or 12)))
        bar_h = max(36, int(round(vid_h * (height_pct / 100.0))))
        bar_y = 0 if pos != "bottom" else max(0, vid_h - bar_h)
        custom_font = (edits.get("sub_font_family") or "").strip() or "Khmer OS Battambang"
        fs = max(18, int(round(int(edits.get("hook_font_size", 28) or 28) * (min(vid_w, vid_h) / 480.0))))
        end_t = cls._ms_to_ass_time(max(60000, int(dur_ms or 60000) + 5000))
        safe_chars = max(14, int((vid_w * 0.90) / max(10.0, fs * 0.56)))
        wrapped = "\\N".join(cls._wrap_khmer_ass_lines(hook_text, safe_chars)[:2])
        draw_cmd = f"m 0 0 l {vid_w} 0 l {vid_w} {bar_h} l 0 {bar_h}"
        text_y = bar_y + bar_h // 2
        content = (
            "[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {vid_w}\nPlayResY: {vid_h}\nWrapStyle: 1\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: HookBar,Arial,20,{bg_ass},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n"
            f"Style: HookText,{custom_font},{fs},{txt_ass},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,2,5,24,24,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,{end_t},HookBar,,0,0,0,,{{\\an7\\pos(0,{bar_y})\\p1\\1c{bg_ass}\\bord0\\shad0}}{draw_cmd}{{\\p0}}\n"
            f"Dialogue: 1,0:00:00.00,{end_t},HookText,,0,0,0,,{{\\an5\\pos({vid_w // 2},{text_y})}}{wrapped}\n"
        )
        Path(out_ass).write_text(content, encoding="utf-8-sig")
        return out_ass

    @classmethod
    def capture_thumbnail_jpg(
        cls,
        video_path: str,
        pos_ms: int,
        out_jpg: str,
        edits: Dict = None,
    ) -> str:
        """
        Captures the exact current video frame at full native resolution, applies Aspect Ratio crop
        (if set), composites the customizable Hook Banner Overlay + Logo Watermark, and saves
        a ready-to-upload YouTube/Facebook/TikTok .jpg cover image.
        """
        if not video_path or not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        edits = edits or {}
        out_p = Path(out_jpg)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        tmp_frame = out_p.parent / f"_thumb_raw_{int(time.time() * 1000)}.png"

        sec = max(0.0, float(pos_ms or 0) / 1000.0)
        vf_parts = []
        ratio = str(edits.get("aspect_ratio", "original") or "original").split(" ")[0]
        if ratio == "9:16":
            vf_parts.append("crop=ih*9/16:ih")
        elif ratio == "1:1":
            vf_parts.append("crop=min(iw\\,ih):min(iw\\,ih)")
        elif ratio == "16:9":
            vf_parts.append("crop=iw:iw*9/16")

        lut_vf = get_lut_ffmpeg_filter(edits.get("lut_preset", "none"))
        if lut_vf:
            vf_parts.append(lut_vf)

        cmd = ["ffmpeg", "-y", "-ss", f"{sec:.3f}", "-i", video_path]
        if vf_parts:
            cmd.extend(["-vf", ",".join(vf_parts)])
        cmd.extend(["-frames:v", "1", str(tmp_frame)])

        try:
            cls.run_ffmpeg_safe(cmd, fallback_cpu=False)
            if not tmp_frame.exists():
                raise RuntimeError("មិនអាចចាប់យក Frame ពីវីដេអូបានទេ!")

            from PySide6.QtCore import Qt, QRectF
            from PySide6.QtGui import QImage, QPainter

            img = QImage(str(tmp_frame))
            if img.isNull():
                raise RuntimeError("មិនអាចផ្ទុករូបភាព Frame សម្រាប់ Thumbnail បានទេ!")
            img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            w, h = img.width(), img.height()

            painter = QPainter(img)
            try:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

                # 1. Composite Hook Banner if enabled (or non-empty text)
                if bool(edits.get("hook_enabled", 0)) and (edits.get("hook_text") or "").strip():
                    cls._draw_hook_banner_on_painter(painter, edits, w, h)

                # 2. Composite Logo Watermark at native proportions
                logo_path = edits.get("logo_path", "")
                if logo_path and Path(logo_path).exists():
                    logo_img = QImage(str(logo_path))
                    if not logo_img.isNull():
                        l_scale = max(0.03, min(0.80, float(edits.get("logo_scale", 0.15))))
                        l_opacity = max(0.05, min(1.0, float(edits.get("logo_opacity", 0.90))))
                        lx = max(0.0, min(0.95, float(edits.get("logo_x", 0.05)))) * w
                        ly = max(0.0, min(0.95, float(edits.get("logo_y", 0.05)))) * h
                        target_lw = max(24, int(round(w * l_scale)))
                        scaled_logo = logo_img.scaledToWidth(target_lw, Qt.SmoothTransformation)
                        painter.save()
                        painter.setOpacity(l_opacity)
                        painter.drawImage(int(round(lx)), int(round(ly)), scaled_logo)
                        painter.restore()
            finally:
                painter.end()

            if not img.save(str(out_p), "JPG", 95):
                raise RuntimeError(f"មិនអាចរក្សាទុកឯកសារ Thumbnail ទៅ {out_p} បានទេ!")
            return str(out_p)
        finally:
            tmp_frame.unlink(missing_ok=True)
            gc.collect()

    @classmethod
    def stitch_intro_outro(
        cls,
        main_video_path: str,
        output_mp4: str,
        intro_path: str = "",
        outro_path: str = "",
        target_w: int = 0,
        target_h: int = 0,
        quality_preset: str = "balanced",
        encoder_choice: str = "auto",
        cancel_event: Any = None,
        progress_cb: Any = None,
    ) -> str:
        """
        Auto Intro & Outro Stitcher:
        Normalizes resolution, SAR, frame rate (30 fps), and audio (44100 Hz stereo,
        auto-injecting silent audio if an Intro/Outro clip has no audio stream), then
        seamlessly concatenates [Intro] + [Dubbed Episode] + [Outro].
        """
        clips = []
        if intro_path and Path(intro_path).exists():
            clips.append(str(Path(intro_path).resolve()))
        clips.append(str(Path(main_video_path).resolve()))
        if outro_path and Path(outro_path).exists():
            clips.append(str(Path(outro_path).resolve()))

        if len(clips) <= 1:
            if str(Path(main_video_path).resolve()) != str(Path(output_mp4).resolve()):
                import shutil
                shutil.copy2(main_video_path, output_mp4)
            return output_mp4

        if target_w <= 0 or target_h <= 0:
            target_w, target_h = cls._probe_resolution(main_video_path)
        vw = max(160, (int(target_w) // 2) * 2)
        vh = max(160, (int(target_h) // 2) * 2)

        inputs = []
        vf_parts = []
        concat_in = []
        for i, vp in enumerate(clips):
            inputs.extend(["-i", vp])
            vf_parts.append(
                f"[{i}:v]scale={vw}:{vh}:force_original_aspect_ratio=decrease,"
                f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[sv{i}];"
            )
            if cls._has_audio_stream(vp):
                vf_parts.append(
                    f"[{i}:a]aresample=44100:async=1,aformat=sample_fmts=fltp:channel_layouts=stereo[sa{i}];"
                )
            else:
                dur_sec = max(0.2, cls.get_duration_ms(vp) / 1000.0)
                vf_parts.append(f"anullsrc=r=44100:cl=stereo:d={dur_sec:.3f}[sa{i}];")
            concat_in.append(f"[sv{i}][sa{i}]")

        vf_parts.append(f"{''.join(concat_in)}concat=n={len(clips)}:v=1:a=1[vcat][acat]")

        hw = get_hardware_profile()
        opt_flags = cls.detect_video_encoder()
        detected_codec = opt_flags[1] if len(opt_flags) > 1 else "libx264"
        if encoder_choice == "cpu" or detected_codec == "libx264":
            enc_flags = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", str(hw["ffmpeg_threads"])]
        else:
            enc_flags = list(opt_flags)

        cmd = [
            "ffmpeg", "-y", "-threads", str(hw["ffmpeg_threads"]),
            *inputs,
            "-filter_complex", "".join(vf_parts),
            "-map", "[vcat]", *enc_flags, "-pix_fmt", "yuv420p",
            "-map", "[acat]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-max_muxing_queue_size", "1024",
            "-movflags", "+faststart",
            output_mp4,
        ]
        if progress_cb:
            progress_cb(88, "🎬 កំពុងភ្ជាប់ Intro + វីដេអូ + Outro ដោយស្វ័យប្រវត្តិ...")
        cls.run_ffmpeg_safe(
            cmd,
            fallback_cpu=True,
            quality_preset=quality_preset,
            cancel_event=cancel_event,
            progress_cb=progress_cb,
        )
        return output_mp4

    @classmethod
    def build_preview_audio(
        cls,
        video_path: str,
        segments: List[Dict],
        out_wav: str,
        bgm_volume: float = 0.0,
        voice_gain: float = 2.2,
    ) -> str:
        """
        បង្កើត Track សំឡេងខ្មែរសុទ្ធ (KH Voice Only) សម្រាប់ Video Preview
        ដើម្បីឲ្យ Original Audio Slider អាចបិទ/បើកសំឡេងដើមភ្លាមៗ 0% - 100% ដោយមិនបាច់ Render ឡើងវិញ!
        """
        valid = [s for s in segments if s.get("tts_audio_path") and Path(s["tts_audio_path"]).exists()]
        if not valid:
            return ""

        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        inputs = []
        filter_parts = []
        mix_labels = []

        for i, seg in enumerate(valid):
            inputs.extend(["-i", seg["tts_audio_path"]])
            delay = max(0, int(seg["start_ms"]))
            seg_end = max(delay + 200, int(seg.get("end_ms", delay + 1000)))

            # Lock atrim strictly inside [start_ms, end_ms] AND never overlapping the next speaker (Zero-Drift Sync)
            slot_end = seg_end
            if i + 1 < len(valid):
                next_start = max(delay + 150, int(valid[i + 1]["start_ms"]) - 15)
                slot_end = min(slot_end, next_start)
            max_dur_sec = max(0.15, (slot_end - delay) / 1000.0)
            trim_slot = f"atrim=0:{max_dur_sec:.4f},"

            lbl = f"[d{i}]"
            filter_parts.append(
                f"[{i}:a]aresample=44100:async=1,{trim_slot}volume={voice_gain:.2f},"
                f"adelay={delay}|{delay}:all=1{lbl}"
            )
            mix_labels.append(lbl)

        filter_parts.append(
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=0:normalize=0,"
            f"alimiter=limit=0.95[aout]"
        )

        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[aout]",
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            out_wav
        ]
        cls.run_ffmpeg_safe(cmd, fallback_cpu=False)
        return out_wav

    @classmethod
    def _mix_audio_in_chunks(
        cls,
        video_path: str,
        valid_segments: List[Dict],
        out_mixed_wav: str,
        bgm_volume: float = 0.20,
        voice_gain: float = 2.2,
        custom_bgm_path: str = "",
        custom_bgm_vol: float = 0.18,
        chunk_size: int = 100,
        auto_ducking: bool = True,
        sfx_events: List[Dict] = None,
        edits: Dict = None,
    ) -> str:
        """
        លាយសំឡេងខ្មែរម្តង 50 ជួរ (Chunked Mixing) ដើម្បីការពារកុំឲ្យអស់ RAM ឬគាំង FFmpeg
        នៅពេលមាន 300 - 1,000 ប្រយោគ (ពី 50 វីដេអូតភ្ជាប់គ្នា) ព្រមទាំងអនុវត្ត Auto-Ducking BGM និង SFX។
        """
        edits = dict(edits or {})
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        if keep_bgm_only:
            # Vocal Remover mode: strip Chinese speech via extract_clean_bgm while keeping soundtrack alive
            if bgm_volume <= 0.001:
                orig_v = float(edits.get("orig_volume") or 0.0)
                bgm_volume = orig_v if orig_v > 0.01 else 0.35
            edits["mute_original_audio"] = 0
        else:
            if edits.get("orig_volume") is not None and bgm_volume <= 0.001:
                bgm_volume = float(edits["orig_volume"])
            if bool(edits.get("mute_original_audio", 0)) or bool(edits.get("dubbed_no_orig_audio", 0)) or bgm_volume <= 0.001:
                bgm_volume = 0.0
                edits["orig_volume"] = 0.0
                edits["mute_original_audio"] = 1
        if edits.get("dub_volume") is not None:
            voice_gain = float(edits["dub_volume"]) * 1.9

        ducking_db = int(edits.get("ducking_db", -18))
        ducking_smoothness = edits.get("ducking_smoothness", "smooth")
        voice_fx = edits.get("voice_fx", "clean")

        if ducking_smoothness == "fast":
            atk, rel = 20, 100
        elif ducking_smoothness == "cinema":
            atk, rel = 80, 500
        else:
            atk, rel = 40, 250

        comp_ratio = max(3, min(16, int(abs(ducking_db) / 2.2)))

        work_dir = Path(out_mixed_wav).parent
        work_dir.mkdir(parents=True, exist_ok=True)
        chunk_wavs = []

        # Auto-adapt chunk size for Low-Spec PCs to keep RAM minimal
        hw = get_hardware_profile()
        eff_chunk = min(int(chunk_size), int(hw["audio_chunk_size"]))

        # ១. លាយសំឡេងខ្មែរជាកញ្ចប់តូចៗ (ប្រើ RAM តិចបំផុត និងមិនលើស Windows CLI limit)
        for c_idx in range(0, len(valid_segments), eff_chunk):
            batch = valid_segments[c_idx : c_idx + eff_chunk]
            c_out = str(work_dir / f"_chunk_voice_{c_idx}.wav")

            inputs = []
            filters = []
            labels = []

            for i, seg in enumerate(batch):
                inputs.extend(["-i", seg["tts_audio_path"]])
                delay = max(0, int(seg["start_ms"]))
                seg_end = max(delay + 200, int(seg.get("end_ms", delay + 1000)))

                # Lock atrim strictly inside [start_ms, end_ms] AND before next_start (Zero-Drift Lip-Sync)
                global_i = c_idx + i
                slot_end = seg_end
                if global_i + 1 < len(valid_segments):
                    next_start = max(delay + 150, int(valid_segments[global_i + 1]["start_ms"]) - 15)
                    slot_end = min(slot_end, next_start)
                max_sec = max(0.15, (slot_end - delay) / 1000.0)
                trim_f = f"atrim=0:{max_sec:.4f},"

                lbl = f"[v{i}]"
                filters.append(
                    f"[{i}:a]aresample=44100:async=1,{trim_f}volume={voice_gain:.2f},"
                    f"adelay={delay}|{delay}:all=1{lbl}"
                )
                labels.append(lbl)

            filters.append(
                f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[cout]"
            )
            cls.run_ffmpeg_safe(
                [
                    "ffmpeg", "-y", "-threads", str(min(2, hw["ffmpeg_threads"])), *inputs,
                    "-filter_complex", ";".join(filters),
                    "-map", "[cout]", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                    c_out
                ],
                fallback_cpu=False,
            )
            chunk_wavs.append(c_out)

        # ១b. លាយសំឡេង Effect (🔔 SFX Pad & Auto Emotion SFX) តាមវិនាទីដែលបានដាក់ ជាមួយកម្រិតសំឡេងថ្នមមិនគ្របសំឡេងខ្មែរ
        valid_sfx = [
            s for s in (sfx_events or [])
            if (s.get("audio_path") or s.get("tts_audio_path"))
            and Path(s.get("audio_path") or s.get("tts_audio_path")).exists()
        ]
        sfx_chunk_wavs = []
        for s_idx in range(0, len(valid_sfx), eff_chunk):
            s_batch = valid_sfx[s_idx : s_idx + eff_chunk]
            s_out = str(work_dir / f"_chunk_sfx_{s_idx}.wav")
            s_inputs, s_filters, s_labels = [], [], []
            for i, sfx in enumerate(s_batch):
                ap = sfx.get("audio_path") or sfx.get("tts_audio_path")
                s_inputs.extend(["-i", ap])
                delay = max(0, int(sfx.get("start_ms", 0)))
                raw_vol = float(sfx.get("volume", 0.55))
                is_auto_sfx = str(sfx.get("name") or "").startswith("[Auto]")
                vol = min(0.65, raw_vol) if is_auto_sfx else min(1.15, raw_vol * 1.1)
                lbl = f"[s{i}]"
                s_filters.append(
                    f"[{i}:a]aresample=44100:async=1,volume={vol:.2f},adelay={delay}|{delay}:all=1{lbl}"
                )
                s_labels.append(lbl)
            s_filters.append(
                f"{''.join(s_labels)}amix=inputs={len(s_labels)}:duration=longest:dropout_transition=0:normalize=0[sout]"
            )
            cls.run_ffmpeg_safe(
                [
                    "ffmpeg", "-y", "-threads", str(min(2, hw["ffmpeg_threads"])), *s_inputs,
                    "-filter_complex", ";".join(s_filters),
                    "-map", "[sout]", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                    s_out
                ],
                fallback_cpu=False,
            )
            sfx_chunk_wavs.append(s_out)
            chunk_wavs.append(s_out)

        # ២. បូកបញ្ចូលកញ្ចប់សំឡេងខ្មែរទាំងអស់ទៅជា Track សំឡេងនិយាយរួម [voice_raw]
        vid_dur_sec = max(1.0, cls.get_duration_ms(video_path) / 1000.0)
        is_orig_muted = (not keep_bgm_only) and (
            bool(edits.get("mute_original_audio", 0))
            or bool(edits.get("dubbed_no_orig_audio", 0))
            or (bgm_volume <= 0.001)
        )
        has_orig_bgm = (not is_orig_muted) and bool(video_path and Path(video_path).exists() and cls._has_audio_stream(video_path))
        has_custom_bgm = bool(custom_bgm_path and Path(custom_bgm_path).exists() and custom_bgm_vol > 0.001)

        final_inputs = []
        final_filters = []
        bgm_labels = []
        voice_labels = []
        idx = 0

        if has_orig_bgm:
            bgm_source_path = video_path
            if keep_bgm_only:
                extracted_bgm = cls._get_or_extract_clean_bgm(video_path, work_dir)
                if extracted_bgm and Path(extracted_bgm).exists():
                    bgm_source_path = extracted_bgm
            final_inputs.extend(["-i", bgm_source_path])
            final_filters.append(f"[{idx}:a]aresample=44100:async=1,volume={bgm_volume:.2f}[obgm]")
            bgm_labels.append("[obgm]")
            idx += 1

        if has_custom_bgm:
            # ប្រើ -stream_loop -1 ដើម្បីចាក់ភ្លេង BGM វិលជុំរហូតដល់ចប់វីដេអូ (ទោះ 5 ម៉ោងក៏ដោយ!)
            final_inputs.extend(["-stream_loop", "-1", "-i", custom_bgm_path])
            fade_st = max(0.5, vid_dur_sec - 2.0)
            final_filters.append(
                f"[{idx}:a]aresample=44100:async=1,atrim=0:{vid_dur_sec:.3f},"
                f"volume={custom_bgm_vol:.2f},afade=t=out:st={fade_st:.2f}:d=2.0[cbgm]"
            )
            bgm_labels.append("[cbgm]")
            idx += 1

        for cw in chunk_wavs:
            final_inputs.extend(["-i", cw])
            if cw in sfx_chunk_wavs:
                # Feed Auto/Manual SFX into BGM bed so sidechaincompress Auto-Ducking keeps Khmer speech dominant!
                bgm_labels.append(f"[{idx}:a]")
            else:
                voice_labels.append(f"[{idx}:a]")
            idx += 1

        # បង្កើត Track សំឡេងនិយាយខ្មែរសុទ្ធ
        v_fx_filter = ""
        if voice_fx == "inner_thought":
            v_fx_filter = ",aecho=0.8:0.88:35|55:0.35|0.25"
        elif voice_fx == "phone":
            v_fx_filter = ",highpass=f=300,lowpass=f=3400,volume=1.2"
        elif voice_fx == "hall":
            v_fx_filter = ",aecho=0.8:0.9:60:0.45"

        if len(voice_labels) == 0:
            final_filters.append(f"aevalsrc=0:d={vid_dur_sec:.3f}[voice_raw]")
        elif len(voice_labels) == 1:
            final_filters.append(f"{voice_labels[0]}apad=whole_dur={vid_dur_sec:.3f}{v_fx_filter}[voice_raw]")
        else:
            final_filters.append(
                f"{''.join(voice_labels)}amix=inputs={len(voice_labels)}:duration=longest:dropout_transition=0:normalize=0,"
                f"apad=whole_dur={vid_dur_sec:.3f}{v_fx_filter}[voice_raw]"
            )

        # ៣. អនុវត្ត Auto-Ducking (បន្ថយភ្លេង BGM ស្វ័យប្រវត្តិពេលមានសំឡេងនិយាយខ្មែរ!)
        if bgm_labels:
            if len(bgm_labels) == 1:
                final_filters.append(f"{bgm_labels[0]}anull[bgm_combined]")
            else:
                final_filters.append(
                    f"{''.join(bgm_labels)}amix=inputs={len(bgm_labels)}:duration=longest:dropout_transition=0:normalize=0[bgm_combined]"
                )

            if auto_ducking:
                final_filters.append("[voice_raw]asplit=2[v_out][v_sc]")
                final_filters.append(
                    f"[bgm_combined][v_sc]sidechaincompress=threshold=0.015:ratio={comp_ratio}:attack={atk}:release={rel}[bgm_ducked]"
                )
                final_filters.append(
                    "[bgm_ducked][v_out]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                    "dynaudnorm=f=150:g=15,alimiter=limit=0.95[aout]"
                )
            else:
                final_filters.append(
                    "[bgm_combined][voice_raw]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                    "dynaudnorm=f=150:g=15,alimiter=limit=0.95[aout]"
                )
        else:
            final_filters.append("[voice_raw]dynaudnorm=f=150:g=15,alimiter=limit=0.95[aout]")

        if edits.get("anti_copyright_enabled", 0):
            ac_level = str(edits.get("anti_copyright_level", "medium")).lower()
            if ac_level == "light":
                r_mult, t_rate, eq_b, eq_t, n_amp = 1.008, 0.992, 0.8, 0.6, 0.0008
            elif ac_level == "strong":
                r_mult, t_rate, eq_b, eq_t, n_amp = 1.022, 0.978, 1.8, 1.5, 0.0016
            else:
                r_mult, t_rate, eq_b, eq_t, n_amp = 1.015, 0.985, 1.4, 1.1, 0.0012

            final_filters.append(
                f"[aout]asetrate=44100*{r_mult:.4f},aresample=44100,atempo={t_rate:.4f},"
                f"equalizer=f=250:t=q:w=1:g={eq_b:.1f},equalizer=f=3200:t=q:w=1:g={eq_t:.1f}[a_ac_base];"
                f"anoisesrc=d={vid_dur_sec:.2f}:c=pink:r=44100:a={n_amp:.5f}[a_ac_noise];"
                f"[a_ac_base][a_ac_noise]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.04[a_ac_out]"
            )
            a_out_map = "[a_ac_out]"
        else:
            a_out_map = "[aout]"

        ff_audio_threads = str(min(2, hw["ffmpeg_threads"]))
        try:
            cls.run_ffmpeg_safe(
                [
                    "ffmpeg", "-y", "-threads", ff_audio_threads, *final_inputs,
                    "-filter_complex", ";".join(final_filters),
                    "-map", a_out_map, "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                    out_mixed_wav
                ],
                fallback_cpu=False,
            )
        finally:
            # សម្អាតឯកសារបណ្តោះអាសន្នភ្លាមៗ
            for cw in chunk_wavs:
                Path(cw).unlink(missing_ok=True)
            gc.collect()

        return out_mixed_wav

    @classmethod
    def build_fast_preview_video(
        cls,
        video_path: str,
        segments: List[Dict],
        out_preview_mp4: str,
        bgm_volume: float = 0.20,
        voice_gain: float = 2.2,
        edits: Dict = None,
        sfx_events: List[Dict] = None,
    ) -> str:
        """
        បញ្ចូលសំឡេងខ្មែរ និង SFX ទៅក្នុងវីដេអូ Preview ដោយប្រើ Chunked Audio Mixing + '-c:v copy' (~0.5s, 0% CPU)
        ដើម្បីឲ្យ Player ចាក់រូបភាព និងសំឡេងព្រមគ្នាបានរលូន 100% ទោះមាន 50 វីដេអូ (500+ ជួរ) ក៏ដោយ!
        """
        edits = dict(edits or {})
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        if keep_bgm_only:
            edits["mute_original_audio"] = 0
            if bgm_volume <= 0.001:
                bgm_volume = 0.35
        elif bool(edits.get("mute_original_audio", 0)) or bool(edits.get("dubbed_no_orig_audio", 0)) or bgm_volume <= 0.001:
            bgm_volume = 0.0
            edits["orig_volume"] = 0.0
            edits["mute_original_audio"] = 1
        if "anti_copyright_enabled" not in edits:
            edits["anti_copyright_enabled"] = 1
        if "auto_blur_chinese" not in edits:
            edits["auto_blur_chinese"] = 1
        valid = [s for s in segments if s.get("tts_audio_path") and Path(s["tts_audio_path"]).exists()]
        valid_sfx = [
            s for s in (sfx_events or [])
            if (s.get("audio_path") or s.get("tts_audio_path"))
            and Path(s.get("audio_path") or s.get("tts_audio_path")).exists()
        ]
        if (not valid and not valid_sfx and not keep_bgm_only) or not video_path or not Path(video_path).exists():
            return ""

        out_p = Path(out_preview_mp4)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        mixed_wav = str(out_p.parent / "_preview_mixed_track.wav")

        cls._mix_audio_in_chunks(
            video_path=video_path,
            valid_segments=valid,
            out_mixed_wav=mixed_wav,
            bgm_volume=bgm_volume,
            voice_gain=voice_gain,
            custom_bgm_path=edits.get("custom_bgm_path", ""),
            custom_bgm_vol=float(edits.get("custom_bgm_vol", 0.18)),
            chunk_size=50,
            auto_ducking=bool(edits.get("auto_ducking", 1)),
            sfx_events=valid_sfx,
            edits=edits,
        )

        hw = get_hardware_profile()
        ff_threads = str(min(2, hw["ffmpeg_threads"]))
        cmd = [
            "ffmpeg", "-y", "-threads", ff_threads,
            "-i", video_path,
            "-i", mixed_wav,
            "-map", "0:v", "-c:v", "copy",
            "-map", "1:a", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
            "-max_muxing_queue_size", "1024",
            "-shortest",
            "-movflags", "+faststart",
            out_preview_mp4
        ]
        try:
            cls.run_ffmpeg_safe(cmd, fallback_cpu=False)
        finally:
            Path(mixed_wav).unlink(missing_ok=True)
            gc.collect()
        return out_preview_mp4

    @classmethod
    def apply_anti_copyright(
        cls,
        video_path: str,
        output_mp4: str,
        level: str = "medium",
        mirror_flip: bool = False,
        add_frame_border: bool = False,
        auto_blur_chinese: bool = True,
        auto_timed_blur: bool = True,
        lut_preset: str = "none",
        segments: List[Dict] = None,
        cancel_event: Any = None,
        progress_cb: Any = None,
    ) -> str:
        """
        AI Anti-Copyright Transformation Engine (🛡️ កាត់ផ្តាច់ Copyright & Perceptual Hash):
        Transforms both visual pixel matrix and audio waveform hash while keeping
        the video natural, smooth, and watchable. Supports 20+ LUT presets and
        Timed Dynamic Auto-Blur (0% blur direct pass-through when text is off-screen).
        """
        if not video_path or not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        level = str(level or "medium").lower().strip()
        out_p = Path(output_mp4)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if progress_cb:
            progress_cb(10, f"🛡️ កំពុងរៀបចំ AI Anti-Copyright ({level.upper()})...")

        dur_ms = cls.get_duration_ms(video_path)
        dur_sec = max(1.0, dur_ms / 1000.0)
        raw_vw, raw_vh = cls._probe_resolution(video_path)
        vw = max(2, int(raw_vw) - (int(raw_vw) % 2))
        vh = max(2, int(raw_vh) - (int(raw_vh) % 2))

        # 1. Video Filters
        v_filters = []

        # Apply optional 20+ LUT/Adjustment preset
        lut_vf = get_lut_ffmpeg_filter(lut_preset)
        if lut_vf:
            v_filters.append(lut_vf)

        if mirror_flip or level == "strong":
            v_filters.append("hflip")

        if level == "light":
            v_filters.append(
                "scale=trunc(iw*1.04/2)*2:trunc(ih*1.04/2)*2,"
                "crop=trunc(iw/1.04/2)*2:trunc(ih/1.04/2)*2:"
                "clip((iw-ow)/2+sin(t*0.5)*4\\,0\\,iw-ow):clip((ih-oh)/2+cos(t*0.4)*3\\,0\\,ih-oh)"
            )
            v_filters.append("eq=contrast=1.02:brightness=0.01:saturation=1.03:gamma=1.01")
            v_filters.append("colorbalance=rs=0.01:bs=-0.01")
            v_filters.append("noise=alls=1:allf=t+u")
        elif level == "strong":
            v_filters.append(
                "scale=trunc(iw*1.09/2)*2:trunc(ih*1.09/2)*2,"
                "crop=trunc(iw/1.09/2)*2:trunc(ih/1.09/2)*2:"
                "clip((iw-ow)/2+sin(t*0.8)*8\\,0\\,iw-ow):clip((ih-oh)/2+cos(t*0.6)*6\\,0\\,ih-oh)"
            )
            v_filters.append("eq=contrast=1.06:brightness=0.02:saturation=1.08:gamma=1.04")
            v_filters.append("colorbalance=rs=0.03:gs=0.01:bs=-0.03")
            v_filters.append("noise=alls=3:allf=t+u")
            v_filters.append("fps=29.97")
        else:
            v_filters.append(
                "scale=trunc(iw*1.07/2)*2:trunc(ih*1.07/2)*2,"
                "crop=trunc(iw/1.07/2)*2:trunc(ih/1.07/2)*2:"
                "clip((iw-ow)/2+sin(t*0.7)*6\\,0\\,iw-ow):clip((ih-oh)/2+cos(t*0.5)*5\\,0\\,ih-oh)"
            )
            v_filters.append("eq=contrast=1.04:brightness=0.015:saturation=1.06:gamma=1.02")
            v_filters.append("colorbalance=rs=0.02:bs=-0.02")
            v_filters.append("noise=alls=2:allf=t+u")
            v_filters.append("fps=29.97")

        # Always guarantee exact even resolution & yuv420p for libx264 / hardware encoders / maskedmerge
        v_filters.append(f"scale={vw}:{vh}:flags=bicubic,format=yuv420p")

        has_audio = cls._has_audio_stream(video_path)

        # 2. Audio Filters
        a_filters = []
        if has_audio:
            if level == "light":
                r_mult, t_rate, eq_b, eq_t, n_amp = 1.008, 0.992, 0.8, 0.6, 0.0008
            elif level == "strong":
                r_mult, t_rate, eq_b, eq_t, n_amp = 1.022, 0.978, 1.8, 1.5, 0.0016
            else:
                r_mult, t_rate, eq_b, eq_t, n_amp = 1.015, 0.985, 1.4, 1.1, 0.0012

            a_filters.append(
                f"asetrate=44100*{r_mult:.4f},aresample=44100,atempo={t_rate:.4f},"
                f"equalizer=f=250:t=q:w=1:g={eq_b:.1f},equalizer=f=3200:t=q:w=1:g={eq_t:.1f}"
            )

        filter_parts = []
        inputs = ["-i", video_path]
        mask_ass = ""

        current_v = "[v_base]"
        if add_frame_border:
            v_chain = ",".join(v_filters) if v_filters else f"scale={vw}:{vh},format=yuv420p"
            bg_w = max(2, (vw // 4) - ((vw // 4) % 2))
            bg_h = max(2, (vh // 4) - ((vh // 4) % 2))
            in_w = max(2, int(vw * 0.94) - (int(vw * 0.94) % 2))
            in_h = max(2, int(vh * 0.94) - (int(vh * 0.94) % 2))
            filter_parts.append(
                f"[0:v]{v_chain}[v_trans];"
                f"[v_trans]split[v_bg][v_fg];"
                f"[v_bg]scale={bg_w}:{bg_h},boxblur=8:1,scale={vw}:{vh}[v_blur_bg];"
                f"[v_fg]scale={in_w}:{in_h}[v_inner];"
                f"[v_blur_bg][v_inner]overlay=(W-w)/2:(H-h)/2,format=yuv420p{current_v}"
            )
        else:
            v_chain = ",".join(v_filters) if v_filters else f"scale={vw}:{vh},format=yuv420p"
            filter_parts.append(f"[0:v]{v_chain}{current_v}")

        if auto_blur_chinese:
            smart_blur_masks = [
                {"id": 91, "name": "Auto Bottom Subtitles", "enabled": 1, "mode": "blur", "x": 0.03, "y": 0.74, "w": 0.94, "h": 0.20},
                {"id": 92, "name": "Auto Left Character Name", "enabled": 1, "mode": "blur", "x": 0.02, "y": 0.20, "w": 0.18, "h": 0.45},
                {"id": 93, "name": "Auto Right Character Name", "enabled": 1, "mode": "blur", "x": 0.80, "y": 0.20, "w": 0.18, "h": 0.45},
                {"id": 94, "name": "Auto Top Title Card", "enabled": 1, "mode": "blur", "x": 0.02, "y": 0.02, "w": 0.38, "h": 0.12},
            ]
            mask_ass = str(out_p.parent / f"_ac_dyn_mask_{int(time.time()*1000)}.ass")
            has_dyn = bool(
                auto_timed_blur
                and segments
                and cls.write_dynamic_blur_mask_ass(segments, smart_blur_masks, vw, vh, mask_ass)
            )

            if has_dyn:
                safe_ass = mask_ass.replace("\\", "/").replace(":", "\\:")
                filter_parts.append(
                    f"{current_v}split=3[vac_clean][vac_to_blur][vac_for_mask];"
                    f"[vac_to_blur]boxblur=12:2[vac_blurred];"
                    f"[vac_for_mask]drawbox=color=black:t=fill,ass='{safe_ass}'[vac_mtimed];"
                    f"[vac_clean][vac_blurred][vac_mtimed]maskedmerge[vout]"
                )
            else:
                filter_parts.append(
                    f"{current_v}split[vm_m0][vm_c0];"
                    f"[vm_c0]crop=w=trunc(iw*0.94/2)*2:h=trunc(ih*0.20/2)*2:x=trunc(iw*0.03/2)*2:y=trunc(ih*0.74/2)*2,boxblur=12:2[vm_b0];"
                    f"[vm_m0][vm_b0]overlay=x=trunc(main_w*0.03/2)*2:y=trunc(main_h*0.74/2)*2[vm_m1];"
                    f"[vm_m1]split[vm_m1_m][vm_c1];"
                    f"[vm_c1]crop=w=trunc(iw*0.18/2)*2:h=trunc(ih*0.45/2)*2:x=trunc(iw*0.02/2)*2:y=trunc(ih*0.20/2)*2,boxblur=12:2[vm_b1];"
                    f"[vm_m1_m][vm_b1]overlay=x=trunc(main_w*0.02/2)*2:y=trunc(main_h*0.20/2)*2[vm_m2];"
                    f"[vm_m2]split[vm_m2_m][vm_c2];"
                    f"[vm_c2]crop=w=trunc(iw*0.18/2)*2:h=trunc(ih*0.45/2)*2:x=trunc(iw*0.80/2)*2:y=trunc(ih*0.20/2)*2,boxblur=12:2[vm_b2];"
                    f"[vm_m2_m][vm_b2]overlay=x=trunc(main_w*0.80/2)*2:y=trunc(main_h*0.20/2)*2[vm_m3];"
                    f"[vm_m3]split[vm_m3_m][vm_c3];"
                    f"[vm_c3]crop=w=trunc(iw*0.38/2)*2:h=trunc(ih*0.12/2)*2:x=trunc(iw*0.02/2)*2:y=trunc(ih*0.02/2)*2,boxblur=12:2[vm_b3];"
                    f"[vm_m3_m][vm_b3]overlay=x=trunc(main_w*0.02/2)*2:y=trunc(main_h*0.02/2)*2[vout]"
                )
        else:
            filter_parts.append(f"{current_v}null[vout]")

        if has_audio:
            a_chain = ",".join(a_filters)
            filter_parts.append(
                f"[0:a]{a_chain}[abase];"
                f"anoisesrc=d={dur_sec:.2f}:c=pink:r=44100:a={n_amp:.5f}[anoise];"
                f"[abase][anoise]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.04[aout]"
            )
            a_map = ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
        else:
            a_map = []

        opt_flags = cls.detect_video_encoder()
        hw = get_hardware_profile()

        cmd = [
            "ffmpeg", "-y", "-threads", str(hw["ffmpeg_threads"]),
            *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[vout]", *opt_flags, "-pix_fmt", "yuv420p",
            *a_map,
            "-max_muxing_queue_size", "1024",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-fflags", "+bitexact",
            "-movflags", "+faststart",
            output_mp4
        ]

        if progress_cb:
            progress_cb(40, f"🛡️ កំពុងដំណើរការកាត់ផ្តាច់ Copyright ({level.upper()})...")

        try:
            cls.run_ffmpeg_safe(
                cmd,
                fallback_cpu=True,
                quality_preset="ultrafast",
                cancel_event=cancel_event,
                progress_cb=progress_cb,
            )
        finally:
            if mask_ass:
                Path(mask_ass).unlink(missing_ok=True)
            gc.collect()

        if progress_cb:
            progress_cb(100, f"🛡️ កាត់ផ្តាច់ Copyright បានជោគជ័យ: {Path(output_mp4).name}")

        return output_mp4

    @classmethod
    def render_final_video(
        cls,
        video_path: str,
        segments: List[Dict],
        output_mp4: str,
        bgm_volume: float = 0.25,
        edits: Dict = None,
        ass_sub_path: str = "",
        voice_gain: float = 2.2,
        sfx_events: List[Dict] = None,
        resolution: str = "original",
        quality_preset: str = "balanced",
        fps: str = "original",
        encoder_choice: str = "auto",
        cancel_event: Any = None,
        progress_cb: Any = None,
    ):
        edits = dict(edits or {})
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        if keep_bgm_only:
            edits["mute_original_audio"] = 0
            if bgm_volume <= 0.001:
                bgm_volume = float(edits.get("orig_volume") or 0.35)
                if bgm_volume <= 0.01:
                    bgm_volume = 0.35
        elif bool(edits.get("mute_original_audio", 0)) or bool(edits.get("dubbed_no_orig_audio", 0)) or bgm_volume <= 0.001:
            bgm_volume = 0.0
            edits["orig_volume"] = 0.0
            edits["mute_original_audio"] = 1
        if "anti_copyright_enabled" not in edits:
            edits["anti_copyright_enabled"] = 1
        if "auto_blur_chinese" not in edits:
            edits["auto_blur_chinese"] = 1
        valid = [s for s in segments if s.get("tts_audio_path") and Path(s["tts_audio_path"]).exists()]

        if progress_cb:
            progress_cb(15, "កំពុងលាយសំឡេងខ្មែរ និង BGM...")

        # 1. Pre-mix all Khmer voice clips + BGM + SFX in 50-line chunks so RAM stays < 100MB even for 50 merged videos
        work_dir = Path(valid[0]["tts_audio_path"]).parent if valid else (Path(output_mp4).parent / "_tmp_work")
        work_dir.mkdir(parents=True, exist_ok=True)
        mixed_wav = str(work_dir / "_final_mixed_track.wav")
        cls._mix_audio_in_chunks(
            video_path=video_path,
            valid_segments=valid,
            out_mixed_wav=mixed_wav,
            bgm_volume=bgm_volume,
            voice_gain=voice_gain,
            custom_bgm_path=edits.get("custom_bgm_path", ""),
            custom_bgm_vol=float(edits.get("custom_bgm_vol", 0.18)),
            chunk_size=50,
            auto_ducking=bool(edits.get("auto_ducking", 1)),
            sfx_events=sfx_events,
            edits=edits,
        )

        if progress_cb:
            progress_cb(40, "កំពុងរៀបចំ Video Filter និងកំណត់កម្រិតច្បាស់ (Resolution)...")

        inputs = ["-i", video_path, "-i", mixed_wav]
        filter_parts = []
        next_input_idx = 2

        # 2. Probe Resolution and Calculate Target Dimensions
        vw, vh = cls._probe_resolution(video_path)
        ratio = edits.get("aspect_ratio", "original")

        v_filters = []
        bright = float(edits.get("brightness", 0.0))
        contrast = float(edits.get("contrast", 1.0))
        sat = float(edits.get("saturation", 1.0))
        if bright != 0.0 or contrast != 1.0 or sat != 1.0:
            v_filters.append(f"eq=brightness={bright:.2f}:contrast={contrast:.2f}:saturation={sat:.2f}")

        # 20+ Cinematic Adjustments & LUT Presets
        lut_vf = get_lut_ffmpeg_filter(edits.get("lut_preset", "none"))
        if lut_vf:
            v_filters.append(lut_vf)

        # AI Anti-Copyright Video Transformations
        ac_enabled = bool(edits.get("anti_copyright_enabled", 1))
        ac_level = str(edits.get("anti_copyright_level", "medium")).lower().strip()
        ac_flip = bool(edits.get("anti_copyright_flip", 0) or ac_level == "strong")
        ac_border = bool(edits.get("anti_copyright_border", 0))

        if ac_enabled:
            if ac_flip:
                v_filters.append("hflip")
            if ac_level == "light":
                v_filters.append(
                    "scale=trunc(iw*1.04/2)*2:trunc(ih*1.04/2)*2,"
                    "crop=trunc(iw/1.04/2)*2:trunc(ih/1.04/2)*2:"
                    "clip((iw-ow)/2+sin(t*0.5)*4\\,0\\,iw-ow):clip((ih-oh)/2+cos(t*0.4)*3\\,0\\,ih-oh)"
                )
                v_filters.append("eq=contrast=1.02:brightness=0.01:saturation=1.03:gamma=1.01")
                v_filters.append("colorbalance=rs=0.01:bs=-0.01")
                v_filters.append("noise=alls=1:allf=t+u")
            elif ac_level == "strong":
                v_filters.append(
                    "scale=trunc(iw*1.09/2)*2:trunc(ih*1.09/2)*2,"
                    "crop=trunc(iw/1.09/2)*2:trunc(ih/1.09/2)*2:"
                    "clip((iw-ow)/2+sin(t*0.8)*8\\,0\\,iw-ow):clip((ih-oh)/2+cos(t*0.6)*6\\,0\\,ih-oh)"
                )
                v_filters.append("eq=contrast=1.06:brightness=0.02:saturation=1.08:gamma=1.04")
                v_filters.append("colorbalance=rs=0.03:gs=0.01:bs=-0.03")
                v_filters.append("noise=alls=3:allf=t+u")
                v_filters.append("fps=29.97")
            else:
                v_filters.append(
                    "scale=trunc(iw*1.07/2)*2:trunc(ih*1.07/2)*2,"
                    "crop=trunc(iw/1.07/2)*2:trunc(ih/1.07/2)*2:"
                    "clip((iw-ow)/2+sin(t*0.7)*6\\,0\\,iw-ow):clip((ih-oh)/2+cos(t*0.5)*5\\,0\\,ih-oh)"
                )
                v_filters.append("eq=contrast=1.04:brightness=0.015:saturation=1.06:gamma=1.02")
                v_filters.append("colorbalance=rs=0.02:bs=-0.02")
                v_filters.append("noise=alls=2:allf=t+u")
                v_filters.append("fps=29.97")

        if ratio == "9:16":
            v_filters.append("crop=min(iw\\,ih*9/16):ih:(iw-min(iw\\,ih*9/16))/2:0")
            crop_w = min(vw, int(vh * 9 / 16))
            crop_h = vh
        elif ratio == "1:1":
            v_filters.append("crop=min(iw\\,ih):min(iw\\,ih)")
            crop_w = crop_h = min(vw, vh)
        elif ratio == "16:9":
            v_filters.append("crop=iw:min(ih\\,iw*9/16):0:(ih-min(ih\\,iw*9/16))/2")
            crop_w = vw
            crop_h = min(vh, int(vw * 9 / 16))
        else:
            crop_w = vw
            crop_h = vh

        is_portrait = (crop_h > crop_w)
        res_key = str(resolution or "original").lower().strip()
        if res_key in ("2k", "1440p"):
            if is_portrait:
                target_w, target_h = 1440, 2560
            elif crop_w == crop_h:
                target_w, target_h = 1440, 1440
            else:
                target_w, target_h = 2560, 1440
        elif res_key in ("1080p", "fhd"):
            if is_portrait:
                target_w, target_h = 1080, 1920
            elif crop_w == crop_h:
                target_w, target_h = 1080, 1080
            else:
                target_w, target_h = 1920, 1080
        elif res_key in ("720p", "hd"):
            if is_portrait:
                target_w, target_h = 720, 1280
            elif crop_w == crop_h:
                target_w, target_h = 720, 720
            else:
                target_w, target_h = 1280, 720
        else:
            target_w, target_h = crop_w, crop_h

        target_w = (int(target_w) // 2) * 2
        target_h = (int(target_h) // 2) * 2

        # Scale to requested resolution if different from cropped source
        hd_upscale_enabled = bool(edits.get("hd_upscale_enabled", 0))
        hd_upscale_1080p = bool(edits.get("hd_upscale_1080p", 0))
        if hd_upscale_enabled and hd_upscale_1080p and res_key == "original" and min(target_w, target_h) < 1080:
            if is_portrait:
                target_h = int(round(1080 * (crop_h / max(1.0, float(crop_w)))))
                target_w = 1080
                target_h = (target_h // 2) * 2
                v_filters.append("scale=1080:-2:flags=lanczos")
            else:
                target_w = int(round(1080 * (crop_w / max(1.0, float(crop_h)))))
                target_h = 1080
                target_w = (target_w // 2) * 2
                v_filters.append("scale=-2:1080:flags=lanczos")
        elif res_key != "original" or (crop_w != target_w or crop_h != target_h):
            scale_flags = ":flags=lanczos" if hd_upscale_enabled else ""
            v_filters.append(
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease{scale_flags},"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black"
            )

        # Smart HD Clarity Upscaler & Frame Enhancer (Denoise + Unsharp mask)
        if hd_upscale_enabled:
            v_filters.append("hqdn3d=1.5:1.5:6:6,unsharp=5:5:0.85:5:5:0.0")

        # Frame rate adjustment if specified
        fps_val = str(fps or "original").strip()
        if fps_val in ("60", "30"):
            v_filters.append(f"fps={fps_val}")

        active_masks = cls._parse_masks(edits)
        box_masks = [m for m in active_masks if m.get("mode", "blur") != "blur"]
        blur_masks = [m for m in active_masks if m.get("mode", "blur") == "blur"]

        # Solid Boxes can be added as drawbox filters
        for bm in box_masks:
            mx = max(0.0, min(0.98, float(bm.get("x", 0.05))))
            my = max(0.0, min(0.98, float(bm.get("y", 0.78))))
            mw = max(0.02, min(1.0, float(bm.get("w", 0.90))))
            mh = max(0.02, min(1.0, float(bm.get("h", 0.14))))
            if mx + mw > 1.0:
                mw = max(0.02, round(1.0 - mx, 3))
            if my + mh > 1.0:
                mh = max(0.02, round(1.0 - my, 3))
            strength = float(bm.get("strength", 0.75))
            raw_col = str(bm.get("color", "#000000")).lstrip("#")
            hex_col = raw_col if len(raw_col) == 6 else "000000"
            alpha = max(0.10, min(1.0, strength))
            drawbox_str = (
                f"drawbox=x=iw*{mx:.3f}:y=ih*{my:.3f}:w=iw*{mw:.3f}:h=ih*{mh:.3f}"
                f":color=0x{hex_col}@{alpha:.2f}:t=fill"
            )
            v_filters.append(drawbox_str)

        # Burn subtitles at target resolution for razor-sharp clarity
        if edits.get("burn_subs", 0):
            ass_path = ass_sub_path if (ass_sub_path and Path(ass_sub_path).exists()) else str(Path(output_mp4).with_suffix(".ass"))
            cls.write_khmer_ass(segments, ass_path, edits, vid_w=target_w, vid_h=target_h)
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            v_filters.append(f"ass='{safe_ass}'")

        logo_path = edits.get("logo_path", "")
        has_logo = bool(logo_path and Path(logo_path).exists())
        has_blur_masks = bool(blur_masks)
        has_hook_banner = bool(edits.get("hook_enabled", 0) and (edits.get("hook_text") or "").strip())

        needs_reencode = bool(
            v_filters
            or has_logo
            or has_blur_masks
            or has_hook_banner
            or hd_upscale_enabled
            or edits.get("burn_subs", 0)
            or res_key != "original"
            or fps_val in ("60", "30")
            or int(edits.get("trim_start_ms", 0)) > 0
            or int(edits.get("trim_end_ms", 0)) > 0
            or ac_enabled
            or bool(lut_vf)
        )

        mask_ass_path = ""
        hook_png_path = ""
        hook_ass_path = ""
        hw = get_hardware_profile()
        q_p = str(quality_preset or "balanced").lower()

        if needs_reencode:
            # If Blur Mask is active AND burned subtitles are active, apply blur mask before burning subtitles
            burn_filter = None
            if has_blur_masks and v_filters and (
                v_filters[-1].startswith("subtitles=") or v_filters[-1].startswith("ass=")
            ):
                burn_filter = v_filters.pop()

            v_chain = "[0:v]" + ",".join(v_filters) + "[vbase]" if v_filters else "[0:v]null[vbase]"
            filter_parts.append(v_chain)
            current_v = "[vbase]"

            if blur_masks:
                auto_timed_blur = bool(edits.get("auto_timed_blur", 1))
                mask_ass_path = str(work_dir / f"_dynamic_blur_mask_{int(time.time()*1000)}.ass")
                has_timed_segments = bool(
                    auto_timed_blur
                    and segments
                    and any(int(s.get("end_ms", 0)) > int(s.get("start_ms", 0)) for s in segments)
                )
                has_dynamic_ass = has_timed_segments and cls.write_dynamic_blur_mask_ass(
                    segments, blur_masks, target_w, target_h, mask_ass_path
                )

                if has_dynamic_ass:
                    safe_mask_ass = mask_ass_path.replace("\\", "/").replace(":", "\\:")
                    filter_parts.append(
                        f"{current_v}split=3[v_base_clean][v_base_to_blur][v_for_mask];"
                        f"[v_base_to_blur]boxblur=12:2[v_base_blurred];"
                        f"[v_for_mask]drawbox=color=black:t=fill,ass='{safe_mask_ass}'[mask_timed];"
                        f"[v_base_clean][v_base_blurred][mask_timed]maskedmerge[vmasked]"
                    )
                    current_v = "[vmasked]"
                else:
                    for idx, bm in enumerate(blur_masks):
                        mx = max(0.0, min(0.98, float(bm.get("x", 0.05))))
                        my = max(0.0, min(0.98, float(bm.get("y", 0.78))))
                        mw = max(0.02, min(1.0, float(bm.get("w", 0.90))))
                        mh = max(0.02, min(1.0, float(bm.get("h", 0.14))))
                        if mx + mw > 1.0:
                            mw = max(0.02, round(1.0 - mx, 3))
                        if my + mh > 1.0:
                            mh = max(0.02, round(1.0 - my, 3))

                        next_v = f"[vmasked_{idx}]"
                        filter_parts.append(
                            f"{current_v}split[vm_main_{idx}][vm_crop_{idx}];"
                            f"[vm_crop_{idx}]crop=w=trunc(iw*{mw:.3f}/2)*2:h=trunc(ih*{mh:.3f}/2)*2:x=trunc(iw*{mx:.3f}/2)*2:y=trunc(ih*{my:.3f}/2)*2,"
                            f"boxblur=12:2[vm_blurred_{idx}];"
                            f"[vm_main_{idx}][vm_blurred_{idx}]overlay=x=trunc(main_w*{mx:.3f}/2)*2:y=trunc(main_h*{my:.3f}/2)*2{next_v}"
                        )
                        current_v = next_v

            if burn_filter:
                filter_parts.append(f"{current_v}{burn_filter}[vsubbed]")
                current_v = "[vsubbed]"

            if has_hook_banner:
                hook_png_candidate = str(work_dir / f"_hook_banner_{int(time.time()*1000)}.png")
                rendered_png = cls.render_hook_banner_png(edits, target_w, target_h, hook_png_candidate)
                if rendered_png and Path(rendered_png).exists():
                    hook_png_path = rendered_png
                    hook_idx = next_input_idx
                    next_input_idx += 1
                    inputs.extend(["-loop", "1", "-i", str(Path(hook_png_path).resolve())])
                    filter_parts.append(
                        f"[{hook_idx}:v]format=rgba,setsar=1[hk_a];"
                        f"{current_v}[hk_a]overlay=x=0:y=0:shortest=1[vhook]"
                    )
                    current_v = "[vhook]"
                else:
                    hook_ass_candidate = str(work_dir / f"_hook_banner_{int(time.time()*1000)}.ass")
                    vid_dur_ms = cls.get_duration_ms(video_path)
                    rendered_ass = cls.write_hook_banner_ass(edits, target_w, target_h, vid_dur_ms, hook_ass_candidate)
                    if rendered_ass and Path(rendered_ass).exists():
                        hook_ass_path = rendered_ass
                        safe_hk_ass = hook_ass_path.replace("\\", "/").replace(":", "\\:")
                        filter_parts.append(f"{current_v}ass='{safe_hk_ass}'[vhook]")
                        current_v = "[vhook]"

            if has_logo:
                logo_idx = next_input_idx
                next_input_idx += 1
                inputs.extend(["-loop", "1", "-i", str(Path(logo_path).resolve())])
                scale = max(0.03, min(0.80, float(edits.get("logo_scale", 0.15))))
                target_logo_w = max(24, int(round(target_w * scale / 2.0) * 2))
                opacity = max(0.05, min(1.0, float(edits.get("logo_opacity", 0.90))))
                lx = max(0.0, min(0.95, float(edits.get("logo_x", 0.05))))
                ly = max(0.0, min(0.95, float(edits.get("logo_y", 0.05))))
                filter_parts.append(
                    f"[{logo_idx}:v]format=rgba,scale={target_logo_w}:-2:flags=lanczos,setsar=1,"
                    f"colorchannelmixer=aa={opacity:.2f}[lg_a];"
                    f"{current_v}[lg_a]overlay=x=main_w*{lx:.3f}:y=main_h*{ly:.3f}:shortest=1[vlogo]"
                )
                current_v = "[vlogo]"

            if ac_enabled and ac_border:
                bg_w = max(32, (target_w // 4 // 2) * 2)
                bg_h = max(32, (target_h // 4 // 2) * 2)
                fg_w = (int(target_w * 0.94) // 2) * 2
                fg_h = (int(target_h * 0.94) // 2) * 2
                filter_parts.append(
                    f"{current_v}split[vac_bg][vac_fg];"
                    f"[vac_bg]scale={bg_w}:{bg_h},boxblur=8:1,scale={target_w}:{target_h}[vac_blur];"
                    f"[vac_fg]scale={fg_w}:{fg_h}[vac_inner];"
                    f"[vac_blur][vac_inner]overlay=(W-w)/2:(H-h)/2[vout]"
                )
            else:
                filter_parts.append(f"{current_v}null[vout]")

            # Choose optimal hardware / CPU encoder with quality bitrate flags
            opt_flags = cls.detect_video_encoder()
            detected_codec = opt_flags[1] if len(opt_flags) > 1 else "libx264"
            target_codec = "libx264" if encoder_choice == "cpu" else detected_codec
            is_2k = (res_key in ("2k", "1440p"))
            q_p = str(quality_preset or "balanced").lower()

            if "nvenc" in target_codec:
                if q_p in ("ultrafast", "speed"):
                    enc_flags = ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "fastdecode", "-cq", "28", "-b:v", "5M" if is_2k else "3.5M"]
                elif q_p == "high":
                    enc_flags = ["-c:v", "h264_nvenc", "-preset", "p2", "-cq", "19", "-b:v", "14M" if is_2k else "10M"]
                elif q_p == "small":
                    enc_flags = ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "27", "-b:v", "4M" if is_2k else "3M"]
                else:
                    enc_flags = ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "23", "-b:v", "8M" if is_2k else "5.5M"]
            elif "qsv" in target_codec:
                if q_p in ("ultrafast", "speed"):
                    enc_flags = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "28", "-b:v", "5M" if is_2k else "3.5M"]
                elif q_p == "high":
                    enc_flags = ["-c:v", "h264_qsv", "-preset", "faster", "-global_quality", "19", "-b:v", "14M" if is_2k else "10M"]
                elif q_p == "small":
                    enc_flags = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "27", "-b:v", "4M" if is_2k else "3M"]
                else:
                    enc_flags = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23", "-b:v", "8M" if is_2k else "5.5M"]
            elif "amf" in target_codec:
                if q_p in ("ultrafast", "speed"):
                    enc_flags = ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "28", "-qp_p", "28"]
                elif q_p == "high":
                    enc_flags = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "19", "-qp_p", "19"]
                elif q_p == "small":
                    enc_flags = ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "27", "-qp_p", "27"]
                else:
                    enc_flags = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]
            elif "mf" in target_codec:
                if q_p in ("ultrafast", "speed"):
                    enc_flags = ["-c:v", "h264_mf", "-quality", "0", "-b:v", "4.5M" if is_2k else "3M"]
                elif q_p == "high":
                    enc_flags = ["-c:v", "h264_mf", "-quality", "0", "-b:v", "14M" if is_2k else "10M"]
                elif q_p == "small":
                    enc_flags = ["-c:v", "h264_mf", "-quality", "0", "-b:v", "4M" if is_2k else "3M"]
                else:
                    enc_flags = ["-c:v", "h264_mf", "-quality", "0", "-b:v", "8M" if is_2k else "5.5M"]
            else:
                cpu_t = str(hw["ffmpeg_threads"])
                if q_p in ("ultrafast", "speed"):
                    enc_flags = ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode", "-crf", "25", "-threads", cpu_t]
                elif q_p == "high":
                    enc_flags = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-threads", cpu_t]
                elif q_p == "small":
                    enc_flags = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-threads", cpu_t]
                else:
                    enc_flags = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", cpu_t]

            v_map = ["-map", "[vout]", *enc_flags, "-pix_fmt", "yuv420p"]
        else:
            # Zero video re-encoding if no visual edits or scaling applied (~2-4 seconds)
            v_map = ["-map", "0:v", "-c:v", "copy"]

        # Optional Trim Flags
        trim_flags = []
        t_start = int(edits.get("trim_start_ms", 0))
        t_end = int(edits.get("trim_end_ms", 0))
        if t_start > 0:
            trim_flags.extend(["-ss", f"{t_start / 1000:.3f}"])
        if t_end > t_start:
            trim_flags.extend(["-to", f"{t_end / 1000:.3f}"])

        fc_args = ["-filter_complex", ";".join(filter_parts)] if filter_parts else []

        meta_flags = [
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-fflags", "+bitexact",
            "-movflags", "+faststart",
        ] if ac_enabled else ["-movflags", "+faststart"]

        intro_p = str(edits.get("intro_path") or "").strip() if bool(edits.get("intro_enabled", 0)) else ""
        outro_p = str(edits.get("outro_path") or "").strip() if bool(edits.get("outro_enabled", 0)) else ""
        has_stitch = bool((intro_p and Path(intro_p).exists()) or (outro_p and Path(outro_p).exists()))
        pre_stitch_mp4 = str(work_dir / f"_main_pre_stitch_{int(time.time()*1000)}.mp4") if has_stitch else output_mp4

        cmd = [
            "ffmpeg", "-y", "-threads", str(hw["ffmpeg_threads"]), *inputs,
            *trim_flags,
            *fc_args,
            *v_map, "-map", "1:a",
            "-c:a", "aac", "-b:a", "192k",
            "-max_muxing_queue_size", "1024",
            *meta_flags,
            "-shortest",
            pre_stitch_mp4
        ]
        if progress_cb:
            progress_cb(60, f"កំពុង Render វីដេអូចេញជាកម្រិត {target_w}x{target_h} ({res_key.upper()})...")

        try:
            cls.run_ffmpeg_safe(
                cmd,
                fallback_cpu=True,
                quality_preset=q_p,
                cancel_event=cancel_event,
                progress_cb=progress_cb,
            )
            if has_stitch:
                cls.stitch_intro_outro(
                    main_video_path=pre_stitch_mp4,
                    output_mp4=output_mp4,
                    intro_path=intro_p if (intro_p and Path(intro_p).exists()) else "",
                    outro_path=outro_p if (outro_p and Path(outro_p).exists()) else "",
                    target_w=target_w,
                    target_h=target_h,
                    quality_preset=q_p,
                    encoder_choice=encoder_choice,
                    cancel_event=cancel_event,
                    progress_cb=progress_cb,
                )
            if progress_cb:
                progress_cb(100, f"Render វីដេអូបានជោគជ័យ: {Path(output_mp4).name}")
            return output_mp4
        finally:
            Path(mixed_wav).unlink(missing_ok=True)
            if mask_ass_path:
                Path(mask_ass_path).unlink(missing_ok=True)
            if hook_png_path:
                Path(hook_png_path).unlink(missing_ok=True)
            if hook_ass_path:
                Path(hook_ass_path).unlink(missing_ok=True)
            if has_stitch and pre_stitch_mp4 != output_mp4:
                Path(pre_stitch_mp4).unlink(missing_ok=True)
            gc.collect()

    @classmethod
    def export_split_episodes(
        cls,
        video_path: str,
        segments: List[Dict],
        clip_markers: List[Dict],
        output_dir: str,
        edits: Dict = None,
        bgm_volume: float = 0.25,
        voice_gain: float = 2.2,
        sfx_events: List[Dict] = None,
        resolution: str = "original",
        quality_preset: str = "balanced",
        fps: str = "original",
        encoder_choice: str = "auto",
        cancel_event: Any = None,
        progress_cb: Any = None,
    ) -> List[str]:
        """
        នាំចេញវីដេអូកាត់ជាភាគៗ (Split by Episode / Chapter Markers).
        ប្រសិនបើគ្មាន Marker ឬមានតែ 1 វីដេអូវែង វានឹងស្វ័យប្រវត្តិកាត់ជាភាគ 3 នាទីម្តង។
        អនុវត្ត Offset ពេលវេលា Subtitle និង Audio តាមម៉ោងចាប់ផ្តើមរបស់ភាគនីមួយៗ (seg_start - ep_start)
        ព្រមទាំងរក្សាទុក Subtitle Style, Blur Mask, Logo, និងលាយសំឡេងខ្មែរ 100% ស្អាត។
        """
        edits = dict(edits or {})
        keep_bgm_only = bool(edits.get("keep_bgm_only", 0))
        if keep_bgm_only:
            edits["mute_original_audio"] = 0
            if bgm_volume <= 0.001:
                bgm_volume = float(edits.get("orig_volume") or 0.35)
                if bgm_volume <= 0.01:
                    bgm_volume = 0.35
        elif bool(edits.get("mute_original_audio", 0)) or bool(edits.get("dubbed_no_orig_audio", 0)) or bgm_volume <= 0.001:
            bgm_volume = 0.0
            edits["orig_volume"] = 0.0
            edits["mute_original_audio"] = 1
        if "anti_copyright_enabled" not in edits:
            edits["anti_copyright_enabled"] = 1
        if "auto_blur_chinese" not in edits:
            edits["auto_blur_chinese"] = 1
        out_d = Path(output_dir)
        out_d.mkdir(parents=True, exist_ok=True)

        total_dur_ms = cls.get_duration_ms(video_path)
        markers = list(clip_markers or [])
        if not markers or len(markers) <= 1:
            # Auto-split into 3-minute parts (180,000 ms)
            part_dur_ms = 180000
            markers = []
            c_start = 0
            idx = 1
            base_name = Path(video_path).stem
            while c_start < total_dur_ms:
                c_end = min(total_dur_ms, c_start + part_dur_ms)
                markers.append({
                    "index": idx,
                    "name": f"{base_name}_Part{idx:02d}",
                    "start_ms": c_start,
                    "end_ms": c_end,
                })
                idx += 1
                c_start = c_end

        total_eps = len(markers)
        exported_files = []

        if progress_cb:
            progress_cb(5, f"ចាប់ផ្តើមរៀបចំ Export វីដេអូចំនួន {total_eps} ភាគ...")

        work_dir = out_d / "_split_temp"
        work_dir.mkdir(parents=True, exist_ok=True)

        for i, ep in enumerate(markers, start=1):
            if cancel_event is not None and cancel_event.is_set():
                break
            ep_start = int(ep["start_ms"])
            ep_end = int(ep["end_ms"])
            if ep_end <= ep_start:
                continue

            ep_name = Path(ep.get("name", f"Episode_{i:02d}")).stem
            safe_name = "".join(c for c in ep_name if c.isalnum() or c in (" ", "-", "_")).strip()
            out_file = str(out_d / f"{i:02d}_{safe_name}_KH.mp4")

            # Offset segments relative to episode start
            ep_segs = []
            for s in segments:
                s_start = int(s.get("start_ms", 0))
                s_end = int(s.get("end_ms", 0))
                if s_start < ep_end and s_end > ep_start:
                    sc = dict(s)
                    sc["start_ms"] = max(0, s_start - ep_start)
                    sc["end_ms"] = max(100, s_end - ep_start)
                    ep_segs.append(sc)

            # Offset SFX events relative to episode start
            ep_sfx = []
            for sx in (sfx_events or []):
                sx_start = int(sx.get("start_ms", 0))
                if ep_start <= sx_start < ep_end:
                    sxc = dict(sx)
                    sxc["start_ms"] = max(0, sx_start - ep_start)
                    ep_sfx.append(sxc)

            # Fast trim video clip for this episode
            temp_ep_vid = str(work_dir / f"_ep_{i}_{Path(video_path).stem}.mp4")
            trim_cmd = [
                "ffmpeg", "-y",
                "-ss", f"{ep_start / 1000.0:.3f}",
                "-to", f"{ep_end / 1000.0:.3f}",
                "-i", video_path,
                "-c:v", "copy", "-c:a", "copy",
                temp_ep_vid
            ]
            try:
                cls.run_ffmpeg_safe(trim_cmd, fallback_cpu=False, cancel_event=cancel_event)
            except Exception:
                hw = get_hardware_profile()
                trim_cmd = [
                    "ffmpeg", "-y", "-threads", str(hw["ffmpeg_threads"]),
                    "-ss", f"{ep_start / 1000.0:.3f}",
                    "-to", f"{ep_end / 1000.0:.3f}",
                    "-i", video_path,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                    "-c:a", "aac",
                    "-max_muxing_queue_size", "1024",
                    temp_ep_vid
                ]
                cls.run_ffmpeg_safe(trim_cmd, fallback_cpu=False, cancel_event=cancel_event)

            ep_edits = dict(edits)
            ep_edits["trim_start_ms"] = 0
            ep_edits["trim_end_ms"] = 0

            ep_base_pct = int(10 + (i - 1) * (85.0 / total_eps))
            ep_span_pct = int(85.0 / total_eps)

            def make_sub_progress(b_pct, s_pct, ep_num, tot, name):
                def sub_emit(p_val, p_msg):
                    if progress_cb:
                        curr = b_pct + int((p_val / 100.0) * s_pct)
                        progress_cb(curr, f"[{ep_num}/{tot}] {name}: {p_msg}")
                return sub_emit

            sub_cb = make_sub_progress(ep_base_pct, ep_span_pct, i, total_eps, safe_name)
            sub_cb(10, f"កំពុង Render ភាគ {i}/{total_eps}...")

            try:
                cls.render_final_video(
                    video_path=temp_ep_vid,
                    segments=ep_segs,
                    output_mp4=out_file,
                    bgm_volume=bgm_volume,
                    edits=ep_edits,
                    voice_gain=voice_gain,
                    sfx_events=ep_sfx,
                    resolution=resolution,
                    quality_preset=quality_preset,
                    fps=fps,
                    encoder_choice=encoder_choice,
                    cancel_event=cancel_event,
                    progress_cb=sub_cb,
                )
                exported_files.append(out_file)
            finally:
                Path(temp_ep_vid).unlink(missing_ok=True)
                gc.collect()

        try:
            import shutil
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass

        if progress_cb:
            progress_cb(100, f"បាន Render ចប់សព្វគ្រប់ចំនួន {len(exported_files)} ភាគ!")

        return exported_files


# Module-level aliases
get_duration_ms = MediaEngine.get_duration_ms
get_duration_sec = MediaEngine.get_duration_sec

