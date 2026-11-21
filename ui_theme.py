# ui_theme.py - Desmos-inspired blue color theme constants and stylesheets

# ── Color Palette ──────────────────────────────────────────────────────────────
BG_MAIN        = "#F0F4FA"   # matte slate-blue background
BG_DISPLAY     = "#FFFFFF"   # crisp white display area
BG_KEYPAD      = "#E8EEF8"   # soft key surface
BG_CARD        = "#FFFFFF"   # choice card background
BG_DRAWER      = "#F5F8FF"   # chat drawer
BG_MODAL       = "#FFFFFF"

BORDER_SOFT    = "#B8C8E8"   # soft navy border
BORDER_ACCENT  = "#4A6FA5"   # cobalt border
BORDER_STRONG  = "#1E3A5F"   # navy strong

TEXT_PRIMARY   = "#1A2B4A"   # deep navy text
TEXT_SECONDARY = "#4A6080"   # muted blue-grey
TEXT_MUTED     = "#8098B8"   # light label text
TEXT_WHITE     = "#FFFFFF"

ACCENT_PRIMARY = "#2563EB"   # vibrant cobalt/royal blue (= button, active)
ACCENT_HOVER   = "#1D4ED8"   # darker cobalt hover
ACCENT_LIGHT   = "#DBEAFE"   # pale blue highlight
ACCENT_PILL    = "#3B82F6"   # skip/pill button

KEY_DEFAULT    = "#FFFFFF"
KEY_HOVER      = "#DBEAFE"
KEY_PRESSED    = "#BFDBFE"
KEY_FN_BG      = "#EEF2FF"   # scientific function keys (indigo tint)
KEY_FN_HOVER   = "#C7D2FE"
KEY_EQUALS_BG  = ACCENT_PRIMARY
KEY_EQUALS_HV  = ACCENT_HOVER

ROBI_BUBBLE_BOT  = "#EFF6FF"
ROBI_BUBBLE_USER = "#DBEAFE"

AD_BG          = "#FF4444"   # jarring red ad background

# ── Font ───────────────────────────────────────────────────────────────────────
FONT_FAMILY = "Segoe UI"
FONT_MONO   = "Consolas"

# ── Shared Stylesheet ─────────────────────────────────────────────────────────
GLOBAL_STYLE = f"""
QWidget {{
    font-family: '{FONT_FAMILY}', 'Arial', sans-serif;
    color: {TEXT_PRIMARY};
    background-color: {BG_MAIN};
}}
QScrollBar:vertical {{
    background: {BG_KEYPAD};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_ACCENT};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG_KEYPAD};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_ACCENT};
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
"""

DISPLAY_STYLE = f"""
QFrame#display_frame {{
    background-color: {BG_DISPLAY};
    border: 1.5px solid {BORDER_SOFT};
    border-radius: 12px;
}}
QLabel#expr_label {{
    font-family: '{FONT_MONO}', monospace;
    font-size: 15px;
    color: {TEXT_SECONDARY};
    background: transparent;
    padding: 2px 8px;
}}
QLabel#result_label {{
    font-family: '{FONT_MONO}', monospace;
    font-size: 26px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
    background: transparent;
    padding: 4px 8px;
}}
"""

KEY_STYLE = f"""
QPushButton.calc-key {{
    background-color: {KEY_DEFAULT};
    color: {TEXT_PRIMARY};
    border: 1.5px solid {BORDER_SOFT};
    border-radius: 10px;
    font-size: 14px;
    font-weight: 500;
    padding: 0;
}}
QPushButton.calc-key:hover {{
    background-color: {KEY_HOVER};
    border-color: {ACCENT_PRIMARY};
}}
QPushButton.calc-key:pressed {{
    background-color: {KEY_PRESSED};
}}
QPushButton.fn-key {{
    background-color: {KEY_FN_BG};
    color: {ACCENT_PRIMARY};
    border: 1.5px solid {BORDER_SOFT};
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    padding: 0;
}}
QPushButton.fn-key:hover {{
    background-color: {KEY_FN_HOVER};
    border-color: {ACCENT_PRIMARY};
}}
QPushButton.eq-key {{
    background-color: {KEY_EQUALS_BG};
    color: {TEXT_WHITE};
    border: none;
    border-radius: 10px;
    font-size: 20px;
    font-weight: 700;
    padding: 0;
}}
QPushButton.eq-key:hover {{
    background-color: {KEY_EQUALS_HV};
}}
QPushButton.eq-key:pressed {{
    background-color: {BORDER_STRONG};
}}
QPushButton.clear-key {{
    background-color: #FEE2E2;
    color: #DC2626;
    border: 1.5px solid #FECACA;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    padding: 0;
}}
QPushButton.clear-key:hover {{
    background-color: #FECACA;
    border-color: #DC2626;
}}
"""

CHOICE_CARD_STYLE = f"""
QPushButton.choice-card {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 2px solid {BORDER_SOFT};
    border-radius: 12px;
    font-size: 14px;
    font-weight: 500;
    text-align: left;
    padding: 10px 16px;
}}
QPushButton.choice-card:hover {{
    background-color: {ACCENT_LIGHT};
    border-color: {ACCENT_PRIMARY};
    color: {ACCENT_PRIMARY};
}}
QPushButton.choice-card:pressed {{
    background-color: {KEY_PRESSED};
}}
"""

PILL_BUTTON_STYLE = f"""
QPushButton {{
    background-color: {ACCENT_PILL};
    color: {TEXT_WHITE};
    border: none;
    border-radius: 16px;
    font-size: 13px;
    font-weight: 600;
    padding: 6px 18px;
}}
QPushButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton:pressed {{
    background-color: {BORDER_STRONG};
}}
"""

MODAL_STYLE = f"""
QDialog {{
    background-color: {BG_MODAL};
    border: 2px solid {BORDER_SOFT};
    border-radius: 16px;
}}
"""

CHAT_STYLE = f"""
QWidget#chat_widget {{
    background-color: {BG_DRAWER};
    border-left: 2px solid {BORDER_SOFT};
}}
QTextEdit#chat_history {{
    background-color: {BG_DRAWER};
    border: none;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}
QLineEdit#chat_input {{
    background-color: {BG_DISPLAY};
    border: 1.5px solid {BORDER_SOFT};
    border-radius: 10px;
    font-size: 13px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
}}
QLineEdit#chat_input:focus {{
    border-color: {ACCENT_PRIMARY};
}}
"""
