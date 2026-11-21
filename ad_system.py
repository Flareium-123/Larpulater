# ad_system.py - Hostile popup ad system
import os
import random
import sys
import pathlib

from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QRect
from PySide6.QtGui import QFont, QColor, QPalette, QCursor, QPixmap, QPainter, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QSizePolicy, QApplication
)
import ui_theme as T

# ── Ad copy templates ─────────────────────────────────────────────────────────
AD_TEMPLATES = [
    {
        "headline": "YOU WON A FREE iPhone 15 Pro!!!",
        "body": "Claim your prize NOW before it expires in 00:03!",
        "cta": "CLAIM FREE PRIZE »",
        "bg": "#FF2222",
        "fg": "#FFFFFF",
        "corrupt_file": False,
    },
    {
        "headline": "Your PC is INFECTED with 47 viruses!",
        "body": "Download our FREE antivirus scanner to remove all threats immediately.",
        "cta": "Download FREE Fix →",
        "bg": "#FF6B00",
        "fg": "#FFFFFF",
        "corrupt_file": True,   # triggers the 0-KB readme download
    },
    {
        "headline": "MATH GENIUS DETECTED!",
        "body": "Local educators HATE this one trick. Solve any equation instantly!",
        "cta": "Learn THE SECRET →",
        "bg": "#7B00FF",
        "fg": "#FFFFFF",
        "corrupt_file": False,
    },
    {
        "headline": "Make $8,500/week from home!",
        "body": "Thousands of calculater users earn passive income. Zero effort required!",
        "cta": "START EARNING NOW »",
        "bg": "#006600",
        "fg": "#FFFF00",
        "corrupt_file": False,
    },
    {
        "headline": "HOT SINGLES want to do your math!",
        "body": "Local mathematicians in your area are waiting to explain their solutions.",
        "cta": "MEET THEM NOW »",
        "bg": "#CC0055",
        "fg": "#FFFFFF",
        "corrupt_file": False,
    },
    {
        "headline": "LIMITED TIME: Calculater PRO UNLOCKED",
        "body": "Someone nearby just unlocked PRO access for FREE. Grab your copy before it's gone!",
        "cta": "Get PRO FREE !!!",
        "bg": "#0033AA",
        "fg": "#FFD700",
        "corrupt_file": False,
    },
    {
        "headline": "",
        "body": "",
        "cta": "",
        "bg": "#1A1A1A",
        "fg": "#FFFFFF",
        "corrupt_file": False,
        "image": "assets/Huss-Ad.jpg",
        "register_text": "REGISTER NOW",
        "lock_in_url": "https://example.com/lock-in",
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
        self.setObjectName("ad_root")
        self.setFixedWidth(310)
        image_path = t.get("image", None)
        click_url = t.get("lock_in_url", None)

        # Desmos-inspired clean card: white surface, soft border, no yellow outline
        self.setStyleSheet("""
            #ad_root {
                background-color: #FFFFFF;
                border: 1px solid #DADCE0;
                border-radius: 12px;
            }
            QLabel {
                background: transparent;
                color: #1E1E1E;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 14)
        outer.setSpacing(10)

        def _make_close_btn(circle: bool) -> QPushButton:
            btn = QPushButton("✕")
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Close")
            if circle:
                # Black circular close button for image ads
                btn.setStyleSheet("""
                    QPushButton {
                        background: #000000;
                        color: #FFFFFF;
                        border: none;
                        border-radius: 12px;
                        font-size: 12px;
                        font-weight: 600;
                    }
                    QPushButton:hover {
                        background: #333333;
                    }
                    QPushButton:pressed {
                        background: #555555;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #5F6368;
                        border: none;
                        border-radius: 12px;
                        font-size: 14px;
                        font-weight: 400;
                    }
                    QPushButton:hover {
                        background: #F1F3F4;
                        color: #202124;
                    }
                    QPushButton:pressed {
                        background: #E8EAED;
                    }
                """)
            btn.clicked.connect(self._on_close_clicked)
            return btn

        if image_path:
            # Image-based ad — image itself is clickable, X button overlaid on top-right
            import os
            full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), image_path)
            if os.path.exists(full_path):
                pixmap = QPixmap(full_path)
                if not pixmap.isNull():
                    max_width = 282
                    if pixmap.width() > max_width:
                        pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)

                    class ClickableImageLabel(QLabel):
                        def __init__(self, pixmap, url, parent=None):
                            super().__init__(parent)
                            self.setPixmap(pixmap)
                            self.setAlignment(Qt.AlignCenter)
                            self.setStyleSheet("background: transparent; border: none;")
                            self._url = url
                            if url:
                                self.setCursor(Qt.PointingHandCursor)

                        def mousePressEvent(self, event):
                            if event.button() == Qt.LeftButton and self._url:
                                QDesktopServices.openUrl(self._url)
                            super().mousePressEvent(event)

                    # Overlay container: image fills the cell, close button floats top-right
                    image_container = QWidget()
                    image_container.setStyleSheet("background: transparent;")
                    grid = QGridLayout(image_container)
                    grid.setContentsMargins(0, 0, 0, 0)
                    grid.setSpacing(0)

                    img_label = ClickableImageLabel(pixmap, click_url)
                    grid.addWidget(img_label, 0, 0)

                    # Wrapper gives the black circle a small inset from the image edge
                    overlay = QWidget()
                    overlay.setStyleSheet("background: transparent;")
                    ov_lay = QVBoxLayout(overlay)
                    ov_lay.setContentsMargins(8, 8, 8, 8)
                    self._close_btn = _make_close_btn(circle=True)
                    ov_lay.addWidget(self._close_btn)
                    grid.addWidget(overlay, 0, 0, Qt.AlignTop | Qt.AlignRight)

                    outer.addWidget(image_container)

            if t.get("headline"):
                hl = QLabel(t["headline"])
                hl.setWordWrap(True)
                hl.setFont(QFont(T.FONT_FAMILY, 13, QFont.Bold))
                hl.setStyleSheet("color: #1E1E1E; background: transparent;")
                outer.addWidget(hl)
        else:
            # Text-based ad — close button in a header row
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.addStretch()
            self._close_btn = _make_close_btn(circle=False)
            header.addWidget(self._close_btn)
            outer.addLayout(header)

            hl = QLabel(t["headline"])
            hl.setWordWrap(True)
            hl.setFont(QFont(T.FONT_FAMILY, 13, QFont.Bold))
            hl.setStyleSheet("color: #1E1E1E; background: transparent;")
            outer.addWidget(hl)

            body = QLabel(t["body"])
            body.setWordWrap(True)
            body.setFont(QFont(T.FONT_FAMILY, 10))
            body.setStyleSheet("color: #5F6368; background: transparent;")
            outer.addWidget(body)

        # CTA button — Desmos blue (hidden when no CTA text)
        if t.get("cta"):
            cta = QPushButton(t["cta"])
            cta.setFixedHeight(36)
            cta.setCursor(Qt.PointingHandCursor)
            cta.setStyleSheet("""
                QPushButton {
                    background-color: #1C7ED6;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: 600;
                    padding: 0 12px;
                }
                QPushButton:hover {
                    background-color: #1864AB;
                }
                QPushButton:pressed {
                    background-color: #155A99;
                }
            """)
            cta.clicked.connect(self._on_cta_clicked)
            outer.addWidget(cta)

        self.adjustSize()

    def _position_randomly(self, parent: QWidget):
        """Position the ad randomly over the parent, favoring the answer area."""
        pw = parent.width() if (parent and parent.width() > 200) else 1000
        ph = parent.height() if (parent and parent.height() > 200) else 650
        aw = self.width() or 310
        ah = self.height() or 180

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
    Guarantees timer never dies. Supports pausing during boss battles.
    """

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._spawn_timer_ad)
        self._active_ads: list[AdPopup] = []
        self._paused = False

    def start(self):
        self._schedule_next_timer()

    def stop(self):
        self._timer.stop()

    def pause(self):
        """Suspend all ad timers and hide active overlays for battle mode."""
        self._paused = True
        self._timer.stop()
        for a in self._active_ads:
            try:
                if not a.isHidden():
                    a.hide()
            except Exception:
                pass

    def resume(self):
        """Resume normal ad spawning behavior."""
        self._paused = False
        self._schedule_next_timer()

    def is_paused(self) -> bool:
        return self._paused

    def maybe_trigger_click_ad(self):
        """10% probability on keypad click."""
        if self._paused:
            return
        if random.random() < 0.10:
            self._spawn_ad()

    def _schedule_next_timer(self):
        if self._paused:
            return
        interval_ms = random.randint(10_000, 20_000)
        self._timer.setSingleShot(True)
        self._timer.start(interval_ms)

    def _spawn_timer_ad(self):
        if self._paused:
            return
        try:
            self._spawn_ad()
        except Exception:
            pass
        finally:
            if not self._paused:
                self._schedule_next_timer()

    def _spawn_ad(self):
        if self._paused:
            return
        try:
            # TEMPORARY: Force Huss ad (last template in list)
            template = AD_TEMPLATES[-1]
            ad = AdPopup(self._parent, template)
            self._active_ads = [a for a in self._active_ads if not a.isHidden()]
            self._active_ads.append(ad)
            ad.show()
            ad.raise_()
        except Exception:
            pass
