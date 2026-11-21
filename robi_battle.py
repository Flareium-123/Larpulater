# robi_battle.py - Undertale-style boss fight: "Battle Robi"
import os
import math
import random
import threading
from typing import List, Dict, Tuple

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal, QObject
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPainterPath,
    QPolygonF, QKeySequence, QLinearGradient, QPixmap
)
from PySide6.QtWidgets import QWidget, QApplication

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
                # 3 sharp rising alert beeps
                winsound.Beep(850, 60)
                winsound.Beep(1200, 60)
                winsound.Beep(1600, 100)
            elif sound_type == "slash":
                # Sweeping slice
                winsound.Beep(1800, 40)
                winsound.Beep(900, 60)
            elif sound_type == "hurt":
                # Low thud
                winsound.Beep(240, 80)
            elif sound_type == "hit_robi":
                # Solid strike
                winsound.Beep(450, 70)
                winsound.Beep(320, 90)
            elif sound_type == "shatter":
                # Crack and break
                winsound.Beep(800, 40)
                winsound.Beep(500, 60)
                winsound.Beep(250, 120)
            elif sound_type == "select":
                winsound.Beep(1100, 50)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


# ── Sprite configuration ───────────────────────────────────────────────────────
SPRITE_PATHS = {
    "robi_boss":   "assets/robi_boss.png",
    "player_calc": "assets/player_calc.png",
    "proj_plus":   "assets/proj_plus.png",
    "proj_minus":  "assets/proj_minus.png",
    "proj_mult":   "assets/proj_mult.png",
    "proj_div":    "assets/proj_div.png",
    "proj_sqrt":   "assets/proj_sqrt.png",
    "proj_pi":     "assets/proj_pi.png",
}

MATH_SYMBOLS = ["+", "-", "×", "÷", "√", "π", "=", "0", "1", "^"]

ROBI_TAUNTS = [
    "Did you really think that would hurt? My CPU runs hotter than your attack.",
    "You're still failing geometry, sweetie. Try carrying the one.",
    "Is that your best calculation? My error margin is zero!",
    "WARNING: Critical chassis damage! I'm STILL not grading your essay!",
    "FATAL SYSTEM ERROR: Memory dump initiated... don't celebrate yet!",
]


