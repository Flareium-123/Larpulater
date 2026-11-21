# robi_battle.py - Undertale-style boss fight: "Battle Robi"
import os
import sys
import math
import random
import struct
from typing import List, Optional

from shiboken6 import isValid
from PySide6.QtCore import (
    Qt, QTimer, QRect, QRectF, QPointF, Signal, QElapsedTimer, QUrl,
    QByteArray, QBuffer, QIODevice, QPropertyAnimation, QEasingCurve,
    QCoreApplication, qWarning
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QPainterPath, QPolygonF, QPixmap
)
from PySide6.QtMultimedia import (
    QAudio, QAudioFormat, QAudioOutput, QAudioSink, QMediaPlayer
)
from PySide6.QtWidgets import QWidget


# ── Global battle flag (ads / popups check this) ──────────────────────────────
BATTLE_ACTIVE = False


def is_battle_active() -> bool:
    return BATTLE_ACTIVE


def _set_battle_active(value: bool):
    global BATTLE_ACTIVE
    BATTLE_ACTIVE = value


# ── Asset path resolution (PyInstaller sys._MEIPASS & dev paths) ──────────────
def get_asset_path(filename: str) -> str:
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


# ── Battle audio ──────────────────────────────────────────────────────────────
SFX_VOLUME = 0.12
BATTLE_MUSIC_VOLUME = 0.75
_ACTIVE_SFX_SINKS: List[QAudioSink] = []

_SFX_TONES = {
    "encounter": [(850, 60), (1200, 60), (1600, 100)],
    "slash": [(1800, 40), (900, 60)],
    "hurt": [(240, 80)],
    "hit_robi": [(450, 70), (320, 90)],
    "shatter": [(800, 40), (500, 60), (250, 120)],
    "select": [(1100, 50)],
}


