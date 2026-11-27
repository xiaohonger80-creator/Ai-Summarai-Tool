# -*- coding: utf-8 -*-
"""
Ai Summarai — Deep Audit & Automated Stress Test Suite (tests/deep_test_suite.py)
=================================================================================
Self-contained end-to-end verification suite covering:
  1. Static AST syntax, imports, and Windows zero-console (CREATE_NO_WINDOW) audit
  2. SQLite database initialization + legacy schema migration + Series Profiles + API pool
  3. SubtitleOCRScanner edge-case resilience (empty dir, malformed boxes, normalized bbox)
  4. SpeechTranscriber edge-case resilience (empty/silent audio, inner_thought, phone_call, onset snap)
  5. ZHtoKHTranslator literal/recap modes, Multi-API 429 rotation/failover, Hook & Social Pack
  6. KhmerTTSEngine silence trimming, speed_mult + dynamic atempo (0.85x-1.90x), offline fallback
  7. MediaEngine 100 Khmer Subtitle Styles x 4 custom fonts x (16:9, 9:16, 1:1), Timed Auto-Blur,
     22 LUT presets, Logo, Hook Banner, Anti-Copyright (light/medium/strong), Vocal Remover,
     HD Clarity 1080p Upscaler, Intro/Outro Stitcher, Split Episodes, Viral 9:16 Shorts,
     GPU->CPU fallback, and 65-segment chunked audio mixing
  8. SFXEngine WAV synthesis & Emotion Auto-Matcher with smart ducking
  9. InAppPackageUpdater safe .zip extraction (Zip Slip & data/ user DB protection)
 10. PySide6 GUI & background QThread worker thread-safety / Stop-Cancel verification
"""

