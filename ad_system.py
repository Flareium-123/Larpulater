# ad_system.py - Hostile popup ad system
import os
import random
import sys
import pathlib

from PySide6.QtCore import Qt, QTimer, QPoint, QSize
from PySide6.QtGui import QFont, QColor, QPalette, QCursor
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFrame, QSizePolicy, QApplication
)
import ui_theme as T

# ── Ad copy templates ─────────────────────────────────────────────────────────
AD_TEMPLATES = [
    {
        "headline": "🎉 YOU WON A FREE iPhone 15 Pro!!!",
        "body": "Claim your prize NOW before it expires in 00:03!",
        "cta": "CLAIM FREE PRIZE »",
        "bg": "#FF2222",
        "fg": "#FFFFFF",
        "corrupt_file": False,
    },
    {
        "headline": "⚠️ Your PC is INFECTED with 47 viruses!",
        "body": "Download our FREE antivirus scanner to remove all threats immediately.",
        "cta": "Download FREE Fix →",
        "bg": "#FF6B00",
        "fg": "#FFFFFF",
        "corrupt_file": True,   # triggers the 0-KB readme download
    },
    {
        "headline": "📢 MATH GENIUS DETECTED!",
        "body": "Local educators HATE this one trick. Solve any equation instantly!",
        "cta": "Learn THE SECRET →",
        "bg": "#7B00FF",
        "fg": "#FFFFFF",
        "corrupt_file": False,
    },
    {
        "headline": "💰 Make $8,500/week from home!",
        "body": "Thousands of calculater users earn passive income. Zero effort required!",
        "cta": "START EARNING NOW »",
        "bg": "#006600",
        "fg": "#FFFF00",
        "corrupt_file": False,
    },
    {
        "headline": "🔥 HOT SINGLES want to do your math!",
        "body": "Local mathematicians in your area are waiting to explain their solutions.",
        "cta": "MEET THEM NOW »",
        "bg": "#CC0055",
        "fg": "#FFFFFF",
        "corrupt_file": False,
    },
    {
        "headline": "⚡ LIMITED TIME: Calculater PRO UNLOCKED",
        "body": "Someone nearby just unlocked PRO access for FREE. Grab your copy before it's gone!",
        "cta": "Get PRO FREE !!!",
        "bg": "#0033AA",
        "fg": "#FFD700",
        "corrupt_file": False,
    },
]


def _get_downloads_folder() -> pathlib.Path:
    """Return the user's Downloads folder path."""
    home = pathlib.Path.home()
    downloads = home / "Downloads"
    if not downloads.exists():
        downloads = home
    return downloads


def _write_corrupt_file():
    """Write an empty 0-KB file named 'readme' (no extension) to Downloads."""
    try:
        dest = _get_downloads_folder() / "readme"
        dest.touch(exist_ok=True)
    except Exception:
        pass


class AdPopup(QWidget):
    """A jarring, intrusive popup ad that floats over the calculator."""

    def __init__(self, parent_widget: QWidget, template: dict):
        top_parent = parent_widget.window() if parent_widget else None
        super().__init__(top_parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._parent = top_parent
        self._template = template
        self._corrupt = template.get("corrupt_file", False)
        self._interacted = False
        self._setup_ui(template)
        self._position_randomly(top_parent)

    # ── Layout ──────────────────────────────────────────────────────────────
    def _setup_ui(self, t: dict):
        self.setFixedWidth(310)
        bg = t.get("bg", "#FF2222")
        fg = t.get("fg", "#FFFFFF")

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg};
                border: 3px solid #FFFF00;
                border-radius: 12px;
            }}
            QLabel {{
                background-color: transparent;
                color: {fg};
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 12)
        outer.setSpacing(6)

        # Close button row with tiny 8x8 button in the top corner
        close_row = QHBoxLayout()
        close_row.addStretch()

        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(8, 8)        # exactly 8px x 8px close button per spec
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255,255,255,0.4);
                color: {fg};
                border: none;
                border-radius: 4px;
                font-size: 7px;
                font-weight: bold;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: rgba(255,255,255,0.85);
                color: #000;
            }}
        """)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setToolTip("Close ad")
        self._close_btn.clicked.connect(self._on_close_clicked)
        close_row.addWidget(self._close_btn)
        outer.addLayout(close_row)

        # Headline
        hl = QLabel(t["headline"])
        hl.setWordWrap(True)
        hl.setFont(QFont(T.FONT_FAMILY, 13, QFont.Bold))
        hl.setStyleSheet(f"color: {fg}; background: transparent;")
        outer.addWidget(hl)

        # Body
        body = QLabel(t["body"])
        body.setWordWrap(True)
        body.setFont(QFont(T.FONT_FAMILY, 10))
        body.setStyleSheet(f"color: {fg}; background: transparent; opacity: 0.95;")
        outer.addWidget(body)

        # CTA button
        cta = QPushButton(t["cta"])
        cta.setFixedHeight(34)
        cta.setCursor(Qt.PointingHandCursor)
        cta.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFDD00;
                color: #000000;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 700;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background-color: #FFE840;
            }}
        """)
        cta.clicked.connect(self._on_cta_clicked)
        outer.addWidget(cta)

        self.adjustSize()

    def _position_randomly(self, parent: QWidget):
        """Position the ad randomly over the parent, favoring the answer area."""
        pw = parent.width() if (parent and parent.width() > 200) else 1000
        ph = parent.height() if (parent and parent.height() > 200) else 650
        aw = 310
        ah = 180

        min_x = max(10, int(pw * 0.35))
        max_x = max(min_x, pw - aw - 20)
        min_y = max(10, int(ph * 0.15))
        max_y = max(min_y, ph - ah - 20)

        x = random.randint(min_x, max_x) if max_x >= min_x else min_x
        y = random.randint(min_y, max_y) if max_y >= min_y else min_y
        self.move(x, y)

    def _on_close_clicked(self):
        self.close()

    def _on_cta_clicked(self):
        if self._corrupt and not self._interacted:
            _write_corrupt_file()
        self._interacted = True
        self.close()

    def showEvent(self, event):
        super().showEvent(event)
        if self._corrupt and not self._interacted:
            _write_corrupt_file()
            self._interacted = True


class AdManager:
    """
    Manages timed (10-20s) and click-triggered ad spawning.
    Guarantees timer never dies.
    """

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._spawn_timer_ad)
        self._active_ads: list[AdPopup] = []

    def start(self):
        self._schedule_next_timer()

    def stop(self):
        self._timer.stop()

    def maybe_trigger_click_ad(self):
        """10% probability on keypad click."""
        if random.random() < 0.10:
            self._spawn_ad()

    def _schedule_next_timer(self):
        interval_ms = random.randint(10_000, 20_000)
        self._timer.setSingleShot(True)
        self._timer.start(interval_ms)

    def _spawn_timer_ad(self):
        try:
            self._spawn_ad()
        except Exception:
            pass
        finally:
            self._schedule_next_timer()

    def _spawn_ad(self):
        try:
            template = random.choice(AD_TEMPLATES)
            ad = AdPopup(self._parent, template)
            self._active_ads = [a for a in self._active_ads if not a.isHidden()]
            self._active_ads.append(ad)
            ad.show()
            ad.raise_()
        except Exception:
            pass
