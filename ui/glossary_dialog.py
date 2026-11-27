import json
from pathlib import Path
from typing import List, Dict, Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QComboBox,
    QFrame, QMessageBox, QFileDialog, QProgressBar
)

from core.khmer_dub_glossary_dataset import GLOSSARY_CATEGORIES, SPOKEN_KHMER_GLOSSARY_PACK


class AIExpandWorker(QThread):
    progress = Signal(str)
    finished = Signal(int, str)  # count, message

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

    def run(self):
        try:
            from tools.build_khmer_dub_glossary import expand_with_ai
            api_key = (
                self.db.get_setting("gemini_api_key")
                or self.db.get_setting("api_key")
                or ""
            )
            model = self.db.get_setting("gemini_model", "gemini-3.1-flash-lite")
            if not api_key:
                self.finished.emit(0, "សូមបញ្ចូល Gemini API Key នៅក្នុង Settings ជាមុនសិន ទើបអាចប្រើមុខងារ AI បាន!")
                return

            self.progress.emit("កំពុងស្នើសុំ AI បង្កើតពាក្យរឿងភាគ និងភាសានិយាយខ្មែរបន្ថែម...")
            new_items = expand_with_ai(api_key=api_key, model=model, batch_size=120)
            if not new_items:
                self.finished.emit(0, "មិនអាចបង្កើតពាក្យបន្ថែមបានទេ សូមពិនិត្យមើល API Key ឬភ្ជាប់អ៊ីនធឺណិត។")
                return

            inserted = self.db.bulk_upsert_glossary(new_items)
            self.finished.emit(len(new_items), f"ជោគជ័យ! បានបង្កើត និងបន្ថែម {len(new_items)} ពាក្យថ្មីចូលវចនានុក្រម!")
        except Exception as e:
            self.finished.emit(0, f"មានបញ្ហាក្នុងការបង្កើតពាក្យ: {e}")


