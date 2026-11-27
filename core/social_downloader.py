"""
core/social_downloader.py - Social Video Downloader using yt-dlp
Supports TikTok, Douyin (抖音), YouTube / Shorts, Facebook, Instagram, X (Twitter), Bilibili, etc.
Safe for low-spec PCs: forces H.264/AAC MP4 output and streams chunks without ballooning RAM.
"""

import os
import re
import threading
from pathlib import Path
from typing import List, Callable, Optional


class SocialVideoDownloader:
    """Downloader helper for social video links"""

    @staticmethod
    def extract_urls(text: str, max_count: int = 50) -> List[str]:
        """
        ស្រង់យក Links វីដេអូស្អាតៗចេញពីអត្ថបទ (កាត់ចោលអក្សរចិន/ខ្មែរ/សំរាមដែលជាប់ជាមួយ link)
        និងលុប Links ស្ទួនៗដោយស្វ័យប្រវត្តិ។
        """
        if not text:
            return []

        pattern = r"https?://[^\s<>\"'()]+"
        matches = re.findall(pattern, text)
        cleaned = []
        seen = set()

        for m in matches:
            u = m.rstrip(".,;!?:")
            if u and u not in seen:
                seen.add(u)
                cleaned.append(u)
                if len(cleaned) >= max_count:
                    break
        return cleaned

    @staticmethod
    def download_urls(
        urls: List[str],
        output_dir: str,
        progress_cb: Optional[Callable[[dict], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None
    ) -> List[str]:
        """
        ទាញយកវីដេអូទាំងអស់តាម yt-dlp ដោយរក្សាទុកជា .mp4 (H.264 + AAC)
        - urls: បញ្ជី links
        - output_dir: folder សម្រាប់ទុកឯកសារ
        - progress_cb: callback ផ្តល់ព័ត៌មានភាគរយ (pct, speed, eta, current_index, total)
        - log_cb: callback ផ្តល់ status text
        - stop_event: threading.Event សម្រាប់ Cancel
        """
        try:
            import yt_dlp
        except ImportError:
            if log_cb:
                log_cb("កំហុស៖ រកមិនឃើញបណ្ណាល័យ yt-dlp សូមដំឡើង pip install yt-dlp")
            return []

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        downloaded_files = []

        total_links = len(urls)

        for idx, url in enumerate(urls, start=1):
            if stop_event and stop_event.is_set():
                if log_cb:
                    log_cb("បានផ្អាកការទាញយកតាមការស្នើសុំ។")
                break

            if log_cb:
                log_cb(f"[{idx}/{total_links}] កំពុងទាញយក: {url[:55]}...")

            current_downloaded_file = [None]

            def ydl_hook(d):
                if stop_event and stop_event.is_set():
                    raise Exception("Download cancelled by user")

                if d["status"] == "downloading":
                    total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    downloaded_bytes = d.get("downloaded_bytes") or 0
                    pct = 0.0
                    if total_bytes > 0:
                        pct = round((downloaded_bytes / total_bytes) * 100.0, 1)
                    speed = d.get("speed") or 0  # bytes/sec
                    eta = d.get("eta") or 0      # seconds

                    if progress_cb:
                        progress_cb({
                            "index": idx,
                            "total": total_links,
                            "percent": pct,
                            "speed_bytes": speed,
                            "eta_sec": eta,
                            "filename": Path(d.get("filename", "")).name,
                        })
                elif d["status"] == "finished":
                    fn = d.get("filename")
                    if fn:
                        current_downloaded_file[0] = fn

            ydl_opts = {
                # Format: ជ្រើសរើស MP4 (H.264 + AAC) ដើម្បីឲ្យ preview player ដើរស្រួលបំផុតលើ Low-Spec PC
                "format": "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": str(out_path / "%(title).45B_%(id)s.%(ext)s"),
                "merge_output_format": "mp4",
                "noplaylist": True,
                "no_color": True,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
                "progress_hooks": [ydl_hook],
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        final_fn = current_downloaded_file[0]
                        if not final_fn or not os.path.exists(final_fn):
                            fn_requested = ydl.prepare_filename(info)
                            base, _ = os.path.splitext(fn_requested)
                            if os.path.exists(base + ".mp4"):
                                final_fn = base + ".mp4"
                            elif os.path.exists(fn_requested):
                                final_fn = fn_requested

                        if final_fn and os.path.exists(final_fn):
                            downloaded_files.append(str(Path(final_fn).resolve()))
                            if log_cb:
                                log_cb(f"✓ ទាញយកបានជោគជ័យ: {Path(final_fn).name}")
            except Exception as e:
                if stop_event and stop_event.is_set():
                    break
                if log_cb:
                    log_cb(f"⚠ មិនអាចទាញយក link ទី {idx} បានទេ: {e}")

        return downloaded_files
