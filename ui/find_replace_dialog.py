from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QLabel, QComboBox, QCheckBox, QMessageBox
)


class FindReplaceDialog(QDialog):
    """ផ្ទាំងស្វែងរក និងកែពាក្យខុស (Find & Replace) ទាំងម្តងមួយកន្លែង និងកែទាំងអស់"""

    def __init__(self, db, project_id: int, lang: str = "kh", on_updated_cb=None, on_jump_row_cb=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.project_id = project_id
        self.lang = lang
        self.on_updated_cb = on_updated_cb
        self.on_jump_row_cb = on_jump_row_cb
        self._match_cursor = -1
        self._matches = []

        kh = lang == "kh"
        self.setWindowTitle("🔍 ស្វែងរក និងកែពាក្យខុស (Find & Replace)" if kh else "🔍 Find & Replace")
        self.resize(500, 310)
        self._build_ui()
        self._scan_matches()

    def _build_ui(self):
        kh = self.lang == "kh"
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        lbl_title = QLabel(
            "ស្វែងរក និងកែពាក្យខុសក្នុងអត្ថបទបកប្រែខ្មែរ ឬអត្ថបទដើមភាសាចិន៖"
            if kh else "Find and replace misspelled words in Khmer or Chinese segments:"
        )
        lbl_title.setStyleSheet("color: #CBD5E1; font-weight: 600;")
        layout.addWidget(lbl_title)

        form = QFormLayout()
        form.setSpacing(8)

        self.txt_find = QLineEdit()
        self.txt_find.setPlaceholderText("វាយពាក្យដែលចង់ស្វែងរក (ឧ. ពាក្យខុស)..." if kh else "Find word...")
        self.txt_find.textChanged.connect(self._scan_matches)

        self.txt_replace = QLineEdit()
        self.txt_replace.setPlaceholderText("វាយពាក្យត្រឹមត្រូវដែលចង់ជំនួស..." if kh else "Replace with...")

        self.combo_target = QComboBox()
        if kh:
            self.combo_target.addItems([
                "អត្ថបទបកប្រែខ្មែរ (KH Text)",
                "អត្ថបទដើមភាសាចិន (ZH Text)",
                "ទាំងពីរ (ខ្មែរ និង ចិន)",
            ])
        else:
            self.combo_target.addItems([
                "Khmer Translation (KH Text)",
                "Original Chinese (ZH Text)",
                "Both (KH & ZH)",
            ])
        self.combo_target.currentIndexChanged.connect(self._scan_matches)

        self.chk_case = QCheckBox("ប្រកាន់អក្សរធំ-តូច (Match Case)" if kh else "Match Case")
        self.chk_case.toggled.connect(self._scan_matches)

        form.addRow("ស្វែងរក (Find):" if kh else "Find:", self.txt_find)
        form.addRow("ជំនួសដោយ (Replace):" if kh else "Replace:", self.txt_replace)
        form.addRow("ជួរឈរ (Target):" if kh else "Target:", self.combo_target)
        form.addRow("", self.chk_case)
        layout.addLayout(form)

        self.lbl_status = QLabel("រកឃើញ៖ 0 កន្លែង" if kh else "Matches found: 0")
        self.lbl_status.setStyleSheet("color: #00C4CC; font-weight: 700; padding: 2px 0;")
        layout.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_find_next = QPushButton("🔎 រកបន្ទាប់ (Find Next)" if kh else "🔎 Find Next")
        self.btn_find_next.clicked.connect(self._on_find_next)

        self.btn_replace_one = QPushButton("✏️ កែ ១ កន្លែង (Replace)" if kh else "✏️ Replace")
        self.btn_replace_one.clicked.connect(self._on_replace_one)

        self.btn_replace_all = QPushButton("⚡ កែទាំងអស់ (Replace All)" if kh else "⚡ Replace All")
        self.btn_replace_all.setObjectName("BtnBlue")
        self.btn_replace_all.clicked.connect(self._on_replace_all)

        btn_close = QPushButton("បិទ" if kh else "Close")
        btn_close.clicked.connect(self.close)

        btn_row.addWidget(self.btn_find_next)
        btn_row.addWidget(self.btn_replace_one)
        btn_row.addWidget(self.btn_replace_all)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _target_key(self) -> str:
        idx = self.combo_target.currentIndex()
        if idx == 0:
            return "kh"
        elif idx == 1:
            return "zh"
        return "both"

    def _scan_matches(self):
        kh = self.lang == "kh"
        needle = self.txt_find.text()
        if not needle or not self.project_id:
            self._matches = []
            self._match_cursor = -1
            self.lbl_status.setText("រកឃើញ៖ 0 កន្លែង" if kh else "Matches found: 0")
            return

        segs = self.db.get_segments(self.project_id)
        target = self._target_key()
        case_sensitive = self.chk_case.isChecked()
        cmp_needle = needle if case_sensitive else needle.lower()

        matches = []
        total_occurrences = 0
        for row_idx, s in enumerate(segs):
            found_here = 0
            if target in ("kh", "both"):
                t_kh = s.get("kh_text") or ""
                h_kh = t_kh if case_sensitive else t_kh.lower()
                found_here += h_kh.count(cmp_needle)
            if target in ("zh", "both"):
                t_zh = s.get("zh_text") or ""
                h_zh = t_zh if case_sensitive else t_zh.lower()
                found_here += h_zh.count(cmp_needle)
            if found_here > 0:
                matches.append((row_idx, s["id"]))
                total_occurrences += found_here

        self._matches = matches
        if self._match_cursor >= len(self._matches):
            self._match_cursor = 0 if self._matches else -1

        self.lbl_status.setText(
            f"រកឃើញ៖ {total_occurrences} កន្លែង (ក្នុង {len(matches)} ជួរ)"
            if kh else f"Matches found: {total_occurrences} (in {len(matches)} rows)"
        )

    def _on_find_next(self):
        self._scan_matches()
        if not self._matches:
            return
        self._match_cursor = (self._match_cursor + 1) % len(self._matches)
        row_idx, _ = self._matches[self._match_cursor]
        if self.on_jump_row_cb:
            self.on_jump_row_cb(row_idx)

    def _on_replace_one(self):
        kh = self.lang == "kh"
        needle = self.txt_find.text()
        replacement = self.txt_replace.text()
        if not needle:
            return
        self._scan_matches()
        if not self._matches:
            return
        if self._match_cursor < 0:
            self._match_cursor = 0

        row_idx, seg_id = self._matches[self._match_cursor]
        updated = self.db.replace_text_in_segments(
            self.project_id,
            find_text=needle,
            replace_text=replacement,
            target=self._target_key(),
            case_sensitive=self.chk_case.isChecked(),
            only_seg_id=seg_id,
        )
        if updated > 0:
            if self.on_updated_cb:
                self.on_updated_cb(updated, single=True)
            self._scan_matches()
            if self._matches and self.on_jump_row_cb:
                next_row, _ = self._matches[self._match_cursor % len(self._matches)]
                self.on_jump_row_cb(next_row)

    def _on_replace_all(self):
        kh = self.lang == "kh"
        needle = self.txt_find.text()
        replacement = self.txt_replace.text()
        if not needle:
            return
        count = self.db.replace_text_in_segments(
            self.project_id,
            find_text=needle,
            replace_text=replacement,
            target=self._target_key(),
            case_sensitive=self.chk_case.isChecked(),
            only_seg_id=None,
        )
        self._scan_matches()
        if self.on_updated_cb:
            self.on_updated_cb(count, single=False)
        QMessageBox.information(
            self,
            "Find & Replace",
            f"បានកែពាក្យចំនួន {count} ជួររួចរាល់!" if kh else f"Replaced in {count} row(s)!",
        )
