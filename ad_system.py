# ad_system.py - Hostile popup ad system with dynamic asset scanning
import os
import random
import sys
import pathlib

from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QRect
from PySide6.QtGui import QFont, QColor, QPalette, QCursor, QPixmap, QPainter, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QSizePolicy, QApplication, QGraphicsDropShadowEffect
)
import ui_theme as T

# ── Asset path resolution & dynamic ad image scanning ─────────────────────────
EXCLUDED_SPRITES = {
    "angry robi", "defeated robi", "robi attack symbols",
    "shash1", "slash2", "slash3", "slash4", "slash 5", "player_calc",
    "robi logo circle", "robi logo square", "robi logo", "robi icon"
}


def resolve_asset_dir() -> str:
    """Find the assets directory supporting both local dev and PyInstaller sys._MEIPASS."""
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_dir, "assets"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"),
        os.path.join("assets"),
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.isdir(c):
            return os.path.abspath(c)
    return candidates[0]


_DEFAULT_FALLBACK_TEMPLATES = [
    {
        "headline": "🎉 YOU WON A FREE iPhone 15 Pro!!!",
        "body": "Claim your prize NOW before it expires in 00:03!",
        "cta": "CLAIM FREE PRIZE »",
        "bg": "#FF2222",
        "fg": "#FFFFFF",
        "corrupt_file": False,
        "image": None,
    },
    {
        "headline": "⚠️ Your PC is INFECTED with 47 viruses!",
        "body": "Download our FREE antivirus scanner to remove all threats immediately.",
        "cta": "Download FREE Fix →",
        "bg": "#FF6B00",
        "fg": "#FFFFFF",
        "corrupt_file": True,
        "image": None,
    },
]


def scan_ad_templates() -> list[dict]:
    """
    Scan assets/ for all ad image files (*ad*.png, *ad*.jpg, *ad*.gif, etc.),
    excluding Robi battle sprites and Robi logos. Identifies the corrupt-file variant.
    """
    asset_dir = resolve_asset_dir()
    templates = []

    if not os.path.exists(asset_dir):
        return _DEFAULT_FALLBACK_TEMPLATES

    seen_stems = set()
    for root, _, files in os.walk(asset_dir):
        # Exclude Robi boss assets subfolder
        if "robi assets" in root.lower():
            continue

        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                continue

            stem = os.path.splitext(fname)[0].lower()
            if any(ex in stem for ex in EXCLUDED_SPRITES):
                continue

            # Deduplicate near-identical copies like 'Huss-Ad (1)' vs 'Huss-Ad'
            norm_stem = stem.replace(" (1)", "").replace("_1", "").strip()
            if norm_stem in seen_stems:
                continue
            seen_stems.add(norm_stem)

            full_path = os.path.join(root, fname)

            # Check if this is the corrupt-file variant (antivirus / security alert)
            is_corrupt = any(k in stem for k in ["security", "alert", "virus", "infect", "corrupt"])

            template = {
                "headline": "",
                "body": "",
                "cta": "DOWNLOAD FREE FIX →" if is_corrupt else "",
                "bg": "#1A1A1A",
                "fg": "#FFFFFF",
                "corrupt_file": is_corrupt,
                "image": full_path,
                "lock_in_url": "https://example.com/lock-in" if "huss" in stem else None,
            }
            templates.append(template)

    if not templates:
        return _DEFAULT_FALLBACK_TEMPLATES

    return templates


# Dynamic ad templates loaded from assets/
AD_TEMPLATES = scan_ad_templates()


