# -*- coding: utf-8 -*-
"""
ui/widgets/segment_table.py
Editable 6-Column QTableWidget:
[#, Timecode, Speaker / Voice, Voice FX, Original Text, Translated / Recap Script]
Includes per-row `Voice FX` QComboBox delegate (`Normal`, `Inner Thought`, `Phone Call`, `Radio`)
and right-click Speaker Role Mapper shortcut.
"""

from typing import List, Dict, Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QMenu
)

from core.schema import SubtitleSegment, normalize_segments


class SegmentTable(QTableWidget):
    """
    Live-updating editable subtitle & recap script table with per-row Voice FX selector.
    """

    segments_edited = Signal(list)
    row_selected = Signal(float)                   # Emits start timestamp (seconds)
    open_speaker_mapper_requested = Signal()       # Emits when user right-clicks -> Map Speaker Roles

    COLUMNS = [
        "#",
        "Timecode",
        "Speaker / Voice",
        "Voice FX",
        "Original Text",
        "Translated / Recap Script",
    ]

    FX_LABELS = [
        ("Normal", "normal"),
        ("Inner Thought", "inner_thought"),
        ("Phone Call", "phone_call"),
        ("Radio", "radio"),
    ]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, 44)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        self.setColumnWidth(1, 130)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        self.setColumnWidth(2, 115)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self.setColumnWidth(3, 125)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)

        self._segments: List[Dict[str, Any]] = []
        self._updating = False

        self.itemChanged.connect(self._on_item_changed)
        self.cellClicked.connect(self._on_cell_clicked)

    def set_segments(self, segments: List[Dict[str, Any]]) -> None:
        self._updating = True
        try:
            self._segments = normalize_segments(segments)
            self.setRowCount(len(self._segments))

            for r, seg in enumerate(self._segments):
                sid_item = QTableWidgetItem(str(seg.get("id", r + 1)))
                sid_item.setFlags(sid_item.flags() & ~Qt.ItemIsEditable)
                sid_item.setTextAlignment(Qt.AlignCenter)
                self.setItem(r, 0, sid_item)

                tc_str = f"{seg['start']:.2f}s - {seg['end']:.2f}s"
                tc_item = QTableWidgetItem(tc_str)
                tc_item.setFlags(tc_item.flags() & ~Qt.ItemIsEditable)
                tc_item.setTextAlignment(Qt.AlignCenter)
                self.setItem(r, 1, tc_item)

                spk_item = QTableWidgetItem(str(seg.get("speaker", "SPEAKER_01")))
                self.setItem(r, 2, spk_item)

                fx_combo = QComboBox()
                cur_fx = str(seg.get("voice_fx", "normal")).lower()
                matched_idx = 0
                for idx, (label, val) in enumerate(self.FX_LABELS):
                    fx_combo.addItem(label, val)
                    if val == cur_fx:
                        matched_idx = idx
                fx_combo.setCurrentIndex(matched_idx)
                fx_combo.currentIndexChanged.connect(lambda _i, row_idx=r: self._on_fx_combo_changed(row_idx))
                self.setCellWidget(r, 3, fx_combo)

                orig_item = QTableWidgetItem(str(seg.get("text", "")))
                self.setItem(r, 4, orig_item)

                trans_item = QTableWidgetItem(str(seg.get("translated", "")))
                self.setItem(r, 5, trans_item)
        finally:
            self._updating = False

    def get_segments(self) -> List[Dict[str, Any]]:
        return list(self._segments)

    def get_detected_speakers(self) -> List[str]:
        seen: List[str] = []
        for s in self._segments:
            spk = str(s.get("speaker") or "SPEAKER_01").strip()
            if spk and spk not in seen:
                seen.append(spk)
        return seen

    def _on_fx_combo_changed(self, row: int) -> None:
        if self._updating or not (0 <= row < len(self._segments)):
            return
        combo: QComboBox = self.cellWidget(row, 3)
        if combo:
            self._segments[row]["voice_fx"] = str(combo.currentData() or "normal")
            self.segments_edited.emit(self._segments)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row = item.row()
        col = item.column()
        if 0 <= row < len(self._segments):
            if col == 2:
                self._segments[row]["speaker"] = item.text().strip()
            elif col == 4:
                self._segments[row]["text"] = item.text().strip()
            elif col == 5:
                self._segments[row]["translated"] = item.text().strip()
            self.segments_edited.emit(self._segments)

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._segments):
            self.row_selected.emit(float(self._segments[row].get("start", 0.0)))

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_map = menu.addAction("🎙️ Map Speaker Roles & Voices...")
        act_fx_thought = menu.addAction("💭 Set Row to 'Inner Thought' Reverb")
        act_fx_phone = menu.addAction("📞 Set Row to 'Phone Call' Bandpass")
        act_fx_normal = menu.addAction("🔊 Set Row to 'Normal' Voice")

        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        row = self.currentRow()
        if chosen == act_map:
            self.open_speaker_mapper_requested.emit()
        elif chosen in (act_fx_thought, act_fx_phone, act_fx_normal) and 0 <= row < len(self._segments):
            target_fx = "inner_thought" if chosen == act_fx_thought else ("phone_call" if chosen == act_fx_phone else "normal")
            combo: QComboBox = self.cellWidget(row, 3)
            if combo:
                for i in range(combo.count()):
                    if combo.itemData(i) == target_fx:
                        combo.setCurrentIndex(i)
                        break

    def export_srt(self, out_srt_path: str, use_translated: bool = True) -> str:
        lines: List[str] = []
        for idx, raw in enumerate(self._segments, start=1):
            seg = SubtitleSegment.from_dict(raw, default_id=idx)
            content = (seg.translated if use_translated and seg.translated else seg.text).strip()
            if not content:
                continue
            lines.append(f"{idx}")
            lines.append(f"{seg.start_timecode} --> {seg.end_timecode}")
            lines.append(content)
            lines.append("")
        with open(out_srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return out_srt_path
