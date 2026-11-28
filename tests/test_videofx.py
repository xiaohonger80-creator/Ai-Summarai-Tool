# -*- coding: utf-8 -*-
"""
tests/test_videofx.py
Verification suite for VideoFX Studio & the 5 Production Modules:
  1. LUTEngine & 6 built-in presets + intensity blend
  2. TextAnimator UTF-8-SIG .ass subtitle script generation
  3. ShapeMasker & VideoFXCompositor filter_complex
  4. HardwareProfiler (NVENC/AMF/QSV/x264) & DependencyChecker (Setup & Models audit)
  5. ProjectManager (.vfxproj Save/Load) + SmartTTSCache (SHA-256 reuse on re-export)
  6. VoiceFXProcessor (normal, inner_thought, phone_call, radio) & BatchManager auto-splitter
"""

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.lut_engine import LUTEngine
from core.text_animator import TextAnimator
from core.masking.shape_masker import ShapeMasker
from core.masking.factory import MaskerFactory
from core.compositor import VideoFXCompositor
from core.cache_manager import SmartTTSCache
from core.project_manager import ProjectManager
from core.hardware_profiler import HardwareProfiler
from core.dependency_checker import DependencyChecker
from core.batch_manager import BatchManager
from core.recap_dubbing.voice_fx import VoiceFXProcessor


