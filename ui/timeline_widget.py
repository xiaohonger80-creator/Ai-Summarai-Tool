# -*- coding: utf-8 -*-
from PySide6.QtCore import Qt, Signal, QPoint, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, QFrame, QMenu
)


class TimelineCanvas(QWidget):
    """
    CapCut Multi-Track Canvas:
    - 112px track header column with color-coded accent strips and M/S pills
    - Time ruler with subtle tick marks and monospace timecodes
    - Visual clip blocks for Video, Khmer Subtitles, Khmer Dub Audio, and SFX
    - 2px Electric Cyan playhead with scrubber handle that smoothly tracks video playback
    """
    seek_requested = Signal(int)
    segment_selected = Signal(int)
    gap_action_requested = Signal(str, int, int)
    segment_action_requested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration_ms = 60000
        self.current_ms = 0
        self.segments = []
        self.clip_markers = []
        self.sfx_events = []
        self.selected_idx = -1
        self.active_idx = -1
        self.zoom_factor = 1.0
        self.scroll_offset = 0.0
        self._is_dragging = False

        # Track Mute / Solo states
        self.mute_video = False
        self.mute_sub = False
        self.mute_dub = False

        self.setMinimumHeight(150)
        self.setCursor(Qt.PointingHandCursor)

        self._font_ruler = QFont("JetBrains Mono", 8)
        self._font_track = QFont("Inter", 8, QFont.Bold)
        self._font_sub = QFont("Kantumruy Pro", 8, QFont.Bold)
        self._font_sub.setFamilies(["Kantumruy Pro", "Noto Sans Khmer", "Khmer OS Battambang", "Segoe UI"])
        self._font_sfx = QFont("JetBrains Mono", 7, QFont.Bold)

    def _get_left_margin(self) -> int:
        return 112

    def _x_to_ms(self, x: float) -> int:
        left_m = self._get_left_margin()
        visible_w = max(1.0, float(self.width() - left_m - 14))
        total_w = visible_w * self.zoom_factor
        adj_x = max(0.0, (x - left_m) + getattr(self, "scroll_offset", 0.0))
        ratio = max(0.0, min(1.0, adj_x / total_w))
        return int(ratio * self.duration_ms)

    def _ms_to_x(self, ms: int) -> float:
        left_m = self._get_left_margin()
        visible_w = max(1.0, float(self.width() - left_m - 14))
        total_w = visible_w * self.zoom_factor
        safe_ms = max(0, int(ms or 0))
        dur = max(1.0, float(getattr(self, "duration_ms", 1000) or 1000))
        raw_x = left_m + (min(safe_ms, dur) / dur) * total_w
        return raw_x - getattr(self, "scroll_offset", 0.0)

    def set_position(self, pos_ms: int):
        """Called automatically by video player positionChanged signal"""
        if getattr(self, "_is_dragging", False):
            return
        self.current_ms = max(0, min(pos_ms, self.duration_ms))

        # Auto-scroll playhead into view when zoomed in
        if self.zoom_factor > 1.0:
            left_m = self._get_left_margin()
            visible_w = max(1.0, float(self.width() - left_m - 14))
            total_w = visible_w * self.zoom_factor
            raw_x = (min(self.current_ms, self.duration_ms) / float(self.duration_ms)) * total_w
            curr_x = raw_x - getattr(self, "scroll_offset", 0.0)
            if curr_x > visible_w * 0.75:
                max_scroll = max(0.0, total_w - visible_w)
                self.scroll_offset = min(max_scroll, raw_x - visible_w * 0.3)
            elif curr_x < 0:
                self.scroll_offset = max(0.0, raw_x - visible_w * 0.2)

        new_active = -1
        for idx, seg in enumerate(self.segments):
            if seg["start_ms"] <= self.current_ms <= seg["end_ms"]:
                new_active = idx
                break
        self.active_idx = new_active
        self.update()

    def set_data(self, duration_ms: int, segments: list, clip_markers: list = None):
        self.duration_ms = max(1000, duration_ms)
        self.segments = segments or []
        if clip_markers is not None:
            self.clip_markers = clip_markers
        self.update()

    def set_sfx_events(self, sfx_events: list):
        self.sfx_events = sfx_events or []
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            y = event.position().y()
            left_m = self._get_left_margin()

            # Clicked on track Mute/Solo button area
            if x < left_m:
                if 28 <= y <= 56:
                    self.mute_video = not self.mute_video
                elif 64 <= y <= 94:
                    self.mute_sub = not self.mute_sub
                elif 102 <= y <= 132:
                    self.mute_dub = not self.mute_dub
                self.update()
                return

            self._is_dragging = True
            ms = self._x_to_ms(x)
            self.current_ms = ms
            self.seek_requested.emit(ms)
            for idx, seg in enumerate(self.segments):
                s_st = int(seg.get("start_ms") or 0)
                s_en = int(seg.get("end_ms") or 0)
                if s_st <= ms <= s_en:
                    self.selected_idx = idx
                    self.segment_selected.emit(idx)
                    break
            self.update()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            x = event.position().x()
            left_m = self._get_left_margin()
            if x >= left_m:
                ms = self._x_to_ms(x)
                self.current_ms = ms
                self.seek_requested.emit(ms)
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_dragging = False

    def contextMenuEvent(self, event):
        x = event.position().x()
        left_m = self._get_left_margin()
        if x < left_m:
            return
        ms = self._x_to_ms(x)

        # Check if clicked on an existing segment block
        target_idx = -1
        for idx, seg in enumerate(self.segments):
            s_st = int(seg.get("start_ms") or 0)
            s_en = int(seg.get("end_ms") or 0)
            if s_st <= ms <= s_en:
                target_idx = idx
                break

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #161920;
                color: #F4F6FB;
                border: 1px solid #343B4C;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
                font-size: 11px;
            }
            QMenu::item:selected {
                background-color: #202530;
                color: #00E5FF;
            }
            QMenu::separator {
                height: 1px;
                background-color: #252A36;
                margin: 4px 6px;
            }
        """)

        if target_idx >= 0:
            seg = self.segments[target_idx]
            self.selected_idx = target_idx
            self.segment_selected.emit(target_idx)
            self.update()

            act_redub = menu.addAction("🎙️ បង្កើតសំឡេងជួរនេះឡើងវិញ (Redub Line)")
            act_redub.triggered.connect(lambda: self.segment_action_requested.emit("redub", target_idx))

            act_retrans = menu.addAction("🌐 បកប្រែជួរនេះឡើងវិញ (Retranslate Line)")
            act_retrans.triggered.connect(lambda: self.segment_action_requested.emit("retranslate", target_idx))

            menu.addSeparator()

            act_split = menu.addAction("✂️ កាត់បំបែកត្រង់ម៉ោងនេះ (Split at Playhead)")
            act_split.triggered.connect(lambda: self.segment_action_requested.emit("split", target_idx))

            act_del = menu.addAction("🗑️ លុបជួរនេះ (Delete Line)")
            act_del.triggered.connect(lambda: self.segment_action_requested.emit("delete", target_idx))
        else:
            # Clicked on blank timeline gap
            gap_start = 0
            gap_end = self.duration_ms
            for seg in self.segments:
                if seg["end_ms"] <= ms and seg["end_ms"] > gap_start:
                    gap_start = seg["end_ms"]
                if seg["start_ms"] >= ms and seg["start_ms"] < gap_end:
                    gap_end = seg["start_ms"]

            gap_dur_s = max(0.1, (gap_end - gap_start) / 1000.0)
            lbl_title = f"🔍 ស្កេន និងបកប្រែចន្លោះនេះ ({gap_dur_s:.1f}s)"
            act_scan = menu.addAction(lbl_title)
            act_scan.triggered.connect(lambda: self.gap_action_requested.emit("scan", gap_start, gap_end))

            act_add = menu.addAction(f"➕ បន្ថែមជួរនិយាយត្រង់នេះ ({gap_dur_s:.1f}s)")
            act_add.triggered.connect(lambda: self.gap_action_requested.emit("add", gap_start, gap_end))

        menu.exec(event.globalPos())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            p = self.parent()
            if p and hasattr(p, "zoom_in") and hasattr(p, "zoom_out"):
                if delta > 0:
                    p.zoom_in()
                elif delta < 0:
                    p.zoom_out()
                event.accept()
                return
        elif self.zoom_factor > 1.0:
            delta = event.angleDelta().y() or event.angleDelta().x()
            left_m = self._get_left_margin()
            visible_w = max(1.0, float(self.width() - left_m - 14))
            total_w = visible_w * self.zoom_factor
            max_scroll = max(0.0, total_w - visible_w)
            self.scroll_offset = max(0.0, min(max_scroll, self.scroll_offset - delta * 0.8))
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        left_m = self._get_left_margin()

        # Canvas backgrounds
        p.fillRect(0, 0, w, h, QColor("#0B0D10"))

        # Clip timeline drawing area so it doesn't bleed into track headers
        p.setClipRect(QRectF(left_m, 0, max(0, w - left_m), h))

        # 1. TIME RULER (Top Bar: 24px)
        p.fillRect(left_m, 0, w - left_m, 24, QColor("#161920"))
        p.setPen(QPen(QColor("#252A36"), 1))
        p.drawLine(left_m, 24, w, 24)

        p.setFont(self._font_ruler)
        steps = max(6, int(10 * self.zoom_factor))
        for i in range(steps + 1):
            t_ms = int((i / steps) * self.duration_ms)
            x = int(self._ms_to_x(t_ms))
            if x < left_m - 20:
                continue
            if x > w + 20:
                break
            p.setPen(QPen(QColor("#343B4C"), 1))
            p.drawLine(x, 16, x, 24)

            sec = t_ms // 1000
            p.setPen(QColor("#8E95A5"))
            p.drawText(x + 3, 14, f"{sec // 60:02d}:{sec % 60:02d}")

        # Track horizontal dividers
        tracks = [
            (28, 28, "🎬 Video", QColor("#3B82F6"), self.mute_video),
            (64, 30, "💬 KH Sub", QColor("#F59E0B"), self.mute_sub),
            (102, 30, "🎙 KH Dub", QColor("#00E5FF"), self.mute_dub),
        ]
        for y, th, _, _, _ in tracks:
            p.setPen(QPen(QColor("#181C24"), 1))
            p.drawLine(left_m, y + th, w, y + th)

        # 3. TRACK 1: VIDEO STRIP
        if self.clip_markers:
            p.setFont(self._font_track)
            for cm in self.clip_markers:
                cx1 = int(self._ms_to_x(cm["start_ms"]))
                cx2 = max(cx1 + 3, int(self._ms_to_x(cm["end_ms"])))
                cw = cx2 - cx1
                if cx2 < left_m or cx1 > w:
                    continue
                p.setBrush(QColor("#1E293B") if cm["index"] % 2 == 1 else QColor("#182234"))
                p.setPen(QPen(QColor("#38BDF8"), 1))
                p.drawRoundedRect(cx1, 28, max(2, cw - 1), 26, 4, 4)
                if cw > 34:
                    p.setPen(QColor("#E0F2FE"))
                    p.drawText(cx1 + 6, 45, f"#{cm['index']} {cm['name'][:12]}")
        else:
            p.setBrush(QColor("#182234"))
            p.setPen(QPen(QColor("#3B82F6"), 1))
            p.drawRoundedRect(left_m + 2, 28, max(10, w - left_m - 16), 26, 4, 4)
            p.setPen(QColor("#93C5FD"))
            p.drawText(left_m + 12, 45, "🎬 Original Video Track")

        # 4. TRACK 2 (SUBTITLES) & TRACK 3 (KHMER DUB AUDIO)
        p.setFont(self._font_sub)
        for idx, seg in enumerate(self.segments):
            x1 = int(self._ms_to_x(seg.get("start_ms") or 0))
            x2 = max(x1 + 4, int(self._ms_to_x(seg.get("end_ms") or 0)))
            bw = x2 - x1
            if x2 < left_m or x1 > w:
                continue

            # Subtitle Block (Amber with glow border when selected or currently playing)
            is_active = (idx == self.selected_idx or idx == getattr(self, "active_idx", -1))
            if is_active:
                sub_col = QColor("#D97706")
                sub_pen = QPen(QColor("#00E5FF"), 1.5)
            else:
                sub_col = QColor("#542B0D")
                sub_pen = QPen(QColor("#F59E0B"), 1)

            p.setBrush(sub_col)
            p.setPen(sub_pen)
            p.drawRoundedRect(x1, 65, bw, 27, 4, 4)
            if bw > 24:
                p.setPen(QColor("#FEF3C7"))
                p.drawText(x1 + 4, 83, (seg.get("kh_text") or seg.get("zh_text") or "")[:20])

            # Khmer Dub Voice Audio Block (Emerald / Cyan accent with #A7F3D0 Waveform)
            tts_path = seg.get("tts_audio_path")
            has_tts = bool(tts_path and Path(str(tts_path)).exists())
            if has_tts:
                if is_active:
                    dub_col = QColor("#059669")
                    dub_pen = QPen(QColor("#00E5FF"), 1.5)
                else:
                    dub_col = QColor("#064E3B")
                    dub_pen = QPen(QColor("#10B981"), 1)

                p.setBrush(dub_col)
                p.setPen(dub_pen)
                p.drawRoundedRect(x1, 103, bw, 27, 4, 4)

                # Draw stylized audio waveform vertical bars (#A7F3D0)
                if bw > 14:
                    p.setPen(QPen(QColor("#A7F3D0"), 1))
                    y_mid = 103 + 13
                    wf_start = x1 + 4
                    wf_end = x1 + bw - 4
                    bx = wf_start
                    b_seed = idx * 11
                    while bx <= wf_end:
                        h_amp = 4 + int((((bx * 13 + b_seed) % 17) / 16.0) * 16)
                        p.drawLine(bx, y_mid - h_amp // 2, bx, y_mid + h_amp // 2)
                        bx += 3
                if bw > 28:
                    p.setPen(QColor("#D1FAE5"))
                    p.drawText(x1 + 4, 121, "🎙️ Dub")
            elif seg.get("kh_text") or seg.get("zh_text"):
                # Unvoiced / Missing audio with text -> Dashed Red Warning Block (#F87171)
                p.setBrush(QColor(239, 68, 68, 35))
                p.setPen(QPen(QColor("#F87171"), 1.2, Qt.DashLine))
                p.drawRoundedRect(x1, 103, bw, 27, 4, 4)
                if bw > 24:
                    p.setPen(QColor("#FCA5A5"))
                    p.drawText(x1 + 4, 120, "⚠️ Missing")

        # SFX Events (Cyber Violet pill)
        if self.sfx_events:
            p.setFont(self._font_sfx)
            for sfx in self.sfx_events:
                sx = int(self._ms_to_x(sfx["start_ms"]))
                if sx + 42 < left_m or sx > w:
                    continue
                p.setBrush(QColor("#6D28D9"))
                p.setPen(QPen(QColor("#A78BFA"), 1))
                p.drawRoundedRect(sx, 107, 42, 21, 4, 4)
                p.setPen(QColor("#EDE9FE"))
                p.drawText(sx + 4, 121, "🔔SFX")

        # 5. PLAYHEAD NEEDLE (2px Electric Cyan)
        px = int(self._ms_to_x(self.current_ms))
        p.setPen(QPen(QColor("#00E5FF"), 2))
        p.drawLine(px, 0, px, h)

        # Top scrubber handle triangle
        p.setBrush(QColor("#00E5FF"))
        p.setPen(Qt.NoPen)
        p.drawPolygon([
            QPoint(px - 6, 0),
            QPoint(px + 6, 0),
            QPoint(px + 6, 7),
            QPoint(px, 14),
            QPoint(px - 6, 7),
        ])

        # Disable clipping for track headers
        p.setClipping(False)

        # 2. TRACK HEADERS (Left Column: 112px, drawn on top)
        p.fillRect(0, 0, left_m, h, QColor("#12151B"))

        # Vertical separator line
        p.setPen(QPen(QColor("#252A36"), 1))
        p.drawLine(left_m, 0, left_m, h)

        p.setFont(self._font_track)
        for y, th, label, accent, is_muted in tracks:
            # Color-coded left accent strip (4px wide)
            p.fillRect(0, y, 4, th, accent)

            # Track label
            p.setPen(accent if not is_muted else QColor("#64748B"))
            p.drawText(8, y + 19, label)

            # Mute / Solo Pills on right edge of header
            m_col = QColor("#EF4444") if is_muted else QColor("#252A36")
            m_text_col = QColor("#FFFFFF") if is_muted else QColor("#8E95A5")
            p.setBrush(m_col)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(left_m - 34, y + 6, 14, 16, 3, 3)
            p.drawRoundedRect(left_m - 17, y + 6, 14, 16, 3, 3)

            p.setPen(m_text_col)
            p.drawText(left_m - 31, y + 18, "M")
            p.setPen(QColor("#8E95A5"))
            p.drawText(left_m - 14, y + 18, "S")

            # Track horizontal divider in header
            p.setPen(QPen(QColor("#181C24"), 1))
            p.drawLine(0, y + th, left_m, y + th)


class CapCutTimelineWidget(QWidget):
    """
    Complete CapCut Multi-Track Timeline with Toolbar:
    - 32px Toolbar: Play/Pause, Select (V), Split/Razor (C), Magnet Snap, Fill Gaps, Dub Missing, Zoom (- / +)
    - Multi-Track Canvas with Playhead, Video, Sub, Dub, and SFX
    """
    seek_requested = Signal(int)
    segment_selected = Signal(int)
    play_pause_requested = Signal()
    gap_action_requested = Signal(str, int, int)
    segment_action_requested = Signal(str, int)
    fill_gaps_clicked = Signal()
    dub_missing_clicked = Signal()
    auto_sfx_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Timeline Toolbar (32px Header)
        toolbar = QFrame()
        toolbar.setFixedHeight(32)
        toolbar.setStyleSheet("background-color: #12151B; border-bottom: 1px solid #252A36; padding: 2px 8px;")
        t_box = QHBoxLayout(toolbar)
        t_box.setContentsMargins(8, 2, 8, 2)
        t_box.setSpacing(6)

        self.btn_play_tl = QPushButton("▶ Play")
        self.btn_play_tl.setToolTip("Play / Pause Video (Space)")
        self.btn_play_tl.setStyleSheet(
            "background: #181C24; border: 1px solid #343B4C; border-radius: 4px; padding: 3px 10px; font-size: 11px; font-weight: 700; color: #F4F6FB;"
        )
        self.btn_play_tl.clicked.connect(self.play_pause_requested.emit)

        self.btn_select = QPushButton("🖱️ Select (V)")
        self.btn_select.setStyleSheet("background: #181C24; border: 1px solid #343B4C; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 700; color: #00E5FF;")

        self.btn_split = QPushButton("✂️ Razor (C)")
        self.btn_split.setStyleSheet("background: #181C24; border: 1px solid #252A36; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 600; color: #8E95A5;")

        self.btn_snap = QPushButton("🧲 Snap: ON")
        self.btn_snap.setStyleSheet("background: #181C24; border: 1px solid #252A36; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 600; color: #34D399;")

        self.btn_fill_gaps = QPushButton("🔍 Fill Gaps (បំពេញចន្លោះ)")
        self.btn_fill_gaps.setToolTip("ស្កេន និងបកប្រែបំពេញចន្លោះទំនេរទាំងអស់លើ Timeline (Scan & Fill Gaps)")
        self.btn_fill_gaps.setStyleSheet(
            "background: #181C24; border: 1px solid #7C3AED; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 700; color: #C4B5FD;"
        )
        self.btn_fill_gaps.clicked.connect(self.fill_gaps_clicked.emit)

        self.btn_dub_missing = QPushButton("🎙️ Dub Missing")
        self.btn_dub_missing.setToolTip("បង្កើតសំឡេងតែជួរណាដែលខ្វះ ឬបរាជ័យ (Dub Missing Audio)")
        self.btn_dub_missing.setStyleSheet(
            "background: #181C24; border: 1px solid #10B981; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 700; color: #34D399;"
        )
        self.btn_dub_missing.clicked.connect(self.dub_missing_clicked.emit)

        self.btn_auto_sfx = QPushButton("🎵 Auto-Place Emotion SFX && BGM")
        self.btn_auto_sfx.setToolTip("🎵 ដាក់ភ្លេង & Effect ស្វ័យប្រវត្តិតាមអារម្មណ៍សាច់រឿង (Shock / Sad / Action / Funny / Romantic)")
        self.btn_auto_sfx.setStyleSheet(
            "background: #1E1630; border: 1px solid #A78BFA; border-radius: 4px; padding: 3px 9px; font-size: 11px; font-weight: 700; color: #DDD6FE;"
        )
        self.btn_auto_sfx.clicked.connect(self.auto_sfx_clicked.emit)

        t_box.addWidget(self.btn_play_tl)
        t_box.addWidget(self.btn_select)
        t_box.addWidget(self.btn_split)
        t_box.addWidget(self.btn_snap)
        t_box.addWidget(self.btn_fill_gaps)
        t_box.addWidget(self.btn_dub_missing)
        t_box.addWidget(self.btn_auto_sfx)
        t_box.addStretch()

        lbl_zoom = QLabel("🔍 Zoom:")
        lbl_zoom.setStyleSheet("color: #8E95A5; font-size: 11px;")
        t_box.addWidget(lbl_zoom)

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 60)
        self.zoom_slider.setValue(10)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.setToolTip("Zoom Timeline (Ctrl + Mouse Scroll)")
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        t_box.addWidget(self.zoom_slider)

        layout.addWidget(toolbar)

        # 2. Canvas
        self.canvas = TimelineCanvas(self)
        self.canvas.seek_requested.connect(self.seek_requested)
        self.canvas.segment_selected.connect(self.segment_selected)
        self.canvas.gap_action_requested.connect(self.gap_action_requested)
        self.canvas.segment_action_requested.connect(self.segment_action_requested)
        layout.addWidget(self.canvas, 1)

    @property
    def selected_idx(self) -> int:
        return self.canvas.selected_idx

    @selected_idx.setter
    def selected_idx(self, val: int):
        self.canvas.selected_idx = val
        self.canvas.update()

    def set_playing(self, is_playing: bool):
        if hasattr(self, "btn_play_tl"):
            self.btn_play_tl.setText("⏸ Pause" if is_playing else "▶ Play")
            self.btn_play_tl.setStyleSheet(
                "background: #252A36; border: 1px solid #00E5FF; border-radius: 4px; padding: 3px 10px; font-size: 11px; font-weight: 700; color: #00E5FF;"
                if is_playing else
                "background: #181C24; border: 1px solid #343B4C; border-radius: 4px; padding: 3px 10px; font-size: 11px; font-weight: 700; color: #F4F6FB;"
            )

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def zoom_in(self):
        new_val = min(self.zoom_slider.maximum(), self.zoom_slider.value() + 2)
        self.zoom_slider.setValue(new_val)

    def zoom_out(self):
        new_val = max(self.zoom_slider.minimum(), self.zoom_slider.value() - 2)
        self.zoom_slider.setValue(new_val)

    def set_data(self, duration_ms: int, segments: list, clip_markers: list = None):
        self.canvas.set_data(duration_ms, segments, clip_markers)

    def set_sfx_events(self, sfx_events: list):
        self.canvas.set_sfx_events(sfx_events)

    def set_position(self, pos_ms: int):
        self.canvas.set_position(pos_ms)

    def _on_zoom_changed(self, val: int):
        self.canvas.zoom_factor = val / 10.0
        left_m = self.canvas._get_left_margin()
        visible_w = max(1.0, float(self.canvas.width() - left_m - 14))
        total_w = visible_w * self.canvas.zoom_factor
        max_scroll = max(0.0, total_w - visible_w)
        self.canvas.scroll_offset = max(0.0, min(max_scroll, getattr(self.canvas, "scroll_offset", 0.0)))
        self.canvas.update()
