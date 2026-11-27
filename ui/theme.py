"""
Ai Summarai Studio — Modern CapCut-Inspired Visual Design System
================================================================
Theme Tokens & QSS Engine supporting:
- Obsidian Neon (Primary Default Studio Theme)
- Midnight Lime (Cyberpunk Dark Variant)
- Studio Daylight (Clean Editorial Light Theme)
"""

THEMES = {
    "obsidian": {
        "name_en": "Obsidian Neon (Studio)",
        "name_kh": "Obsidian Neon (CapCut Pro)",
        "bg_canvas": "#0B0D10",
        "bg_surface": "#12151B",
        "bg_elevated": "#181C24",
        "bg_hover": "#202530",
        "border_subtle": "#252A36",
        "border_focus": "#343B4C",
        "text_primary": "#F4F6FB",
        "text_secondary": "#8E95A5",
        "accent_primary": "#00E5FF",      # Electric Cyan
        "accent_primary_hover": "#33EBFF",
        "accent_ai": "#7C3AED",           # Cyber Violet
        "accent_ai_hover": "#8B5CF6",
        "accent_success": "#10B981",      # Emerald Green
        "accent_success_hover": "#34D399",
        "accent_warning": "#F59E0B",      # Amber
        "accent_danger": "#EF4444",       # Crimson Rose
        "selection": "rgba(0, 229, 255, 0.15)",
        "glass_btn": "#181C24",
        "glass_btn_hover": "#222733",
    },
    "midnight": {
        "name_en": "Midnight Lime",
        "name_kh": "Midnight Lime (បៃតងខ្ចី)",
        "bg_canvas": "#0D1117",
        "bg_surface": "#161B22",
        "bg_elevated": "#21262D",
        "bg_hover": "#30363D",
        "border_subtle": "#30363D",
        "border_focus": "#8B949E",
        "text_primary": "#F0F6FC",
        "text_secondary": "#8B949E",
        "accent_primary": "#A3E635",      # Cyber Lime
        "accent_primary_hover": "#BEF264",
        "accent_ai": "#8B5CF6",           # Violet
        "accent_ai_hover": "#A78BFA",
        "accent_success": "#10B981",      # Emerald
        "accent_success_hover": "#34D399",
        "accent_warning": "#F59E0B",
        "accent_danger": "#F43F5E",
        "selection": "rgba(163, 230, 53, 0.15)",
        "glass_btn": "#21262D",
        "glass_btn_hover": "#30363D",
    },
    "daylight": {
        "name_en": "Studio Daylight",
        "name_kh": "Studio Daylight (ពន្លឺថ្ងៃ)",
        "bg_canvas": "#F1F5F9",
        "bg_surface": "#FFFFFF",
        "bg_elevated": "#F8FAFC",
        "bg_hover": "#E2E8F0",
        "border_subtle": "#CBD5E1",
        "border_focus": "#64748B",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "accent_primary": "#0284C7",      # Sky Blue
        "accent_primary_hover": "#0369A1",
        "accent_ai": "#7C3AED",           # Violet
        "accent_ai_hover": "#6D28D9",
        "accent_success": "#059669",      # Green
        "accent_success_hover": "#047857",
        "accent_warning": "#D97706",
        "accent_danger": "#E11D48",
        "selection": "rgba(2, 132, 199, 0.12)",
        "glass_btn": "#F1F5F9",
        "glass_btn_hover": "#E2E8F0",
    },
}

# Alias for backwards compatibility with existing user configs
THEMES["capcut"] = THEMES["obsidian"]


