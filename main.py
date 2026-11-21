# main.py - Calculater: Desmos-inspired hostile calculator
#
# State machine:  IDLE → CHOICES → CONFIRM → ESSAY → SOLVED / WIPED
#
import sys
import os
import math
import random

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QFont, QIcon, QFontDatabase, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
    QLabel, QPushButton, QDialog, QDialogButtonBox,
    QTextEdit, QScrollArea, QMessageBox, QSplitter,
    QStackedWidget
)

import ui_theme as T
from calculator_logic import safe_eval, format_number, build_choices
from ad_system import AdManager
from robi_chat import RobiChatWidget
from paywall import PaywallModal
from robi_battle import RobiBattleOverlay

# ── State constants ───────────────────────────────────────────────────────────
STATE_IDLE    = "IDLE"
STATE_CHOICES = "CHOICES"
STATE_CONFIRM = "CONFIRM"
STATE_ESSAY   = "ESSAY"
STATE_SOLVED  = "SOLVED"
STATE_WIPED   = "WIPED"

# ── Keypad definition ─────────────────────────────────────────────────────────
# (label, value_to_insert, key_class)
# key_class: "fn" = scientific, "eq" = equals, "clear" = C/backspace, "num" = default
KEYPAD_GRID = [
    # row 0
    [("sin(", "sin(",    "fn"), ("cos(", "cos(",    "fn"), ("tan(", "tan(",    "fn"), ("log(", "log(",    "fn"), ("ln(",  "ln(",     "fn")],
    # row 1
    [("√(",   "√(",      "fn"), ("^",    "^",       "fn"), ("π",    "π",       "fn"), ("e",    "e",       "fn"), ("(",    "(",       "num")],
    # row 2
    [("7",    "7",       "num"), ("8",   "8",       "num"), ("9",   "9",       "num"), ("÷",   "/",       "num"), (")",   ")",       "num")],
    # row 3
    [("4",    "4",       "num"), ("5",   "5",       "num"), ("6",   "6",       "num"), ("×",   "*",       "num"), ("C",   "CLEAR",   "clear")],
    # row 4
    [("1",    "1",       "num"), ("2",   "2",       "num"), ("3",   "3",       "num"), ("−",   "-",       "num"), ("⌫",  "BACK",    "clear")],
    # row 5
    [("0",    "0",       "num"), (".",   ".",       "num"), ("(",   "(",       "num"), ("+",   "+",       "num"), ("=",   "EQUALS",  "eq")],
]