class Projectile:
    """A bullet-hell math projectile."""
    def __init__(self, x: float, y: float, vx: float, vy: float, symbol: str, size: float = 20.0):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.symbol = symbol
        self.size = size
        self.rot = random.uniform(0, 360)
        self.vrot = random.uniform(-6, 6)
        self.alive = True

    def update(self, dt: float):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.rot += self.vrot

    def get_hitbox_radius(self) -> float:
        return self.size * 0.42


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
        self.vy += 450.0 * dt  # gravity
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

    STATE_ENCOUNTER  = "ENCOUNTER"    # Shatter effect & 3 flashes
    STATE_PLAYER_TURN = "PLAYER_TURN"  # [ FIGHT ] button ready
    STATE_SLASH      = "SLASH"        # Slash animation across Robi
    STATE_DIALOGUE   = "DIALOGUE"     # Robi sassy speech bubble
    STATE_DODGE      = "DODGE"        # 7-second bullet-hell dodge wave
    STATE_VICTORY    = "VICTORY"      # Robi defeated & fades
    STATE_GAME_OVER  = "GAME_OVER"    # Calculator shatters in half

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
        self.player_speed = 190.0  # px/sec
        self.calc_w = 20.0
        self.calc_h = 26.0
        self.iframe_time = 0.0     # Invulnerability frame timer

        # Keys pressed
        self.keys = {
            Qt.Key_W: False, Qt.Key_Up: False,
            Qt.Key_S: False, Qt.Key_Down: False,
            Qt.Key_A: False, Qt.Key_Left: False,
            Qt.Key_D: False, Qt.Key_Right: False,
        }

        # Arena box geometry (interpolated smoothly)
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
        self.damage_popup = None  # (text, timer, x, y)
        self.dialogue_text = ""
        self.slash_progress = 0.0

        # Encounter transition
        self.encounter_flashes = 0
        self.flash_white = False
        self.shatter_cracks: List[List[QPointF]] = []

        # Death shards
        self.death_shards: List[ShatterShard] = []

        # 60 FPS game loop timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._game_loop)
        self.timer.start(16)  # ~60 FPS

        self._generate_shatter_cracks()
        play_8bit_sound("encounter")

    # ── Geometry initialization ───────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        # Default menu box layout centered in lower half
        bw = min(540.0, w * 0.75)
        bh = 150.0
        bx = (w - bw) / 2.0
        by = h - bh - 60.0
        self.box_target_rect = QRectF(bx, by, bw, bh)
        self.box_cur_rect = QRectF(bx, by, bw, bh)
        self.px = self.box_cur_rect.center().x()
        self.py = self.box_cur_rect.center().y()

    def _generate_shatter_cracks(self):
        """Generate jagged spiderweb fracture paths for encounter transition."""
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
        dt = 0.016  # fixed delta time
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
        # 3 flashes in 0.6 seconds, then start battle
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
        # Waiting for user to click/trigger [ FIGHT ]
        pass

    def trigger_fight_action(self):
        """User pressed [ FIGHT ] (Space / Enter / Click)."""
        if self.state != self.STATE_PLAYER_TURN:
            return
        self.state = self.STATE_SLASH
        self.state_time = 0.0
        self.slash_progress = 0.0
        play_8bit_sound("slash")

    def _update_slash(self, dt: float):
        self.slash_progress += dt * 3.5
        if self.slash_progress >= 1.0:
            # Land the hit!
            self.hits_landed += 1
            self.robi_hp = max(0, self.robi_hp - 20)
            self.screen_shake = 10.0
            self.damage_popup = ("-20", 1.2, self.width() / 2.0, self.height() * 0.22)
            play_8bit_sound("hit_robi")

            if self.robi_hp <= 0:
                self.state = self.STATE_VICTORY
                self.state_time = 0.0
            else:
                self.state = self.STATE_DIALOGUE
                self.state_time = 0.0
                idx = min(self.hits_landed - 1, len(ROBI_TAUNTS) - 1)
                self.dialogue_text = ROBI_TAUNTS[idx]

    def _update_dialogue(self, dt: float):
        if self.state_time >= 1.6:
            # Transition to bullet-hell dodge turn
            self.state = self.STATE_DODGE
            self.state_time = 0.0
            self.wave_timer = 0.0
            self.wave_spawn_acc = 0.0
            self.projectiles.clear()
            self._set_dodge_box()

    def _update_dodge(self, dt: float):
        self.wave_timer += dt

        # Player movement
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

        # Clamp inside bullet box
        box = self.box_cur_rect
        hw = self.calc_w / 2.0 + 4
        hh = self.calc_h / 2.0 + 4
        self.px = max(box.left() + hw, min(box.right() - hw, self.px))
        self.py = max(box.top() + hh, min(box.bottom() - hh, self.py))

        # Projectile spawning waves
        self.wave_spawn_acc += dt
        spawn_rate = 0.28 - (self.hits_landed * 0.03)  # gets denser each hit!
        if self.wave_spawn_acc >= spawn_rate:
            self.wave_spawn_acc = 0.0
            self._spawn_wave_projectile()

        # Update projectiles
        hit_radius = 9.0
        for p in self.projectiles:
            p.update(dt)

            # Collision check
            if self.iframe_time <= 0:
                dist = math.hypot(p.x - self.px, p.y - self.py)
                if dist < (hit_radius + p.get_hitbox_radius()):
                    # Take damage!
                    self.player_hp = max(0, self.player_hp - 2)
                    self.iframe_time = 0.75  # 0.75s i-frames
                    self.screen_shake = 6.0
                    play_8bit_sound("hurt")
                    if self.player_hp <= 0:
                        self._trigger_game_over()
                        return

        # Prune out-of-bounds projectiles
        self.projectiles = [
            p for p in self.projectiles
            if (box.left() - 60 <= p.x <= box.right() + 60 and
                box.top() - 60 <= p.y <= box.bottom() + 60)
        ]

        # Wave complete after 7 seconds!
        if self.wave_timer >= self.wave_duration:
            self.projectiles.clear()
            self.state = self.STATE_PLAYER_TURN
            self.state_time = 0.0
            self._set_menu_box()

    def _spawn_wave_projectile(self):
        box = self.box_cur_rect
        symbol = random.choice(MATH_SYMBOLS)
        pattern = random.randint(0, 2)

        if pattern == 0:
            # Fall from top downward
            x = random.uniform(box.left() + 15, box.right() - 15)
            y = box.top() - 10
            vy = random.uniform(90, 140)
            vx = random.uniform(-20, 20)
            self.projectiles.append(Projectile(x, y, vx, vy, symbol, 22.0))
        elif pattern == 1:
            # Sweep from left to right
            x = box.left() - 10
            y = random.uniform(box.top() + 15, box.bottom() - 15)
            vx = random.uniform(80, 130)
            vy = random.uniform(-15, 15)
            self.projectiles.append(Projectile(x, y, vx, vy, symbol, 20.0))
        else:
            # Sweep from right to left
            x = box.right() + 10
            y = random.uniform(box.top() + 15, box.bottom() - 15)
            vx = -random.uniform(80, 130)
            vy = random.uniform(-15, 15)
            self.projectiles.append(Projectile(x, y, vx, vy, symbol, 20.0))

    def _trigger_game_over(self):
        self.state = self.STATE_GAME_OVER
        self.state_time = 0.0
        play_8bit_sound("shatter")

        # Create broken calculator shards radiating outward
        self.death_shards.clear()
        half_w = self.calc_w / 2.0
        half_h = self.calc_h / 2.0

        # Shard 1: Top-left
        poly1 = QPolygonF([QPointF(-half_w, -half_h), QPointF(0, -half_h), QPointF(-4, 0), QPointF(-half_w, 0)])
        self.death_shards.append(ShatterShard(self.px, self.py, -120, -180, poly1))

        # Shard 2: Top-right
        poly2 = QPolygonF([QPointF(0, -half_h), QPointF(half_w, -half_h), QPointF(half_w, 0), QPointF(4, 0)])
        self.death_shards.append(ShatterShard(self.px, self.py, 130, -210, poly2))

        # Shard 3: Bottom-left
        poly3 = QPolygonF([QPointF(-half_w, 0), QPointF(-2, 0), QPointF(0, half_h), QPointF(-half_w, half_h)])
        self.death_shards.append(ShatterShard(self.px, self.py, -90, -110, poly3))

        # Shard 4: Bottom-right
        poly4 = QPolygonF([QPointF(2, 0), QPointF(half_w, 0), QPointF(half_w, half_h), QPointF(0, half_h)])
        self.death_shards.append(ShatterShard(self.px, self.py, 110, -130, poly4))

    def _update_game_over(self, dt: float):
        for s in self.death_shards:
            s.update(dt)

        if self.state_time >= 2.4:
            self.timer.stop()
            self.battle_lost.emit()
            self.battle_ended.emit()
            self.close()

    def _update_victory(self, dt: float):
        if self.state_time >= 2.0:
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
            # Close battle and yield
            self.timer.stop()
            self.battle_ended.emit()
            self.close()

    def keyReleaseEvent(self, event):
        k = event.key()
        if k in self.keys:
            self.keys[k] = False

    def mousePressEvent(self, event):
        if self.state == self.STATE_PLAYER_TURN:
            # Check if click is on [ FIGHT ] button
            btn_rect = self._get_fight_button_rect()
            if btn_rect.contains(event.position()):
                play_8bit_sound("select")
                self.trigger_fight_action()

    # ── Rendering (QPainter 60 FPS) ───────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # Apply screen shake offset
        painter.translate(self.shake_offset)

        # Full black Undertale canvas
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        # Encounter transition shatter overlay
        if self.state == self.STATE_ENCOUNTER:
            self._draw_encounter_shatter(painter)
            return

        # 1. Draw Robi Boss
        self._draw_robi_boss(painter)

        # 2. Draw Speech Bubble
        if self.state == self.STATE_DIALOGUE:
            self._draw_speech_bubble(painter)

        # 3. Draw The White Box
        self._draw_battle_box(painter)

        # 4. Draw Turn-specific Content
        if self.state == self.STATE_PLAYER_TURN:
            self._draw_player_menu(painter)
        elif self.state == self.STATE_DODGE:
            self._draw_dodge_turn(painter)
        elif self.state == self.STATE_SLASH:
            self._draw_slash(painter)
        elif self.state == self.STATE_GAME_OVER:
            self._draw_death_shards(painter)

        # 5. Draw Player HUD Bar at Bottom
        self._draw_hud(painter)

        # 6. Draw Damage Popup
        if self.damage_popup:
            self._draw_damage_popup(painter)

        # 7. Draw Victory Text
        if self.state == self.STATE_VICTORY:
            self._draw_victory_text(painter)

    # ── Drawing helpers ───────────────────────────────────────────────────────
    def _draw_encounter_shatter(self, painter: QPainter):
        """Render cracked glass shatter effect across the screen."""
        if self.flash_white:
            painter.fillRect(self.rect(), QColor(255, 255, 255))
            return

        painter.fillRect(self.rect(), QColor(10, 15, 25))
        pen = QPen(QColor(220, 240, 255, 200), 2.5)
        painter.setPen(pen)

        for crack in self.shatter_cracks:
            for i in range(len(crack) - 1):
                painter.drawLine(crack[i], crack[i + 1])

        # Centered alert label
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, "⚔️ ROBI ENCOUNTER ⚔️")

    def _draw_robi_boss(self, painter: QPainter):
        """Render Robi boss sprite with opacity tied to current HP."""
        cx = self.width() / 2.0
        cy = self.height() * 0.22
        w = 120.0
        h = 100.0
        rx = cx - w / 2.0
        ry = cy - h / 2.0

        # Opacity drops as HP decreases
        hp_ratio = self.robi_hp / float(self.max_robi_hp)
        alpha = max(0.0, min(1.0, hp_ratio if self.state != self.STATE_VICTORY else max(0.0, 1.0 - self.state_time)))
        painter.setOpacity(alpha)

        # Check if custom asset exists
        if os.path.exists(SPRITE_PATHS["robi_boss"]):
            pix = QPixmap(SPRITE_PATHS["robi_boss"])
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), pix)
        else:
            # Procedural pixel-art angry robot face
            # Body casing (matte slate blue)
            painter.setPen(QPen(QColor(255, 255, 255), 2.5))
            painter.setBrush(QColor(30, 58, 138))  # Dark blue
            painter.drawRoundedRect(QRectF(rx, ry, w, h), 16, 16)

            # Antenna
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(QPointF(cx, ry), QPointF(cx, ry - 18))
            painter.setBrush(QColor(239, 68, 68))  # Angry red beacon
            painter.drawEllipse(QPointF(cx, ry - 20), 5, 5)

            # Angry Visor / Eyes
            painter.setBrush(QColor(15, 23, 42))  # Visor bg
            painter.drawRoundedRect(QRectF(rx + 15, ry + 22, w - 30, 32), 6, 6)

            # Glowing angled angry eyes (bright cyan)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(34, 211, 238))
            # Left slanted eye
            eye1 = QPolygonF([
                QPointF(rx + 25, ry + 30), QPointF(rx + 48, ry + 36),
                QPointF(rx + 48, ry + 44), QPointF(rx + 25, ry + 38)
            ])
            painter.drawPolygon(eye1)
            # Right slanted eye
            eye2 = QPolygonF([
                QPointF(rx + w - 25, ry + 30), QPointF(rx + w - 48, ry + 36),
                QPointF(rx + w - 48, ry + 44), QPointF(rx + w - 25, ry + 38)
            ])
            painter.drawPolygon(eye2)

            # Angry grid mouth
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.drawLine(QPointF(rx + 30, ry + 72), QPointF(rx + w - 30, ry + 72))
            for mx in range(int(rx + 36), int(rx + w - 30), 10):
                painter.drawLine(QPointF(mx, ry + 67), QPointF(mx, ry + 77))

        painter.setOpacity(1.0)

        # Robi Boss HP bar above box
        bar_w = 180.0
        bar_h = 10.0
        bar_x = cx - bar_w / 2.0
        bar_y = cy + h / 2.0 + 14.0

        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(QColor(30, 30, 30))
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        fill_w = bar_w * hp_ratio
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(37, 99, 235))  # Robi blue HP
        painter.drawRect(QRectF(bar_x + 1, bar_y + 1, fill_w, bar_h - 2))

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(
            QRectF(bar_x, bar_y - 18, bar_w, 16),
            Qt.AlignCenter,
            f"ROBI HP  {self.robi_hp} / {self.max_robi_hp}"
        )

    def _draw_speech_bubble(self, painter: QPainter):
        """Render comic speech bubble next to Robi with mid-battle trash talk."""
        cx = self.width() / 2.0
        cy = self.height() * 0.20
        bw = 200.0
        bh = 70.0
        bx = cx + 80.0
        by = cy - 30.0

        # Bubble body
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 10, 10)

        # Pointer triangle towards Robi
        tri = QPolygonF([QPointF(bx, by + 25), QPointF(bx - 14, by + 30), QPointF(bx, by + 38)])
        painter.drawPolygon(tri)

        # Text
        painter.setPen(QColor(0, 0, 0))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(bx + 10, by + 8, bw - 20, bh - 16), Qt.TextWordWrap | Qt.AlignVCenter, self.dialogue_text)

    def _draw_battle_box(self, painter: QPainter):
        """Draw the iconic thick white-bordered Undertale bullet box."""
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
        """Render the [ FIGHT ] action button in the player turn."""
        box = self.box_cur_rect
        btn_rect = self._get_fight_button_rect()

        # Prompt text in upper box
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 14))
        painter.drawText(
            QRectF(box.left() + 24, box.top() + 24, box.width() - 48, 40),
            Qt.AlignLeft,
            "* Robi glares down at your math calculations."
        )

        # [ FIGHT ] Button
        painter.setPen(QPen(QColor(249, 115, 22), 2.5))  # Glowing Undertale orange
        painter.setBrush(QColor(20, 20, 20))
        painter.drawRoundedRect(btn_rect, 6, 6)

        # Mini soul icon next to [ FIGHT ]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(249, 115, 22))
        soul_cx = btn_rect.left() + 24
        soul_cy = btn_rect.center().y()
        painter.drawEllipse(QPointF(soul_cx, soul_cy), 5, 5)

        painter.setPen(QColor(249, 115, 22))
        painter.setFont(QFont("Consolas", 16, QFont.Bold))
        painter.drawText(btn_rect, Qt.AlignCenter, "  [ FIGHT ]")

        # Hint text
        painter.setPen(QColor(160, 160, 160))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            QRectF(box.left(), box.bottom() - 18, box.width(), 16),
            Qt.AlignCenter,
            "Press SPACE / ENTER / CLICK to Strike Robi (-20 HP)"
        )

    def _draw_slash(self, painter: QPainter):
        """Render Undertale curved knife slash sweep across Robi."""
        cx = self.width() / 2.0
        cy = self.height() * 0.22
        prog = min(1.0, self.slash_progress)

        painter.setPen(QPen(QColor(255, 255, 255), 4.0))
        path = QPainterPath()
        start_x = cx - 50.0 + (prog * 30.0)
        start_y = cy - 40.0 + (prog * 20.0)
        end_x = cx + 50.0
        end_y = cy + 40.0
        path.moveTo(start_x, start_y)
        path.quadTo(cx - 10.0, cy + 20.0, end_x, end_y)
        painter.strokePath(path, QPen(QColor(255, 255, 255), 5.0))

    def _draw_dodge_turn(self, painter: QPainter):
        """Render bullet-hell dodge turn with player calculator & projectiles."""
        # 1. Draw Player Calculator
        is_flashing = (self.iframe_time > 0 and int(self.state_time * 20) % 2 == 0)
        if not is_flashing:
            self._draw_player_calc(painter, self.px, self.py)

        # 2. Draw Projectiles
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
        """Render procedural glowing blue/white mini-calculator."""
        w = self.calc_w
        h = self.calc_h
        rx = x - w / 2.0
        ry = y - h / 2.0

        if os.path.exists(SPRITE_PATHS["player_calc"]):
            pix = QPixmap(SPRITE_PATHS["player_calc"])
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), pix)
            return

        # Calculator body
        painter.setPen(QPen(QColor(34, 211, 238), 2.0))  # Glowing cyan border
        painter.setBrush(QColor(15, 23, 42))             # Dark slate fill
        painter.drawRoundedRect(QRectF(rx, ry, w, h), 4, 4)

        # LCD screen
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(219, 234, 254))  # Bright white-blue screen
        painter.drawRect(QRectF(rx + 3, ry + 3, w - 6, 6))

        # 6 mini grid keypad dots
        painter.setBrush(QColor(59, 130, 246))
        for r in range(2):
            for c in range(3):
                bx = rx + 4 + (c * 4.5)
                by = ry + 12 + (r * 4.5)
                painter.drawRect(QRectF(bx, by, 3, 3))

    def _draw_projectile(self, painter: QPainter, p: Projectile):
        """Render glowing math symbols and shards."""
        painter.save()
        painter.translate(p.x, p.y)
        painter.rotate(p.rot)

        # Crisp cyan glow & white symbol
        painter.setPen(QPen(QColor(255, 255, 255), 2.0))
        painter.setFont(QFont("Segoe UI", int(p.size * 0.7), QFont.Bold))
        r = QRectF(-p.size / 2.0, -p.size / 2.0, p.size, p.size)
        painter.drawText(r, Qt.AlignCenter, p.symbol)

        painter.restore()

    def _draw_death_shards(self, painter: QPainter):
        """Render split/crack-in-half shatter death animation."""
        painter.setPen(QPen(QColor(239, 68, 68), 2.0))
        painter.setBrush(QColor(30, 41, 59))

        for s in self.death_shards:
            painter.save()
            painter.translate(s.x, s.y)
            painter.rotate(s.rot)
            painter.drawPolygon(s.poly)
            painter.restore()

        # Defeat text
        painter.setPen(QColor(239, 68, 68))
        painter.setFont(QFont("Consolas", 22, QFont.Bold))
        painter.drawText(
            self.rect(),
            Qt.AlignCenter,
            "CALCULATOR SHATTERED!\n\nRobi proved superior."
        )

    def _draw_hud(self, painter: QPainter):
        """Render Undertale-style bottom player HUD."""
        y = self.height() - 34.0
        cx = self.width() / 2.0

        # Player name and level
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 13, QFont.Bold))
        painter.drawText(QPointF(cx - 180, y + 14), "CALC   LV 1")

        # HP label
        painter.drawText(QPointF(cx - 60, y + 14), "HP")

        # HP bar
        bar_w = 90.0
        bar_h = 16.0
        bar_x = cx - 25.0
        bar_y = y

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(190, 18, 60))  # Empty red bar
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        # Filled yellow/green bar
        fill_ratio = max(0.0, self.player_hp / float(self.max_player_hp))
        painter.setBrush(QColor(250, 204, 21))  # Undertale HP yellow
        painter.drawRect(QRectF(bar_x, bar_y, bar_w * fill_ratio, bar_h))

        # HP numbers
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QPointF(cx + 80, y + 14), f"{self.player_hp} / {self.max_player_hp}")

    def _draw_damage_popup(self, painter: QPainter):
        """Render floating damage text."""
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
        """Render victory declaration."""
        painter.setPen(QColor(34, 197, 94))
        painter.setFont(QFont("Consolas", 26, QFont.Bold))
        painter.drawText(
            self.rect(),
            Qt.AlignCenter,
            "🏆 VICTORY! 🏆\n\nRobi has been silenced!\nCheck Robi Chat for the secret phrase!"
        )
