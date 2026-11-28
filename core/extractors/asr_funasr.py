import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from core.extractors.base import BaseExtractor
from core.extractors.asr_whisper import WhisperExtractor
from core.schema import SubtitleSegment

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class FunASRExtractor(BaseExtractor):
    """
    Chinese ASR extraction via Alibaba FunASR (SenseVoiceSmall / paraformer-zh).
    High accuracy on Chinese dialects and fast inference.
    Falls back gracefully to Faster-Whisper if funasr package is not installed.
    """

    def __init__(self, model_name: str = "SenseVoiceSmall", device: str = "auto"):
        super().__init__()
        self.model_name = model_name
        self.device = device
        self._fallback_whisper = None

    def _ensure_model(self):
        if self.model is None:
            try:
                from funasr import AutoModel
                import torch

                dev = "cuda" if (self.device == "cuda" or (self.device == "auto" and torch.cuda.is_available())) else "cpu"
                self.model = AutoModel(
                    model=self.model_name,
                    vad_model="fsmn-vad",
                    punc_model="ct-punc",
                    device=dev,
                    disable_update=True,
                )
            except Exception as e:
                print(f"[FunASR Note] FunASR not available ({e}), falling back to Whisper...")
                self._fallback_whisper = WhisperExtractor(model_size="large-v3", device=self.device)

    def extract(
        self,
        video_path: str,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        cancel_event=None,
    ) -> List[Dict[str, Any]]:
        self._ensure_model()
        if self._fallback_whisper is not None:
            return self._fallback_whisper.extract(video_path, progress_cb, cancel_event)

        if not video_path or not Path(video_path).exists():
            return []

        if progress_cb:
            progress_cb(10, "Extracting 16kHz audio for FunASR...")

        wav_path = str(Path(video_path).with_suffix(".temp_funasr.wav"))
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            wav_path
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:
            if progress_cb:
                progress_cb(0, f"FFmpeg Audio Extraction Error: {e}")
            return []

        try:
            if progress_cb:
                progress_cb(35, f"Running FunASR ({self.model_name}) with timestamp alignment...")

            res = self.model.generate(
                input=wav_path,
                batch_size_s=300,
                hotword="",
            )

            results: List[Dict[str, Any]] = []
            seg_id = 1

            for item in res:
                if cancel_event and cancel_event.is_set():
                    break
                text = item.get("text", "").strip()
                timestamp = item.get("timestamp", [])
                if timestamp and len(timestamp) > 0:
                    for chunk in timestamp:
                        c_start = round(chunk[0] / 1000.0, 2)
                        c_end = round(chunk[1] / 1000.0, 2)
                        c_text = chunk[2] if len(chunk) > 2 else text
                        if c_text.strip():
                            results.append(SubtitleSegment(
                                id=seg_id,
                                start=c_start,
                                end=c_end,
                                text=c_text.strip(),
                                translated="",
                            ).to_dict())
                            seg_id += 1
                elif text:
                    results.append(SubtitleSegment(
                        id=seg_id,
                        start=0.0,
                        end=3.0,
                        text=text,
                        translated="",
                    ).to_dict())
                    seg_id += 1

            if progress_cb:
                progress_cb(90, f"FunASR extracted {len(results)} segments.")
            return results

        finally:
            Path(wav_path).unlink(missing_ok=True)
            self.unload()
