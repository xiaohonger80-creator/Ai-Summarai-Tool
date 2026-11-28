import gc
import json
import os
import re
import time
from pathlib import Path
from difflib import SequenceMatcher
import numpy as np
from core.sentence_splitter import split_all_segments, clean_chinese_text, is_junk_text

# កម្រិត Threads សម្រាប់ ONNX / OpenMP / BLAS ដើម្បីកុំឲ្យជាន់ឈ្លី CPU 100% លើម៉ាស៊ីន Spech តូច
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["VECLIB_MAXIMUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"
os.environ["ORT_NUM_THREADS"] = "2"
os.environ["ONNXRUNTIME_NUM_THREADS"] = "2"

try:
    import cv2
    _HAVE_CV2 = True
    # កំណត់ OpenCV Threads ត្រឹម 2 (ការពារកុំឲ្យប្រើ 20 threads pinning CPU 100%)
    cv2.setNumThreads(2)
    cv2.ocl.setUseOpenCL(False)
except ImportError:
    _HAVE_CV2 = False

try:
    from rapidocr import RapidOCR
    _IS_RAPIDOCR_V3 = True
except ImportError:
    from rapidocr_onnxruntime import RapidOCR
    _IS_RAPIDOCR_V3 = False


class SubtitleOCRScanner:
    def __init__(self):
        # កំណត់ Parameter ច្បាស់លាស់បំផុតសម្រាប់ចាប់អក្សរចិន និងកំណត់ Threads = 2 ការពារ CPU 100%
        ocr_params = {
            "Det.box_thresh": 0.22,
            "Det.unclip_ratio": 2.2,
            "Global.text_score": 0.32,
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.openvino.inference_num_threads": 2,
        }
        if _IS_RAPIDOCR_V3:
            self.ocr = RapidOCR(params=ocr_params)
        else:
            self.ocr = RapidOCR(box_thresh=0.22, unclip_ratio=2.2)

    @staticmethod
    def _clean_text(text: str) -> str:
        return clean_chinese_text(text)

    @staticmethod
    def _is_valid_subtitle(text: str) -> bool:
        if not text or is_junk_text(text):
            return False
        return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text))

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        if not a or not b:
            return False
        clean_a = re.sub(r"[^\w\u4e00-\u9fff]", "", a)
        clean_b = re.sub(r"[^\w\u4e00-\u9fff]", "", b)
        if not clean_a or not clean_b:
            return False
        if clean_a == clean_b:
            return True
        ratio = SequenceMatcher(None, clean_a, clean_b).ratio()
        if ratio >= 0.80:
            return True
        min_l, max_l = sorted([len(clean_a), len(clean_b)])
        if (clean_a in clean_b or clean_b in clean_a) and (min_l / float(max_l) >= 0.75) and ratio >= 0.70:
            return True
        return False

    @classmethod
    def _preprocess_frame(cls, frame_path: str, img=None):
        """
        បង្កើន Contrast និងភាពច្បាស់នៃអក្សររត់ចិន (CLAHE Enhancement) ការពារកុំឲ្យបាត់តួអក្សរស្តើងៗ
        """
        if not _HAVE_CV2:
            return frame_path
        try:
            if img is None:
                img = cv2.imread(frame_path)
            if img is None:
                return frame_path
            # CLAHE on Lightness channel to make Chinese characters pop out against background
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            enhanced = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)
            return enhanced
        except Exception:
            return frame_path

    @classmethod
    def _extract_ordered_text_and_bbox(
        cls,
        ocr_out,
        frame_w: int = 0,
        frame_h: int = 0,
        crop_y_offset: float = 0.72,
        crop_ratio: float = 0.28,
        min_score: float = 0.32,
    ):
        """
        Extracts ordered Chinese text AND the normalized full-frame bounding box
        {"x", "y", "w", "h"} covering all detected valid subtitle boxes on the frame.
        """
        items = []
        if hasattr(ocr_out, "txts"):
            txts = getattr(ocr_out, "txts", None)
            scores = getattr(ocr_out, "scores", None)
            boxes = getattr(ocr_out, "boxes", None)
            if not txts:
                return "", None
            for i, txt in enumerate(txts):
                score = float(scores[i]) if (scores is not None and i < len(scores)) else 1.0
                box = boxes[i] if (boxes is not None and i < len(boxes)) else [[0, i * 15]]
                items.append((box, str(txt), score))
        else:
            result = ocr_out[0] if isinstance(ocr_out, tuple) else ocr_out
            if not result:
                return "", None
            for item in result:
                if len(item) >= 3:
                    items.append((item[0], str(item[1]), float(item[2])))

        if not items:
            return "", None

        def _box_sort_key(it):
            try:
                box = it[0]
                if box and len(box) > 0 and len(box[0]) >= 2:
                    return (round(float(box[0][1]) / 12.0), float(box[0][0]))
            except Exception:
                pass
            return (0, 0.0)

        sorted_boxes = sorted(items, key=_box_sort_key)
        valid_items = [
            it for it in sorted_boxes
            if it[2] >= min_score and cls._is_valid_subtitle(it[1])
        ]
        lines = [it[1].strip() for it in valid_items]
        cleaned = cls._clean_text(" ".join(lines))
        if not cleaned:
            return "", None

        # Compute full-frame normalized bounding box if frame dimensions are known
        norm_bbox = None
        if frame_w > 0 and frame_h > 0:
            xs, ys = [], []
            for box, _, _ in valid_items:
                try:
                    for pt in box:
                        if len(pt) >= 2:
                            xs.append(float(pt[0]))
                            ys.append(float(pt[1]))
                except Exception:
                    continue
            if xs and ys:
                min_x = max(0.0, min(xs) / float(frame_w) - 0.025)
                max_x = min(1.0, max(xs) / float(frame_w) + 0.025)
                # Map crop-local y to full-video normalized y
                local_y0 = max(0.0, min(ys) / float(frame_h))
                local_y1 = min(1.0, max(ys) / float(frame_h))
                full_y0 = max(0.0, crop_y_offset + local_y0 * crop_ratio - 0.015)
                full_y1 = min(1.0, crop_y_offset + local_y1 * crop_ratio + 0.018)
                bw = max(0.08, round(max_x - min_x, 4))
                bh = max(0.04, round(full_y1 - full_y0, 4))
                norm_bbox = {
                    "x": round(min_x, 4),
                    "y": round(full_y0, 4),
                    "w": round(min(1.0 - min_x, bw), 4),
                    "h": round(min(1.0 - full_y0, bh), 4),
                }

        return cleaned, norm_bbox

    @classmethod
    def _extract_ordered_text(cls, ocr_out, min_score: float = 0.32) -> str:
        text, _ = cls._extract_ordered_text_and_bbox(ocr_out, min_score=min_score)
        return text

    @staticmethod
    def _union_bbox(b1, b2):
        if not b1:
            return b2
        if not b2:
            return b1
        x0 = min(b1["x"], b2["x"])
        y0 = min(b1["y"], b2["y"])
        x1 = max(b1["x"] + b1["w"], b2["x"] + b2["w"])
        y1 = max(b1["y"] + b1["h"], b2["y"] + b2["h"])
        return {
            "x": round(max(0.0, x0), 4),
            "y": round(max(0.0, y0), 4),
            "w": round(min(1.0 - max(0.0, x0), x1 - x0), 4),
            "h": round(min(1.0 - max(0.0, y0), y1 - y0), 4),
        }

    def scan_frames(
        self,
        frames_dir: str,
        fps: int = 3,
        progress_cb=None,
        crop_y_offset: float = 0.72,
        crop_ratio: float = 0.28,
    ):
        frames = sorted(Path(frames_dir).glob("frame_*.jpg")) if frames_dir and Path(frames_dir).exists() else []
        total = len(frames)
        if total == 0:
            if progress_cb:
                progress_cb(100)
            return []
        step_ms = int(1000 / max(1, fps))
        raw_events = []
        prev_thumb = None
        c_ratio = max(0.08, min(1.0, float(crop_ratio or 0.28)))
        c_y = max(0.0, min(1.0 - c_ratio, float(crop_y_offset if crop_y_offset is not None else (1.0 - c_ratio))))

        for idx, frame in enumerate(frames):
            ts_ms = idx * step_ms

            # ត្រួតពិនិត្យភាពខុសគ្នានៃរូបភាព (Fast Frame Difference & Downscale) ដើម្បីកាត់បន្ថយ CPU Load លើកុំព្យូទ័រ Spech តូច
            img = cv2.imread(str(frame)) if _HAVE_CV2 else None
            fh, fw = (img.shape[0], img.shape[1]) if img is not None else (0, 0)
            if img is not None:
                # Downscale មកត្រឹម max-width 960px បើធំជាងនេះ (កាត់បន្ថយបន្ទុក ONNX 65% ដោយរក្សាភាពច្បាស់នៃអក្សរចិន ១០០%)
                if fw > 960:
                    scale = 960.0 / fw
                    img = cv2.resize(img, (960, int(fh * scale)), interpolation=cv2.INTER_AREA)
                    fh, fw = img.shape[:2]

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                thumb = cv2.resize(gray, (160, 40), interpolation=cv2.INTER_NEAREST)

                # រំលង Frame ណាដែលខ្មៅសុទ្ធ ឬស្មើធេងគ្មានអត្ថបទ (Blank / Flat Frame Guard)
                thumb_f = thumb.astype(np.float32)
                if float(np.std(thumb_f)) < 3.2 or float(np.mean(thumb_f)) < 4.0:
                    del img, gray, thumb, thumb_f
                    continue

                if prev_thumb is not None:
                    diff = float(np.mean(np.abs(thumb_f - prev_thumb)))
                    # បើទិដ្ឋភាពអក្សរមិនផ្លាស់ប្តូរ (Diff < 3.2) ពន្យារម៉ោងអក្សរមុន ដោយមិនបាច់រត់ Neural Network នាំឱ្យយឺត និងឡើងកម្តៅ CPU
                    if diff < 3.2:
                        if raw_events:
                            last = raw_events[-1]
                            if (ts_ms + step_ms - last["start_ms"]) <= 4200:
                                last["end_ms"] = ts_ms + step_ms
                        del img, gray, thumb, thumb_f
                        time.sleep(0.002)
                        if progress_cb and idx % 10 == 0:
                            progress_cb(int(((idx + 1) / max(1, total)) * 100))
                        continue
                prev_thumb = thumb_f
                inp = self._preprocess_frame(str(frame), img=img)
                del gray, thumb
            else:
                inp = str(frame)

            ocr_out = self.ocr(inp)
            text, bbox = self._extract_ordered_text_and_bbox(
                ocr_out, frame_w=fw, frame_h=fh, crop_y_offset=c_y, crop_ratio=c_ratio, min_score=0.32
            )
            if img is not None:
                del img, inp

            # Cooperative Sleep ក្រោយ Inference (12ms) ដើម្បីទុក CPU ឲ្យ Windows & UI ដើររលូន កុំឲ្យឡើង 95%-100%
            time.sleep(0.012)

            if text and not is_junk_text(text):
                if raw_events:
                    last = raw_events[-1]
                    gap_ms = ts_ms - last["end_ms"]
                    if gap_ms <= 450 and self._similar(last["zh_text"], text):
                        if (ts_ms + step_ms - last["start_ms"]) <= 4200:
                            last["end_ms"] = ts_ms + step_ms
                            if len(text) > len(last["zh_text"]):
                                last["zh_text"] = text
                            if bbox:
                                last["_bbox"] = self._union_bbox(last.get("_bbox"), bbox)
                                last["bbox_json"] = json.dumps(last["_bbox"])
                            continue

                ev_dict = {
                    "start_ms": ts_ms,
                    "end_ms": ts_ms + step_ms,
                    "zh_text": text,
                    "bbox_json": json.dumps(bbox) if bbox else "",
                }
                if bbox:
                    ev_dict["_bbox"] = bbox
                raw_events.append(ev_dict)

            if idx % 45 == 44:
                gc.collect()

            if idx % 4 == 0:
                time.sleep(0.003)

            if progress_cb and idx % 10 == 0:
                progress_cb(int(((idx + 1) / max(1, total)) * 100))

        for ev in raw_events:
            ev.pop("_bbox", None)
            if (ev["end_ms"] - ev["start_ms"]) < 450:
                ev["end_ms"] = ev["start_ms"] + 450

        # កាត់ប្រយោគវែងៗឲ្យនៅខ្លីៗដោយស្វ័យប្រវត្តិ
        return split_all_segments(raw_events, max_chars=12, max_duration_ms=3800)