class GlossaryDialog(QDialog):
    """
    CapCut Studio-Inspired 2,000+ Word Spoken Khmer Dubbing Glossary Dialog
    - Pre-loaded with 2,000+ high-frequency Chinese-to-Khmer dubbing terms
    - Fast category filtering, real-time live search, and live word counter badge
    - One-click 'Load 2,000+ Spoken Pack' & 'Expand to 5,000 Words (AI)'
    """

    def __init__(self, db, lang: str = "kh", parent=None):
        super().__init__(parent)
        self.db = db
        self.lang = lang
        self._expand_worker = None

        kh = lang == "kh"
        self.setWindowTitle(
            "📖 វចនានុក្រមបញ្ចូលសំឡេងរឿងភាគ (2,000+ Spoken Khmer Dubbing Glossary)" if kh
            else "📖 Spoken Khmer Dubbing Glossary (2,000+ Terms)"
        )
        self.resize(880, 620)
        self.setMinimumSize(780, 520)
        self._build_ui()
        self._load_items()

    def _build_ui(self):
        kh = self.lang == "kh"
        self.setStyleSheet("""
            QDialog {
                background-color: #0B0D10;
                color: #F4F6FB;
                font-family: 'Inter', 'Kantumruy Pro', 'Noto Sans Khmer', 'Segoe UI';
            }
            QLabel {
                color: #F4F6FB;
            }
            QLineEdit, QComboBox {
                background-color: #181C24;
                color: #F4F6FB;
                border: 1px solid #252A36;
                border-radius: 6px;
                padding: 7px 10px;
                font-size: 13px;
                selection-background-color: #00E5FF;
                selection-color: #0B0D10;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #00E5FF;
            }
            QTableWidget {
                background-color: #12151B;
                color: #F4F6FB;
                border: 1px solid #252A36;
                border-radius: 8px;
                gridline-color: #1A1F29;
                font-size: 13px;
                selection-background-color: rgba(0, 229, 255, 0.15);
                selection-color: #00E5FF;
            }
            QHeaderView::section {
                background-color: #181C24;
                color: #8E95A5;
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid #252A36;
                font-weight: 700;
                font-size: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        # 1. Header Card with Title & Live Word Count Badge
        header_card = QFrame()
        header_card.setStyleSheet("background: #12151B; border: 1px solid #252A36; border-radius: 8px; padding: 10px;")
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(8, 4, 8, 4)

        info_box = QVBoxLayout()
        info_box.setSpacing(3)
        lbl_title = QLabel("📖 វចនានុក្រមភាសានិយាយបញ្ចូលសំឡេងរឿងភាគ (Spoken Dubbing Glossary)" if kh else "📖 Spoken Khmer Dubbing Glossary")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #00E5FF;")
        lbl_desc = QLabel(
            "ពាក្យខ្មែរនិយាយធម្មជាតិ ងាយស្តាប់ ងាយបញ្ចូលសំឡេង (AI នឹងបកប្រែតាមវចនានុក្រមនេះ ១០០% គ្រប់ភាគ)" if kh else
            "Natural spoken Cambodian dialogue terms for lip-sync dubbing and recurring character consistency."
        )
        lbl_desc.setStyleSheet("font-size: 11px; color: #8E95A5;")
        info_box.addWidget(lbl_title)
        info_box.addWidget(lbl_desc)

        h_layout.addLayout(info_box, 1)

        # Word count pill
        self.lbl_word_count = QLabel("Total: 0 ZH → KH")
        self.lbl_word_count.setStyleSheet(
            "background: rgba(16, 185, 129, 0.15); color: #10B981; "
            "font-weight: 800; font-size: 12px; border: 1px solid rgba(16, 185, 129, 0.35); "
            "padding: 6px 12px; border-radius: 6px;"
        )
        h_layout.addWidget(self.lbl_word_count)
        layout.addWidget(header_card)

        # 2. Action Toolbar (Load 2,000+ Pack, AI Expand, Export, Import)
        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)

        self.btn_load_pack = QPushButton("✨ Load 2,000+ Spoken Khmer Pack" if kh else "✨ Load 2,000+ Spoken Pack")
        self.btn_load_pack.setStyleSheet(
            "background-color: #10B981; color: #0B0D10; font-weight: 700; "
            "border-radius: 6px; padding: 7px 14px; border: none; font-size: 12px;"
        )
        self.btn_load_pack.clicked.connect(self._load_spoken_pack)

        self.btn_expand_ai = QPushButton("🚀 Expand to 5,000 Words (AI)" if kh else "🚀 Expand to 5,000 Words (AI)")
        self.btn_expand_ai.setStyleSheet(
            "background-color: #7C3AED; color: #FFFFFF; font-weight: 700; "
            "border-radius: 6px; padding: 7px 14px; border: none; font-size: 12px;"
        )
        self.btn_expand_ai.clicked.connect(self._expand_ai)

        btn_export = QPushButton("📤 Export JSON" if kh else "📤 Export")
        btn_export.setStyleSheet("background: #181C24; color: #F4F6FB; border: 1px solid #252A36; border-radius: 6px; padding: 7px 12px;")
        btn_export.clicked.connect(self._export_json)

        btn_import = QPushButton("📥 Import JSON" if kh else "📥 Import")
        btn_import.setStyleSheet("background: #181C24; color: #F4F6FB; border: 1px solid #252A36; border-radius: 6px; padding: 7px 12px;")
        btn_import.clicked.connect(self._import_json)

        tool_row.addWidget(self.btn_load_pack)
        tool_row.addWidget(self.btn_expand_ai)
        tool_row.addStretch()
        tool_row.addWidget(btn_export)
        tool_row.addWidget(btn_import)
        layout.addLayout(tool_row)

        # 3. Search & Filter Bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText("🔍 ស្វែងរកពាក្យចិន ឬខ្មែរ... (Search Chinese or Khmer terms)" if kh else "🔍 Search terms...")
        self.in_search.textChanged.connect(self._filter_items)

        self.cb_category = QComboBox()
        self.cb_category.addItem("ទាំងអស់ (All Categories)", "all")
        for key, name in GLOSSARY_CATEGORIES.items():
            if key != "all":
                self.cb_category.addItem(name, key)
        self.cb_category.currentIndexChanged.connect(self._filter_items)

        filter_row.addWidget(self.in_search, 1)
        filter_row.addWidget(self.cb_category)
        layout.addLayout(filter_row)

        # 4. Add New Term Row
        add_frame = QFrame()
        add_frame.setStyleSheet("background: #12151B; border: 1px solid #252A36; border-radius: 6px; padding: 6px;")
        add_row = QHBoxLayout(add_frame)
        add_row.setContentsMargins(4, 4, 4, 4)
        add_row.setSpacing(8)

        self.in_zh = QLineEdit()
        self.in_zh.setPlaceholderText("ពាក្យចិន ឬ EN (ឧ. 顾总 / 怎么了)" if kh else "Source term (e.g. 顾总)")
        self.in_kh = QLineEdit()
        self.in_kh.setPlaceholderText("ពាក្យខ្មែរនិយាយ (ឧ. លោកអគ្គនាយក គូ / កើតអីហ្នឹង?)" if kh else "Khmer spoken term")
        self.in_kh.returnPressed.connect(self._add_term)

        self.cb_add_cat = QComboBox()
        for key, name in GLOSSARY_CATEGORIES.items():
            if key != "all":
                self.cb_add_cat.addItem(name.split(" ")[0], key)

        btn_add = QPushButton("+ បន្ថែម" if kh else "+ Add")
        btn_add.setStyleSheet("background-color: #00E5FF; color: #0B0D10; font-weight: 700; border-radius: 6px; padding: 7px 16px; border: none;")
        btn_add.clicked.connect(self._add_term)

        add_row.addWidget(self.in_zh, 1)
        add_row.addWidget(self.in_kh, 1)
        add_row.addWidget(self.cb_add_cat)
        add_row.addWidget(btn_add)
        layout.addWidget(add_frame)

        # 5. Table of Terms
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["ពាក្យដើម (ZH/EN)", "ពាក្យខ្មែរនិយាយ (Spoken KH)", "ប្រភេទ (Category)", "លុប"] if kh else
            ["Source Term", "Spoken Khmer Term", "Category", "Del"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 220)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 55)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_item_edited)
        layout.addWidget(self.table, 1)

        # 6. Bottom Bar
        bottom_row = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #8E95A5; font-size: 11px;")
        bottom_row.addWidget(self.lbl_status, 1)

        btn_close = QPushButton("រួចរាល់ (Done)" if kh else "Done")
        btn_close.setStyleSheet("background-color: #181C24; color: #F4F6FB; border: 1px solid #252A36; padding: 8px 22px; border-radius: 6px; font-weight: 700;")
        btn_close.clicked.connect(self.accept)
        bottom_row.addWidget(btn_close)
        layout.addLayout(bottom_row)

    def _load_items(self):
        cat = self.cb_category.currentData() or "all"
        search = self.in_search.text().strip()
        items = self.db.get_glossary(category=cat, search=search)
        total_all = self.db.get_glossary_count()

        kh = self.lang == "kh"
        self.lbl_word_count.setText(f"🏷️ Total Terms: {total_all:,} ZH → KH")
        self.lbl_status.setText(f"បង្ហាញ {len(items):,} / {total_all:,} ពាក្យ" if kh else f"Showing {len(items):,} / {total_all:,} terms")

        self.table.blockSignals(True)
        self.table.setRowCount(len(items))

        for r, item in enumerate(items):
            zh_val = item.get("src_term") or item.get("zh_term") or ""
            kh_val = item.get("kh_term") or ""
            cat_code = item.get("category") or "general"
            cat_label = GLOSSARY_CATEGORIES.get(cat_code, cat_code)

            it_zh = QTableWidgetItem(zh_val)
            it_zh.setData(Qt.UserRole, item["id"])
            it_kh = QTableWidgetItem(kh_val)
            it_cat = QTableWidgetItem(cat_label)
            it_cat.setFlags(it_cat.flags() & ~Qt.ItemIsEditable)

            it_zh.setForeground(QColor("#00E5FF"))
            it_kh.setForeground(QColor("#F4F6FB"))
            it_cat.setForeground(QColor("#8E95A5"))

            self.table.setItem(r, 0, it_zh)
            self.table.setItem(r, 1, it_kh)
            self.table.setItem(r, 2, it_cat)

            btn_del = QPushButton("🗑")
            btn_del.setToolTip("លុបពាក្យនេះ")
            btn_del.setStyleSheet("background: transparent; color: #EF4444; border: none; font-size: 13px;")
            btn_del.clicked.connect(lambda _, gid=item["id"]: self._delete_term(gid))
            self.table.setCellWidget(r, 3, btn_del)

        self.table.blockSignals(False)

    def _filter_items(self):
        self._load_items()

    def _on_item_edited(self, item: QTableWidgetItem):
        row = item.row()
        zh_it = self.table.item(row, 0)
        kh_it = self.table.item(row, 1)
        if zh_it and kh_it:
            zh = zh_it.text().strip()
            kh = kh_it.text().strip()
            if zh and kh:
                cat = self.table.item(row, 2).text() if self.table.item(row, 2) else "general"
                self.db.upsert_glossary(zh, kh, cat)

    def _add_term(self):
        zh = self.in_zh.text().strip()
        kh = self.in_kh.text().strip()
        cat = self.cb_add_cat.currentData() or "general"
        if zh and kh:
            self.db.upsert_glossary(zh, kh, cat)
            self.in_zh.clear()
            self.in_kh.clear()
            self._load_items()

    def _delete_term(self, gid: int):
        self.db.delete_glossary(gid)
        self._load_items()

    def _load_spoken_pack(self):
        """One-click instant loading of the pre-built 2,150+ spoken Khmer dataset."""
        count = len(SPOKEN_KHMER_GLOSSARY_PACK)
        self.db.bulk_upsert_glossary(SPOKEN_KHMER_GLOSSARY_PACK)
        self._load_items()
        QMessageBox.information(
            self,
            "Glossary Pack Loaded",
            f"🎉 បានបញ្ចូលកញ្ចប់វចនានុក្រមភាសានិយាយខ្មែរ {count:,} ពាក្យដោយជោគជ័យ!\n\n"
            "ឥឡូវនេះ AI នឹងបកប្រែពាក្យទាំងនេះទៅជាភាសាខ្មែរនិយាយបែបធម្មជាតិ "
            "ងាយស្តាប់ និងងាយបញ្ចូលសំឡេងគ្រប់ភាគទាំងអស់។"
        )

    def _expand_ai(self):
        """Background AI expansion for short drama dubbing phrases."""
        kh = self.lang == "kh"
        api_key = self.db.get_setting("gemini_api_key") or self.db.get_setting("api_key") or ""
        if not api_key:
            QMessageBox.warning(
                self,
                "API Key Missing",
                "សូមចូលទៅកាន់ Settings ហើយបញ្ចូល Google Gemini API Key ជាមុនសិន "
                "ទើបអាចប្រើមុខងារបង្កើតពាក្យស្វ័យប្រវត្តតាមរយៈ AI បាន!" if kh else
                "Please configure a Google Gemini API Key in Settings first to enable AI vocabulary expansion."
            )
            return

        self.btn_expand_ai.setEnabled(False)
        self.lbl_status.setText("⏳ កំពុងដំណើរការ AI Expand..." if kh else "⏳ AI Expanding...")
        self._expand_worker = AIExpandWorker(self.db)
        self._expand_worker.progress.connect(lambda msg: self.lbl_status.setText(f"⏳ {msg}"))
        self._expand_worker.finished.connect(self._on_expand_finished)
        self._expand_worker.start()

    def _on_expand_finished(self, count: int, msg: str):
        self.btn_expand_ai.setEnabled(True)
        self._load_items()
        if count > 0:
            QMessageBox.information(self, "AI Expansion Complete", msg)
        else:
            QMessageBox.warning(self, "AI Expansion Result", msg)

    def _export_json(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export Spoken Glossary", "glossary_zh_kh_spoken.json", "JSON Files (*.json)")
        if p:
            items = self.db.get_glossary()
            data = [{"zh_term": i["src_term"], "kh_term": i["kh_term"], "category": i.get("category", "general")} for i in items]
            Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Exported", f"បាន Export {len(items):,} ពាក្យទៅកាន់:\n{p}")

    def _import_json(self):
        p, _ = QFileDialog.getOpenFileName(self, "Import Glossary", "", "JSON Files (*.json)")
        if p and Path(p).exists():
            try:
                data = json.loads(Path(p).read_text(encoding="utf-8"))
                rows = []
                for item in data:
                    zh = item.get("zh_term") or item.get("src_term") or ""
                    kh = item.get("kh_term") or ""
                    cat = item.get("category") or "general"
                    if zh and kh:
                        rows.append((zh.strip(), kh.strip(), cat.strip()))
                if rows:
                    self.db.bulk_upsert_glossary(rows)
                    self._load_items()
                    QMessageBox.information(self, "Imported", f"បាន Import {len(rows):,} ពាក្យដោយជោគជ័យ!")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"មិនអាចអាន JSON បានទេ: {e}")