def get_random_ad_template() -> dict:
    """Return a randomly chosen ad template from the dynamically scanned list."""
    global AD_TEMPLATES
    if not AD_TEMPLATES:
        AD_TEMPLATES = scan_ad_templates()
    return random.choice(AD_TEMPLATES)


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
    """A jarring, intrusive popup ad with a tiny 8px x 8px close button."""

    def __init__(self, parent_widget: QWidget, template: dict, target_area: str = "random"):
        top_parent = parent_widget.window() if parent_widget else None
        super().__init__(top_parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._parent = top_parent
        self._template = template
        self._target_area = target_area
        self._corrupt = template.get("corrupt_file", False)
        self._interacted = False
        self._setup_ui(template)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 210))
        shadow.setOffset(0, 8)
        self.setGraphicsEffect(shadow)
        self._position_randomly(top_parent, target_area)

    # ── Layout ──────────────────────────────────────────────────────────────
    def _setup_ui(self, t: dict):
        self.setObjectName("ad_root")
        self.setFixedWidth(390)
        image_path = t.get("image", None)
        click_url = t.get("lock_in_url", None)

        self.setStyleSheet("""
            #ad_root {
                background-color: #FFFFFF;
                border: 4px solid #EF4444;
                border-radius: 12px;
            }
            QLabel {
                background: transparent;
                color: #1E1E1E;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 12)
        outer.setSpacing(9)

        notice = QLabel("ADVERTISEMENT")
        notice.setAlignment(Qt.AlignCenter)
        notice.setFixedHeight(30)
        notice.setFont(QFont(T.FONT_FAMILY, 12, QFont.Bold))
        notice.setStyleSheet("""
            QLabel {
                background-color: #FDE047;
                color: #7F1D1D;
                border: 1px solid #DC2626;
                border-radius: 5px;
                padding: 3px;
            }
        """)
        outer.addWidget(notice)

        def _make_close_btn() -> QPushButton:
            """Tiny 8px x 8px hostile close button."""
            btn = QPushButton("✕")
            btn.setFixedSize(8, 8)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Close")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #000000;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 1px;
                    font-size: 6px;
                    font-weight: 700;
                    padding: 0px;
                    margin: 0px;
                    line-height: 8px;
                }
                QPushButton:hover {
                    background-color: #EF4444;
                }
            """)
            btn.clicked.connect(self._on_close_clicked)
            return btn

        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                max_width = 362
                max_height = 360
                if pixmap.width() > max_width or pixmap.height() > max_height:
                    pixmap = pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                popup_ref = self
                corrupt_ref = self._corrupt

                class ClickableImageLabel(QLabel):
                    def __init__(self, pix, url, parent=None):
                        super().__init__(parent)
                        self.setPixmap(pix)
                        self.setAlignment(Qt.AlignCenter)
                        self.setStyleSheet("background: transparent; border: none;")
                        self._url = url
                        self.setCursor(Qt.PointingHandCursor)

                    def mousePressEvent(self, event):
                        if event.button() == Qt.LeftButton:
                            if corrupt_ref:
                                _write_corrupt_file()
                            elif self._url:
                                QDesktopServices.openUrl(self._url)
                            popup_ref.close()
                        super().mousePressEvent(event)

                image_container = QWidget()
                image_container.setStyleSheet("background: transparent;")
                grid = QGridLayout(image_container)
                grid.setContentsMargins(0, 0, 0, 0)
                grid.setSpacing(0)

                img_label = ClickableImageLabel(pixmap, click_url)
                grid.addWidget(img_label, 0, 0)

                # Tiny 8px x 8px close button overlaid in top-right corner
                overlay = QWidget()
                overlay.setStyleSheet("background: transparent;")
                ov_lay = QVBoxLayout(overlay)
                ov_lay.setContentsMargins(4, 4, 4, 4)
                ov_lay.setSpacing(0)
                self._close_btn = _make_close_btn()
                ov_lay.addWidget(self._close_btn)
                grid.addWidget(overlay, 0, 0, Qt.AlignTop | Qt.AlignRight)

                outer.addWidget(image_container)

            if t.get("headline"):
                hl = QLabel(t["headline"])
                hl.setWordWrap(True)
                hl.setFont(QFont(T.FONT_FAMILY, 15, QFont.Bold))
                hl.setStyleSheet("color: #1E1E1E; background: transparent;")
                outer.addWidget(hl)
        else:
            # Text-based ad fallback
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.addStretch()
            self._close_btn = _make_close_btn()
            header.addWidget(self._close_btn)
            outer.addLayout(header)

            hl = QLabel(t.get("headline", "Special Announcement"))
            hl.setWordWrap(True)
            hl.setFont(QFont(T.FONT_FAMILY, 15, QFont.Bold))
            hl.setStyleSheet("color: #1E1E1E; background: transparent;")
            outer.addWidget(hl)

            if t.get("body"):
                body = QLabel(t["body"])
                body.setWordWrap(True)
                body.setFont(QFont(T.FONT_FAMILY, 12))
                body.setStyleSheet("color: #5F6368; background: transparent;")
                outer.addWidget(body)

        # CTA button if provided
        if t.get("cta"):
            cta = QPushButton(t["cta"])
            cta.setFixedHeight(42)
            cta.setCursor(Qt.PointingHandCursor)
            cta.setStyleSheet("""
                QPushButton {
                    background-color: #1C7ED6;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 8px;
                    font-size: 15px;
                    font-weight: 700;
                    padding: 0 12px;
                }
                QPushButton:hover {
                    background-color: #1864AB;
                }
            """)
            cta.clicked.connect(self._on_cta_clicked)
            outer.addWidget(cta)

        self.adjustSize()

    def _position_randomly(self, parent: QWidget, target_area: str):
        """Randomize ad placement within a high-impact UI area."""
        pw = parent.width() if (parent and parent.width() > 200) else 1000
        ph = parent.height() if (parent and parent.height() > 200) else 650
        aw = self.width() or 310
        ah = self.height() or 220

        if target_area == "random":
            target_area = random.choice(("calculator", "chatbot")) if pw > 700 else "calculator"

        areas = {
            "calculator": (0.02, 0.42, 0.28, 0.92),
            "chatbot": (0.42, 0.98, 0.42, 0.95),
            "essay": (0.05, 0.95, 0.22, 0.85),
        }
        left, right, top, bottom = areas.get(target_area, areas["calculator"])
        min_x = max(0, int(pw * left))
        max_x = min(pw - aw - 10, int(pw * right) - aw)
        min_y = max(0, int(ph * top))
        max_y = min(ph - ah - 10, int(ph * bottom) - ah)
        if max_x < min_x:
            min_x = max_x = max(0, min(min_x, pw - aw))
        if max_y < min_y:
            min_y = max_y = max(0, min(min_y, ph - ah))

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
    Supports random asset-based ad rotation and battle pausing.
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

    def maybe_trigger_click_ad(self, target_area: str = "calculator", parent_widget: QWidget = None):
        """25% probability on calculator, essay, or chatbot interactions."""
        if self._paused:
            return
        if random.random() < 0.25:
            self._spawn_ad(target_area, parent_widget)

    def _schedule_next_timer(self):
        if self._paused:
            return
        interval_ms = random.randint(5_000, 10_000)
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

    def _spawn_ad(self, target_area: str = "random", parent_widget: QWidget = None):
        if self._paused:
            return
        try:
            template = get_random_ad_template()
            ad = AdPopup(parent_widget or self._parent, template, target_area)
            self._active_ads = [a for a in self._active_ads if not a.isHidden()]
            self._active_ads.append(ad)
            ad.show()
            ad.raise_()
        except Exception:
            pass