import ast
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class DeepTestRunner:
    def __init__(self):
        self.results = []
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="aisummarai_deep_test_"))
        self.fixtures = {}

    def run_test(self, name: str, fn):
        t0 = time.monotonic()
        try:
            detail = fn() or "OK"
            dt = time.monotonic() - t0
            self.results.append((name, True, f"{detail} ({dt:.2f}s)"))
            print(f"  [PASS] {name}: {detail} ({dt:.2f}s)")
        except Exception as exc:
            dt = time.monotonic() - t0
            import traceback
            tb = traceback.format_exc()
            self.results.append((name, False, f"{exc} ({dt:.2f}s)"))
            print(f"  [FAIL] {name}: {exc} ({dt:.2f}s)\n{tb}")

    def _ff(self, args):
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )

    def build_fixtures(self):
        td = self.tmp_dir
        vid_stereo = str(td / "fixture_stereo.mp4")
        vid_mono = str(td / "fixture_mono.mp4")
        vid_intro = str(td / "fixture_intro.mp4")
        vid_outro = str(td / "fixture_outro.mp4")
        wav_silent = str(td / "fixture_silent.wav")
        wav_empty = str(td / "fixture_empty.wav")
        wav_speech = str(td / "fixture_speech.wav")
        tts_wav = str(td / "fixture_tts.wav")
        logo_png = str(td / "fixture_logo.png")

        # 4s 640x360 stereo video (center 440Hz voice + stereo BGM L=220Hz R=330Hz)
        self._ff([
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
            "-f", "lavfi", "-i", "aevalsrc=0.4*sin(2*PI*440*t)+0.3*sin(2*PI*220*t)|0.4*sin(2*PI*440*t)+0.3*sin(2*PI*330*t):d=4:s=44100",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", vid_stereo,
        ])
        # 2s mono video
        self._ff([
            "-f", "lavfi", "-i", "color=c=navy:s=640x360:r=30:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-ac", "1", "-c:a", "aac", "-shortest", vid_mono,
        ])
        # 1.0s silent-stream intro (different resolution 480x270)
        self._ff([
            "-f", "lavfi", "-i", "color=c=darkred:s=480x270:r=24:d=1.0",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            vid_intro,
        ])
        # 1.0s outro with audio
        self._ff([
            "-f", "lavfi", "-i", "color=c=darkgreen:s=640x360:r=30:d=1.0",
            "-f", "lavfi", "-i", "sine=frequency=523:duration=1.0",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", vid_outro,
        ])
        # Silent 16kHz mono wav
        self._ff(["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1.5", "-acodec", "pcm_s16le", wav_silent])
        # 0-byte empty wav
        Path(wav_empty).write_bytes(b"")
        # Synthetic speech-like 16kHz mono wav (leading silence + 210Hz female tone + 115Hz male tone + silence)
        self._ff([
            "-f", "lavfi",
            "-i", "aevalsrc='between(t,0.25,1.2)*0.45*sin(2*PI*210*t)+between(t,1.6,2.7)*0.45*sin(2*PI*115*t)':d=3.0:s=16000",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_speech,
        ])
        # Synthetic 0.9s Khmer TTS wav
        self._ff(["-f", "lavfi", "-i", "sine=frequency=320:duration=0.9", "-ar", "44100", "-ac", "2", tts_wav])

        # Synthetic logo PNG via Qt QImage
        from PySide6.QtGui import QImage
        img = QImage(120, 60, QImage.Format_ARGB32)
        img.fill(0xFF00E5FF)
        img.save(logo_png, "PNG")

        self.fixtures = {
            "vid_stereo": vid_stereo,
            "vid_mono": vid_mono,
            "vid_intro": vid_intro,
            "vid_outro": vid_outro,
            "wav_silent": wav_silent,
            "wav_empty": wav_empty,
            "wav_speech": wav_speech,
            "tts_wav": tts_wav,
            "logo_png": logo_png,
        }

    # ------------------------------------------------------------------
    # PHASE 1: STATIC CODE, IMPORTS & ZERO-CONSOLE AUDIT
    # ------------------------------------------------------------------
    def test_static_ast_and_zero_console(self):
        py_files = [ROOT / "main.py"] + sorted((ROOT / "core").glob("*.py")) + sorted((ROOT / "ui").glob("*.py"))
        missing_flags = []
        for p in py_files:
            src = p.read_text(encoding="utf-8-sig")
            tree = ast.parse(src, filename=str(p))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("run", "Popen", "check_output", "check_call", "call"):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                            kws = {kw.arg for kw in node.keywords if kw.arg}
                            if "creationflags" not in kws:
                                missing_flags.append(f"{p.relative_to(ROOT)}:{node.lineno} ({node.func.attr})")
        assert not missing_flags, f"Subprocess calls missing creationflags: {missing_flags}"

        # Import every core and ui module (detects circular/broken imports)
        imported = 0
        for folder in ("core", "ui"):
            for p in sorted((ROOT / folder).glob("*.py")):
                if p.name == "__init__.py":
                    continue
                importlib.import_module(f"{folder}.{p.stem}")
                imported += 1
        return f"AST clean on {len(py_files)} files, {imported} modules imported, 0 missing CREATE_NO_WINDOW"

    # ------------------------------------------------------------------
    # PHASE 1B: DATABASE FRESH + LEGACY SCHEMA MIGRATION
    # ------------------------------------------------------------------
    def test_database_fresh_and_legacy(self):
        from core.database import Database

        # 1. Brand-new DB
        fresh_db = Database(self.tmp_dir / "fresh.db")
        pid = fresh_db.create_project("Ep01", self.fixtures["vid_stereo"], "voice")
        edits = fresh_db.get_project_edits(pid)
        required_edit_cols = (
            "sub_style", "sub_font_family", "mask_enabled", "mask_mode",
            "anti_copyright_enabled", "auto_timed_blur", "lut_preset",
            "keep_bgm_only", "hook_enabled", "intro_enabled", "outro_enabled",
            "hd_upscale_enabled", "hd_upscale_1080p", "series_profile_id",
        )
        for col in required_edit_cols:
            assert col in edits, f"Fresh DB missing project_edits.{col}"

        sp_id = fresh_db.save_series_profile(
            "TestSeries",
            default_voice_map={"speaker_voices": {"王总": "male"}},
            glossary=[{"src_term": "王总", "kh_term": "លោកប្រធានវ៉ាង", "category": "series"}],
            edits_preset={"burn_subs": 1},
            intro_path=self.fixtures["vid_intro"],
            outro_path=self.fixtures["vid_outro"],
        )
        assert fresh_db.get_series_profile(sp_id)["series_name"] == "TestSeries"
        fresh_db.save_studio_preset("TikTokPreset", {"aspect_ratio": "9:16"})
        assert any(p["name"] == "TikTokPreset" for p in fresh_db.get_studio_presets())
        assert fresh_db.set_api_keys("keyA\nkeyB\nkeyA") == 2 and fresh_db.get_api_keys() == ["keyA", "keyB"]
        fresh_db.close()

        # 2. Legacy ancient v1.0 DB migration test
        legacy_path = self.tmp_dir / "legacy_v1.db"
        raw = sqlite3.connect(str(legacy_path))
        raw.executescript("""
            CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, video_path TEXT, source_mode TEXT);
            CREATE TABLE segments (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, seq_index INTEGER, start_ms INTEGER, end_ms INTEGER, zh_text TEXT, kh_text TEXT, status TEXT);
            CREATE TABLE project_edits (project_id INTEGER PRIMARY KEY, logo_path TEXT DEFAULT '');
            INSERT INTO projects (name, video_path, source_mode) VALUES ('OldProj', 'old.mp4', 'voice');
            INSERT INTO segments (project_id, seq_index, start_ms, end_ms, zh_text, kh_text, status) VALUES (1, 1, 100, 1200, '你好', 'សួស្តី', 'Ready');
            INSERT INTO project_edits (project_id, logo_path) VALUES (1, '');
        """)
        raw.commit()
        raw.close()

        migrated = Database(legacy_path)
        seg_cols = {r[1] for r in migrated.conn.execute("PRAGMA table_info(segments)").fetchall()}
        for sc in ("voice_override", "tts_audio_path", "bbox_json"):
            assert sc in seg_cols, f"Legacy DB migration missing segments.{sc}"
        m_edits = migrated.get_project_edits(1)
        for col in required_edit_cols:
            assert col in m_edits, f"Legacy DB migration missing project_edits.{col}"
        tables = {r[0] for r in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for tbl in ("series_profiles", "studio_presets", "sfx_events", "glossary", "cloned_voices"):
            assert tbl in tables, f"Legacy DB migration missing table {tbl}"
        migrated.close()
        return "Fresh + Legacy v1.0 migration, series_profiles, studio_presets, API pool verified"

    # ------------------------------------------------------------------
    # PHASE 2A: OCR SCANNER STRESS TEST
    # ------------------------------------------------------------------
    def test_ocr_scanner(self):
        from core.ocr_scanner import SubtitleOCRScanner

        # Empty directory -> returns [] with zero crash
        empty_dir = self.tmp_dir / "empty_frames"
        empty_dir.mkdir(exist_ok=True)
        scanner = SubtitleOCRScanner.__new__(SubtitleOCRScanner)
        assert scanner.scan_frames(str(empty_dir), fps=2) == []

        # Malformed / empty polygon boxes -> zero IndexError
        txt_bad, box_bad = SubtitleOCRScanner._extract_ordered_text_and_bbox([([], "你好世界", 0.9)], frame_w=640, frame_h=180)
        assert "你好世界" in txt_bad and box_bad is None

        # Valid boxes -> ordered text + full-frame normalized bbox inside [0, 1]
        mock_out = [
            ([[100, 20], [320, 20], [320, 60], [100, 60]], "别走！", 0.95),
            ([[340, 22], [540, 22], [540, 62], [340, 62]], "听我解释！", 0.91),
        ]
        txt_ok, box_ok = SubtitleOCRScanner._extract_ordered_text_and_bbox(
            mock_out, frame_w=640, frame_h=180, crop_y_offset=0.72, crop_ratio=0.28
        )
        assert "别走" in txt_ok and "听我解释" in txt_ok
        assert box_ok and 0.0 <= box_ok["x"] <= 1.0 and 0.70 <= box_ok["y"] <= 1.0
        return f"Empty dir, malformed box guard, and bbox={box_ok} verified"

    # ------------------------------------------------------------------
    # PHASE 2B: SPEECH TRANSCRIBER STRESS TEST
    # ------------------------------------------------------------------
    def test_transcriber(self):
        from core.transcriber import SpeechTranscriber

        asr = SpeechTranscriber()
        # 1. Empty 0-byte & pure silent WAV -> returns [] gracefully without invoking Whisper crash
        assert asr.transcribe_local(self.fixtures["wav_empty"]) == []
        assert asr.transcribe_local(self.fixtures["wav_silent"]) == []

        # 2. Inner thought, phone call, female & male character detection + acoustic onset snapping
        segs = [
            {"start_ms": 0, "end_ms": 1350, "zh_text": "你好，请问你在哪里？", "voice_override": ""},
            {"start_ms": 1450, "end_ms": 2850, "zh_text": "你别管我！", "voice_override": ""},
            {"start_ms": 1500, "end_ms": 2200, "zh_text": "（心里暗想：他到底是谁？）", "voice_override": ""},
            {"start_ms": 1500, "end_ms": 2200, "zh_text": "喂，电话听得到吗？", "voice_override": ""},
            {"start_ms": 99999, "end_ms": 100500, "zh_text": "越界测试", "voice_override": ""},
        ]
        refined = asr.refine_speech_boundaries(self.fixtures["wav_speech"], segs)
        # Leading 250ms silence on segment 0 must be trimmed closer to acoustic onset!
        assert refined[0]["start_ms"] > 0, f"Onset snap did not trim dead silence: {refined[0]}"
        detected = asr.detect_character_from_wav(self.fixtures["wav_speech"], refined)
        assert detected[0]["voice_override"] == "female", f"Expected female 210Hz, got {detected[0]}"
        assert detected[1]["voice_override"] == "male", f"Expected male 115Hz, got {detected[1]}"
        assert detected[2]["voice_override"] == "inner_thought", f"Expected inner_thought, got {detected[2]}"
        assert detected[3]["voice_override"] == "phone_call", f"Expected phone_call, got {detected[3]}"
        return f"Empty/silent guard, RMS onset snap ({refined[0]['start_ms']}ms), and 4-role voice detection verified"

    # ------------------------------------------------------------------
    # PHASE 2C: TRANSLATOR, MULTI-API 429 FAILOVER & SOCIAL PACK
    # ------------------------------------------------------------------
    def test_translator_and_api_rotation(self):
        from core.translator import ZHtoKHTranslator, normalize_dub_khmer_text, DUBBING_SYSTEM_PROMPT, RECAP_SYSTEM_PROMPT

        tr_lit = ZHtoKHTranslator(api_key="k1\nk2\nk3", base_url="https://api.openai.com/v1", model="gpt-4o-mini", dub_style="literal")
        tr_rec = ZHtoKHTranslator(api_key="k1\nk2\nk3", base_url="https://api.openai.com/v1", model="gpt-4o-mini", dub_style="recap")
        assert tr_lit._get_system_prompt() == DUBBING_SYSTEM_PROMPT
        assert tr_rec._get_system_prompt() == RECAP_SYSTEM_PROMPT

        # Verify pure Khmer normalization & conversational polish (zero leaked Chinese)
        polished = tr_lit._polish_conversational_khmer("តើអ្នកជានរណា？（笑）សូមអភ័យទោស ខ្ញុំមិនដឹងទេ！")
        assert not any("\u4e00" <= c <= "\u9fff" for c in polished)
        assert "ឯងជាអ្នកណា" in polished and "សុំទោស" in polished and "អត់ដឹងទេ" in polished
        assert normalize_dub_khmer_text(polished) == polished

        # Verify Multi-API Key round-robin & instant 429 failover without dropping segments
        calls = []

        class _FakeResp:
            def __init__(self, status_code, text="", payload=None):
                self.status_code = status_code
                self.text = text
                self._payload = payload or {}
            def json(self):
                return self._payload

        def _mock_post(url, json=None, timeout=18):
            calls.append(url)
            if "key=AIzaKey1" in url:
                return _FakeResp(429, "RESOURCE_EXHAUSTED: quota exceeded")
            return _FakeResp(200, payload={
                "candidates": [{"content": {"parts": [{"text": '{"1": "ឈប់សិន! ឯងជាអ្នកណា?", "2": "ខ្ញុំអត់ដឹងទេ!"}'}]}}]
            })

        tr_gem = ZHtoKHTranslator(api_key="AIzaKey1\nAIzaKey2\nAIzaKey3", base_url="https://generativelanguage.googleapis.com", model="gemini-3.1-flash-lite")
        with patch.object(tr_gem._http, "post", side_effect=_mock_post):
            res = tr_gem._translate_chunk_gemini_direct([
                {"id": 1, "start_ms": 0, "end_ms": 1500, "zh_text": "站住！你是谁？"},
                {"id": 2, "start_ms": 1600, "end_ms": 2800, "zh_text": "我不知道！"},
            ])
        assert 1 in res and 2 in res and tr_gem.api_key != "AIzaKey1", f"Failover failed: res={res}, key={tr_gem.api_key}"

        # Viral hook, emotion classifier, and Social Pack (.txt + .json)
        tr_free = ZHtoKHTranslator(api_key="", base_url="google-free", model="google-free")
        segs = [
            {"id": 1, "start_ms": 0, "end_ms": 1500, "zh_text": "不可能！", "kh_text": "មិនអាចទេ! នាងគឺជាកូនស្រីមហាសេដ្ឋី!"},
            {"id": 2, "start_ms": 2000, "end_ms": 3500, "zh_text": "我爱你", "kh_text": "បងស្រឡាញ់អូនណាស់!"},
        ]
        hook = tr_free.generate_viral_hook(segs, episode_title="Ep01")
        emos = tr_free.classify_segment_emotions(segs)
        pack = tr_free.generate_social_pack(segs, video_name="Ep01")
        txt_p, json_p = tr_free.save_social_pack_files(pack, str(self.tmp_dir / "ep01_out.mp4"))
        assert hook and emos.get(1) == "dramatic_shock" and emos.get(2) == "romantic"
        assert Path(txt_p).exists() and Path(json_p).exists()
        return f"Literal/Recap, 429 failover ({len(calls)} calls -> {tr_gem.api_key}), emotions={emos}, SocialPack OK"

    # ------------------------------------------------------------------
    # PHASE 2D: KHMER TTS ENGINE (TRIM, ATEMPO 0.85x-1.90x, OFFLINE FALLBACK)
    # ------------------------------------------------------------------
    def test_tts_engine(self):
        from core.tts_engine import KhmerTTSEngine
        from core.media_engine import MediaEngine

        tts = KhmerTTSEngine()
        # 1. Mock synthesis writing a 1.8s audio clip with leading/trailing silence -> must compress cleanly into 750ms slot via atempo!
        def _fake_synth_mp3(text, voice, pitch, rate, out_mp3):
            self._ff([
                "-f", "lavfi",
                "-i", "aevalsrc='between(t,0.18,1.55)*0.5*sin(2*PI*380*t)':d=1.8:s=44100",
                "-c:a", "libmp3lame", "-b:a", "96k", out_mp3,
            ])

        out_fast = str(self.tmp_dir / "tts_fast_sync.wav")
        with patch.object(tts, "_synth_edge_tts", side_effect=_fake_synth_mp3):
            tts.generate_clip("ឈប់សិន! ឯងកំពុងធ្វើអីហ្នឹងលឿនឡើង!", "female", target_ms=750, out_wav=out_fast, speed_mult=1.15)
        assert Path(out_fast).exists() and Path(out_fast).stat().st_size > 2000
        dur_fast = MediaEngine.get_duration_ms(out_fast)
        assert 650 <= dur_fast <= 820, f"TTS overflowed 750ms slot: {dur_fast}ms"

        # 2. Simulated complete network drop -> must gracefully generate timed fallback clip with zero crash
        out_offline = str(self.tmp_dir / "tts_offline_fallback.wav")
        with patch.object(tts, "_synth_edge_tts", side_effect=ConnectionError("Network down")), \
             patch.object(tts, "_synth_google_khmer", side_effect=ConnectionError("Network down")):
            tts.generate_clip("សួស្តីអ្នកទាំងអស់គ្នា", "male", target_ms=900, out_wav=out_offline)
        assert Path(out_offline).exists() and Path(out_offline).stat().st_size > 2000
        dur_off = MediaEngine.get_duration_ms(out_offline)
        assert 800 <= dur_off <= 1000, f"Offline fallback clip wrong duration: {dur_off}ms"
        return f"Silence trim + dynamic atempo fit ({dur_fast}ms/750ms) + offline fallback ({dur_off}ms/900ms) verified"

    # ------------------------------------------------------------------
    # PHASE 3: 100 SUBTITLE STYLES x 4 FONTS x 3 RATIOS, 22 LUTS, TIMED BLUR & ANTI-COPYRIGHT
    # ------------------------------------------------------------------
    def test_100_sub_styles_luts_and_anti_copyright(self):
        from core.sub_styles import KHMER_SUB_STYLES
        from core.lut_presets import LUT_PRESETS
        from core.media_engine import MediaEngine

        assert len(KHMER_SUB_STYLES) == 100, f"Expected 100 subtitle styles, got {len(KHMER_SUB_STYLES)}"
        assert len(LUT_PRESETS) >= 20, f"Expected >=20 LUT presets, got {len(LUT_PRESETS)}"

        fonts = ["Khmer OS Battambang", "Khmer OS Muol Light", "Kantumruy Pro", "Noto Sans Khmer"]
        ratios = [(1920, 1080), (1080, 1920), (1080, 1080)]
        long_seg = [{
            "start_ms": 200, "end_ms": 2500,
            "kh_text": "ភាគទី១៖ នាងត្រូវគេមើលងាយគ្រប់គ្នា តែការពិតគឺជាកូនស្រីមហាសេដ្ឋីលំដាប់ពិភពលោក!",
        }]
        ass_test = str(self.tmp_dir / "style_audit.ass")
        for idx, style_key in enumerate(KHMER_SUB_STYLES.keys()):
            vw, vh = ratios[idx % len(ratios)]
            font_fam = fonts[idx % len(fonts)]
            MediaEngine.write_khmer_ass(
                long_seg, ass_test,
                {"sub_style": style_key, "sub_font_family": font_fam, "sub_font_size": 26, "sub_y": 0.85},
                vid_w=vw, vid_h=vh,
            )
            txt = Path(ass_test).read_text(encoding="utf-8-sig")
            assert "WrapStyle: 1" in txt and f",{font_fam}," in txt, f"Style {style_key} failed font/wrap check"
            m_min = max(24, int(round(vw * 0.08)))
            assert f",{m_min},{m_min}," in txt, f"Style {style_key} violated >=8% safe margins ({m_min})"

        # Validate ALL 22 LUT FFmpeg filter strings execute cleanly (0.1s null render)
        for lp in LUT_PRESETS:
            vf = lp.get("ffmpeg_vf", "")
            if not vf:
                continue
            self._ff(["-f", "lavfi", "-i", "color=c=gray:s=128x128:d=0.1", "-vf", vf, "-f", "null", "-"])

        # Validate Anti-Copyright light / medium / strong + Timed Auto-Blur in real FFmpeg
        ac_segs = [{"start_ms": 400, "end_ms": 1800, "zh_text": "测试字幕", "bbox_json": '{"x":0.1,"y":0.78,"w":0.8,"h":0.14}'}]
        for lvl in ("light", "medium", "strong"):
            out_ac = str(self.tmp_dir / f"ac_{lvl}.mp4")
            MediaEngine.apply_anti_copyright(
                self.fixtures["vid_stereo"], out_ac, level=lvl,
                mirror_flip=(lvl == "strong"), add_frame_border=(lvl == "medium"),
                auto_blur_chinese=True, auto_timed_blur=True, lut_preset="cinematic",
                segments=ac_segs,
            )
            assert Path(out_ac).exists() and Path(out_ac).stat().st_size > 5000
        return f"100/100 sub styles x 4 fonts x 3 ratios, {len(LUT_PRESETS)} LUTs, & 3 AC levels + Timed Blur verified"

    # ------------------------------------------------------------------
    # PHASE 4: EXPORT PIPELINE, VOCAL REMOVER, HD UPSCALE, STITCHER, SHORTS, CHUNKED MIX & CPU FALLBACK
    # ------------------------------------------------------------------
    def test_export_pipeline_and_stability(self):
        from core.media_engine import MediaEngine
        from core.long_video_engine import LongVideoStreamEngine
        from core.system_monitor import get_hardware_profile

        # 1. Hardware profile & GPU->CPU fallback builder
        hw = get_hardware_profile()
        assert hw["tier"] in ("low", "mid", "high") and hw["ffmpeg_threads"] >= 1
        enc = MediaEngine.detect_video_encoder()
        assert "-c:v" in enc
        fb = MediaEngine._build_cpu_fallback_cmd(["ffmpeg", "-i", "a.mp4", "-c:v", "h264_nvenc", "-preset", "p1", "-cq", "23", "out.mp4"])
        assert fb and "libx264" in fb and "h264_nvenc" not in fb

        # 2. Vocal Remover (Stereo + Mono)
        bgm_s = MediaEngine.extract_clean_bgm(self.fixtures["vid_stereo"], str(self.tmp_dir / "bgm_st.wav"))
        bgm_m = MediaEngine.extract_clean_bgm(self.fixtures["vid_mono"], str(self.tmp_dir / "bgm_mo.wav"))
        assert bgm_s and bgm_m and Path(bgm_s).stat().st_size > 10000 and Path(bgm_m).stat().st_size > 10000

        # 3. 65-segment chunked audio mixing stress test (chunk_size=50 -> tests multi-chunk merge!)
        many_segs = [
            {"id": i + 1, "start_ms": i * 50, "end_ms": i * 50 + 40, "tts_audio_path": self.fixtures["tts_wav"]}
            for i in range(65)
        ]
        mixed_65 = str(self.tmp_dir / "mixed_65.wav")
        MediaEngine._mix_audio_in_chunks(
            self.fixtures["vid_stereo"], many_segs, mixed_65,
            bgm_volume=0.30, chunk_size=50, auto_ducking=True, edits={"keep_bgm_only": 1}
        )
        assert Path(mixed_65).exists() and Path(mixed_65).stat().st_size > 20000

        # 4. Full-stack Single MP4 Render (Timed Blur + Burned ASS + Hook Banner + Logo + LUT + HD 1080p + Intro/Outro)
        segs = [
            {"id": 1, "start_ms": 300, "end_ms": 1700, "zh_text": "你好！", "kh_text": "សួស្តី! តើមានរឿងអីកើតឡើង?", "tts_audio_path": self.fixtures["tts_wav"], "bbox_json": '{"x":0.1,"y":0.78,"w":0.8,"h":0.14}'},
            {"id": 2, "start_ms": 1900, "end_ms": 3400, "zh_text": "快跑！", "kh_text": "រត់ឲ្យលឿនឡើង!", "tts_audio_path": self.fixtures["tts_wav"]},
        ]
        full_edits = {
            "burn_subs": 1, "sub_style": "tiktok_yellow_punch", "sub_font_family": "Kantumruy Pro",
            "logo_path": self.fixtures["logo_png"], "logo_x": 0.04, "logo_y": 0.16, "logo_scale": 0.15, "logo_opacity": 0.9,
            "hook_enabled": 1, "hook_text": "ភាគទី១៖ ការពិតដ៏ភ្ញាក់ផ្អើល!", "hook_pos": "top",
            "lut_preset": "vibrant", "anti_copyright_enabled": 1, "anti_copyright_level": "light",
            "auto_blur_chinese": 1, "auto_timed_blur": 1, "keep_bgm_only": 1,
            "hd_upscale_enabled": 1, "hd_upscale_1080p": 1,
            "intro_enabled": 1, "intro_path": self.fixtures["vid_intro"],
            "outro_enabled": 1, "outro_path": self.fixtures["vid_outro"],
        }
        full_mp4 = str(self.tmp_dir / "full_export.mp4")
        MediaEngine.render_final_video(
            self.fixtures["vid_stereo"], segs, full_mp4, bgm_volume=0.35, edits=full_edits, quality_preset="ultrafast"
        )
        f_dur, f_w, f_h = MediaEngine.probe_video_info(full_mp4)
        assert 5200 <= f_dur <= 7200 and f_w == 1920 and f_h == 1080, f"Full export mismatch: {f_dur}ms {f_w}x{f_h}"

        # 5. Split Episodes Export + Viral 9:16 Shorts Export
        split_dir = self.tmp_dir / "split_eps"
        split_out = MediaEngine.export_split_episodes(
            self.fixtures["vid_stereo"], segs,
            [{"index": 1, "name": "EP01", "start_ms": 0, "end_ms": 2000}, {"index": 2, "name": "EP02", "start_ms": 2000, "end_ms": 4000}],
            str(split_dir), edits={"burn_subs": 1, "anti_copyright_enabled": 0, "auto_blur_chinese": 0}, quality_preset="ultrafast",
        )
        assert len(split_out) == 2 and all(Path(p).exists() for p in split_out)

        shorts_dir = self.tmp_dir / "shorts_9x16"
        shorts_out = LongVideoStreamEngine.cut_viral_shorts(
            self.fixtures["vid_stereo"], segs, str(shorts_dir),
            edits={"burn_subs": 1, "anti_copyright_enabled": 0, "auto_blur_chinese": 0},
            max_clips=1, min_sec=2, max_sec=4,
        )
        assert len(shorts_out) == 1
        _, sw, sh = MediaEngine.probe_video_info(shorts_out[0])
        assert sw == 1080 and sh == 1920, f"Shorts not 9:16: {sw}x{sh}"
        return f"Full HD+Stitch ({f_dur}ms {f_w}x{f_h}), 65-seg chunk mix, 2 splits, 9:16 short ({sw}x{sh}), CPU fallback OK"

    # ------------------------------------------------------------------
    # PHASE 4B: SFX ENGINE & EMOTION AUTO-MATCHER
    # ------------------------------------------------------------------
    def test_sfx_engine(self):
        from core.database import Database
        from core.sfx_engine import SFXEngine

        for preset in ("boom", "heartbeat", "whoosh", "alert", "ding", "pop"):
            w = SFXEngine.get_preset_wav(preset)
            assert Path(w).exists() and Path(w).stat().st_size > 1000

        db = Database(self.tmp_dir / "sfx.db")
        pid = db.create_project("SFXTest", self.fixtures["vid_stereo"], "voice")
        db.insert_segments(pid, [
            {"start_ms": 200, "end_ms": 1200, "zh_text": "不可能！", "kh_text": "មិនអាចទេ! ការពិតគឺបែបនេះអ្ហ៎!"},
            {"start_ms": 1500, "end_ms": 2500, "zh_text": "救命！", "kh_text": "ជួយផង! រត់ឲ្យលឿន!"},
            {"start_ms": 2900, "end_ms": 3800, "zh_text": "我爱你", "kh_text": "បងស្រឡាញ់អូនជារៀងរហូត!"},
        ])
        placed = SFXEngine.auto_match_emotion_sfx(db.get_segments(pid), db, pid, min_gap_ms=800)
        assert len(placed) >= 2 and all(0.2 <= p["volume"] <= 0.55 for p in placed)
        db.close()
        return f"All 6 SFX WAVs synthesized & {len(placed)} ducked emotion SFX events inserted"

    # ------------------------------------------------------------------
    # PHASE 4C: IN-APP GITHUB UPDATER, URL PARSING & SAFE EXTRACTION
    # ------------------------------------------------------------------
    def test_updater_safe_extraction(self):
        from core.updater import InAppPackageUpdater, GITHUB_REPO_URL, GITHUB_MANIFEST_URL, get_updater_config

        # 1. Verify GitHub URL parsing, raw URL normalization & 0..9 decimal version rollover
        assert InAppPackageUpdater.bump_version("1.6.0") == "1.6.1"
        assert InAppPackageUpdater.bump_version("1.6.8") == "1.6.9"
        assert InAppPackageUpdater.bump_version("1.6.9") == "1.7.0"
        assert InAppPackageUpdater.bump_version("1.9.9") == "2.0.0"
        assert InAppPackageUpdater.bump_version("1.5.10") == "1.6.0"
        assert InAppPackageUpdater.parse_github_repo("https://github.com/xiaohonger80-creator/Ai-Summarai-Tool.git") == (
            "xiaohonger80-creator", "Ai-Summarai-Tool", "main"
        )
        assert InAppPackageUpdater.parse_github_repo(GITHUB_MANIFEST_URL) == (
            "xiaohonger80-creator", "Ai-Summarai-Tool", "main"
        )
        raw_conv = InAppPackageUpdater.normalize_github_raw_url(
            "https://github.com/xiaohonger80-creator/Ai-Summarai-Tool/blob/main/release_output/AiSummarai_Update.zip"
        )
        assert raw_conv == "https://raw.githubusercontent.com/xiaohonger80-creator/Ai-Summarai-Tool/main/release_output/AiSummarai_Update.zip"

        # 2. Verify active config uses GitHub (migrated away from Google Drive)
        cfg = get_updater_config()
        assert cfg["update_provider"] == "github" and "github.com" in cfg["github_repo_url"]
        assert "drive.google.com" not in cfg["manifest_url"]

        # 3. Verify GitHub manifest update detection (mocked v9.9.9 > current)
        fake_manifest = json.dumps({
            "version": "9.9.9",
            "release_date": "2026-11-27",
            "download_url": raw_conv,
            "changelog": "• GitHub update test",
        }).encode("utf-8")
        with patch.object(InAppPackageUpdater, "_http_get_bytes", return_value=fake_manifest):
            upd = InAppPackageUpdater.check_for_updates(GITHUB_REPO_URL)
        assert upd and upd["has_update"] is True and upd["remote_version"] == "9.9.9"

        # 4. Verify safe .zip extraction (GitHub archive unwrap + data/ protection + admin_keygen block + Zip Slip)
        pkg_zip = self.tmp_dir / "mock_github_update.zip"
        with zipfile.ZipFile(pkg_zip, "w") as zf:
            zf.writestr("Ai-Summarai-Tool-main/core/new_module.py", "# safe code update\n")
            zf.writestr("Ai-Summarai-Tool-main/data/dub_studio.db", "MALICIOUS_OVERWRITE")
            zf.writestr("Ai-Summarai-Tool-main/admin_keygen.py", "SHOULD_NOT_EXTRACT")
            zf.writestr("data/user_secret.db", "MALICIOUS_ROOT_DATA")
            zf.writestr("../zip_slip_escape.txt", "MALICIOUS_ESCAPE")

        ext_dir = self.tmp_dir / "updater_extract"
        src_root = InAppPackageUpdater.extract_package_safe(pkg_zip, ext_dir)
        assert (src_root / "core" / "new_module.py").exists(), "Valid code file was not extracted"
        assert not (src_root / "data").exists(), "data/ directory was NOT stripped!"
        assert not (src_root / "admin_keygen.py").exists(), "admin_keygen.py was NOT blocked!"
        assert not (ext_dir / "data").exists(), "Root data/ directory was NOT stripped!"
        assert not (self.tmp_dir / "zip_slip_escape.txt").exists(), "Zip Slip path traversal was NOT blocked!"
        return "GitHub parser, manifest check, archive unwrap, data/ + admin_keygen + Zip Slip guards OK"

    # ------------------------------------------------------------------
    # PHASE 4D: PYSIDE6 UI & QTHREAD CANCEL/STOP SAFETY
    # ------------------------------------------------------------------
    def test_ui_and_worker_thread_safety(self):
        from PySide6.QtWidgets import QApplication
        from ui.main_window import PipelineWorker, MainWindow, SettingsDialog
        from ui.multi_clip_dialog import MultiClipComposerDialog
        from core.database import Database

        app = QApplication.instance() or QApplication([])

        # Verify PipelineWorker emits progress & honors Stop/Cancel interruption cleanly
        progress_seen = []
        stopped_seen = []

        def _cancellable_task(emit):
            for step in range(20):
                emit(step * 5, f"Step {step}")
                time.sleep(0.02)
            return "Finished"

        w = PipelineWorker(_cancellable_task)
        w.progress.connect(lambda p, m: progress_seen.append(p))
        w.stopped.connect(lambda m: stopped_seen.append(m))
        w.start()
        time.sleep(0.06)
        w.requestInterruption()
        assert w.wait(3000), "PipelineWorker failed to stop promptly!"
        app.processEvents()
        assert len(progress_seen) >= 1 and len(stopped_seen) >= 1, f"Cancel signal missing: prog={progress_seen}, stop={stopped_seen}"

        # Verify MainWindow, SettingsDialog, MultiClipComposerDialog & WorkflowViewDialog instantiate cleanly
        from ui.workflow_view import WorkflowViewDialog
        db = Database(self.tmp_dir / "ui_test.db")
        win = MainWindow()
        win.show()
        sd = SettingsDialog(db, "kh")
        sd.show()
        mcd = MultiClipComposerDialog("kh", has_active_project=True)
        mcd.show()
        wf = WorkflowViewDialog(lang="kh")
        wf.sync_project_snapshot("Ep01.mp4", "1080p", 20, 20, 15, "LUT:drama_glow • TimedBlur")
        wf.on_stage_started("dub", "Generating Khmer TTS 16/20...")
        wf.on_stage_progress(80, "Generating Khmer TTS 16/20...", "dub")
        wf.on_stage_finished("Dubbing complete!", "dub")
        wf.set_view_mode(1, False)
        wf.set_view_mode(2, False)
        wf.set_view_mode(0, True)
        wf.set_view_mode(0, False)
        wf.show()
        app.processEvents()
        wf.close()
        sd.close()
        mcd.close()
        win.close()
        app.processEvents()
        wf.deleteLater()
        sd.deleteLater()
        mcd.deleteLater()
        win.deleteLater()
        app.processEvents()
        db.close()
        return f"QThread progress ({len(progress_seen)} events) + Stop cancel + MainWindow/Dialogs/WorkflowView clean"

    def run_all(self) -> bool:
        print("=" * 72)
        print("  Ai Summarai — Deep Audit & Automated Stress Test Suite")
        print("=" * 72)
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])
        try:
            self.build_fixtures()
            self.run_test("1. Static AST, Imports & Zero-Console Audit", self.test_static_ast_and_zero_console)
            self.run_test("2. SQLite Fresh + Legacy v1.0 Migration", self.test_database_fresh_and_legacy)
            self.run_test("3. SubtitleOCRScanner Stress & Edge Cases", self.test_ocr_scanner)
            self.run_test("4. SpeechTranscriber VAD/Onset & 4-Role Voices", self.test_transcriber)
            self.run_test("5. ZHtoKHTranslator, 429 Failover & Social Pack", self.test_translator_and_api_rotation)
            self.run_test("6. KhmerTTSEngine Trim, Atempo & Offline Fallback", self.test_tts_engine)
            self.run_test("7. 100 Sub Styles, 22 LUTs, Timed Blur & Anti-CR", self.test_100_sub_styles_luts_and_anti_copyright)
            self.run_test("8. Export, Vocal Remover, HD 1080p, Stitch, Shorts", self.test_export_pipeline_and_stability)
            self.run_test("9. SFXEngine WAV Synthesis & Emotion Auto-Matcher", self.test_sfx_engine)
            self.run_test("10. InAppPackageUpdater Safe Extraction & Data Guard", self.test_updater_safe_extraction)
            self.run_test("11. PySide6 UI & QThread Worker Cancel Safety", self.test_ui_and_worker_thread_safety)
        finally:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print("\n" + "=" * 72)
        print(f"  FINAL REPORT: {passed}/{total} PASSED ({'100% GREEN' if passed == total else 'FAILURES DETECTED'})")
        print("=" * 72)
        return passed == total


if __name__ == "__main__":
    ok = DeepTestRunner().run_all()
    sys.exit(0 if ok else 1)
