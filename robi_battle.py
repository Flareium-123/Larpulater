# robi_battle.py - Undertale-style boss fight: "Battle Robi"
import os
import sys
import math
import random
import threading
from typing import List, Dict, Tuple, Optional

from PySide6.QtCore import Qt, QTimer, QRect, QRectF, QPointF, Signal, QObject
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPainterPath,
    QPolygonF, QKeySequence, QLinearGradient, QPixmap, QImage
)
from PySide6.QtWidgets import QWidget, QApplication

# ── Asset path resolution (handles PyInstaller sys._MEIPASS & dev paths) ───────
def get_asset_path(filename: str) -> str:
    """Resolve asset paths supporting sys._MEIPASS for PyInstaller and local dev."""
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_dir, "assets", filename),
        os.path.join(base_dir, "assets", "ROBI ASSETS", filename),
        os.path.join("assets", filename),
        os.path.join("assets", "ROBI ASSETS", filename),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


# ── Sound system (8-bit synthetic sound via winsound on Windows) ──────────────
try:
    import winsound
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False


def play_8bit_sound(sound_type: str):
    """Play retro 8-bit sound effects asynchronously without blocking UI."""
    if not _HAS_WINSOUND:
        return

    def _worker():
        try:
            if sound_type == "encounter":
                winsound.Beep(850, 60)
                winsound.Beep(1200, 60)
                winsound.Beep(1600, 100)
            elif sound_type == "slash":
                winsound.Beep(1800, 40)
                winsound.Beep(900, 60)
            elif sound_type == "hurt":
                winsound.Beep(240, 80)
            elif sound_type == "hit_robi":
                winsound.Beep(450, 70)
                winsound.Beep(320, 90)
            elif sound_type == "shatter":
                winsound.Beep(800, 40)
                winsound.Beep(500, 60)
                winsound.Beep(250, 120)
            elif sound_type == "select":
                winsound.Beep(1100, 50)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


ROBI_TAUNTS = [
    "Did you really think that would hurt? My CPU runs hotter than your attack.",
    "You're still failing geometry, sweetie. Try carrying the one.",
    "Is that your best calculation? My error margin is zero!",
    "WARNING: Critical chassis damage! I'm STILL not grading your essay!",
    "FATAL SYSTEM ERROR: Memory dump initiated... don't celebrate yet!",
]


class Projectile:
    """A bullet-hell math projectile firing sliced colored symbols or procedural fallbacks."""
    def __init__(self, x: float, y: float, vx: float, vy: float, pixmap: Optional[QPixmap] = None, symbol: str = "*", size: float = 24.0):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.pixmap = pixmap
        self.symbol = symbol
        self.size = size
        self.rot = random.uniform(0, 360)
        self.vrot = random.uniform(-5, 5)

    def update(self, dt: float):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.rot += self.vrot

    def get_hitbox_radius(self) -> float:
        return self.size * 0.40


class ShatterShard:
    """A broken shard for the player death animation."""
    def __init__(self, x: float, y: float, vx: float, vy: float, poly: QPolygonF):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.poly = poly
        self.rot = 0.0
        self.vrot = random.uniform(-10, 10)

    def update(self, dt: float):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 450.0 * dt
        self.rot += self.vrot