class CalcButton(QPushButton):
    """A single calculator key with sabotage mechanics."""

    def __init__(self, label: str, value: str, key_class: str, app: "CalculaterApp"):
        super().__init__(label)
        self._value     = value
        self._key_class = key_class
        self._app       = app
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("class", key_class + "-key")
        self._apply_style()
        self.clicked.connect(self._on_click)

    def _apply_style(self):
        cls = self._key_class
        if cls == "eq":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {T.KEY_EQUALS_BG};
                    color: {T.TEXT_WHITE};
                    border: none;
                    border-radius: 10px;
                    font-size: 20px;
                    font-weight: 700;
                }}
                QPushButton:hover {{ background-color: {T.KEY_EQUALS_HV}; }}
                QPushButton:pressed {{ background-color: {T.BORDER_STRONG}; }}
            """)
        elif cls == "fn":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {T.KEY_FN_BG};
                    color: {T.ACCENT_PRIMARY};
                    border: 1.5px solid {T.BORDER_SOFT};
                    border-radius: 10px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {T.KEY_FN_HOVER};
                    border-color: {T.ACCENT_PRIMARY};
                }}
            """)
        elif cls == "clear":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #FEE2E2;
                    color: #DC2626;
                    border: 1.5px solid #FECACA;
                    border-radius: 10px;
                    font-size: 13px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background-color: #FECACA; border-color: #DC2626; }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {T.KEY_DEFAULT};
                    color: {T.TEXT_PRIMARY};
                    border: 1.5px solid {T.BORDER_SOFT};
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background-color: {T.KEY_HOVER};
                    border-color: {T.ACCENT_PRIMARY};
                }}
                QPushButton:pressed {{ background-color: {T.KEY_PRESSED}; }}
            """)

    def _on_click(self):
        # Notify ad manager
        self._app.ad_manager.maybe_trigger_click_ad()

        # 1% chance to scramble the keypad
        if random.random() < 0.01:
            self._app.scramble_keypad()
            return

        # 10% chance misclick → fire an adjacent button instead
        value_to_fire = self._value
        if random.random() < 0.10:
            value_to_fire = self._app.get_random_adjacent_value(self)

        self._app.handle_input(value_to_fire)


class ChoiceCard(QPushButton):
    """A multiple-choice answer card with confirmation-trap mechanic."""

    def __init__(self, label: str, text: str, is_correct: bool, on_confirm):
        super().__init__()
        self._label      = label
        self._text       = text
        self._is_correct = is_correct
        self._on_confirm = on_confirm
        self._confirmed  = False
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(52)
        self._refresh_text(first=True)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {T.BG_CARD};
                color: {T.TEXT_PRIMARY};
                border: 2px solid {T.BORDER_SOFT};
                border-radius: 12px;
                font-size: 14px;
                font-weight: 500;
                text-align: left;
                padding: 10px 16px;
            }}
            QPushButton:hover {{
                background-color: {T.ACCENT_LIGHT};
                border-color: {T.ACCENT_PRIMARY};
                color: {T.ACCENT_PRIMARY};
            }}
        """)
        self.clicked.connect(self._handle_click)

    def _refresh_text(self, first=False):
        if first:
            self.setText(f"  {self._label}.  {self._text}")
        else:
            self.setText(f"  {self._label}.  Are you sure your answer is correct?")

    def _handle_click(self):
        if not self._confirmed:
            # First click → show confirmation prompt
            self._confirmed = True
            self._refresh_text()
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #FEF9C3;
                    color: #92400E;
                    border: 2px solid #FCD34D;
                    border-radius: 12px;
                    font-size: 13px;
                    font-weight: 600;
                    text-align: left;
                    padding: 10px 16px;
                }}
                QPushButton:hover {{
                    background-color: #FEF08A;
                    border-color: #EAB308;
                }}
            """)
        else:
            # Second click → trigger essay dialog
            self._on_confirm(self._is_correct, self._label, self._text)


class EssayDialog(QDialog):
    """The 5-paragraph interrogation modal."""

    def __init__(self, parent=None, initial_text=""):
        super().__init__(parent)
        self._initial_text = initial_text
        self.setWindowTitle("Justify Your Answer")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setFixedWidth(560)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {T.BG_MODAL};
                border: 2px solid {T.BORDER_SOFT};
                border-radius: 20px;
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Header banner
        banner = QFrame()
        banner.setFixedHeight(56)
        banner.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {T.ACCENT_PRIMARY}, stop:1 #7C3AED);
                border-top-left-radius: 18px;
                border-top-right-radius: 18px;
            }}
        """)
        blay = QHBoxLayout(banner)
        blay.setContentsMargins(20, 0, 20, 0)
        btitle = QLabel("📝  Elaborate Your Answer")
        btitle.setFont(QFont(T.FONT_FAMILY, 13, QFont.Bold))
        btitle.setStyleSheet("color: white; background: transparent;")
        blay.addWidget(btitle)
        root.addWidget(banner)

        # Body
        body = QWidget()
        body.setStyleSheet(f"background: {T.BG_MODAL};")
        blay2 = QVBoxLayout(body)
        blay2.setContentsMargins(24, 18, 24, 18)
        blay2.setSpacing(14)

        prompt_lbl = QLabel(
            "Please elaborate why you chose this answer, and why you believe in this answer "
            "<b>(minimum of 5 paragraphs)</b>."
        )
        prompt_lbl.setWordWrap(True)
        prompt_lbl.setFont(QFont(T.FONT_FAMILY, 12))
        prompt_lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        blay2.addWidget(prompt_lbl)

        robi_note = QLabel(
            "⚠️  Your essay will be reviewed by Robi (RageBot AI). "
            "Robi will decline all essays until you discover the secret reason in debate."
        )
        robi_note.setWordWrap(True)
        robi_note.setFont(QFont(T.FONT_FAMILY, 10))
        robi_note.setStyleSheet(
            f"color: #92400E; background: #FEF9C3; border-radius: 8px; padding: 8px; border: 1px solid #FCD34D;"
        )
        blay2.addWidget(robi_note)

        self._essay_edit = QTextEdit()
        self._essay_edit.setPlaceholderText(
            "Write at least 5 paragraphs explaining your reasoning...\n\n"
            "Paragraph 1:\n\nParagraph 2:\n\nParagraph 3:\n\n..."
        )
        if self._initial_text:
            self._essay_edit.setPlainText(self._initial_text)

        self._essay_edit.setFixedHeight(220)
        self._essay_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {T.BG_DISPLAY};
                border: 1.5px solid {T.BORDER_SOFT};
                border-radius: 10px;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
                padding: 10px;
            }}
            QTextEdit:focus {{ border-color: {T.ACCENT_PRIMARY}; }}
        """)
        blay2.addWidget(self._essay_edit)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(38)
        cancel.setStyleSheet(f"""
            QPushButton {{
                background: {T.BG_KEYPAD};
                color: {T.TEXT_SECONDARY};
                border: 1.5px solid {T.BORDER_SOFT};
                border-radius: 10px;
                font-size: 13px;
                padding: 0 20px;
            }}
            QPushButton:hover {{ background: {T.KEY_HOVER}; }}
        """)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        submit = QPushButton("Submit to Robi →")
        submit.setFixedHeight(38)
        submit.setCursor(Qt.PointingHandCursor)
        submit.setStyleSheet(f"""
            QPushButton {{
                background: {T.ACCENT_PRIMARY};
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 13px;
                font-weight: 600;
                padding: 0 24px;
            }}
            QPushButton:hover {{ background: {T.ACCENT_HOVER}; }}
        """)
        submit.clicked.connect(self.accept)
        btn_row.addWidget(submit)
        blay2.addLayout(btn_row)

        root.addWidget(body)

    def get_essay(self) -> str:
        return self._essay_edit.toPlainText().strip()


class CalculaterApp(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Calculater")
        self.setMinimumSize(900, 620)
        self.resize(1100, 680)

        # State
        self._state        = STATE_IDLE
        self._expression   = ""
        self._true_answer  = None
        self._choices: list[dict] = []
        self._pending_choice_correct = False
        self._last_essay   = ""

        # Build UI
        self._setup_ui()

        # Keypad button registry (for scrambling & adjacency)
        self._keypad_buttons: list[list[CalcButton]] = []
        self._populate_keypad()

        # Ad manager
        self.ad_manager = AdManager(self._central)
        self.ad_manager.start()

        # Apply global styles
        self.setStyleSheet(T.GLOBAL_STYLE)

    # ══════════════════════════════════════════════════════════════════════════
    # UI Setup
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_ui(self):
        self._central = QWidget()
        self.setCentralWidget(self._central)
        self._central.setStyleSheet(f"background-color: {T.BG_MAIN};")

        outer = QHBoxLayout(self._central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── LEFT PANEL: display + keypad ──────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(420)
        left.setStyleSheet(f"background: {T.BG_MAIN};")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(20, 20, 10, 20)
        left_lay.setSpacing(14)

        # App title
        title_row = QHBoxLayout()
        app_title = QLabel("🧮  Calculater")
        app_title.setFont(QFont(T.FONT_FAMILY, 16, QFont.Bold))
        app_title.setStyleSheet(f"color: {T.ACCENT_PRIMARY};")
        title_row.addWidget(app_title)
        title_row.addStretch()
        # Settings icon (placeholder)
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T.TEXT_MUTED};
                border: none;
                font-size: 18px;
            }}
            QPushButton:hover {{ color: {T.ACCENT_PRIMARY}; }}
        """)
        settings_btn.clicked.connect(self._open_settings)
        title_row.addWidget(settings_btn)
        left_lay.addLayout(title_row)

        # Display area (expression + result split header)
        display_frame = QFrame()
        display_frame.setObjectName("display_frame")
        display_frame.setFixedHeight(100)
        display_frame.setStyleSheet(f"""
            QFrame#display_frame {{
                background-color: {T.BG_DISPLAY};
                border: 1.5px solid {T.BORDER_SOFT};
                border-radius: 14px;
            }}
        """)
        disp_lay = QVBoxLayout(display_frame)
        disp_lay.setContentsMargins(14, 10, 14, 10)
        disp_lay.setSpacing(2)

        self._expr_label = QLabel("")
        self._expr_label.setObjectName("expr_label")
        self._expr_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._expr_label.setFont(QFont(T.FONT_MONO, 14))
        self._expr_label.setStyleSheet(f"color: {T.TEXT_MUTED}; background: transparent;")
        self._expr_label.setWordWrap(False)
        self._expr_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        disp_lay.addWidget(self._expr_label)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color: {T.BORDER_SOFT}; background: {T.BORDER_SOFT};")
        div.setFixedHeight(1)
        disp_lay.addWidget(div)

        self._result_label = QLabel("0")
        self._result_label.setObjectName("result_label")
        self._result_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._result_label.setFont(QFont(T.FONT_MONO, 28, QFont.Bold))
        self._result_label.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        disp_lay.addWidget(self._result_label)

        left_lay.addWidget(display_frame)

        # Keypad grid
        self._keypad_frame = QFrame()
        self._keypad_frame.setStyleSheet(f"""
            QFrame {{
                background: {T.BG_KEYPAD};
                border: 1.5px solid {T.BORDER_SOFT};
                border-radius: 14px;
            }}
        """)
        self._keypad_layout = QGridLayout(self._keypad_frame)
        self._keypad_layout.setContentsMargins(12, 12, 12, 12)
        self._keypad_layout.setSpacing(7)
        left_lay.addWidget(self._keypad_frame, 1)

        outer.addWidget(left, 0)

        # ── VERTICAL DIVIDER ──────────────────────────────────────────────────
        vdiv = QFrame()
        vdiv.setFrameShape(QFrame.VLine)
        vdiv.setStyleSheet(f"color: {T.BORDER_SOFT};")
        vdiv.setFixedWidth(1)
        outer.addWidget(vdiv)

        # ── RIGHT PANEL: answer choices + Robi ───────────────────────────────
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setHandleWidth(1)
        right_splitter.setStyleSheet("QSplitter::handle { background: transparent; }")

        # Answer area
        answer_container = QWidget()
        answer_container.setStyleSheet(f"background: {T.BG_MAIN};")
        self._answer_lay = QVBoxLayout(answer_container)
        self._answer_lay.setContentsMargins(14, 20, 14, 10)
        self._answer_lay.setSpacing(10)

        ans_title_row = QHBoxLayout()
        self._ans_title = QLabel("Select Answer")
        self._ans_title.setFont(QFont(T.FONT_FAMILY, 13, QFont.Bold))
        self._ans_title.setStyleSheet(f"color: {T.TEXT_PRIMARY};")
        ans_title_row.addWidget(self._ans_title)
        ans_title_row.addStretch()

        # "Instant Answer (Skip)" pill
        self._skip_btn = QPushButton("⚡  Instant Answer (Skip)")
        self._skip_btn.setFixedHeight(32)
        self._skip_btn.setCursor(Qt.PointingHandCursor)
        self._skip_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T.ACCENT_PILL};
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background-color: {T.ACCENT_HOVER}; }}
        """)
        self._skip_btn.clicked.connect(self._on_skip)
        self._skip_btn.hide()
        ans_title_row.addWidget(self._skip_btn)

        # Circular Chatbot Avatar Icon
        self._robi_circle_btn = QPushButton("🤖")
        self._robi_circle_btn.setFixedSize(42, 42)
        self._robi_circle_btn.setCursor(Qt.PointingHandCursor)
        self._robi_circle_btn.setToolTip("Chat with Robi (RageBot AI)")
        self._robi_circle_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {T.ACCENT_PRIMARY}, stop:1 #7C3AED);
                color: white;
                border: 2px solid white;
                border-radius: 21px;
                font-size: 20px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {T.ACCENT_HOVER}, stop:1 #6D28D9);
                border: 2px solid {T.ACCENT_LIGHT};
            }}
        """)
        self._robi_circle_btn.clicked.connect(self._toggle_robi)
        ans_title_row.addWidget(self._robi_circle_btn)

        self._answer_lay.addLayout(ans_title_row)

        # Debate & Rejection Panel
        self._debate_panel = QFrame()
        self._debate_panel.setStyleSheet(f"""
            QFrame {{
                background-color: #FEF2F2;
                border: 1.5px solid #FCA5A5;
                border-radius: 12px;
            }}
        """)
        dp_lay = QVBoxLayout(self._debate_panel)
        dp_lay.setContentsMargins(14, 10, 14, 10)
        dp_lay.setSpacing(6)

        dp_title = QLabel("❌ Robi Rejected Your Essay!")
        dp_title.setFont(QFont(T.FONT_FAMILY, 11, QFont.Bold))
        dp_title.setStyleSheet("color: #DC2626; background: transparent;")
        dp_lay.addWidget(dp_title)

        self._debate_desc = QLabel("Robi thinks your explanation is a delusion. Argue with Robi to extract a hint, or revise your essay.")
        self._debate_desc.setFont(QFont(T.FONT_FAMILY, 10))
        self._debate_desc.setWordWrap(True)
        self._debate_desc.setStyleSheet("color: #7F1D1D; background: transparent;")
        dp_lay.addWidget(self._debate_desc)

        dp_btn_row = QHBoxLayout()
        dp_argue_btn = QPushButton("🗣️ Argue / Debate with Robi")
        dp_argue_btn.setFixedHeight(32)
        dp_argue_btn.setCursor(Qt.PointingHandCursor)
        dp_argue_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T.ACCENT_PRIMARY};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 11px;
                font-weight: 700;
                padding: 0 12px;
            }}
            QPushButton:hover {{ background-color: {T.ACCENT_HOVER}; }}
        """)
        dp_argue_btn.clicked.connect(self._focus_argue_robi)
        dp_btn_row.addWidget(dp_argue_btn)

        dp_revise_btn = QPushButton("✏️ Revise & Resubmit Essay")
        dp_revise_btn.setFixedHeight(32)
        dp_revise_btn.setCursor(Qt.PointingHandCursor)
        dp_revise_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 11px;
                font-weight: 700;
                padding: 0 12px;
            }}
            QPushButton:hover {{ background-color: #DC2626; }}
        """)
        dp_revise_btn.clicked.connect(self._reopen_essay)
        dp_btn_row.addWidget(dp_revise_btn)
        dp_lay.addLayout(dp_btn_row)

        self._debate_panel.hide()
        self._answer_lay.addWidget(self._debate_panel)

        # Placeholder when idle
        self._idle_placeholder = QLabel(
            "Press  =  to evaluate your expression\nand receive your multiple-choice options here."
        )
        self._idle_placeholder.setFont(QFont(T.FONT_FAMILY, 12))
        self._idle_placeholder.setAlignment(Qt.AlignCenter)
        self._idle_placeholder.setStyleSheet(f"color: {T.TEXT_MUTED}; background: transparent;")
        self._idle_placeholder.setWordWrap(True)
        self._answer_lay.addWidget(self._idle_placeholder, 1)

        # Cards container (shown in CHOICES state)
        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet("background: transparent;")
        self._cards_lay = QVBoxLayout(self._cards_widget)
        self._cards_lay.setContentsMargins(0, 0, 0, 0)
        self._cards_lay.setSpacing(8)
        self._cards_widget.hide()
        self._answer_lay.addWidget(self._cards_widget, 1)

        # Solved answer display
        self._solved_frame = QFrame()
        self._solved_frame.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {T.ACCENT_LIGHT}, stop:1 #BFDBFE);
                border: 2px solid {T.ACCENT_PRIMARY};
                border-radius: 14px;
            }}
        """)
        sol_lay = QVBoxLayout(self._solved_frame)
        sol_lay.setContentsMargins(20, 16, 20, 16)
        sol_lbl_top = QLabel("✅  Correct! Robi reluctantly accepts.")
        sol_lbl_top.setFont(QFont(T.FONT_FAMILY, 11))
        sol_lbl_top.setStyleSheet(f"color: {T.ACCENT_PRIMARY}; background: transparent;")
        sol_lay.addWidget(sol_lbl_top)
        self._solved_value_label = QLabel("")
        self._solved_value_label.setFont(QFont(T.FONT_MONO, 32, QFont.Bold))
        self._solved_value_label.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        self._solved_value_label.setAlignment(Qt.AlignCenter)
        sol_lay.addWidget(self._solved_value_label)
        new_calc_btn = QPushButton("New Calculation")
        new_calc_btn.setFixedHeight(36)
        new_calc_btn.setCursor(Qt.PointingHandCursor)
        new_calc_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.ACCENT_PRIMARY};
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {T.ACCENT_HOVER}; }}
        """)
        new_calc_btn.clicked.connect(self._reset)
        sol_lay.addWidget(new_calc_btn)
        self._solved_frame.hide()
        self._answer_lay.addWidget(self._solved_frame)

        right_splitter.addWidget(answer_container)

        # ── Robi chat area ────────────────────────────────────────────────────
        robi_container = QWidget()
        robi_container.setStyleSheet(f"background: {T.BG_MAIN};")
        robi_outer_lay = QVBoxLayout(robi_container)
        robi_outer_lay.setContentsMargins(14, 0, 14, 14)
        robi_outer_lay.setSpacing(6)

        ask_robi_header = QHBoxLayout()
        robi_toggle_btn = QPushButton("💬  Ask Robi")
        robi_toggle_btn.setFixedHeight(30)
        robi_toggle_btn.setCursor(Qt.PointingHandCursor)
        robi_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {T.ACCENT_PRIMARY};
                border: 1.5px solid {T.ACCENT_PRIMARY};
                border-radius: 15px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 12px;
            }}
            QPushButton:hover {{ background-color: {T.ACCENT_LIGHT}; }}
        """)
        robi_toggle_btn.clicked.connect(self._toggle_robi)
        ask_robi_header.addWidget(robi_toggle_btn)
        ask_robi_header.addStretch()
        robi_outer_lay.addLayout(ask_robi_header)

        self._robi_widget = RobiChatWidget()
        self._robi_widget.essay_rejected.connect(self._on_essay_rejected)
        self._robi_widget.essay_accepted.connect(self._on_essay_accepted)
        self._robi_widget.request_resubmit.connect(self._reopen_essay)
        self._robi_widget.request_battle.connect(self._start_battle)
        self._robi_widget.hide()
        robi_outer_lay.addWidget(self._robi_widget, 1)

        right_splitter.addWidget(robi_container)
        right_splitter.setSizes([400, 280])

        outer.addWidget(right_splitter, 1)

    # ══════════════════════════════════════════════════════════════════════════
    # Keypad population & scramble
    # ══════════════════════════════════════════════════════════════════════════
    def _populate_keypad(self, layout=None):
        """Fill self._keypad_layout with CalcButton instances."""
        grid = self._keypad_layout if layout is None else layout

        # Clear existing
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._keypad_buttons = []
        for row_idx, row_def in enumerate(KEYPAD_GRID):
            row_btns = []
            for col_idx, (label, value, cls) in enumerate(row_def):
                btn = CalcButton(label, value, cls, self)
                grid.addWidget(btn, row_idx, col_idx)
                row_btns.append(btn)
            self._keypad_buttons.append(row_btns)

    def scramble_keypad(self):
        """Randomly shuffle all button positions in the keypad grid."""
        # Collect all buttons
        flat = [btn for row in self._keypad_buttons for btn in row]
        positions = [(r, c) for r in range(len(KEYPAD_GRID)) for c in range(len(KEYPAD_GRID[r]))]

        # Remove all from grid without deleting
        for btn in flat:
            self._keypad_layout.removeWidget(btn)

        random.shuffle(positions)
        self._keypad_buttons = []
        pos_iter = iter(positions)
        for row_def in KEYPAD_GRID:
            row_btns = []
            for _ in row_def:
                r, c = next(pos_iter)
                btn = flat.pop(0)
                self._keypad_layout.addWidget(btn, r, c)
                row_btns.append(btn)
            self._keypad_buttons.append(row_btns)

    def get_random_adjacent_value(self, btn: "CalcButton") -> str:
        """Find the value of a random adjacent button for misclick sabotage."""
        flat = [(r, c, b) for r, row in enumerate(self._keypad_buttons) for c, b in enumerate(row)]
        # Find this button's position
        pos = None
        for r, c, b in flat:
            if b is btn:
                pos = (r, c)
                break
        if pos is None:
            return btn._value

        r0, c0 = pos
        candidates = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                r1, c1 = r0 + dr, c0 + dc
                if 0 <= r1 < len(self._keypad_buttons):
                    row = self._keypad_buttons[r1]
                    if 0 <= c1 < len(row):
                        candidates.append(row[c1]._value)
        return random.choice(candidates) if candidates else btn._value

    # ══════════════════════════════════════════════════════════════════════════
    # Input handling
    # ══════════════════════════════════════════════════════════════════════════
    def handle_input(self, value: str):
        if self._state in (STATE_CHOICES, STATE_CONFIRM, STATE_ESSAY):
            return   # lock keypad during choices
        if self._state == STATE_SOLVED:
            self._reset()

        if value == "CLEAR":
            self._expression = ""
            self._update_display()
        elif value == "BACK":
            self._expression = self._expression[:-1]
            self._update_display()
        elif value == "EQUALS":
            self._evaluate()
        else:
            self._expression += value
            self._update_display()

    def _update_display(self):
        display = self._expression or "0"
        # Truncate display if very long
        if len(display) > 42:
            display_short = "…" + display[-40:]
        else:
            display_short = display
        self._expr_label.setText(display_short)
        self._result_label.setText("")

    def _evaluate(self):
        if not self._expression.strip():
            return
        try:
            result = safe_eval(self._expression)
        except Exception as exc:
            self._result_label.setText("Error")
            self._expr_label.setText(str(exc)[:40])
            self._expression = ""
            return

        self._true_answer = result
        self._choices = build_choices(result)
        self._transition_to_choices()

    # ══════════════════════════════════════════════════════════════════════════
    # State transitions
    # ══════════════════════════════════════════════════════════════════════════
    def _transition_to_choices(self):
        self._state = STATE_CHOICES
        # Update Robi context
        self._robi_widget.set_context(self._expression, self._choices)

        # Build choice cards
        self._idle_placeholder.hide()
        self._solved_frame.hide()
        # Clear existing cards
        while self._cards_lay.count():
            item = self._cards_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for ch in self._choices:
            card = ChoiceCard(ch["label"], ch["text"], ch["is_correct"], self._on_choice_confirmed)
            self._cards_lay.addWidget(card)

        self._cards_lay.addStretch()
        self._cards_widget.show()
        self._skip_btn.show()
        self._ans_title.setText("Choose the correct answer:")
        self._result_label.setText("?")
        self._state = STATE_CONFIRM   # allow clicking cards

    def _on_choice_confirmed(self, is_correct: bool, label: str, text: str):
        """Called when user double-confirms a choice card."""
        self._state = STATE_ESSAY
        self._pending_choice_correct = is_correct
        self._open_essay_dialog(label, text)

    def _open_essay_dialog(self, label: str = "", text: str = ""):
        dlg = EssayDialog(self, initial_text=self._last_essay)
        result = dlg.exec()
        if result == QDialog.Accepted:
            essay = dlg.get_essay()
            self._last_essay = essay
            # Validate through Robi
            self._robi_widget.validate_essay(essay)
            # Show Robi chat
            self._robi_widget.show()
        else:
            # Cancelled — back to choices
            self._state = STATE_CONFIRM

    def _focus_argue_robi(self):
        """Focus the Robi chat input to debate the essay."""
        self._robi_widget.show()
        self._robi_widget.focus_input()

    def _reopen_essay(self):
        """Reopen the essay dialog with existing text."""
        self._open_essay_dialog()

    def _on_essay_rejected(self, msg: str):
        """Robi rejected — keep choices intact and open debate."""
        self._state = STATE_CONFIRM
        self._result_label.setText("Rejected!")
        self._result_label.setStyleSheet("color: #DC2626; background: transparent; font-size: 26px; font-weight: 700;")
        self._ans_title.setText("Essay Rejected — Argue or Revise:")
        self._debate_panel.show()
        self._robi_widget.show()

    def _on_essay_accepted(self):
        """Robi accepted — show true answer."""
        self._state = STATE_SOLVED
        self._debate_panel.hide()
        self._cards_widget.hide()
        self._idle_placeholder.hide()
        self._skip_btn.hide()
        true_str = format_number(self._true_answer)
        self._solved_value_label.setText(true_str)
        self._result_label.setText(true_str)
        self._result_label.setStyleSheet(f"color: {T.ACCENT_PRIMARY}; background: transparent; font-size: 28px; font-weight: 700;")
        self._solved_frame.show()
        self._ans_title.setText("Answer Unlocked")

    def _reset(self):
        self._state       = STATE_IDLE
        self._expression  = ""
        self._true_answer = None
        self._choices     = []
        self._last_essay  = ""
        self._update_display()
        self._result_label.setText("0")
        self._result_label.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent; font-size: 28px; font-weight: 700;")
        self._cards_widget.hide()
        self._solved_frame.hide()
        self._debate_panel.hide()
        self._skip_btn.hide()
        self._idle_placeholder.show()
        self._ans_title.setText("Select Answer")
        # Clear cards
        while self._cards_lay.count():
            item = self._cards_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ══════════════════════════════════════════════════════════════════════════
    # Misc actions
    # ══════════════════════════════════════════════════════════════════════════
    def _on_skip(self):
        if self._true_answer is None:
            return
        modal = PaywallModal(format_number(self._true_answer), self)
        modal.exec()

    def _toggle_robi(self):
        if self._robi_widget.isVisible():
            self._robi_widget.hide()
        else:
            self._robi_widget.show()

    def _open_settings(self):
        """Simple settings dialog for GROQ_API_KEY."""
        from PySide6.QtWidgets import QInputDialog
        key, ok = QInputDialog.getText(
            self, "Robi API Settings",
            "Enter your GROQ_API_KEY (saved to .env in app folder):",
        )
        if ok and key.strip():
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
            with open(env_path, "w") as f:
                f.write(f"GROQ_API_KEY={key.strip()}\n")
            os.environ["GROQ_API_KEY"] = key.strip()
            self._robi_widget._init_groq()
            QMessageBox.information(self, "Saved", "API key saved! Robi is now fully powered.")

    def _start_battle(self):
        """Initiate the Undertale-style boss fight against Robi."""
        if hasattr(self, "_battle_overlay") and self._battle_overlay and self._battle_overlay.isVisible():
            return
        # 1. Suspend ad manager & hide visible ads
        self.ad_manager.pause()
        # 2. Inform Robi chat
        self._robi_widget.set_battle_active(True)
        # 3. Create battle overlay covering the full window
        self._battle_overlay = RobiBattleOverlay(self)
        self._battle_overlay.setGeometry(self.rect())
        self._battle_overlay.battle_won.connect(self._on_battle_won)
        self._battle_overlay.battle_lost.connect(self._on_battle_lost)
        self._battle_overlay.battle_ended.connect(self._on_battle_ended)
        self._battle_overlay.show()
        self._battle_overlay.raise_()
        self._battle_overlay.setFocus()

    def _on_battle_won(self):
        """Victory: Robi admits defeat and drops the secret phrase."""
        self._robi_widget.post_battle_victory()
        self._robi_widget.show()
        self.ad_manager.resume()

    def _on_battle_lost(self):
        """Defeat: Robi mocks the player."""
        self._robi_widget.post_battle_defeat()
        self._robi_widget.show()
        self.ad_manager.resume()

    def _on_battle_ended(self):
        """Clean up when battle finishes."""
        self._robi_widget.set_battle_active(False)
        self.ad_manager.resume()
        self._battle_overlay = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_battle_overlay") and self._battle_overlay and self._battle_overlay.isVisible():
            self._battle_overlay.setGeometry(self.rect())


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════
def log_debug(msg):
    try:
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def main():
    log_debug("1. main() called")
    app = QApplication(sys.argv)
    log_debug("2. QApplication created")
    app.setApplicationName("Calculater")
    app.setApplicationDisplayName("Calculater")

    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(T.BG_MAIN))
    palette.setColor(QPalette.WindowText,      QColor(T.TEXT_PRIMARY))
    palette.setColor(QPalette.Base,            QColor(T.BG_DISPLAY))
    palette.setColor(QPalette.AlternateBase,   QColor(T.BG_KEYPAD))
    palette.setColor(QPalette.Text,            QColor(T.TEXT_PRIMARY))
    palette.setColor(QPalette.Button,          QColor(T.KEY_DEFAULT))
    palette.setColor(QPalette.ButtonText,      QColor(T.TEXT_PRIMARY))
    palette.setColor(QPalette.Highlight,       QColor(T.ACCENT_PRIMARY))
    palette.setColor(QPalette.HighlightedText, QColor(T.TEXT_WHITE))
    app.setPalette(palette)
    log_debug("3. Palette set")

    try:
        win = CalculaterApp()
        log_debug(f"4. CalculaterApp instantiated: {win}")
        win.show()
        win.raise_()
        win.activateWindow()
        log_debug(f"5. win.show() called, isVisible={win.isVisible()}, winId={int(win.winId())}")
    except Exception as e:
        log_debug(f"ERROR in CalculaterApp: {e}")
        import traceback
        log_debug(traceback.format_exc())

    log_debug("6. entering app.exec()")
    code = app.exec()
    log_debug(f"7. app.exec() exited with code {code}")
    sys.exit(code)


if __name__ == "__main__":
    main()
