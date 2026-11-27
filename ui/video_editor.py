import subprocess
import json
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import QPixmap, QColor, QFont, QBrush, QPen, QPainter, QPainterPath, QFontMetrics, QFontDatabase
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsTextItem,
    QGraphicsRectItem, QGraphicsItem, QTabWidget, QFormLayout, QFileDialog, QCheckBox,
    QComboBox, QColorDialog, QSpinBox, QSizePolicy, QMessageBox, QInputDialog,
    QGridLayout, QScrollArea, QLineEdit, QFrame
)

from core.sub_styles import (
    KHMER_SUB_STYLES, KHMER_RECOMMENDED_FONTS, get_categories, get_sub_style,
    ass_color_to_rgb, ass_color_to_rgba
)
from core.lut_presets import LUT_PRESETS, get_lut_preset, get_lut_categories
from core.media_engine import CREATE_NO_WINDOW


class DraggableOverlay(QGraphicsPixmapItem):
    """អាចចាប់អូស Logo Watermark ដោយផ្ទាល់នៅលើផ្ទាំង Video Preview បានយ៉ាងរលូន"""
    def __init__(self, on_moved_cb):
        super().__init__()
        self.on_moved_cb = on_moved_cb
        self._drag_offset = None
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(28)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and self.scene():
            max_w = self.scene().sceneRect().width()
            max_h = self.scene().sceneRect().height()
            bw = self.boundingRect().width() * self.scale()
            bh = self.boundingRect().height() * self.scale()
            new_pos = self.mapToScene(event.pos()) - self._drag_offset
            nx = max(0.0, min(max(0.0, max_w - bw), new_pos.x()))
            ny = max(0.0, min(max(0.0, max_h - bh), new_pos.y()))
            self.setPos(nx, ny)
            if self.on_moved_cb:
                self.on_moved_cb(nx, ny)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class InteractiveMaskOverlay(QGraphicsRectItem):
    """
    ប្រអប់ Mask សម្រាប់បិទអក្សរដើមលើវីដេអូ (Multi-Mask)៖
    - ចុចលើប្រអប់ -> ជ្រើសរើស Mask នេះភ្លាមៗ
    - ចាប់អូសកណ្តាលប្រអប់ -> ប្តូរទីតាំង (X, Y)
    - ចាប់អូសជ្រុងខាងស្តាំ-ក្រោម (ចំណុចពណ៌ស/ខៀវ) -> ពង្រីក-បង្រួមទំហំ (Width, Height) ភ្លាមៗ!
    """
    HANDLE_SIZE = 12.0

    def __init__(self, mask_index: int, on_changed_cb, on_selected_cb=None):
        super().__init__()
        self.mask_index = mask_index
        self.on_changed_cb = on_changed_cb
        self.on_selected_cb = on_selected_cb
        self._resizing = False
        self._drag_offset = None
        self.is_selected = False
        self.setAcceptHoverEvents(True)
        self.setZValue(30)  # ដាក់នៅជាន់លើគេបង្អស់ ដើម្បីឲ្យចាប់ទាញបានគ្រប់ពេល!

    def _handle_rect(self) -> QRectF:
        r = self.rect()
        return QRectF(
            r.width() - self.HANDLE_SIZE,
            r.height() - self.HANDLE_SIZE,
            self.HANDLE_SIZE,
            self.HANDLE_SIZE,
        )

    def hoverMoveEvent(self, event):
        if self._handle_rect().contains(event.pos()):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.on_selected_cb:
                self.on_selected_cb(self.mask_index)
            if self._handle_rect().contains(event.pos()):
                self._resizing = True
            else:
                self._resizing = False
                self._drag_offset = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene = self.scene()
        if not scene:
            return
        max_w = scene.sceneRect().width()
        max_h = scene.sceneRect().height()

        if self._resizing:
            new_w = max(24.0, min(max_w - self.x(), event.pos().x()))
            new_h = max(14.0, min(max_h - self.y(), event.pos().y()))
            self.setRect(0, 0, new_w, new_h)
            if self.on_changed_cb:
                self.on_changed_cb(self.mask_index, self.x(), self.y(), new_w, new_h)
            event.accept()
            return

        if self._drag_offset is not None:
            new_pos = self.mapToScene(event.pos()) - self._drag_offset
            nx = max(0.0, min(max_w - self.rect().width(), new_pos.x()))
            ny = max(0.0, min(max_h - self.rect().height(), new_pos.y()))
            self.setPos(nx, ny)
            if self.on_changed_cb:
                self.on_changed_cb(self.mask_index, nx, ny, self.rect().width(), self.rect().height())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        # គូរចំណុចទាញពង្រីក-បង្រួមនៅជ្រុងខាងស្តាំ-ក្រោម ឲ្យមើលឃើញច្បាស់ងាយចាប់ទាញ
        hr = self._handle_rect()
        hcol = QColor("#38BDF8") if self.is_selected else QColor("#94A3B8")
        painter.setBrush(QBrush(hcol))
        painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
        painter.drawRect(hr)


FEATURED_PRESETS = [
    ("pure_zen_paper_white", "01. Pure Zen Minimal", "#FFFFFF", "none", "#0B0D10", "Clean white Kantumruy Pro"),
    ("tiktok_yellow_punch", "02. TikTok Yellow Pop", "#FACC15", "#000000", "#000000", "Bold yellow + thick stroke"),
    ("reels_clean_pill", "03. Dark Cinema Pill", "#FFFFFF", "none", "rgba(0,0,0,0.75)", "White in dark capsule"),
    ("neon_cyan_glow", "04. Neon Cyan Glow", "#00E5FF", "#00E5FF", "rgba(0,229,255,0.15)", "Electric cyan outer glow"),
    ("marvel_crimson", "05. Viral Red Badge", "#FFFFFF", "#FFFFFF", "#EF4444", "White on red highlight tag"),
    ("neon_vaporwave", "06. Inner Thought Italic", "#C4B5FD", "none", "rgba(49,27,105,0.6)", "Soft lavender italic"),
    ("cinema_gold", "07. Gold Drama Title", "#F59E0B", "#000000", "#18181B", "Metallic warm gold"),
    ("royal_emerald_box", "08. Karaoke Word Box", "#FFFFFF", "none", "#10B981", "Emerald green active pill"),
    ("ultra_clean_outline", "09. Clean Outline Pro", "#FFFFFF", "#0B0D10", "none", "Crisp white + 2.5px stroke"),
    ("vlog_aesthetic_cream", "10. Soft Cream Vlog", "#FEF3C7", "none", "#1E293B", "Warm cream text + slate pill"),
]