class RobiBattleOverlay(QWidget):
    """
    Undertale-style battle screen canvas running at 60 FPS.
    Signals:
        battle_won()   - Robi defeated (5 hits)
        battle_lost()  - Player HP reached 0
        battle_ended() - Battle screen closed
    """
    battle_won   = Signal()
    battle_lost  = Signal()
    battle_ended = Signal()

    STATE_ENCOUNTER   = "ENCOUNTER"
    STATE_PLAYER_TURN = "PLAYER_TURN"
    STATE_SLASH       = "SLASH"
    STATE_DIALOGUE    = "DIALOGUE"
    STATE_DODGE       = "DODGE"
    STATE_VICTORY     = "VICTORY"
    STATE_GAME_OVER   = "GAME_OVER"

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        # Game statistics
        self.max_player_hp = 20
        self.player_hp     = 20
        self.max_robi_hp   = 100
        self.robi_hp       = 100
        self.hits_landed   = 0

        # Player position & movement
        self.px = 0.0
        self.py = 0.0
        self.player_speed = 195.0
        self.calc_w = 22.0
        self.calc_h = 28.0
        self.iframe_time = 0.0

        # Keys pressed
        self.keys = {
            Qt.Key_W: False, Qt.Key_Up: False,
            Qt.Key_S: False, Qt.Key_Down: False,
            Qt.Key_A: False, Qt.Key_Left: False,
            Qt.Key_D: False, Qt.Key_Right: False,
        }

        # Arena box geometry (smoothly interpolated)
        self.box_cur_rect = QRectF(250, 340, 460, 160)
        self.box_target_rect = QRectF(250, 340, 460, 160)

        # Attack wave
        self.projectiles: List[Projectile] = []
        self.wave_timer = 0.0
        self.wave_duration = 7.0
        self.wave_spawn_acc = 0.0

        # State & timers
        self.state = self.STATE_ENCOUNTER
        self.state_time = 0.0
        self.screen_shake = 0.0
        self.shake_offset = QPointF(0, 0)
        self.damage_popup = None
        self.dialogue_text = ""

        # 5-frame slash animation tracking
        self.slash_frame_idx = 0
        self.slash_timer = 0.0
        self.slash_frame_duration = 0.075  # ~0.375s total 5-frame animation

        # Encounter transition
        self.flash_white = False
        self.shatter_cracks: List[List[QPointF]] = []

        # Death shards
        self.death_shards: List[ShatterShard] = []

        # Load all sprite assets
        self._load_sprites()

        # 60 FPS game loop timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._game_loop)
        self.timer.start(16)

        self._generate_shatter_cracks()
        play_8bit_sound("encounter")

    # ── Sprite loading & sheet slicing ────────────────────────────────────────
    def _load_sprites(self):
        """Load and crop all required sprite assets from assets/."""
        # 1. Boss Poses
        p_angry = get_asset_path("Angry Robi.png")
        self.pix_angry_robi = QPixmap(p_angry) if os.path.exists(p_angry) else None

        p_defeated = get_asset_path("Defeated Robi.png")
        self.pix_defeated_robi = QPixmap(p_defeated) if os.path.exists(p_defeated) else None

        # 2. Player Calc Sprite (or procedural fallback)
        p_calc = get_asset_path("player_calc.png")
        self.pix_player_calc = QPixmap(p_calc) if os.path.exists(p_calc) else None

        # 3. 5-Frame Slash Animation Sequence
        slash_names = ["SHASH1.png", "SLASH2.png", "SLASH3.png", "SLASH4.png", "SLASH 5.png"]
        self.slash_frames: List[QPixmap] = []
        for name in slash_names:
            p = get_asset_path(name)
            if os.path.exists(p):
                self.slash_frames.append(QPixmap(p))

        # 4. Sliced Colored Attack Symbols: Blue -, Yellow +, Purple ÷, Red ×
        p_attack_sheet = get_asset_path("Robi Attack Symbols.png")
        self.symbol_pixmaps: List[QPixmap] = []
        if os.path.exists(p_attack_sheet):
            sheet = QPixmap(p_attack_sheet)
            # Precise crop rectangles for the 4 math symbols in the sheet
            regions = [
                QRect(604, 506, 418, 452),    # Blue -
                QRect(1024, 522, 346, 498),   # Yellow +
                QRect(632, 1044, 384, 440),   # Purple ÷
                QRect(1116, 1060, 396, 418),  # Red ×
            ]
            for r in regions:
                cropped = sheet.copy(r)
                if not cropped.isNull():
                    self.symbol_pixmaps.append(cropped)

    # ── Geometry initialization ───────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        bw = min(540.0, w * 0.75)
        bh = 150.0
        bx = (w - bw) / 2.0
        by = h - bh - 60.0
        self.box_target_rect = QRectF(bx, by, bw, bh)
        self.box_cur_rect = QRectF(bx, by, bw, bh)
        self.px = self.box_cur_rect.center().x()
        self.py = self.box_cur_rect.center().y()

    def _generate_shatter_cracks(self):
        self.shatter_cracks = []
        cx = 500
        cy = 350
        for _ in range(12):
            pts = [QPointF(cx, cy)]
            curr = QPointF(cx, cy)
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(250, 500)
            steps = random.randint(4, 7)
            for s in range(steps):
                step_dist = dist / steps
                angle += random.uniform(-0.35, 0.35)
                curr = QPointF(
                    curr.x() + math.cos(angle) * step_dist,
                    curr.y() + math.sin(angle) * step_dist
                )
                pts.append(QPointF(curr.x(), curr.y()))
            self.shatter_cracks.append(pts)

    # ── 60 FPS Main Loop ──────────────────────────────────────────────────────
    def _game_loop(self):
        dt = 0.016
        self.state_time += dt

        # Screen shake dampening
        if self.screen_shake > 0:
            self.screen_shake = max(0.0, self.screen_shake - dt * 25.0)
            self.shake_offset = QPointF(
                random.uniform(-self.screen_shake, self.screen_shake),
                random.uniform(-self.screen_shake, self.screen_shake)
            )
        else:
            self.shake_offset = QPointF(0, 0)

        # Smooth arena box interpolation
        cur = self.box_cur_rect
        tgt = self.box_target_rect
        speed = 10.0 * dt
        new_x = cur.x() + (tgt.x() - cur.x()) * speed
        new_y = cur.y() + (tgt.y() - cur.y()) * speed
        new_w = cur.width() + (tgt.width() - cur.width()) * speed
        new_h = cur.height() + (tgt.height() - cur.height()) * speed
        self.box_cur_rect = QRectF(new_x, new_y, new_w, new_h)

        # I-frame cooldown
        if self.iframe_time > 0:
            self.iframe_time = max(0.0, self.iframe_time - dt)

        # State updates
        if self.state == self.STATE_ENCOUNTER:
            self._update_encounter(dt)
        elif self.state == self.STATE_PLAYER_TURN:
            self._update_player_turn(dt)
        elif self.state == self.STATE_SLASH:
            self._update_slash(dt)
        elif self.state == self.STATE_DIALOGUE:
            self._update_dialogue(dt)
        elif self.state == self.STATE_DODGE:
            self._update_dodge(dt)
        elif self.state == self.STATE_VICTORY:
            self._update_victory(dt)
        elif self.state == self.STATE_GAME_OVER:
            self._update_game_over(dt)

        self.update()

    # ── State Handlers ────────────────────────────────────────────────────────
    def _update_encounter(self, dt: float):
        cycle = int(self.state_time / 0.12)
        if cycle < 6:
            self.flash_white = (cycle % 2 == 1)
        else:
            self.flash_white = False
            self.state = self.STATE_PLAYER_TURN
            self.state_time = 0.0
            self._set_menu_box()

    def _set_menu_box(self):
        w = self.width()
        h = self.height()
        bw = min(540.0, w * 0.75)
        bh = 150.0
        bx = (w - bw) / 2.0
        by = h - bh - 60.0
        self.box_target_rect = QRectF(bx, by, bw, bh)

    def _set_dodge_box(self):
        w = self.width()
        h = self.height()
        bw = 290.0
        bh = 190.0
        bx = (w - bw) / 2.0
        by = h - bh - 70.0
        self.box_target_rect = QRectF(bx, by, bw, bh)
        self.px = self.box_target_rect.center().x()
        self.py = self.box_target_rect.center().y()

    def _update_player_turn(self, dt: float):
        pass

    def trigger_fight_action(self):
        """User pressed [ FIGHT ] (Space / Enter / Click)."""
        if self.state != self.STATE_PLAYER_TURN:
            return
        self.state = self.STATE_SLASH
        self.state_time = 0.0
        self.slash_frame_idx = 0
        self.slash_timer = 0.0
        play_8bit_sound("slash")

    def _update_slash(self, dt: float):
        """Step through the 5-frame slash sequence: SHASH1 -> SLASH 5."""
        self.slash_timer += dt
        if self.slash_timer >= self.slash_frame_duration:
            self.slash_timer = 0.0
            self.slash_frame_idx += 1

        total_frames = len(self.slash_frames) if self.slash_frames else 5
        if self.slash_frame_idx >= total_frames:
            # Landing hit!
            self.hits_landed += 1
            self.robi_hp = max(0, self.robi_hp - 20)
            self.screen_shake = 10.0
            self.damage_popup = ("-20", 1.2, self.width() / 2.0, self.height() * 0.22)
            play_8bit_sound("hit_robi")

            if self.robi_hp <= 0:
                # 5th hit lands: Robi reaches 0 HP, swaps to Defeated Robi
                self.state = self.STATE_VICTORY
                self.state_time = 0.0
            else:
                self.state = self.STATE_DIALOGUE
                self.state_time = 0.0
                idx = min(self.hits_landed - 1, len(ROBI_TAUNTS) - 1)
                self.dialogue_text = ROBI_TAUNTS[idx]

    def _update_dialogue(self, dt: float):
        if self.state_time >= 1.6:
            self.state = self.STATE_DODGE
            self.state_time = 0.0
            self.wave_timer = 0.0
            self.wave_spawn_acc = 0.0
            self.projectiles.clear()
            self._set_dodge_box()

    def _update_dodge(self, dt: float):
        self.wave_timer += dt

        # Player movement inside arena
        dx = 0.0
        dy = 0.0
        if self.keys[Qt.Key_W] or self.keys[Qt.Key_Up]:
            dy -= 1.0
        if self.keys[Qt.Key_S] or self.keys[Qt.Key_Down]:
            dy += 1.0
        if self.keys[Qt.Key_A] or self.keys[Qt.Key_Left]:
            dx -= 1.0
        if self.keys[Qt.Key_D] or self.keys[Qt.Key_Right]:
            dx += 1.0

        if dx != 0.0 and dy != 0.0:
            dx *= 0.7071
            dy *= 0.7071

        self.px += dx * self.player_speed * dt
        self.py += dy * self.player_speed * dt

        # Clamp player inside arena walls
        box = self.box_cur_rect
        hw = self.calc_w / 2.0 + 4
        hh = self.calc_h / 2.0 + 4
        self.px = max(box.left() + hw, min(box.right() - hw, self.px))
        self.py = max(box.top() + hh, min(box.bottom() - hh, self.py))

        # Spawn projectile waves (7 seconds duration)
        self.wave_spawn_acc += dt
        spawn_rate = 0.28 - (self.hits_landed * 0.03)
        if self.wave_spawn_acc >= spawn_rate:
            self.wave_spawn_acc = 0.0
            self._spawn_wave_projectile()

        # Update projectiles and check collisions
        hit_radius = 8.5
        for p in self.projectiles:
            p.update(dt)

            if self.iframe_time <= 0:
                dist = math.hypot(p.x - self.px, p.y - self.py)
                if dist < (hit_radius + p.get_hitbox_radius()):
                    # Flat 2 damage per collision & 0.75s i-frames
                    self.player_hp = max(0, self.player_hp - 2)
                    self.iframe_time = 0.75
                    self.screen_shake = 6.0
                    play_8bit_sound("hurt")
                    if self.player_hp <= 0:
                        self._trigger_game_over()
                        return

        # Prune out-of-bounds projectiles
        self.projectiles = [
            p for p in self.projectiles
            if (box.left() - 70 <= p.x <= box.right() + 70 and
                box.top() - 70 <= p.y <= box.bottom() + 70)
        ]

        # Wave complete after 7 seconds
        if self.wave_timer >= self.wave_duration:
            self.projectiles.clear()
            self.state = self.STATE_PLAYER_TURN
            self.state_time = 0.0
            self._set_menu_box()

    def _spawn_wave_projectile(self):
        """Spawn sliced colored symbol projectile (blue -, yellow +, purple ÷, red ×)."""
        box = self.box_cur_rect
        pix = random.choice(self.symbol_pixmaps) if self.symbol_pixmaps else None
        sym = random.choice(["+", "-", "×", "÷", "√", "π"])
        pattern = random.randint(0, 2)

        if pattern == 0:
            # Fall downward
            x = random.uniform(box.left() + 15, box.right() - 15)
            y = box.top() - 12
            vy = random.uniform(90, 140)
            vx = random.uniform(-20, 20)
            self.projectiles.append(Projectile(x, y, vx, vy, pix, sym, 26.0))
        elif pattern == 1:
            # Sweep left to right
            x = box.left() - 12
            y = random.uniform(box.top() + 15, box.bottom() - 15)
            vx = random.uniform(85, 130)
            vy = random.uniform(-15, 15)
            self.projectiles.append(Projectile(x, y, vx, vy, pix, sym, 24.0))
        else:
            # Sweep right to left
            x = box.right() + 12
            y = random.uniform(box.top() + 15, box.bottom() - 15)
            vx = -random.uniform(85, 130)
            vy = random.uniform(-15, 15)
            self.projectiles.append(Projectile(x, y, vx, vy, pix, sym, 24.0))

    def _trigger_game_over(self):
        self.state = self.STATE_GAME_OVER
        self.state_time = 0.0
        play_8bit_sound("shatter")

        # Split/crack-in-half shatter animation on calculator sprite
        self.death_shards.clear()
        hw = self.calc_w / 2.0
        hh = self.calc_h / 2.0

        p1 = QPolygonF([QPointF(-hw, -hh), QPointF(0, -hh), QPointF(-4, 0), QPointF(-hw, 0)])
        self.death_shards.append(ShatterShard(self.px, self.py, -120, -180, p1))

        p2 = QPolygonF([QPointF(0, -hh), QPointF(hw, -hh), QPointF(hw, 0), QPointF(4, 0)])
        self.death_shards.append(ShatterShard(self.px, self.py, 130, -210, p2))

        p3 = QPolygonF([QPointF(-hw, 0), QPointF(-2, 0), QPointF(0, hh), QPointF(-hw, hh)])
        self.death_shards.append(ShatterShard(self.px, self.py, -90, -110, p3))

        p4 = QPolygonF([QPointF(2, 0), QPointF(hw, 0), QPointF(hw, hh), QPointF(0, hh)])
        self.death_shards.append(ShatterShard(self.px, self.py, 110, -130, p4))

    def _update_game_over(self, dt: float):
        for s in self.death_shards:
            s.update(dt)

        if self.state_time >= 2.4:
            self.timer.stop()
            self.battle_lost.emit()
            self.battle_ended.emit()
            self.close()

    def _update_victory(self, dt: float):
        if self.state_time >= 2.2:
            self.timer.stop()
            self.battle_won.emit()
            self.battle_ended.emit()
            self.close()

    # ── Key & Mouse Input ─────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k = event.key()
        if k in self.keys:
            self.keys[k] = True

        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Z):
            if self.state == self.STATE_PLAYER_TURN:
                play_8bit_sound("select")
                self.trigger_fight_action()
        elif k == Qt.Key_Escape:
            self.timer.stop()
            self.battle_ended.emit()
            self.close()

    def keyReleaseEvent(self, event):
        k = event.key()
        if k in self.keys:
            self.keys[k] = False

    def mousePressEvent(self, event):
        if self.state == self.STATE_PLAYER_TURN:
            btn_rect = self._get_fight_button_rect()
            if btn_rect.contains(event.position()):
                play_8bit_sound("select")
                self.trigger_fight_action()

    # ── Rendering (QPainter 60 FPS) ───────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        painter.translate(self.shake_offset)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        if self.state == self.STATE_ENCOUNTER:
            self._draw_encounter_shatter(painter)
            return

        # 1. Robi Boss (Angry Robi or Defeated Robi)
        self._draw_robi_boss(painter)

        # 2. Mid-battle Speech Bubble
        if self.state == self.STATE_DIALOGUE:
            self._draw_speech_bubble(painter)

        # 3. Undertale White Bullet Box
        self._draw_battle_box(painter)

        # 4. Turn-specific content
        if self.state == self.STATE_PLAYER_TURN:
            self._draw_player_menu(painter)
        elif self.state == self.STATE_DODGE:
            self._draw_dodge_turn(painter)
        elif self.state == self.STATE_SLASH:
            self._draw_slash(painter)
        elif self.state == self.STATE_GAME_OVER:
            self._draw_death_shards(painter)

        # 5. Bottom Player HUD Bar
        self._draw_hud(painter)

        # 6. Damage Popup
        if self.damage_popup:
            self._draw_damage_popup(painter)

        # 7. Victory Text
        if self.state == self.STATE_VICTORY:
            self._draw_victory_text(painter)

    # ── Drawing Details ───────────────────────────────────────────────────────
    def _draw_encounter_shatter(self, painter: QPainter):
        if self.flash_white:
            painter.fillRect(self.rect(), QColor(255, 255, 255))
            return

        painter.fillRect(self.rect(), QColor(10, 15, 25))
        pen = QPen(QColor(220, 240, 255, 200), 2.5)
        painter.setPen(pen)

        for crack in self.shatter_cracks:
            for i in range(len(crack) - 1):
                painter.drawLine(crack[i], crack[i + 1])

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, "⚔️ ROBI ENCOUNTER ⚔️")

    def _draw_robi_boss(self, painter: QPainter):
        """Render Angry Robi.png throughout fight, or Defeated Robi.png fading to 0% at victory."""
        cx = self.width() / 2.0
        cy = self.height() * 0.22
        w = 140.0
        h = 130.0
        rx = cx - w / 2.0
        ry = cy - h / 2.0

        hp_ratio = self.robi_hp / float(self.max_robi_hp)
        if self.state == self.STATE_VICTORY:
            # Fades to 0% opacity upon victory
            alpha = max(0.0, 1.0 - (self.state_time / 1.8))
        else:
            # Opacity progressively drops across 5 hits (100 -> 80 -> 60 -> 40 -> 20)
            alpha = max(0.35, 0.35 + 0.65 * hp_ratio)

        painter.setOpacity(alpha)

        # Active Boss Pose vs Defeated Boss Pose
        if self.state == self.STATE_VICTORY and self.pix_defeated_robi:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_defeated_robi)
        elif self.pix_angry_robi:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_angry_robi)
        else:
            # Procedural fallback
            painter.setPen(QPen(QColor(255, 255, 255), 2.5))
            painter.setBrush(QColor(30, 58, 138))
            painter.drawRoundedRect(QRectF(rx, ry, w, h), 16, 16)
            painter.setBrush(QColor(15, 23, 42))
            painter.drawRoundedRect(QRectF(rx + 15, ry + 22, w - 30, 32), 6, 6)
            painter.setBrush(QColor(34, 211, 238))
            painter.drawRect(QRectF(rx + 25, ry + 32, 25, 12))
            painter.drawRect(QRectF(rx + w - 50, ry + 32, 25, 12))

        painter.setOpacity(1.0)

        # Robi Boss HP bar
        bar_w = 180.0
        bar_h = 10.0
        bar_x = cx - bar_w / 2.0
        bar_y = cy + h / 2.0 + 14.0

        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(QColor(30, 30, 30))
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        fill_w = bar_w * hp_ratio
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(37, 99, 235))
        painter.drawRect(QRectF(bar_x + 1, bar_y + 1, fill_w, bar_h - 2))

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(
            QRectF(bar_x, bar_y - 18, bar_w, 16),
            Qt.AlignCenter,
            f"ROBI HP  {self.robi_hp} / {self.max_robi_hp}"
        )

    def _draw_speech_bubble(self, painter: QPainter):
        cx = self.width() / 2.0
        cy = self.height() * 0.20
        bw = 210.0
        bh = 74.0
        bx = cx + 85.0
        by = cy - 30.0

        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 10, 10)

        tri = QPolygonF([QPointF(bx, by + 25), QPointF(bx - 14, by + 30), QPointF(bx, by + 38)])
        painter.drawPolygon(tri)

        painter.setPen(QColor(0, 0, 0))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(bx + 10, by + 8, bw - 20, bh - 16), Qt.TextWordWrap | Qt.AlignVCenter, self.dialogue_text)

    def _draw_battle_box(self, painter: QPainter):
        box = self.box_cur_rect
        painter.setPen(QPen(QColor(255, 255, 255), 4.0, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRect(box)

    def _get_fight_button_rect(self) -> QRectF:
        box = self.box_cur_rect
        btn_w = 150.0
        btn_h = 42.0
        btn_x = box.center().x() - btn_w / 2.0
        btn_y = box.bottom() - btn_h - 20.0
        return QRectF(btn_x, btn_y, btn_w, btn_h)

    def _draw_player_menu(self, painter: QPainter):
        box = self.box_cur_rect
        btn_rect = self._get_fight_button_rect()

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 14))
        painter.drawText(
            QRectF(box.left() + 24, box.top() + 24, box.width() - 48, 40),
            Qt.AlignLeft,
            "* Robi glares down at your math calculations."
        )

        # [ FIGHT ] Button
        painter.setPen(QPen(QColor(249, 115, 22), 2.5))
        painter.setBrush(QColor(20, 20, 20))
        painter.drawRoundedRect(btn_rect, 6, 6)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(249, 115, 22))
        soul_cx = btn_rect.left() + 24
        soul_cy = btn_rect.center().y()
        painter.drawEllipse(QPointF(soul_cx, soul_cy), 5, 5)

        painter.setPen(QColor(249, 115, 22))
        painter.setFont(QFont("Consolas", 16, QFont.Bold))
        painter.drawText(btn_rect, Qt.AlignCenter, "  [ FIGHT ]")

        painter.setPen(QColor(160, 160, 160))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            QRectF(box.left(), box.bottom() - 18, box.width(), 16),
            Qt.AlignCenter,
            "Press SPACE / ENTER / CLICK to Strike Robi (-20 HP)"
        )

    def _draw_slash(self, painter: QPainter):
        """Render 5-frame slash sequence (SHASH1.png -> SLASH 5.png) over Robi's sprite."""
        cx = self.width() / 2.0
        cy = self.height() * 0.22
        w = 120.0
        h = 120.0
        rx = cx - w / 2.0
        ry = cy - h / 2.0

        if self.slash_frames and self.slash_frame_idx < len(self.slash_frames):
            frame = self.slash_frames[self.slash_frame_idx]
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), frame)
        else:
            # Procedural slash fallback
            painter.setPen(QPen(QColor(255, 255, 255), 5.0))
            path = QPainterPath()
            path.moveTo(cx - 50.0, cy - 40.0)
            path.quadTo(cx - 10.0, cy + 20.0, cx + 50.0, cy + 40.0)
            painter.strokePath(path, QPen(QColor(255, 255, 255), 5.0))

    def _draw_dodge_turn(self, painter: QPainter):
        # 1. Player Calculator Sprite (or procedural fallback)
        is_flashing = (self.iframe_time > 0 and int(self.state_time * 20) % 2 == 0)
        if not is_flashing:
            self._draw_player_calc(painter, self.px, self.py)

        # 2. Sliced Math Symbol Projectiles
        for p in self.projectiles:
            self._draw_projectile(painter, p)

        # 3. Wave Timer Countdown
        time_left = max(0.0, self.wave_duration - self.wave_timer)
        box = self.box_cur_rect
        painter.setPen(QColor(34, 211, 238))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(
            QRectF(box.left(), box.top() - 20, box.width(), 16),
            Qt.AlignRight,
            f"DODGE: {time_left:.1f}s"
        )

    def _draw_player_calc(self, painter: QPainter, x: float, y: float):
        w = self.calc_w
        h = self.calc_h
        rx = x - w / 2.0
        ry = y - h / 2.0

        if self.pix_player_calc:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_player_calc)
            return

        # Procedural mini-calculator fallback
        painter.setPen(QPen(QColor(34, 211, 238), 2.0))
        painter.setBrush(QColor(15, 23, 42))
        painter.drawRoundedRect(QRectF(rx, ry, w, h), 4, 4)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(219, 234, 254))
        painter.drawRect(QRectF(rx + 3, ry + 3, w - 6, 6))

        painter.setBrush(QColor(59, 130, 246))
        for r in range(2):
            for c in range(3):
                bx = rx + 4 + (c * 4.5)
                by = ry + 12 + (r * 4.5)
                painter.drawRect(QRectF(bx, by, 3, 3))

    def _draw_projectile(self, painter: QPainter, p: Projectile):
        """Draw sliced colored math symbol (or fallback text)."""
        painter.save()
        painter.translate(p.x, p.y)
        painter.rotate(p.rot)

        if p.pixmap:
            sz = int(p.size)
            painter.drawPixmap(-sz // 2, -sz // 2, sz, sz, p.pixmap)
        else:
            painter.setPen(QPen(QColor(255, 255, 255), 2.0))
            painter.setFont(QFont("Segoe UI", int(p.size * 0.7), QFont.Bold))
            r = QRectF(-p.size / 2.0, -p.size / 2.0, p.size, p.size)
            painter.drawText(r, Qt.AlignCenter, p.symbol)

        painter.restore()

    def _draw_death_shards(self, painter: QPainter):
        painter.setPen(QPen(QColor(239, 68, 68), 2.0))
        painter.setBrush(QColor(30, 41, 59))

        for s in self.death_shards:
            painter.save()
            painter.translate(s.x, s.y)
            painter.rotate(s.rot)
            painter.drawPolygon(s.poly)
            painter.restore()

        painter.setPen(QColor(239, 68, 68))
        painter.setFont(QFont("Consolas", 22, QFont.Bold))
        painter.drawText(
            self.rect(),
            Qt.AlignCenter,
            "CALCULATOR SHATTERED!\n\nRobi proved superior.\nWiping equation..."
        )

    def _draw_hud(self, painter: QPainter):
        y = self.height() - 34.0
        cx = self.width() / 2.0

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 13, QFont.Bold))
        painter.drawText(QPointF(cx - 180, y + 14), "CALC   LV 1")
        painter.drawText(QPointF(cx - 60, y + 14), "HP")

        bar_w = 90.0
        bar_h = 16.0
        bar_x = cx - 25.0
        bar_y = y

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(190, 18, 60))
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        fill_ratio = max(0.0, self.player_hp / float(self.max_player_hp))
        painter.setBrush(QColor(250, 204, 21))
        painter.drawRect(QRectF(bar_x, bar_y, bar_w * fill_ratio, bar_h))

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QPointF(cx + 80, y + 14), f"{self.player_hp} / {self.max_player_hp}")

    def _draw_damage_popup(self, painter: QPainter):
        txt, timer, x, y = self.damage_popup
        timer -= 0.016
        if timer <= 0:
            self.damage_popup = None
            return
        self.damage_popup = (txt, timer, x, y - 0.4)

        alpha = min(255, int(timer * 255))
        painter.setPen(QColor(239, 68, 68, alpha))
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.drawText(QRectF(x - 60, y - 15, 120, 30), Qt.AlignCenter, txt)

    def _draw_victory_text(self, painter: QPainter):
        painter.setPen(QColor(34, 197, 94))
        painter.setFont(QFont("Consolas", 26, QFont.Bold))
        painter.drawText(
            self.rect(),
            Qt.AlignCenter,
            "🏆 VICTORY! 🏆\n\nRobi has been silenced!\nCheck Robi Chat for the secret phrase!"
        )
