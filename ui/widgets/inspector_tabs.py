# -*- coding: utf-8 -*-
"""
ui/widgets/inspector_tabs.py
3-Tab Inspector Panel auto-populated from `EngineRegistry`:
  - Smart Workflow Preset Bar at top of Tab 1 & Tab 2
  - Tab 1: Extract & Translate (FunASR, WhisperX, PaddleOCR, Hybrid, whisper.cpp)
  - Tab 2: Story Recap & Dubbing (Demucs, UVR5, FFmpeg + Edge-TTS, Khmer-XTTS, GPT-SoVITS, Fish-Speech, Meta MMS-TTS)
    + Progressive-Disclosure Voice Cloning & Emotion Strip (`Reference Voice .wav`, `Reference Transcript`, `[normal]`, `[whisper]`, `[laughing]`, `[angry]`, `[sad]`)
  - Tab 3: Text FX, Mask & LUTs
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, Any
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QComboBox, QPushButton, QCheckBox, QSlider,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QFileDialog, QColorDialog
)

from core.engine_registry import EngineRegistry
from core.translators.providers import UnifiedLLMClient
from core.videofx.lut_engine import LUTEngine
from core.recap_dubbing.tts_dubber import TTSDubber


class InspectorTabs(QTabWidget):
    """
    Right-hand 3-Tab Inspector Panel managing all selectable engines from EngineRegistry
    with Progressive-Disclosure Voice Cloning & Emotion Tag controls.
    """

    settings_changed = Signal(dict)
    speaker_mapper_requested = Signal()
    emotion_tag_selected = Signal(str)  # Emits emotion tag ("normal", "whisper", "laughing", "angry", "sad")

    def __init__(self, initial_settings: Dict[str, Any] = None, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(335)
        self._settings = dict(initial_settings or {})
        self.lut_engine = LUTEngine()
        self._text_color = self._settings.get("text_color", "#FFFFFF")
        self._outline_color = self._settings.get("outline_color", "#000000")
        self._active_emotion = self._settings.get("active_emotion_tag", "normal")
        self._preview_player = QMediaPlayer(self)
        self._preview_audio = QAudioOutput(self)
        self._preview_player.setAudioOutput(self._preview_audio)

        self.addTab(self._build_tab1_extract_translate(), "1. Extract & Translate")
        self.addTab(self._build_tab2_recap_dubbing(), "2. Recap & Dubbing")
        self.addTab(self._build_tab3_videofx_luts(), "3. Text FX, Mask & LUTs")

        # Sync initial progressive-disclosure state
        self._update_voice_clone_subpanel_visibility()

    # ------------------------------------------------------------------
    # TAB 1: EXTRACT & TRANSLATE
    # ------------------------------------------------------------------
    def _build_tab1_extract_translate(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # Smart Workflow Preset Selector (Auto-configures all 4 categories in 1 click)
        grp_preset = QGroupBox("Smart Workflow Preset (1-Click Auto-Config)")
        f_preset = QFormLayout(grp_preset)
        f_preset.setSpacing(6)
        self.combo_smart_preset = QComboBox()
        self.combo_smart_preset.addItems(EngineRegistry.list_smart_presets())
        self._select_combo_text(
            self.combo_smart_preset,
            self._settings.get("smart_workflow_preset", EngineRegistry.list_smart_presets()[0]),
        )
        self.combo_smart_preset.currentTextChanged.connect(self.apply_workflow_preset)
        f_preset.addRow("Preset:", self.combo_smart_preset)
        layout.addWidget(grp_preset)

        grp_ext = QGroupBox("Category 1: Speech && Hard-Subtitle Extraction")
        f_ext = QFormLayout(grp_ext)
        f_ext.setSpacing(8)

        self.combo_extractor = QComboBox()
        self.combo_extractor.addItems(EngineRegistry.list_engines("extraction"))
        self._select_combo_text(self.combo_extractor, self._settings.get("extraction_engine", "Hybrid (OCR Primary + ASR Check)"))
        self.combo_extractor.currentIndexChanged.connect(self._emit_changed)
        f_ext.addRow("Extractor:", self.combo_extractor)
        layout.addWidget(grp_ext)

        grp_tr = QGroupBox("Category 4: Context-Aware AI Translation")
        f_tr = QFormLayout(grp_tr)
        f_tr.setSpacing(8)

        self.combo_strategy = QComboBox()
        self.combo_strategy.addItems(EngineRegistry.list_engines("translation"))
        self._select_combo_text(self.combo_strategy, self._settings.get("translation_strategy", ""))
        self.combo_strategy.currentIndexChanged.connect(self._emit_changed)
        f_tr.addRow("Strategy:", self.combo_strategy)

        self.combo_provider = QComboBox()
        self.combo_provider.addItems([
            "100% Local Offline (Ollama)",
            "Cloud API (Gemini / OpenAI)",
        ])
        self._select_combo_text(self.combo_provider, self._settings.get("ai_provider", ""))
        self.combo_provider.currentIndexChanged.connect(self._emit_changed)
        f_tr.addRow("AI Provider:", self.combo_provider)

        model_row = QHBoxLayout()
        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        self.combo_model.addItems(["qwen2.5:7b", "qwen2.5:14b", "gemma2:9b", "llama3.2:3b", "gemini-2.5-flash", "google-free", "gpt-4o-mini"])
        self.combo_model.setCurrentText(self._settings.get("model_name", "qwen2.5:7b"))
        self.combo_model.currentTextChanged.connect(self._emit_changed)
        model_row.addWidget(self.combo_model, 1)

        self.btn_refresh_ollama = QPushButton("Refresh Ollama")
        self.btn_refresh_ollama.clicked.connect(self._on_refresh_ollama)
        model_row.addWidget(self.btn_refresh_ollama)
        f_tr.addRow("Model:", model_row)

        self.combo_target_lang = QComboBox()
        self.combo_target_lang.addItems([
            "Khmer (ភាសាខ្មែរ)",
            "English",
            "Chinese",
            "Thai",
            "Vietnamese",
        ])
        self._select_combo_text(self.combo_target_lang, self._settings.get("target_language", "Khmer (ភាសាខ្មែរ)"))
        self.combo_target_lang.currentIndexChanged.connect(self._emit_changed)
        f_tr.addRow("Target Lang:", self.combo_target_lang)

        layout.addWidget(grp_tr)
        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # TAB 2: STORY RECAP & DUBBING (+ PROGRESSIVE-DISCLOSURE VOICE CLONE)
    # ------------------------------------------------------------------
    def _build_tab2_recap_dubbing(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        grp_mode = QGroupBox("Production Mode && Anti-Copyright")
        f_mode = QFormLayout(grp_mode)
        f_mode.setSpacing(6)

        self.combo_dub_mode = QComboBox()
        self.combo_dub_mode.addItems([
            "Disabled (Subtitles Only)",
            "AI Movie Dubbing (Replace Dialogue)",
            "AI Story Recap (Auto Scene Cut + Narration)",
        ])
        self._select_combo_text(self.combo_dub_mode, self._settings.get("dub_mode", "AI Movie Dubbing (Replace Dialogue)"))
        self.combo_dub_mode.currentIndexChanged.connect(self._emit_changed)
        f_mode.addRow("Mode:", self.combo_dub_mode)

        self.chk_scene_cut = QCheckBox("PySceneDetect Auto-Cut Scenes")
        self.chk_scene_cut.setChecked(bool(self._settings.get("scene_auto_cut", False)))
        self.chk_scene_cut.toggled.connect(self._emit_changed)
        f_mode.addRow("", self.chk_scene_cut)

        ac_row = QHBoxLayout()
        self.chk_mirror = QCheckBox("Mirror Flip")
        self.chk_mirror.setChecked(bool(self._settings.get("anti_cr_mirror", False)))
        self.chk_mirror.toggled.connect(self._emit_changed)
        ac_row.addWidget(self.chk_mirror)

        self.chk_zoom = QCheckBox("Micro-Zoom (1.05x)")
        self.chk_zoom.setChecked(bool(self._settings.get("anti_cr_zoom", True)))
        self.chk_zoom.toggled.connect(self._emit_changed)
        ac_row.addWidget(self.chk_zoom)
        f_mode.addRow("Anti-CR:", ac_row)

        self.spin_recap_dur = QDoubleSpinBox()
        self.spin_recap_dur.setRange(0.5, 30.0)
        self.spin_recap_dur.setSingleStep(0.5)
        self.spin_recap_dur.setSuffix(" min")
        self.spin_recap_dur.setValue(float(self._settings.get("recap_target_minutes", 3.0)))
        self.spin_recap_dur.valueChanged.connect(self._emit_changed)
        f_mode.addRow("Recap Length:", self.spin_recap_dur)
        layout.addWidget(grp_mode)

        grp_audio = QGroupBox("Category 2 && 3: Stem Separation && AI Dubbing")
        f_audio = QFormLayout(grp_audio)
        f_audio.setSpacing(6)

        self.combo_vocal = QComboBox()
        self.combo_vocal.addItems(EngineRegistry.list_engines("separation"))
        self._select_combo_text(self.combo_vocal, self._settings.get("vocal_removal_engine", "FFmpeg Vocal Suppression"))
        self.combo_vocal.currentIndexChanged.connect(self._emit_changed)
        f_audio.addRow("Vocal / BGM:", self.combo_vocal)

        self.combo_tts = QComboBox()
        self.combo_tts.addItems(EngineRegistry.list_engines("dubbing"))
        self._select_combo_text(self.combo_tts, self._settings.get("tts_engine", "Edge-TTS (Fast Online/Fallback)"))
        self.combo_tts.currentIndexChanged.connect(self._on_tts_engine_changed)
        f_audio.addRow("TTS Engine:", self.combo_tts)

        self.chk_rate_sync = QCheckBox("Auto Speech-Rate Sync (FFmpeg rubberband / atempo)")
        self.chk_rate_sync.setChecked(bool(self._settings.get("auto_rate_sync", True)))
        self.chk_rate_sync.toggled.connect(self._emit_changed)
        f_audio.addRow("", self.chk_rate_sync)

        self.btn_speaker_voices = QPushButton("🎙️ Speaker Voices... (Multi-Speaker & Roles)")
        self.btn_speaker_voices.clicked.connect(self.speaker_mapper_requested.emit)
        f_audio.addRow("Role Map:", self.btn_speaker_voices)

        layout.addWidget(grp_audio)

        # --------------------------------------------------------------
        # Progressive-Disclosure Voice Cloning & Emotion Strip Sub-Panel
        # (Revealed automatically when GPT-SoVITS, Fish-Speech, or Khmer-XTTS is active)
        # --------------------------------------------------------------
        self.voice_clone_subpanel = QGroupBox("🧬 Zero-Shot Voice Cloning && Emotion Cues")
        vc_layout = QVBoxLayout(self.voice_clone_subpanel)
        vc_layout.setSpacing(6)

        ref_form = QFormLayout()
        ref_form.setSpacing(5)

        wav_row = QHBoxLayout()
        self.edit_ref_voice = QLineEdit(str(self._settings.get("ref_voice_wav", "")))
        self.edit_ref_voice.setPlaceholderText("Drop or browse 5-10s Reference Voice (.wav)...")
        self.edit_ref_voice.textChanged.connect(self._emit_changed)
        wav_row.addWidget(self.edit_ref_voice, 1)

        self.btn_browse_ref_wav = QPushButton("Browse .wav")
        self.btn_browse_ref_wav.clicked.connect(self._on_browse_ref_wav)
        wav_row.addWidget(self.btn_browse_ref_wav)

        self.btn_test_clone_voice = QPushButton("▶ Test Voice")
        self.btn_test_clone_voice.clicked.connect(self._on_test_clone_voice)
        wav_row.addWidget(self.btn_test_clone_voice)
        ref_form.addRow("Ref Voice:", wav_row)

        self.edit_ref_transcript = QLineEdit(str(self._settings.get("ref_voice_transcript", "")))
        self.edit_ref_transcript.setPlaceholderText("Optional reference transcript (for GPT-SoVITS / F5-TTS alignment)...")
        self.edit_ref_transcript.textChanged.connect(self._emit_changed)
        ref_form.addRow("Ref Text:", self.edit_ref_transcript)
        vc_layout.addLayout(ref_form)

        # Quick Emotion Tag Pills
        em_row = QHBoxLayout()
        em_row.setSpacing(4)
        em_row.addWidget(QLabel("Emotion:"))
        self.emotion_buttons: Dict[str, QPushButton] = {}
        for em_tag in EngineRegistry.EMOTION_TAGS:
            btn = QPushButton(f"[{em_tag}]")
            btn.setCheckable(True)
            btn.setChecked(em_tag == self._active_emotion)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda _c=False, tag=em_tag: self._on_emotion_pill_clicked(tag))
            self.emotion_buttons[em_tag] = btn
            em_row.addWidget(btn)
        vc_layout.addLayout(em_row)

        layout.addWidget(self.voice_clone_subpanel)
        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # TAB 3: TEXT FX, MASK & LUTS
    # ------------------------------------------------------------------
    def _build_tab3_videofx_luts(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # 1. Animated Text FX
        grp_txt = QGroupBox("Animated Text && Hardsub Cover")
        f_txt = QFormLayout(grp_txt)
        f_txt.setSpacing(6)

        self.chk_text_fx = QCheckBox("Enable Animated Text / Subtitles")
        self.chk_text_fx.setChecked(bool(self._settings.get("text_fx_enabled", True)))
        self.chk_text_fx.toggled.connect(self._emit_changed)
        f_txt.addRow("", self.chk_text_fx)

        self.combo_text_style = QComboBox()
        self.combo_text_style.addItems([
            "Horizontal Scrolling Marquee",
            "Vertical Credits Roll",
            "Kinetic Pop-In",
            "Static Styled Subtitles",
        ])
        self._select_combo_text(self.combo_text_style, self._settings.get("text_fx_style", "Static Styled Subtitles"))
        self.combo_text_style.currentIndexChanged.connect(self._emit_changed)
        f_txt.addRow("Style:", self.combo_text_style)

        self.chk_bottom_box = QCheckBox("Bottom Hardsub Cover Box")
        self.chk_bottom_box.setChecked(bool(self._settings.get("bottom_cover_box", True)))
        self.chk_bottom_box.toggled.connect(self._emit_changed)
        f_txt.addRow("", self.chk_bottom_box)

        font_row = QHBoxLayout()
        self.combo_font = QComboBox()
        self.combo_font.addItems(["Noto Sans Khmer", "Khmer OS Battambang", "Khmer OS Muol Light", "Microsoft YaHei", "Arial"])
        self._select_combo_text(self.combo_font, self._settings.get("font_family", "Noto Sans Khmer"))
        self.combo_font.currentIndexChanged.connect(self._emit_changed)
        font_row.addWidget(self.combo_font, 1)

        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(18, 120)
        self.spin_font_size.setValue(int(self._settings.get("font_size", 46)))
        self.spin_font_size.valueChanged.connect(self._emit_changed)
        font_row.addWidget(self.spin_font_size)

        self.btn_text_color = QPushButton("Color")
        self.btn_text_color.clicked.connect(self._pick_text_color)
        font_row.addWidget(self.btn_text_color)
        f_txt.addRow("Font:", font_row)
        layout.addWidget(grp_txt)

        # 2. Video Masking
        grp_mask = QGroupBox("AI && Geometric Video Masking")
        f_mask = QFormLayout(grp_mask)
        f_mask.setSpacing(6)

        self.chk_mask = QCheckBox("Enable Video Masking")
        self.chk_mask.setChecked(bool(self._settings.get("mask_enabled", False)))
        self.chk_mask.toggled.connect(self._emit_changed)
        f_mask.addRow("", self.chk_mask)

        self.combo_mask_engine = QComboBox()
        self.combo_mask_engine.addItems([
            "AI Human Matting - RobustVideoMatting",
            "AI Object Cutout - rembg",
            "Shape Mask - Portrait/Circle",
            "Shape Mask - Split Screen",
        ])
        self._select_combo_text(self.combo_mask_engine, self._settings.get("mask_engine", "Shape Mask - Portrait/Circle"))
        self.combo_mask_engine.currentIndexChanged.connect(self._emit_changed)
        f_mask.addRow("Mask Engine:", self.combo_mask_engine)

        self.combo_bg_mode = QComboBox()
        self.combo_bg_mode.addItems(["Blur BG", "Custom Image/Video", "Green Screen"])
        self._select_combo_text(self.combo_bg_mode, self._settings.get("mask_bg_mode", "Blur BG"))
        self.combo_bg_mode.currentIndexChanged.connect(self._emit_changed)
        f_mask.addRow("Background:", self.combo_bg_mode)
        layout.addWidget(grp_mask)

        # 3. 3D Color LUTs
        grp_lut = QGroupBox("3D Color LUT Grading (.cube)")
        f_lut = QFormLayout(grp_lut)
        f_lut.setSpacing(6)

        self.chk_lut = QCheckBox("Enable 3D LUT Grading")
        self.chk_lut.setChecked(bool(self._settings.get("lut_enabled", False)))
        self.chk_lut.toggled.connect(self._emit_changed)
        f_lut.addRow("", self.chk_lut)

        lut_row = QHBoxLayout()
        self.combo_lut = QComboBox()
        self.combo_lut.addItems(self.lut_engine.get_available_luts())
        self._select_combo_text(self.combo_lut, self._settings.get("lut_preset", "Cinematic_Teal_Orange.cube"))
        self.combo_lut.currentIndexChanged.connect(self._emit_changed)
        lut_row.addWidget(self.combo_lut, 1)

        self.btn_import_lut = QPushButton("Import .cube")
        self.btn_import_lut.clicked.connect(self._on_import_cube)
        lut_row.addWidget(self.btn_import_lut)
        f_lut.addRow("LUT Preset:", lut_row)

        int_row = QHBoxLayout()
        self.slider_lut = QSlider(Qt.Horizontal)
        self.slider_lut.setRange(0, 100)
        self.slider_lut.setValue(int(self._settings.get("lut_intensity", 80)))
        self.slider_lut.valueChanged.connect(self._on_lut_slider_changed)
        int_row.addWidget(self.slider_lut, 1)

        self.lbl_lut_pct = QLabel(f"{self.slider_lut.value()}%")
        self.lbl_lut_pct.setFixedWidth(38)
        int_row.addWidget(self.lbl_lut_pct)
        f_lut.addRow("Intensity:", int_row)

        layout.addWidget(grp_lut)
        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Progressive-Disclosure & Event Handlers
    # ------------------------------------------------------------------
    def _on_tts_engine_changed(self, *_args) -> None:
        self._update_voice_clone_subpanel_visibility()
        self._emit_changed()

    def _update_voice_clone_subpanel_visibility(self) -> None:
        engine_txt = self.combo_tts.currentText()
        is_cloning = EngineRegistry.is_voice_cloning_engine(engine_txt)
        self.voice_clone_subpanel.setVisible(is_cloning)

    def _on_browse_ref_wav(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Reference Voice Sample (5-10s .wav)",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.m4a);;All Files (*.*)",
        )
        if path and os.path.exists(path):
            self.edit_ref_voice.setText(str(Path(path).resolve()))
            self._emit_changed()

    def _on_test_clone_voice(self) -> None:
        tmp_wav = str(Path(tempfile.gettempdir()) / "preview_clone_voice.wav")
        dubber = TTSDubber(
            engine_name=self.combo_tts.currentText(),
            ref_voice_wav=self.edit_ref_voice.text().strip(),
            ref_voice_transcript=self.edit_ref_transcript.text().strip(),
        )
        ok = dubber.synthesize(
            text="សួស្តី! នេះគឺជាការសាកល្បងសំឡេងក្លូន និងអារម្មណ៍តួអង្គក្នុងកម្មវិធី Ai Summarai។",
            voice_cfg={"voice": "km-KH-SreymomNeural"},
            out_wav_path=tmp_wav,
            target_ms=2600,
            ref_audio_path=self.edit_ref_voice.text().strip(),
            emotion_tag=self._active_emotion,
        )
        dubber.unload()
        if ok and os.path.exists(tmp_wav):
            self._preview_player.setSource(QUrl.fromLocalFile(tmp_wav))
            self._preview_player.play()

    def _on_emotion_pill_clicked(self, emotion_tag: str) -> None:
        self._active_emotion = emotion_tag
        for tag, btn in self.emotion_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(tag == emotion_tag)
            btn.blockSignals(False)
        self.emotion_tag_selected.emit(emotion_tag)
        self._emit_changed()

    @staticmethod
    def _select_combo_text(combo: QComboBox, text: str) -> None:
        if not text:
            return
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _on_refresh_ollama(self) -> None:
        models = UnifiedLLMClient.list_ollama_models(self._settings.get("ollama_url", "http://localhost:11434"))
        cur = self.combo_model.currentText()
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItems(models)
        self.combo_model.setCurrentText(cur or (models[0] if models else "qwen2.5:7b"))
        self.combo_model.blockSignals(False)
        self._emit_changed()

    def _pick_text_color(self) -> None:
        col = QColorDialog.getColor(QColor(self._text_color), self, "Select Subtitle Color")
        if col.isValid():
            self._text_color = col.name().upper()
            self._emit_changed()

    def _on_import_cube(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import 3D .cube LUT", "", "Cube LUT (*.cube)")
        if path:
            imported = self.lut_engine.import_lut(path)
            if imported:
                self.combo_lut.blockSignals(True)
                self.combo_lut.clear()
                self.combo_lut.addItems(self.lut_engine.get_available_luts())
                self.combo_lut.blockSignals(False)
                self._emit_changed()

    def _on_lut_slider_changed(self, val: int) -> None:
        self.lbl_lut_pct.setText(f"{val}%")
        self._emit_changed()

    def get_settings(self) -> Dict[str, Any]:
        return {
            "smart_workflow_preset": self.combo_smart_preset.currentText(),
            "extraction_engine": self.combo_extractor.currentText(),
            "translation_strategy": self.combo_strategy.currentText(),
            "ai_provider": self.combo_provider.currentText(),
            "model_name": self.combo_model.currentText().strip(),
            "target_language": self.combo_target_lang.currentText(),
            "dub_mode": self.combo_dub_mode.currentText(),
            "scene_auto_cut": self.chk_scene_cut.isChecked(),
            "anti_cr_mirror": self.chk_mirror.isChecked(),
            "anti_cr_zoom": self.chk_zoom.isChecked(),
            "recap_target_minutes": self.spin_recap_dur.value(),
            "vocal_removal_engine": self.combo_vocal.currentText(),
            "tts_engine": self.combo_tts.currentText(),
            "auto_rate_sync": self.chk_rate_sync.isChecked(),
            "ref_voice_wav": self.edit_ref_voice.text().strip(),
            "ref_voice_transcript": self.edit_ref_transcript.text().strip(),
            "active_emotion_tag": self._active_emotion,
            "text_fx_enabled": self.chk_text_fx.isChecked(),
            "text_fx_style": self.combo_text_style.currentText(),
            "bottom_cover_box": self.chk_bottom_box.isChecked(),
            "font_family": self.combo_font.currentText(),
            "font_size": self.spin_font_size.value(),
            "text_color": self._text_color,
            "outline_color": self._outline_color,
            "mask_enabled": self.chk_mask.isChecked(),
            "mask_engine": self.combo_mask_engine.currentText(),
            "mask_bg_mode": self.combo_bg_mode.currentText(),
            "lut_enabled": self.chk_lut.isChecked(),
            "lut_preset": self.combo_lut.currentText(),
            "lut_intensity": self.slider_lut.value(),
        }

    def apply_workflow_preset(self, preset_name: str) -> None:
        cfg = EngineRegistry.get_preset_config(preset_name)
        if cfg:
            if "extraction_engine" in cfg:
                self._select_combo_text(self.combo_extractor, cfg["extraction_engine"])
            if "translation_strategy" in cfg:
                self._select_combo_text(self.combo_strategy, cfg["translation_strategy"])
            if "dub_mode" in cfg:
                self._select_combo_text(self.combo_dub_mode, cfg["dub_mode"])
            if "vocal_removal_engine" in cfg:
                self._select_combo_text(self.combo_vocal, cfg["vocal_removal_engine"])
            if "tts_engine" in cfg:
                self._select_combo_text(self.combo_tts, cfg["tts_engine"])
            if "scene_auto_cut" in cfg:
                self.chk_scene_cut.setChecked(bool(cfg["scene_auto_cut"]))
            if "anti_cr_zoom" in cfg:
                self.chk_zoom.setChecked(bool(cfg["anti_cr_zoom"]))
            if "bottom_cover_box" in cfg:
                self.chk_bottom_box.setChecked(bool(cfg["bottom_cover_box"]))
            if "text_fx_enabled" in cfg:
                self.chk_text_fx.setChecked(bool(cfg["text_fx_enabled"]))
        else:
            p = (preset_name or "").lower()
            if "recap" in p:
                self._select_combo_text(self.combo_dub_mode, "AI Story Recap (Auto Scene Cut + Narration)")
                self.chk_scene_cut.setChecked(True)
                self.chk_zoom.setChecked(True)
            elif "subtitle" in p:
                self._select_combo_text(self.combo_dub_mode, "Disabled (Subtitles Only)")
                self.chk_text_fx.setChecked(True)
            elif "videofx" in p or "lut" in p:
                self.chk_lut.setChecked(True)
                self.chk_text_fx.setChecked(True)
                self.chk_mask.setChecked(True)
            elif "full movie" in p:
                self._select_combo_text(self.combo_dub_mode, "AI Movie Dubbing (Replace Dialogue)")
                self.chk_text_fx.setChecked(True)
                self.chk_bottom_box.setChecked(True)

        self._update_voice_clone_subpanel_visibility()
        self._emit_changed()

    def _emit_changed(self, *_args) -> None:
        self._settings.update(self.get_settings())
        self.settings_changed.emit(self.get_settings())
