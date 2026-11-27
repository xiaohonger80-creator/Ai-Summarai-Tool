import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QApplication, QTextEdit
)
from core.license_manager import (
    get_machine_id, verify_license, save_license_key,
    load_license_key, get_active_license_status
)


class LicenseActivationDialog(QDialog):
    """
    ផ្ទាំងធ្វើឱ្យសកម្មអាជ្ញាប័ណ្ណ (License Activation Dialog) សម្រាប់ការពារសុវត្ថិភាពកម្មវិធី
    """
    def __init__(self, parent=None, is_forced: bool = True):
        super().__init__(parent)
        self.is_forced = is_forced
        self.is_activated = False
        self.machine_id = get_machine_id()

        self.setWindowTitle("🛡️ ផ្ទៀងផ្ទាត់អាជ្ញាប័ណ្ណ (License Activation) — Ai Summarai")
        self.setFixedWidth(560)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QLabel {
                color: #E2E8F0;
            }
            QLineEdit, QTextEdit {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                selection-background-color: #059669;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #10B981;
            }
            QPushButton#BtnPrimary {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #059669);
                color: white;
                font-weight: 700;
                font-size: 13px;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
            }
            QPushButton#BtnPrimary:hover {
                background: #10B981;
            }
            QPushButton#BtnSecondary {
                background-color: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
            }
            QPushButton#BtnSecondary:hover {
                background-color: #334155;
                color: #F8FAFC;
            }
        """)

        self._build_ui()
        self._check_initial_state()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        # 1. Header Card
        header = QFrame()
        header.setStyleSheet("background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 10px; padding: 12px;")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 8)
        h_layout.setSpacing(4)

        lbl_title = QLabel("🛡️ Ai Summarai Studio — ប្រព័ន្ធផ្ទៀងផ្ទាត់អាជ្ញាប័ណ្ណ")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #10B981;")

        lbl_desc = QLabel(
            "កម្មវិធីនេះត្រូវបានការពារដោយប្រព័ន្ធ License សុវត្ថិភាព។ "
            "សូមចម្លង Machine ID ខាងក្រោមនេះ ផ្ញើទៅកាន់ Admin ដើម្បីទទួលបាន License Key បើកដំណើរការ។"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; line-height: 1.4;")

        h_layout.addWidget(lbl_title)
        h_layout.addWidget(lbl_desc)
        layout.addWidget(header)

        # 2. Machine ID Section
        lbl_mid_title = QLabel("🖥️ លេខសម្គាល់កុំព្យូទ័ររបស់អ្នក (Your Machine ID)៖")
        lbl_mid_title.setStyleSheet("font-weight: 700; color: #38BDF8; font-size: 12px;")
        layout.addWidget(lbl_mid_title)

        mid_box = QHBoxLayout()
        mid_box.setSpacing(8)

        self.txt_mid = QLineEdit(self.machine_id)
        self.txt_mid.setReadOnly(True)
        self.txt_mid.setStyleSheet(
            "background-color: #0B1120; color: #38BDF8; font-family: 'Consolas', 'Courier New', monospace; "
            "font-size: 15px; font-weight: 800; border: 1px solid #1E293B; letter-spacing: 1px;"
        )

        btn_copy_mid = QPushButton("📋 ចម្លង (Copy)")
        btn_copy_mid.setObjectName("BtnSecondary")
        btn_copy_mid.setFixedWidth(120)
        btn_copy_mid.clicked.connect(self._copy_machine_id)

        mid_box.addWidget(self.txt_mid, 1)
        mid_box.addWidget(btn_copy_mid)
        layout.addLayout(mid_box)

        # 3. License Key Input Section
        lbl_key_title = QLabel("🔑 បញ្ចូល License Key ដែលទទួលបានពី Admin៖")
        lbl_key_title.setStyleSheet("font-weight: 700; color: #F8FAFC; font-size: 12px; margin-top: 6px;")
        layout.addWidget(lbl_key_title)

        self.txt_key = QTextEdit()
        self.txt_key.setPlaceholderText("ឧ. ASKEY-eyJkIjozMCwibSI6IkFTL... (Paste License Key នៅទីនេះ)")
        self.txt_key.setFixedHeight(85)
        self.txt_key.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; line-height: 1.3;"
        )
        layout.addWidget(self.txt_key)

        # 4. Feedback & Status Label
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: 700;")
        layout.addWidget(self.lbl_status)

        # 5. Buttons Section
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_exit = QPushButton("🚪 ចាកចេញ (Exit)" if self.is_forced else "បិទ (Close)")
        self.btn_exit.setObjectName("BtnSecondary")
        self.btn_exit.clicked.connect(self.reject)

        self.btn_paste = QPushButton("📋 បិទភ្ជាប់ (Paste)")
        self.btn_paste.setObjectName("BtnSecondary")
        self.btn_paste.clicked.connect(self._paste_clipboard)

        self.btn_activate = QPushButton("⚡ ធ្វើឱ្យសកម្មឥឡូវនេះ (Activate)")
        self.btn_activate.setObjectName("BtnPrimary")
        self.btn_activate.clicked.connect(self._do_activate)

        btn_row.addWidget(self.btn_exit)
        btn_row.addWidget(self.btn_paste)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_activate)
        layout.addLayout(btn_row)

    def _copy_machine_id(self):
        QApplication.clipboard().setText(self.machine_id)
        self.lbl_status.setText("✅ បានចម្លង Machine ID ទៅកាន់ Clipboard រួចរាល់! សូមផ្ញើទៅ Admin។")
        self.lbl_status.setStyleSheet("color: #10B981; font-weight: 700;")

    def _paste_clipboard(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.txt_key.setPlainText(text)
            self._do_activate()

    def _check_initial_state(self):
        saved = load_license_key()
        if saved:
            self.txt_key.setPlainText(saved)
            ok, msg, days, info = verify_license(saved)
            if ok:
                client = info.get("u", "")
                name_str = f"សម្រាប់៖ {client} | " if client else ""
                self.lbl_status.setText(f"✅ {msg} ({name_str}សុពលភាព៖ {days} ថ្ងៃ)")
                self.lbl_status.setStyleSheet("color: #10B981; font-weight: 700;")
                self.is_activated = True
            else:
                self.lbl_status.setText(f"⚠️ {msg}")
                self.lbl_status.setStyleSheet("color: #EF4444; font-weight: 700;")

    def _do_activate(self):
        key = self.txt_key.toPlainText().strip()
        if not key:
            self.lbl_status.setText("⚠️ សូមបញ្ចូល License Key ជាមុនសិន!")
            self.lbl_status.setStyleSheet("color: #F59E0B; font-weight: 700;")
            return

        ok, msg, days, info = verify_license(key)
        if ok:
            save_license_key(key)
            self.is_activated = True
            client = info.get("u", "")
            name_str = f" ({client})" if client else ""
            self.lbl_status.setText(f"🎉 ធ្វើឱ្យសកម្មជោគជ័យ{name_str}! សុពលភាពនៅសល់៖ {days} ថ្ងៃ។")
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: 700; font-size: 13px;")
            QMessageBox.information(
                self,
                "License Activated",
                f"🎉 អបអរសាទរ! កម្មវិធី Ai Summarai Studio ត្រូវបានធ្វើឱ្យសកម្មជោគជ័យ!\n\n"
                f"• កុំព្យូទ័រ៖ {self.machine_id}\n"
                f"• សុពលភាព៖ នៅសល់ {days} ថ្ងៃ\n\n"
                f"សូមអរគុណសម្រាប់ការប្រើប្រាស់!"
            )
            self.accept()
        else:
            self.lbl_status.setText(f"❌ {msg}")
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: 700;")


def enforce_license_or_exit(parent=None) -> bool:
    """
    Checks active license. If missing or expired, opens activation dialog.
    If user fails/exits, returns False.
    """
    ok, msg, days, info = get_active_license_status()
    if ok:
        return True

    # Show Activation Dialog
    dlg = LicenseActivationDialog(parent=parent, is_forced=True)
    res = dlg.exec()
    if res == QDialog.Accepted and dlg.is_activated:
        return True
    return False