def apply_app_palette(app, theme_key: str = "obsidian"):
    """Applies matching QPalette so Qt 6 popup QListViews (QComboBox) NEVER render white-on-white on Windows."""
    if app is None:
        return
    from PySide6.QtGui import QPalette, QColor
    t = THEMES.get(theme_key, THEMES["obsidian"])
    is_light = theme_key == "daylight"
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["bg_canvas"]))
    pal.setColor(QPalette.WindowText, QColor(t["text_primary"]))
    pal.setColor(QPalette.Base, QColor(t["bg_surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["bg_elevated"]))
    pal.setColor(QPalette.ToolTipBase, QColor(t["bg_surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text_primary"]))
    pal.setColor(QPalette.Text, QColor(t["text_primary"]))
    pal.setColor(QPalette.Button, QColor(t["bg_elevated"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text_primary"]))
    pal.setColor(QPalette.BrightText, QColor("#000000" if is_light else "#FFFFFF"))
    pal.setColor(QPalette.Highlight, QColor(t["accent_primary"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF" if is_light else "#0B0D10"))
    pal.setColor(QPalette.PlaceholderText, QColor(t["text_secondary"]))
    app.setPalette(pal)


def build_stylesheet(theme_key: str = "obsidian") -> str:
    t = THEMES.get(theme_key, THEMES["obsidian"])
    is_light = theme_key == "daylight"

    return f"""
    /* =========================================================================
       1. GLOBAL APPLICATION CANVAS & TYPOGRAPHY
       ========================================================================= */
    QMainWindow, QDialog {{
        background-color: {t['bg_canvas']};
        color: {t['text_primary']};
        font-family: "Inter", "Kantumruy Pro", "Noto Sans Khmer", "Khmer OS Battambang", "Segoe UI", sans-serif;
        font-size: 12.5px;
        font-weight: 500;
    }}

    QWidget {{
        color: {t['text_primary']};
        font-family: "Inter", "Kantumruy Pro", "Noto Sans Khmer", "Khmer OS Battambang", "Segoe UI", sans-serif;
        outline: none;
    }}

    QLabel {{
        background-color: transparent;
        color: {t['text_primary']};
    }}

    /* =========================================================================
       2. TOP NAVIGATION BAR & SURFACE PANELS
       ========================================================================= */
    QFrame#TopBar {{
        background-color: {t['bg_surface']};
        border: 1px solid {t['border_subtle']};
        border-radius: 8px;
    }}

    QFrame#StepBar {{
        background-color: {t['bg_surface']};
        border: 1px solid {t['border_subtle']};
        border-radius: 8px;
    }}

    QLabel#AppTitle {{
        font-size: 15px;
        font-weight: 800;
        letter-spacing: 0.5px;
        color: {t['accent_primary']};
    }}

    QLabel#SubTitle {{
        font-size: 11.5px;
        font-weight: 600;
        color: {t['text_secondary']};
    }}

    QLabel#FilePill {{
        background-color: {t['bg_elevated']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        padding: 4px 10px;
        font-family: "JetBrains Mono", "Consolas", monospace;
        font-size: 11.5px;
        font-weight: 600;
    }}

    QLabel#DropTitle {{
        font-size: 17px;
        font-weight: 800;
        color: {t['text_primary']};
    }}

    QLabel#DropHint, QLabel#StatusLbl {{
        font-size: 12px;
        font-weight: 500;
        color: {t['text_secondary']};
    }}

    QLabel#BgmLbl {{
        color: {t['text_secondary']};
        font-size: 11.5px;
        font-weight: 600;
    }}

    QLabel#BgmValLbl {{
        color: {t['accent_primary']};
        font-family: "JetBrains Mono", "Consolas", monospace;
        font-weight: 700;
        font-size: 11.5px;
    }}

    /* =========================================================================
       3. BUTTON SYSTEM & GRADIENT ACCENTS (Interactive Tactile Scale + Pointer)
       ========================================================================= */
    QPushButton, QToolButton {{
        cursor: pointer;
        background-color: {t['bg_elevated']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 12px;
        font-weight: 600;
    }}

    QPushButton:hover, QToolButton:hover {{
        background-color: {t['bg_hover']};
        border-color: {t['accent_primary']};
        color: #FFFFFF;
        padding: 4px 13px 6px 11px;
    }}

    QPushButton:pressed, QToolButton:pressed {{
        background-color: {t['border_subtle']};
        padding: 6px 11px 4px 13px;
    }}

    QPushButton:disabled, QToolButton:disabled {{
        background-color: {t['bg_surface']};
        color: {t['text_secondary']};
        border-color: {t['border_subtle']};
        opacity: 0.5;
        padding: 5px 12px;
    }}

    /* Consolidated Tools Menu Button */
    QPushButton#BtnTools {{
        cursor: pointer;
        background-color: {t['glass_btn']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        font-weight: 700;
        padding: 5px 12px;
    }}
    QPushButton#BtnTools:hover {{
        background-color: {t['bg_hover']};
        border-color: {t['accent_primary']};
        color: {t['accent_primary']};
        padding: 4px 13px 6px 11px;
    }}
    QPushButton#BtnTools:pressed {{
        padding: 6px 11px 4px 13px;
    }}

    /* Primary Export CTA Button (Always Emerald Green, prominent & unclipped) */
    QPushButton#BtnGreen {{
        cursor: pointer;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #059669);
        color: #FFFFFF;
        border: 1px solid #34D399;
        border-radius: 6px;
        font-weight: 800;
        font-size: 12.5px;
        padding: 5px 16px;
    }}
    QPushButton#BtnGreen:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34D399, stop:1 #10B981);
        border: 1.5px solid #6EE7B7;
        color: #FFFFFF;
        padding: 4px 17px 6px 15px;
    }}
    QPushButton#BtnGreen:pressed {{
        padding: 6px 15px 4px 17px;
    }}
    QPushButton#BtnGreen:disabled {{
        background: {t['bg_elevated']};
        color: {t['text_secondary']};
        border: 1px solid {t['border_subtle']};
        padding: 5px 16px;
    }}

    /* Step 1: Open Video (Electric Sky/Blue) */
    QPushButton#BtnBlue {{
        cursor: pointer;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0284C7, stop:1 #0369A1);
        color: #FFFFFF;
        border: 1px solid #38BDF8;
        border-radius: 6px;
        font-weight: 700;
        padding: 5px 12px;
    }}
    QPushButton#BtnBlue:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #38BDF8, stop:1 #0284C7);
        border: 1.5px solid #7DD3FC;
        padding: 4px 13px 6px 11px;
    }}
    QPushButton#BtnBlue:pressed {{
        padding: 6px 11px 4px 13px;
    }}

    /* Step 2: Scan Subtitles (Cyan) */
    QPushButton#BtnCyan {{
        cursor: pointer;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0891B2, stop:1 #0E7490);
        color: #FFFFFF;
        border: 1px solid #22D3EE;
        border-radius: 6px;
        font-weight: 700;
        padding: 5px 12px;
    }}
    QPushButton#BtnCyan:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #22D3EE, stop:1 #0891B2);
        border: 1.5px solid #67E8F9;
        padding: 4px 13px 6px 11px;
    }}
    QPushButton#BtnCyan:pressed {{
        padding: 6px 11px 4px 13px;
    }}

    /* Step 3: AI Translate (Cyber Violet) */
    QPushButton#BtnViolet {{
        cursor: pointer;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7C3AED, stop:1 #6D28D9);
        color: #FFFFFF;
        border: 1px solid #A78BFA;
        border-radius: 6px;
        font-weight: 700;
        padding: 5px 12px;
    }}
    QPushButton#BtnViolet:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #A78BFA, stop:1 #7C3AED);
        border: 1.5px solid #C4B5FD;
        padding: 4px 13px 6px 11px;
    }}
    QPushButton#BtnViolet:pressed {{
        padding: 6px 11px 4px 13px;
    }}

    /* Step 4: AI Dubbing (Warm Amber / Gold) */
    QPushButton#BtnAmber {{
        cursor: pointer;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #D97706, stop:1 #B45309);
        color: #FFFFFF;
        border: 1px solid #FBBF24;
        border-radius: 6px;
        font-weight: 700;
        padding: 5px 12px;
    }}
    QPushButton#BtnAmber:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FBBF24, stop:1 #D97706);
        border: 1.5px solid #FDE68A;
        padding: 4px 13px 6px 11px;
    }}
    QPushButton#BtnAmber:pressed {{
        padding: 6px 11px 4px 13px;
    }}

    /* Secondary Soft Purple & Rose buttons */
    QPushButton#BtnPurple {{
        cursor: pointer;
        background-color: {t['bg_elevated']};
        color: #C4B5FD;
        border: 1px solid #4C1D95;
        border-radius: 6px;
        font-weight: 700;
        padding: 5px 12px;
    }}
    QPushButton#BtnPurple:hover {{
        background-color: #312E81;
        border-color: #8B5CF6;
        color: #FFFFFF;
        padding: 4px 13px 6px 11px;
    }}
    QPushButton#BtnPurple:pressed {{
        padding: 6px 11px 4px 13px;
    }}

    QPushButton#BtnRose {{
        cursor: pointer;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #E11D48, stop:1 #BE123C);
        color: #FFFFFF;
        border: 1px solid #FB7185;
        border-radius: 6px;
        font-weight: 700;
        padding: 5px 12px;
    }}
    QPushButton#BtnRose:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FB7185, stop:1 #E11D48);
        border: 1.5px solid #FDA4AF;
        padding: 4px 13px 6px 11px;
    }}
    QPushButton#BtnRose:pressed {{
        padding: 6px 11px 4px 13px;
    }}

    QPushButton#BtnGlass {{
        cursor: pointer;
        background-color: {t['glass_btn']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        font-weight: 600;
        padding: 4px 8px;
    }}
    QPushButton#BtnGlass:hover {{
        background-color: {t['glass_btn_hover']};
        border-color: {t['accent_primary']};
        color: #FFFFFF;
        padding: 3px 9px 5px 7px;
    }}
    QPushButton#BtnGlass:pressed {{
        padding: 5px 7px 3px 9px;
    }}
    QPushButton#BtnGlass::menu-indicator {{
        image: none;
        width: 0px;
    }}

    /* Row Play Button (26px Circular) */
    QPushButton#RowPlayBtn {{
        cursor: pointer;
        background-color: {t['bg_elevated']};
        color: {t['accent_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 13px;
        padding: 0px;
        font-weight: 800;
        font-size: 11px;
    }}
    QPushButton#RowPlayBtn:hover {{
        background-color: {t['accent_primary']};
        color: #0B0D10;
        border-color: {t['accent_primary']};
    }}

    /* Player Transport Controls */
    QPushButton#TransportBtn {{
        cursor: pointer;
        background-color: {t['bg_elevated']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        padding: 4px 8px;
        font-family: "JetBrains Mono", monospace;
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#TransportBtn:hover {{
        background-color: {t['bg_hover']};
        border-color: {t['accent_primary']};
        color: {t['accent_primary']};
        padding: 3px 9px 5px 7px;
    }}
    QPushButton#TransportBtn:pressed {{
        padding: 5px 7px 3px 9px;
    }}

    /* Circular Play/Pause button in center transport */
    QPushButton#PlayCircleBtn {{
        cursor: pointer;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t['accent_primary']}, stop:1 #00B8D4);
        color: #0B0D10;
        border: none;
        border-radius: 18px;
        font-size: 14px;
        font-weight: 800;
    }}
    QPushButton#PlayCircleBtn:hover {{
        background: {t['accent_primary_hover']};
    }}

    /* =========================================================================
       4. INPUTS, COMBOBOXES & FORM CONTROLS
       ========================================================================= */
    QLineEdit, QComboBox, QSpinBox {{
        background-color: {t['bg_elevated']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
        selection-background-color: {t['accent_primary']};
        selection-color: #0B0D10;
    }}

    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {t['accent_primary']};
    }}

    QCheckBox {{
        color: {t['text_primary']};
        font-size: 12px;
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {t['border_subtle']};
        border-radius: 4px;
        background-color: {t['bg_elevated']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {t['accent_primary']};
        border-color: {t['accent_primary']};
    }}

    QComboBoxPrivateContainer {{
        background-color: {t['bg_surface']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
    }}

    QComboBox QAbstractItemView, QComboBox QListView {{
        background-color: {t['bg_surface']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        padding: 4px;
        selection-background-color: {t['accent_primary']};
        selection-color: #0B0D10;
        outline: none;
    }}

    QComboBox QAbstractItemView::item, QComboBox QListView::item {{
        background-color: {t['bg_surface']};
        color: {t['text_primary']};
        padding: 6px 10px;
        min-height: 22px;
        border-radius: 4px;
    }}

    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected,
    QComboBox QListView::item:hover,
    QComboBox QListView::item:selected {{
        background-color: {t['accent_primary']};
        color: #0B0D10;
        font-weight: 700;
    }}

    /* =========================================================================
       5. SCRIPT & TRANSCRIPT TABLE (Card Rows & Generous Khmer Line-Height)
       ========================================================================= */
    QTableWidget {{
        background-color: {t['bg_surface']};
        alternate-background-color: {t['bg_elevated']};
        color: {t['text_primary']};
        gridline-color: transparent;
        border: 1px solid {t['border_subtle']};
        border-radius: 8px;
        selection-background-color: {t['selection']};
        selection-color: {t['text_primary']};
        font-family: "Inter", "Kantumruy Pro", "Noto Sans Khmer", "Khmer OS Battambang", sans-serif;
        font-size: 13px;
    }}

    QHeaderView::section {{
        background-color: {t['bg_elevated']};
        color: {t['text_secondary']};
        font-size: 11.5px;
        font-weight: 700;
        padding: 8px 6px;
        border: none;
        border-bottom: 1px solid {t['border_subtle']};
    }}

    QTableWidget::item {{
        padding: 6px 4px;
        border-bottom: 1px solid {t['border_subtle']};
    }}

    QTableWidget::item:selected {{
        background-color: {t['selection']};
        color: {t['text_primary']};
    }}

    /* =========================================================================
       6. EQUAL-WIDTH SEGMENTED INSPECTOR TABS
       ========================================================================= */
    QTabWidget::pane {{
        background-color: {t['bg_surface']};
        border: 1px solid {t['border_subtle']};
        border-radius: 8px;
        padding: 6px;
    }}

    QTabBar::tab {{
        background-color: {t['bg_elevated']};
        color: {t['text_secondary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 5px;
        padding: 6px 4px;
        margin-right: 2px;
        margin-bottom: 4px;
        font-size: 11px;
        font-weight: 600;
        min-width: 48px;
        text-align: center;
    }}

    QTabBar::tab:selected {{
        background-color: {t['bg_hover']};
        color: {t['accent_primary']};
        border-color: {t['accent_primary']};
        font-weight: 700;
    }}

    QTabBar::tab:hover:!selected {{
        background-color: {t['bg_hover']};
        color: {t['text_primary']};
    }}

    /* =========================================================================
       7. VISIBLE CUSTOM SLIDERS & PROGRESS BARS
       ========================================================================= */
    QSlider::groove:horizontal {{
        height: 4px;
        background: {t['border_subtle']};
        border-radius: 2px;
    }}

    QSlider::sub-page:horizontal {{
        background: {t['accent_primary']};
        border-radius: 2px;
    }}

    QSlider::handle:horizontal {{
        background: {t['accent_primary']};
        border: 2px solid #FFFFFF;
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}

    QSlider::handle:horizontal:hover {{
        background: {t['accent_primary_hover']};
        width: 16px;
        height: 16px;
        margin: -6px 0;
        border-radius: 8px;
    }}

    QProgressBar {{
        background-color: {t['bg_elevated']};
        border: 1px solid {t['border_subtle']};
        border-radius: 6px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}

    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t['accent_ai']}, stop:1 {t['accent_primary']});
        border-radius: 5px;
    }}

    /* =========================================================================
       8. CUSTOM ULTRA-SLIM SCROLLBARS
       ========================================================================= */
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(142, 149, 165, 0.3);
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(142, 149, 165, 0.6);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: rgba(142, 149, 165, 0.3);
        border-radius: 3px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: rgba(142, 149, 165, 0.6);
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* =========================================================================
       9. MENUS & POPUPS
       ========================================================================= */
    QMenu {{
        background-color: {t['bg_surface']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        border-radius: 8px;
        padding: 6px;
        font-size: 12px;
    }}
    QMenu::item {{
        padding: 6px 14px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background-color: {t['selection']};
        color: {t['accent_primary']};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {t['border_subtle']};
        margin: 4px 6px;
    }}

    QToolTip {{
        background-color: {t['bg_elevated']};
        color: {t['text_primary']};
        border: 1px solid {t['border_subtle']};
        padding: 5px 8px;
        border-radius: 6px;
        font-size: 11.5px;
    }}

    QFrame#DropZone {{
        background-color: {t['bg_surface']};
        border: 2px dashed {t['border_subtle']};
        border-radius: 12px;
    }}
    QFrame#DropZone:hover {{
        border-color: {t['accent_primary']};
        background-color: {t['bg_elevated']};
    }}
    """


CLEAN_DARK_QSS = build_stylesheet("obsidian")
