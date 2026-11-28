from typing import List, Dict, Any, Callable, Optional

from core.extractors.base import BaseExtractor
from core.extractors.ocr_paddle import PaddleOCRExtractor
from core.extractors.asr_whisper import WhisperExtractor
from core.schema import SubtitleSegment


class HybridExtractor(BaseExtractor):
    """
    Hybrid Subtitle Extractor:
    1. Runs OCR (PaddleOCR/RapidOCR) as primary to extract hardcoded on-screen text.
    2. Unloads OCR from VRAM.
    3. Runs ASR (Whisper) to detect spoken dialogue.
    4. Gaps in OCR that have spoken audio are seamlessly filled with ASR lines!
    """

    def __init__(self, confidence_threshold: float = 0.75, sample_fps: float = 2.0):
        super().__init__()
        self.ocr_extractor = PaddleOCRExtractor(confidence_threshold=confidence_threshold, sample_fps=sample_fps)
        self.asr_extractor = WhisperExtractor(model_size="base")

    def extract(
        self,
        video_path: str,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        cancel_event=None,
    ) -> List[Dict[str, Any]]:
        # Phase 1: OCR Extraction
        if progress_cb:
            progress_cb(5, "Hybrid Phase 1/2: Extracting hardcoded subtitles via OCR...")

        ocr_segs = self.ocr_extractor.extract(
            video_path,
            progress_cb=lambda pct, msg: progress_cb(int(pct * 0.50), f"[OCR] {msg}") if progress_cb else None,
            cancel_event=cancel_event,
        )
        self.ocr_extractor.unload()

        if cancel_event and cancel_event.is_set():
            return ocr_segs

        # Phase 2: ASR Audio Dialogue Extraction
        if progress_cb:
            progress_cb(55, "Hybrid Phase 2/2: Extracting audio dialogue to fill gaps...")

        asr_segs = self.asr_extractor.extract(
            video_path,
            progress_cb=lambda pct, msg: progress_cb(50 + int(pct * 0.40), f"[ASR] {msg}") if progress_cb else None,
            cancel_event=cancel_event,
        )
        self.asr_extractor.unload()

        if cancel_event and cancel_event.is_set():
            return ocr_segs

        if not asr_segs:
            return ocr_segs
        if not ocr_segs:
            return asr_segs

        # Phase 3: Alignment & Gap Filling
        if progress_cb:
            progress_cb(92, "Aligning OCR text with ASR audio gaps...")

        final_list = list(ocr_segs)
        for a in asr_segs:
            a_s = a["start"]
            a_e = a["end"]
            # Check if this ASR line overlaps with any existing OCR line
            has_overlap = any(
                not (a_e <= o["start"] + 0.3 or a_s >= o["end"] - 0.3)
                for o in ocr_segs
            )
            if not has_overlap and (a_e - a_s >= 0.5):
                # Gap with spoken voice detected! Fill the gap!
                final_list.append(a)

        # Sort by start time and re-index
        final_list.sort(key=lambda x: x["start"])
        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(final_list, start=1):
            normalized.append(SubtitleSegment(
                id=idx,
                start=item["start"],
                end=item["end"],
                text=item["text"],
                translated=item.get("translated", ""),
            ).to_dict())

        if progress_cb:
            progress_cb(100, f"Hybrid Complete: {len(normalized)} unified segments (OCR + Audio Fill).")

        return normalized

    def unload(self):
        self.ocr_extractor.unload()
        self.asr_extractor.unload()
        super().unload()