def play_8bit_sound(sound_type: str):
    tones = _SFX_TONES.get(sound_type)
    if not tones:
        return

    sample_rate = 44100
    fade_samples = int(sample_rate * 0.004)
    samples = bytearray()
    total_duration_ms = 0
    for frequency, duration_ms in tones:
        sample_count = int(sample_rate * duration_ms / 1000)
        tone = bytearray(sample_count * 2)
        for index in range(sample_count):
            envelope = min(
                1.0,
                index / fade_samples,
                (sample_count - index - 1) / fade_samples,
            )
            value = int(32767 * 0.35 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
            struct.pack_into("<h", tone, index * 2, value)
        samples.extend(tone)
        silence_samples = int(sample_rate * 0.01)
        samples.extend(bytes(silence_samples * 2))
        total_duration_ms += duration_ms + 10

    audio_format = QAudioFormat()
    audio_format.setSampleRate(sample_rate)
    audio_format.setChannelCount(1)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

    sink = QAudioSink(audio_format, QCoreApplication.instance())
    sink.setVolume(SFX_VOLUME)
    buffer = QBuffer(sink)
    buffer.setData(QByteArray(bytes(samples)))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        sink.deleteLater()
        raise RuntimeError("Unable to open the battle sound-effect buffer")

    def report_audio_error(state):
        if (
            state == QAudio.State.StoppedState
            and isValid(sink)
            and sink.error() != QAudio.Error.NoError
        ):
            qWarning(f"Battle sound effect failed to play: {sink.error()}")

    sink.stateChanged.connect(report_audio_error)
    _ACTIVE_SFX_SINKS.append(sink)
    sink.start(buffer)

    def stop_sound():
        if sink in _ACTIVE_SFX_SINKS:
            sink.stateChanged.disconnect(report_audio_error)
            _ACTIVE_SFX_SINKS.remove(sink)
            sink.stop()
            sink.deleteLater()

    QTimer.singleShot(total_duration_ms + 250, stop_sound)


ROBI_TAUNTS = [
    "Did you really think that would hurt? My CPU runs hotter than your attack.",
    "You're still failing geometry, sweetie. Try carrying the one.",
    "Is that your best calculation? My error margin is zero!",
    "WARNING: Critical chassis damage! I'm STILL not grading your essay!",
    "FATAL SYSTEM ERROR: Memory dump initiated... don't celebrate yet!",
]


class Projectile:
    def __init__(self, x, y, vx, vy, pixmap: Optional[QPixmap] = None,
                 symbol: str = "*", size: float = 24.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.pixmap = pixmap
        self.symbol = symbol
        self.size = size
        self.rot = random.uniform(0, 360)
        self.vrot = random.uniform(-5, 5)

    def update(self, dt: float):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.rot += self.vrot * dt * 60.0

    def get_hitbox_radius(self) -> float:
        return self.size * 0.40


class ShatterShard:
    def __init__(self, x, y, vx, vy, poly: QPolygonF):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.poly = poly
        self.rot = 0.0
        self.vrot = random.uniform(-10, 10)

    def update(self, dt: float):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 450.0 * dt
        self.rot += self.vrot * dt * 60.0


class RobiBattleOverlay(QWidget):
    """
    Undertale-style battle screen (60 FPS).
    Signals:
        battle_won()   - Robi defeated (5 hits)
        battle_lost()  - Player HP reached 0
        battle_ended() - Battle screen closed (always emitted once, win/lose/esc)
    """
    battle_won = Signal()
    battle_lost = Signal()
    battle_ended = Signal()

    STATE_ENCOUNTER = "ENCOUNTER"
    STATE_PLAYER_TURN = "PLAYER_TURN"
    STATE_SLASH = "SLASH"
    STATE_DIALOGUE = "DIALOGUE"
    STATE_DODGE = "DODGE"
    STATE_VICTORY = "VICTORY"
    STATE_GAME_OVER = "GAME_OVER"

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        # Snapshot of the calculator window for the cracked-glass encounter effect
        self.backdrop: Optional[QPixmap] = None
        if parent is not None:
            try:
                self.backdrop = parent.grab()
            except Exception:
                self.backdrop = None

        # Stats
        self.max_player_hp = 20
        self.player_hp = 20
        self.max_robi_hp = 100
        self.robi_hp = 100
        self.hits_landed = 0

        # Player
        self.px = 0.0
        self.py = 0.0
        self.player_speed = 195.0
        self.calc_w = 22.0
        self.calc_h = 28.0
        self.iframe_time = 0.0

        self.keys = {
            Qt.Key_W: False, Qt.Key_Up: False,
            Qt.Key_S: False, Qt.Key_Down: False,
            Qt.Key_A: False, Qt.Key_Left: False,
            Qt.Key_D: False, Qt.Key_Right: False,
        }

        # Arena
        self.box_cur_rect = QRectF(250, 340, 460, 160)
        self.box_target_rect = QRectF(250, 340, 460, 160)

        # Attack wave
        self.projectiles: List[Projectile] = []
        self.wave_timer = 0.0
        self.wave_duration = 7.0
        self.wave_spawn_acc = 0.0

        # State
        self.state = self.STATE_ENCOUNTER
        self.state_time = 0.0
        self.screen_shake = 0.0
        self.shake_offset = QPointF(0, 0)
        self.damage_popup = None  # [text, time_left, x, y]
        self.dialogue_text = ""
        self._finished = False

        # Slash animation
        self.slash_frame_idx = 0
        self.slash_timer = 0.0
        self.slash_frame_duration = 0.075

        # Encounter
        self.flash_white = False
        self.shatter_cracks: List[List[QPointF]] = []

        # Death
        self.death_shards: List[ShatterShard] = []

        self._load_sprites()
        self._prepare_battle_music()
        self._battle_music_started = False
        self._battle_music_fade: Optional[QPropertyAnimation] = None

        # Game loop (~60 FPS, real dt)
        self._clock = QElapsedTimer()
        self._clock.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._game_loop)
        self.timer.start(16)

        _set_battle_active(True)
        self._generate_shatter_cracks()
        play_8bit_sound("encounter")

    def _prepare_battle_music(self):
        music_path = get_asset_path("robi_battle_theme.mp3")
        if not os.path.isfile(music_path):
            raise FileNotFoundError(f"Robi battle music asset not found: {music_path}")

        self._battle_music_output = QAudioOutput(self)
        self._battle_music_output.setVolume(0.0)
        self._battle_music_player = QMediaPlayer(self)
        self._battle_music_player.setAudioOutput(self._battle_music_output)
        self._battle_music_player.setLoops(QMediaPlayer.Loops.Infinite)
        self._battle_music_player.errorOccurred.connect(self._on_battle_music_error)
        self._battle_music_player.setSource(QUrl.fromLocalFile(music_path))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._battle_music_started:
            self._battle_music_started = True
            self._battle_music_player.play()
            self._fade_battle_music(BATTLE_MUSIC_VOLUME, 700)

    def _fade_battle_music(self, target_volume: float, duration_ms: int, stop_after: bool = False):
        if self._battle_music_fade is not None:
            self._battle_music_fade.stop()

        fade = QPropertyAnimation(self._battle_music_output, b"volume", self)
        fade.setDuration(duration_ms)
        fade.setStartValue(self._battle_music_output.volume())
        fade.setEndValue(target_volume)
        fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        if stop_after:
            fade.finished.connect(self._battle_music_player.stop)
        self._battle_music_fade = fade
        fade.start()

    def _stop_battle_music(self):
        if self._battle_music_fade is not None:
            self._battle_music_fade.stop()
        self._battle_music_player.stop()

    def _on_battle_music_error(self, error, error_string: str):
        qWarning(f"Robi battle music playback failed ({error}): {error_string}")

    # ── Sprites ───────────────────────────────────────────────────────────────
    def _load_pix(self, name: str) -> Optional[QPixmap]:
        p = get_asset_path(name)
        if os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                return pm
        return None

    def _load_sprites(self):
        self.pix_angry_robi = self._load_pix("Angry Robi.png")
        self.pix_defeated_robi = self._load_pix("Defeated Robi.png")
        self.pix_player_calc = self._load_pix("player_calc.png")

        slash_names = ["SHASH1.png", "SLASH2.png", "SLASH3.png", "SLASH4.png", "SLASH 5.png"]
        self.slash_frames: List[QPixmap] = []
        for name in slash_names:
            pm = self._load_pix(name)
            if pm:
                self.slash_frames.append(pm)

        # Slice 4 symbols: Blue -, Yellow +, Purple ÷, Red ×
        self.symbol_pixmaps: List[QPixmap] = []
        sheet = self._load_pix("Robi Attack Symbols.png")
        if sheet:
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

    # ── Geometry ──────────────────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_menu_box()
        self.box_cur_rect = QRectF(self.box_target_rect)
        self.px = self.box_cur_rect.center().x()
        self.py = self.box_cur_rect.center().y()
        self._generate_shatter_cracks()

    def _generate_shatter_cracks(self):
        self.shatter_cracks = []
        cx = self.width() / 2.0 if self.width() > 0 else 500
        cy = self.height() / 2.0 if self.height() > 0 else 350
        for _ in range(12):
            pts = [QPointF(cx, cy)]
            curr = QPointF(cx, cy)
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(250, 500)
            steps = random.randint(4, 7)
            for _s in range(steps):
                step_dist = dist / steps
                angle += random.uniform(-0.35, 0.35)
                curr = QPointF(curr.x() + math.cos(angle) * step_dist,
                               curr.y() + math.sin(angle) * step_dist)
                pts.append(QPointF(curr.x(), curr.y()))
            self.shatter_cracks.append(pts)

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _game_loop(self):
        dt = min(self._clock.restart() / 1000.0, 0.05)
        if dt <= 0:
            dt = 0.016
        self.state_time += dt

        if self.screen_shake > 0:
            self.screen_shake = max(0.0, self.screen_shake - dt * 25.0)
            self.shake_offset = QPointF(
                random.uniform(-self.screen_shake, self.screen_shake),
                random.uniform(-self.screen_shake, self.screen_shake))
        else:
            self.shake_offset = QPointF(0, 0)

        # Smooth arena interpolation
        cur, tgt = self.box_cur_rect, self.box_target_rect
        s = min(1.0, 10.0 * dt)
        self.box_cur_rect = QRectF(
            cur.x() + (tgt.x() - cur.x()) * s,
            cur.y() + (tgt.y() - cur.y()) * s,
            cur.width() + (tgt.width() - cur.width()) * s,
            cur.height() + (tgt.height() - cur.height()) * s)

        if self.iframe_time > 0:
            self.iframe_time = max(0.0, self.iframe_time - dt)

        # Damage popup
        if self.damage_popup:
            self.damage_popup[1] -= dt
            self.damage_popup[3] -= 24.0 * dt
            if self.damage_popup[1] <= 0:
                self.damage_popup = None

        handler = {
            self.STATE_ENCOUNTER: self._update_encounter,
            self.STATE_PLAYER_TURN: self._update_player_turn,
            self.STATE_SLASH: self._update_slash,
            self.STATE_DIALOGUE: self._update_dialogue,
            self.STATE_DODGE: self._update_dodge,
            self.STATE_VICTORY: self._update_victory,
            self.STATE_GAME_OVER: self._update_game_over,
        }.get(self.state)
        if handler:
            handler(dt)

        self.update()

    # ── States ────────────────────────────────────────────────────────────────
    def _update_encounter(self, dt):
        cycle = int(self.state_time / 0.12)
        if cycle < 6:  # 3 flashes
            self.flash_white = (cycle % 2 == 1)
        else:
            self.flash_white = False
            self.state = self.STATE_PLAYER_TURN
            self.state_time = 0.0
            self._set_menu_box()

    def _set_menu_box(self):
        w, h = self.width(), self.height()
        bw = min(540.0, w * 0.75)
        bh = 150.0
        self.box_target_rect = QRectF((w - bw) / 2.0, h - bh - 60.0, bw, bh)

    def _set_dodge_box(self):
        w, h = self.width(), self.height()
        bw, bh = 290.0, 190.0
        self.box_target_rect = QRectF((w - bw) / 2.0, h - bh - 70.0, bw, bh)
        self.px = self.box_target_rect.center().x()
        self.py = self.box_target_rect.center().y()

    def _update_player_turn(self, dt):
        pass

    def trigger_fight_action(self):
        if self.state != self.STATE_PLAYER_TURN:
            return
        self.state = self.STATE_SLASH
        self.state_time = 0.0
        self.slash_frame_idx = 0
        self.slash_timer = 0.0
        play_8bit_sound("slash")

    def _update_slash(self, dt):
        self.slash_timer += dt
        if self.slash_timer >= self.slash_frame_duration:
            self.slash_timer = 0.0
            self.slash_frame_idx += 1

        total = len(self.slash_frames) if self.slash_frames else 5
        if self.slash_frame_idx >= total:
            self.hits_landed += 1
            self.robi_hp = max(0, self.robi_hp - 20)
            self.screen_shake = 10.0
            self.damage_popup = ["-20", 1.2, self.width() / 2.0, self.height() * 0.22]
            play_8bit_sound("hit_robi")

            if self.robi_hp <= 0:
                self.state = self.STATE_VICTORY
                self._fade_battle_music(0.0, 1500, stop_after=True)
            else:
                self.state = self.STATE_DIALOGUE
                idx = min(self.hits_landed - 1, len(ROBI_TAUNTS) - 1)
                self.dialogue_text = ROBI_TAUNTS[idx]
            self.state_time = 0.0

    def _update_dialogue(self, dt):
        if self.state_time >= 1.6:
            self.state = self.STATE_DODGE
            self.state_time = 0.0
            self.wave_timer = 0.0
            self.wave_spawn_acc = 0.0
            self.projectiles.clear()
            self._set_dodge_box()

    def _update_dodge(self, dt):
        self.wave_timer += dt

        dx = dy = 0.0
        if self.keys[Qt.Key_W] or self.keys[Qt.Key_Up]:
            dy -= 1.0
        if self.keys[Qt.Key_S] or self.keys[Qt.Key_Down]:
            dy += 1.0
        if self.keys[Qt.Key_A] or self.keys[Qt.Key_Left]:
            dx -= 1.0
        if self.keys[Qt.Key_D] or self.keys[Qt.Key_Right]:
            dx += 1.0
        if dx and dy:
            dx *= 0.7071
            dy *= 0.7071

        self.px += dx * self.player_speed * dt
        self.py += dy * self.player_speed * dt

        box = self.box_cur_rect
        hw = self.calc_w / 2.0 + 4
        hh = self.calc_h / 2.0 + 4
        self.px = max(box.left() + hw, min(box.right() - hw, self.px))
        self.py = max(box.top() + hh, min(box.bottom() - hh, self.py))

        self.wave_spawn_acc += dt
        spawn_rate = max(0.12, 0.28 - self.hits_landed * 0.03)
        if self.wave_spawn_acc >= spawn_rate:
            self.wave_spawn_acc = 0.0
            self._spawn_wave_projectile()

        hit_radius = 8.5
        for p in self.projectiles:
            p.update(dt)
            if self.iframe_time <= 0:
                if math.hypot(p.x - self.px, p.y - self.py) < hit_radius + p.get_hitbox_radius():
                    self.player_hp = max(0, self.player_hp - 2)  # flat 2 dmg
                    self.iframe_time = 0.75                      # 0.75s i-frames
                    self.screen_shake = 6.0
                    play_8bit_sound("hurt")
                    if self.player_hp <= 0:
                        self._trigger_game_over()
                        return

        self.projectiles = [
            p for p in self.projectiles
            if (box.left() - 70 <= p.x <= box.right() + 70 and
                box.top() - 70 <= p.y <= box.bottom() + 70)
        ]

        if self.wave_timer >= self.wave_duration:
            self.projectiles.clear()
            self.state = self.STATE_PLAYER_TURN
            self.state_time = 0.0
            self._set_menu_box()

    def _spawn_wave_projectile(self):
        box = self.box_cur_rect
        pix = random.choice(self.symbol_pixmaps) if self.symbol_pixmaps else None
        sym = random.choice(["+", "-", "×", "÷"])
        pattern = random.randint(0, 2)

        if pattern == 0:      # fall downward
            p = Projectile(random.uniform(box.left() + 15, box.right() - 15), box.top() - 12,
                           random.uniform(-20, 20), random.uniform(90, 140), pix, sym, 26.0)
        elif pattern == 1:    # sweep left -> right
            p = Projectile(box.left() - 12, random.uniform(box.top() + 15, box.bottom() - 15),
                           random.uniform(85, 130), random.uniform(-15, 15), pix, sym, 24.0)
        else:                 # sweep right -> left
            p = Projectile(box.right() + 12, random.uniform(box.top() + 15, box.bottom() - 15),
                           -random.uniform(85, 130), random.uniform(-15, 15), pix, sym, 24.0)
        self.projectiles.append(p)

    def _trigger_game_over(self):
        self.state = self.STATE_GAME_OVER
        self.state_time = 0.0
        play_8bit_sound("shatter")

        self.death_shards.clear()
        hw, hh = self.calc_w / 2.0, self.calc_h / 2.0
        polys = [
            (QPolygonF([QPointF(-hw, -hh), QPointF(0, -hh), QPointF(-4, 0), QPointF(-hw, 0)]), -120, -180),
            (QPolygonF([QPointF(0, -hh), QPointF(hw, -hh), QPointF(hw, 0), QPointF(4, 0)]), 130, -210),
            (QPolygonF([QPointF(-hw, 0), QPointF(-2, 0), QPointF(0, hh), QPointF(-hw, hh)]), -90, -110),
            (QPolygonF([QPointF(2, 0), QPointF(hw, 0), QPointF(hw, hh), QPointF(0, hh)]), 110, -130),
        ]
        for poly, vx, vy in polys:
            self.death_shards.append(ShatterShard(self.px, self.py, vx, vy, poly))

    def _finish(self, won: Optional[bool]):
        """Emit exactly once: won/lost (if any) then ended."""
        if self._finished:
            return
        self._finished = True
        self.timer.stop()
        self._stop_battle_music()
        _set_battle_active(False)
        if won is True:
            self.battle_won.emit()
        elif won is False:
            self.battle_lost.emit()
        self.battle_ended.emit()
        self.close()

    def _update_game_over(self, dt):
        for s in self.death_shards:
            s.update(dt)
        if self.state_time >= 2.4:
            self._finish(False)

    def _update_victory(self, dt):
        if self.state_time >= 2.2:
            self._finish(True)

    def closeEvent(self, event):
        # Safety net if the widget is closed externally
        self._stop_battle_music()
        if not self._finished:
            self._finished = True
            self.timer.stop()
            _set_battle_active(False)
            self.battle_ended.emit()
        super().closeEvent(event)

    # ── Input ─────────────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k = event.key()
        if k in self.keys:
            self.keys[k] = True

        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z):
            if self.state == self.STATE_PLAYER_TURN:
                play_8bit_sound("select")
                self.trigger_fight_action()
        elif k == Qt.Key_Escape:
            self._finish(None)

    def keyReleaseEvent(self, event):
        k = event.key()
        if k in self.keys:
            self.keys[k] = False

    def focusOutEvent(self, event):
        for k in self.keys:
            self.keys[k] = False
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()
        if self.state == self.STATE_PLAYER_TURN:
            if self._get_fight_button_rect().contains(event.position()):
                play_8bit_sound("select")
                self.trigger_fight_action()

    # ── Rendering ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        painter.translate(self.shake_offset)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        if self.state == self.STATE_ENCOUNTER:
            self._draw_encounter_shatter(painter)
            painter.end()
            return

        self._draw_robi_boss(painter)

        if self.state == self.STATE_DIALOGUE:
            self._draw_speech_bubble(painter)

        self._draw_battle_box(painter)

        if self.state == self.STATE_PLAYER_TURN:
            self._draw_player_menu(painter)
        elif self.state == self.STATE_DODGE:
            self._draw_dodge_turn(painter)
        elif self.state == self.STATE_SLASH:
            self._draw_slash(painter)
        elif self.state == self.STATE_GAME_OVER:
            self._draw_death_shards(painter)

        self._draw_hud(painter)

        if self.damage_popup:
            self._draw_damage_popup(painter)

        if self.state == self.STATE_VICTORY:
            self._draw_victory_text(painter)
        painter.end()

    def _draw_encounter_shatter(self, painter: QPainter):
        if self.flash_white:
            painter.fillRect(self.rect(), QColor(255, 255, 255))
            return

        # Calculator window snapshot underneath the cracks
        if self.backdrop and not self.backdrop.isNull():
            painter.drawPixmap(self.rect(), self.backdrop)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        else:
            painter.fillRect(self.rect(), QColor(10, 15, 25))

        painter.setPen(QPen(QColor(220, 240, 255, 220), 2.5))
        for crack in self.shatter_cracks:
            for i in range(len(crack) - 1):
                painter.drawLine(crack[i], crack[i + 1])

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, "ROBI ENCOUNTER")

    def _draw_robi_boss(self, painter: QPainter):
        cx = self.width() / 2.0
        cy = self.height() * 0.22
        w, h = 140.0, 130.0
        rx, ry = cx - w / 2.0, cy - h / 2.0

        hp_ratio = self.robi_hp / float(self.max_robi_hp)
        if self.state == self.STATE_VICTORY:
            alpha = max(0.0, 1.0 - (self.state_time / 1.8))
        else:
            alpha = max(0.35, 0.35 + 0.65 * hp_ratio)
        painter.setOpacity(alpha)

        if self.state == self.STATE_VICTORY and self.pix_defeated_robi:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_defeated_robi)
        elif self.pix_angry_robi:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_angry_robi)
        else:
            painter.setPen(QPen(QColor(255, 255, 255), 2.5))
            painter.setBrush(QColor(30, 58, 138))
            painter.drawRoundedRect(QRectF(rx, ry, w, h), 16, 16)
            painter.setBrush(QColor(15, 23, 42))
            painter.drawRoundedRect(QRectF(rx + 15, ry + 22, w - 30, 32), 6, 6)
            painter.setBrush(QColor(34, 211, 238))
            painter.drawRect(QRectF(rx + 25, ry + 32, 25, 12))
            painter.drawRect(QRectF(rx + w - 50, ry + 32, 25, 12))
        painter.setOpacity(1.0)

        # HP bar
        bar_w, bar_h = 180.0, 10.0
        bar_x = cx - bar_w / 2.0
        bar_y = cy + h / 2.0 + 14.0
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(QColor(30, 30, 30))
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(37, 99, 235))
        painter.drawRect(QRectF(bar_x + 1, bar_y + 1, max(0.0, (bar_w - 2) * hp_ratio), bar_h - 2))

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(QRectF(bar_x, bar_y - 18, bar_w, 16), Qt.AlignCenter,
                         f"ROBI HP  {self.robi_hp} / {self.max_robi_hp}")

    def _draw_speech_bubble(self, painter: QPainter):
        cx = self.width() / 2.0
        cy = self.height() * 0.20
        bw, bh = 210.0, 74.0
        bx, by = cx + 85.0, cy - 30.0

        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 10, 10)
        painter.drawPolygon(QPolygonF([QPointF(bx, by + 25), QPointF(bx - 14, by + 30), QPointF(bx, by + 38)]))

        painter.setPen(QColor(0, 0, 0))
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.drawText(QRectF(bx + 10, by + 6, bw - 20, bh - 12),
                         Qt.TextWordWrap | Qt.AlignVCenter, self.dialogue_text)

    def _draw_battle_box(self, painter: QPainter):
        painter.setPen(QPen(QColor(255, 255, 255), 4.0, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRect(self.box_cur_rect)

    def _get_fight_button_rect(self) -> QRectF:
        box = self.box_cur_rect
        btn_w, btn_h = 150.0, 42.0
        return QRectF(box.center().x() - btn_w / 2.0, box.bottom() - btn_h - 20.0, btn_w, btn_h)

    def _draw_player_menu(self, painter: QPainter):
        box = self.box_cur_rect
        btn_rect = self._get_fight_button_rect()

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 12))
        painter.drawText(QRectF(box.left() + 24, box.top() + 16, box.width() - 48, 30),
                         Qt.AlignLeft, "* Robi glares down at your math calculations.")

        painter.setPen(QPen(QColor(249, 115, 22), 2.5))
        painter.setBrush(QColor(20, 20, 20))
        painter.drawRoundedRect(btn_rect, 6, 6)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(249, 115, 22))
        painter.drawEllipse(QPointF(btn_rect.left() + 24, btn_rect.center().y()), 5, 5)

        painter.setPen(QColor(249, 115, 22))
        painter.setFont(QFont("Consolas", 16, QFont.Bold))
        painter.drawText(btn_rect, Qt.AlignCenter, "  [ FIGHT ]")

        painter.setPen(QColor(160, 160, 160))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(QRectF(box.left(), box.bottom() - 16, box.width(), 14),
                         Qt.AlignCenter, "SPACE / ENTER / CLICK to strike Robi (-20 HP)")

    def _draw_slash(self, painter: QPainter):
        cx = self.width() / 2.0
        cy = self.height() * 0.22
        w = h = 120.0
        rx, ry = cx - w / 2.0, cy - h / 2.0

        if self.slash_frames and self.slash_frame_idx < len(self.slash_frames):
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.slash_frames[self.slash_frame_idx])
        else:
            path = QPainterPath()
            path.moveTo(cx - 50.0, cy - 40.0)
            path.quadTo(cx - 10.0, cy + 20.0, cx + 50.0, cy + 40.0)
            painter.strokePath(path, QPen(QColor(255, 255, 255), 5.0))

    def _draw_dodge_turn(self, painter: QPainter):
        box = self.box_cur_rect

        # Player (blinks during i-frames)
        if not (self.iframe_time > 0 and int(self.iframe_time * 20) % 2 == 0):
            self._draw_player_calc(painter, self.px, self.py)

        # Projectiles clipped to the arena
        painter.save()
        painter.setClipRect(box.adjusted(2, 2, -2, -2))
        for p in self.projectiles:
            self._draw_projectile(painter, p)
        painter.restore()

        time_left = max(0.0, self.wave_duration - self.wave_timer)
        painter.setPen(QColor(34, 211, 238))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(QRectF(box.left(), box.top() - 20, box.width(), 16),
                         Qt.AlignRight, f"DODGE: {time_left:.1f}s")

    def _draw_player_calc(self, painter: QPainter, x: float, y: float):
        w, h = self.calc_w, self.calc_h
        rx, ry = x - w / 2.0, y - h / 2.0

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
                painter.drawRect(QRectF(rx + 4 + c * 4.5, ry + 12 + r * 4.5, 3, 3))

    def _draw_projectile(self, painter: QPainter, p: Projectile):
        painter.save()
        painter.translate(p.x, p.y)
        painter.rotate(p.rot)

        if p.pixmap:
            # Keep aspect ratio: fit longest side to p.size
            pw, ph = p.pixmap.width(), p.pixmap.height()
            scale = p.size / float(max(pw, ph))
            dw, dh = int(pw * scale), int(ph * scale)
            painter.drawPixmap(-dw // 2, -dh // 2, dw, dh, p.pixmap)
        else:
            painter.setPen(QPen(QColor(255, 255, 255), 2.0))
            painter.setFont(QFont("Segoe UI", int(p.size * 0.6), QFont.Bold))
            painter.drawText(QRectF(-p.size / 2.0, -p.size / 2.0, p.size, p.size),
                             Qt.AlignCenter, p.symbol)
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
        painter.setFont(QFont("Consolas", 20, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter,
                         "CALCULATOR SHATTERED!\n\nRobi proved superior.\nWiping equation...")

    def _draw_hud(self, painter: QPainter):
        y = self.height() - 34.0
        cx = self.width() / 2.0

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Consolas", 13, QFont.Bold))
        painter.drawText(QPointF(cx - 180, y + 14), "CALC   LV 1")
        painter.drawText(QPointF(cx - 60, y + 14), "HP")

        bar_w, bar_h = 90.0, 16.0
        bar_x = cx - 25.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(190, 18, 60))
        painter.drawRect(QRectF(bar_x, y, bar_w, bar_h))
        painter.setBrush(QColor(250, 204, 21))
        painter.drawRect(QRectF(bar_x, y, bar_w * max(0.0, self.player_hp / float(self.max_player_hp)), bar_h))

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QPointF(cx + 80, y + 14), f"{self.player_hp} / {self.max_player_hp}")

    def _draw_damage_popup(self, painter: QPainter):
        txt, t_left, x, y = self.damage_popup
        painter.setPen(QColor(239, 68, 68, max(0, min(255, int(t_left * 255)))))
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.drawText(QRectF(x - 60, y - 15, 120, 30), Qt.AlignCenter, txt)

    def _draw_victory_text(self, painter: QPainter):
        title_y = int(self.height() * 0.56)
        painter.setPen(QColor(34, 197, 94))
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.drawText(QRectF(0, title_y, self.width(), 36), Qt.AlignCenter, "VICTORY!")

        painter.setFont(QFont("Consolas", 20, QFont.Bold))
        metrics = painter.fontMetrics()
        line_one = "I lost...I cant believe it..."
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            QPointF((self.width() - metrics.horizontalAdvance(line_one)) / 2, title_y + 70),
            line_one,
        )

        prefix = "maybe "
        highlighted = "I am stupid"
        suffix = ".."
        prefix_width = metrics.horizontalAdvance(prefix)
        highlighted_width = metrics.horizontalAdvance(highlighted)
        line_width = prefix_width + highlighted_width + metrics.horizontalAdvance(suffix)
        start_x = (self.width() - line_width) / 2
        baseline = title_y + 105

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(37, 99, 235, 90))
        painter.drawRoundedRect(
            QRectF(
                start_x + prefix_width - 5,
                baseline - metrics.ascent() - 3,
                highlighted_width + 10,
                metrics.height() + 6,
            ),
            5,
            5,
        )
        painter.setBrush(Qt.NoBrush)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QPointF(start_x, baseline), prefix)
        painter.setPen(QColor(96, 165, 250))
        painter.drawText(QPointF(start_x + prefix_width, baseline), highlighted)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QPointF(start_x + prefix_width + highlighted_width, baseline), suffix)