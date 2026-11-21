# paywall.py - "Instant Answer (Skip)" subscription decrypt paywall modal
import random

from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QFont, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QButtonGroup, QRadioButton, QWidget,
    QSizePolicy, QScrollArea
)

import ui_theme as T
from calculator_logic import encrypt_answer


class PaywallModal(QDialog):
    """
    Polished SaaS paywall modal.
    Shows the ciphertext, tier selector, mock credit card form.
    'Subscribe' button does nothing useful.
    """

    TIERS = [
        ("Calculater Basic",   "$2.99/mo",  ["Remove ads",           "Instant answers",    "5 equations/day"]),
        ("Calculater Pro",     "$9.99/mo",  ["Everything in Basic",  "Unlimited equations","Priority Robi access"]),
        ("Calculater Elite",   "$29.99/mo", ["Everything in Pro",    "VIP ad experience",  "Dedicated Robi agent"]),
    ]

    def __init__(self, true_answer_str: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._cipher = encrypt_answer(true_answer_str)
        self._selected_tier = 1   # default Pro

        self.setFixedWidth(500)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {T.BG_MODAL};
                border: 2px solid {T.BORDER_SOFT};
                border-radius: 20px;
            }}
        """)
        self._build_ui()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Banner
        banner = QFrame()
        banner.setFixedHeight(60)
        banner.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {T.ACCENT_PRIMARY}, stop:1 #7C3AED);
                border-top-left-radius: 18px;
                border-top-right-radius: 18px;
            }}
        """)
        b_lay = QHBoxLayout(banner)
        b_lay.setContentsMargins(20, 0, 20, 0)
        b_title = QLabel("🔒  Unlock Instant Answer")
        b_title.setFont(QFont(T.FONT_FAMILY, 14, QFont.Bold))
        b_title.setStyleSheet("color: white; background: transparent;")
        b_lay.addWidget(b_title)
        b_lay.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.2);
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(255,255,255,0.4); }
        """)
        close_btn.clicked.connect(self.reject)
        b_lay.addWidget(close_btn)
        root.addWidget(banner)

        # ── Body scroll area
        body = QWidget()
        body.setStyleSheet(f"background: {T.BG_MODAL};")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(24, 20, 24, 20)
        body_lay.setSpacing(16)

        # Ciphertext block
        cipher_lbl = QLabel("Encrypted Answer:")
        cipher_lbl.setFont(QFont(T.FONT_FAMILY, 11, QFont.Bold))
        cipher_lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY};")
        body_lay.addWidget(cipher_lbl)

        cipher_box = QFrame()
        cipher_box.setStyleSheet(f"""
            QFrame {{
                background-color: #0F172A;
                border: 1.5px solid {T.BORDER_ACCENT};
                border-radius: 10px;
                padding: 10px;
            }}
        """)
        cb_lay = QHBoxLayout(cipher_box)
        cb_lay.setContentsMargins(12, 10, 12, 10)
        cipher_text = QLabel(self._cipher)
        cipher_text.setFont(QFont(T.FONT_MONO, 13, QFont.Bold))
        cipher_text.setStyleSheet("color: #22D3EE; background: transparent;")
        cipher_text.setWordWrap(True)
        cb_lay.addWidget(cipher_text)
        lock_icon = QLabel("🔐")
        lock_icon.setFont(QFont(T.FONT_FAMILY, 20))
        lock_icon.setStyleSheet("background: transparent;")
        cb_lay.addWidget(lock_icon)
        body_lay.addWidget(cipher_box)

        hint = QLabel("Subscribe to decrypt and reveal the true answer instantly.")
        hint.setFont(QFont(T.FONT_FAMILY, 11))
        hint.setStyleSheet(f"color: {T.TEXT_MUTED};")
        hint.setWordWrap(True)
        body_lay.addWidget(hint)

        # ── Tier selector
        tier_lbl = QLabel("Choose your plan:")
        tier_lbl.setFont(QFont(T.FONT_FAMILY, 12, QFont.Bold))
        body_lay.addWidget(tier_lbl)

        self._tier_group = QButtonGroup(self)
        for i, (name, price, perks) in enumerate(self.TIERS):
            card = self._make_tier_card(i, name, price, perks)
            body_lay.addWidget(card)

        # ── Credit card form
        cc_lbl = QLabel("Payment Details:")
        cc_lbl.setFont(QFont(T.FONT_FAMILY, 12, QFont.Bold))
        body_lay.addWidget(cc_lbl)

        form_frame = QFrame()
        form_frame.setStyleSheet(f"""
            QFrame {{
                background: {T.BG_KEYPAD};
                border: 1.5px solid {T.BORDER_SOFT};
                border-radius: 12px;
            }}
        """)
        ff = QVBoxLayout(form_frame)
        ff.setContentsMargins(16, 14, 16, 14)
        ff.setSpacing(10)

        self._cc_num = self._make_field("Card Number", "1234  5678  9012  3456")
        self._cc_exp = self._make_field("MM / YY", "12 / 29")
        self._cc_cvv = self._make_field("CVV", "•••")
        self._cc_name = self._make_field("Cardholder Name", "John Doe")

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("💳"), 0)
        row1.addWidget(self._cc_num, 1)
        ff.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(self._cc_exp)
        row2.addWidget(self._cc_cvv)
        ff.addLayout(row2)
        ff.addWidget(self._cc_name)
        body_lay.addWidget(form_frame)

        # ── Subscribe button
        sub_btn = QPushButton("🔓  Subscribe & Decrypt Now")
        sub_btn.setFixedHeight(48)
        sub_btn.setCursor(Qt.PointingHandCursor)
        sub_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {T.ACCENT_PRIMARY}, stop:1 #7C3AED);
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 15px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {T.ACCENT_HOVER}, stop:1 #6D28D9);
            }}
        """)
        sub_btn.clicked.connect(self._on_subscribe)
        body_lay.addWidget(sub_btn)

        fine_print = QLabel(
            "By subscribing you agree to our Terms of Service. Cancel anytime — "
            "just kidding, cancellation requires contacting our 24/7 support team "
            "which is currently experiencing high volume. All sales final."
        )
        fine_print.setWordWrap(True)
        fine_print.setFont(QFont(T.FONT_FAMILY, 9))
        fine_print.setStyleSheet(f"color: {T.TEXT_MUTED};")
        body_lay.addWidget(fine_print)

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(560)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        root.addWidget(scroll)

    def _make_tier_card(self, idx: int, name: str, price: str, perks: list[str]) -> QFrame:
        frame = QFrame()
        is_recommended = (idx == 1)
        border = T.ACCENT_PRIMARY if is_recommended else T.BORDER_SOFT
        bg     = T.ACCENT_LIGHT   if is_recommended else T.BG_CARD
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 12px;
            }}
        """)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        rb = QRadioButton()
        rb.setChecked(is_recommended)
        self._tier_group.addButton(rb, idx)
        rb.setStyleSheet(f"QRadioButton::indicator {{ width: 18px; height: 18px; }}")
        lay.addWidget(rb)

        info = QVBoxLayout()
        name_row = QHBoxLayout()
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont(T.FONT_FAMILY, 12, QFont.Bold))
        name_row.addWidget(name_lbl)
        if is_recommended:
            rec = QLabel("  RECOMMENDED")
            rec.setFont(QFont(T.FONT_FAMILY, 9, QFont.Bold))
            rec.setStyleSheet(f"color: {T.ACCENT_PRIMARY}; background: transparent;")
            name_row.addWidget(rec)
        name_row.addStretch()
        info.addLayout(name_row)

        price_lbl = QLabel(price)
        price_lbl.setFont(QFont(T.FONT_FAMILY, 11))
        price_lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY};")
        info.addWidget(price_lbl)

        for perk in perks:
            p = QLabel(f"✓ {perk}")
            p.setFont(QFont(T.FONT_FAMILY, 10))
            p.setStyleSheet(f"color: {T.TEXT_MUTED};")
            info.addWidget(p)

        lay.addLayout(info)
        return frame

    def _make_field(self, placeholder: str, hint: str = "") -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setFixedHeight(36)
        field.setStyleSheet(f"""
            QLineEdit {{
                background: {T.BG_DISPLAY};
                border: 1.5px solid {T.BORDER_SOFT};
                border-radius: 8px;
                font-size: 13px;
                padding: 4px 10px;
                color: {T.TEXT_PRIMARY};
            }}
            QLineEdit:focus {{ border-color: {T.ACCENT_PRIMARY}; }}
        """)
        return field

    def _on_subscribe(self):
        # Pretend to process, then show an error
        from PySide6.QtWidgets import QMessageBox
        mb = QMessageBox(self)
        mb.setWindowTitle("Processing...")
        mb.setText(
            "✅ Payment received!\n\n"
            "Your decryption key is being generated...\n\n"
            "ERROR 402: Decryption service temporarily unavailable.\n"
            "Please try again in 24–48 business hours.\n\n"
            "You have NOT been charged.*\n\n"
            "*You may have been charged."
        )
        mb.setIcon(QMessageBox.Warning)
        mb.exec()
