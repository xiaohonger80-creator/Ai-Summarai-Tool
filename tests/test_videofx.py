# -*- coding: utf-8 -*-
"""
tests/test_videofx.py
Verification suite for VideoFX Studio components:
- LUTEngine & 6 built-in presets
- TextAnimator ASS subtitle script generation
- ShapeMasker FFmpeg filter syntax
- VideoFXCompositor unified filtergraph & single-frame preview
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.lut_engine import LUTEngine
from core.text_animator import TextAnimator
from core.masking.shape_masker import ShapeMasker
from core.masking.factory import MaskerFactory
from core.compositor import VideoFXCompositor


class TestVideoFXStudio(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="test_videofx_"))
        self.lut_engine = LUTEngine()
        self.compositor = VideoFXCompositor(lut_engine=self.lut_engine)

    def test_01_lut_presets_exist(self):
        luts = self.lut_engine.get_available_luts()
        self.assertGreaterEqual(len(luts), 6)
        self.assertIn("Cinematic_Teal_Orange.cube", luts)
        self.assertIn("Kodak_Vintage_Film.cube", luts)

    def test_02_lut_filter_intensity(self):
        # 100% intensity
        f100 = self.lut_engine.build_ffmpeg_filter("Cinematic_Teal_Orange.cube", intensity=1.0)
        self.assertIn("lut3d=", f100)
        # 50% intensity
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

    def test_05_masker_factory(self):
        m_shape = MaskerFactory.create("Fast Shape & Blur Mask (FFmpeg)")
        self.assertIsInstance(m_shape, ShapeMasker)

    def test_06_compositor_chain(self):
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


if __name__ == "__main__":
    unittest.main()
