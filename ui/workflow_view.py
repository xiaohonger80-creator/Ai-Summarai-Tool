# -*- coding: utf-8 -*-
"""
Ai Summarai — Real-Time Workflow Views Monitor (ui/workflow_view.py)
-------------------------------------------------------------------
Live visual pipeline monitor allowing users to watch every stage of
the video dubbing & export process in real time:
  - View 1: Animated Visual Pipeline Flowchart (6 connected live nodes)
  - View 2: Live Stage Checklist & Telemetry Metrics
  - View 3: Timestamped Real-Time Process Console Log
  - Compact Mini Always-on-Top HUD mode
"""

import datetime
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit,
    QProgressBar, QFrame, QFileDialog, QApplication, QSizePolicy
)


PIPELINE_STAGES = [
    {
        "key": "input",
        "num": "01",
        "icon": "🎬",
        "title_kh": "នាំចូលវីដេអូ",
        "title_en": "Input Video",
        "desc_kh": "ផ្ទុកវីដេអូ និងគម្រោង",
        "desc_en": "Load video & project",
        "accent": "#38BDF8",
    },
    {
        "key": "scan",
        "num": "02",
        "icon": "🔍",
        "title_kh": "ស្កេនអក្សរ/សំឡេងចិន",
        "title_en": "Scan ZH (ASR/OCR)",
        "desc_kh": "VAD Speech / RapidOCR",
        "desc_en": "VAD Speech / RapidOCR",
        "accent": "#00E5FF",
    },
    {
        "key": "translate",
        "num": "03",
        "icon": "🤖",
        "title_kh": "បកប្រែ AI ជាខ្មែរ",
        "title_en": "AI Translate KH",
        "desc_kh": "Literal / Recap + 429 Pool",
        "desc_en": "Literal / Recap + 429 Pool",
        "accent": "#A78BFA",
    },
    {
        "key": "dub",
        "num": "04",
        "icon": "🎙️",
        "title_kh": "បង្កើតសំឡេងខ្មែរ",
        "title_en": "Khmer Voice TTS",
        "desc_kh": "4 Voices + Lip-Sync Atempo",
        "desc_en": "4 Voices + Lip-Sync Atempo",
        "accent": "#F59E0B",
    },
    {
        "key": "fx",
        "num": "05",
        "icon": "🛡️",
        "title_kh": "រូបភាព & Anti-Copyright",
        "title_en": "FX, Blur & Anti-CR",
        "desc_kh": "LUT 20+, Timed Blur, BGM/SFX",
        "desc_en": "20+ LUTs, Timed Blur, BGM/SFX",
        "accent": "#EC4899",
    },
    {
        "key": "export",
        "num": "06",
        "icon": "🚀",
        "title_kh": "Render & Export",
        "title_en": "Final Render & Export",
        "desc_kh": "MP4 / Splits / 9:16 Shorts",
        "desc_en": "MP4 / Splits / 9:16 Shorts",
        "accent": "#10B981",
    },
]


def infer_stage_from_message(msg: str, default_stage: str = "export") -> str:
    """Infers the active pipeline stage key from live worker progress messages."""
    m = (msg or "").lower()
    if any(k in m for k in ("step 1/5", "ស្កេន", "ocr", "whisper", "transcrib", "extract", "asr", "vad", "សម្អាត", "clean")):
        return "scan"
    if any(k in m for k in ("step 2/5", "step 3/5", "បកប្រែ", "translat", "glossary", "recap", "api pool", "hook")):
        return "translate"
    if any(k in m for k in ("step 4/5", "សំឡេង", "tts", "voice", "dub", "atempo", "lipsync", "lip-sync")):
        return "dub"
    if any(k in m for k in ("anti-copyright", "copyright", "blur", "sfx", "bgm", "vocal", "lut", "mask", "effect", "កាត់ផ្តាច់")):
        return "fx"
    if any(k in m for k in ("step 5/5", "export", "render", "short", "split", "stitch", "social pack", "mux", "encode", "នាំចេញ")):
        return "export"
    if any(k in m for k in ("open", "load", "video", "បើកវីដេអូ", "គម្រោង")):
        return "input"
    return default_stage


