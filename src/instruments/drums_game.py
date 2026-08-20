"""
Talking Hands — Genius Drums Game UI (PySide6)

Split layout: panel on the LEFT (1/3), camera + drum overlays on the RIGHT (2/3).
Dark/purple palette matching keyboard_game.py.

The Genius / Simon-says logic is unchanged — only the renderer was ported
from pygame to PySide6.

Entry point: start_drums_game(...)
"""

import sys
import os
import time
import threading
import queue
import math
import numpy as np
import cv2
import mediapipe as mp
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSizePolicy, QStackedWidget, QFrame,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPen, QBrush

FILE_PATH     = Path(__file__).resolve()
PROJECT_ROOT  = FILE_PATH.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- FluidSynth path setup BEFORE any module that imports fluidsynth ---
def _setup_fluidsynth_path():
    fluidsynth_bin = PROJECT_ROOT / "assets" / "fluidsynth-v2.5.1" / "bin"
    if fluidsynth_bin.exists():
        bin_str = str(fluidsynth_bin)
        os.environ["FLUIDSYNTH_PATH"] = bin_str
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(bin_str)
            except Exception:
                pass
        current = os.environ.get("PATH", "")
        if bin_str not in current:
            os.environ["PATH"] = f"{bin_str};{current}"
    _orig = getattr(os, "add_dll_directory", None)
    if _orig:
        def _safe_add(p):
            if p.lower() == r"c:\tools\fluidsynth\bin":
                return None
            return _orig(p)
        os.add_dll_directory = _safe_add

_setup_fluidsynth_path()

from src.config import settings
from src.engines.game_genius import GeniusGame
from src.instruments.common import (
    init_fluidsynth, load_single_soundfont,
    setup_video_capture, fit_resolution_to_screen,
    CameraThread, prepare_mediapipe_frame, MediaPipeHandsThread,
)
from src.instruments.drums_ui import (
    build_drum_kit, apply_drum_note_profile, check_collision,
    DRUM_ELEMENT_LIBRARY,
    DRUMS_INSTRUMENT_ELEMENT_PRESETS, DRUMS_INSTRUMENT_REPLACE_BASE,
    VELOCITY_THRESHOLD, TOUCH_VELOCITY, DRUM_MIN_VELOCITY,
    DRUM_MIN_HIT_INTERVAL, MIN_REHIT_PIXELS,
    FIXED_SF2_PATH, POLYPHONY_CHANNELS,
)
from src.instruments.ui_shared import (
    load_custom_font, FONT_FAMILY,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL,
    BTN_HEIGHT, BORDER_RAD,
)

import fluidsynth as _fluidsynth  # noqa: side-effect DLL already in PATH

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
GAME_BG_PANEL       = "#0F0D18"
GAME_BG_PANEL_ALT   = "#16141F"
GAME_ACCENT         = "#746292"
GAME_ACCENT_RED     = "#C44E6A"
GAME_TEXT_PRIMARY   = "#EDE7F6"
GAME_TEXT_SECONDARY = "#6C6080"
GAME_TEXT_LIGHT     = "#FFFFFF"
GAME_BORDER_LIGHT   = "#231E33"
GAME_CARD_BORDER    = "#211D2E"
GAME_DIFF_SELECTED  = "#7ECBA1"

# ---------------------------------------------------------------------------
# Per-element Genius colours
# ---------------------------------------------------------------------------
_ELEMENT_GAME_COLORS: dict = {
    "crash":      (255,  70,  70), "ride":       ( 70, 150, 255),
    "tom_hi":     (255, 210,  50), "tom_low":    ( 70, 230, 120),
    "hihat":      (255, 130,   0), "snare":      (200,  80, 255),
    "floor":      (  0, 210, 200), "kick":       (255,  60, 180),
    "open_hh":    (255, 180,   0), "splash":     (255, 100, 100),
    "china":      (100, 255, 180), "tom_mid":    (180, 255,  80),
    "rimshot":    (255, 255, 100), "snare_alt":  (160, 100, 255),
    "kick_alt":   (255, 100, 130), "hh_pedal":   (200, 200, 200),
    "cowbell":    (255, 200, 100), "clap":       (255, 130, 200),
    "tamb":       (255, 160,  60), "ride_bell":  ( 80, 220, 240),
    "crash2":     (255,  90,  90), "ride2":      ( 90, 160, 255),
    "vibra_slap": (220, 220,  60), "shaker":     (180, 255, 150),
    "cabasa":     (255, 150, 100), "maracas":    (150, 255, 200),
    "bongo_hi":   (255, 120,  80), "bongo_mid":  (200, 180, 255),
    "bongo_lo":   (100, 240, 180), "bongo_deep": ( 60, 180, 255),
    "conga_hi":   (255, 200,  60), "conga_mid":  (200, 255, 100),
    "conga_lo":   ( 80, 200, 255), "timbale_hi": (255, 100, 200),
    "timbale_lo": (150, 100, 255),
}
_PALETTE_FALLBACK = [
    (255,80,80),(80,200,255),(80,255,130),(255,220,50),
    (200,80,255),(255,130,0),(0,210,200),(255,60,180),
]

def _element_color(key: str, index: int = 0) -> tuple:
    return _ELEMENT_GAME_COLORS.get(key, _PALETTE_FALLBACK[index % len(_PALETTE_FALLBACK)])

