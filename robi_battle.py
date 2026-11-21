# robi_battle.py - Undertale Phase 1 + Pokemon Phase 2 Boss Fight
import os
import sys
import math
import random
import struct
from typing import List, Optional, Tuple, Callable

from shiboken6 import isValid
from PySide6.QtCore import (
    Qt, QTimer, QRect, QRectF, QPointF, Signal, QElapsedTimer, QUrl,
    QByteArray, QBuffer, QIODevice, QPropertyAnimation, QEasingCurve,
    QCoreApplication, qWarning
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QPainterPath, QPolygonF, QPixmap, QBrush, QLinearGradient
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
UNDERTALE_SFX_VOLUME = 0.30
BATTLE_MUSIC_VOLUME = 0.75
_ACTIVE_SFX_SINKS: List[QAudioSink] = []
_ACTIVE_SFX_PLAYERS: List[QMediaPlayer] = []

_SFX_TONES = {
    "slash": [(1800, 40), (900, 60)],
    "hurt": [(240, 80)],
    "shatter": [(800, 40), (500, 60), (250, 120)],
    "select": [(1100, 50)],
    "charge": [(300, 90), (500, 70), (900, 140)],
    "pokemon_encounter": [(523, 70), (659, 70), (784, 70), (1046, 120)],
    "pokemon_hit": [(420, 60), (260, 80)],
    "pokemon_crit": [(550, 50), (800, 70), (1100, 100)],
    "pokemon_stat": [(850, 50), (700, 60), (550, 80)],
    "pokemon_faint": [(550, 80), (400, 100), (280, 140)],
}

_SFX_MEDIA = {
    "encounter": "robi_encounter_shatter.mp4",
    "hit_robi": "robi_hit_sound.mp4",
}


def play_8bit_sound(sound_type: str):
    media_filename = _SFX_MEDIA.get(sound_type)
    if media_filename:
        media_path = get_asset_path(media_filename)
        if not os.path.isfile(media_path):
            raise FileNotFoundError(f"Battle sound effect asset not found: {media_path}")

        app = QCoreApplication.instance()
        if app is None:
            raise RuntimeError("Battle sound effects require a Qt application instance")

        player = QMediaPlayer(app)
        output = QAudioOutput(player)
        output.setVolume(UNDERTALE_SFX_VOLUME)
        player.setAudioOutput(output)

        def release_player():
            if player in _ACTIVE_SFX_PLAYERS:
                _ACTIVE_SFX_PLAYERS.remove(player)
                player.stop()
                player.deleteLater()

        cleanup_timer = QTimer(player)
        cleanup_timer.setSingleShot(True)
        cleanup_timer.timeout.connect(release_player)

        def schedule_cleanup(duration_ms: int):
            if duration_ms > 0 and not cleanup_timer.isActive():
                cleanup_timer.start(duration_ms + 250)

        def on_media_status_changed(status):
            if status == QMediaPlayer.MediaStatus.EndOfMedia:
                release_player()

        def on_media_error(error, error_string: str):
            qWarning(f"Battle sound effect playback failed ({error}): {error_string}")
            release_player()

        player.mediaStatusChanged.connect(on_media_status_changed)
        player.durationChanged.connect(schedule_cleanup)
        player.errorOccurred.connect(on_media_error)
        _ACTIVE_SFX_PLAYERS.append(player)
        player.setSource(QUrl.fromLocalFile(media_path))
        player.play()
        return

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


class LaserPillar:
    """High-frequency Gaster Blaster overlay pillar."""
    def __init__(self, direction: str, pos: float, box_rect: QRectF, symbol_pixmaps: List[QPixmap]):
        self.direction = direction  # "horizontal", "vertical", "diagonal_lr", "diagonal_rl"
        self.pos = pos
        self.box_rect = QRectF(box_rect)
        self.symbol_pixmaps = symbol_pixmaps
        self.phase = "telegraph"   # "telegraph" (0.65s) -> "blast" (0.45s) -> "done"
        self.phase_time = 0.0
        self.telegraph_duration = 0.65
        self.blast_duration = 0.45
        self.alpha = 200
        self.blast_spawned = False
        self.done = False

    def update(self, dt: float, parent: "RobiBattleOverlay"):
        self.phase_time += dt
        if self.phase == "telegraph":
            self.alpha = int(140 + 115 * math.sin(self.phase_time * 16.0))
            if self.phase_time >= self.telegraph_duration:
                self.phase = "blast"
                self.phase_time = 0.0
        elif self.phase == "blast":
            if not self.blast_spawned:
                self.blast_spawned = True
                self.spawn_blast(parent)
            self.alpha = 230
            if self.phase_time >= self.blast_duration:
                self.done = True

    def spawn_blast(self, parent: "RobiBattleOverlay"):
        box = parent.box_cur_rect
        spacing = 18.0
        speed = 320.0
        symbols = ["+", "-", "×", "÷"]
        d = self.direction
        if d == "horizontal":
            y = self.pos
            x = box.left() - spacing
            while x <= box.right() + spacing:
                pix = random.choice(self.symbol_pixmaps) if self.symbol_pixmaps else None
                sym = random.choice(symbols)
                p = Projectile(x, y, speed, 0.0, pix, sym, 22.0)
                p.vrot = 0.0
                parent.projectiles.append(p)
                x += spacing
        elif d == "vertical":
            x = self.pos
            y = box.top() - spacing
            while y <= box.bottom() + spacing:
                pix = random.choice(self.symbol_pixmaps) if self.symbol_pixmaps else None
                sym = random.choice(symbols)
                p = Projectile(x, y, 0.0, speed, pix, sym, 22.0)
                p.vrot = 0.0
                parent.projectiles.append(p)
                y += spacing
        elif d == "diagonal_lr":
            nx, ny = 0.7071, 0.7071
            sx, sy = box.left() - spacing, box.top() - spacing
            dist = math.hypot(box.width() + spacing * 2, box.height() + spacing * 2)
            t = 0.0
            while t <= dist:
                px = sx + nx * t
                py = sy + ny * t
                pix = random.choice(self.symbol_pixmaps) if self.symbol_pixmaps else None
                sym = random.choice(symbols)
                p = Projectile(px, py, speed * nx, speed * ny, pix, sym, 22.0)
                p.vrot = 0.0
                parent.projectiles.append(p)
                t += spacing
        else:  # diagonal_rl
            nx, ny = -0.7071, 0.7071
            sx, sy = box.right() + spacing, box.top() - spacing
            dist = math.hypot(box.width() + spacing * 2, box.height() + spacing * 2)
            t = 0.0
            while t <= dist:
                px = sx + nx * t
                py = sy + ny * t
                pix = random.choice(self.symbol_pixmaps) if self.symbol_pixmaps else None
                sym = random.choice(symbols)
                p = Projectile(px, py, speed * nx, speed * ny, pix, sym, 22.0)
                p.vrot = 0.0
                parent.projectiles.append(p)
                t += spacing


class PokemonTypewriter:
    """Typewriter text animator with prompt arrow."""
    def __init__(self):
        self.full_text = ""
        self.displayed_text = ""
        self.char_idx = 0
        self.char_timer = 0.0
        self.char_speed = 0.022
        self.is_done = False
        self.auto_advance_delay = 0.0
        self.elapsed_after_done = 0.0

    def set_text(self, text: str, auto_advance: float = 0.0):
        self.full_text = text
        self.displayed_text = ""
        self.char_idx = 0
        self.char_timer = 0.0
        self.is_done = False
        self.auto_advance_delay = auto_advance
        self.elapsed_after_done = 0.0

    def update(self, dt: float) -> bool:
        """Returns True when auto-advance time has elapsed."""
        if not self.is_done:
            self.char_timer += dt
            while self.char_timer >= self.char_speed and self.char_idx < len(self.full_text):
                self.char_timer -= self.char_speed
                self.char_idx += 1
                self.displayed_text = self.full_text[:self.char_idx]
            if self.char_idx >= len(self.full_text):
                self.is_done = True
        else:
            if self.auto_advance_delay > 0:
                self.elapsed_after_done += dt
                if self.elapsed_after_done >= self.auto_advance_delay:
                    return True
        return False

    def skip(self):
        self.char_idx = len(self.full_text)
        self.displayed_text = self.full_text
        self.is_done = True


class RobiBattleOverlay(QWidget):
    """
    Undertale Boss Fight (Phase 1) + Pokemon Turn-Based Battle (Phase 2).
    Signals:
        battle_won()   - Robi defeated in Phase 2
        battle_lost()  - Player HP reached 0 in Phase 1 or 2
        battle_ended() - Overlay closed (always emitted once, win/lose/esc)
    """
    battle_won = Signal()
    battle_lost = Signal()
    battle_ended = Signal()

    STATE_ENCOUNTER = "ENCOUNTER"
    STATE_PLAYER_TURN = "PLAYER_TURN"
    STATE_SLASH = "SLASH"
    STATE_DIALOGUE = "DIALOGUE"
    STATE_DODGE = "DODGE"
    STATE_FAKEOUT = "FAKEOUT"
    STATE_POKEMON_TRANSITION = "POKEMON_TRANSITION"
    STATE_POKEMON_BATTLE = "POKEMON_BATTLE"
    STATE_VICTORY = "VICTORY"
    STATE_GAME_OVER = "GAME_OVER"

    # Pokemon Substates
    POKE_INTRO_1 = "POKE_INTRO_1"
    POKE_INTRO_2 = "POKE_INTRO_2"
    POKE_ACTION_SELECT = "POKE_ACTION_SELECT"
    POKE_MOVE_SELECT = "POKE_MOVE_SELECT"
    POKE_REJECTION_TEXT = "POKE_REJECTION_TEXT"
    POKE_TEXT_SEQUENCE = "POKE_TEXT_SEQUENCE"
    POKE_ROBI_FAINT = "POKE_ROBI_FAINT"
    POKE_PLAYER_FAINT = "POKE_PLAYER_FAINT"

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

        # Phase 1 Stats
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

        # Phase 1 Attack waves
        self.projectiles: List[Projectile] = []
        self.wave_timer = 0.0
        self.wave_duration = 7.0
        self.wave_spawn_acc = 0.0
        self.dodge_wave_index = 0

        # High-Frequency Gaster Blaster Overlay
        self.active_lasers: List[LaserPillar] = []
        self.laser_overlay_timer = 0.0
        self.next_laser_time = random.uniform(1.2, 1.8)

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

        # ── Pokemon Phase 2 State ─────────────────────────────────────────────
        self.poke_substate = self.POKE_INTRO_1
        self.poke_typewriter = PokemonTypewriter()
        self.poke_queue: List[Tuple[str, Optional[Callable[[], None]]]] = []

        self.poke_player_max_hp = 100
        self.poke_player_hp = 100
        self.poke_player_display_hp = 100.0

        self.poke_robi_max_hp = 100
        self.poke_robi_hp = 100
        self.poke_robi_display_hp = 100.0

        self.poke_turn_count = 1
        self.poke_player_confused_turns = 0
        self.poke_robi_ego_lowered = False
        self.poke_last_player_move = ""

        # UI selection indices
        self.poke_action_cursor = 0  # 0=FIGHT, 1=BAG, 2=CALC, 3=RUN
        self.poke_move_cursor = 0    # 0=DIVIDE BY ZERO, 1=CLEAR ENTRY, 2=PEMDAS SLAM, 3=FACT CHECK

        self.poke_player_moves = [
            {"name": "DIVIDE BY ZERO", "type": "CHAOS", "pp": 10, "max_pp": 10, "pwr": 35},
            {"name": "CLEAR ENTRY",    "type": "MATH",  "pp": 10, "max_pp": 10, "pwr": 20},
            {"name": "PEMDAS SLAM",    "type": "LOGIC", "pp": 10, "max_pp": 10, "pwr": 15},
            {"name": "FACT CHECK",     "type": "LOGIC", "pp": 10, "max_pp": 10, "pwr": 0},
        ]

        self.poke_robi_faint_y = 0.0
        self.poke_player_faint_y = 0.0
        self.poke_enemy_flash_timer = 0.0
        self.poke_player_flash_timer = 0.0

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
            play_8bit_sound("encounter")
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
            self.STATE_FAKEOUT: self._update_fakeout,
            self.STATE_POKEMON_TRANSITION: self._update_pokemon_transition,
            self.STATE_POKEMON_BATTLE: self._update_pokemon_battle,
            self.STATE_VICTORY: self._update_victory,
            self.STATE_GAME_OVER: self._update_game_over,
        }.get(self.state)
        if handler:
            handler(dt)

        self.update()

    # ── Phase 1 Undertale States ──────────────────────────────────────────────
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
                # ── Fake-Out Transition: swap to Defeated Robi + speech bubble ──
                self.state = self.STATE_FAKEOUT
                self.dialogue_text = "I still got one more in me."
                self.projectiles.clear()
                self.active_lasers.clear()
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
            self.dodge_wave_index += 1
            # Waves alternate: A (odd) = Scattered, B (even) = Gapped Rows
            if self.dodge_wave_index % 2 == 0:
                self.wave_spawn_acc = 1.05
            else:
                self.wave_spawn_acc = 0.0
            self.laser_overlay_timer = 0.0
            self.next_laser_time = random.uniform(1.2, 1.8)
            self.projectiles.clear()
            self.active_lasers.clear()
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

        # Alternating Wave Logic (7 seconds per wave)
        # Wave A (odd index): Scattered Chaos
        # Wave B (even index): Gapped Falling Rows
        is_wave_b = (self.dodge_wave_index % 2 == 0)
        self.wave_spawn_acc += dt

        if is_wave_b:
            column_interval = 1.05
            if self.wave_spawn_acc >= column_interval:
                self.wave_spawn_acc = 0.0
                self._spawn_wave_b_gapped_rows()
        else:
            spawn_rate = max(0.12, 0.28 - self.hits_landed * 0.03)
            if self.wave_spawn_acc >= spawn_rate:
                self.wave_spawn_acc = 0.0
                self._spawn_wave_a_scattered()

        # ── High-Frequency Gaster Blaster Overlay (Every 1.5 - 2.0s across ALL waves) ──
        self.laser_overlay_timer += dt
        if self.laser_overlay_timer >= self.next_laser_time:
            self.laser_overlay_timer = 0.0
            self.next_laser_time = random.uniform(1.5, 2.0)
            burst_count = random.choice([1, 2])
            for _ in range(burst_count):
                d = random.choice(["horizontal", "vertical", "diagonal_lr", "diagonal_rl"])
                if d == "horizontal":
                    pos = random.uniform(box.top() + 20, box.bottom() - 20)
                else:
                    pos = random.uniform(box.left() + 20, box.right() - 20)
                self.active_lasers.append(LaserPillar(d, pos, box, self.symbol_pixmaps))
            play_8bit_sound("charge")

        for l in self.active_lasers:
            l.update(dt, self)
        self.active_lasers = [l for l in self.active_lasers if not l.done]

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
                box.top() - 140 <= p.y <= box.bottom() + 70)
        ]

        if self.wave_timer >= self.wave_duration:
            self.projectiles.clear()
            self.active_lasers.clear()
            self.state = self.STATE_PLAYER_TURN
            self.state_time = 0.0
            self._set_menu_box()

    def _spawn_wave_a_scattered(self):
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

    def _spawn_wave_b_gapped_rows(self):
        box = self.box_cur_rect
        sym_size = 24.0
        sym_spacing = 30.0
        safe_gap = max(55.0, self.calc_w * 2.5)
        vy = random.uniform(115.0, 135.0)
        symbols = ["+", "-", "×", "÷"]
        bw = max(box.width(), safe_gap + sym_spacing)

        gap_max_start = bw - safe_gap
        gap_start = random.uniform(0.0, max(0.0, gap_max_start))
        gap_end = gap_start + safe_gap

        num_steps = int((bw + sym_size) / sym_spacing) + 2
        for i in range(num_steps):
            rel_x = i * sym_spacing
            abs_x = box.left() + rel_x
            if abs_x > box.right() + sym_size:
                break
            if gap_start - 0.5 <= rel_x < gap_end + 0.5:
                continue
            pix = random.choice(self.symbol_pixmaps) if self.symbol_pixmaps else None
            sym = random.choice(symbols)
            proj = Projectile(abs_x, box.top() - sym_size, 0.0, vy, pix, sym, sym_size)
            proj.vrot = 0.0
            self.projectiles.append(proj)

    # ── Fake-Out & Transition States ──────────────────────────────────────────
    def _update_fakeout(self, dt):
        if self.state_time >= 2.0:
            self.state = self.STATE_POKEMON_TRANSITION
            self.state_time = 0.0
            play_8bit_sound("pokemon_encounter")

    def _update_pokemon_transition(self, dt):
        if self.state_time >= 1.4:
            self._init_pokemon_battle()
            self.state = self.STATE_POKEMON_BATTLE

    # ── Phase 2 Pokemon Battle Logic ──────────────────────────────────────────
    def _init_pokemon_battle(self):
        self.state_time = 0.0
        self.poke_player_max_hp = 100
        self.poke_player_hp = 100
        self.poke_player_display_hp = 100.0

        self.poke_robi_max_hp = 100
        self.poke_robi_hp = 100
        self.poke_robi_display_hp = 100.0

        self.poke_turn_count = 1
        self.poke_player_confused_turns = 0
        self.poke_robi_ego_lowered = False
        self.poke_last_player_move = ""
        self.poke_action_cursor = 0
        self.poke_move_cursor = 0
        self.poke_robi_faint_y = 0.0
        self.poke_player_faint_y = 0.0
        self.poke_enemy_flash_timer = 0.0
        self.poke_player_flash_timer = 0.0
        self.poke_queue.clear()
        self._post_faint_callback = None

        self.poke_substate = self.POKE_INTRO_1
        self.poke_typewriter.set_text("ROBI wants to fight!", auto_advance=1.6)

    def _update_pokemon_battle(self, dt):
        # Smooth HP bar animations
        hp_speed = 50.0 * dt
        if self.poke_player_display_hp > self.poke_player_hp:
            self.poke_player_display_hp = max(float(self.poke_player_hp), self.poke_player_display_hp - hp_speed)
        elif self.poke_player_display_hp < self.poke_player_hp:
            self.poke_player_display_hp = min(float(self.poke_player_hp), self.poke_player_display_hp + hp_speed)

        if self.poke_robi_display_hp > self.poke_robi_hp:
            self.poke_robi_display_hp = max(float(self.poke_robi_hp), self.poke_robi_display_hp - hp_speed)
        elif self.poke_robi_display_hp < self.poke_robi_hp:
            self.poke_robi_display_hp = min(float(self.poke_robi_hp), self.poke_robi_display_hp + hp_speed)

        if self.poke_enemy_flash_timer > 0:
            self.poke_enemy_flash_timer = max(0.0, self.poke_enemy_flash_timer - dt)
        if self.poke_player_flash_timer > 0:
            self.poke_player_flash_timer = max(0.0, self.poke_player_flash_timer - dt)

        # Substate updates
        if self.poke_substate in (self.POKE_INTRO_1, self.POKE_INTRO_2, self.POKE_REJECTION_TEXT, self.POKE_TEXT_SEQUENCE):
            auto_done = self.poke_typewriter.update(dt)
            if auto_done:
                self._advance_pokemon_text()

        elif self.poke_substate == self.POKE_ROBI_FAINT:
            self.poke_robi_faint_y = min(120.0, self.poke_robi_faint_y + 160.0 * dt)
            if self.poke_typewriter.update(dt):
                self._advance_pokemon_text()

        elif self.poke_substate == self.POKE_PLAYER_FAINT:
            self.poke_player_faint_y = min(120.0, self.poke_player_faint_y + 160.0 * dt)
            if self.poke_typewriter.update(dt):
                self._advance_pokemon_text()

    def _advance_pokemon_text(self):
        if self.poke_substate == self.POKE_INTRO_1:
            self.poke_substate = self.POKE_INTRO_2
            self.poke_typewriter.set_text("ROBI sent out ANGRY ROBI!", auto_advance=1.6)

        elif self.poke_substate == self.POKE_INTRO_2:
            self.poke_substate = self.POKE_ACTION_SELECT
            self.poke_typewriter.set_text("What will LARPULATER do?")

        elif self.poke_substate == self.POKE_REJECTION_TEXT:
            self.poke_substate = self.POKE_ACTION_SELECT
            self.poke_typewriter.set_text("What will LARPULATER do?")

        elif self.poke_substate == self.POKE_ROBI_FAINT:
            if self.poke_queue:
                next_text, callback = self.poke_queue.pop(0)
                self._post_faint_callback = callback
                self.poke_typewriter.set_text(next_text, auto_advance=2.5)
            else:
                if getattr(self, '_post_faint_callback', None):
                    cb = self._post_faint_callback
                    self._post_faint_callback = None
                    cb()
                else:
                    self._trigger_victory_screen()

        elif self.poke_substate == self.POKE_PLAYER_FAINT:
            if self.poke_queue:
                next_text, callback = self.poke_queue.pop(0)
                self._post_faint_callback = callback
                self.poke_typewriter.set_text(next_text, auto_advance=2.0)
            else:
                if getattr(self, '_post_faint_callback', None):
                    cb = self._post_faint_callback
                    self._post_faint_callback = None
                    cb()
                else:
                    self._trigger_player_loss()

        elif self.poke_substate == self.POKE_TEXT_SEQUENCE:
            if self.poke_queue:
                next_text, callback = self.poke_queue.pop(0)
                if callback:
                    callback()
                self.poke_typewriter.set_text(next_text, auto_advance=1.8)
            else:
                # Sequence done, check win/loss or return to action select
                if self.poke_robi_hp <= 0:
                    self.poke_substate = self.POKE_ROBI_FAINT
                    play_8bit_sound("pokemon_faint")
                    self.poke_typewriter.set_text("Wild ANGRY ROBI fainted!", auto_advance=1.8)
                    self.poke_queue = [
                        ("ROBI dropped the victory passphrase:\n\"because i am stupid\"", self._trigger_victory_screen)
                    ]
                elif self.poke_player_hp <= 0:
                    self.poke_substate = self.POKE_PLAYER_FAINT
                    play_8bit_sound("pokemon_faint")
                    self.poke_typewriter.set_text("LARPULATER fainted! You blacked out!", auto_advance=2.0)
                    self.poke_queue = [
                        ("Restarting calculator...", self._trigger_player_loss)
                    ]
                else:
                    self.poke_substate = self.POKE_ACTION_SELECT
                    self.poke_typewriter.set_text("What will LARPULATER do?")

    def _trigger_victory_screen(self):
        self.state = self.STATE_VICTORY
        self.state_time = 0.0
        self._fade_battle_music(0.0, 1500, stop_after=True)

    def _trigger_player_loss(self):
        self._finish(False)

    def _on_pokemon_action_confirm(self):
        play_8bit_sound("select")
        act = self.poke_action_cursor
        if act == 0:    # FIGHT
            self.poke_substate = self.POKE_MOVE_SELECT
            self.poke_move_cursor = 0
        elif act == 1:  # BAG
            self.poke_substate = self.POKE_REJECTION_TEXT
            self.poke_typewriter.set_text("Your Bag is empty—you're broke!", auto_advance=1.8)
        elif act == 2:  # CALC
            self.poke_substate = self.POKE_REJECTION_TEXT
            self.poke_typewriter.set_text("No other calculators in your party!", auto_advance=1.8)
        elif act == 3:  # RUN
            self.poke_substate = self.POKE_REJECTION_TEXT
            self.poke_typewriter.set_text("Can't escape! Robi blocked the exit with math!", auto_advance=1.8)

    def _on_pokemon_move_confirm(self):
        play_8bit_sound("select")
        move_idx = self.poke_move_cursor
        move = self.poke_player_moves[move_idx]
        move["pp"] = max(0, move["pp"] - 1)

        self.poke_queue = []
        self.poke_substate = self.POKE_TEXT_SEQUENCE

        # 1. Confusion Check
        if self.poke_player_confused_turns > 0:
            self.poke_player_confused_turns -= 1
            if random.random() < 0.33:
                def _hurt_self():
                    self.poke_player_hp = max(0, self.poke_player_hp - 10)
                    self.screen_shake = 6.0
                    self.poke_player_flash_timer = 0.4
                    play_8bit_sound("pokemon_hit")
                self.poke_typewriter.set_text("LARPULATER is confused!", auto_advance=1.3)
                self.poke_queue.append(("It hurt itself in its confusion (-10 HP)!", _hurt_self))
                # Skip attack and go straight to Robi's turn if player survived
                if self.poke_player_hp - 10 > 0:
                    self._queue_robi_turn()
                return

        # 2. Player Move Execution
        mult = 1.5 if self.poke_robi_ego_lowered else 1.0

        if move["name"] == "DIVIDE BY ZERO":
            dmg = int(35 * mult)
            recoil = (random.random() < 0.30)
            def _apply_div():
                self.poke_robi_hp = max(0, self.poke_robi_hp - dmg)
                self.screen_shake = 9.0
                self.poke_enemy_flash_timer = 0.5
                play_8bit_sound("pokemon_crit" if mult > 1.0 else "pokemon_hit")
                self.poke_robi_ego_lowered = False

            self.poke_typewriter.set_text(f"LARPULATER used DIVIDE BY ZERO!\nDealt {dmg} CHAOS damage!", auto_advance=1.6)
            self.poke_queue.append(("", _apply_div))

            if recoil:
                def _apply_recoil():
                    self.poke_player_hp = max(0, self.poke_player_hp - 15)
                    self.screen_shake = 6.0
                    self.poke_player_flash_timer = 0.4
                    play_8bit_sound("hurt")
                self.poke_queue.append(("LARPULATER divided by zero!\nIt hurt itself in a stack overflow (-15 HP)!", _apply_recoil))

        elif move["name"] == "CLEAR ENTRY":
            dmg = int(20 * mult)
            def _apply_ce():
                self.poke_robi_hp = max(0, self.poke_robi_hp - dmg)
                self.screen_shake = 5.0
                self.poke_enemy_flash_timer = 0.4
                play_8bit_sound("pokemon_hit")
                self.poke_robi_ego_lowered = False

            self.poke_typewriter.set_text(f"LARPULATER used CLEAR ENTRY (CE)!\nDealt {dmg} MATH damage!", auto_advance=1.6)
            self.poke_queue.append(("", _apply_ce))

        elif move["name"] == "PEMDAS SLAM":
            is_crit = (self.poke_last_player_move == "FACT CHECK")
            base_pwr = 30 if is_crit else 15
            dmg = int(base_pwr * mult)
            def _apply_pemdas():
                self.poke_robi_hp = max(0, self.poke_robi_hp - dmg)
                self.screen_shake = 10.0 if is_crit else 5.0
                self.poke_enemy_flash_timer = 0.5
                play_8bit_sound("pokemon_crit" if is_crit else "pokemon_hit")
                self.poke_robi_ego_lowered = False

            if is_crit:
                msg = f"LARPULATER followed order of operations!\nA critical hit dealing {dmg} damage!"
            else:
                msg = f"LARPULATER used PEMDAS SLAM!\nDealt {dmg} LOGIC damage!"
            self.poke_typewriter.set_text(msg, auto_advance=1.6)
            self.poke_queue.append(("", _apply_pemdas))

        elif move["name"] == "FACT CHECK":
            def _apply_fact():
                self.poke_robi_ego_lowered = True
                self.poke_player_confused_turns = 0
                play_8bit_sound("pokemon_stat")
            self.poke_typewriter.set_text("LARPULATER used FACT CHECK!\nRobi's Ego plummeted! (Next hit: +50% DMG)\nConfusion cured!", auto_advance=1.8)
            self.poke_queue.append(("", _apply_fact))

        self.poke_last_player_move = move["name"]

        # Queue Robi Turn if Robi will survive
        self._queue_robi_turn()

    def _queue_robi_turn(self):
        # AI decision
        turn = self.poke_turn_count
        self.poke_turn_count += 1

        use_gaslight = False
        if turn == 1 or self.poke_last_player_move == "FACT CHECK":
            use_gaslight = True
        elif self.poke_player_confused_turns <= 0 and random.random() < 0.35:
            use_gaslight = True

        if use_gaslight:
            def _apply_gaslight():
                self.poke_player_confused_turns = random.randint(2, 3)
                play_8bit_sound("pokemon_stat")
            self.poke_queue.append(("ROBI used GASLIGHT!\n\"Your math is a delusion!\" LARPULATER became confused!", _apply_gaslight))
        else:
            attacks = [
                ("Move The Decimal", 20, "ROBI moved the decimal point!\nLARPULATER lost value (-20 HP)!"),
                ("Redact Steps",     25, "ROBI redacted LARPULATER's steps!\n\"Show your work!\" Robi sneered (-25 HP)!"),
                ("Delusion Blast",   30, "ROBI unleashed DELUSION BLAST!\nPure unhinged chaos (-30 HP)!"),
            ]
            r_name, r_dmg, r_msg = random.choice(attacks)
            def _apply_robi_atk(dmg=r_dmg):
                self.poke_player_hp = max(0, self.poke_player_hp - dmg)
                self.screen_shake = 7.0
                self.poke_player_flash_timer = 0.4
                play_8bit_sound("pokemon_hit")
            self.poke_queue.append((r_msg, _apply_robi_atk))

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
        if self.state_time >= 3.0:
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

    # ── Input Handlers ────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k = event.key()
        if k in self.keys:
            self.keys[k] = True

        if k == Qt.Key_Escape:
            if self.state == self.STATE_POKEMON_BATTLE and self.poke_substate == self.POKE_MOVE_SELECT:
                self.poke_substate = self.POKE_ACTION_SELECT
                self.poke_typewriter.set_text("What will LARPULATER do?")
                return
            self._finish(None)
            return

        # Phase 1 Input
        if self.state == self.STATE_PLAYER_TURN:
            if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z):
                play_8bit_sound("select")
                self.trigger_fight_action()
                return

        # Phase 2 Pokemon Input
        if self.state == self.STATE_POKEMON_BATTLE:
            if self.poke_substate in (self.POKE_INTRO_1, self.POKE_INTRO_2, self.POKE_REJECTION_TEXT, self.POKE_TEXT_SEQUENCE, self.POKE_ROBI_FAINT, self.POKE_PLAYER_FAINT):
                if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z):
                    if not self.poke_typewriter.is_done:
                        self.poke_typewriter.skip()
                    else:
                        self._advance_pokemon_text()
                return

            elif self.poke_substate == self.POKE_ACTION_SELECT:
                if k in (Qt.Key_Left, Qt.Key_A):
                    self.poke_action_cursor ^= 1
                    play_8bit_sound("select")
                elif k in (Qt.Key_Right, Qt.Key_D):
                    self.poke_action_cursor ^= 1
                    play_8bit_sound("select")
                elif k in (Qt.Key_Up, Qt.Key_W):
                    self.poke_action_cursor ^= 2
                    play_8bit_sound("select")
                elif k in (Qt.Key_Down, Qt.Key_S):
                    self.poke_action_cursor ^= 2
                    play_8bit_sound("select")
                elif k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z):
                    self._on_pokemon_action_confirm()

            elif self.poke_substate == self.POKE_MOVE_SELECT:
                if k in (Qt.Key_Left, Qt.Key_A):
                    self.poke_move_cursor ^= 1
                    play_8bit_sound("select")
                elif k in (Qt.Key_Right, Qt.Key_D):
                    self.poke_move_cursor ^= 1
                    play_8bit_sound("select")
                elif k in (Qt.Key_Up, Qt.Key_W):
                    self.poke_move_cursor ^= 2
                    play_8bit_sound("select")
                elif k in (Qt.Key_Down, Qt.Key_S):
                    self.poke_move_cursor ^= 2
                    play_8bit_sound("select")
                elif k in (Qt.Key_Backspace, Qt.Key_X):
                    self.poke_substate = self.POKE_ACTION_SELECT
                    self.poke_typewriter.set_text("What will LARPULATER do?")
                elif k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Z):
                    self._on_pokemon_move_confirm()

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
        pos = event.position()

        if self.state == self.STATE_PLAYER_TURN:
            if self._get_fight_button_rect().contains(pos):
                play_8bit_sound("select")
                self.trigger_fight_action()

        elif self.state == self.STATE_POKEMON_BATTLE:
            if self.poke_substate in (self.POKE_INTRO_1, self.POKE_INTRO_2, self.POKE_REJECTION_TEXT, self.POKE_TEXT_SEQUENCE, self.POKE_ROBI_FAINT, self.POKE_PLAYER_FAINT):
                if not self.poke_typewriter.is_done:
                    self.poke_typewriter.skip()
                else:
                    self._advance_pokemon_text()

            elif self.poke_substate == self.POKE_ACTION_SELECT:
                for idx, r in enumerate(self._get_pokemon_action_rects()):
                    if r.contains(pos):
                        self.poke_action_cursor = idx
                        self._on_pokemon_action_confirm()
                        break

            elif self.poke_substate == self.POKE_MOVE_SELECT:
                for idx, r in enumerate(self._get_pokemon_move_rects()):
                    if r.contains(pos):
                        self.poke_move_cursor = idx
                        self._on_pokemon_move_confirm()
                        break

    # ── Rendering ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        painter.translate(self.shake_offset)

        if self.state == self.STATE_POKEMON_TRANSITION:
            self._draw_pokemon_transition(painter)
            painter.end()
            return

        if self.state == self.STATE_POKEMON_BATTLE:
            self._draw_pokemon_battlefield(painter)
            painter.end()
            return

        painter.fillRect(self.rect(), QColor(0, 0, 0))

        if self.state == self.STATE_ENCOUNTER:
            self._draw_encounter_shatter(painter)
            painter.end()
            return

        self._draw_robi_boss(painter)

        if self.state in (self.STATE_DIALOGUE, self.STATE_FAKEOUT):
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

    # ── Phase 1 Draw Helpers ──────────────────────────────────────────────────
    def _draw_encounter_shatter(self, painter: QPainter):
        if self.flash_white:
            painter.fillRect(self.rect(), QColor(255, 255, 255))
            return

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
        alpha = max(0.35, 0.35 + 0.65 * hp_ratio) if self.state != self.STATE_FAKEOUT else 1.0
        painter.setOpacity(alpha)

        # In Fakeout, Robi's sprite is Defeated Robi
        if self.state == self.STATE_FAKEOUT and self.pix_defeated_robi:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_defeated_robi)
        elif self.pix_angry_robi:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_angry_robi)
        else:
            painter.setPen(QPen(QColor(255, 255, 255), 2.5))
            painter.setBrush(QColor(30, 58, 138))
            painter.drawRoundedRect(QRectF(rx, ry, w, h), 16, 16)
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
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
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

        # Draw active Gaster Blaster warning trajectory lines
        for l in self.active_lasers:
            if l.phase == "telegraph":
                self._draw_single_laser_telegraph(painter, box, l)

        # Player
        if not (self.iframe_time > 0 and int(self.iframe_time * 20) % 2 == 0):
            self._draw_player_calc(painter, self.px, self.py)

        # Projectiles
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

    def _draw_single_laser_telegraph(self, painter: QPainter, box: QRectF, laser: LaserPillar):
        alpha = max(0, min(255, laser.alpha))
        pen = QPen(QColor(255, 30, 30, alpha), 6.0, Qt.SolidLine, Qt.RoundCap)
        painter.save()
        painter.setClipRect(box.adjusted(2, 2, -2, -2))
        painter.setPen(pen)
        d = laser.direction
        if d == "horizontal":
            y = laser.pos
            painter.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        elif d == "vertical":
            x = laser.pos
            painter.drawLine(QPointF(x, box.top()), QPointF(x, box.bottom()))
        elif d == "diagonal_lr":
            painter.drawLine(QPointF(box.left(), box.top()), QPointF(box.right(), box.bottom()))
        else:  # diagonal_rl
            painter.drawLine(QPointF(box.right(), box.top()), QPointF(box.left(), box.bottom()))

        painter.setPen(QPen(QColor(255, 200, 200, min(255, alpha + 60)), 1.5, Qt.DashLine))
        if d == "horizontal":
            y = laser.pos
            painter.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        elif d == "vertical":
            x = laser.pos
            painter.drawLine(QPointF(x, box.top()), QPointF(x, box.bottom()))
        elif d == "diagonal_lr":
            painter.drawLine(QPointF(box.left(), box.top()), QPointF(box.right(), box.bottom()))
        else:
            painter.drawLine(QPointF(box.right(), box.top()), QPointF(box.left(), box.bottom()))
        painter.restore()

    def _draw_player_calc(self, painter: QPainter, x: float, y: float):
        w, h = self.calc_w, self.calc_h
        rx, ry = x - w / 2.0, y - h / 2.0

        if self.pix_player_calc:
            painter.drawPixmap(int(rx), int(ry), int(w), int(h), self.pix_player_calc)
            return

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

    # ── Pokemon Transition Draw Helper ────────────────────────────────────────
    def _draw_pokemon_transition(self, painter: QPainter):
        # 1. Background
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        t = self.state_time
        # Flash phase (0 - 0.4s)
        if t < 0.4:
            flash_idx = int(t / 0.08)
            if flash_idx % 2 == 0:
                painter.fillRect(self.rect(), QColor(255, 255, 255))
            else:
                painter.fillRect(self.rect(), QColor(0, 0, 0))
            return

        # Shutter / Wipe bars phase (0.4 - 1.4s)
        prog = min(1.0, (t - 0.4) / 0.9)
        num_bars = 10
        bar_h = self.height() / float(num_bars)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(15, 23, 42))

        for i in range(num_bars):
            y = i * bar_h
            bw = self.width() * prog
            if i % 2 == 0:
                painter.drawRect(QRectF(0, y, bw, bar_h + 1))
            else:
                painter.drawRect(QRectF(self.width() - bw, y, bw, bar_h + 1))

        # Center trainer encounter banner
        if t > 0.6:
            painter.setPen(QColor(250, 204, 21))
            painter.setFont(QFont("Consolas", 26, QFont.Bold))
            painter.drawText(self.rect(), Qt.AlignCenter, "POKÉMON BATTLE!")

    # ── Pokemon Phase 2 Battlefield Rendering ─────────────────────────────────
    def _draw_pokemon_battlefield(self, painter: QPainter):
        W, H = self.width(), self.height()

        # 1. Sky & Ground Gradient
        sky_grad = QLinearGradient(0, 0, 0, H * 0.65)
        sky_grad.setColorAt(0.0, QColor(220, 245, 255))
        sky_grad.setColorAt(1.0, QColor(240, 250, 245))
        painter.fillRect(QRectF(0, 0, W, H * 0.65), sky_grad)

        ground_grad = QLinearGradient(0, H * 0.65, 0, H)
        ground_grad.setColorAt(0.0, QColor(187, 247, 208))
        ground_grad.setColorAt(1.0, QColor(134, 239, 172))
        painter.fillRect(QRectF(0, H * 0.65, W, H * 0.35), ground_grad)

        # 2. Enemy Battle Platform (Top-Right)
        e_cx = W * 0.72
        e_cy = H * 0.32
        painter.setPen(QPen(QColor(22, 163, 74), 3.0))
        painter.setBrush(QColor(74, 222, 128))
        painter.drawEllipse(QPointF(e_cx, e_cy), 110, 36)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(21, 128, 61, 90))
        painter.drawEllipse(QPointF(e_cx, e_cy + 8), 104, 28)

        # Enemy Sprite (Angry Robi)
        e_bob = math.sin(self.state_time * 3.5) * 4.0
        e_sp_w, e_sp_h = 110.0, 110.0
        e_x = e_cx - e_sp_w / 2.0
        e_y = e_cy - e_sp_h + 10.0 + e_bob + self.poke_robi_faint_y

        if self.poke_enemy_flash_timer > 0 and int(self.poke_enemy_flash_timer * 20) % 2 == 1:
            pass  # Flash transparent on hit
        else:
            if self.pix_angry_robi:
                painter.drawPixmap(int(e_x), int(e_y), int(e_sp_w), int(e_sp_h), self.pix_angry_robi)
            else:
                painter.setPen(QPen(QColor(0, 0, 0), 2))
                painter.setBrush(QColor(30, 58, 138))
                painter.drawRoundedRect(QRectF(e_x, e_y, e_sp_w, e_sp_h), 12, 12)

        # 3. Enemy Status Box (Top-Left)
        self._draw_enemy_status_box(painter, W * 0.08, H * 0.08)

        # 4. Player Battle Platform (Bottom-Left)
        p_cx = W * 0.25
        p_cy = H * 0.63
        painter.setPen(QPen(QColor(100, 116, 139), 3.0))
        painter.setBrush(QColor(203, 213, 225))
        painter.drawEllipse(QPointF(p_cx, p_cy), 125, 40)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(148, 163, 184, 90))
        painter.drawEllipse(QPointF(p_cx, p_cy + 8), 118, 32)

        # Player Back-View Calculator Sprite
        p_sp_w, p_sp_h = 74.0, 90.0
        p_x = p_cx - p_sp_w / 2.0
        p_y = p_cy - p_sp_h + 14.0 + self.poke_player_faint_y

        if self.poke_player_flash_timer > 0 and int(self.poke_player_flash_timer * 20) % 2 == 1:
            pass
        else:
            self._draw_player_back_sprite(painter, p_x, p_y, p_sp_w, p_sp_h)

        # 5. Player Status Box (Bottom-Right)
        self._draw_player_status_box(painter, W * 0.56, H * 0.47)

        # 6. Bottom Dialogue & Command Deck
        self._draw_bottom_deck(painter)

    def _draw_enemy_status_box(self, painter: QPainter, x: float, y: float):
        w, h = 240.0, 72.0
        # Pokemon status card style: white fill, double dark border
        painter.setPen(QPen(QColor(31, 41, 55), 3.0))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(x, y, w, h), 8, 8)

        # Name & Level
        painter.setPen(QColor(17, 24, 39))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(QPointF(x + 12, y + 24), "ANGRY ROBI")

        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.setPen(QColor(234, 88, 12))
        painter.drawText(QPointF(x + w - 58, y + 24), "Lv.99")

        # HP bar frame
        bar_x = x + 44
        bar_y = y + 36
        bar_w = 176.0
        bar_h = 12.0

        painter.setPen(QColor(234, 179, 8))
        painter.setFont(QFont("Consolas", 9, QFont.Bold))
        painter.drawText(QPointF(x + 12, bar_y + 10), "HP")

        painter.setPen(QPen(QColor(31, 41, 55), 2.0))
        painter.setBrush(QColor(55, 65, 81))
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 4, 4)

        # Animated HP bar fill
        ratio = max(0.0, min(1.0, self.poke_robi_display_hp / 100.0))
        hp_color = QColor(34, 197, 94) if ratio > 0.50 else (QColor(234, 179, 8) if ratio > 0.20 else QColor(239, 68, 68))
        painter.setPen(Qt.NoPen)
        painter.setBrush(hp_color)
        painter.drawRoundedRect(QRectF(bar_x + 1, bar_y + 1, (bar_w - 2) * ratio, bar_h - 2), 3, 3)

        if self.poke_robi_ego_lowered:
            painter.setPen(QColor(220, 38, 38))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(QPointF(x + 12, y + 64), "▼ DEF DOWN (-50% Ego)")

    def _draw_player_status_box(self, painter: QPainter, x: float, y: float):
        w, h = 260.0, 84.0
        painter.setPen(QPen(QColor(31, 41, 55), 3.0))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(x, y, w, h), 8, 8)

        # Name & Level
        painter.setPen(QColor(17, 24, 39))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(QPointF(x + 14, y + 24), "LARPULATER")

        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.setPen(QColor(37, 99, 235))
        painter.drawText(QPointF(x + 130, y + 24), "Lv.1")

        if self.poke_player_confused_turns > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(168, 85, 247))
            painter.drawRoundedRect(QRectF(x + w - 66, y + 10, 52, 18), 4, 4)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Consolas", 8, QFont.Bold))
            painter.drawText(QRectF(x + w - 66, y + 10, 52, 18), Qt.AlignCenter, "CONF")

        # HP Bar
        bar_x = x + 44
        bar_y = y + 38
        bar_w = 196.0
        bar_h = 12.0

        painter.setPen(QColor(234, 179, 8))
        painter.setFont(QFont("Consolas", 9, QFont.Bold))
        painter.drawText(QPointF(x + 14, bar_y + 10), "HP")

        painter.setPen(QPen(QColor(31, 41, 55), 2.0))
        painter.setBrush(QColor(55, 65, 81))
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 4, 4)

        ratio = max(0.0, min(1.0, self.poke_player_display_hp / 100.0))
        hp_color = QColor(34, 197, 94) if ratio > 0.50 else (QColor(234, 179, 8) if ratio > 0.20 else QColor(239, 68, 68))
        painter.setPen(Qt.NoPen)
        painter.setBrush(hp_color)
        painter.drawRoundedRect(QRectF(bar_x + 1, bar_y + 1, (bar_w - 2) * ratio, bar_h - 2), 3, 3)

        # Exact numeric HP readout
        painter.setPen(QColor(55, 65, 81))
        painter.setFont(QFont("Consolas", 10, QFont.Bold))
        painter.drawText(QRectF(bar_x, y + 54, bar_w, 20), Qt.AlignRight,
                         f"{int(round(self.poke_player_display_hp))} / {self.poke_player_max_hp}")

    def _draw_player_back_sprite(self, painter: QPainter, x: float, y: float, w: float, h: float):
        """Retro-styled 3D-angled back-view mini calculator sprite."""
        painter.save()
        painter.setPen(QPen(QColor(30, 41, 59), 2.5))
        painter.setBrush(QColor(51, 65, 85))
        painter.drawRoundedRect(QRectF(x, y, w, h), 10, 10)

        # Solar cell strip on top
        painter.setPen(QPen(QColor(15, 23, 42), 1.5))
        painter.setBrush(QColor(71, 85, 105))
        painter.drawRoundedRect(QRectF(x + 8, y + 8, w - 16, 12), 3, 3)
        for s in range(3):
            painter.drawLine(QPointF(x + 14 + s * 16, y + 8), QPointF(x + 14 + s * 16, y + 20))

        # Battery compartment door
        painter.setBrush(QColor(30, 41, 59))
        painter.drawRoundedRect(QRectF(x + 10, y + 26, w - 20, 38), 5, 5)

        # Textured grip ridges on battery door
        painter.setPen(QPen(QColor(71, 85, 105), 1.5))
        for r in range(4):
            ry = y + 34 + r * 6
            painter.drawLine(QPointF(x + 18, ry), QPointF(x + w - 18, ry))

        # Brand label badge
        painter.setPen(QColor(148, 163, 184))
        painter.setFont(QFont("Consolas", 6, QFont.Bold))
        painter.drawText(QRectF(x, y + 68, w, 14), Qt.AlignCenter, "CALC-84")
        painter.restore()

    def _get_pokemon_deck_rect(self) -> QRectF:
        W, H = self.width(), self.height()
        deck_h = 145.0
        return QRectF(14, H - deck_h - 14, W - 28, deck_h)

    def _get_pokemon_action_rects(self) -> List[QRectF]:
        deck = self._get_pokemon_deck_rect()
        right_w = 260.0
        right_x = deck.right() - right_w
        hw = right_w / 2.0
        hh = deck.height() / 2.0
        return [
            QRectF(right_x, deck.top(), hw, hh),          # 0: FIGHT
            QRectF(right_x + hw, deck.top(), hw, hh),     # 1: BAG
            QRectF(right_x, deck.top() + hh, hw, hh),     # 2: CALC
            QRectF(right_x + hw, deck.top() + hh, hw, hh) # 3: RUN
        ]

    def _get_pokemon_move_rects(self) -> List[QRectF]:
        deck = self._get_pokemon_deck_rect()
        left_w = deck.width() * 0.62
        hw = left_w / 2.0
        hh = deck.height() / 2.0
        return [
            QRectF(deck.left(), deck.top(), hw, hh),          # 0: DIVIDE BY ZERO
            QRectF(deck.left() + hw, deck.top(), hw, hh),     # 1: CLEAR ENTRY
            QRectF(deck.left(), deck.top() + hh, hw, hh),     # 2: PEMDAS SLAM
            QRectF(deck.left() + hw, deck.top() + hh, hw, hh) # 3: FACT CHECK
        ]

    def _draw_bottom_deck(self, painter: QPainter):
        deck = self._get_pokemon_deck_rect()

        # Outer frame
        painter.setPen(QPen(QColor(31, 41, 55), 4.0))
        painter.setBrush(QColor(249, 250, 251))
        painter.drawRoundedRect(deck, 10, 10)

        # Inner border
        painter.setPen(QPen(QColor(209, 213, 219), 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(deck.adjusted(4, 4, -4, -4), 8, 8)

        if self.poke_substate in (self.POKE_INTRO_1, self.POKE_INTRO_2, self.POKE_REJECTION_TEXT,
                                  self.POKE_TEXT_SEQUENCE, self.POKE_ROBI_FAINT, self.POKE_PLAYER_FAINT):
            # Full-width dialogue display
            self._draw_typewriter_box(painter, deck.adjusted(16, 14, -16, -14))

        elif self.poke_substate == self.POKE_ACTION_SELECT:
            # Left side: Prompt text
            left_w = deck.width() - 260.0
            prompt_rect = QRectF(deck.left() + 16, deck.top() + 14, left_w - 24, deck.height() - 28)
            self._draw_typewriter_box(painter, prompt_rect, show_prompt=False)

            # Divider line
            painter.setPen(QPen(QColor(209, 213, 219), 2.0))
            painter.drawLine(QPointF(deck.right() - 260.0, deck.top() + 4),
                             QPointF(deck.right() - 260.0, deck.bottom() - 4))

            # Right side: 2x2 Command Grid
            rects = self._get_pokemon_action_rects()
            labels = ["FIGHT", "BAG", "CALC", "RUN"]
            for idx, r in enumerate(rects):
                painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
                is_sel = (idx == self.poke_action_cursor)
                if is_sel:
                    painter.setPen(QColor(220, 38, 38))
                    painter.drawText(r.adjusted(14, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, f"▶ {labels[idx]}")
                else:
                    painter.setPen(QColor(31, 41, 55))
                    painter.drawText(r.adjusted(28, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, labels[idx])

        elif self.poke_substate == self.POKE_MOVE_SELECT:
            # Left 62%: 2x2 Move Grid
            rects = self._get_pokemon_move_rects()
            for idx, r in enumerate(rects):
                m = self.poke_player_moves[idx]
                is_sel = (idx == self.poke_move_cursor)
                painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
                if is_sel:
                    painter.setPen(QColor(220, 38, 38))
                    painter.drawText(r.adjusted(12, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, f"▶ {m['name']}")
                else:
                    painter.setPen(QColor(31, 41, 55))
                    painter.drawText(r.adjusted(24, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, m["name"])

            # Divider line
            left_w = deck.width() * 0.62
            div_x = deck.left() + left_w
            painter.setPen(QPen(QColor(209, 213, 219), 2.0))
            painter.drawLine(QPointF(div_x, deck.top() + 4), QPointF(div_x, deck.bottom() - 4))

            # Right 38%: Move Details (Type badge & PP)
            cur_m = self.poke_player_moves[self.poke_move_cursor]
            right_rect = QRectF(div_x + 14, deck.top() + 14, deck.right() - div_x - 24, deck.height() - 28)

            painter.setPen(QColor(75, 85, 99))
            painter.setFont(QFont("Consolas", 10, QFont.Bold))
            painter.drawText(QPointF(right_rect.left(), right_rect.top() + 20), f"PP  {cur_m['pp']}/{cur_m['max_pp']}")

            # Type badge
            type_color = {
                "CHAOS": QColor(139, 92, 246),
                "MATH":  QColor(59, 130, 246),
                "LOGIC": QColor(245, 158, 11)
            }.get(cur_m["type"], QColor(107, 114, 128))

            badge_rect = QRectF(right_rect.left(), right_rect.top() + 34, 76, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(type_color)
            painter.drawRoundedRect(badge_rect, 4, 4)

            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Consolas", 9, QFont.Bold))
            painter.drawText(badge_rect, Qt.AlignCenter, cur_m["type"])

            # Power note
            painter.setPen(QColor(107, 114, 128))
            painter.setFont(QFont("Segoe UI", 9))
            pwr_txt = f"PWR: {cur_m['pwr']}" if cur_m['pwr'] > 0 else "STATUS"
            painter.drawText(QPointF(right_rect.left() + 86, right_rect.top() + 50), pwr_txt)

            # Help prompt
            painter.setPen(QColor(156, 163, 175))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(QPointF(right_rect.left(), right_rect.bottom() - 4), "ESC / X: Back")

    def _draw_typewriter_box(self, painter: QPainter, rect: QRectF, show_prompt: bool = True):
        painter.setPen(QColor(17, 24, 39))
        painter.setFont(QFont("Segoe UI", 13, QFont.Bold))
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                         self.poke_typewriter.displayed_text)

        # Blinking red prompt triangle ▼
        if show_prompt and self.poke_typewriter.is_done:
            if int(self.state_time * 4.0) % 2 == 0:
                tx = rect.right() - 14
                ty = rect.bottom() - 10
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(220, 38, 38))
                painter.drawPolygon(QPolygonF([
                    QPointF(tx - 6, ty - 8),
                    QPointF(tx + 6, ty - 8),
                    QPointF(tx, ty)
                ]))

    def _draw_victory_text(self, painter: QPainter):
        title_y = int(self.height() * 0.44)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 220))

        painter.setPen(QColor(34, 197, 94))
        painter.setFont(QFont("Consolas", 28, QFont.Bold))
        painter.drawText(QRectF(0, title_y, self.width(), 40), Qt.AlignCenter, "VICTORY!")

        painter.setFont(QFont("Consolas", 18, QFont.Bold))
        metrics = painter.fontMetrics()
        line_one = "ROBI fainted! Passphrase unlocked:"
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            QPointF((self.width() - metrics.horizontalAdvance(line_one)) / 2, title_y + 60),
            line_one,
        )

        prefix = "because "
        highlighted = "i am stupid"
        suffix = ""
        prefix_width = metrics.horizontalAdvance(prefix)
        highlighted_width = metrics.horizontalAdvance(highlighted)
        line_width = prefix_width + highlighted_width + metrics.horizontalAdvance(suffix)
        start_x = (self.width() - line_width) / 2
        baseline = title_y + 105

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(37, 99, 235, 120))
        painter.drawRoundedRect(
            QRectF(
                start_x + prefix_width - 6,
                baseline - metrics.ascent() - 4,
                highlighted_width + 12,
                metrics.height() + 8,
            ),
            6,
            6,
        )
        painter.setBrush(Qt.NoBrush)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QPointF(start_x, baseline), prefix)
        painter.setPen(QColor(96, 165, 250))
        painter.drawText(QPointF(start_x + prefix_width, baseline), highlighted)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QPointF(start_x + prefix_width + highlighted_width, baseline), suffix)

        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor(156, 163, 175))
        painter.drawText(QRectF(0, baseline + 35, self.width(), 20), Qt.AlignCenter,
                         "Closing battle screen in 3 seconds (or press ESC)...")