class SubtitlePresetCard(QFrame):
    clicked = Signal(str)

    def __init__(self, preset_id: str, title: str, text_color: str, stroke_color: str, bg_color: str, desc: str = "", parent=None):
        super().__init__(parent)
        self.preset_id = preset_id
        self.title = title
        self.desc = desc
        self.is_selected = False
        self.setFixedHeight(54)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        # 16:9 Miniature Aspect Chip Preview
        self.chip = QFrame()
        self.chip.setFixedHeight(26)
        chip_css = "border-radius: 4px; padding: 1px 4px; "
        if bg_color and bg_color != "none":
            chip_css += f"background: {bg_color}; "
        else:
            chip_css += "background: rgba(11, 13, 16, 0.85); "
        self.chip.setStyleSheet(chip_css)

        chip_l = QHBoxLayout(self.chip)
        chip_l.setContentsMargins(0, 0, 0, 0)
        chip_l.setAlignment(Qt.AlignCenter)

        self.lbl_sample = QLabel("សួស្តីអ្នកទាំងអស់គ្នា")
        self.lbl_sample.setAlignment(Qt.AlignCenter)
        lbl_style = f"color: {text_color}; font-family: 'Kantumruy Pro', 'Khmer OS Battambang', 'Segoe UI', sans-serif; font-size: 10.5px; font-weight: bold;"
        if stroke_color and stroke_color != "none":
            lbl_style += f" border: 1.2px solid {stroke_color}; border-radius: 3px; padding: 0 4px;"
        self.lbl_sample.setStyleSheet(lbl_style)
        chip_l.addWidget(self.lbl_sample)

        self.lbl_name = QLabel(title)
        self.lbl_name.setStyleSheet("font-size: 9.5px; color: #8E95A5;")
        self.lbl_name.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.chip)
        layout.addWidget(self.lbl_name)
        self._update_style()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def enterEvent(self, event):
        if not self.is_selected:
            self.setStyleSheet(
                "SubtitlePresetCard { background: #1B212D; border: 1.5px solid #00E5FF; border-radius: 6px; }"
            )
            self.lbl_name.setStyleSheet("font-size: 9.5px; color: #FFFFFF; font-weight: 600; border: none; background: transparent;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._update_style()
        super().leaveEvent(event)

    def _update_style(self):
        if self.is_selected:
            self.setStyleSheet(
                "SubtitlePresetCard { background: #1A2230; border: 2px solid #00E5FF; border-radius: 6px; }"
            )
            self.lbl_name.setStyleSheet("font-size: 9.5px; color: #00E5FF; font-weight: bold; border: none; background: transparent;")
        else:
            self.setStyleSheet(
                "SubtitlePresetCard { background: #161920; border: 1px solid #252A36; border-radius: 6px; } "
                "SubtitlePresetCard:hover { background: #1B212D; border: 1.5px solid #00E5FF; }"
            )
            self.lbl_name.setStyleSheet("font-size: 9.5px; color: #8E95A5; border: none; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.preset_id)
        super().mousePressEvent(event)


class LutPresetCard(QFrame):
    """Visual color-grading / LUT preset card for the 20+ Adjustments & LUTs panel."""
    clicked = Signal(str)

    def __init__(self, preset: dict, parent=None):
        super().__init__(parent)
        self.preset_id = preset["id"]
        self.preset = preset
        self.is_selected = False
        self.setFixedHeight(58)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{preset['name']}\n{preset.get('desc', '')}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 4)
        lay.setSpacing(3)

        c1, c2 = preset.get("swatch", ("#1E293B", "#38BDF8"))
        self.swatch_bar = QFrame()
        self.swatch_bar.setFixedHeight(22)
        self.swatch_bar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c1}, stop:1 {c2}); "
            f"border-radius: 4px; border: 1px solid rgba(255,255,255,0.14);"
        )
        sw_l = QHBoxLayout(self.swatch_bar)
        sw_l.setContentsMargins(6, 0, 6, 0)
        lbl_cat = QLabel(preset.get("category", ""))
        lbl_cat.setStyleSheet(
            "color: rgba(255,255,255,0.92); background: rgba(0,0,0,0.45); "
            "border-radius: 3px; padding: 0 4px; font-size: 8.5px; font-weight: 700;"
        )
        sw_l.addStretch()
        sw_l.addWidget(lbl_cat)

        self.lbl_title = QLabel(preset.get("short", preset.get("name", preset["id"])))
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 9.8px; color: #CBD5E1; font-weight: 600; border: none; background: transparent;")

        lay.addWidget(self.swatch_bar)
        lay.addWidget(self.lbl_title)
        self.setMinimumWidth(0)
        self._update_style()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def enterEvent(self, event):
        if not self.is_selected:
            self.setStyleSheet("LutPresetCard { background: #1B212D; border: 1.5px solid #00E5FF; border-radius: 6px; }")
            self.lbl_title.setStyleSheet("font-size: 9.8px; color: #FFFFFF; font-weight: 700; border: none; background: transparent;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._update_style()
        super().leaveEvent(event)

    def _update_style(self):
        if self.is_selected:
            self.setStyleSheet("LutPresetCard { background: #1A2230; border: 2px solid #00E5FF; border-radius: 6px; }")
            self.lbl_title.setStyleSheet("font-size: 9.8px; color: #00E5FF; font-weight: 800; border: none; background: transparent;")
        else:
            self.setStyleSheet(
                "LutPresetCard { background: #161920; border: 1px solid #252A36; border-radius: 6px; } "
                "LutPresetCard:hover { background: #1B212D; border: 1.5px solid #00E5FF; }"
            )
            self.lbl_title.setStyleSheet("font-size: 9.8px; color: #CBD5E1; font-weight: 600; border: none; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.preset_id)
        super().mousePressEvent(event)


class LiveSubtitleItem(QGraphicsItem):
    """
    Studio-grade Live Khmer Subtitle Item for VideoPreviewEditor.
    Renders accurate outline stroke, drop shadow / glow, antialiased background box,
    and automatic line-wrapping without breaking Khmer subscripts (ជើង) and vowels.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.font = QFont("Khmer OS Battambang", 16, QFont.Bold)
        self.font.setFamilies(["Khmer OS Battambang", "Kantumruy Pro", "Noto Sans Khmer", "Khmer OS", "Segoe UI"])
        self.text_color = QColor(255, 255, 255)
        self.outline_color = QColor(0, 0, 0)
        self.outline_width = 2
        self.shadow_color = QColor(0, 0, 0, 180)
        self.shadow_dist = 2
        self.bg_color = QColor(0, 0, 0, 160)
        self.show_box = True
        self.max_width = 460.0
        self._rect = QRectF(0, 0, 10, 10)
        self._lines = []

    def setTextWidth(self, width: float):
        """Sets safe-zone maximum wrapping width (mirrors QGraphicsTextItem.setTextWidth)."""
        self.max_width = max(80.0, float(width))

    def boundingRect(self) -> QRectF:
        return self._rect

    def set_content(self, text: str, font: QFont, text_col: QColor, outline_col: QColor,
                    outline_w: int, shadow_col: QColor, shadow_dist: int,
                    bg_col: QColor, show_box: bool, max_w: float):
        self.text = (text or "").strip()
        self.font = QFont(font)
        fam = font.family()
        self.font.setFamilies([fam, "Khmer OS Battambang", "Kantumruy Pro", "Noto Sans Khmer", "Khmer OS", "Segoe UI"])
        self.text_color = text_col
        self.outline_color = outline_col
        self.outline_width = max(0, outline_w)
        self.shadow_color = shadow_col
        self.shadow_dist = max(0, shadow_dist)
        self.bg_color = bg_col
        self.show_box = show_box
        self.max_width = max(80.0, float(max_w))

        if not self.text:
            self.prepareGeometryChange()
            self._lines = []
            self._rect = QRectF(0, 0, 0, 0)
            self.update()
            return

        pad_x = 12 if self.show_box else 5
        pad_y = 6 if self.show_box else 3
        inner_max_w = max(60.0, self.max_width - (pad_x * 2) - (self.outline_width * 2) - self.shadow_dist)

        # Auto-scale font size down slightly if wrapped text exceeds 2 lines or safe width
        base_pt = max(9, self.font.pointSize() if self.font.pointSize() > 0 else 14)
        min_pt = max(9, int(round(base_pt * 0.68)))
        chosen_pt = base_pt
        fm = QFontMetrics(self.font)
        lines = self._wrap_khmer(self.text, fm, inner_max_w)
        while chosen_pt > min_pt and (
            len(lines) > 2 or max([fm.horizontalAdvance(l) for l in lines] or [0]) > inner_max_w
        ):
            chosen_pt -= 1
            self.font.setPointSize(chosen_pt)
            fm = QFontMetrics(self.font)
            lines = self._wrap_khmer(self.text, fm, inner_max_w)

        self._lines = lines
        line_h = fm.height()
        max_line_w = min(inner_max_w, max([fm.horizontalAdvance(l) for l in self._lines] or [20]))

        total_w = min(self.max_width, max_line_w + (pad_x * 2) + (self.outline_width * 2) + self.shadow_dist)
        total_h = (line_h * len(self._lines)) + (pad_y * 2) + (self.outline_width * 2) + self.shadow_dist

        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, total_w, total_h)
        self.update()

    @staticmethod
    def _wrap_khmer(text: str, fm: QFontMetrics, max_w: float) -> list:
        input_lines = text.split("\n")
        res_lines = []
        dependents = set([chr(c) for c in range(0x17B4, 0x17D4)] + [chr(0x17D2)])

        for raw_line in input_lines:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            words = raw_line.split(" ")
            for w in words:
                if not w:
                    continue
                if fm.horizontalAdvance(w) <= max_w:
                    if not res_lines:
                        res_lines.append(w)
                    elif fm.horizontalAdvance(res_lines[-1] + " " + w) <= max_w:
                        res_lines[-1] = res_lines[-1] + " " + w
                    else:
                        res_lines.append(w)
                else:
                    cur = ""
                    i = 0
                    while i < len(w):
                        chunk = w[i]
                        i += 1
                        while i < len(w):
                            if w[i] in dependents:
                                chunk += w[i]
                                i += 1
                            elif i + 1 < len(w) and w[i+1] == '\u17D2':
                                chunk += w[i]
                                i += 1
                            elif i > 0 and w[i-1] == '\u17D2':
                                chunk += w[i]
                                i += 1
                            else:
                                break
                        if fm.horizontalAdvance(cur + chunk) <= max_w:
                            cur += chunk
                        else:
                            if cur:
                                res_lines.append(cur)
                            cur = chunk
                    if cur:
                        res_lines.append(cur)
        return res_lines or [text]

    def paint(self, painter: QPainter, option, widget=None):
        if not self.text or not self._lines:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        fm = QFontMetrics(self.font)
        line_h = fm.height()
        ascent = fm.ascent()
        pad_x = 14 if self.show_box else 6
        pad_y = 6 if self.show_box else 3

        # 1. Rounded Background Box
        if self.show_box and self.bg_color.alpha() > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.bg_color))
            box_r = QRectF(0, 0, self._rect.width(), self._rect.height())
            painter.drawRoundedRect(box_r, 6, 6)

        # 2. Text Lines with Outline and Shadow
        for idx, line in enumerate(self._lines):
            lw = fm.horizontalAdvance(line)
            x = (self._rect.width() - lw) / 2.0
            y = pad_y + (idx * line_h) + ascent

            # Drop Shadow / Glow
            if self.shadow_dist > 0 and self.shadow_color.alpha() > 0:
                shadow_path = QPainterPath()
                shadow_path.addText(QPointF(x + self.shadow_dist, y + self.shadow_dist), self.font, line)
                painter.fillPath(shadow_path, QBrush(self.shadow_color))

            path = QPainterPath()
            path.addText(QPointF(x, y), self.font, line)

            # Outline Stroke
            if self.outline_width > 0 and self.outline_color.alpha() > 0:
                pen = QPen(self.outline_color, self.outline_width * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                painter.strokePath(path, pen)

            # Text Fill
            painter.fillPath(path, QBrush(self.text_color))


class LiveHookBannerItem(QGraphicsItem):
    """
    Live Top/Bottom Viral Hook Banner Overlay rendered directly on VideoPreviewEditor canvas.
    Mirrors MediaEngine._draw_hook_banner_on_painter proportions so preview == final export == thumbnail JPG.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rect = QRectF(0, 0, 480, 36)
        self.text = ""
        self.pos_mode = "top"
        self.bg_color = QColor("#D90429")
        self.text_color = QColor("#FFFFFF")
        self.font_family = "Kantumruy Pro"
        self.base_font_size = 28
        self.setZValue(40)

    def boundingRect(self) -> QRectF:
        return self._rect

    def configure(self, canvas_w: int, canvas_h: int, edits: dict):
        enabled = bool(edits.get("hook_enabled", 0))
        text = (edits.get("hook_text") or "").strip()
        if not enabled or not text:
            self.setVisible(False)
            return

        self.text = text
        self.pos_mode = str(edits.get("hook_pos", "top") or "top").lower().strip()
        bg_c = QColor(str(edits.get("hook_bg_color", "#D90429") or "#D90429"))
        self.bg_color = bg_c if bg_c.isValid() else QColor("#D90429")
        self.bg_color.setAlpha(242)
        txt_c = QColor(str(edits.get("hook_text_color", "#FFFFFF") or "#FFFFFF"))
        self.text_color = txt_c if txt_c.isValid() else QColor("#FFFFFF")
        self.font_family = (edits.get("sub_font_family") or "").strip() or "Kantumruy Pro"
        self.base_font_size = max(14, min(72, int(edits.get("hook_font_size", 28) or 28)))

        h_pct = max(6, min(26, int(edits.get("hook_height_pct", 12) or 12)))
        bar_h = max(24.0, canvas_h * (h_pct / 100.0))
        bar_y = 0.0 if self.pos_mode != "bottom" else max(0.0, canvas_h - bar_h)

        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, float(canvas_w), bar_h)
        self.setPos(0.0, bar_y)
        self.setVisible(True)
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        if not self.text or self._rect.width() <= 0 or self._rect.height() <= 0:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        w = self._rect.width()
        h = self._rect.height()
        painter.fillRect(self._rect, QBrush(self.bg_color))

        accent_h = max(1.5, h * 0.05)
        accent_y = (h - accent_h) if self.pos_mode != "bottom" else 0.0
        painter.fillRect(QRectF(0, accent_y, w, accent_h), QBrush(QColor(255, 255, 255, 190)))

        scale_ref = min(w, max(h / 0.12, 240.0)) / 480.0
        px = max(10, int(round(self.base_font_size * scale_ref * 0.72)))
        min_px = max(8, int(round(px * 0.50)))

        font = QFont(self.font_family)
        font.setFamilies([self.font_family, "Kantumruy Pro", "Khmer OS Battambang", "Noto Sans Khmer", "Khmer OS", "Segoe UI"])
        font.setBold(True)

        pad_x = max(8.0, w * 0.045)
        avail_w = max(40.0, w - pad_x * 2.0)
        avail_h = max(14.0, h * 0.84)

        lines = [self.text]
        while px >= min_px:
            font.setPixelSize(px)
            fm = QFontMetrics(font)
            lines = LiveSubtitleItem._wrap_khmer(self.text, fm, avail_w)
            max_lw = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
            if len(lines) <= 2 and max_lw <= avail_w and (fm.height() * len(lines)) <= avail_h:
                break
            lines = lines[:2]
            px -= 1

        font.setPixelSize(max(min_px, px))
        painter.setFont(font)
        fm = QFontMetrics(font)
        line_h = fm.height()
        start_y = (h - line_h * len(lines)) / 2.0

        for i, ln in enumerate(lines):
            r = QRectF(pad_x, start_y + i * line_h, avail_w, line_h)
            painter.setPen(QPen(QColor(0, 0, 0, 175)))
            painter.drawText(r.translated(1.0, 1.0), Qt.AlignCenter, ln)
            painter.setPen(QPen(self.text_color))
            painter.drawText(r, Qt.AlignCenter, ln)


class VideoPreviewEditor(QWidget):
    edits_changed = Signal(dict)
    position_ms_changed = Signal(int)
    position_synced = Signal(int)
    duration_ms_changed = Signal(int)
    playback_state_changed = Signal(bool)
    generate_hook_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.edits = {}
        self.masks_list = []
        self.active_mask_idx = 0
        self.mask_items = []
        self.canvas_w = 480
        self.canvas_h = 270
        self._native_wh = (16, 9)
        self._is_seeking = False

        self._build_ui()
        self._setup_player()

    def _build_ui(self):
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # --- 1. Interactive Video Canvas ---
        self.scene = QGraphicsScene(0, 0, self.canvas_w, self.canvas_h)
        self.view = QGraphicsView(self.scene)
        self.view.setMinimumHeight(260)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setStyleSheet("background-color: #0B0D10; border: 1px solid #252A36; border-radius: 8px;")
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.view.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.view.setCacheMode(QGraphicsView.CacheBackground)
        self.view.setInteractive(True)
        self.view.setDragMode(QGraphicsView.NoDrag)

        self.video_item = QGraphicsVideoItem()
        self.video_item.setSize(QRectF(0, 0, self.canvas_w, self.canvas_h).size())
        self.scene.addItem(self.video_item)

        # Color adjustment tint preview layer
        self.color_overlay = QGraphicsRectItem(0, 0, self.canvas_w, self.canvas_h)
        self.color_overlay.setPen(Qt.NoPen)
        self.color_overlay.setBrush(QBrush(QColor(0, 0, 0, 0)))
        self.scene.addItem(self.color_overlay)

        # Draggable Logo Overlay
        self.logo_item = DraggableOverlay(self._on_logo_dragged)
        self.logo_item.setZValue(10)
        self.scene.addItem(self.logo_item)

        # Live Viral Hook Banner Overlay (Top / Bottom Bar)
        self.hook_banner_item = LiveHookBannerItem()
        self.hook_banner_item.setVisible(False)
        self.scene.addItem(self.hook_banner_item)

        # Live Khmer Subtitle Preview Item (100% Studio Grade with Stroke, Shadow, Box)
        self.sub_live_item = LiveSubtitleItem()
        self.sub_live_item.setZValue(25)
        self.scene.addItem(self.sub_live_item)

        # Legacy backward-compatibility handles
        self.sub_bg_item = QGraphicsRectItem()
        self.sub_bg_item.setVisible(False)
        self.sub_text_item = self.sub_live_item

        layout.addWidget(self.view, 1)

        # --- 2A. Full-Width Timeline Scrubber Row (Top) ---
        timeline_row = QHBoxLayout()
        timeline_row.setContentsMargins(2, 4, 2, 0)
        timeline_row.setSpacing(8)

        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.sliderPressed.connect(lambda: setattr(self, "_is_seeking", True))
        self.timeline.sliderReleased.connect(self._on_seek_released)
        self.timeline.valueChanged.connect(self._on_timeline_moved)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11.5px; font-weight: 700; color: #00E5FF;")

        timeline_row.addWidget(self.timeline, 1)
        timeline_row.addWidget(self.lbl_time)
        layout.addLayout(timeline_row)

        # --- 2B. Centered Transport Control Buttons Row (Below Timeline) ---
        transport = QHBoxLayout()
        transport.setContentsMargins(0, 2, 0, 4)
        transport.setSpacing(8)
        transport.addStretch()

        self.btn_prev_line = QPushButton("|<")
        self.btn_prev_line.setObjectName("TransportBtn")
        self.btn_prev_line.setFixedSize(38, 28)
        self.btn_prev_line.setToolTip("ជួរមុន (Previous Subtitle Line)")
        self.btn_prev_line.clicked.connect(self.prev_segment)

        self.btn_back = QPushButton("<")
        self.btn_back.setObjectName("TransportBtn")
        self.btn_back.setFixedSize(38, 28)
        self.btn_back.setToolTip("ថយក្រោយ ២ វិនាទី (Rewind 2s - Left Arrow)")
        self.btn_back.clicked.connect(lambda: self.step_ms(-2000))

        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("PlayCircleBtn")
        self.btn_play.setFixedSize(38, 38)
        self.btn_play.setToolTip("លេង / ផ្អាក (Play / Pause - Ctrl+Space)")
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_forward = QPushButton(">")
        self.btn_forward.setObjectName("TransportBtn")
        self.btn_forward.setFixedSize(38, 28)
        self.btn_forward.setToolTip("ទៅមុខ ២ វិនាទី (Forward 2s - Right Arrow)")
        self.btn_forward.clicked.connect(lambda: self.step_ms(2000))

        self.btn_next_line = QPushButton(">|")
        self.btn_next_line.setObjectName("TransportBtn")
        self.btn_next_line.setFixedSize(38, 28)
        self.btn_next_line.setToolTip("ជួរបន្ទាប់ (Next Subtitle Line)")
        self.btn_next_line.clicked.connect(self.next_segment)

        self.transport_layout = QHBoxLayout()
        self.transport_layout.setContentsMargins(0, 0, 0, 0)
        self.transport_layout.setSpacing(8)
        for w in (
            self.btn_prev_line, self.btn_back, self.btn_play,
            self.btn_forward, self.btn_next_line
        ):
            self.transport_layout.addWidget(w)

        transport.addLayout(self.transport_layout)
        transport.addStretch()
        layout.addLayout(transport)

        # --- Studio Preset Toolbar (Hosted in Right Details Pane) ---
        self.preset_widget = QWidget()
        preset_box = QHBoxLayout(self.preset_widget)
        preset_box.setContentsMargins(0, 0, 0, 4)
        preset_box.setSpacing(6)

        lbl_preset = QLabel("🎨 Preset:")
        lbl_preset.setStyleSheet("font-weight: bold; font-size: 11px;")

        self.combo_presets = QComboBox()
        self.combo_presets.addItem("📋 -- ជ្រើសរើស Preset --", None)
        self.combo_presets.currentIndexChanged.connect(self._on_apply_preset)

        self.btn_save_preset = QPushButton("💾 Save")
        self.btn_save_preset.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.btn_save_preset.setToolTip("រក្សាទុក Style បច្ចុប្បន្ន (Logo, Mask, Subtitle, Ducking) ជាគំរូ Studio Preset")
        self.btn_save_preset.clicked.connect(self._on_save_preset)

        self.btn_del_preset = QPushButton("🗑")
        self.btn_del_preset.setToolTip("លុប Preset ដែលកំពុងរើសចោល")
        self.btn_del_preset.setFixedSize(32, 28)
        self.btn_del_preset.setStyleSheet("padding: 2px 4px; font-size: 12px;")
        self.btn_del_preset.clicked.connect(self._on_delete_preset)

        preset_box.addWidget(lbl_preset)
        preset_box.addWidget(self.combo_presets, 1)
        preset_box.addWidget(self.btn_save_preset)
        preset_box.addWidget(self.btn_del_preset)

        # --- 3. CapCut-Style 2-Row Segmented 7-Tab Inspector (All 7 Tabs 100% Visible, Zero Clipping!) ---
        self.inspector_nav_widget = QWidget()
        nav_v = QVBoxLayout(self.inspector_nav_widget)
        nav_v.setContentsMargins(0, 0, 0, 2)
        nav_v.setSpacing(4)
        nav_row1 = QHBoxLayout()
        nav_row1.setContentsMargins(0, 0, 0, 0)
        nav_row1.setSpacing(4)
        nav_row2 = QHBoxLayout()
        nav_row2.setContentsMargins(0, 0, 0, 0)
        nav_row2.setSpacing(4)

        self._nav_buttons = []
        nav_row1_defs = [
            ("🖼 Logo", 0),
            ("💬 Sub", 1),
            ("🎚 Audio", 2),
            ("🎨 LUTs", 3),
        ]
        nav_row2_defs = [
            ("✂ Cut && Intro", 4),
            ("🎭 Mask", 5),
            ("🖼️ Hook && Cover", 6),
        ]
        for label_n, tab_idx in nav_row1_defs:
            btn_n = QPushButton(label_n)
            btn_n.setCursor(Qt.PointingHandCursor)
            btn_n.setFixedHeight(27)
            btn_n.setMinimumWidth(0)
            btn_n.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            btn_n.clicked.connect(lambda _, ti=tab_idx: self.tabs.setCurrentIndex(ti))
            nav_row1.addWidget(btn_n, 1)
            self._nav_buttons.append(btn_n)
        for label_n, tab_idx in nav_row2_defs:
            btn_n = QPushButton(label_n)
            btn_n.setCursor(Qt.PointingHandCursor)
            btn_n.setFixedHeight(27)
            btn_n.setMinimumWidth(0)
            btn_n.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            btn_n.clicked.connect(lambda _, ti=tab_idx: self.tabs.setCurrentIndex(ti))
            nav_row2.addWidget(btn_n, 1)
            self._nav_buttons.append(btn_n)

        nav_v.addLayout(nav_row1)
        nav_v.addLayout(nav_row2)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { background-color: #12151B; border: 1px solid #252A36; border-radius: 8px; padding: 2px; }"
        )

        # Reusable helper to prevent QFrame QSS from cascading borders/padding onto child labels/checkboxes
        CARD_QSS = "QFrame#InspectorCard { background-color: #161920; border: 1px solid #252A36; border-radius: 8px; }"
        SCROLL_QSS = "QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }"

        # Tab A: Logo Watermark
        tab_logo = QWidget()
        logo_form = QFormLayout(tab_logo)
        logo_row = QHBoxLayout()
        btn_pick_logo = QPushButton("Choose Logo (.png)")
        btn_pick_logo.clicked.connect(self._choose_logo)
        btn_clear_logo = QPushButton("Remove")
        btn_clear_logo.clicked.connect(self._clear_logo)
        logo_row.addWidget(btn_pick_logo)
        logo_row.addWidget(btn_clear_logo)

        self.lbl_logo_info = QLabel("គ្មាន Logo ត្រូវបានជ្រើសរើសទេ")
        self.lbl_logo_info.setStyleSheet("color: #8E95A5; font-size: 11px; font-style: italic;")

        # 3x3 Interactive Anchor Dot Grid for Logo Watermark Position
        grid_widget = QWidget()
        grid_pos = QGridLayout(grid_widget)
        grid_pos.setSpacing(4)
        grid_pos.setContentsMargins(0, 0, 0, 0)

        anchors = [
            ("↖", "Top-Left (លើ-ឆ្វេង)", 0.03, 0.03, 0, 0),
            ("⬆", "Top-Center (លើ-កណ្ដាល)", 0.42, 0.03, 0, 1),
            ("↗", "Top-Right (លើ-ស្ដាំ)", 0.82, 0.03, 0, 2),
            ("⬅", "Center-Left (កណ្ដាល-ឆ្វេង)", 0.03, 0.45, 1, 0),
            ("🎯", "Center (ចំកណ្ដាល)", 0.42, 0.45, 1, 1),
            ("➡", "Center-Right (កណ្ដាល-ស្ដាំ)", 0.82, 0.45, 1, 2),
            ("↙", "Bottom-Left (ក្រោម-ឆ្វេង)", 0.03, 0.85, 2, 0),
            ("⬇", "Bottom-Center (ក្រោម-កណ្ដាល)", 0.42, 0.85, 2, 1),
            ("↘", "Bottom-Right (ក្រោម-ស្ដាំ)", 0.82, 0.85, 2, 2),
        ]
        self.anchor_buttons = []
        for icon, tooltip, rx, ry, r, c in anchors:
            b = QPushButton(icon)
            b.setFixedSize(36, 26)
            b.setToolTip(tooltip)
            b.setStyleSheet("background: #181C24; border: 1px solid #252A36; border-radius: 4px; font-size: 11px;")
            b.clicked.connect(lambda _, x=rx, y=ry: self._set_logo_preset(x, y))
            grid_pos.addWidget(b, r, c)
            self.anchor_buttons.append(b)

        # Logo Size Slider + Numeric Percentage Readout
        scale_box = QHBoxLayout()
        self.sl_logo_scale = QSlider(Qt.Horizontal)
        self.sl_logo_scale.setRange(5, 50)
        self.sl_logo_scale.setValue(15)
        self.lbl_logo_scale_val = QLabel("15%")
        self.lbl_logo_scale_val.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #00E5FF; min-width: 35px;")
        self.sl_logo_scale.valueChanged.connect(lambda v: (self.lbl_logo_scale_val.setText(f"{v}%"), self._sync_ui_to_edits()))
        scale_box.addWidget(self.sl_logo_scale, 1)
        scale_box.addWidget(self.lbl_logo_scale_val)

        # Logo Opacity Slider + Numeric Percentage Readout
        opacity_box = QHBoxLayout()
        self.sl_logo_opacity = QSlider(Qt.Horizontal)
        self.sl_logo_opacity.setRange(10, 100)
        self.sl_logo_opacity.setValue(90)
        self.lbl_logo_opacity_val = QLabel("90%")
        self.lbl_logo_opacity_val.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #00E5FF; min-width: 35px;")
        self.sl_logo_opacity.valueChanged.connect(lambda v: (self.lbl_logo_opacity_val.setText(f"{v}%"), self._sync_ui_to_edits()))
        opacity_box.addWidget(self.sl_logo_opacity, 1)
        opacity_box.addWidget(self.lbl_logo_opacity_val)

        logo_form.addRow("Watermark:", logo_row)
        logo_form.addRow("Status:", self.lbl_logo_info)
        logo_form.addRow("Position (3×3):", grid_widget)
        logo_form.addRow("Logo Size:", scale_box)
        logo_form.addRow("Opacity:", opacity_box)
        self.tabs.addTab(tab_logo, "🖼 Logo")

        # Tab B: Subtitle Style (100 Khmer Subtitle Styles & Visual Gallery)
        tab_sub = QWidget()
        sub_layout = QVBoxLayout(tab_sub)
        sub_layout.setContentsMargins(8, 8, 8, 8)
        sub_layout.setSpacing(8)

        self.chk_burn_subs = QCheckBox("បង្ហាញ && ដុតអក្សរខ្មែរចូលវីដេអូ (Burn Subtitles)")
        self.chk_burn_subs.setChecked(False)
        self.chk_burn_subs.setStyleSheet("font-weight: 700; color: #F4F6FB;")
        self.chk_burn_subs.stateChanged.connect(self._sync_ui_to_edits)
        sub_layout.addWidget(self.chk_burn_subs)

        # 1. Category Selector + Compact Filter Input Row
        cat_filter_row = QHBoxLayout()
        cat_filter_row.setSpacing(6)

        self.combo_sub_cat = QComboBox()
        self.combo_sub_cat.setFixedWidth(130)
        self.combo_sub_cat.setCursor(Qt.PointingHandCursor)
        self.combo_sub_cat.setStyleSheet(
            "background: #161920; color: #00E5FF; border: 1px solid #252A36; border-radius: 6px; padding: 3px 6px; font-weight: 700; font-size: 10.5px;"
        )
        self.combo_sub_cat.addItem("🌟 All (100)", "all")
        self.combo_sub_cat.addItem("🎬 Cinematic (15)", "Cinematic")
        self.combo_sub_cat.addItem("⚡ Neon & Cyberpunk (15)", "Neon & Cyberpunk")
        self.combo_sub_cat.addItem("💎 Luxury & Gold (12)", "Luxury & Gold")
        self.combo_sub_cat.addItem("📱 TikTok / Viral (18)", "Social Viral Pop")
        self.combo_sub_cat.addItem("🎨 Anime & Comic (15)", "Anime & Comic")
        self.combo_sub_cat.addItem("📺 Retro & Vintage (13)", "Retro & Vintage")
        self.combo_sub_cat.addItem("🧊 Minimalist (12)", "Modern Minimalist")
        self.combo_sub_cat.currentIndexChanged.connect(self._on_sub_cat_changed)

        self.sub_filter_input = QLineEdit()
        self.sub_filter_input.setPlaceholderText("🔍 Filter 100+ presets...")
        self.sub_filter_input.setStyleSheet(
            "background: #161920; border: 1px solid #252A36; border-radius: 6px; padding: 4px 8px; font-size: 11px; color: #F4F6FB;"
        )
        self.sub_filter_input.textChanged.connect(lambda t: self._filter_preset_gallery(t, self.combo_sub_cat.currentData()))

        cat_filter_row.addWidget(self.combo_sub_cat)
        cat_filter_row.addWidget(self.sub_filter_input)
        sub_layout.addLayout(cat_filter_row)

        # 2. Visual Preset Card Grid (2-Column Scrollable Area, Dark Viewport, Zero H-Overflow)
        self.sub_scroll = QScrollArea()
        self.sub_scroll.setFixedHeight(205)
        self.sub_scroll.setWidgetResizable(True)
        self.sub_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sub_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #252A36; border-radius: 6px; background-color: #12151B; } "
            "QScrollArea > QWidget > QWidget { background-color: #12151B; }"
        )
        self.grid_presets_container = QWidget()
        self.grid_presets_container.setStyleSheet("background-color: #12151B;")
        self.grid_presets = QGridLayout(self.grid_presets_container)
        self.grid_presets.setContentsMargins(6, 6, 6, 6)
        self.grid_presets.setSpacing(6)
        self.grid_presets.setColumnStretch(0, 1)
        self.grid_presets.setColumnStretch(1, 1)
        self.sub_scroll.setWidget(self.grid_presets_container)
        sub_layout.addWidget(self.sub_scroll)

        # Hidden Underlying Combos (for backwards compatibility)
        self.combo_sub_style = QComboBox()
        self.combo_sub_style.setVisible(False)
        self._populate_sub_styles("all")
        self.combo_sub_style.currentIndexChanged.connect(self._on_sub_style_changed)

        # 3. Two-Row Style Controls Card (Scoped QFrame#InspectorCard so child labels never inherit borders!)
        style_card = QFrame()
        style_card.setObjectName("InspectorCard")
        style_card.setStyleSheet(CARD_QSS)
        style_card_l = QVBoxLayout(style_card)
        style_card_l.setContentsMargins(8, 8, 8, 8)
        style_card_l.setSpacing(6)

        # Row 0: Khmer & Custom Font Family Selector (Live Preview + ASS Fontname)
        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        lbl_font = QLabel("🔤 Font ខ្មែរ:")
        lbl_font.setStyleSheet("font-size: 11px; color: #00E5FF; font-weight: 700;")
        self.combo_sub_font = QComboBox()
        self.combo_sub_font.setStyleSheet(
            "background: #12151B; color: #F4F6FB; border: 1px solid #2D3548; border-radius: 4px; padding: 3px 6px; font-size: 11px;"
        )
        self._populate_khmer_fonts()
        self.combo_sub_font.currentIndexChanged.connect(self._on_sub_font_changed)
        font_row.addWidget(lbl_font)
        font_row.addWidget(self.combo_sub_font, 1)
        style_card_l.addLayout(font_row)

        # Row 1: Font Size (spinbox) + Outline/Stroke (spinbox)
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        lbl_sz = QLabel("Font Size:")
        lbl_sz.setStyleSheet("font-size: 11px; color: #8E95A5;")
        self.spin_font = QSpinBox()
        self.spin_font.setRange(12, 72)
        self.spin_font.setValue(24)
        self.spin_font.setSuffix(" px")
        self.spin_font.setFixedWidth(68)
        self.spin_font.valueChanged.connect(self._sync_ui_to_edits)

        lbl_out = QLabel("Outline:")
        lbl_out.setStyleSheet("font-size: 11px; color: #8E95A5;")
        self.spin_outline = QSpinBox()
        self.spin_outline.setRange(0, 10)
        self.spin_outline.setValue(2)
        self.spin_outline.setSuffix(" px")
        self.spin_outline.setFixedWidth(64)
        self.spin_outline.valueChanged.connect(self._sync_ui_to_edits)

        row1.addWidget(lbl_sz)
        row1.addWidget(self.spin_font)
        row1.addStretch()
        row1.addWidget(lbl_out)
        row1.addWidget(self.spin_outline)
        style_card_l.addLayout(row1)

        # Row 2: [Color Swatch] Text Color button + [Color Swatch] Dark BG toggle pill
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.btn_sub_color = QPushButton("🎨 Text Color")
        self.btn_sub_color.setStyleSheet(
            "background: #181C24; border: 1px solid #252A36; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: 600; color: #F4F6FB;"
        )
        self.btn_sub_color.clicked.connect(self._pick_sub_color)

        self.chk_sub_bg = QCheckBox("⬛ Dark BG")
        self.chk_sub_bg.setChecked(True)
        self.chk_sub_bg.setStyleSheet("font-size: 11px; color: #F4F6FB;")
        self.chk_sub_bg.stateChanged.connect(self._sync_ui_to_edits)

        row2.addWidget(self.btn_sub_color, 1)
        row2.addWidget(self.chk_sub_bg, 1)
        style_card_l.addLayout(row2)
        sub_layout.addWidget(style_card)

        # 4. Vertical Position Slider
        y_box = QHBoxLayout()
        lbl_y = QLabel("Vertical Pos:")
        lbl_y.setStyleSheet("font-size: 11px; color: #8E95A5;")
        self.sl_sub_y = QSlider(Qt.Horizontal)
        self.sl_sub_y.setRange(10, 95)
        self.sl_sub_y.setValue(85)
        self.sl_sub_y.valueChanged.connect(self._sync_ui_to_edits)
        y_box.addWidget(lbl_y)
        y_box.addWidget(self.sl_sub_y, 1)
        sub_layout.addLayout(y_box)

        self._build_preset_gallery()
        self.tabs.addTab(tab_sub, "💬 Subtitle")

        # Tab C: Pro Audio FX & Smart Auto-Ducking Panel (Scrollable so cards NEVER squash!)
        tab_adj_scroll = QScrollArea()
        tab_adj_scroll.setWidgetResizable(True)
        tab_adj_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tab_adj_scroll.setFrameShape(QFrame.NoFrame)
        tab_adj_scroll.setStyleSheet(SCROLL_QSS)
        tab_adj = QWidget()
        adj_layout = QVBoxLayout(tab_adj)
        adj_layout.setContentsMargins(6, 6, 6, 8)
        adj_layout.setSpacing(8)

        # 1. Smart Auto-Ducking Card
        duck_card = QFrame()
        duck_card.setObjectName("InspectorCard")
        duck_card.setStyleSheet(CARD_QSS)
        duck_l = QVBoxLayout(duck_card)
        duck_l.setContentsMargins(10, 8, 10, 8)
        duck_l.setSpacing(6)

        d_head = QHBoxLayout()
        self.chk_ducking = QCheckBox("🎚 Smart Auto-Ducking")
        self.chk_ducking.setStyleSheet("font-size: 11.5px; font-weight: 700; color: #00E5FF;")
        self.chk_ducking.setChecked(True)
        self.chk_ducking.toggled.connect(self._sync_ui_to_edits)
        d_head.addWidget(self.chk_ducking)
        d_head.addStretch()
        duck_l.addLayout(d_head)

        lbl_duck_hint = QLabel("Lowers original video audio when Khmer AI speaks")
        lbl_duck_hint.setWordWrap(True)
        lbl_duck_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_duck_hint.setStyleSheet("font-size: 10px; color: #8E95A5;")
        duck_l.addWidget(lbl_duck_hint)

        reduc_row = QHBoxLayout()
        reduc_row.setSpacing(6)
        lbl_reduc = QLabel("Reduction:")
        lbl_reduc.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 62px;")
        self.sl_ducking_reduction = QSlider(Qt.Horizontal)
        self.sl_ducking_reduction.setRange(-30, 0)
        self.sl_ducking_reduction.setValue(-18)
        self.sl_ducking_reduction.valueChanged.connect(self._on_ducking_reduction_changed)
        self.lbl_ducking_db = QLabel("-18 dB")
        self.lbl_ducking_db.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_ducking_db.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #00E5FF; font-weight: bold; min-width: 44px;")
        reduc_row.addWidget(lbl_reduc)
        reduc_row.addWidget(self.sl_ducking_reduction, 1)
        reduc_row.addWidget(self.lbl_ducking_db)
        duck_l.addLayout(reduc_row)

        smooth_row = QHBoxLayout()
        smooth_row.setSpacing(4)
        lbl_smooth = QLabel("Fade:")
        lbl_smooth.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 34px;")
        self.duck_smoothness = "smooth"
        self.btn_duck_fast = QPushButton("Fast 100ms")
        self.btn_duck_smooth = QPushButton("Smooth 250ms")
        self.btn_duck_cinema = QPushButton("Cinema 500ms")
        for b_d in (self.btn_duck_fast, self.btn_duck_smooth, self.btn_duck_cinema):
            b_d.setMinimumWidth(0)
            b_d.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b_d.setFixedHeight(26)
        self.btn_duck_fast.clicked.connect(lambda: self._set_duck_smoothness("fast"))
        self.btn_duck_smooth.clicked.connect(lambda: self._set_duck_smoothness("smooth"))
        self.btn_duck_cinema.clicked.connect(lambda: self._set_duck_smoothness("cinema"))
        smooth_row.addWidget(lbl_smooth)
        smooth_row.addWidget(self.btn_duck_fast, 1)
        smooth_row.addWidget(self.btn_duck_smooth, 1)
        smooth_row.addWidget(self.btn_duck_cinema, 1)
        duck_l.addLayout(smooth_row)
        adj_layout.addWidget(duck_card)
        self._set_duck_smoothness("smooth")

        # 2. Voice Environment & Character FX Card (2x2 Grid)
        fx_card = QFrame()
        fx_card.setObjectName("InspectorCard")
        fx_card.setStyleSheet(CARD_QSS)
        fx_l = QVBoxLayout(fx_card)
        fx_l.setContentsMargins(10, 8, 10, 8)
        fx_l.setSpacing(6)

        lbl_fx_title = QLabel("🎤 Voice Environment & FX:")
        lbl_fx_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_fx_title.setStyleSheet("font-size: 11.5px; font-weight: 700; color: #A78BFA;")
        fx_l.addWidget(lbl_fx_title)

        fx_grid = QGridLayout()
        fx_grid.setSpacing(6)
        self.voice_fx = "clean"
        self.btn_fx_studio = QPushButton("🎙️ Studio Clean")
        self.btn_fx_thought = QPushButton("💭 Inner Thought")
        self.btn_fx_phone = QPushButton("📱 Phone Call")
        self.btn_fx_hall = QPushButton("📢 Hall / Echo")
        for b_f in (self.btn_fx_studio, self.btn_fx_thought, self.btn_fx_phone, self.btn_fx_hall):
            b_f.setMinimumWidth(0)
            b_f.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b_f.setFixedHeight(28)
        self.btn_fx_studio.clicked.connect(lambda: self._set_voice_fx("clean"))
        self.btn_fx_thought.clicked.connect(lambda: self._set_voice_fx("inner_thought"))
        self.btn_fx_phone.clicked.connect(lambda: self._set_voice_fx("phone"))
        self.btn_fx_hall.clicked.connect(lambda: self._set_voice_fx("hall"))
        fx_grid.addWidget(self.btn_fx_studio, 0, 0)
        fx_grid.addWidget(self.btn_fx_thought, 0, 1)
        fx_grid.addWidget(self.btn_fx_phone, 1, 0)
        fx_grid.addWidget(self.btn_fx_hall, 1, 1)
        fx_l.addLayout(fx_grid)
        adj_layout.addWidget(fx_card)
        self._set_voice_fx("clean")

        # 3. Master Gain & Loudness Normalization Card
        gain_card = QFrame()
        gain_card.setObjectName("InspectorCard")
        gain_card.setStyleSheet(CARD_QSS)
        gain_l = QVBoxLayout(gain_card)
        gain_l.setContentsMargins(10, 8, 10, 8)
        gain_l.setSpacing(6)

        dub_row = QHBoxLayout()
        dub_row.setSpacing(6)
        lbl_dub = QLabel("AI Dub Vol:")
        lbl_dub.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 66px;")
        self.sl_dub_vol = QSlider(Qt.Horizontal)
        self.sl_dub_vol.setRange(0, 200)
        self.sl_dub_vol.setValue(115)
        self.sl_dub_vol.valueChanged.connect(self._on_dub_vol_changed)
        self.lbl_dub_vol = QLabel("115%")
        self.lbl_dub_vol.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_dub_vol.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #00E5FF; font-weight: bold; min-width: 38px;")
        dub_row.addWidget(lbl_dub)
        dub_row.addWidget(self.sl_dub_vol, 1)
        dub_row.addWidget(self.lbl_dub_vol)
        gain_l.addLayout(dub_row)

        orig_row = QHBoxLayout()
        orig_row.setSpacing(6)
        lbl_orig = QLabel("Original Vol:")
        lbl_orig.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 66px;")
        self.sl_custom_bgm = QSlider(Qt.Horizontal)
        self.sl_custom_bgm.setRange(0, 100)
        self.sl_custom_bgm.setValue(25)
        self.sl_custom_bgm.valueChanged.connect(self._on_orig_vol_changed)
        self.lbl_orig_vol = QLabel("25%")
        self.lbl_orig_vol.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_orig_vol.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #00E5FF; font-weight: bold; min-width: 38px;")
        orig_row.addWidget(lbl_orig)
        orig_row.addWidget(self.sl_custom_bgm, 1)
        orig_row.addWidget(self.lbl_orig_vol)
        gain_l.addLayout(orig_row)

        self.chk_normalize = QCheckBox("✓ Auto-Normalize -14 LUFS (TikTok/YT)")
        self.chk_normalize.setChecked(True)
        self.chk_normalize.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chk_normalize.setStyleSheet("font-size: 10.5px; color: #10B981; font-weight: 600;")
        self.chk_normalize.toggled.connect(self._sync_ui_to_edits)
        gain_l.addWidget(self.chk_normalize)

        bgm_box = QHBoxLayout()
        bgm_box.setSpacing(6)
        self.btn_pick_bgm = QPushButton("🎵 រើសភ្លេង BGM (.mp3)")
        self.btn_pick_bgm.setMinimumWidth(0)
        self.btn_pick_bgm.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.btn_pick_bgm.setStyleSheet("background: #181C24; border: 1px solid #2D3548; border-radius: 5px; padding: 5px 8px; font-size: 11px; color: #F4F6FB;")
        self.btn_pick_bgm.clicked.connect(self._choose_custom_bgm)
        self.btn_clear_bgm = QPushButton("✕")
        self.btn_clear_bgm.setFixedSize(30, 28)
        self.btn_clear_bgm.setStyleSheet("background: #181C24; border: 1px solid #2D3548; border-radius: 5px; padding: 2px 4px; font-size: 12px; color: #F87171;")
        self.btn_clear_bgm.setToolTip("លុបភ្លេង BGM")
        self.btn_clear_bgm.clicked.connect(self._clear_custom_bgm)
        bgm_box.addWidget(self.btn_pick_bgm, 1)
        bgm_box.addWidget(self.btn_clear_bgm)
        gain_l.addLayout(bgm_box)
        adj_layout.addWidget(gain_card)

        # 4. Video Color Adjustments (Brightness, Contrast, Saturation)
        color_card = QFrame()
        color_card.setObjectName("InspectorCard")
        color_card.setStyleSheet(CARD_QSS)
        color_l = QVBoxLayout(color_card)
        color_l.setContentsMargins(10, 8, 10, 8)
        color_l.setSpacing(6)

        b_row = QHBoxLayout()
        b_row.setSpacing(6)
        lbl_b = QLabel("Brightness:")
        lbl_b.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 66px;")
        self.sl_bright = QSlider(Qt.Horizontal)
        self.sl_bright.setRange(-50, 50)
        self.sl_bright.setValue(0)
        self.sl_bright.valueChanged.connect(self._sync_ui_to_edits)
        b_row.addWidget(lbl_b)
        b_row.addWidget(self.sl_bright, 1)
        color_l.addLayout(b_row)

        c_row = QHBoxLayout()
        c_row.setSpacing(6)
        lbl_c = QLabel("Contrast:")
        lbl_c.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 66px;")
        self.sl_contrast = QSlider(Qt.Horizontal)
        self.sl_contrast.setRange(50, 180)
        self.sl_contrast.setValue(100)
        self.sl_contrast.valueChanged.connect(self._sync_ui_to_edits)
        c_row.addWidget(lbl_c)
        c_row.addWidget(self.sl_contrast, 1)
        color_l.addLayout(c_row)

        s_row = QHBoxLayout()
        s_row.setSpacing(6)
        lbl_s = QLabel("Saturation:")
        lbl_s.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 66px;")
        self.sl_sat = QSlider(Qt.Horizontal)
        self.sl_sat.setRange(0, 200)
        self.sl_sat.setValue(100)
        self.sl_sat.valueChanged.connect(self._sync_ui_to_edits)
        s_row.addWidget(lbl_s)
        s_row.addWidget(self.sl_sat, 1)
        color_l.addLayout(s_row)

        btn_reset_adj = QPushButton("↺ Reset Video Colors")
        btn_reset_adj.setMinimumWidth(0)
        btn_reset_adj.setStyleSheet("background: #181C24; border: 1px solid #2D3548; border-radius: 5px; padding: 5px 8px; font-size: 11px; color: #CBD5E1;")
        btn_reset_adj.clicked.connect(self._reset_adjustments)
        color_l.addWidget(btn_reset_adj)

        # Smart HD Clarity Upscaler & Frame Enhancer (Batch 2 Feature 4)
        self.chk_hd_upscale = QCheckBox("✨ HD Clarity Upscale && Sharpen (បង្កើនគុណភាពរូបភាពច្បាស់)")
        self.chk_hd_upscale.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chk_hd_upscale.setStyleSheet("font-size: 10.5px; font-weight: 800; color: #38BDF8; padding-top: 3px;")
        self.chk_hd_upscale.setToolTip(
            "អនុវត្ត FFmpeg Denoise + Sharpen (hqdn3d + unsharp) និង GPU acceleration ដើម្បីឲ្យវីដេអូព្រិលៗកាន់តែច្បាស់ស្អាត"
        )
        self.chk_hd_upscale.toggled.connect(self._on_hd_upscale_toggled)
        color_l.addWidget(self.chk_hd_upscale)

        self.chk_hd_1080p = QCheckBox("📐 Optional 1080p Lanczos Upscale (ពង្រីកដល់ 1080p)")
        self.chk_hd_1080p.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chk_hd_1080p.setEnabled(False)
        self.chk_hd_1080p.setStyleSheet("font-size: 10px; font-weight: 600; color: #94A3B8; padding-left: 16px;")
        self.chk_hd_1080p.toggled.connect(self._sync_ui_to_edits)
        color_l.addWidget(self.chk_hd_1080p)

        adj_layout.addWidget(color_card)
        adj_layout.addStretch()

        tab_adj_scroll.setWidget(tab_adj)
        self.tabs.addTab(tab_adj_scroll, "🎚 Audio FX")

        # Tab C2: 🎨 Adjustments & LUT Presets (ការកែសម្រួល ២០+ ប្រភេទ)
        tab_luts = QWidget()
        luts_layout = QVBoxLayout(tab_luts)
        luts_layout.setContentsMargins(8, 8, 8, 8)
        luts_layout.setSpacing(6)

        lut_header = QHBoxLayout()
        lbl_lut_hdr = QLabel("🎨 Adjustments & LUT Presets (ការកែសម្រួល ២០ ប្រភេទ)")
        lbl_lut_hdr.setStyleSheet("font-size: 11.5px; font-weight: 800; color: #00E5FF;")
        lut_header.addWidget(lbl_lut_hdr, 1)

        btn_reset_lut = QPushButton("↺ Reset")
        btn_reset_lut.setFixedHeight(24)
        btn_reset_lut.setStyleSheet(
            "background: #181C24; border: 1px solid #343B4C; border-radius: 4px; padding: 2px 8px; font-size: 10px; color: #CBD5E1;"
        )
        btn_reset_lut.clicked.connect(lambda: self._select_lut_preset("none"))
        lut_header.addWidget(btn_reset_lut)
        luts_layout.addLayout(lut_header)

        lut_filter_row = QHBoxLayout()
        lut_filter_row.setSpacing(6)

        self.combo_lut_cat = QComboBox()
        self.combo_lut_cat.setFixedWidth(118)
        self.combo_lut_cat.setStyleSheet(
            "background: #161920; color: #00E5FF; border: 1px solid #252A36; border-radius: 6px; padding: 3px 6px; font-weight: 700; font-size: 10.5px;"
        )
        for c in get_lut_categories():
            lbl_c = f"🌟 All ({len(LUT_PRESETS)})" if c == "All" else c
            self.combo_lut_cat.addItem(lbl_c, c)
        self.combo_lut_cat.currentIndexChanged.connect(
            lambda: self._filter_lut_gallery(self.lut_search_input.text(), self.combo_lut_cat.currentData())
        )

        self.lut_search_input = QLineEdit()
        self.lut_search_input.setPlaceholderText("🔍 ស្វែងរក LUT / FX ២០+ ប្រភេទ...")
        self.lut_search_input.setStyleSheet(
            "background: #161920; border: 1px solid #252A36; border-radius: 6px; padding: 4px 8px; font-size: 11px; color: #F4F6FB;"
        )
        self.lut_search_input.textChanged.connect(
            lambda t: self._filter_lut_gallery(t, self.combo_lut_cat.currentData())
        )

        lut_filter_row.addWidget(self.combo_lut_cat)
        lut_filter_row.addWidget(self.lut_search_input, 1)
        luts_layout.addLayout(lut_filter_row)

        self.lut_scroll = QScrollArea()
        self.lut_scroll.setMinimumHeight(210)
        self.lut_scroll.setWidgetResizable(True)
        self.lut_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lut_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #252A36; border-radius: 6px; background-color: #12151B; } "
            "QScrollArea > QWidget > QWidget { background-color: #12151B; }"
        )
        self.lut_grid_container = QWidget()
        self.lut_grid_container.setStyleSheet("background-color: #12151B;")
        self.lut_grid = QGridLayout(self.lut_grid_container)
        self.lut_grid.setContentsMargins(6, 6, 6, 6)
        self.lut_grid.setSpacing(6)
        self.lut_grid.setColumnStretch(0, 1)
        self.lut_grid.setColumnStretch(1, 1)
        self.lut_scroll.setWidget(self.lut_grid_container)
        luts_layout.addWidget(self.lut_scroll, 1)

        self.lbl_active_lut = QLabel("🎨 Active LUT: Original (ធម្មជាតិ / ដើម)")
        self.lbl_active_lut.setWordWrap(True)
        self.lbl_active_lut.setStyleSheet(
            "background: #161920; border: 1px solid #252A36; border-radius: 6px; "
            "padding: 6px 8px; font-size: 10.5px; color: #A7F3D0;"
        )
        luts_layout.addWidget(self.lbl_active_lut)

        self.lut_cards = {}
        self._filter_lut_gallery("", "All")
        self.tabs.addTab(tab_luts, "🎨 LUTs 20+")

        # Tab D: Crop / Aspect Ratio, Trim & Auto Intro/Outro Stitcher (Scrollable)
        tab_cut_scroll = QScrollArea()
        tab_cut_scroll.setWidgetResizable(True)
        tab_cut_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tab_cut_scroll.setFrameShape(QFrame.NoFrame)
        tab_cut_scroll.setStyleSheet(SCROLL_QSS)
        tab_cut = QWidget()
        cut_v = QVBoxLayout(tab_cut)
        cut_v.setContentsMargins(6, 6, 6, 8)
        cut_v.setSpacing(8)

        # Card 1: Aspect Ratio & Trim
        ratio_card = QFrame()
        ratio_card.setObjectName("InspectorCard")
        ratio_card.setStyleSheet(CARD_QSS)
        cut_form = QFormLayout(ratio_card)
        cut_form.setContentsMargins(10, 8, 10, 8)
        cut_form.setSpacing(6)
        cut_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.combo_ratio = QComboBox()
        self.combo_ratio.setMinimumWidth(0)
        self.combo_ratio.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_ratio.addItems(["original", "9:16 (TikTok / Reels)", "16:9 (YouTube)", "1:1 (Square)"])
        self.combo_ratio.currentIndexChanged.connect(self._sync_ui_to_edits)

        trim_row = QHBoxLayout()
        trim_row.setSpacing(4)
        btn_set_in = QPushButton("Start [")
        btn_set_in.clicked.connect(self._set_trim_start)
        btn_set_out = QPushButton("End ]")
        btn_set_out.clicked.connect(self._set_trim_end)
        btn_clear_trim = QPushButton("Reset")
        btn_clear_trim.clicked.connect(self._clear_trim)
        for bt in (btn_set_in, btn_set_out, btn_clear_trim):
            bt.setMinimumWidth(0)
            bt.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            bt.setStyleSheet("padding: 4px 4px; font-size: 10.5px;")
        trim_row.addWidget(btn_set_in, 1)
        trim_row.addWidget(btn_set_out, 1)
        trim_row.addWidget(btn_clear_trim, 1)

        self.lbl_trim_info = QLabel("Full Video (No Trim)")
        self.lbl_trim_info.setStyleSheet("font-size: 11px; color: #94A3B8;")

        cut_form.addRow("Ratio:", self.combo_ratio)
        cut_form.addRow("Trim:", trim_row)
        cut_form.addRow("", self.lbl_trim_info)
        cut_v.addWidget(ratio_card)

        # Card 2: Auto Intro & Outro Stitcher (Feature 4)
        io_card = QFrame()
        io_card.setObjectName("InspectorCard")
        io_card.setStyleSheet(CARD_QSS)
        io_l = QVBoxLayout(io_card)
        io_l.setContentsMargins(10, 8, 10, 8)
        io_l.setSpacing(6)

        lbl_io_hdr = QLabel("🎬 Auto Intro & Outro Stitcher (ភ្ជាប់ Intro/Outro)")
        lbl_io_hdr.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_io_hdr.setStyleSheet("font-size: 11.5px; font-weight: 800; color: #00E5FF;")
        io_l.addWidget(lbl_io_hdr)

        lbl_io_hint = QLabel("ភ្ជាប់ [Intro] + [រឿងបញ្ចូលសំឡេង] + [Outro] ដោយស្វ័យប្រវត្តិពេល Export")
        lbl_io_hint.setWordWrap(True)
        lbl_io_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_io_hint.setStyleSheet("font-size: 10px; color: #8E95A5;")
        io_l.addWidget(lbl_io_hint)

        # Intro Controls
        self.chk_intro_enabled = QCheckBox("▶ បើក Intro Video (.mp4)")
        self.chk_intro_enabled.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chk_intro_enabled.setStyleSheet("font-size: 11px; font-weight: 700; color: #34D399;")
        self.chk_intro_enabled.stateChanged.connect(self._sync_ui_to_edits)
        io_l.addWidget(self.chk_intro_enabled)

        intro_row = QHBoxLayout()
        intro_row.setSpacing(5)
        self.btn_pick_intro = QPushButton("📁 រើស Intro (.mp4)")
        self.btn_pick_intro.setMinimumWidth(0)
        self.btn_pick_intro.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.btn_pick_intro.setStyleSheet("background: #181C24; border: 1px solid #2D3548; border-radius: 5px; padding: 5px 8px; font-size: 10.5px; color: #F4F6FB;")
        self.btn_pick_intro.clicked.connect(self._choose_intro_video)
        self.btn_clear_intro = QPushButton("✕")
        self.btn_clear_intro.setFixedSize(30, 28)
        self.btn_clear_intro.setStyleSheet("background: #181C24; border: 1px solid #2D3548; border-radius: 5px; padding: 2px 4px; font-size: 12px; color: #F87171;")
        self.btn_clear_intro.setToolTip("លុប Intro Video")
        self.btn_clear_intro.clicked.connect(self._clear_intro_video)
        intro_row.addWidget(self.btn_pick_intro, 1)
        intro_row.addWidget(self.btn_clear_intro)
        io_l.addLayout(intro_row)

        self.lbl_intro_info = QLabel("មិនទាន់ជ្រើសរើស Intro Video ទេ")
        self.lbl_intro_info.setWordWrap(True)
        self.lbl_intro_info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_intro_info.setStyleSheet("font-size: 10px; color: #8E95A5; font-style: italic;")
        io_l.addWidget(self.lbl_intro_info)

        # Outro Controls
        self.chk_outro_enabled = QCheckBox("⏹ បើក Outro Video (.mp4)")
        self.chk_outro_enabled.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chk_outro_enabled.setStyleSheet("font-size: 11px; font-weight: 700; color: #F59E0B;")
        self.chk_outro_enabled.stateChanged.connect(self._sync_ui_to_edits)
        io_l.addWidget(self.chk_outro_enabled)

        outro_row = QHBoxLayout()
        outro_row.setSpacing(5)
        self.btn_pick_outro = QPushButton("📁 រើស Outro (.mp4)")
        self.btn_pick_outro.setMinimumWidth(0)
        self.btn_pick_outro.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.btn_pick_outro.setStyleSheet("background: #181C24; border: 1px solid #2D3548; border-radius: 5px; padding: 5px 8px; font-size: 10.5px; color: #F4F6FB;")
        self.btn_pick_outro.clicked.connect(self._choose_outro_video)
        self.btn_clear_outro = QPushButton("✕")
        self.btn_clear_outro.setFixedSize(30, 28)
        self.btn_clear_outro.setStyleSheet("background: #181C24; border: 1px solid #2D3548; border-radius: 5px; padding: 2px 4px; font-size: 12px; color: #F87171;")
        self.btn_clear_outro.setToolTip("លុប Outro Video")
        self.btn_clear_outro.clicked.connect(self._clear_outro_video)
        outro_row.addWidget(self.btn_pick_outro, 1)
        outro_row.addWidget(self.btn_clear_outro)
        io_l.addLayout(outro_row)

        self.lbl_outro_info = QLabel("មិនទាន់ជ្រើសរើស Outro Video ទេ")
        self.lbl_outro_info.setWordWrap(True)
        self.lbl_outro_info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_outro_info.setStyleSheet("font-size: 10px; color: #8E95A5; font-style: italic;")
        io_l.addWidget(self.lbl_outro_info)

        cut_v.addWidget(io_card)
        cut_v.addStretch()
        tab_cut_scroll.setWidget(tab_cut)
        self.tabs.addTab(tab_cut_scroll, "✂ Cut & Ratio")

        # Tab E: Multi-Mask បិទអក្សរដើម (Watermark, Hard-sub, Logo) — Scrollable & Zero-Clipping
        tab_mask_scroll = QScrollArea()
        tab_mask_scroll.setWidgetResizable(True)
        tab_mask_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tab_mask_scroll.setFrameShape(QFrame.NoFrame)
        tab_mask_scroll.setStyleSheet(SCROLL_QSS)
        tab_mask = QWidget()
        mask_form = QFormLayout(tab_mask)
        mask_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        mask_form.setContentsMargins(6, 6, 6, 8)
        mask_form.setSpacing(6)

        mask_select_row = QHBoxLayout()
        mask_select_row.setSpacing(4)
        self.combo_mask_select = QComboBox()
        self.combo_mask_select.setMinimumWidth(0)
        self.combo_mask_select.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_mask_select.currentIndexChanged.connect(self._on_mask_select_changed)

        self.btn_add_mask = QPushButton("➕ Mask")
        self.btn_add_mask.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        self.btn_add_mask.setToolTip("បន្ថែម Mask ថ្មីមួយទៀត (បិទ Watermark ឬ Logo)")
        self.btn_add_mask.clicked.connect(self._add_mask)

        self.btn_del_mask = QPushButton("🗑")
        self.btn_del_mask.setFixedSize(32, 28)
        self.btn_del_mask.setStyleSheet("padding: 2px 4px; font-size: 12px;")
        self.btn_del_mask.setToolTip("លុប Mask ដែលកំពុងរើស")
        self.btn_del_mask.clicked.connect(self._delete_mask)

        mask_select_row.addWidget(self.combo_mask_select, 1)
        mask_select_row.addWidget(self.btn_add_mask)
        mask_select_row.addWidget(self.btn_del_mask)

        top_mask_row = QHBoxLayout()
        top_mask_row.setSpacing(4)
        self.chk_mask = QCheckBox("បើក Mask")
        self.chk_mask.stateChanged.connect(self._sync_mask_controls_to_edits)

        self.combo_mask_mode = QComboBox()
        self.combo_mask_mode.setMinimumWidth(0)
        self.combo_mask_mode.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_mask_mode.addItems(["Blur (ព្រិល)", "Solid Box (ប្រអប់ពណ៌)"])
        self.combo_mask_mode.currentIndexChanged.connect(self._sync_mask_controls_to_edits)

        self.btn_mask_color = QPushButton("ពណ៌")
        self.btn_mask_color.setFixedWidth(48)
        self.btn_mask_color.setStyleSheet("padding: 4px 6px; font-size: 11px;")
        self.btn_mask_color.clicked.connect(self._pick_mask_color)

        top_mask_row.addWidget(self.chk_mask)
        top_mask_row.addWidget(self.combo_mask_mode, 1)
        top_mask_row.addWidget(self.btn_mask_color)

        self.sl_mask_strength = QSlider(Qt.Horizontal)
        self.sl_mask_strength.setRange(10, 100)
        self.sl_mask_strength.setValue(75)
        self.sl_mask_strength.valueChanged.connect(self._sync_mask_controls_to_edits)

        size_row = QHBoxLayout()
        self.sl_mask_w = QSlider(Qt.Horizontal)
        self.sl_mask_w.setRange(5, 100)
        self.sl_mask_w.setValue(90)
        self.sl_mask_w.valueChanged.connect(self._sync_mask_controls_to_edits)

        self.sl_mask_h = QSlider(Qt.Horizontal)
        self.sl_mask_h.setRange(3, 50)
        self.sl_mask_h.setValue(14)
        self.sl_mask_h.valueChanged.connect(self._sync_mask_controls_to_edits)

        size_row.addWidget(QLabel("W:"))
        size_row.addWidget(self.sl_mask_w)
        size_row.addWidget(QLabel("H:"))
        size_row.addWidget(self.sl_mask_h)

        preset_grid = QGridLayout()
        preset_grid.setSpacing(4)
        btn_pre_tl = QPushButton("↖ លើ-ឆ្វេង")
        btn_pre_tr = QPushButton("↗ លើ-ស្តាំ")
        btn_pre_bot = QPushButton("⏹ បាតក្រោម")
        btn_pre_cen = QPushButton("🎯 កណ្តាល")
        for bp in (btn_pre_tl, btn_pre_tr, btn_pre_bot, btn_pre_cen):
            bp.setMinimumWidth(0)
            bp.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            bp.setStyleSheet("padding: 4px 4px; font-size: 10.5px;")
        btn_pre_tl.clicked.connect(lambda: self._set_mask_preset(0.03, 0.03, 0.28, 0.10))
        btn_pre_tr.clicked.connect(lambda: self._set_mask_preset(0.69, 0.03, 0.28, 0.10))
        btn_pre_bot.clicked.connect(lambda: self._set_mask_preset(0.05, 0.78, 0.90, 0.14))
        btn_pre_cen.clicked.connect(lambda: self._set_mask_preset(0.20, 0.40, 0.60, 0.20))
        preset_grid.addWidget(btn_pre_tl, 0, 0)
        preset_grid.addWidget(btn_pre_tr, 0, 1)
        preset_grid.addWidget(btn_pre_bot, 1, 0)
        preset_grid.addWidget(btn_pre_cen, 1, 1)

        # Timed Dynamic Auto-Blur Visual Feedback Toggler (Scoped QFrame#TimedCard!)
        timed_card = QFrame()
        timed_card.setObjectName("TimedCard")
        timed_card.setStyleSheet(
            "QFrame#TimedCard { background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 7px; }"
        )
        timed_v = QVBoxLayout(timed_card)
        timed_v.setContentsMargins(8, 6, 8, 6)
        timed_v.setSpacing(4)

        self.chk_auto_timed_blur = QCheckBox("⏱️ Blur តាមម៉ោង និងទីតាំង (Auto Timed Blur)")
        self.chk_auto_timed_blur.setChecked(True)
        self.chk_auto_timed_blur.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chk_auto_timed_blur.setStyleSheet("font-size: 10.5px; font-weight: 800; color: #34D399;")
        self.chk_auto_timed_blur.setToolTip(
            "បាំង Blur តែពេលមានអក្សរចិនលោតលើអេក្រង់ — ពេលអក្សរបាត់ វីដេអូដើរស្អាត ១០០% (Direct Pass-Through 0% Blur)"
        )
        self.chk_auto_timed_blur.stateChanged.connect(self._on_auto_timed_blur_toggled)
        timed_v.addWidget(self.chk_auto_timed_blur)

        self.lbl_blur_live_state = QLabel("⚪ NO TEXT — Direct Pass-Through (0% Blur)")
        self.lbl_blur_live_state.setWordWrap(True)
        self.lbl_blur_live_state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_blur_live_state.setStyleSheet("font-size: 10px; color: #94A3B8; font-weight: 600;")
        timed_v.addWidget(self.lbl_blur_live_state)

        mask_form.addRow(timed_card)
        mask_form.addRow("Mask:", mask_select_row)
        mask_form.addRow("កំណត់:", top_mask_row)
        mask_form.addRow("កម្រិត:", self.sl_mask_strength)
        mask_form.addRow("ទំហំ:", size_row)
        mask_form.addRow("ទីតាំង:", preset_grid)
        tab_mask_scroll.setWidget(tab_mask)
        self.tabs.addTab(tab_mask_scroll, "🎭 Mask")

        # Tab F: 🖼️ Hook Banner & Cover (AI Viral Hook Title + Banner Overlay + Native-Res Thumbnail JPG)
        tab_hook_scroll = QScrollArea()
        tab_hook_scroll.setWidgetResizable(True)
        tab_hook_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tab_hook_scroll.setFrameShape(QFrame.NoFrame)
        tab_hook_scroll.setStyleSheet(SCROLL_QSS)
        tab_hook = QWidget()
        hook_v = QVBoxLayout(tab_hook)
        hook_v.setContentsMargins(6, 6, 6, 8)
        hook_v.setSpacing(8)

        # Card 1: AI Viral Hook Title & Live Banner Overlay
        hook_card = QFrame()
        hook_card.setObjectName("InspectorCard")
        hook_card.setStyleSheet(CARD_QSS)
        hk_l = QVBoxLayout(hook_card)
        hk_l.setContentsMargins(10, 8, 10, 8)
        hk_l.setSpacing(6)

        self.chk_hook_enabled = QCheckBox("🖼️ បើក Hook Banner Overlay (លើវីដេអូ && Cover)")
        self.chk_hook_enabled.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chk_hook_enabled.setStyleSheet("font-size: 10.5px; font-weight: 800; color: #F59E0B;")
        self.chk_hook_enabled.stateChanged.connect(self._sync_ui_to_edits)
        hk_l.addWidget(self.chk_hook_enabled)

        self.btn_ai_hook = QPushButton("✨ AI Generate Viral Hook Title")
        self.btn_ai_hook.setCursor(Qt.PointingHandCursor)
        self.btn_ai_hook.setMinimumWidth(0)
        self.btn_ai_hook.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.btn_ai_hook.setFixedHeight(32)
        self.btn_ai_hook.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #06B6D4); "
            "color: #FFFFFF; font-weight: 800; font-size: 11px; border: none; border-radius: 6px; padding: 4px 10px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8B5CF6, stop:1 #22D3EE); } "
            "QPushButton:disabled { background: #252A36; color: #64748B; }"
        )
        self.btn_ai_hook.setToolTip("ឲ្យ AI សង្ខេបសាច់រឿងភាគនេះជាចំណងជើង Viral ១ ជួរទាក់ទាញភ្នែក")
        self.btn_ai_hook.clicked.connect(self.generate_hook_requested.emit)
        hk_l.addWidget(self.btn_ai_hook)

        lbl_hk_txt = QLabel("📝 ចំណងជើង Hook Banner (អក្សរខ្មែរ):")
        lbl_hk_txt.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_hk_txt.setStyleSheet("font-size: 10.5px; color: #CBD5E1; font-weight: 600;")
        hk_l.addWidget(lbl_hk_txt)

        self.edit_hook_text = QLineEdit()
        self.edit_hook_text.setMinimumWidth(0)
        self.edit_hook_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.edit_hook_text.setPlaceholderText("ឧ. ភាគទី១៖ នាងត្រូវគេមើលងាយ តែការពិតគឺជាកូនស្រីមហាសេដ្ឋី!")
        self.edit_hook_text.setStyleSheet(
            "background: #12151B; border: 1px solid #343B4C; border-radius: 5px; padding: 5px 8px; "
            "font-family: 'Kantumruy Pro', 'Khmer OS Battambang', sans-serif; font-size: 11px; color: #F4F6FB;"
        )
        self.edit_hook_text.textChanged.connect(self._on_hook_text_edited)
        hk_l.addWidget(self.edit_hook_text)

        # Position selector
        pos_row = QHBoxLayout()
        pos_row.setSpacing(6)
        lbl_hk_pos = QLabel("ទីតាំង:")
        lbl_hk_pos.setStyleSheet("font-size: 11px; color: #CBD5E1; min-width: 42px;")
        self.combo_hook_pos = QComboBox()
        self.combo_hook_pos.setMinimumWidth(0)
        self.combo_hook_pos.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_hook_pos.addItem("⬆️ ខាងលើ (Top Banner)", "top")
        self.combo_hook_pos.addItem("⬇️ ខាងក្រោម (Bottom Banner)", "bottom")
        self.combo_hook_pos.currentIndexChanged.connect(self._sync_ui_to_edits)
        pos_row.addWidget(lbl_hk_pos)
        pos_row.addWidget(self.combo_hook_pos, 1)
        hk_l.addLayout(pos_row)

        # Bar Color & Text Color + Quick Swatches
        col_row = QHBoxLayout()
        col_row.setSpacing(5)
        self.btn_hook_bg_color = QPushButton("🎨 Bar Color")
        self.btn_hook_bg_color.setMinimumWidth(0)
        self.btn_hook_bg_color.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.btn_hook_bg_color.setStyleSheet("background: #D90429; color: #FFFFFF; border: 1px solid #475569; border-radius: 5px; padding: 4px 6px; font-size: 10.5px; font-weight: 700;")
        self.btn_hook_bg_color.clicked.connect(self._pick_hook_bg_color)

        self.btn_hook_text_color = QPushButton("🔤 Text Color")
        self.btn_hook_text_color.setMinimumWidth(0)
        self.btn_hook_text_color.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.btn_hook_text_color.setStyleSheet("background: #181C24; color: #FFFFFF; border: 1px solid #475569; border-radius: 5px; padding: 4px 6px; font-size: 10.5px; font-weight: 700;")
        self.btn_hook_text_color.clicked.connect(self._pick_hook_text_color)
        col_row.addWidget(self.btn_hook_bg_color, 1)
        col_row.addWidget(self.btn_hook_text_color, 1)
        hk_l.addLayout(col_row)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(4)
        for sw_lbl, sw_bg, sw_fg in (
            ("🔴 Red", "#D90429", "#FFFFFF"),
            ("🟡 Gold", "#F59E0B", "#0B0D10"),
            ("🔵 Royal", "#1D4ED8", "#FFFFFF"),
            ("⚫ Dark", "#111827", "#FACC15"),
        ):
            bs = QPushButton(sw_lbl)
            bs.setMinimumWidth(0)
            bs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            bs.setFixedHeight(24)
            bs.setStyleSheet(f"background: {sw_bg}; color: {sw_fg}; border: 1px solid #334155; border-radius: 4px; padding: 2px 3px; font-size: 9.5px; font-weight: 700;")
            bs.clicked.connect(lambda _, bg=sw_bg, fg=sw_fg: self._apply_hook_color_preset(bg, fg))
            swatch_row.addWidget(bs, 1)
        hk_l.addLayout(swatch_row)

        # Banner Height % slider
        hh_row = QHBoxLayout()
        hh_row.setSpacing(6)
        lbl_hh = QLabel("កម្ពស់ Bar:")
        lbl_hh.setStyleSheet("font-size: 10.5px; color: #CBD5E1; min-width: 58px;")
        self.sl_hook_height = QSlider(Qt.Horizontal)
        self.sl_hook_height.setRange(6, 24)
        self.sl_hook_height.setValue(12)
        self.lbl_hook_height_val = QLabel("12%")
        self.lbl_hook_height_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_hook_height_val.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: #00E5FF; min-width: 34px;")
        self.sl_hook_height.valueChanged.connect(lambda v: (self.lbl_hook_height_val.setText(f"{v}%"), self._sync_ui_to_edits()))
        hh_row.addWidget(lbl_hh)
        hh_row.addWidget(self.sl_hook_height, 1)
        hh_row.addWidget(self.lbl_hook_height_val)
        hk_l.addLayout(hh_row)

        # Hook Font Size slider
        hf_row = QHBoxLayout()
        hf_row.setSpacing(6)
        lbl_hf = QLabel("ទំហំអក្សរ:")
        lbl_hf.setStyleSheet("font-size: 10.5px; color: #CBD5E1; min-width: 58px;")
        self.sl_hook_font_size = QSlider(Qt.Horizontal)
        self.sl_hook_font_size.setRange(16, 52)
        self.sl_hook_font_size.setValue(28)
        self.lbl_hook_font_val = QLabel("28px")
        self.lbl_hook_font_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_hook_font_val.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: #00E5FF; min-width: 34px;")
        self.sl_hook_font_size.valueChanged.connect(lambda v: (self.lbl_hook_font_val.setText(f"{v}px"), self._sync_ui_to_edits()))
        hf_row.addWidget(lbl_hf)
        hf_row.addWidget(self.sl_hook_font_size, 1)
        hf_row.addWidget(self.lbl_hook_font_val)
        hk_l.addLayout(hf_row)

        hook_v.addWidget(hook_card)

        # Card 2: 1-Click Native-Resolution Thumbnail Cover Export (.jpg)
        thumb_card = QFrame()
        thumb_card.setObjectName("InspectorCard")
        thumb_card.setStyleSheet(CARD_QSS)
        th_l = QVBoxLayout(thumb_card)
        th_l.setContentsMargins(10, 8, 10, 8)
        th_l.setSpacing(6)

        lbl_th_hdr = QLabel("📸 Thumbnail Cover Generator (គម្របវីដេអូ)")
        lbl_th_hdr.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_th_hdr.setStyleSheet("font-size: 11.5px; font-weight: 800; color: #34D399;")
        th_l.addWidget(lbl_th_hdr)

        lbl_th_desc = QLabel("ចាប់យករូបភាព Frame បច្ចុប្បន្ន + Hook Banner + Logo ក្នុងកម្រិតច្បាស់ដើម ១០០% សម្រាប់ YouTube / Facebook / TikTok")
        lbl_th_desc.setWordWrap(True)
        lbl_th_desc.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_th_desc.setStyleSheet("font-size: 10px; color: #8E95A5;")
        th_l.addWidget(lbl_th_desc)

        self.btn_save_thumbnail = QPushButton("📸 Save Thumbnail (.jpg)")
        self.btn_save_thumbnail.setCursor(Qt.PointingHandCursor)
        self.btn_save_thumbnail.setFixedHeight(34)
        self.btn_save_thumbnail.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #10B981); "
            "color: #FFFFFF; font-weight: 800; font-size: 11.5px; border: none; border-radius: 6px; padding: 4px 10px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #34D399); }"
        )
        self.btn_save_thumbnail.clicked.connect(self._save_thumbnail_jpg)
        th_l.addWidget(self.btn_save_thumbnail)

        hook_v.addWidget(thumb_card)
        hook_v.addStretch()
        tab_hook_scroll.setWidget(tab_hook)
        self.tabs.addTab(tab_hook_scroll, "🖼️ Hook Banner & Cover")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._update_nav_buttons(0)

        layout.addWidget(self.inspector_nav_widget)
        layout.addWidget(self.tabs)

    def _update_nav_buttons(self, active_index: int):
        nav_act = (
            "background: #1A2433; color: #00E5FF; border: 1.5px solid #00E5FF; "
            "border-radius: 6px; padding: 3px 4px; font-size: 10.5px; font-weight: 800;"
        )
        nav_inact = (
            "background: #181C24; color: #94A3B8; border: 1px solid #252A36; "
            "border-radius: 6px; padding: 3px 4px; font-size: 10.5px; font-weight: 600;"
        )
        for i, btn in enumerate(getattr(self, "_nav_buttons", [])):
            btn.setStyleSheet(nav_act if i == active_index else nav_inact)

    def _on_tab_changed(self, index: int):
        self._update_nav_buttons(index)
        # បើចុចចូល Tab Mask ហើយមិនទាន់ធីក ឲ្យធីកបង្ហាញប្រអប់ Mask លើវីដេអូភ្លាមៗ
        if "Mask" in self.tabs.tabText(index) and not self.chk_mask.isChecked():
            self.chk_mask.setChecked(True)

    def showEvent(self, event):
        super().showEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def _setup_player(self):
        # ប្រើ QMediaPlayer តែមួយគត់ (រូបភាព + សំឡេងខ្មែរដើរក្នុង Stream តែមួយ = រលូន 100% គ្មានទាក់!)
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(1.0)
        self.player.setAudioOutput(self.audio_out)
        self.player.setVideoOutput(self.video_item)

        self.original_video_path = ""
        self.dubbed_preview_path = ""
        self.has_dub_track = False

        self.video_item.nativeSizeChanged.connect(self._on_native_size_changed)
        self.player.positionChanged.connect(self._on_pos_changed)
        self.player.durationChanged.connect(self._on_dur_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.mediaStatusChanged.connect(
            lambda st: self.btn_play.setText("▶") if st == QMediaPlayer.EndOfMedia else None
        )

    def _on_playback_state_changed(self, state):
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        self.btn_play.setText("⏸" if is_playing else "▶")
        self.playback_state_changed.emit(is_playing)
        if not is_playing:
            for item, m in zip(getattr(self, "mask_items", []), getattr(self, "masks_list", [])):
                if m.get("enabled", True):
                    item.setVisible(True)

    def _on_native_size_changed(self, size):
        if size.width() > 0 and size.height() > 0:
            self._native_wh = (int(size.width()), int(size.height()))
            self._apply_canvas_dimensions(int(size.width()), int(size.height()))

    @staticmethod
    def _probe_video_resolution(video_path: str):
        """វាស់ទទឹង និងកម្ពស់ពិតប្រាកដរបស់វីដេអូភ្លាមៗពេល Import (timeout 2.5s មិនឲ្យ UI គាំង)"""
        try:
            out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
                    video_path,
                ],
                stderr=subprocess.DEVNULL,
                timeout=2.5,
                creationflags=CREATE_NO_WINDOW,
            ).decode().strip()
            if "x" in out:
                first_line = out.splitlines()[0].strip()
                w_str, h_str = first_line.split("x")[:2]
                return int(w_str), int(h_str)
        except Exception:
            pass
        return 16, 9

    def _apply_canvas_dimensions(self, vid_w: int, vid_h: int):
        """ប្តូរខ្នាត Canvas ឲ្យត្រូវនឹងវីដេអូពិតប្រាកដ (ផ្តេក / បញ្ឈរ / ការ៉េ) ឬតាម Aspect Ratio ដែលបានរើស"""
        ratio_choice = (self.edits.get("aspect_ratio") or "original").split(" ")[0]
        if ratio_choice == "9:16":
            target_ratio = 9.0 / 16.0
        elif ratio_choice == "16:9":
            target_ratio = 16.0 / 9.0
        elif ratio_choice == "1:1":
            target_ratio = 1.0
        else:
            target_ratio = float(vid_w) / max(1.0, float(vid_h))

        # កំណត់ខ្នាតមូលដ្ឋានច្បាស់លាស់ (បញ្ឈរ = 270x480, ផ្តេក = 480x270, ការ៉េ = 360x360)
        if target_ratio < 0.8:          # វីដេអូបញ្ឈរ (Portrait 9:16)
            self.canvas_h = 480
            self.canvas_w = max(200, int(480 * target_ratio))
        elif target_ratio > 1.2:        # វីដេអូផ្តេក (Landscape 16:9)
            self.canvas_w = 480
            self.canvas_h = max(200, int(480 / target_ratio))
        else:                           # វីដេអូការ៉េ (Square 1:1)
            self.canvas_w = 360
            self.canvas_h = 360

        rect = QRectF(0, 0, self.canvas_w, self.canvas_h)
        self.scene.setSceneRect(rect)
        self.video_item.setSize(rect.size())
        self.color_overlay.setRect(rect)

        # ពង្រីកវីដេអូឲ្យពេញប្រអប់ Player ដោយរក្សាសមាមាត្រដើម (គ្មានសល់គែមខ្មៅលើស)
        self.view.fitInView(rect, Qt.KeepAspectRatio)
        self._render_overlays()

    def set_original_volume(self, volume_pct: int):
        """ប្តូរកម្រិតសំឡេងវីដេអូដើម។ បើកម្រិត 0% បិទសំឡេងដើមភ្លាមៗ 100%"""
        self._current_bgm_pct = int(volume_pct)
        vol = max(0.0, min(1.0, volume_pct / 100.0))
        if not self.has_dub_track:
            self.audio_out.setMuted(vol <= 0.001)
            self.audio_out.setVolume(vol)

    def set_dubbed_video_preview(self, preview_mp4_path: str):
        """ប្តូរទៅចាក់វីដេអូដែលបានបញ្ចូលសំឡេងខ្មែររួច (Single-Stream Smooth Playback)"""
        pos = self.player.position()
        was_playing = self.player.playbackState() == QMediaPlayer.PlayingState

        valid_prev = bool(
            preview_mp4_path
            and Path(preview_mp4_path).exists()
            and Path(preview_mp4_path).stat().st_size > 1024
        )
        is_dub = bool(
            valid_prev
            and str(Path(preview_mp4_path).resolve()) != str(Path(self.original_video_path).resolve())
        )
        target = preview_mp4_path if valid_prev else (
            self.original_video_path if (self.original_video_path and Path(self.original_video_path).exists()) else ""
        )
        self.has_dub_track = is_dub

        if target and Path(target).exists():
            target_resolved = str(Path(target).resolve())
            current_src = self.player.source().toLocalFile()
            if current_src and Path(current_src).resolve() == Path(target_resolved):
                # Already playing this source
                return

            self.dubbed_preview_path = target if is_dub else ""
            self.player.stop()
            self.player.setSource(QUrl())
            if not is_dub:
                vol = max(0.0, min(1.0, getattr(self, "_current_bgm_pct", 0) / 100.0))
                self.audio_out.setMuted(vol <= 0.001)
                self.audio_out.setVolume(vol)
            else:
                self.audio_out.setMuted(False)
                self.audio_out.setVolume(1.0)
            self.player.setSource(QUrl.fromLocalFile(target_resolved))
            self.player.setPosition(pos)
            if was_playing:
                self.player.play()
                self.btn_play.setText("⏸")
            else:
                self.player.pause()
                self.btn_play.setText("▶")

    def load_video(self, video_path: str, edits: dict, segments: list, pre_wh: tuple = None, pre_dur_ms: int = 0, preview_path: str = ""):
        self.edits = dict(edits)
        self.segments = segments
        self.original_video_path = video_path or ""
        self.dubbed_preview_path = ""
        self.has_dub_track = False

        valid_preview = bool(
            preview_path
            and Path(preview_path).exists()
            and Path(preview_path).stat().st_size > 1024
        )
        if valid_preview:
            target_file = preview_path
            self.dubbed_preview_path = preview_path
            self.has_dub_track = True
        elif self.original_video_path and Path(self.original_video_path).exists():
            target_file = self.original_video_path
            self.has_dub_track = False
        else:
            target_file = ""

        probe_src = self.original_video_path if (self.original_video_path and Path(self.original_video_path).exists()) else target_file
        if probe_src and Path(probe_src).exists():
            vw, vh = pre_wh if (pre_wh and len(pre_wh) == 2 and pre_wh[0] > 0) else self._probe_video_resolution(probe_src)
            self._native_wh = (vw, vh)
            self._apply_canvas_dimensions(vw, vh)

        if pre_dur_ms > 0:
            self.timeline.setRange(0, pre_dur_ms)
            self.duration_ms_changed.emit(pre_dur_ms)

        if target_file and Path(target_file).exists():
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(str(Path(target_file).resolve())))
            self.player.pause()
            # ប្រើ Asynchronous SingleShot ដើម្បីកុំឲ្យ QtMultimedia DirectShow គាំង GUI Thread
            QTimer.singleShot(150, self._safe_initial_seek)

            if self.has_dub_track:
                self.audio_out.setMuted(False)
                self.audio_out.setVolume(1.0)
            else:
                vol = max(0.0, min(1.0, getattr(self, "_current_bgm_pct", 0) / 100.0))
                self.audio_out.setMuted(vol <= 0.001)
                self.audio_out.setVolume(vol)
        else:
            self.player.stop()
            self.player.setSource(QUrl())

        self._load_edits_into_controls()
        self._reload_presets_combo()

    def _safe_initial_seek(self):
        try:
            if self.player and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self.player.setPosition(50)
        except Exception:
            pass

    def set_database(self, db):
        self.db = db
        self._reload_presets_combo()

    def _reload_presets_combo(self):
        if not hasattr(self, "db") or not self.db or not hasattr(self, "combo_presets"):
            return
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        self.combo_presets.addItem("📋 -- ជ្រើសរើស Preset --", None)
        try:
            presets = self.db.get_studio_presets()
            for p in presets:
                self.combo_presets.addItem(f"⭐ {p['name']}", p)
        except Exception:
            pass
        self.combo_presets.blockSignals(False)

    def _on_save_preset(self):
        if not hasattr(self, "db") or not self.db:
            QMessageBox.warning(self, "Preset", "សូមបើកគម្រោងជាមុនសិន!")
            return
        name, ok = QInputDialog.getText(
            self, "Save Studio Preset",
            "បញ្ចូលឈ្មោះ Preset (ឧ. TikTok_9x16, FB_Drama, YT_Recap):"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        keys = [
            "logo_path", "logo_x", "logo_y", "logo_scale", "logo_opacity",
            "burn_subs", "sub_style", "sub_font_family", "sub_y", "sub_font_size", "sub_color", "sub_bg", "sub_outline",
            "brightness", "contrast", "saturation", "lut_preset",
            "mask_enabled", "mask_mode", "mask_x", "mask_y", "mask_w", "mask_h", "mask_strength", "mask_color",
            "masks_json", "auto_blur_chinese", "auto_timed_blur",
            "anti_copyright_enabled", "anti_copyright_level", "anti_copyright_flip", "anti_copyright_border",
            "custom_bgm_vol", "auto_ducking", "keep_bgm_only",
            "hook_enabled", "hook_text", "hook_pos", "hook_bg_color", "hook_text_color", "hook_height_pct", "hook_font_size",
            "intro_enabled", "intro_path", "outro_enabled", "outro_path", "aspect_ratio",
            "hd_upscale_enabled", "hd_upscale_1080p",
        ]
        cfg = {k: self.edits.get(k) for k in keys if k in self.edits}
        try:
            self.db.save_studio_preset(name, cfg)
            self._reload_presets_combo()
            for i in range(self.combo_presets.count()):
                d = self.combo_presets.itemData(i)
                if d and d.get("name") == name:
                    self.combo_presets.setCurrentIndex(i)
                    break
            QMessageBox.information(self, "Preset Saved", f"បានរក្សាទុក Studio Preset '{name}' ដោយជោគជ័យ!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"មិនអាចរក្សាទុកបាន: {e}")

    def _on_apply_preset(self, idx: int):
        if idx <= 0:
            return
        p_data = self.combo_presets.currentData()
        if not p_data or "config" not in p_data:
            return
        cfg = p_data["config"]
        for k, v in cfg.items():
            self.edits[k] = v
        self._load_edits_into_controls()
        self.edits_changed.emit(dict(self.edits))

    def _on_delete_preset(self):
        idx = self.combo_presets.currentIndex()
        if idx <= 0:
            return
        p_data = self.combo_presets.currentData()
        if not p_data:
            return
        ret = QMessageBox.question(
            self, "Delete Preset",
            f"តើអ្នកពិតជាចង់លុប Preset '{p_data['name']}' មែនទេ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            self.db.delete_studio_preset(p_data["id"])
            self._reload_presets_combo()

    def set_segments(self, segments: list):
        self.segments = segments
        pos = self.player.position()
        self._update_live_subtitle(pos)
        self._update_dynamic_blur_visibility(pos)

    def seek_to_ms(self, ms: int):
        dur = max(0, self.player.duration())
        ms = max(0, min(dur, ms) if dur > 0 else ms)
        self.player.setPosition(ms)
        self.timeline.setValue(ms)
        self._update_live_subtitle(ms)
        self._update_dynamic_blur_visibility(ms)
        self.position_synced.emit(ms)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.pause()
        else:
            if not self.has_dub_track:
                vol = max(0.0, min(1.0, getattr(self, "_current_bgm_pct", 0) / 100.0))
                self.audio_out.setMuted(vol <= 0.001)
                self.audio_out.setVolume(vol)
            else:
                self.audio_out.setMuted(False)
                self.audio_out.setVolume(1.0)
            self.player.play()
            self.btn_play.setText("⏸")

    def pause(self):
        """ផ្អាកវីដេអូ និងសំឡេងខ្មែរភ្លាមៗ"""
        self.player.pause()
        self.btn_play.setText("▶")

    def step_ms(self, delta_ms: int):
        """ប៊ូតុង < និង > សម្រាប់រំកិលវីដេអូថយក្រោយ ឬទៅមុខ (ឧ. -2000ms ឬ +2000ms)"""
        dur = max(0, self.player.duration())
        new_pos = max(0, min(dur, self.player.position() + delta_ms))
        self.seek_to_ms(new_pos)

    def prev_segment(self):
        """ប៊ូតុង |< សម្រាប់លោតទៅជួរអត្ថបទមុន"""
        if not self.segments:
            self.step_ms(-5000)
            return
        cur = self.player.position()
        prev_items = [s for s in self.segments if s["start_ms"] < cur - 400]
        target = prev_items[-1] if prev_items else self.segments[0]
        self.seek_to_ms(target["start_ms"])

    def next_segment(self):
        """ប៊ូតុង >| សម្រាប់លោតទៅជួរអត្ថបទបន្ទាប់"""
        if not self.segments:
            self.step_ms(5000)
            return
        cur = self.player.position()
        next_items = [s for s in self.segments if s["start_ms"] > cur + 150]
        if next_items:
            self.seek_to_ms(next_items[0]["start_ms"])

    def _on_dur_changed(self, dur_ms: int):
        self.timeline.setRange(0, max(1, dur_ms))
        self.duration_ms_changed.emit(max(1000, dur_ms))

    def _on_pos_changed(self, pos_ms: int):
        if not self._is_seeking:
            self.timeline.setValue(pos_ms)
        dur = max(1, self.player.duration())
        cur_sec = pos_ms // 1000
        if cur_sec != getattr(self, "_last_time_sec", -1):
            self._last_time_sec = cur_sec
            self.lbl_time.setText(f"{self._fmt(pos_ms)} / {self._fmt(dur)}")
        self._update_live_subtitle(pos_ms)
        self._update_dynamic_blur_visibility(pos_ms)
        self.position_ms_changed.emit(pos_ms)

    def _on_auto_timed_blur_toggled(self):
        if hasattr(self, "chk_auto_timed_blur"):
            self.edits["auto_timed_blur"] = 1 if self.chk_auto_timed_blur.isChecked() else 0
            self._update_dynamic_blur_visibility(self.player.position())
            self.edits_changed.emit(dict(self.edits))

    def _update_dynamic_blur_visibility(self, pos_ms: int):
        """
        Dynamically updates the visibility of blur masks & visual feedback pill:
        - When Auto Timed Blur is ON:
          * Text pop-up active -> shows blur masks + green badge.
          * Text off-screen -> hides blur masks (Direct Pass-Through 0% Blur) + neutral badge.
        - When Auto Timed Blur is OFF:
          * Keeps enabled masks continuously visible (Static Blur mode).
        """
        auto_timed = bool(self.edits.get("auto_timed_blur", 1))
        auto_blur = bool(self.edits.get("auto_blur_chinese", 1))
        is_playing = (self.player.playbackState() == QMediaPlayer.PlayingState)

        active_seg = None
        if getattr(self, "segments", None):
            for s in self.segments:
                if int(s.get("start_ms", 0)) <= pos_ms <= int(s.get("end_ms", 0)):
                    active_seg = s
                    break
        is_text_active = active_seg is not None

        if hasattr(self, "lbl_blur_live_state"):
            if not auto_timed:
                self.lbl_blur_live_state.setText("🔒 STATIC MASK — Blur ជាប់គ្រប់ Frame")
                self.lbl_blur_live_state.setStyleSheet("font-size: 10px; color: #F59E0B; font-weight: 700;")
            elif is_text_active:
                has_box = bool(active_seg.get("bbox_json"))
                tag = "Localized Box" if has_box else "Timed Zones"
                self.lbl_blur_live_state.setText(f"🟢 TEXT POP-UP — Blur ON ({tag})")
                self.lbl_blur_live_state.setStyleSheet("font-size: 10px; color: #34D399; font-weight: 700;")
            else:
                self.lbl_blur_live_state.setText("⚪ NO TEXT — Direct Pass-Through (0% Blur)")
                self.lbl_blur_live_state.setStyleSheet("font-size: 10px; color: #94A3B8; font-weight: 600;")

        if not hasattr(self, "mask_items") or not self.mask_items:
            return

        if auto_timed and auto_blur and getattr(self, "segments", None):
            for item, m in zip(self.mask_items, self.masks_list):
                if m.get("enabled", True) and m.get("mode", "blur") == "blur":
                    if is_playing:
                        item.setVisible(is_text_active)
                    else:
                        item.setVisible(is_text_active or getattr(item, "is_selected", False))
                elif m.get("enabled", True):
                    item.setVisible(True)
        else:
            for item, m in zip(self.mask_items, self.masks_list):
                if m.get("enabled", True):
                    item.setVisible(True)

    def _on_timeline_moved(self, val: int):
        if self._is_seeking:
            self._update_live_subtitle(val)
            self._update_dynamic_blur_visibility(val)

    def _on_seek_released(self):
        self._is_seeking = False
        pos = self.timeline.value()
        self.player.setPosition(pos)
        self.position_synced.emit(pos)

    @staticmethod
    def _fmt(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"

    # --- Subtitle 100 Styles & Khmer Font Selector Management ---
    def _populate_khmer_fonts(self):
        """Populates Khmer Font Selector with installed Khmer fonts, curated favorites, and custom system fonts."""
        if not hasattr(self, "combo_sub_font"):
            return
        self.combo_sub_font.blockSignals(True)
        self.combo_sub_font.clear()
        self.combo_sub_font.addItem("✨ Auto (តាម Style នីមួយៗ)", "")

        try:
            installed = set(QFontDatabase.families())
        except Exception:
            installed = set()

        added = set()
        # 1. Curated Khmer fonts (prioritize installed ones first, still list key Khmer families)
        khmer_keywords = (
            "khmer", "kantumruy", "hanuman", "battambang", "moul", "muol",
            "siemreap", "bokor", "dangrek", "koulen", "suwannaphum", "taprom",
            "bayon", "chenla", "content", "fasthand", "freehand", "metal",
            "moulpali", "odor", "preahvihear", "siamreap", "noto sans khmer", "noto serif khmer",
            "koh santepheap", "nokora", "angkor", "kdam", "akbalthom", "limon",
        )
        installed_khmer = sorted(
            f for f in installed if any(kw in f.lower() for kw in khmer_keywords)
        )
        for f in KHMER_RECOMMENDED_FONTS:
            if f in installed and f not in added:
                self.combo_sub_font.addItem(f"🇰🇭 {f}", f)
                added.add(f)
        for f in installed_khmer:
            if f not in added:
                self.combo_sub_font.addItem(f"🇰🇭 {f}", f)
                added.add(f)
        # Ensure core Khmer defaults are always selectable even if font cache names differ
        for f in KHMER_RECOMMENDED_FONTS[:6]:
            if f not in added:
                self.combo_sub_font.addItem(f"🇰🇭 {f}", f)
                added.add(f)

        # 2. Other installed custom system fonts (so any custom .ttf/.otf installed on Windows is accessible)
        other_fonts = sorted(f for f in installed if f not in added and not f.startswith("@"))
        if other_fonts:
            self.combo_sub_font.insertSeparator(self.combo_sub_font.count())
            for f in other_fonts:
                self.combo_sub_font.addItem(f, f)
                added.add(f)

        self.combo_sub_font.blockSignals(False)

    def _on_sub_font_changed(self):
        if not hasattr(self, "combo_sub_font"):
            return
        font_fam = self.combo_sub_font.currentData() or ""
        self.edits["sub_font_family"] = font_fam
        self._last_sub_cache_key = None
        if font_fam and not self.chk_burn_subs.isChecked():
            self.chk_burn_subs.setChecked(True)
        self._sync_ui_to_edits()

    def _populate_sub_styles(self, category: str = "all"):
        self.combo_sub_style.blockSignals(True)
        cur_data = self.combo_sub_style.currentData()
        self.combo_sub_style.clear()
        for k, v in KHMER_SUB_STYLES.items():
            c = v.get("category", "")
            if category == "all" or c.lower() == category.lower() or category.lower() in c.lower():
                self.combo_sub_style.addItem(v["label"], k)
        # Restore selection if exists
        for i in range(self.combo_sub_style.count()):
            if self.combo_sub_style.itemData(i) == cur_data:
                self.combo_sub_style.setCurrentIndex(i)
                break
        self.combo_sub_style.blockSignals(False)

    def _on_sub_cat_changed(self):
        cat = self.combo_sub_cat.currentData() or "all"
        q = self.sub_filter_input.text() if hasattr(self, "sub_filter_input") else ""
        self._filter_preset_gallery(q, cat)

    def _on_sub_style_changed(self):
        if not self.chk_burn_subs.isChecked():
            self.chk_burn_subs.setChecked(True)
        cur_st = self.combo_sub_style.currentData() or "classic_box"
        for k, c in getattr(self, "preset_cards", {}).items():
            c.set_selected(k == cur_st)
        self._sync_ui_to_edits()

    # --- Visual Subtitle Preset Gallery Grid Management ---
    def _build_preset_gallery(self):
        cat = self.combo_sub_cat.currentData() if hasattr(self, "combo_sub_cat") else "all"
        q = self.sub_filter_input.text() if hasattr(self, "sub_filter_input") else ""
        self._filter_preset_gallery(q, cat)

    def _filter_preset_gallery(self, query: str = "", category: str = "all"):
        q = (query or "").strip().lower()
        if not hasattr(self, "grid_presets"):
            return
        for i in reversed(range(self.grid_presets.count())):
            w = self.grid_presets.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.preset_cards = {}
        cur_style = self.edits.get("sub_style", "classic_box")

        cat = category or "all"
        if hasattr(self, "combo_sub_cat") and not category:
            cat = self.combo_sub_cat.currentData() or "all"

        matches = []
        for k, st in KHMER_SUB_STYLES.items():
            c = st.get("category", "")
            lbl = st.get("label", "")
            if cat != "all" and (cat.lower() != c.lower() and cat.lower() not in c.lower()):
                continue
            if q and (q not in k.lower() and q not in lbl.lower() and q not in c.lower()):
                continue
            matches.append((k, st))

        for idx, (k, st) in enumerate(matches):
            tr, tg, tb = ass_color_to_rgb(st.get("primary", "&H00FFFFFF"))
            t_hex = f"#{tr:02x}{tg:02x}{tb:02x}"
            or_, og, ob = ass_color_to_rgb(st.get("outline_col", "&H00000000"))
            s_hex = f"#{or_:02x}{og:02x}{ob:02x}" if (st.get("border_style") != 3 and st.get("outline", 0) > 0) else "none"
            b_hex = "none"
            if st.get("border_style") == 3:
                br, bg, bb, ba = ass_color_to_rgba(st.get("back_col", "&H48000000"))
                b_hex = f"rgba({br},{bg},{bb},{ba/255.0:.2f})"

            title = st.get("label", k).split("(")[0].strip()
            card = SubtitlePresetCard(k, title, t_hex, s_hex, b_hex, desc=st.get("category", ""))
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            card.clicked.connect(self._select_preset_card)
            card.set_selected(k == cur_style)
            self.preset_cards[k] = card
            row, col = divmod(idx, 2)
            self.grid_presets.addWidget(card, row, col)

    def _select_preset_card(self, preset_id: str):
        for k, c in self.preset_cards.items():
            c.set_selected(k == preset_id)
        if not self.chk_burn_subs.isChecked():
            self.chk_burn_subs.setChecked(True)
        st = get_sub_style(preset_id)
        if hasattr(self, "spin_outline"):
            self.spin_outline.blockSignals(True)
            self.spin_outline.setValue(int(st.get("outline", 2)))
            self.spin_outline.blockSignals(False)
        if hasattr(self, "chk_sub_bg"):
            self.chk_sub_bg.blockSignals(True)
            self.chk_sub_bg.setChecked(int(st.get("border_style", 1)) == 3)
            self.chk_sub_bg.blockSignals(False)
        self.combo_sub_style.blockSignals(True)
        self._populate_sub_styles("all")
        for i in range(self.combo_sub_style.count()):
            if self.combo_sub_style.itemData(i) == preset_id:
                self.combo_sub_style.setCurrentIndex(i)
                break
        self.combo_sub_style.blockSignals(False)
        self.edits["sub_style"] = preset_id
        self._last_sub_cache_key = None
        self._sync_ui_to_edits()

    # --- 20+ Adjustments & LUT Presets Gallery ---
    def _filter_lut_gallery(self, query: str = "", category: str = "All"):
        if not hasattr(self, "lut_grid"):
            return
        q = (query or "").strip().lower()
        cat = category or "All"
        for i in reversed(range(self.lut_grid.count())):
            w = self.lut_grid.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.lut_cards = {}
        cur_lut = str(self.edits.get("lut_preset", "none") or "none")

        matches = []
        for p in LUT_PRESETS:
            if cat != "All" and p.get("category", "").lower() != cat.lower():
                continue
            if q and (
                q not in p["id"].lower()
                and q not in p["name"].lower()
                and q not in p.get("desc", "").lower()
                and q not in p.get("category", "").lower()
            ):
                continue
            matches.append(p)

        for idx, p in enumerate(matches):
            card = LutPresetCard(p)
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            card.clicked.connect(self._select_lut_preset)
            card.set_selected(p["id"] == cur_lut)
            self.lut_cards[p["id"]] = card
            row, col = divmod(idx, 2)
            self.lut_grid.addWidget(card, row, col)

    def _select_lut_preset(self, preset_id: str):
        preset = get_lut_preset(preset_id)
        self.edits["lut_preset"] = preset["id"]
        for k, card in getattr(self, "lut_cards", {}).items():
            card.set_selected(k == preset["id"])
        if hasattr(self, "lbl_active_lut"):
            self.lbl_active_lut.setText(f"🎨 Active LUT: {preset['name']} — {preset.get('desc', '')}")
        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))

    # --- Audio FX & Smart Auto-Ducking Management ---
    def _set_duck_smoothness(self, mode: str):
        self.duck_smoothness = mode
        p_act = "background: #00E5FF; color: #0B0D10; font-weight: 800; border: 1px solid #00E5FF; border-radius: 5px; padding: 4px 3px; font-size: 10px;"
        p_inact = "background: #181C24; color: #CBD5E1; font-weight: 600; border: 1px solid #2D3548; border-radius: 5px; padding: 4px 3px; font-size: 10px;"
        if hasattr(self, "btn_duck_fast"):
            self.btn_duck_fast.setStyleSheet(p_act if mode == "fast" else p_inact)
            self.btn_duck_smooth.setStyleSheet(p_act if mode == "smooth" else p_inact)
            self.btn_duck_cinema.setStyleSheet(p_act if mode == "cinema" else p_inact)
        self.edits["ducking_smoothness"] = mode
        self._sync_ui_to_edits()

    def _set_voice_fx(self, mode: str):
        self.voice_fx = mode
        p_act = "background: #7C3AED; color: #FFFFFF; font-weight: 800; border: 1px solid #A78BFA; border-radius: 5px; padding: 5px 6px; font-size: 10.5px;"
        p_inact = "background: #181C24; color: #CBD5E1; font-weight: 600; border: 1px solid #2D3548; border-radius: 5px; padding: 5px 6px; font-size: 10.5px;"
        if hasattr(self, "btn_fx_studio"):
            self.btn_fx_studio.setStyleSheet(p_act if mode == "clean" else p_inact)
            self.btn_fx_thought.setStyleSheet(p_act if mode == "inner_thought" else p_inact)
            self.btn_fx_phone.setStyleSheet(p_act if mode == "phone" else p_inact)
            self.btn_fx_hall.setStyleSheet(p_act if mode == "hall" else p_inact)
        self.edits["voice_fx"] = mode
        self._sync_ui_to_edits()

    def _on_ducking_reduction_changed(self, val: int):
        if hasattr(self, "lbl_ducking_db"):
            self.lbl_ducking_db.setText(f"{val} dB")
        self._sync_ui_to_edits()

    def _on_dub_vol_changed(self, val: int):
        if hasattr(self, "lbl_dub_vol"):
            self.lbl_dub_vol.setText(f"{val}%")
        self._sync_ui_to_edits()

    def _on_orig_vol_changed(self, val: int):
        if hasattr(self, "lbl_orig_vol"):
            self.lbl_orig_vol.setText(f"{val}%")
        self._sync_ui_to_edits()

    # --- Multi-Mask Video Management ---
    def _init_masks_from_edits(self):
        raw = self.edits.get("masks_json")
        masks = []
        if raw:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list):
                    masks = parsed
            except Exception:
                masks = []
        if not masks:
            default_blur_active = bool(self.edits.get("auto_blur_chinese", 1)) or bool(self.edits.get("mask_enabled", 0))
            masks = [
                {
                    "id": "mask_1",
                    "name": "🎭 អក្សររត់បាតក្រោម (Bottom Subs)",
                    "mode": "blur",
                    "color": "#000000",
                    "strength": 0.88,
                    "x": 0.03,
                    "y": 0.74,
                    "w": 0.94,
                    "h": 0.20,
                    "enabled": default_blur_active,
                },
                {
                    "id": "mask_2",
                    "name": "🎭 ឈ្មោះតួអង្គឆ្វេង (Left Name Card)",
                    "mode": "blur",
                    "color": "#000000",
                    "strength": 0.88,
                    "x": 0.02,
                    "y": 0.20,
                    "w": 0.18,
                    "h": 0.45,
                    "enabled": default_blur_active,
                },
                {
                    "id": "mask_3",
                    "name": "🎭 ឈ្មោះតួអង្គស្តាំ (Right Name Card)",
                    "mode": "blur",
                    "color": "#000000",
                    "strength": 0.88,
                    "x": 0.80,
                    "y": 0.20,
                    "w": 0.18,
                    "h": 0.45,
                    "enabled": default_blur_active,
                },
                {
                    "id": "mask_4",
                    "name": "🎭 ចំណងជើង/ភាគលើ (Top Title / Badge)",
                    "mode": "blur",
                    "color": "#000000",
                    "strength": 0.88,
                    "x": 0.02,
                    "y": 0.02,
                    "w": 0.38,
                    "h": 0.12,
                    "enabled": default_blur_active,
                },
            ]
        self.masks_list = masks
        if self.active_mask_idx >= len(self.masks_list):
            self.active_mask_idx = 0

    def _update_mask_combo(self):
        self.combo_mask_select.blockSignals(True)
        self.combo_mask_select.clear()
        for i, m in enumerate(self.masks_list):
            st = "ON" if m.get("enabled", True) else "OFF"
            name = m.get("name", f"🎭 Mask #{i+1}")
            self.combo_mask_select.addItem(f"{name} [{st}]", i)
        if 0 <= self.active_mask_idx < self.combo_mask_select.count():
            self.combo_mask_select.setCurrentIndex(self.active_mask_idx)
        self.combo_mask_select.blockSignals(False)

    def _load_active_mask_to_ui(self):
        if not self.masks_list or not (0 <= self.active_mask_idx < len(self.masks_list)):
            return
        m = self.masks_list[self.active_mask_idx]
        for w in (self.chk_mask, self.combo_mask_mode, self.sl_mask_strength, self.sl_mask_w, self.sl_mask_h):
            w.blockSignals(True)

        self.chk_mask.setChecked(bool(m.get("enabled", True)))
        self.combo_mask_mode.setCurrentIndex(0 if m.get("mode", "blur") == "blur" else 1)
        self.sl_mask_strength.setValue(int(float(m.get("strength", 0.75)) * 100))
        self.sl_mask_w.setValue(int(float(m.get("w", 0.90)) * 100))
        self.sl_mask_h.setValue(int(float(m.get("h", 0.14)) * 100))

        for w in (self.chk_mask, self.combo_mask_mode, self.sl_mask_strength, self.sl_mask_w, self.sl_mask_h):
            w.blockSignals(False)

    def _on_mask_select_changed(self, idx: int):
        if 0 <= idx < len(self.masks_list):
            self.active_mask_idx = idx
            self._load_active_mask_to_ui()
            self._render_overlays()

    def _add_mask(self):
        num = len(self.masks_list) + 1
        new_mask = {
            "id": f"mask_{num}",
            "name": f"🎭 Mask #{num}",
            "mode": "blur",
            "color": "#000000",
            "strength": 0.75,
            "x": 0.05,
            "y": 0.05,
            "w": 0.35,
            "h": 0.12,
            "enabled": True,
        }
        self.masks_list.append(new_mask)
        self.active_mask_idx = len(self.masks_list) - 1
        self._sync_mask_controls_to_edits()

    def _delete_mask(self):
        if len(self.masks_list) <= 1:
            self.chk_mask.setChecked(False)
            self._sync_mask_controls_to_edits()
            return
        del self.masks_list[self.active_mask_idx]
        self.active_mask_idx = max(0, self.active_mask_idx - 1)
        self._sync_mask_controls_to_edits()

    def _set_mask_preset(self, x: float, y: float, w: float, h: float):
        if not self.masks_list or not (0 <= self.active_mask_idx < len(self.masks_list)):
            return
        m = self.masks_list[self.active_mask_idx]
        m["x"] = x
        m["y"] = y
        m["w"] = w
        m["h"] = h
        m["enabled"] = True
        self.chk_mask.setChecked(True)
        self._sync_mask_controls_to_edits()

    def toggle_bottom_blur_mask(self) -> bool:
        """
        1-Click Smart Multi-Zone Chinese Text Auto-Blur:
        Toggles blur across all 4 critical zones:
        1) Bottom running subtitles (x=0.03, y=0.74, w=0.94, h=0.20)
        2) Left character name card (x=0.02, y=0.20, w=0.18, h=0.45)
        3) Right character name card (x=0.80, y=0.20, w=0.18, h=0.45)
        4) Top floating title card (x=0.02, y=0.02, w=0.38, h=0.12)
        Syncs UI controls, canvas overlays, and emits edits_changed.
        """
        if not self.masks_list:
            self._init_masks_from_edits()

        is_currently_active = bool(self.edits.get("auto_blur_chinese", 1)) and any(m.get("enabled", False) for m in self.masks_list)
        new_state = not is_currently_active

        smart_templates = [
            ("mask_1", "🎭 អក្សររត់បាតក្រោម (Bottom Subs)", 0.03, 0.74, 0.94, 0.20),
            ("mask_2", "🎭 ឈ្មោះតួអង្គឆ្វេង (Left Name Card)", 0.02, 0.20, 0.18, 0.45),
            ("mask_3", "🎭 ឈ្មោះតួអង្គស្តាំ (Right Name Card)", 0.80, 0.20, 0.18, 0.45),
            ("mask_4", "🎭 ចំណងជើង/ភាគលើ (Top Title / Badge)", 0.02, 0.02, 0.38, 0.12),
        ]

        for mid, mname, mx, my, mw, mh in smart_templates:
            found = False
            for m in self.masks_list:
                if m.get("id") == mid:
                    m["enabled"] = new_state
                    m["mode"] = "blur"
                    m["strength"] = 0.88
                    found = True
                    break
            if not found:
                self.masks_list.append({
                    "id": mid,
                    "name": mname,
                    "mode": "blur",
                    "color": "#000000",
                    "strength": 0.88,
                    "x": mx,
                    "y": my,
                    "w": mw,
                    "h": mh,
                    "enabled": new_state,
                })

        for m in self.masks_list:
            if m.get("mode", "blur") == "blur":
                m["enabled"] = new_state

        self.edits["mask_enabled"] = 1 if new_state else 0
        self.edits["auto_blur_chinese"] = 1 if new_state else 0
        self.edits["mask_mode"] = "blur"
        self.edits["masks_json"] = json.dumps(self.masks_list, ensure_ascii=False)

        self._load_active_mask_to_ui()
        self._update_mask_combo()
        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))
        return new_state

    def _sync_mask_controls_to_edits(self):
        if not self.masks_list or not (0 <= self.active_mask_idx < len(self.masks_list)):
            return
        m = self.masks_list[self.active_mask_idx]
        m["enabled"] = self.chk_mask.isChecked()
        m["mode"] = "blur" if self.combo_mask_mode.currentIndex() == 0 else "box"
        m["strength"] = self.sl_mask_strength.value() / 100.0
        m["w"] = self.sl_mask_w.value() / 100.0
        m["h"] = self.sl_mask_h.value() / 100.0

        # Save to edits
        self.edits["masks_json"] = json.dumps(self.masks_list, ensure_ascii=False)
        self.edits["mask_enabled"] = 1 if any(x.get("enabled", True) for x in self.masks_list) else 0
        # Backward compatibility with primary mask
        self.edits["mask_mode"] = m["mode"]
        self.edits["mask_color"] = m.get("color", "#000000")
        self.edits["mask_strength"] = m["strength"]
        self.edits["mask_x"] = m.get("x", 0.05)
        self.edits["mask_y"] = m.get("y", 0.78)
        self.edits["mask_w"] = m["w"]
        self.edits["mask_h"] = m["h"]

        self._update_mask_combo()
        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))

    def _on_mask_transformed(self, mask_index: int, x: float, y: float, w: float, h: float):
        if not (0 <= mask_index < len(self.masks_list)):
            return
        cw = max(1.0, float(self.canvas_w))
        ch = max(1.0, float(self.canvas_h))

        m = self.masks_list[mask_index]
        m["x"] = round(max(0.0, min(0.98, x / cw)), 3)
        m["y"] = round(max(0.0, min(0.98, y / ch)), 3)
        m["w"] = round(max(0.05, min(1.0, w / cw)), 3)
        m["h"] = round(max(0.03, min(1.0, h / ch)), 3)

        if mask_index == self.active_mask_idx:
            self.sl_mask_w.blockSignals(True)
            self.sl_mask_h.blockSignals(True)
            self.sl_mask_w.setValue(int(m["w"] * 100))
            self.sl_mask_h.setValue(int(m["h"] * 100))
            self.sl_mask_w.blockSignals(False)
            self.sl_mask_h.blockSignals(False)

        self.edits["masks_json"] = json.dumps(self.masks_list, ensure_ascii=False)
        self.edits_changed.emit(dict(self.edits))

    def _on_mask_selected(self, mask_index: int):
        if 0 <= mask_index < len(self.masks_list) and mask_index != self.active_mask_idx:
            self.active_mask_idx = mask_index
            self.combo_mask_select.setCurrentIndex(mask_index)
            self._load_active_mask_to_ui()
            self._render_overlays()

    def _pick_mask_color(self):
        if not self.masks_list or not (0 <= self.active_mask_idx < len(self.masks_list)):
            return
        m = self.masks_list[self.active_mask_idx]
        color = QColorDialog.getColor(QColor(m.get("color", "#000000")), self)
        if color.isValid():
            m["color"] = color.name()
            self.edits["mask_color"] = color.name()
            self.edits["masks_json"] = json.dumps(self.masks_list, ensure_ascii=False)
            self._render_overlays()
            self.edits_changed.emit(dict(self.edits))

    # --- Overlays & Visual Sync ---
    def _load_edits_into_controls(self):
        self._loading_edits = True
        try:
            self._load_edits_into_controls_inner()
        finally:
            self._loading_edits = False
        self._render_overlays()

    def _load_edits_into_controls_inner(self):
        for w in (
            self.sl_logo_scale, self.sl_logo_opacity, self.chk_burn_subs,
            self.sl_sub_y, self.spin_font, self.chk_sub_bg,
            self.sl_bright, self.sl_contrast, self.sl_sat,
            self.sl_custom_bgm, self.chk_ducking
        ):
            w.blockSignals(True)

        l_scale = int(self.edits.get("logo_scale", 0.15) * 100)
        l_opac = int(self.edits.get("logo_opacity", 0.90) * 100)
        self.sl_logo_scale.setValue(l_scale)
        self.sl_logo_opacity.setValue(l_opac)
        if hasattr(self, "lbl_logo_scale_val"):
            self.lbl_logo_scale_val.setText(f"{l_scale}%")
        if hasattr(self, "lbl_logo_opacity_val"):
            self.lbl_logo_opacity_val.setText(f"{l_opac}%")
        self.chk_burn_subs.setChecked(bool(self.edits.get("burn_subs", 0)))

        # Subtitle style & category loading
        cur_st = self.edits.get("sub_style", "classic_box")
        st_info = get_sub_style(cur_st)
        cur_cat = st_info.get("category", "all")
        self.combo_sub_cat.blockSignals(True)
        for i in range(self.combo_sub_cat.count()):
            if self.combo_sub_cat.itemData(i) == cur_cat:
                self.combo_sub_cat.setCurrentIndex(i)
                break
        self.combo_sub_cat.blockSignals(False)
        self._populate_sub_styles(cur_cat)

        self.combo_sub_style.blockSignals(True)
        for i in range(self.combo_sub_style.count()):
            if self.combo_sub_style.itemData(i) == cur_st:
                self.combo_sub_style.setCurrentIndex(i)
                break
        self.combo_sub_style.blockSignals(False)

        self.sl_sub_y.setValue(int(self.edits.get("sub_y", 0.85) * 100))
        self.spin_font.setValue(int(self.edits.get("sub_font_size", 24)))
        if hasattr(self, "spin_outline"):
            self.spin_outline.setValue(int(self.edits.get("sub_outline", 2)))
        self.chk_sub_bg.setChecked(bool(self.edits.get("sub_bg", 1)))
        self.sl_bright.setValue(int(self.edits.get("brightness", 0.0) * 100))
        self.sl_contrast.setValue(int(self.edits.get("contrast", 1.0) * 100))
        self.sl_sat.setValue(int(self.edits.get("saturation", 1.0) * 100))
        self.sl_custom_bgm.setValue(int(float(self.edits.get("custom_bgm_vol", 0.25)) * 100))
        if hasattr(self, "lbl_orig_vol"):
            self.lbl_orig_vol.setText(f"{self.sl_custom_bgm.value()}%")
        self.chk_ducking.setChecked(bool(self.edits.get("auto_ducking", 1)))
        if hasattr(self, "sl_ducking_reduction"):
            self.sl_ducking_reduction.setValue(int(self.edits.get("ducking_db", -18)))
            self.lbl_ducking_db.setText(f"{self.sl_ducking_reduction.value()} dB")
        if hasattr(self, "sl_dub_vol"):
            self.sl_dub_vol.setValue(int(float(self.edits.get("dub_volume", 1.15)) * 100))
            self.lbl_dub_vol.setText(f"{self.sl_dub_vol.value()}%")
        if hasattr(self, "chk_normalize"):
            self.chk_normalize.setChecked(bool(self.edits.get("normalize_lufs", 1)))
        self._set_duck_smoothness(self.edits.get("ducking_smoothness", "smooth"))
        self._set_voice_fx(self.edits.get("voice_fx", "clean"))

        for k, c in getattr(self, "preset_cards", {}).items():
            c.set_selected(k == cur_st)

        # Load LUT preset & Auto Timed Blur controls
        cur_lut = str(self.edits.get("lut_preset", "none") or "none")
        lut_info = get_lut_preset(cur_lut)
        for k, card in getattr(self, "lut_cards", {}).items():
            card.set_selected(k == lut_info["id"])
        if hasattr(self, "lbl_active_lut"):
            self.lbl_active_lut.setText(f"🎨 Active LUT: {lut_info['name']} — {lut_info.get('desc', '')}")
        if hasattr(self, "chk_auto_timed_blur"):
            self.chk_auto_timed_blur.blockSignals(True)
            self.chk_auto_timed_blur.setChecked(bool(self.edits.get("auto_timed_blur", 1)))
            self.chk_auto_timed_blur.blockSignals(False)
        if hasattr(self, "combo_sub_font"):
            cur_ff = str(self.edits.get("sub_font_family", "") or "")
            self.combo_sub_font.blockSignals(True)
            f_idx = self.combo_sub_font.findData(cur_ff)
            if f_idx >= 0:
                self.combo_sub_font.setCurrentIndex(f_idx)
            elif cur_ff:
                self.combo_sub_font.addItem(f"🔤 {cur_ff}", cur_ff)
                self.combo_sub_font.setCurrentIndex(self.combo_sub_font.count() - 1)
            else:
                self.combo_sub_font.setCurrentIndex(0)
            self.combo_sub_font.blockSignals(False)

        bgm_p = self.edits.get("custom_bgm_path", "")
        self.btn_pick_bgm.setText(f"🎵 {Path(bgm_p).name[:18]}" if bgm_p else "🎵 រើសភ្លេង BGM (.mp3)")

        logo_p = self.edits.get("logo_path", "")
        if hasattr(self, "lbl_logo_info"):
            if logo_p and Path(logo_p).exists():
                self.lbl_logo_info.setText(f"📁 {Path(logo_p).name}")
            else:
                self.lbl_logo_info.setText("គ្មាន Logo ត្រូវបានជ្រើសរើសទេ")

        # Load Aspect Ratio
        if hasattr(self, "combo_ratio"):
            cur_ar = str(self.edits.get("aspect_ratio", "original") or "original").split(" ")[0]
            self.combo_ratio.blockSignals(True)
            for i in range(self.combo_ratio.count()):
                if self.combo_ratio.itemText(i).split(" ")[0] == cur_ar:
                    self.combo_ratio.setCurrentIndex(i)
                    break
            self.combo_ratio.blockSignals(False)

        # Load Hook Banner & Cover controls
        if hasattr(self, "chk_hook_enabled"):
            for hw_c in (self.chk_hook_enabled, self.edit_hook_text, self.combo_hook_pos, self.sl_hook_height, self.sl_hook_font_size):
                hw_c.blockSignals(True)
            self.chk_hook_enabled.setChecked(bool(self.edits.get("hook_enabled", 0)))
            self.edit_hook_text.setText(str(self.edits.get("hook_text", "") or ""))
            hp_idx = self.combo_hook_pos.findData(str(self.edits.get("hook_pos", "top") or "top"))
            self.combo_hook_pos.setCurrentIndex(hp_idx if hp_idx >= 0 else 0)
            hh_val = max(6, min(24, int(self.edits.get("hook_height_pct", 12) or 12)))
            hf_val = max(16, min(52, int(self.edits.get("hook_font_size", 28) or 28)))
            self.sl_hook_height.setValue(hh_val)
            self.lbl_hook_height_val.setText(f"{hh_val}%")
            self.sl_hook_font_size.setValue(hf_val)
            self.lbl_hook_font_val.setText(f"{hf_val}px")
            self._update_hook_color_buttons()
            for hw_c in (self.chk_hook_enabled, self.edit_hook_text, self.combo_hook_pos, self.sl_hook_height, self.sl_hook_font_size):
                hw_c.blockSignals(False)

        # Load Intro / Outro controls
        if hasattr(self, "chk_intro_enabled"):
            self.chk_intro_enabled.blockSignals(True)
            self.chk_outro_enabled.blockSignals(True)
            self.chk_intro_enabled.setChecked(bool(self.edits.get("intro_enabled", 0)))
            self.chk_outro_enabled.setChecked(bool(self.edits.get("outro_enabled", 0)))
            self.chk_intro_enabled.blockSignals(False)
            self.chk_outro_enabled.blockSignals(False)
            self._update_intro_outro_labels()

        # Load HD Clarity Upscaler controls
        if hasattr(self, "chk_hd_upscale"):
            hd_on = bool(self.edits.get("hd_upscale_enabled", 0))
            hd_1080 = bool(self.edits.get("hd_upscale_1080p", 0))
            self.chk_hd_upscale.blockSignals(True)
            self.chk_hd_1080p.blockSignals(True)
            self.chk_hd_upscale.setChecked(hd_on)
            self.chk_hd_1080p.setChecked(hd_1080)
            self.chk_hd_1080p.setEnabled(hd_on)
            self.chk_hd_upscale.blockSignals(False)
            self.chk_hd_1080p.blockSignals(False)

        for w in (
            self.sl_logo_scale, self.sl_logo_opacity, self.chk_burn_subs,
            self.sl_sub_y, self.spin_font, self.chk_sub_bg,
            self.sl_bright, self.sl_contrast, self.sl_sat,
            self.sl_custom_bgm, self.chk_ducking
        ):
            w.blockSignals(False)

        self._init_masks_from_edits()
        self._update_mask_combo()
        self._load_active_mask_to_ui()
        self._update_trim_label()
        self._render_overlays()

    def _sync_ui_to_edits(self):
        if getattr(self, "_loading_edits", False):
            return
        if not hasattr(self, "sl_bright") or not hasattr(self, "sl_logo_scale") or not hasattr(self, "combo_ratio"):
            return
        self.edits["logo_scale"] = self.sl_logo_scale.value() / 100.0
        self.edits["logo_opacity"] = self.sl_logo_opacity.value() / 100.0
        self.edits["burn_subs"] = 1 if self.chk_burn_subs.isChecked() else 0
        self.edits["sub_style"] = self.combo_sub_style.currentData() or "classic_box"
        if hasattr(self, "combo_sub_font"):
            self.edits["sub_font_family"] = self.combo_sub_font.currentData() or ""
        self.edits["sub_y"] = self.sl_sub_y.value() / 100.0
        self.edits["sub_font_size"] = self.spin_font.value()
        if hasattr(self, "spin_outline"):
            self.edits["sub_outline"] = self.spin_outline.value()
        self.edits["sub_bg"] = 1 if self.chk_sub_bg.isChecked() else 0
        self.edits["brightness"] = self.sl_bright.value() / 100.0
        self.edits["contrast"] = self.sl_contrast.value() / 100.0
        self.edits["saturation"] = self.sl_sat.value() / 100.0
        old_ratio = self.edits.get("aspect_ratio", "original")
        new_ratio = self.combo_ratio.currentText().split(" ")[0]
        self.edits["aspect_ratio"] = new_ratio
        if old_ratio != new_ratio and hasattr(self, "_native_wh"):
            self._apply_canvas_dimensions(*self._native_wh)
        self.edits["custom_bgm_vol"] = round(self.sl_custom_bgm.value() / 100.0, 2)
        self.edits["orig_volume"] = self.edits["custom_bgm_vol"]
        self.edits["auto_ducking"] = 1 if self.chk_ducking.isChecked() else 0
        if hasattr(self, "sl_ducking_reduction"):
            self.edits["ducking_db"] = self.sl_ducking_reduction.value()
        self.edits["ducking_smoothness"] = getattr(self, "duck_smoothness", "smooth")
        self.edits["voice_fx"] = getattr(self, "voice_fx", "clean")
        if hasattr(self, "sl_dub_vol"):
            self.edits["dub_volume"] = round(self.sl_dub_vol.value() / 100.0, 2)
        if hasattr(self, "chk_normalize"):
            self.edits["normalize_lufs"] = 1 if self.chk_normalize.isChecked() else 0
        if hasattr(self, "chk_auto_timed_blur"):
            self.edits["auto_timed_blur"] = 1 if self.chk_auto_timed_blur.isChecked() else 0
        if "lut_preset" not in self.edits:
            self.edits["lut_preset"] = "none"
        if hasattr(self, "chk_hook_enabled"):
            self.edits["hook_enabled"] = 1 if self.chk_hook_enabled.isChecked() else 0
            self.edits["hook_text"] = self.edit_hook_text.text().strip()
            self.edits["hook_pos"] = self.combo_hook_pos.currentData() or "top"
            self.edits["hook_height_pct"] = self.sl_hook_height.value()
            self.edits["hook_font_size"] = self.sl_hook_font_size.value()
            self.edits.setdefault("hook_bg_color", "#D90429")
            self.edits.setdefault("hook_text_color", "#FFFFFF")
        if hasattr(self, "chk_intro_enabled"):
            self.edits["intro_enabled"] = 1 if self.chk_intro_enabled.isChecked() else 0
            self.edits["outro_enabled"] = 1 if self.chk_outro_enabled.isChecked() else 0
        if hasattr(self, "chk_hd_upscale"):
            self.edits["hd_upscale_enabled"] = 1 if self.chk_hd_upscale.isChecked() else 0
            self.edits["hd_upscale_1080p"] = 1 if (self.chk_hd_upscale.isChecked() and self.chk_hd_1080p.isChecked()) else 0

        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))

    def _render_overlays(self):
        # 1. Logo Watermark
        logo_path = self.edits.get("logo_path", "")
        if logo_path and Path(logo_path).exists():
            pix = QPixmap(logo_path)
            if not pix.isNull():
                target_w = max(24, int(self.canvas_w * float(self.edits.get("logo_scale", 0.15))))
                scaled = pix.scaledToWidth(target_w, Qt.SmoothTransformation)
                self.logo_item.setPixmap(scaled)
                self.logo_item.setOpacity(float(self.edits.get("logo_opacity", 0.90)))
                self.logo_item.setZValue(45)
                self.logo_item.setPos(
                    float(self.edits.get("logo_x", 0.05)) * self.canvas_w,
                    float(self.edits.get("logo_y", 0.05)) * self.canvas_h,
                )
                self.logo_item.setVisible(True)
            else:
                self.logo_item.setVisible(False)
        else:
            self.logo_item.setVisible(False)

        # 2. Multi-Mask Overlays
        while len(self.mask_items) < len(self.masks_list):
            idx = len(self.mask_items)
            item = InteractiveMaskOverlay(idx, self._on_mask_transformed, self._on_mask_selected)
            self.scene.addItem(item)
            self.mask_items.append(item)
        while len(self.mask_items) > len(self.masks_list):
            item = self.mask_items.pop()
            self.scene.removeItem(item)

        for idx, (item, m) in enumerate(zip(self.mask_items, self.masks_list)):
            item.mask_index = idx
            is_active = (idx == self.active_mask_idx)
            item.is_selected = is_active
            if m.get("enabled", True):
                mw = max(24.0, float(m.get("w", 0.90)) * self.canvas_w)
                mh = max(14.0, float(m.get("h", 0.14)) * self.canvas_h)
                mx = float(m.get("x", 0.05)) * self.canvas_w
                my = float(m.get("y", 0.78)) * self.canvas_h
                strength = float(m.get("strength", 0.75))

                item.setRect(0, 0, mw, mh)
                item.setPos(mx, my)

                if m.get("mode", "blur") == "blur":
                    alpha = int(75 + strength * 165)
                    item.setBrush(QBrush(QColor(175, 195, 215, alpha)))
                    border_color = QColor("#38BDF8") if is_active else QColor("#0284C7")
                    item.setPen(QPen(border_color, 2.0 if is_active else 1.2, Qt.DashLine))
                else:
                    base_col = QColor(m.get("color", "#000000"))
                    base_col.setAlpha(int(35 + strength * 220))
                    item.setBrush(QBrush(base_col))
                    border_color = QColor("#F59E0B") if is_active else QColor("#D97706")
                    item.setPen(QPen(border_color, 2.0 if is_active else 1.2, Qt.DashLine))

                item.setVisible(True)
            else:
                item.setVisible(False)

        # 3. Visual preview tint for selected 20+ LUT Preset + Brightness slider
        lut_info = get_lut_preset(self.edits.get("lut_preset", "none"))
        lr, lg, lb, la = lut_info.get("preview_tint", (0, 0, 0, 0))
        b = self.edits.get("brightness", 0.0)
        if la > 0:
            if b > 0:
                lr = min(255, int(lr + b * 120))
                lg = min(255, int(lg + b * 120))
                lb = min(255, int(lb + b * 120))
            elif b < 0:
                la = min(180, int(la + abs(b) * 140))
            self.color_overlay.setBrush(QBrush(QColor(lr, lg, lb, la)))
        elif b > 0:
            self.color_overlay.setBrush(QBrush(QColor(255, 255, 255, int(b * 180))))
        elif b < 0:
            self.color_overlay.setBrush(QBrush(QColor(0, 0, 0, int(abs(b) * 200))))
        else:
            self.color_overlay.setBrush(QBrush(QColor(0, 0, 0, 0)))

        # 4. Live Viral Hook Banner Overlay
        if hasattr(self, "hook_banner_item"):
            self.hook_banner_item.configure(self.canvas_w, self.canvas_h, self.edits)

        # 5. Subtitle Preview & Dynamic Timed Blur Feedback
        cur_pos = self.player.position()
        self._update_live_subtitle(cur_pos)
        self._update_dynamic_blur_visibility(cur_pos)

    def _update_live_subtitle(self, pos_ms: int):
        if not self.edits.get("burn_subs", 0):
            if hasattr(self, "sub_live_item") and self.sub_live_item.isVisible():
                self.sub_live_item.setVisible(False)
            if hasattr(self, "sub_bg_item") and self.sub_bg_item.isVisible():
                self.sub_bg_item.setVisible(False)
            return

        is_playing = self.player.playbackState() == QMediaPlayer.PlayingState

        active_text = ""
        for seg in self.segments:
            if seg["start_ms"] <= pos_ms <= seg["end_ms"]:
                active_text = (seg.get("kh_text") or seg.get("zh_text") or "").strip()
                break

        # បង្ហាញបន្ទាត់គំរូតែពេល Pause ឬពេលតុបតែងម៉ូដអក្សរតែប៉ុណ្ណោះ មិនបង្ហាញពេលវីដេអូកំពុងចាក់ Play ឡើយ
        if not active_text and not is_playing and self.segments:
            active_text = (self.segments[0].get("kh_text") or self.segments[0].get("zh_text") or "").strip()

        if not active_text:
            if hasattr(self, "sub_live_item") and self.sub_live_item.isVisible():
                self.sub_live_item.setVisible(False)
            if hasattr(self, "sub_bg_item") and self.sub_bg_item.isVisible():
                self.sub_bg_item.setVisible(False)
            self._last_sub_cache_key = None
            return

        font_px = max(10, int(self.edits.get("sub_font_size", 24) * 0.65))
        sub_y = self.edits.get("sub_y", 0.85)
        sub_style = self.edits.get("sub_style", "classic_box")
        sub_font_family = (self.edits.get("sub_font_family") or "").strip()
        sub_color = self.edits.get("sub_color", "#FFFFFF")
        sub_bg = self.edits.get("sub_bg", 1)
        sub_outline = self.edits.get("sub_outline", 2)

        cache_key = (
            active_text, font_px, sub_y, sub_style, sub_font_family,
            sub_color, sub_bg, sub_outline, self.canvas_w, self.canvas_h
        )
        if getattr(self, "_last_sub_cache_key", None) == cache_key and self.sub_live_item.isVisible():
            return
        self._last_sub_cache_key = cache_key

        st = get_sub_style(sub_style)
        font_family = sub_font_family if sub_font_family else st.get("font", "Khmer OS Battambang")
        is_bold = bool(st.get("bold", 1))
        border_style = int(st.get("border_style", 1))

        # Primary fill color
        if sub_style == "classic_box" and sub_color:
            eff_color = QColor(sub_color)
        else:
            tr, tg, tb = ass_color_to_rgb(st.get("primary", "&H00FFFFFF"))
            eff_color = QColor(tr, tg, tb)

        # Outline color & stroke width (BorderStyle=3 uses box fill instead of heavy text outline)
        or_, og, ob = ass_color_to_rgb(st.get("outline_col", "&H00000000"))
        outline_qcolor = QColor(or_, og, ob)
        outline_w = 0 if border_style == 3 else (int(sub_outline) if sub_outline is not None else int(st.get("outline", 2)))

        # Shadow color & distance
        shadow_dist = 0 if border_style == 3 else int(st.get("shadow", 2))
        shadow_qcolor = QColor(0, 0, 0, 180) if shadow_dist > 0 else QColor(0, 0, 0, 0)

        # Background color & box
        br, bg, bb, ba = ass_color_to_rgba(st.get("back_col", "&H48000000"))
        bg_qcolor = QColor(br, bg, bb, ba)
        show_box = True if border_style == 3 else bool(sub_bg and sub_style == "classic_box")

        # Safe-Zone Width: strictly <= 88% of canvas width, centered, auto-scaling font if > 2 lines
        safe_max_w = max(110.0, self.canvas_w * 0.88)
        self.sub_live_item.setTextWidth(safe_max_w)

        font = QFont(font_family, font_px, QFont.Bold if is_bold else QFont.Normal)
        self.sub_live_item.set_content(
            text=active_text,
            font=font,
            text_col=eff_color,
            outline_col=outline_qcolor,
            outline_w=outline_w,
            shadow_col=shadow_qcolor,
            shadow_dist=shadow_dist,
            bg_col=bg_qcolor,
            show_box=show_box,
            max_w=safe_max_w,
        )

        rect = self.sub_live_item.boundingRect()
        pad_edge = max(6.0, self.canvas_w * 0.06)
        x = (self.canvas_w - rect.width()) / 2.0
        x = max(pad_edge, min(max(pad_edge, self.canvas_w - rect.width() - pad_edge), x))
        y = (sub_y * self.canvas_h) - (rect.height() / 2.0)
        y = max(6.0, min(self.canvas_h - rect.height() - 6.0, y))

        self.sub_live_item.setPos(x, y)
        self.sub_live_item.setVisible(True)
        if hasattr(self, "sub_bg_item"):
            self.sub_bg_item.setVisible(False)

    def _on_logo_dragged(self, x: float, y: float):
        self.edits["logo_x"] = round(max(0.0, min(0.95, x / self.canvas_w)), 3)
        self.edits["logo_y"] = round(max(0.0, min(0.95, y / self.canvas_h)), 3)
        self.edits_changed.emit(dict(self.edits))

    def _set_logo_preset(self, x: float, y: float):
        """កំណត់ទីតាំង Logo តាមប៊ូតុង Preset លឿន (លើ-ឆ្វេង, លើ-ស្តាំ, ក្រោម-ឆ្វេង, ក្រោម-ស្តាំ, កណ្តាល)"""
        self.edits["logo_x"] = x
        self.edits["logo_y"] = y
        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))

    def _choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Logo", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.edits["logo_path"] = path
            if "logo_x" not in self.edits:
                self.edits["logo_x"] = 0.05
            if "logo_y" not in self.edits:
                self.edits["logo_y"] = 0.05
            if hasattr(self, "lbl_logo_info"):
                self.lbl_logo_info.setText(f"📁 {Path(path).name}")
            self._render_overlays()
            self.edits_changed.emit(dict(self.edits))

    def _clear_logo(self):
        self.edits["logo_path"] = ""
        if hasattr(self, "lbl_logo_info"):
            self.lbl_logo_info.setText("គ្មាន Logo ត្រូវបានជ្រើសរើសទេ")
        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))

    def _pick_sub_color(self):
        color = QColorDialog.getColor(QColor(self.edits.get("sub_color", "#FFFFFF")), self)
        if color.isValid():
            self.edits["sub_color"] = color.name()
            self._render_overlays()
            self.edits_changed.emit(dict(self.edits))

    def _reset_adjustments(self):
        self.sl_bright.setValue(0)
        self.sl_contrast.setValue(100)
        self.sl_sat.setValue(100)
        self._select_lut_preset("none")

    def _on_hd_upscale_toggled(self, checked: bool):
        if hasattr(self, "chk_hd_1080p"):
            self.chk_hd_1080p.setEnabled(bool(checked))
        self._sync_ui_to_edits()

    def _choose_custom_bgm(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Music", "", "Audio (*.mp3 *.wav *.m4a *.aac *.flac)"
        )
        if path:
            self.edits["custom_bgm_path"] = path
            self.btn_pick_bgm.setText(f"🎵 {Path(path).name[:18]}")
            self.edits_changed.emit(dict(self.edits))

    def _clear_custom_bgm(self):
        self.edits["custom_bgm_path"] = ""
        self.btn_pick_bgm.setText("🎵 រើសភ្លេង BGM (.mp3)")
        self.edits_changed.emit(dict(self.edits))

    def _set_trim_start(self):
        self.edits["trim_start_ms"] = self.player.position()
        self._update_trim_label()
        self.edits_changed.emit(dict(self.edits))

    def _set_trim_end(self):
        self.edits["trim_end_ms"] = self.player.position()
        self._update_trim_label()
        self.edits_changed.emit(dict(self.edits))

    def _clear_trim(self):
        self.edits["trim_start_ms"] = 0
        self.edits["trim_end_ms"] = 0
        self._update_trim_label()
        self.edits_changed.emit(dict(self.edits))

    def _update_trim_label(self):
        s = self.edits.get("trim_start_ms", 0)
        e = self.edits.get("trim_end_ms", 0)
        if s == 0 and e == 0:
            self.lbl_trim_info.setText("Full Video (No Trim)")
        else:
            self.lbl_trim_info.setText(f"Trim: {self._fmt(s)} → {self._fmt(e) if e else 'End'}")

    # --- Hook Banner & Cover Helpers (Feature 3) ---
    def set_hook_generating(self, busy: bool):
        if hasattr(self, "btn_ai_hook"):
            self.btn_ai_hook.setEnabled(not busy)
            self.btn_ai_hook.setText("⏳ កំពុងបង្កើត Viral Hook Title..." if busy else "✨ AI Generate Viral Hook Title")

    def set_generated_hook_text(self, hook_title: str):
        clean = (hook_title or "").strip()
        if not clean:
            return
        if hasattr(self, "edit_hook_text"):
            self.edit_hook_text.blockSignals(True)
            self.edit_hook_text.setText(clean)
            self.edit_hook_text.blockSignals(False)
        if hasattr(self, "chk_hook_enabled") and not self.chk_hook_enabled.isChecked():
            self.chk_hook_enabled.blockSignals(True)
            self.chk_hook_enabled.setChecked(True)
            self.chk_hook_enabled.blockSignals(False)
        self.edits["hook_text"] = clean
        self.edits["hook_enabled"] = 1
        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))

    def _on_hook_text_edited(self, text: str):
        if text.strip() and hasattr(self, "chk_hook_enabled") and not self.chk_hook_enabled.isChecked():
            self.chk_hook_enabled.blockSignals(True)
            self.chk_hook_enabled.setChecked(True)
            self.chk_hook_enabled.blockSignals(False)
        self._sync_ui_to_edits()

    def _update_hook_color_buttons(self):
        bg = str(self.edits.get("hook_bg_color", "#D90429") or "#D90429")
        fg = str(self.edits.get("hook_text_color", "#FFFFFF") or "#FFFFFF")
        if hasattr(self, "btn_hook_bg_color"):
            self.btn_hook_bg_color.setStyleSheet(
                f"background: {bg}; color: #FFFFFF; border: 1px solid #475569; border-radius: 5px; padding: 4px 6px; font-size: 10.5px; font-weight: 700;"
            )
        if hasattr(self, "btn_hook_text_color"):
            self.btn_hook_text_color.setStyleSheet(
                f"background: #181C24; color: {fg}; border: 1px solid #475569; border-radius: 5px; padding: 4px 6px; font-size: 10.5px; font-weight: 700;"
            )

    def _pick_hook_bg_color(self):
        cur = QColor(str(self.edits.get("hook_bg_color", "#D90429") or "#D90429"))
        c = QColorDialog.getColor(cur, self, "Choose Hook Banner Bar Color")
        if c.isValid():
            self.edits["hook_bg_color"] = c.name()
            self._update_hook_color_buttons()
            self._render_overlays()
            self.edits_changed.emit(dict(self.edits))

    def _pick_hook_text_color(self):
        cur = QColor(str(self.edits.get("hook_text_color", "#FFFFFF") or "#FFFFFF"))
        c = QColorDialog.getColor(cur, self, "Choose Hook Banner Text Color")
        if c.isValid():
            self.edits["hook_text_color"] = c.name()
            self._update_hook_color_buttons()
            self._render_overlays()
            self.edits_changed.emit(dict(self.edits))

    def _apply_hook_color_preset(self, bg_hex: str, fg_hex: str):
        self.edits["hook_bg_color"] = bg_hex
        self.edits["hook_text_color"] = fg_hex
        if hasattr(self, "chk_hook_enabled") and not self.chk_hook_enabled.isChecked():
            self.chk_hook_enabled.setChecked(True)
        self._update_hook_color_buttons()
        self._render_overlays()
        self.edits_changed.emit(dict(self.edits))

    def _save_thumbnail_jpg(self):
        src_vid = self.original_video_path if (self.original_video_path and Path(self.original_video_path).exists()) else self.dubbed_preview_path
        if not src_vid or not Path(src_vid).exists():
            QMessageBox.warning(self, "Thumbnail Cover", "សូមបើកវីដេអូជាមុនសិន មុននឹងរក្សាទុក Thumbnail (.jpg)!")
            return

        default_name = f"{Path(src_vid).stem}_Thumbnail.jpg"
        default_dir = str(Path(src_vid).parent / default_name)
        out_jpg, _ = QFileDialog.getSaveFileName(
            self, "Save Thumbnail Cover (.jpg)", default_dir, "JPEG Image (*.jpg *.jpeg)"
        )
        if not out_jpg:
            return
        if not out_jpg.lower().endswith((".jpg", ".jpeg")):
            out_jpg += ".jpg"

        self._sync_ui_to_edits()
        pos_ms = max(0, int(self.player.position()))
        try:
            from core.media_engine import MediaEngine
            saved = MediaEngine.capture_thumbnail_jpg(src_vid, pos_ms, out_jpg, dict(self.edits))
            reply = QMessageBox.information(
                self,
                "Thumbnail Saved",
                f"📸 បានរក្សាទុក Thumbnail Cover កម្រិតច្បាស់ដើមដោយជោគជ័យ!\n{saved}",
                QMessageBox.Open | QMessageBox.Ok,
            )
            if reply == QMessageBox.Open:
                import os
                os.startfile(saved)
        except Exception as e:
            QMessageBox.critical(self, "Thumbnail Error", f"មិនអាចរក្សាទុក Thumbnail បានទេ:\n{e}")

    # --- Auto Intro & Outro Stitcher Helpers (Feature 4) ---
    def _update_intro_outro_labels(self):
        ip = str(self.edits.get("intro_path", "") or "")
        op = str(self.edits.get("outro_path", "") or "")
        if hasattr(self, "lbl_intro_info"):
            if ip and Path(ip).exists():
                self.lbl_intro_info.setText(f"🎬 Intro: {Path(ip).name}")
                self.lbl_intro_info.setStyleSheet("font-size: 10px; color: #34D399; font-weight: 600;")
            else:
                self.lbl_intro_info.setText("មិនទាន់ជ្រើសរើស Intro Video ទេ")
                self.lbl_intro_info.setStyleSheet("font-size: 10px; color: #8E95A5; font-style: italic;")
        if hasattr(self, "lbl_outro_info"):
            if op and Path(op).exists():
                self.lbl_outro_info.setText(f"🎬 Outro: {Path(op).name}")
                self.lbl_outro_info.setStyleSheet("font-size: 10px; color: #F59E0B; font-weight: 600;")
            else:
                self.lbl_outro_info.setText("មិនទាន់ជ្រើសរើស Outro Video ទេ")
                self.lbl_outro_info.setStyleSheet("font-size: 10px; color: #8E95A5; font-style: italic;")

    def _choose_intro_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Intro Video (.mp4)", "", "Videos (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.edits["intro_path"] = path
            self.edits["intro_enabled"] = 1
            if hasattr(self, "chk_intro_enabled"):
                self.chk_intro_enabled.blockSignals(True)
                self.chk_intro_enabled.setChecked(True)
                self.chk_intro_enabled.blockSignals(False)
            self._update_intro_outro_labels()
            self.edits_changed.emit(dict(self.edits))

    def _clear_intro_video(self):
        self.edits["intro_path"] = ""
        self.edits["intro_enabled"] = 0
        if hasattr(self, "chk_intro_enabled"):
            self.chk_intro_enabled.blockSignals(True)
            self.chk_intro_enabled.setChecked(False)
            self.chk_intro_enabled.blockSignals(False)
        self._update_intro_outro_labels()
        self.edits_changed.emit(dict(self.edits))

    def _choose_outro_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Outro Video (.mp4)", "", "Videos (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.edits["outro_path"] = path
            self.edits["outro_enabled"] = 1
            if hasattr(self, "chk_outro_enabled"):
                self.chk_outro_enabled.blockSignals(True)
                self.chk_outro_enabled.setChecked(True)
                self.chk_outro_enabled.blockSignals(False)
            self._update_intro_outro_labels()
            self.edits_changed.emit(dict(self.edits))

    def _clear_outro_video(self):
        self.edits["outro_path"] = ""
        self.edits["outro_enabled"] = 0
        if hasattr(self, "chk_outro_enabled"):
            self.chk_outro_enabled.blockSignals(True)
            self.chk_outro_enabled.setChecked(False)
            self.chk_outro_enabled.blockSignals(False)
        self._update_intro_outro_labels()
        self.edits_changed.emit(dict(self.edits))
