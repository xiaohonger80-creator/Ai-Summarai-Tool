import os
import re
import time
import difflib
import subprocess
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

# Limit thread pinning on low-spec PCs so OCR doesn't spike CPU to 95%-100%
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["ORT_NUM_THREADS"] = "2"

import cv2
try:
    cv2.setNumThreads(2)
except Exception:
    pass

from core.extractors.base import BaseExtractor
from core.schema import SubtitleSegment


class PaddleOCRExtractor(BaseExtractor):
    """
    Hard-subtitle OCR scanner for burned-in Chinese video frames.
    - Uses PaddleOCR (PP-OCRv4, lang='ch') with RapidOCR fallback.
    - Samples frames at sample_fps (default 2.0).
    - Crops bottom 35% subtitle region.
    - Filters low-confidence lines (< 0.75) and merges consecutive duplicate lines.
    """

    def __init__(
        self,
        lang: str = "ch",
        use_angle_cls: bool = True,
        confidence_threshold: float = 0.75,
        crop_bottom_pct: float = 0.35,
        sample_fps: float = 2.0,
    ):
        super().__init__()
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.confidence_threshold = confidence_threshold
        self.crop_bottom_pct = crop_bottom_pct
        self.sample_fps = sample_fps
        self._is_paddle = False

    def _ensure_model(self):
        if self.model is None:
            try:
                from paddleocr import PaddleOCR
                self.model = PaddleOCR(use_angle_cls=self.use_angle_cls, lang=self.lang, show_log=False)
                self._is_paddle = True
            except Exception:
                # RapidOCR fallback
                from rapidocr_onnxruntime import RapidOCR
                self.model = RapidOCR()
                self._is_paddle = False

    def _ocr_frame(self, crop_bgr) -> List[tuple[str, float]]:
        """Returns list of (text, confidence) from cropped subtitle box."""
        if self._is_paddle:
            res = self.model.ocr(crop_bgr, cls=self.use_angle_cls)
            lines = []
            if res and res[0]:
                for line in res[0]:
                    txt, score = line[1][0], float(line[1][1])
                    lines.append((txt.strip(), score))
            return lines
        else:
            result, _ = self.model(crop_bgr)
            lines = []
            if result:
                for item in result:
                    txt, score = str(item[1]).strip(), float(item[2])
                    lines.append((txt, score))
            return lines

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()

    def extract(
        self,
        video_path: str,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        cancel_event=None,
    ) -> List[Dict[str, Any]]:
        if not video_path or not Path(video_path).exists():
            return []

        self._ensure_model()
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        total_duration = total_frames / fps if fps > 0 else 0

        frame_step = max(1, int(fps / self.sample_fps))
        frame_idx = 0
        prev_thumb = None

        raw_detections: List[Dict[str, Any]] = []

        if progress_cb:
            progress_cb(10, f"Scanning video frames with OCR (step={frame_step})...")

        try:
            while cap.isOpened():
                if cancel_event and cancel_event.is_set():
                    break

                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % frame_step == 0:
                    current_sec = round(frame_idx / fps, 2)
                    h, w = frame.shape[:2]
                    y_start = int(h * (1.0 - self.crop_bottom_pct))
                    crop = frame[y_start:h, 0:w]

                    # CPU Protection: Fast Thumb Diff check to skip unchanged frames
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    thumb = cv2.resize(gray, (160, 40), interpolation=cv2.INTER_NEAREST).astype(np.float32)

                    if float(np.std(thumb)) < 3.0:
                        frame_idx += 1
                        continue

                    if prev_thumb is not None:
                        diff = float(np.mean(np.abs(thumb - prev_thumb)))
                        if diff < 3.2:
                            prev_thumb = thumb
                            frame_idx += 1
                            time.sleep(0.002)
                            continue
                    prev_thumb = thumb

                    lines = self._ocr_frame(crop)
                    valid_texts = [
                        txt for txt, score in lines
                        if score >= self.confidence_threshold and re.search(r"[\u4e00-\u9fff]", txt)
                    ]
                    if valid_texts:
                        combined_text = " ".join(valid_texts).strip()
                        raw_detections.append({
                            "sec": current_sec,
                            "text": combined_text,
                        })

                    # Cooperative sleep 10ms to keep CPU usage < 50%
                    time.sleep(0.010)

                    if progress_cb and total_frames > 0:
                        pct = min(85, int((frame_idx / total_frames) * 75) + 10)
                        progress_cb(pct, f"OCR Scanning: {int(current_sec)}s / {int(total_duration)}s...")

                frame_idx += 1
        finally:
            cap.release()
            self.unload()

        if not raw_detections:
            return []

        # Merge consecutive identical/similar lines
        if progress_cb:
            progress_cb(88, "Merging consecutive subtitle frames...")

        merged: List[Dict[str, Any]] = []
        cur_start = raw_detections[0]["sec"]
        cur_end = cur_start + 1.2
        cur_text = raw_detections[0]["text"]

        for det in raw_detections[1:]:
            sim = self._text_similarity(cur_text, det["text"])
            time_gap = det["sec"] - cur_end
            if sim >= 0.70 and time_gap <= 1.2:
                cur_end = det["sec"] + (1.0 / self.sample_fps)
                if len(det["text"]) > len(cur_text):
                    cur_text = det["text"]
            else:
                merged.append(SubtitleSegment(
                    id=len(merged) + 1,
                    start=round(cur_start, 2),
                    end=round(cur_end, 2),
                    text=cur_text,
                    translated="",
                ).to_dict())
                cur_start = det["sec"]
                cur_end = cur_start + 1.0
                cur_text = det["text"]

        # Append last segment
        merged.append(SubtitleSegment(
            id=len(merged) + 1,
            start=round(cur_start, 2),
            end=round(cur_end, 2),
            text=cur_text,
            translated="",
        ).to_dict())

        if progress_cb:
            progress_cb(95, f"OCR extracted {len(merged)} subtitle segments.")

        return merged