class WorkflowFlowCanvas(QWidget):
    """
    Custom QPainter real-time animated node-graph canvas showing all 6 stages
    arranged in a clean 3x2 flowing studio diagram with animated pulse & flow dots.
    """
    stage_clicked = Signal(str)

    def __init__(self, lang: str = "kh", parent=None):
        super().__init__(parent)
        self.lang = lang
        self.setMinimumSize(760, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._phase = 0.0
        self._hover_key = ""
        self._node_rects: Dict[str, QRectF] = {}
        self._states: Dict[str, Dict] = {}

    def set_states(self, states: Dict[str, Dict], lang: str = "kh"):
        self._states = states
        self.lang = lang
        self.update()

    def advance_animation(self):
        self._phase = (self._phase + 0.045) % 1.0
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        hovered = ""
        for k, rect in self._node_rects.items():
            if rect.contains(pos):
                hovered = k
                break
        if hovered != self._hover_key:
            self._hover_key = hovered
            self.setCursor(Qt.PointingHandCursor if hovered else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            for k, rect in self._node_rects.items():
                if rect.contains(pos):
                    self.stage_clicked.emit(k)
                    break

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())

        # 1. Background subtle studio grid
        painter.fillRect(self.rect(), QColor("#0D1017"))
        grid_pen = QPen(QColor("#171C28"), 1)
        painter.setPen(grid_pen)
        step = 28
        for gx in range(0, int(w), step):
            painter.drawLine(gx, 0, gx, int(h))
        for gy in range(0, int(h), step):
            painter.drawLine(0, gy, int(w), gy)

        # 2. Compute 3x2 flowing layout (Row 1: 01 -> 02 -> 03, Row 2: 04 -> 05 -> 06)
        pad_x = 24.0
        pad_y = 22.0
        gap_x = 42.0
        gap_y = 46.0
        cols = 3
        rows = 2
        card_w = max(180.0, (w - pad_x * 2 - gap_x * (cols - 1)) / cols)
        card_h = max(112.0, min(145.0, (h - pad_y * 2 - gap_y * (rows - 1)) / rows))
        total_h = card_h * rows + gap_y
        start_y = max(pad_y, (h - total_h) / 2.0)

        self._node_rects.clear()
        coords: List[QRectF] = []
        for idx, stage in enumerate(PIPELINE_STAGES):
            r = idx // cols
            c = idx % cols
            x = pad_x + c * (card_w + gap_x)
            y = start_y + r * (card_h + gap_y)
            rect = QRectF(x, y, card_w, card_h)
            self._node_rects[stage["key"]] = rect
            coords.append(rect)

        # 3. Draw connecting flow edges (0->1, 1->2, 2->3 S-curve, 3->4, 4->5)
        for i in range(len(PIPELINE_STAGES) - 1):
            src_key = PIPELINE_STAGES[i]["key"]
            dst_key = PIPELINE_STAGES[i + 1]["key"]
            src_st = self._states.get(src_key, {}).get("status", "pending")
            dst_st = self._states.get(dst_key, {}).get("status", "pending")
            is_active_flow = (dst_st == "running" or src_st == "running")
            is_done_flow = (src_st == "done" and dst_st in ("done", "running"))

            r1 = coords[i]
            r2 = coords[i + 1]
            path = QPainterPath()

            if i != 2:
                # Straight horizontal connector
                p1 = QPointF(r1.right(), r1.center().y())
                p2 = QPointF(r2.left(), r2.center().y())
                path.moveTo(p1)
                path.lineTo(p2)
            else:
                # Smooth snake connector from node 03 bottom -> node 04 top
                p1 = QPointF(r1.center().x(), r1.bottom())
                p2 = QPointF(r2.center().x(), r2.top())
                mid_y = (p1.y() + p2.y()) / 2.0
                path.moveTo(p1)
                path.lineTo(p1.x(), mid_y)
                path.lineTo(p2.x(), mid_y)
                path.lineTo(p2)

            edge_color = QColor("#00E5FF") if is_active_flow else (
                QColor("#10B981") if is_done_flow else QColor("#2A3244")
            )
            pen_w = 2.6 if is_active_flow else (2.0 if is_done_flow else 1.5)
            painter.setPen(QPen(edge_color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            # Arrowhead at destination
            tip = path.pointAtPercent(1.0)
            painter.setBrush(QBrush(edge_color))
            painter.setPen(Qt.NoPen)
            if i != 2:
                arrow = QPainterPath()
                arrow.moveTo(tip)
                arrow.lineTo(tip.x() - 7, tip.y() - 4.5)
                arrow.lineTo(tip.x() - 7, tip.y() + 4.5)
                arrow.closeSubpath()
                painter.drawPath(arrow)
            else:
                arrow = QPainterPath()
                arrow.moveTo(tip)
                arrow.lineTo(tip.x() - 4.5, tip.y() - 7)
                arrow.lineTo(tip.x() + 4.5, tip.y() - 7)
                arrow.closeSubpath()
                painter.drawPath(arrow)

            # Animated glowing data pulse dot along active flow edge
            if is_active_flow:
                pt = path.pointAtPercent(self._phase)
                painter.setBrush(QBrush(QColor(0, 229, 255, 75)))
                painter.drawEllipse(pt, 8.5, 8.5)
                painter.setBrush(QBrush(QColor("#FFFFFF")))
                painter.drawEllipse(pt, 3.8, 3.8)

        # 4. Draw each stage node card
        kh = self.lang == "kh"
        for stage in PIPELINE_STAGES:
            key = stage["key"]
            rect = self._node_rects[key]
            st = self._states.get(key, {})
            status = st.get("status", "pending")
            pct = max(0, min(100, int(st.get("pct", 0))))
            detail = str(st.get("detail", "") or (stage["desc_kh"] if kh else stage["desc_en"]))
            elapsed = str(st.get("elapsed", ""))
            metric = str(st.get("metric", ""))
            accent = QColor(stage["accent"])
            is_hover = (self._hover_key == key)

            # Card colors by status
            if status == "running":
                bg_top = QColor("#122634")
                bg_bot = QColor("#0E1824")
                border_col = QColor("#00E5FF")
                border_w = 2.4
                # Subtle animated outer glow
                glow_alpha = int(45 + 35 * abs(0.5 - self._phase) * 2)
                painter.setPen(QPen(QColor(0, 229, 255, glow_alpha), 5.5))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 11, 11)
            elif status == "done":
                bg_top = QColor("#102620")
                bg_bot = QColor("#0E1817")
                border_col = QColor("#10B981")
                border_w = 1.8
            elif status == "error":
                bg_top = QColor("#2B1419")
                bg_bot = QColor("#1B1014")
                border_col = QColor("#EF4444")
                border_w = 1.8
            elif status == "stopped":
                bg_top = QColor("#291E12")
                bg_bot = QColor("#1A1510")
                border_col = QColor("#F59E0B")
                border_w = 1.6
            else:
                bg_top = QColor("#161B26") if is_hover else QColor("#131722")
                bg_bot = QColor("#10141D")
                border_col = accent if is_hover else QColor("#252D3F")
                border_w = 1.5 if is_hover else 1.2

            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, bg_top)
            grad.setColorAt(1.0, bg_bot)
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(border_col, border_w))
            painter.drawRoundedRect(rect, 10, 10)

            # Top accent bar strip
            painter.setPen(Qt.NoPen)
            strip_col = border_col if status != "pending" else QColor(accent.red(), accent.green(), accent.blue(), 110)
            painter.setBrush(QBrush(strip_col))
            painter.drawRoundedRect(QRectF(rect.x() + 10, rect.y() + 1, rect.width() - 20, 3.0), 1.5, 1.5)

            # Header row: Stage icon + number + title + status pill
            title_str = f"{stage['icon']} {stage['num']}. {stage['title_kh'] if kh else stage['title_en']}"
            title_font = QFont("Inter", 9, QFont.Bold)
            painter.setFont(title_font)
            painter.setPen(QColor("#F8FAFC"))
            painter.drawText(
                QRectF(rect.x() + 12, rect.y() + 11, rect.width() - 82, 22),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(title_str, Qt.ElideRight, int(rect.width() - 84)),
            )

            # Status pill top-right
            pill_map = {
                "running": (f"⚡ {pct}%", "#00E5FF", "#0A2B36"),
                "done": ("✓ Done", "#10B981", "#0D2B22"),
                "error": ("✕ Error", "#EF4444", "#331419"),
                "stopped": ("⏹ Stop", "#F59E0B", "#332210"),
                "pending": ("○ Wait", "#7A8499", "#1B2130"),
            }
            p_txt, p_fg, p_bg = pill_map.get(status, pill_map["pending"])
            pill_rect = QRectF(rect.right() - 68, rect.y() + 10, 58, 20)
            painter.setBrush(QBrush(QColor(p_bg)))
            painter.setPen(QPen(QColor(p_fg), 1.0))
            painter.drawRoundedRect(pill_rect, 9, 9)
            pill_font = QFont("Inter", 8, QFont.Bold)
            painter.setFont(pill_font)
            painter.setPen(QColor(p_fg))
            painter.drawText(pill_rect, Qt.AlignCenter, p_txt)

            # Metric & Elapsed row
            meta_font = QFont("Inter", 8, QFont.DemiBold)
            painter.setFont(meta_font)
            if metric:
                painter.setPen(accent)
                painter.drawText(
                    QRectF(rect.x() + 12, rect.y() + 36, rect.width() - 78, 18),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    painter.fontMetrics().elidedText(metric, Qt.ElideRight, int(rect.width() - 80)),
                )
            if elapsed:
                painter.setPen(QColor("#94A3B8"))
                painter.drawText(
                    QRectF(rect.right() - 66, rect.y() + 36, 56, 18),
                    Qt.AlignRight | Qt.AlignVCenter,
                    elapsed,
                )

            # Live detail text
            desc_font = QFont("Inter", 8)
            painter.setFont(desc_font)
            painter.setPen(QColor("#CBD5E1") if status == "running" else QColor("#8E98AB"))
            detail_y = rect.y() + (56 if (metric or elapsed) else 42)
            painter.drawText(
                QRectF(rect.x() + 12, detail_y, rect.width() - 24, 24),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(detail, Qt.ElideRight, int(rect.width() - 26)),
            )

            # Bottom slim progress bar inside node
            bar_rect = QRectF(rect.x() + 12, rect.bottom() - 16, rect.width() - 24, 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#1E2536")))
            painter.drawRoundedRect(bar_rect, 3, 3)

            fill_ratio = 1.0 if status == "done" else (pct / 100.0 if status in ("running", "stopped") else 0.0)
            if fill_ratio > 0.0:
                fill_w = max(8.0, bar_rect.width() * fill_ratio)
                fill_rect = QRectF(bar_rect.x(), bar_rect.y(), fill_w, bar_rect.height())
                fill_col = QColor("#10B981") if status == "done" else (
                    QColor("#F59E0B") if status == "stopped" else QColor("#00E5FF")
                )
                painter.setBrush(QBrush(fill_col))
                painter.drawRoundedRect(fill_rect, 3, 3)

        painter.end()


class WorkflowViewDialog(QDialog):
    """
    Real-Time Workflow Views Studio Monitor (non-modal window):
    - Tab 0: 🔀 Visual Pipeline Flowchart (Animated Node Graph)
    - Tab 1: 📊 Live Stage Metrics & Checklist
    - Tab 2: 📜 Real-Time Process Console Log
    - Supports Compact Mini Always-on-Top HUD mode!
    """
    stop_requested = Signal()
    stage_triggered = Signal(str)

    def __init__(self, lang: str = "kh", parent=None):
        super().__init__(parent)
        self.lang = lang
        self._compact_mode = False
        self._active_stage = ""
        self._stage_start_ts: Dict[str, float] = {}
        self._log_lines: List[str] = []
        self._stage_states: Dict[str, Dict] = {
            s["key"]: {"status": "pending", "pct": 0, "detail": "", "metric": "", "elapsed": ""}
            for s in PIPELINE_STAGES
        }

        self.setWindowTitle(
            "🔀 Ai Summarai — ផ្ទាំងតាមដានដំណើរការផ្ទាល់ (Real-Time Workflow Views)" if lang == "kh"
            else "🔀 Ai Summarai — Real-Time Workflow Views"
        )
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint)
        self.resize(940, 560)
        self.setMinimumSize(780, 460)
        self._build_ui()

        # Lightweight animation & elapsed-time ticker (only active while a stage is running!)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(80)
        self._anim_timer.timeout.connect(self._on_anim_tick)

    def _build_ui(self):
        kh = self.lang == "kh"
        self.setStyleSheet("""
            QDialog { background-color: #0B0D12; color: #F4F6FB; font-family: 'Inter', 'Kantumruy Pro', 'Noto Sans Khmer', 'Segoe UI'; }
            QFrame#WfHeader { background: #121620; border: 1px solid #242C3E; border-radius: 8px; }
            QTabWidget::pane { border: 1px solid #242C3E; background: #0E121A; border-radius: 8px; top: -1px; }
            QTabBar::tab {
                background: #141824; color: #94A3B8; padding: 7px 14px;
                border: 1px solid #242C3E; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                margin-right: 4px; font-weight: 700; font-size: 11.5px;
            }
            QTabBar::tab:selected { background: #1B2436; color: #00E5FF; border-color: #00E5FF; }
            QProgressBar {
                background: #181E2B; border: 1px solid #2A3347; border-radius: 6px;
                text-align: center; color: #F8FAFC; font-weight: 700; font-size: 11px; height: 18px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00E5FF, stop:1 #10B981);
                border-radius: 5px;
            }
            QTableWidget {
                background: #0F131C; alternate-background-color: #141925;
                gridline-color: #202738; color: #F1F5F9; border: none; font-size: 11.5px;
            }
            QHeaderView::section {
                background: #161C2A; color: #94A3B8; padding: 6px; border: none;
                border-bottom: 1px solid #273147; font-weight: 700; font-size: 11px;
            }
            QPlainTextEdit {
                background: #0A0D14; color: #D1FAE5; border: none;
                font-family: 'Consolas', 'JetBrains Mono', monospace; font-size: 11.5px;
                padding: 8px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 1. Live Telemetry Header Card
        header = QFrame()
        header.setObjectName("WfHeader")
        h_v = QVBoxLayout(header)
        h_v.setContentsMargins(12, 9, 12, 9)
        h_v.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.lbl_state_badge = QLabel("● IDLE — រង់ចាំដំណើរការ" if kh else "● IDLE — Ready")
        self.lbl_state_badge.setStyleSheet(
            "background: #1A2233; color: #94A3B8; border: 1px solid #2E3A54; "
            "border-radius: 10px; padding: 3px 10px; font-weight: 800; font-size: 11px;"
        )
        top_row.addWidget(self.lbl_state_badge)

        self.lbl_project = QLabel("📁 គ្មានវីដេអូ" if kh else "📁 No project loaded")
        self.lbl_project.setStyleSheet("color: #E2E8F0; font-weight: 700; font-size: 11.5px;")
        top_row.addWidget(self.lbl_project, 1)

        self.lbl_hw = QLabel("⚡ CPU --% | RAM -- | GPU --%")
        self.lbl_hw.setStyleSheet(
            "background: #151C28; color: #00E5FF; border: 1px solid #243045; "
            "border-radius: 6px; padding: 3px 9px; font-weight: 700; font-size: 10.5px;"
        )
        top_row.addWidget(self.lbl_hw)

        self.btn_pin_mini = QPushButton("📌 Mini HUD" if not kh else "📌 ផ្ទាំងតូច")
        self.btn_pin_mini.setCheckable(True)
        self.btn_pin_mini.setStyleSheet(
            "QPushButton { background: #1A2130; color: #CBD5E1; border: 1px solid #323E57; "
            "border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px; } "
            "QPushButton:checked { background: #0E3A47; color: #00E5FF; border-color: #00E5FF; }"
        )
        self.btn_pin_mini.clicked.connect(self._toggle_compact_mode)
        top_row.addWidget(self.btn_pin_mini)

        self.btn_stop_task = QPushButton("⏹ បញ្ឈប់" if kh else "⏹ Stop")
        self.btn_stop_task.setEnabled(False)
        self.btn_stop_task.setStyleSheet(
            "QPushButton { background: #7F1D1D; color: #FFFFFF; border: 1px solid #EF4444; "
            "border-radius: 6px; padding: 4px 11px; font-weight: 700; font-size: 11px; } "
            "QPushButton:disabled { background: #1A1F2B; color: #525C72; border-color: #252D3F; }"
        )
        self.btn_stop_task.clicked.connect(self.stop_requested.emit)
        top_row.addWidget(self.btn_stop_task)

        h_v.addLayout(top_row)

        prog_row = QHBoxLayout()
        prog_row.setSpacing(10)
        self.lbl_live_action = QLabel("ត្រៀមរួចរាល់ — សូមជ្រើសរើសមុខងារ ឬចុចលើដំណាក់កាលណាមួយក្នុង Flowchart" if kh else "Ready — trigger any pipeline step or click a node below")
        self.lbl_live_action.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 600;")
        prog_row.addWidget(self.lbl_live_action, 1)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFixedWidth(220)
        prog_row.addWidget(self.overall_bar)
        h_v.addLayout(prog_row)

        root.addWidget(header)

        # 2. Main 3-View Tabs (Hidden in Mini HUD mode)
        self.tabs = QTabWidget()

        # Tab 0: Visual Flowchart Canvas
        flow_wrap = QWidget()
        fv = QVBoxLayout(flow_wrap)
        fv.setContentsMargins(8, 8, 8, 8)
        fv.setSpacing(6)
        self.canvas = WorkflowFlowCanvas(lang=self.lang)
        self.canvas.stage_clicked.connect(self.stage_triggered.emit)
        fv.addWidget(self.canvas, 1)
        hint = QLabel(
            "💡 ចុចលើប្រអប់ណាមួយក្នុង Flowchart ដើម្បីចាប់ផ្តើម ឬបើកដំណាក់កាលនោះភ្លាមៗ • ព្រួញភ្លឺបង្ហាញដំណើរការផ្ទាល់ (Real-Time)"
            if kh else
            "💡 Click any stage node to jump to or run that step • Animated glowing arrows show live processing"
        )
        hint.setStyleSheet("color: #64748B; font-size: 10.5px; padding-left: 4px;")
        fv.addWidget(hint)
        self.tabs.addTab(flow_wrap, "🔀 Visual Flow (Flowchart ផ្ទាល់)" if kh else "🔀 Visual Flow")

        # Tab 1: Stage Metrics Table
        metrics_wrap = QWidget()
        mv = QVBoxLayout(metrics_wrap)
        mv.setContentsMargins(8, 8, 8, 8)
        self.tbl_stages = QTableWidget(len(PIPELINE_STAGES), 5)
        self.tbl_stages.setHorizontalHeaderLabels(
            ["ដំណាក់កាល (Stage)", "ស្ថានភាព (Status)", "វឌ្ឍនភាព (%)", "ទិន្នន័យ (Metrics)", "ព័ត៌មានលម្អិត (Live Detail)"]
            if kh else
            ["Stage", "Status", "Progress", "Metrics", "Live Detail"]
        )
        self.tbl_stages.verticalHeader().setVisible(False)
        self.tbl_stages.setAlternatingRowColors(True)
        self.tbl_stages.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_stages.setSelectionBehavior(QTableWidget.SelectRows)
        hh = self.tbl_stages.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.tbl_stages.setColumnWidth(2, 110)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        for idx in range(len(PIPELINE_STAGES)):
            self.tbl_stages.setRowHeight(idx, 40)
        mv.addWidget(self.tbl_stages)
        self.tabs.addTab(metrics_wrap, "📊 Stage Metrics (ស្ថិតិផ្ទាល់)" if kh else "📊 Stage Metrics")

        # Tab 2: Real-Time Process Console Log
        log_wrap = QWidget()
        lv = QVBoxLayout(log_wrap)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText("កំណត់ត្រាដំណើរការផ្ទាល់ (Real-Time Process Log) នឹងបង្ហាញនៅទីនេះ..." if kh else "Real-time process events will stream here...")
        lv.addWidget(self.txt_log, 1)

        log_btns = QHBoxLayout()
        log_btns.addStretch()
        btn_copy_log = QPushButton("📋 Copy Log")
        btn_copy_log.setStyleSheet("background: #1A2130; color: #E2E8F0; border: 1px solid #323E57; border-radius: 5px; padding: 4px 12px; font-size: 11px;")
        btn_copy_log.clicked.connect(lambda: QApplication.clipboard().setText(self.txt_log.toPlainText()))
        btn_save_log = QPushButton("💾 Export .txt")
        btn_save_log.setStyleSheet("background: #1A2130; color: #38BDF8; border: 1px solid #323E57; border-radius: 5px; padding: 4px 12px; font-size: 11px;")
        btn_save_log.clicked.connect(self._export_log_txt)
        btn_clear_log = QPushButton("🧹 Clear")
        btn_clear_log.setStyleSheet("background: #1A2130; color: #F87171; border: 1px solid #323E57; border-radius: 5px; padding: 4px 12px; font-size: 11px;")
        btn_clear_log.clicked.connect(self.clear_log)
        for b in (btn_copy_log, btn_save_log, btn_clear_log):
            log_btns.addWidget(b)
        lv.addLayout(log_btns)
        self.tabs.addTab(log_wrap, "📜 Live Process Log (កំណត់ត្រា)" if kh else "📜 Live Process Log")

        root.addWidget(self.tabs, 1)
        self._refresh_views()

    def set_view_mode(self, tab_index: int = 0, compact: bool = False):
        self.btn_pin_mini.setChecked(compact)
        self._apply_compact_mode(compact)
        if not compact and 0 <= tab_index < self.tabs.count():
            self.tabs.setCurrentIndex(tab_index)

    def _toggle_compact_mode(self):
        self._apply_compact_mode(self.btn_pin_mini.isChecked())

    def _apply_compact_mode(self, compact: bool):
        self._compact_mode = compact
        self.tabs.setVisible(not compact)
        flags = self.windowFlags()
        if compact:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
            self.setMinimumSize(640, 108)
            self.resize(740, 114)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
            self.setMinimumSize(780, 460)
            self.resize(940, 560)
        if self.isVisible():
            self.show()

    def _export_log_txt(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Workflow Log", "AiSummarai_Workflow_Log.txt", "Text Files (*.txt)")
        if path:
            Path(path).write_text(self.txt_log.toPlainText(), encoding="utf-8")

    def clear_log(self):
        self._log_lines.clear()
        self.txt_log.clear()

    def append_log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        if self._log_lines and self._log_lines[-1].endswith(f"] {msg}"):
            return
        self._log_lines.append(line)
        if len(self._log_lines) > 600:
            self._log_lines = self._log_lines[-500:]
            self.txt_log.setPlainText("\n".join(self._log_lines))
        else:
            self.txt_log.appendPlainText(line)
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_hw_metrics(self, badge_text: str):
        if badge_text:
            self.lbl_hw.setText(badge_text)

    def sync_project_snapshot(
        self,
        project_name: str = "",
        video_info: str = "",
        total_segs: int = 0,
        translated_segs: int = 0,
        dubbed_segs: int = 0,
        fx_summary: str = "",
        exported_name: str = "",
    ):
        """Synchronizes stage cards from the current SQLite project state."""
        if project_name:
            self.lbl_project.setText(f"📁 {project_name}" + (f"  ({video_info})" if video_info else ""))
            self._set_stage("input", "done", 100, video_info or project_name, "Loaded")
        else:
            self.lbl_project.setText("📁 គ្មានវីដេអូ" if self.lang == "kh" else "📁 No project loaded")
            self._set_stage("input", "pending", 0, "", "")

        if self._active_stage != "scan":
            if total_segs > 0:
                self._set_stage("scan", "done", 100, f"{total_segs} ជួរចិន", f"{total_segs} lines")
            else:
                self._set_stage("scan", "pending", 0, "", "0 lines")

        if self._active_stage != "translate":
            if total_segs > 0 and translated_segs >= total_segs:
                self._set_stage("translate", "done", 100, f"បកប្រែរួច {translated_segs}/{total_segs}", f"{translated_segs}/{total_segs}")
            elif translated_segs > 0:
                p = int((translated_segs / max(1, total_segs)) * 100)
                self._set_stage("translate", "stopped", p, f"បកប្រែបាន {translated_segs}/{total_segs}", f"{translated_segs}/{total_segs}")
            else:
                self._set_stage("translate", "pending", 0, "", f"0/{total_segs}")

        if self._active_stage != "dub":
            if total_segs > 0 and dubbed_segs >= total_segs:
                self._set_stage("dub", "done", 100, f"សំឡេងខ្មែររួច {dubbed_segs}/{total_segs}", f"{dubbed_segs}/{total_segs}")
            elif dubbed_segs > 0:
                p = int((dubbed_segs / max(1, total_segs)) * 100)
                self._set_stage("dub", "stopped", p, f"បង្កើតបាន {dubbed_segs}/{total_segs}", f"{dubbed_segs}/{total_segs}")
            else:
                self._set_stage("dub", "pending", 0, "", f"0/{total_segs}")

        if self._active_stage != "fx":
            if fx_summary:
                self._set_stage("fx", "done", 100, fx_summary, "Configured")
            else:
                self._set_stage("fx", "pending", 0, "", "Default")

        if self._active_stage != "export" and exported_name:
            self._set_stage("export", "done", 100, exported_name, "Exported")

        self._refresh_views()

    def _set_stage(self, key: str, status: str, pct: int, detail: str = "", metric: Optional[str] = None):
        st = self._stage_states.get(key)
        if st is None:
            return
        st["status"] = status
        st["pct"] = max(0, min(100, int(pct)))
        if detail:
            st["detail"] = detail
        if metric is not None:
            st["metric"] = metric

    def on_stage_started(self, stage_key: str, msg: str):
        key = stage_key if stage_key in self._stage_states else infer_stage_from_message(msg)
        self._active_stage = key
        self._stage_start_ts[key] = time.monotonic()
        self._set_stage(key, "running", 5, msg)
        self.btn_stop_task.setEnabled(True)
        self.lbl_state_badge.setText("● RUNNING — កំពុងដំណើរការ" if self.lang == "kh" else "● RUNNING — Live")
        self.lbl_state_badge.setStyleSheet(
            "background: #0B3542; color: #00E5FF; border: 1px solid #00E5FF; "
            "border-radius: 10px; padding: 3px 10px; font-weight: 800; font-size: 11px;"
        )
        self.lbl_live_action.setText(msg)
        self.overall_bar.setValue(5)
        self.append_log(f"START [{key.upper()}] {msg}", "RUN")
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        self._refresh_views()

    def on_stage_progress(self, pct: int, msg: str, stage_key: str = ""):
        inferred = infer_stage_from_message(msg, default_stage=self._active_stage or "export")
        key = stage_key if stage_key in self._stage_states else inferred
        if self._active_stage and key != self._active_stage:
            # Auto-complete previous stage during multi-step 1-Click Auto Pipeline
            prev_idx = next((i for i, s in enumerate(PIPELINE_STAGES) if s["key"] == self._active_stage), -1)
            new_idx = next((i for i, s in enumerate(PIPELINE_STAGES) if s["key"] == key), -1)
            if 0 <= prev_idx < new_idx:
                t0 = self._stage_start_ts.get(self._active_stage)
                if t0:
                    self._stage_states[self._active_stage]["elapsed"] = f"{time.monotonic() - t0:.1f}s"
                self._set_stage(self._active_stage, "done", 100)
            self._active_stage = key
            self._stage_start_ts.setdefault(key, time.monotonic())

        if not self._active_stage:
            self._active_stage = key
            self._stage_start_ts.setdefault(key, time.monotonic())

        self._set_stage(key, "running", max(1, pct), msg)
        self.btn_stop_task.setEnabled(True)
        self.lbl_live_action.setText(msg)
        self.overall_bar.setValue(max(0, min(100, int(pct))))
        self.append_log(f"{pct:3d}% [{key.upper()}] {msg}", "STEP")
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        self._refresh_views()

    def on_stage_finished(self, msg: str, stage_key: str = ""):
        key = stage_key or self._active_stage or infer_stage_from_message(msg)
        if key in self._stage_states:
            t0 = self._stage_start_ts.get(key)
            if t0:
                self._stage_states[key]["elapsed"] = f"{time.monotonic() - t0:.1f}s"
            self._set_stage(key, "done", 100, msg)
        self._active_stage = ""
        self._anim_timer.stop()
        self.btn_stop_task.setEnabled(False)
        self.lbl_state_badge.setText("✓ DONE — បានបញ្ចប់" if self.lang == "kh" else "✓ DONE — Completed")
        self.lbl_state_badge.setStyleSheet(
            "background: #0D3326; color: #10B981; border: 1px solid #10B981; "
            "border-radius: 10px; padding: 3px 10px; font-weight: 800; font-size: 11px;"
        )
        self.lbl_live_action.setText(msg)
        self.overall_bar.setValue(100)
        self.append_log(f"DONE [{key.upper()}] {msg}", "OK")
        self._refresh_views()

    def on_stage_stopped(self, msg: str):
        key = self._active_stage
        if key in self._stage_states:
            self._set_stage(key, "stopped", self._stage_states[key].get("pct", 0), msg)
        self._active_stage = ""
        self._anim_timer.stop()
        self.btn_stop_task.setEnabled(False)
        self.lbl_state_badge.setText("⏹ STOPPED — បានផ្អាក" if self.lang == "kh" else "⏹ STOPPED")
        self.lbl_state_badge.setStyleSheet(
            "background: #332210; color: #F59E0B; border: 1px solid #F59E0B; "
            "border-radius: 10px; padding: 3px 10px; font-weight: 800; font-size: 11px;"
        )
        self.lbl_live_action.setText(msg)
        self.append_log(f"STOPPED {msg}", "WARN")
        self._refresh_views()

    def on_stage_failed(self, err: str):
        key = self._active_stage
        if key in self._stage_states:
            self._set_stage(key, "error", self._stage_states[key].get("pct", 0), err)
        self._active_stage = ""
        self._anim_timer.stop()
        self.btn_stop_task.setEnabled(False)
        self.lbl_state_badge.setText("✕ ERROR — មានកំហុស" if self.lang == "kh" else "✕ ERROR")
        self.lbl_state_badge.setStyleSheet(
            "background: #331419; color: #EF4444; border: 1px solid #EF4444; "
            "border-radius: 10px; padding: 3px 10px; font-weight: 800; font-size: 11px;"
        )
        self.lbl_live_action.setText(f"❌ {err[:120]}")
        self.append_log(f"ERROR {err}", "ERR")
        self._refresh_views()

    def _on_anim_tick(self):
        if self._active_stage and self._active_stage in self._stage_start_ts:
            dt = time.monotonic() - self._stage_start_ts[self._active_stage]
            self._stage_states[self._active_stage]["elapsed"] = f"{int(dt // 60):02d}:{int(dt % 60):02d}"
        self.canvas.advance_animation()

    def _refresh_views(self):
        self.canvas.set_states(self._stage_states, lang=self.lang)
        kh = self.lang == "kh"
        status_labels = {
            "running": ("⚡ កំពុងដំណើរការ" if kh else "⚡ Running", "#00E5FF"),
            "done": ("✅ រួចរាល់" if kh else "✅ Done", "#10B981"),
            "error": ("❌ កំហុស" if kh else "❌ Error", "#EF4444"),
            "stopped": ("⏹ ផ្អាក" if kh else "⏹ Stopped", "#F59E0B"),
            "pending": ("○ រង់ចាំ" if kh else "○ Pending", "#7A8499"),
        }
        for row, stage in enumerate(PIPELINE_STAGES):
            st = self._stage_states.get(stage["key"], {})
            status = st.get("status", "pending")
            pct = st.get("pct", 0)
            s_text, s_col = status_labels.get(status, status_labels["pending"])

            it0 = QTableWidgetItem(f"{stage['icon']} {stage['num']}. {stage['title_kh'] if kh else stage['title_en']}")
            it1 = QTableWidgetItem(s_text)
            it1.setForeground(QColor(s_col))
            it2 = QTableWidgetItem(f"{100 if status == 'done' else pct}%" + (f" ({st['elapsed']})" if st.get("elapsed") else ""))
            it2.setTextAlignment(Qt.AlignCenter)
            it3 = QTableWidgetItem(st.get("metric", "") or "--")
            it4 = QTableWidgetItem(st.get("detail", "") or (stage["desc_kh"] if kh else stage["desc_en"]))

            for col_i, item in enumerate((it0, it1, it2, it3, it4)):
                self.tbl_stages.setItem(row, col_i, item)

    def closeEvent(self, event):
        if self._anim_timer.isActive():
            self._anim_timer.stop()
        super().closeEvent(event)