class TestVideoFXStudio(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="test_videofx_"))
        self.lut_engine = LUTEngine()
        self.compositor = VideoFXCompositor(lut_engine=self.lut_engine)

    def _create_dummy_wav(self, path: str, duration_sec: float = 0.5) -> str:
        sr = 44100
        n_frames = int(sr * duration_sec)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(b"\x00\x00" * n_frames)
        return path

    def test_01_lut_presets_exist(self):
        luts = self.lut_engine.get_available_luts()
        self.assertGreaterEqual(len(luts), 6)
        self.assertIn("Cinematic_Teal_Orange.cube", luts)
        self.assertIn("Kodak_Vintage_Film.cube", luts)

    def test_02_lut_filter_intensity(self):
        f100 = self.lut_engine.build_ffmpeg_filter("Cinematic_Teal_Orange.cube", intensity=1.0)
        self.assertIn("lut3d=", f100)
        f50 = self.lut_engine.build_ffmpeg_filter("Cinematic_Teal_Orange.cube", intensity=0.5)
        self.assertIn("lut3d=", f50)
        self.assertIn("blend=all_expr=", f50)

    def test_03_text_animator_all_modes(self):
        for mode in TextAnimator.ANIMATION_MODES:
            out_ass = str(self.tmp_dir / f"test_{abs(hash(mode))}.ass")
            path = TextAnimator.generate_ass_script(
                text_content="សួស្តីពិភពលោក Hello World",
                animation_mode=mode,
                video_duration_sec=10.0,
                out_ass_path=out_ass,
                width=1920,
                height=1080,
            )
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8-sig") as f:
                content = f.read()
                self.assertIn("[Script Info]", content)
                self.assertIn("[Events]", content)
                self.assertIn("Dialogue:", content)

    def test_04_shape_masker_filters(self):
        masker = ShapeMasker()
        f_blur = masker.build_ffmpeg_filter(
            input_label="0:v", output_label="out", width=1920, height=1080,
            params={"shape_type": "Subtitle Blur Box (បិទបាំងអក្សរក្រោម)", "blur_radius": 20}
        )
        self.assertIn("boxblur=", f_blur)
        self.assertIn("crop=", f_blur)

        f_vig = masker.build_ffmpeg_filter(
            input_label="0:v", output_label="out", width=1920, height=1080,
            params={"shape_type": "Cinematic Vignette (គែមងងឹត)"}
        )
        self.assertIn("vignette=", f_vig)

    def test_05_masker_factory_and_compositor(self):
        m_shape = MaskerFactory.create("Fast Shape & Blur Mask (FFmpeg)")
        self.assertIsInstance(m_shape, ShapeMasker)
        filter_str, stream = self.compositor.build_filter_complex(
            lut_name="Cinematic_Teal_Orange.cube",
            lut_intensity=0.8,
            mask_params={"enabled": True, "shape_type": "Subtitle Blur Box (បិទបាំងអក្សរក្រោម)", "blur_radius": 15},
            ass_path=str(self.tmp_dir / "nonexistent.ass"),
            video_w=1920,
            video_h=1080,
        )
        self.assertIn("lut3d=", filter_str)
        self.assertIn("boxblur=", filter_str)
        self.assertEqual(stream, "mask_out")

    def test_06_hardware_profiler_and_dependency_checker(self):
        hw = HardwareProfiler.detect_hardware()
        self.assertIn("best_encoder", hw)
        enc_args = HardwareProfiler.get_encoder_args()
        self.assertIn("-c:v", enc_args)

        low_cfg = HardwareProfiler.apply_performance_profile("low", {"sample_fps": 2.0})
        self.assertEqual(low_cfg["hardware_profile"], "low")
        self.assertEqual(low_cfg["sample_fps"], 0.5)

        dep_report = DependencyChecker.check_all()
        self.assertTrue(dep_report["ffmpeg"]["ok"])

    def test_07_vfxproj_save_load_and_smart_tts_cache(self):
        cache = SmartTTSCache(cache_dir=str(self.tmp_dir / "tts_cache"))
        dummy_wav = self._create_dummy_wav(str(self.tmp_dir / "sample.wav"))

        segs = [
            {"id": 1, "start": 0.0, "end": 2.5, "speaker": "SPEAKER_00", "voice_fx": "normal", "text": "第一句", "translated": "ប្រយោគទីមួយ"},
            {"id": 2, "start": 2.6, "end": 5.0, "speaker": "SPEAKER_01", "voice_fx": "inner_thought", "text": "第二句", "translated": "ប្រយោគទីពីរ"},
            {"id": 3, "start": 5.1, "end": 8.0, "speaker": "SPEAKER_00", "voice_fx": "phone_call", "text": "第三句", "translated": "ប្រយោគទីបី"},
        ]

        # 1. Populate cache for all 3 segments
        for s in segs:
            h, cpath = cache.store_audio(dummy_wav, s["translated"], s["speaker"], s["voice_fx"], "+0%")
            s["audio_hash"] = h
            s["dub_audio"] = cpath

        # 2. Save as .vfxproj (Ctrl+S simulation)
        proj_file = str(self.tmp_dir / "episode_01.vfxproj")
        saved_path = ProjectManager.save_project(
            project_file_path=proj_file,
            video_path="sample_movie.mp4",
            segments=segs,
            settings={"lut_enabled": True, "lut_preset": "Cinematic_Teal_Orange.cube"},
        )
        self.assertTrue(os.path.exists(saved_path))

        # 3. Reload .vfxproj and edit line 2's Khmer text
        loaded = ProjectManager.load_project(saved_path)
        reloaded_segs = loaded["segments"]
        self.assertEqual(len(reloaded_segs), 3)
        reloaded_segs[1]["translated"] = "ប្រយោគទីពីរ ដែលបានកែថ្មី!"

        # 4. Re-export check: lines 1 & 3 MUST be cache hits, line 2 MUST be a cache miss
        cache.hits = 0
        cache.misses = 0
        for s in reloaded_segs:
            hit_path = cache.get_cached_audio(s["translated"], s["speaker"], s["voice_fx"], "+0%")
            if s["id"] in (1, 3):
                self.assertIsNotNone(hit_path)
            else:
                self.assertIsNone(hit_path)
        self.assertEqual(cache.hits, 2)
        self.assertEqual(cache.misses, 1)

    def test_08_voice_fx_and_batch_manager(self):
        in_wav = self._create_dummy_wav(str(self.tmp_dir / "in_voice.wav"))
        for fx in ("normal", "inner_thought", "phone_call", "radio"):
            out_wav = str(self.tmp_dir / f"out_{fx}.wav")
            ok = VoiceFXProcessor.apply_voice_fx(in_wav, out_wav, voice_fx=fx)
            self.assertTrue(ok and os.path.exists(out_wav))

        bm = BatchManager(split_output_dir=str(self.tmp_dir / "splits"))
        self.assertEqual(len(bm.items), 0)


if __name__ == "__main__":
    unittest.main()
