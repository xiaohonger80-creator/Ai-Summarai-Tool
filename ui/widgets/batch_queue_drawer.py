# -*- coding: utf-8 -*-
"""
ui/widgets/batch_queue_drawer.py
Collapsible / Tabbed Batch Queue & Auto-Episode Splitter Panel:
  - "+ Add Files", "+ Add Folder", "Clear Completed"
  - "Auto-Split Episodes" selector: Off, Every 10 Min, Every 15 Min, Every 20 Min
  - Clicking any row loads its video and segments into the main workspace.
"""

from pathlib import Path
from typing import List, Dict, Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog
)

from core.batch_manager import BatchManager, BatchQueueItem


class BatchQueueDrawer(QWidget):
    """
    Multi-File & Folder Batch Queue Table with FFmpeg Stream-Copy Auto-Episode Splitting.
    """

    queue_item_selected = Signal(dict)   # Emits BatchQueueItem dict when clicked
    queue_changed = Signal(list)         # Emits list of BatchQueueItem objects

    SPLIT_MAP = {
        "Off (No Split)": 0,
        "Every 10 Min": 10,
        "Every 15 Min": 15,
        "Every 20 Min": 20,
    }

    def __init__(self, batch_manager: BatchManager = None, parent=None):
        super().__init__(parent)
        self.batch_manager = batch_manager or BatchManager()
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Top control bar
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)

        self.btn_add_files = QPushButton("+ Add Files")
        self.btn_add_files.clicked.connect(self._on_add_files)
        ctrl.addWidget(self.btn_add_files)

        self.btn_add_folder = QPushButton("+ Add Folder")
        self.btn_add_folder.clicked.connect(self._on_add_folder)
        ctrl.addWidget(self.btn_add_folder)

        self.btn_clear_done = QPushButton("Clear Completed")
        self.btn_clear_done.clicked.connect(self._on_clear_completed)
        ctrl.addWidget(self.btn_clear_done)

        ctrl.addStretch()
        ctrl.addWidget(QLabel("Auto-Split Episodes:"))

        self.combo_split = QComboBox()
        self.combo_split.addItems(list(self.SPLIT_MAP.keys()))
        ctrl.addWidget(self.combo_split)

        layout.addLayout(ctrl)

        # Queue table
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["#", "Episode / File Name", "Duration", "Status"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(165)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 90)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 130)

        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)

    def get_auto_split_minutes(self) -> int:
        return self.SPLIT_MAP.get(self.combo_split.currentText(), 0)

    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Video Files to Batch Queue",
            "",
            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm);;All Files (*.*)",
        )
        if files:
            self.batch_manager.add_files(files, auto_split_minutes=self.get_auto_split_minutes())
            self.refresh_table()

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Video Folder for Batch Queue")
        if folder:
            self.batch_manager.add_folder(folder, auto_split_minutes=self.get_auto_split_minutes())
            self.refresh_table()

    def _on_clear_completed(self) -> None:
        self.batch_manager.clear_completed()
        self.refresh_table()

    def refresh_table(self) -> None:
        items = self.batch_manager.items
        self.table.setRowCount(len(items))
        for r, item in enumerate(items):
            id_it = QTableWidgetItem(str(item.id))
            id_it.setTextAlignment(Qt.AlignCenter)
            id_it.setFlags(id_it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, id_it)

            name_it = QTableWidgetItem(Path(item.video_path).name)
            name_it.setToolTip(item.video_path)
            name_it.setFlags(name_it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 1, name_it)

            mins = int(item.duration_sec // 60)
            secs = int(item.duration_sec % 60)
            dur_it = QTableWidgetItem(f"{mins:02d}:{secs:02d}")
            dur_it.setTextAlignment(Qt.AlignCenter)
            dur_it.setFlags(dur_it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 2, dur_it)

            st_it = QTableWidgetItem(item.status)
            st_it.setTextAlignment(Qt.AlignCenter)
            st_it.setFlags(st_it.flags() & ~Qt.ItemIsEditable)
            if item.error_tooltip:
                st_it.setToolTip(item.error_tooltip)
            self.table.setItem(r, 3, st_it)

        self.queue_changed.emit(items)

    def update_item_status(self, item_id: int, status: str, detail: str = "") -> None:
        if status == "Failed":
            self.batch_manager.update_status(item_id, status, error_tooltip=detail)
        elif status == "Completed":
            self.batch_manager.update_status(item_id, status, output_path=detail)
        else:
            self.batch_manager.update_status(item_id, status)
        self.refresh_table()

    def _on_row_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self.batch_manager.items):
            self.queue_item_selected.emit(self.batch_manager.items[row].to_dict())