# ---------------------------------------------------------------------------
# Difficulty config
# ---------------------------------------------------------------------------
DIFFICULTY_EXTRA_ELEMENTS: dict = {
    "easy":   [],
    "medium": ["tom_mid", "open_hh", "cowbell"],
    "hard":   ["tom_mid", "open_hh", "cowbell", "splash", "clap", "rimshot"],
}
_DIFFICULTY_LABEL: dict = {"easy": "EASY", "medium": "MEDIUM", "hard": "HARD"}
_DIFFICULTY_COLOR_QSS: dict = {"easy": "#4E7C5E", "medium": "#7A6830", "hard": "#8A3A50"}
_DIFF_LABELS_DISPLAY: dict = {"easy": "NORMAL", "medium": "HARD", "hard": "IMPOSSIBLE"}

def _merge_elements_for_difficulty(base_elements, difficulty: str):
    extras = DIFFICULTY_EXTRA_ELEMENTS.get(difficulty, [])
    if not extras:
        return base_elements
    if base_elements is None:
        return list(extras)
    merged = list(base_elements)
    seen = set(merged)
    for e in extras:
        if e not in seen and e in DRUM_ELEMENT_LIBRARY:
            merged.append(e)
            seen.add(e)
    return merged


# ---------------------------------------------------------------------------
# Sequence Dots Widget
# ---------------------------------------------------------------------------

class SequenceDotsWidget(QWidget):
    _R = 7
    _GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game = None
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_game(self, game) -> None:
        self._game = game

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy = h // 2
        r, gap = self._R, self._GAP

        if self._game is None or self._game.state not in (
            GeniusGame.STATE_WAIT_INPUT, GeniusGame.STATE_FEEDBACK, GeniusGame.STATE_DEMO
        ):
            p.end()
            return

        now = time.time()
        seq_len = self._game.sequence_length
        visible = min(seq_len, max(1, (w - 20) // (r * 2 + gap)))
        start_seq_idx = max(0, seq_len - visible)
        total_w = visible * (r * 2) + (visible - 1) * gap
        x0 = (w - total_w) // 2

        for i_local, i_global in enumerate(range(start_seq_idx, seq_len)):
            cx = x0 + i_local * (r * 2 + gap) + r
            p.setPen(Qt.NoPen)

            if self._game.state in (GeniusGame.STATE_WAIT_INPUT, GeniusGame.STATE_FEEDBACK):
                if i_global < self._game.player_index:
                    p.setBrush(QBrush(QColor(220, 220, 220)))
                    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
                    p.setPen(QPen(QColor(255, 255, 255), 2))
                    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
                elif i_global == self._game.player_index:
                    pulse = 0.5 + 0.5 * math.sin(now * 7)
                    r_anim = int(r + 3 * pulse)
                    p.setBrush(QBrush(QColor(60, 60, 60)))
                    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
                    p.setPen(QPen(QColor(200, 200, 200), 3))
                    p.drawEllipse(cx - r_anim, cy - r_anim, r_anim * 2, r_anim * 2)
                else:
                    p.setBrush(QBrush(QColor(GAME_CARD_BORDER)))
                    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
            else:
                demo_idx = self._game._demo_index - 1
                if (i_global < seq_len and
                        self._game.sequence[i_global] == self._game.highlighted_element and
                        i_global == demo_idx):
                    p.setBrush(QBrush(QColor(220, 220, 220)))
                    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
                    p.setPen(QPen(QColor(255, 255, 255), 2))
                    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
                else:
                    p.setBrush(QBrush(QColor(GAME_CARD_BORDER)))
                    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        p.end()


# ---------------------------------------------------------------------------
# Timer Bar Widget
# ---------------------------------------------------------------------------

class TimerBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._frac = 1.0
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_fraction(self, frac: float) -> None:
        self._frac = max(0.0, min(1.0, frac))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h // 2
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(GAME_CARD_BORDER)))
        p.drawRoundedRect(0, 0, w, h, r, r)
        fill_w = int(w * self._frac)
        if fill_w > 0:
            red   = int(255 * (1.0 - self._frac))
            green = int(255 * self._frac)
            p.setBrush(QBrush(QColor(min(255, red), min(255, green), 50)))
            p.drawRoundedRect(0, 0, fill_w, h, r, r)
        p.end()


# ---------------------------------------------------------------------------
# Camera + Drum Overlay Widget
# ---------------------------------------------------------------------------

class DrumGameOverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._frame_rgb  = None
        self._results    = None
        self._drum_kit   = []
        self._game       = None
        self._hit_feedback: dict = {}
        self._show_trackers = False
        self._detecting     = False
        self._countdown_num = 0

    def set_frame(self, frame_rgb) -> None:       self._frame_rgb = frame_rgb
    def set_results(self, results) -> None:
        self._results   = results
        self._detecting = results is not None and results.multi_hand_landmarks is not None
    def set_drum_kit(self, kit: list) -> None:    self._drum_kit = kit
    def set_game(self, game) -> None:             self._game = game
    def set_show_trackers(self, v: bool) -> None: self._show_trackers = v
    def set_countdown(self, n: int) -> None:      self._countdown_num = n

    def record_feedback(self, element_key: str, result: str) -> None:
        self._hit_feedback[element_key] = {"result": result, "ts": time.time()}

    def _clear_old_feedback(self, ttl: float = 0.25) -> None:
        now = time.time()
        for k in [k for k, v in self._hit_feedback.items() if now - v["ts"] > ttl]:
            del self._hit_feedback[k]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, QColor(GAME_BG_PANEL))

        if self._frame_rgb is not None:
            frame = np.ascontiguousarray(self._frame_rgb)
            fh, fw = frame.shape[:2]
            qimg = QImage(frame.data, fw, fh, fw * 3, QImage.Format_RGB888)
            painter.drawImage(0, 0, qimg.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation))

        self._draw_drum_pads(painter, w, h)

        if self._show_trackers and self._results and self._results.multi_hand_landmarks:
            self._draw_hand_connections(painter, w, h)

        self._draw_detecting_badge(painter)
        self._draw_state_banner(painter, w, h)
        if self._countdown_num > 0:
            self._draw_countdown(painter, w, h)
        painter.end()

    def _draw_drum_pads(self, painter, w, h):
        if not self._drum_kit or self._game is None:
            return
        self._clear_old_feedback()
        now = time.time()

        for idx, drum in enumerate(self._drum_kit):
            key = drum.get("element_key", "")
            r, g, b = _element_color(key, idx)
            cx = int(drum["pos"][0] * w)
            cy = int(drum["pos"][1] * h)
            rx = int(drum["axes"][0] * w)
            ry = int(drum["axes"][1] * h)

            is_hl  = self._game.highlighted_element == key
            fb     = self._hit_feedback.get(key)
            is_ok  = fb and fb["result"] == "correct"
            is_err = fb and fb["result"] == "wrong"

            if is_hl:
                pulse = 0.5 + 0.5 * math.sin(now * 8)
                fill  = QColor(r, g, b, int(180 + 70 * pulse))
                bord  = QColor(255, 255, 255, 220); bw = 4
            elif is_ok:
                fill = QColor(0, 255, 100, 210); bord = QColor(200, 255, 200, 220); bw = 4
            elif is_err:
                fill = QColor(255, 50, 50, 210);  bord = QColor(255, 200, 200, 220); bw = 4
            else:
                fill = QColor(r, g, b, 35)
                bord = QColor(max(0,r-60), max(0,g-60), max(0,b-60), 180); bw = 2

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill))
            if drum.get("shape") == "rect":
                painter.drawRect(cx - rx, cy - ry, rx*2, ry*2)
                painter.setPen(QPen(bord, bw)); painter.setBrush(Qt.NoBrush)
                painter.drawRect(cx - rx, cy - ry, rx*2, ry*2)
            else:
                painter.drawEllipse(cx - rx, cy - ry, rx*2, ry*2)
                painter.setPen(QPen(bord, bw)); painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(cx - rx, cy - ry, rx*2, ry*2)

            f = QFont(FONT_FAMILY, FONT_SIZE_SM - 2); f.setBold(True)
            painter.setFont(f)
            name = drum.get("name", key.upper())
            alpha = 200 if is_hl else (160 if (is_ok or is_err) else 80)
            painter.setPen(QColor(255, 255, 255, alpha))
            fm = painter.fontMetrics()
            painter.drawText(cx - fm.horizontalAdvance(name) // 2,
                             cy + fm.ascent() // 2 - 1, name)

    def _draw_hand_connections(self, painter, w, h):
        conns = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(0,9),(9,10),
                 (10,11),(11,12),(0,13),(13,14),(14,15),(15,16),(0,17),(17,18),
                 (18,19),(19,20),(5,9),(9,13),(13,17)]
        for lm in self._results.multi_hand_landmarks:
            pen = QPen(QColor(GAME_ACCENT), 2); pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            for a, b in conns:
                painter.drawLine(int(lm.landmark[a].x*w), int(lm.landmark[a].y*h),
                                 int(lm.landmark[b].x*w), int(lm.landmark[b].y*h))
            painter.setBrush(QBrush(QColor(GAME_ACCENT))); painter.setPen(Qt.NoPen)
            for pt in lm.landmark:
                painter.drawEllipse(int(pt.x*w)-3, int(pt.y*h)-3, 6, 6)

    def _draw_detecting_badge(self, painter):
        if not self._detecting:
            return
        label = "DETECTANDO"
        f = QFont(FONT_FAMILY, FONT_SIZE_SM); f.setBold(True)
        painter.setFont(f); fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label)
        dot_r, pad_l, gap, pad_r = 10, 10, 8, 12
        cw, ch = pad_l + dot_r + gap + tw + pad_r, 28
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(30, 20, 50, 210)))
        painter.drawRoundedRect(12, 12, cw, ch, 14, 14)
        painter.setBrush(QBrush(QColor(GAME_ACCENT)))
        painter.drawEllipse(12 + pad_l, 12 + (ch - dot_r)//2, dot_r, dot_r)
        painter.setPen(QColor(GAME_ACCENT)); painter.setFont(f)
        painter.drawText(12 + pad_l + dot_r + gap, 12 + ch//2 + fm.ascent()//2 - 1, label)

    def _draw_state_banner(self, painter, w, h):
        if self._game is None:
            return
        state = self._game.state
        if state == GeniusGame.STATE_DEMO:
            self._small_banner(painter, w, h//2+30, "  WATCH  ",
                               QColor(40,40,120,180), QColor(180,180,255))
        elif state == GeniusGame.STATE_WAIT_INPUT:
            self._small_banner(painter, w, h//2+30, "  YOUR TURN  ",
                               QColor(20,80,20,180), QColor(100,255,120))
        elif state in (GeniusGame.STATE_IDLE, GeniusGame.STATE_GAME_OVER):
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 155))
            if state == GeniusGame.STATE_IDLE:
                self._center_banner(painter, w, h, "GENIUS DRUMS",
                    "Prepare-se para tocar",
                    QColor(255,220,60), QColor(180,180,255))
            else:
                is_new = self._game.score == self._game.best_score and self._game.score > 0
                sc_txt = (f"NOVO RECORDE!   {self._game.score} pts" if is_new
                          else f"Score: {self._game.score}     Recorde: {self._game.best_score}")
                self._center_banner(painter, w, h, "FIM DE JOGO", sc_txt,
                    QColor(255,70,70), QColor(255,230,60) if is_new else QColor(220,220,220))

    def _center_banner(self, painter, w, h, title, subtitle, tc, sc):
        f_big = QFont(FONT_FAMILY, 36); f_big.setBold(True)
        f_sm  = QFont(FONT_FAMILY, FONT_SIZE_MD)
        cx, cy = w//2, h//2
        painter.setFont(f_big); fm = painter.fontMetrics()
        painter.setPen(tc)
        painter.drawText(cx - fm.horizontalAdvance(title)//2, cy - 30, title)
        painter.setFont(f_sm); fm2 = painter.fontMetrics()
        painter.setPen(sc)
        painter.drawText(cx - fm2.horizontalAdvance(subtitle)//2, cy + 30, subtitle)

    def _draw_countdown(self, painter, w, h):
        text = str(self._countdown_num)
        font = QFont(FONT_FAMILY, min(w, h) // 4)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        painter.setPen(QColor(255, 255, 255))
        painter.drawText((w - metrics.horizontalAdvance(text)) // 2,
                         (h + metrics.height()) // 2, text)

    def _small_banner(self, painter, w, y, text, bg, tc):
        f = QFont(FONT_FAMILY, FONT_SIZE_MD); f.setBold(True)
        painter.setFont(f); fm = painter.fontMetrics()
        pad = 14; bw = fm.horizontalAdvance(text) + pad*2; bh = fm.height() + pad
        bx = w//2 - bw//2
        painter.setPen(Qt.NoPen); painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(bx, y, bw, bh, BORDER_RAD, BORDER_RAD)
        painter.setPen(tc)
        painter.drawText(bx + pad, y + bh//2 + fm.ascent()//2 - 2, text)


# ---------------------------------------------------------------------------
# Scaling label
# ---------------------------------------------------------------------------

class ScalingLabel(QLabel):
    def __init__(self, text="", scale=0.42, parent=None):
        super().__init__(text, parent)
        self._scale = scale

    def resizeEvent(self, event):
        super().resizeEvent(event)
        h = self.height()
        if h > 8:
            px = max(10, int(h * self._scale))
            self.setStyleSheet(f"font-size: {px}px; font-weight: bold;")


# ---------------------------------------------------------------------------
# Game Panel (left side)
# ---------------------------------------------------------------------------

class GeniusGamePanel(QWidget):
    restart_clicked    = Signal()
    end_clicked        = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("gamePanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._current_difficulty = "easy"
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(self._build_title_block())
        self._stack = QStackedWidget()
        self._playing_page  = self._build_playing_page()
        self._gameover_page = self._build_gameover_page()
        self._stack.addWidget(self._playing_page)
        self._stack.addWidget(self._gameover_page)
        outer.addWidget(self._stack, 1)

        btns = QVBoxLayout(); btns.setContentsMargins(12,8,12,12); btns.setSpacing(6)
        self._pause_btn = QPushButton("⏸  Pausar"); self._pause_btn.setObjectName("gamePauseBtn")
        self._pause_btn.setCheckable(True); self._pause_btn.clicked.connect(self._on_pause_click)
        btns.addWidget(self._pause_btn)
        self._end_btn = QPushButton("Encerrar"); self._end_btn.setObjectName("gameEndBtn")
        self._end_btn.clicked.connect(self.end_clicked.emit); btns.addWidget(self._end_btn)
        outer.addLayout(btns)

    def _build_title_block(self):
        w = QWidget(); w.setObjectName("gameTitleBlock")
        vl = QVBoxLayout(w); vl.setContentsMargins(12,14,12,14)
        vl.setAlignment(Qt.AlignCenter); vl.setSpacing(2)
        icon = QLabel("✦"); icon.setObjectName("gameIconLabel"); icon.setAlignment(Qt.AlignCenter)
        vl.addWidget(icon)
        title = QLabel("Genius Drums"); title.setObjectName("gameHeaderLabel")
        title.setAlignment(Qt.AlignCenter); vl.addWidget(title)
        return w

    def _make_stat_card(self, val_obj: str, sub: str):
        card = QFrame(); card.setObjectName("gameStatCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl = QVBoxLayout(card); vl.setContentsMargins(8,6,8,6); vl.setSpacing(2)
        val = ScalingLabel("0", 0.42); val.setObjectName(val_obj)
        val.setAlignment(Qt.AlignCenter)
        val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl.addWidget(val, 1)
        s = QLabel(sub); s.setObjectName("gameStatCardSub"); s.setAlignment(Qt.AlignCenter)
        vl.addWidget(s)
        return card, val

    def _build_playing_page(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.setContentsMargins(8,6,8,6); layout.setSpacing(5)

        card, self._score_label = self._make_stat_card("gameScoreValue", "PONTOS")
        layout.addWidget(card, 2)
        card, self._round_label = self._make_stat_card("gameComboValue", "RODADA")
        layout.addWidget(card, 1)

        seq_card = QFrame(); seq_card.setObjectName("gameStatCard")
        seq_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        seq_vl = QVBoxLayout(seq_card); seq_vl.setContentsMargins(8,6,8,6); seq_vl.setSpacing(4)
        self._seq_dots = SequenceDotsWidget(); seq_vl.addWidget(self._seq_dots)
        s = QLabel("SEQUÊNCIA"); s.setObjectName("gameStatCardSub"); s.setAlignment(Qt.AlignCenter)
        seq_vl.addWidget(s); layout.addWidget(seq_card)

        tc = QFrame(); tc.setObjectName("gameStatCard")
        tc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tv = QVBoxLayout(tc); tv.setContentsMargins(8,8,8,8); tv.setSpacing(4)
        self._timer_bar = TimerBarWidget(); tv.addWidget(self._timer_bar)
        ts = QLabel("TEMPO"); ts.setObjectName("gameStatCardSub"); ts.setAlignment(Qt.AlignCenter)
        tv.addWidget(ts); layout.addWidget(tc)

        info = QFrame(); info.setObjectName("gameInfoBar")
        br = QHBoxLayout(info); br.setContentsMargins(10,8,10,8); br.setSpacing(8)
        ll = QLabel("Dificuldade"); ll.setObjectName("gamePlaySongLabel"); br.addWidget(ll, 1)
        self._play_diff_label = QLabel("EASY"); self._play_diff_label.setObjectName("gamePlayDiffLabel")
        br.addWidget(self._play_diff_label); layout.addWidget(info)

        self._fps_label = QLabel("FPS: --"); self._fps_label.setObjectName("gameFpsLabel")
        layout.addWidget(self._fps_label)
        return page

    def _build_gameover_page(self):
        page = QWidget(); outer = QVBoxLayout(page)
        outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)

        rw = QWidget(); rl = QVBoxLayout(rw); rl.setContentsMargins(8,6,8,4); rl.setSpacing(5)
        self._result_title = QLabel("FIM DE JOGO"); self._result_title.setObjectName("gameResultTitle")
        self._result_title.setAlignment(Qt.AlignCenter); rl.addWidget(self._result_title)
        card, self._result_score_label = self._make_stat_card("gameScoreValue", "PONTOS")
        rl.addWidget(card, 2)
        side = QHBoxLayout(); side.setSpacing(5)
        rc, self._result_round_label = self._make_stat_card("gameComboValue", "RODADA")
        bc, self._result_best_label  = self._make_stat_card("gamePrecisionValue", "RECORDE")
        side.addWidget(rc); side.addWidget(bc); rl.addLayout(side, 1)
        outer.addWidget(rw, 1)

        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {GAME_BORDER_LIGHT};"); outer.addWidget(div)

        ng = QWidget(); ngl = QVBoxLayout(ng); ngl.setContentsMargins(8,6,8,6); ngl.setSpacing(5)
        self._start_btn = QPushButton("▶  Jogar Novamente"); self._start_btn.setObjectName("gameStartBtn")
        self._start_btn.setFixedHeight(BTN_HEIGHT + 2); self._start_btn.clicked.connect(self.restart_clicked.emit)
        ngl.addWidget(self._start_btn, 1)

        self._fps_label_go = QLabel("FPS: --"); self._fps_label_go.setObjectName("gameFpsLabel")
        ngl.addWidget(self._fps_label_go); outer.addWidget(ng, 1)
        return page

    # ── public API ────────────────────────────────────────────────────────

    def switch_to_playing(self) -> None:
        self._update_diff_badge(self._current_difficulty)
        self._stack.setCurrentIndex(0)

    def switch_to_gameover(self, game) -> None:
        self._start_btn.setText("▶  Jogar Novamente")
        is_new = game.score == game.best_score and game.score > 0
        self._result_title.setText("NOVO RECORDE!" if is_new else "FIM DE JOGO")
        self._result_title.setObjectName("gameResultTitleWin" if is_new else "gameResultTitle")
        self._result_title.style().unpolish(self._result_title)
        self._result_title.style().polish(self._result_title)
        self._result_score_label.setText(str(game.score))
        self._result_round_label.setText(str(game.round))
        self._result_best_label.setText(str(game.best_score))
        self._stack.setCurrentIndex(1)

    def update_game_state(self, game) -> None:
        self._score_label.setText(str(game.score))
        self._round_label.setText(str(game.round))
        self._seq_dots.update()
        if game.state == GeniusGame.STATE_WAIT_INPUT:
            self._timer_bar.set_fraction(game.remaining_time / max(0.01, game.PLAYER_TIMEOUT))
        else:
            self._timer_bar.set_fraction(1.0 if game.state == GeniusGame.STATE_DEMO else 0.0)

    def update_fps(self, fps: float) -> None:
        txt = f"FPS: {fps:.0f}"
        self._fps_label.setText(txt); self._fps_label_go.setText(txt)

    def reset_pause(self) -> None:
        self._pause_btn.setChecked(False); self._pause_btn.setText("⏸  Pausar")

    def set_game_for_dots(self, game) -> None:
        self._seq_dots.set_game(game)

    def set_difficulty(self, diff: str) -> None:
        self._current_difficulty = diff
        self._update_diff_badge(diff)

    def _on_pause_click(self, checked: bool) -> None:
        self._pause_btn.setText("▶  Retomar" if checked else "⏸  Pausar")

    def _update_diff_badge(self, diff: str) -> None:
        col = _DIFFICULTY_COLOR_QSS.get(diff, GAME_ACCENT)
        self._play_diff_label.setText(_DIFFICULTY_LABEL.get(diff, diff.upper()))
        self._play_diff_label.setStyleSheet(
            f"background-color: {col}; color: {GAME_TEXT_LIGHT}; border-radius: 6px;"
            f" padding: 2px 8px; font-size: {FONT_SIZE_SM}px;"
            f" font-family: {FONT_FAMILY}; font-weight: bold;"
        )


# ---------------------------------------------------------------------------
# QSS
# ---------------------------------------------------------------------------

def _build_game_qss() -> str:
    return f"""
QMainWindow {{ background-color: {GAME_BG_PANEL}; }}
#gamePanel {{ background-color: {GAME_BG_PANEL}; border-right: 1px solid {GAME_BORDER_LIGHT}; }}
#gamePanel QLabel {{ color: {GAME_TEXT_PRIMARY}; font-family: {FONT_FAMILY}; }}
QWidget#gameTitleBlock {{ background-color: {GAME_BG_PANEL}; }}
QLabel#gameIconLabel {{ font-size: 20px; color: {GAME_ACCENT}; }}
QLabel#gameHeaderLabel {{ font-size: {FONT_SIZE_SM}px; font-weight: bold; color: {GAME_TEXT_SECONDARY}; letter-spacing: 2px; }}
QFrame#gameStatCard {{ background-color: {GAME_BG_PANEL_ALT}; border: 1px solid {GAME_CARD_BORDER}; border-radius: {BORDER_RAD}px; }}
QLabel#gameStatCardSub {{ font-size: {FONT_SIZE_SM}px; color: {GAME_TEXT_SECONDARY}; letter-spacing: 2px; }}
QLabel#gameScoreValue {{ color: {GAME_ACCENT}; }}
QLabel#gameComboValue {{ color: {GAME_TEXT_PRIMARY}; }}
QLabel#gamePrecisionValue {{ color: {GAME_TEXT_PRIMARY}; }}
QLabel#gameStatSectionLabel {{ font-size: {FONT_SIZE_SM}px; font-weight: bold; color: {GAME_TEXT_SECONDARY}; letter-spacing: 1px; }}
QLabel#gameFpsLabel {{ font-size: {FONT_SIZE_SM}px; color: {GAME_TEXT_SECONDARY}; }}
QFrame#gameInfoBar {{ background-color: {GAME_BG_PANEL_ALT}; border: 1px solid {GAME_CARD_BORDER}; border-radius: {BORDER_RAD}px; }}
QLabel#gamePlaySongLabel {{ font-size: {FONT_SIZE_SM}px; font-weight: bold; color: {GAME_TEXT_PRIMARY}; }}
QLabel#gameResultTitle {{ font-size: {FONT_SIZE_MD}px; font-weight: bold; color: {GAME_ACCENT_RED}; }}
QLabel#gameResultTitleWin {{ font-size: {FONT_SIZE_MD}px; font-weight: bold; color: {GAME_ACCENT}; }}
QPushButton#gameEndBtn {{ background-color: transparent; color: {GAME_ACCENT_RED}; border: 1px solid {GAME_ACCENT_RED}; border-radius: {BORDER_RAD}px; padding: 8px 10px; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY}; }}
QPushButton#gameEndBtn:hover {{ background-color: {GAME_ACCENT_RED}; color: white; }}
QPushButton#gamePauseBtn {{ background-color: {GAME_BG_PANEL_ALT}; color: {GAME_TEXT_PRIMARY}; border: 1px solid {GAME_CARD_BORDER}; border-radius: {BORDER_RAD}px; padding: 10px; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY}; }}
QPushButton#gamePauseBtn:checked {{ background-color: {GAME_ACCENT}; color: {GAME_TEXT_LIGHT}; border-color: {GAME_ACCENT}; }}
QPushButton#gameDiffBtn_easy, QPushButton#gameDiffBtn_medium, QPushButton#gameDiffBtn_hard {{ background-color: {GAME_BG_PANEL_ALT}; color: {GAME_TEXT_PRIMARY}; border: 1px solid {GAME_CARD_BORDER}; border-radius: {BORDER_RAD}px; padding: 6px 4px; font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY}; }}
QPushButton#gameDiffBtn_easy:checked, QPushButton#gameDiffBtn_medium:checked, QPushButton#gameDiffBtn_hard:checked {{ background-color: {GAME_DIFF_SELECTED}; color: #0F1A14; border-color: {GAME_DIFF_SELECTED}; font-weight: bold; }}
QPushButton#gameDiffBtn_easy:hover, QPushButton#gameDiffBtn_medium:hover, QPushButton#gameDiffBtn_hard:hover {{ border-color: {GAME_ACCENT}; }}
QPushButton#gameStartBtn {{ background-color: {GAME_ACCENT}; color: {GAME_TEXT_LIGHT}; border: none; border-radius: {BORDER_RAD}px; padding: 10px; font-size: {FONT_SIZE_MD}px; font-weight: bold; font-family: {FONT_FAMILY}; }}
QPushButton#gameStartBtn:hover {{ background-color: #8B74A8; }}
"""


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class GeniusWindow(QMainWindow):
    def __init__(
        self,
        chosen_instrument=None,
        resolution_profile=None,
        show_trackers: bool = False,
        drum_model: str = "default",
        drums_elements=None,
        hand_model_complexity: int = 1,
        difficulty: str = "easy",
    ):
        super().__init__()
        self.setWindowTitle("Talking Hands — Genius Drums")
        self.setStyleSheet(_build_game_qss())

        self._chosen_instrument = chosen_instrument
        self._drum_model        = str(drum_model).strip().lower()
        self._drums_elements    = drums_elements
        self._is_paused         = False

        apply_drum_note_profile(chosen_instrument)
        self._replace_base  = False
        self._base_elements = drums_elements
        if not self._replace_base and self._base_elements is None:
            if chosen_instrument in DRUMS_INSTRUMENT_ELEMENT_PRESETS:
                preset = DRUMS_INSTRUMENT_ELEMENT_PRESETS[chosen_instrument]
                self._base_elements = [e for e in preset if e in DRUM_ELEMENT_LIBRARY]
                if chosen_instrument in DRUMS_INSTRUMENT_REPLACE_BASE:
                    self._replace_base = True

        self._current_difficulty = difficulty if difficulty in ("easy","medium","hard") else "easy"
        self._drum_kit, self._unique_avail = self._build_kit(self._current_difficulty)
        self._countdown_val = 0
        self._countdown_timer = None

        self._game = GeniusGame()

        self._audio_queue: queue.Queue = queue.Queue()
        self._fs = None
        self._init_audio()

        if resolution_profile:
            dw = int(resolution_profile["display_width"]); dh = int(resolution_profile["display_height"])
            self._target_fps = int(resolution_profile["fps"])
        else:
            dw, dh = 1920, 1080; self._target_fps = 30
        dw, dh, _, _, _ = fit_resolution_to_screen(dw, dh)
        self._logical_w, self._logical_h = dw, dh

        self._cap = setup_video_capture(width=self._logical_w, height=self._logical_h, fps=self._target_fps)
        self._cam_thread = CameraThread(self._cap)
        hc = max(0, min(1, int(hand_model_complexity)))
        self._hands_thread = MediaPipeHandsThread(
            mp.solutions.hands.Hands(max_num_hands=2, model_complexity=hc,
                min_detection_confidence=0.3, min_tracking_confidence=0.3))

        self._hands_state = {
            lbl: {"prev_y": 0.5, "can_hit": True, "last_hit_pos": None, "last_hit_drum": -1}
            for lbl in ("Left", "Right")
        }

        self._build_ui(show_trackers)

        self._fps_counter = 0; self._fps_last_time = time.time()
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)
        self._frame_timer.start(1)
        QTimer.singleShot(400, self._start_game)

    def _build_kit(self, difficulty: str):
        merged = _merge_elements_for_difficulty(self._base_elements, difficulty)
        kit = build_drum_kit(drum_model=self._drum_model, elements=merged,
                             instrument_name=self._chosen_instrument)
        avail: list = []; seen: set = set()
        for d in kit:
            k = d.get("element_key", "")
            if not d.get("foot_only", False) and k not in seen:
                avail.append(k); seen.add(k)
        return kit, avail

    def _init_audio(self):
        self._fs, _ = init_fluidsynth(driver="dsound")
        if self._fs is None:
            print("[!] Falha ao inicializar FluidSynth"); return
        drum_sfid = load_single_soundfont(self._fs, "drums", FIXED_SF2_PATH)
        if drum_sfid != -1:
            for i in range(POLYPHONY_CHANNELS):
                self._fs.program_select(i, drum_sfid, 128, 0)
        if self._chosen_instrument and drum_sfid != -1:
            if self._chosen_instrument in settings.INSTRUMENTS:
                _, bank, preset = settings.INSTRUMENTS[self._chosen_instrument]
                for i in range(POLYPHONY_CHANNELS):
                    self._fs.program_select(i, drum_sfid, bank, preset)
                print(f">>> Kit: {self._chosen_instrument}")

    def _audio_loop(self):
        ch_idx = 0
        while True:
            item = self._audio_queue.get()
            if item is None:
                break
            if self._fs:
                self._fs.noteon(ch_idx % POLYPHONY_CHANNELS, item[0], item[1])
                ch_idx += 1

    def _build_ui(self, show_trackers: bool) -> None:
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0,0,0,0); main_layout.setSpacing(0)

        self._panel = GeniusGamePanel()
        self._panel.restart_clicked.connect(self._on_restart)
        self._panel.end_clicked.connect(self._on_end)
        self._panel.set_difficulty(self._current_difficulty)
        self._panel.set_game_for_dots(self._game)
        main_layout.addWidget(self._panel, 30)

        self._camera_widget = DrumGameOverlayWidget()
        self._camera_widget.set_drum_kit(self._drum_kit)
        self._camera_widget.set_game(self._game)
        self._camera_widget.set_show_trackers(show_trackers)
        main_layout.addWidget(self._camera_widget, 70)

    def _start_game(self) -> None:
        if self._countdown_timer is not None and self._countdown_timer.isActive():
            return
        self._is_paused = False
        self._panel.reset_pause()
        self._panel.switch_to_playing()
        self._panel.set_game_for_dots(self._game)
        self._camera_widget.set_game(self._game)
        for s in self._hands_state.values():
            s.update({"prev_y": 0.5, "can_hit": True, "last_hit_pos": None, "last_hit_drum": -1})
        self._game.state = GeniusGame.STATE_IDLE
        self._countdown_val = 3
        self._camera_widget.set_countdown(self._countdown_val)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start(1000)

    def _on_countdown_tick(self) -> None:
        self._countdown_val -= 1
        if self._countdown_val > 0:
            self._camera_widget.set_countdown(self._countdown_val)
            return
        self._countdown_timer.stop()
        self._camera_widget.set_countdown(0)
        self._game.start(self._unique_avail, difficulty=self._current_difficulty)
        print(f">>> Genius Drums [{self._current_difficulty.upper()}] — {len(self._unique_avail)} elementos")

    @Slot()
    def _on_frame_tick(self):
        frame, _ = self._cam_thread.get_latest()
        if frame is None:
            return

        frame     = cv2.resize(frame, (self._logical_w, self._logical_h))
        frame     = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        cam_w = self._camera_widget.width(); cam_h = self._camera_widget.height()
        if cam_w > 0 and cam_h > 0:
            fh, fw = frame_rgb.shape[:2]; wa = cam_w / cam_h; fa = fw / fh
            if fa > wa:
                nfw = int(fh * wa); xoff = (fw - nfw)//2
                frame_rgb = frame_rgb[:, xoff:xoff + nfw]
            elif fa < wa:
                nfh = int(fw / wa); yoff = (fh - nfh)//2
                frame_rgb = frame_rgb[yoff:yoff + nfh, :]

        crh, crw = frame_rgb.shape[:2]
        frame_mp = prepare_mediapipe_frame(frame_rgb, crw, crh, 480)
        self._hands_thread.submit_frame(frame_mp)
        results = self._hands_thread.get_latest_result()
        now = time.time()

        if not self._is_paused:
            self._game.update(self._drum_kit, now=now)
            if self._game.pending_play_note is not None:
                self._audio_queue.put(self._game.pending_play_note)
            if results.multi_hand_landmarks and results.multi_handedness:
                for idx, lm in enumerate(results.multi_hand_landmarks):
                    label = results.multi_handedness[idx].classification[0].label
                    self._process_hand(label, lm.landmark, crw, crh, now)
            self._panel.update_game_state(self._game)
            if self._game.state == GeniusGame.STATE_GAME_OVER:
                self._panel.switch_to_gameover(self._game)

        self._camera_widget.set_frame(frame_rgb)
        self._camera_widget.set_results(results)
        self._camera_widget.update()

        self._fps_counter += 1
        elapsed = now - self._fps_last_time
        if elapsed >= 1.0:
            self._panel.update_fps(self._fps_counter / elapsed)
            self._fps_counter = 0; self._fps_last_time = now

    def _process_hand(self, label: str, landmarks, frame_w: int, frame_h: int, now: float) -> None:
        ref   = landmarks[4]
        ref_x, ref_y = ref.x, ref.y
        state   = self._hands_state[label]
        prev_y  = state["prev_y"]
        can_hit = state["can_hit"]
        dy = ref_y - prev_y

        hit_drum = None
        for drum in self._drum_kit:
            if drum.get("foot_only", False): continue
            if check_collision(ref_x, ref_y, drum): hit_drum = drum; break

        drum_center_y = hit_drum["pos"][1] if hit_drum else 0.0
        if hit_drum is None or dy < -VELOCITY_THRESHOLD:
            can_hit = True
        elif ref_y < drum_center_y and dy < -VELOCITY_THRESHOLD:
            can_hit = True

        if hit_drum is not None and can_hit:
            cursor_pos   = (int(ref_x * frame_w), int(ref_y * frame_h))
            moved_enough = True
            if state["last_hit_pos"] is not None and state["last_hit_drum"] == hit_drum["id"]:
                lx, ly = state["last_hit_pos"]
                moved_enough = ((cursor_pos[0]-lx)**2 + (cursor_pos[1]-ly)**2 >= MIN_REHIT_PIXELS**2)

            if (dy > VELOCITY_THRESHOLD and moved_enough and
                    (now - float(hit_drum.get("last_hit", 0))) >= DRUM_MIN_HIT_INTERVAL):
                velocity = int(min(max((dy - TOUCH_VELOCITY)*10000, DRUM_MIN_VELOCITY), 127))
                elem_key = hit_drum.get("element_key", "")
                result   = self._game.player_hit(elem_key, now=now)
                if result in ("correct", "wrong"):
                    self._audio_queue.put((hit_drum["note"], velocity))
                    hit_drum["last_hit"] = now; can_hit = False
                    self._camera_widget.record_feedback(elem_key, result)
                state["last_hit_pos"]  = cursor_pos
                state["last_hit_drum"] = hit_drum["id"]

        state["prev_y"] = ref_y; state["can_hit"] = can_hit

    @Slot()
    def _on_restart(self) -> None: self._start_game()

    @Slot()
    def _on_end(self) -> None: self.close()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.close()
        elif key == Qt.Key_Space:
            if self._game.state in (GeniusGame.STATE_IDLE, GeniusGame.STATE_GAME_OVER):
                self._start_game()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._frame_timer.stop()
        self._hands_thread.close(); self._cam_thread.stop()
        self._cap.release(); self._audio_queue.put(None)
        event.accept()


# ---------------------------------------------------------------------------
# Entry point  (same signature as original)
# ---------------------------------------------------------------------------

def start_drums_game(
    chosen_instrument=None,
    resolution_profile=None,
    show_trackers: bool = False,
    drum_model: str = "default",
    drums_elements=None,
    hand_model_complexity: int = 1,
    difficulty: str = "easy",
):
    """Launch the Genius Drums PySide6 window."""
    print(f">>> INICIANDO GENIUS DRUMS GAME [{difficulty.upper()}]")
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_font()
    win = GeniusWindow(
        chosen_instrument=chosen_instrument,
        resolution_profile=resolution_profile,
        show_trackers=show_trackers,
        drum_model=drum_model,
        drums_elements=drums_elements,
        hand_model_complexity=hand_model_complexity,
        difficulty=difficulty,
    )
    win.showFullScreen()
    print(">>> MODO PRONTO")
    app.exec()
    print(">>> Genius Drums encerrado.")
