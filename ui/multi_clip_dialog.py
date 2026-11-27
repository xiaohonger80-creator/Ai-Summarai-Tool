from pathlib import Path
from typing import List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QLabel, QMessageBox, QRadioButton, QButtonGroup,
    QSpinBox, QFrame
)


class MultiClipComposerDialog(QDialog):
    MAX_CLIPS = 50

    def __init__(self, lang: str = "kh", parent=None, has_active_project: bool = False):
        super().__init__(parent)
        self.lang = lang
        self.has_active_project = has_active_project
        self.selected_files: List[str] = []
        self.action_mode = "merge"  # "merge", "batch", or "viral_shorts"
        self.shorts_max_clips = 12
        self.shorts_min_sec = 45
        self.shorts_max_sec = 90

        self.setWindowTitle(
            "🎬 បញ្ចូលវីដេអូច្រើន (រហូតដល់ ៥០ ឈុត)" if lang == "kh"
            else "🎬 Multi-Video Timeline Composer (Up to 50 Clips)"
        )
        self.resize(680, 470)
        self._build_ui()

    def _build_ui(self):
        kh = self.lang == "kh"
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # របារខាងលើ៖ បន្ថែមវីដេអូ + តម្រៀបលំដាប់
        top = QHBoxLayout()
        btn_add = QPushButton("+ បន្ថែមវីដេអូ (អតិបរមា ៥០)" if kh else "+ Add Videos (Max 50)")
        btn_add.setObjectName("BtnBlue")
        btn_add.clicked.connect(self._add_files)

        btn_up = QPushButton("▲ ឡើង" if kh else "▲ Up")
        btn_up.clicked.connect(lambda: self._move_item(-1))

        btn_down = QPushButton("▼ ចុះ" if kh else "▼ Down")
        btn_down.clicked.connect(lambda: self._move_item(1))

        btn_del = QPushButton("🗑 លុប" if kh else "🗑 Remove")
        btn_del.clicked.connect(self._remove_selected)

        btn_clear = QPushButton("សម្អាតទាំងអស់" if kh else "Clear All")
        btn_clear.clicked.connect(self._clear_all)

        for w in (btn_add, btn_up, btn_down, btn_del, btn_clear):
            top.addWidget(w)
        layout.addLayout(top)

        # បញ្ជីឈ្មោះវីដេអូទាំង ៥០
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background: #181818; border: 1px solid #2C2C2C; border-radius: 8px; padding: 6px; font-size: 13px; }"
            "QListWidget::item { padding: 7px; border-bottom: 1px solid #242424; }"
            "QListWidget::item:selected { background: #1F3A3D; color: #00C4CC; font-weight: bold; }"
        )
        layout.addWidget(self.list_widget, 1)

        self.lbl_count = QLabel("បានជ្រើសរើស៖ 0 / 50 វីដេអូ" if kh else "Selected: 0 / 50 videos")
        self.lbl_count.setStyleSheet("color: #00C4CC; font-weight: 700;")
        layout.addWidget(self.lbl_count)

        # ជម្រើសរបៀបដំណើរការ ៣ បែប (Merge / Batch / AI Auto-Cut Viral Shorts 9:16)
        mode_box = QVBoxLayout()
        self.rb_merge = QRadioButton(
            "🔗 តភ្ជាប់វីដេអូទាំងអស់ជាប់គ្នាក្នុង Timeline && Preview តែមួយ (ដូច CapCut)"
            if kh else "🔗 Merge all clips continuously into ONE Timeline && Preview (Like CapCut)"
        )
        self.rb_merge.setChecked(True)

        self.rb_batch = QRadioButton(
            "📚 បកប្រែ និង Export ដាច់ដោយឡែកម្តងមួយៗ (Batch 50 ឯកសារ)"
            if kh else "📚 Dub & Export each video separately (Batch 50 files)"
        )

        self.rb_viral_shorts = QRadioButton(
            "⚡ Auto-Cut Viral Shorts (កាត់ឈុតខ្លីៗស្វ័យប្រវត្តិ 9:16 ចំនួន ១០–២០ ឈុត ពីរឿងវែង)"
            if kh else "⚡ Auto-Cut Viral Shorts (AI auto-cut 10–20 vertical 9:16 cliffhanger clips)"
        )
        self.rb_viral_shorts.setStyleSheet("color: #34D399; font-weight: 700;")

        grp = QButtonGroup(self)
        grp.addButton(self.rb_merge)
        grp.addButton(self.rb_batch)
        grp.addButton(self.rb_viral_shorts)
        mode_box.addWidget(self.rb_merge)
        mode_box.addWidget(self.rb_batch)
        mode_box.addWidget(self.rb_viral_shorts)

        # Compact Viral Shorts options row (visible when Auto-Cut Viral Shorts is selected)
        self.shorts_opts_frame = QFrame()
        self.shorts_opts_frame.setObjectName("ShortsOpts")
        self.shorts_opts_frame.setStyleSheet(
            "QFrame#ShortsOpts { background: #141A23; border: 1px solid #10B981; border-radius: 6px; }"
        )
        so_row = QHBoxLayout(self.shorts_opts_frame)
        so_row.setContentsMargins(10, 6, 10, 6)
        so_row.setSpacing(10)

        lbl_sc = QLabel("ចំនួនឈុតខ្លី (Shorts):" if kh else "Max Shorts:")
        lbl_sc.setStyleSheet("font-size: 11px; color: #A7F3D0; font-weight: 600;")
        self.spin_shorts_count = QSpinBox()
        self.spin_shorts_count.setRange(1, 20)
        self.spin_shorts_count.setValue(12)
        self.spin_shorts_count.setSuffix(" ឈុត" if kh else " clips")

        lbl_sd = QLabel("រយៈពេលឈុតនីមួយៗ:" if kh else "Clip Length:")
        lbl_sd.setStyleSheet("font-size: 11px; color: #A7F3D0; font-weight: 600;")
        self.spin_shorts_min = QSpinBox()
        self.spin_shorts_min.setRange(15, 75)
        self.spin_shorts_min.setValue(45)
        self.spin_shorts_min.setSuffix("s")

        lbl_to = QLabel("→")
        lbl_to.setStyleSheet("color: #94A3B8; font-weight: 700;")

        self.spin_shorts_max = QSpinBox()
        self.spin_shorts_max.setRange(30, 120)
        self.spin_shorts_max.setValue(90)
        self.spin_shorts_max.setSuffix("s")

        so_row.addWidget(lbl_sc)
        so_row.addWidget(self.spin_shorts_count)
        so_row.addStretch()
        so_row.addWidget(lbl_sd)
        so_row.addWidget(self.spin_shorts_min)
        so_row.addWidget(lbl_to)
        so_row.addWidget(self.spin_shorts_max)
        self.shorts_opts_frame.setVisible(False)
        mode_box.addWidget(self.shorts_opts_frame)

        self.rb_viral_shorts.toggled.connect(self.shorts_opts_frame.setVisible)
        layout.addLayout(mode_box)

        # ប៊ូតុងយល់ព្រមខាងក្រោម
        bottom = QHBoxLayout()
        bottom.addStretch()
        btn_cancel = QPushButton("បោះបង់" if kh else "Cancel")
        btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton("✅ បញ្ចូលទៅកាន់ Workspace" if kh else "✅ Load into Workspace")
        self.btn_confirm.setObjectName("BtnGreen")
        self.btn_confirm.clicked.connect(self._on_confirm)

        bottom.addWidget(btn_cancel)
        bottom.addWidget(self.btn_confirm)
        layout.addLayout(bottom)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Videos (Up to 50)", "", "Videos (*.mp4 *.mkv *.mov *.avi *.flv)"
        )
        if not files:
            return
        remaining = self.MAX_CLIPS - len(self.selected_files)
        if len(files) > remaining:
            QMessageBox.information(
                self, "Limit 50",
                f"អនុញ្ញាតអតិបរមា {self.MAX_CLIPS} វីដេអូ! ប្រព័ន្ធនឹងបន្ថែម {max(0, remaining)} វីដេអូដំបូង។"
            )
        for f in files[:max(0, remaining)]:
            self.selected_files.append(f)
        self._refresh_list()

    def _move_item(self, direction: int):
        row = self.list_widget.currentRow()
        new_row = row + direction
        if 0 <= row < len(self.selected_files) and 0 <= new_row < len(self.selected_files):
            self.selected_files[row], self.selected_files[new_row] = (
                self.selected_files[new_row],
                self.selected_files[row],
            )
            self._refresh_list()
            self.list_widget.setCurrentRow(new_row)

    def _remove_selected(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.selected_files):
            self.selected_files.pop(row)
            self._refresh_list()

    def _clear_all(self):
        self.selected_files.clear()
        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for idx, path in enumerate(self.selected_files, start=1):
            self.list_widget.addItem(QListWidgetItem(f"ឈុតទី {idx:02d}  |  {Path(path).name}"))
        kh = self.lang == "kh"
        self.lbl_count.setText(
            f"បានជ្រើសរើស៖ {len(self.selected_files)} / {self.MAX_CLIPS} វីដេអូ" if kh
            else f"Selected: {len(self.selected_files)} / {self.MAX_CLIPS} videos"
        )

    def _on_confirm(self):
        if self.rb_viral_shorts.isChecked():
            if not self.selected_files and not self.has_active_project:
                QMessageBox.information(
                    self, "Auto-Cut Viral Shorts",
                    "សូមជ្រើសរើសវីដេអូរឿងវែង ឬបើកគម្រោងវីដេអូក្នុង Workspace ជាមុនសិន!"
                )
                return
            self.action_mode = "viral_shorts"
            self.shorts_max_clips = self.spin_shorts_count.value()
            self.shorts_min_sec = min(self.spin_shorts_min.value(), self.spin_shorts_max.value())
            self.shorts_max_sec = max(self.spin_shorts_min.value() + 5, self.spin_shorts_max.value())
            self.accept()
            return
        if not self.selected_files:
            return
        self.action_mode = "merge" if self.rb_merge.isChecked() else "batch"
        self.accept()
