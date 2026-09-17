"""TTalking Hands — Piano Tiles Game UI (PySide6)

Split layout with the panel on the LEFT (1/3) and the camera on the RIGHT (2/3).
Camera width is fixed — no splitter drag.
Dark-purple palette (opposite of practice mode).

Entry point: start_piano_tiles_ui(...)   <- drop-in for old start_piano_tiles()
"""

import sys
import os
import time
import threading
import queue
import math
import cv2
import numpy as np
import mediapipe as mp
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSizePolicy, QStackedWidget, QFrame,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPen, QBrush

FILE_PATH     = Path(__file__).resolve()
_PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# --- FluidSynth path setup BEFORE any module that imports fluidsynth -------
def _setup_fluidsynth_path():
    fluidsynth_bin = _PROJECT_ROOT / "assets" / "fluidsynth-v2.5.1" / "bin"
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
from src.engines.game_tiles import TilesGame, SONG_NAMES
from src.engines.lighting_controller import IdleLightingService
from src.engines.recorder import MidiRecorder
from src.engines.scores import save_game_score
from src.instruments.common import (
    init_fluidsynth, load_all_soundfonts, select_instrument,
    setup_video_capture, fit_resolution_to_screen,
    CameraThread, prepare_mediapipe_frame, MediaPipeHandsThread,
)
from src.instruments.ui_shared import (
    load_custom_font, FONT_FAMILY,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL, FONT_SIZE_TIMER,
    BTN_HEIGHT, BORDER_RAD, PROJECT_ROOT,
)

import fluidsynth as _fluidsynth  # noqa: F401 - side-effect: DLL already in PATH

# ---------------------------------------------------------------------------
# Game-mode color palette  (dark/purple - opposite of warm-light practice mode)
# ---------------------------------------------------------------------------
GAME_BG_PANEL       = "#0F0D18"   # panel background
GAME_BG_PANEL_ALT   = "#16141F"   # slightly lighter panel element
GAME_ACCENT         = "#746292"   # COL_ACCENT_GREEN equivalent - purple
GAME_ACCENT_RED     = "#C44E6A"   # pinkish-red for misses / errors
GAME_TEXT_PRIMARY   = "#EDE7F6"   # light lavender (vs dark #2C2C2C in practice)
GAME_TEXT_SECONDARY = "#6C6080"   # muted purple (vs #8A8A8A)
GAME_TEXT_LIGHT     = "#FFFFFF"
GAME_BORDER_LIGHT   = "#231E33"   # dark purple border (vs #D5D2CD light)
GAME_CARD_BORDER    = "#211D2E"   # slightly lighter than BG_PANEL_ALT for card edges
GAME_KEY_ACTIVE     = "#746292"   # same as accent
GAME_KEY_WHITE      = "#1C1830"   # dark "white" key surface
GAME_KEY_BLACK      = "#0C0A18"   # very dark black key surface
GAME_DIFF_EASY      = "#4E7C5E"   # muted forest green
GAME_DIFF_MEDIUM    = "#7A6830"   # muted gold
GAME_DIFF_HARD      = "#8A3A50"   # deep rose
GAME_DIFF_SELECTED  = "#7ECBA1"   # keyboard.py green - all diff levels when selected

_DIFF_LABELS = {"easy": "NORMAL", "medium": "HARD", "hard": "IMPOSSIBLE"}

# ---------------------------------------------------------------------------
# Tile colors - purple-family variants per note class (all rooted in #746292)
# ---------------------------------------------------------------------------
_TILE_COLORS: list[tuple[int, int, int]] = [
    (116,  98, 146),  # 0  C   - base purple      #746292
    (126,  84, 158),  # 1  C#  - deeper violet
    (106,  80, 168),  # 2  D   - bluer purple
    (132,  90, 155),  # 3  D#  - warmer purple
    ( 98,  86, 162),  # 4  E   - cool indigo
    (142, 100, 148),  # 5  F   - warm lavender
    ( 94,  76, 172),  # 6  F#  - deep blue-purple
    (122, 108, 140),  # 7  G   - lighter mauve
    (152,  88, 138),  # 8  G#  - dusty rose-purple
    (110,  70, 158),  # 9  A   - deep violet
    (134, 112, 146),  # 10 A#  - muted orchid
    (106,  94, 150),  # 11 B   - cool purple
]


def _tile_color(midi_note: int) -> tuple[int, int, int]:
    return _TILE_COLORS[int(midi_note) % 12]


# ---------------------------------------------------------------------------
# Piano / keyboard constants (same as keyboard_ui.py)
# ---------------------------------------------------------------------------
BLACK_KEY_NOTE_CLASSES   = {1, 3, 6, 8, 10}
BLACK_KEY_HEIGHT_RATIO   = 0.62
BLACK_KEY_WIDTH_RATIO    = 0.44
ACTIVE_FINGERS           = [4, 8, 12, 16, 20]

_GAME_BASE_NOTE = 55   # G3
_GAME_NUM_KEYS  = 22   # G3 -> A4 (covers all built-in songs + extra)
DEFAULT_TABLE_Y = 0.72  # hit-line at 72% from top of camera area


def is_black_key(midi_note: int) -> bool:
    return (int(midi_note) % 12) in BLACK_KEY_NOTE_CLASSES


def _apply_piano_geometry(keys: list) -> None:
    if not keys:
        return
    whites = [k for k in sorted(keys, key=lambda k: k["note"]) if not k["is_black"]]
    if not whites:
        w = 1.0 / max(1, len(keys))
        for i, k in enumerate(keys):
            k["x_start_norm"] = i * w
            k["x_end_norm"]   = min(1.0, (i + 1) * w)
        return
    ww = 1.0 / max(1, len(whites))
    for i, k in enumerate(whites):
        k["x_start_norm"] = i * ww
        k["x_end_norm"]   = min(1.0, (i + 1) * ww)
    wbn = {int(k["note"]): k for k in whites}
    wn  = sorted(wbn.keys())
    for k in keys:
        n = int(k["note"])
        if not k["is_black"]:
            continue
        prev = [x for x in wn if x < n]
        nxt  = [x for x in wn if x > n]
        if prev and nxt:
            center = (wbn[prev[-1]]["x_end_norm"] + wbn[nxt[0]]["x_start_norm"]) * 0.5
        elif prev:
            center = wbn[prev[-1]]["x_end_norm"] - ww * 0.5
        elif nxt:
            center = wbn[nxt[0]]["x_start_norm"] + ww * 0.5
        else:
            center = 0.5
        bw = ww * BLACK_KEY_WIDTH_RATIO
        k["x_start_norm"] = max(0.0, center - bw * 0.5)
        k["x_end_norm"]   = min(1.0, center + bw * 0.5)


def _build_game_keys() -> list:
    keys = []
    for i in range(_GAME_NUM_KEYS):
        note = _GAME_BASE_NOTE + i
        keys.append({
            "note":         note,
            "last_hit":     0.0,
            "is_active":    False,
            "is_black":     is_black_key(note),
            "x_start_norm": 0.0,
            "x_end_norm":   1.0,
        })
    _apply_piano_geometry(keys)
    return keys


def _get_key_index_from_x(keys: list, x_norm: float) -> int:
    x = max(0.0, min(1.0, float(x_norm)))
    for i, k in enumerate(keys):
        if k["is_black"] and k["x_start_norm"] <= x <= k["x_end_norm"]:
            return i
    for i, k in enumerate(keys):
        if not k["is_black"] and k["x_start_norm"] <= x <= k["x_end_norm"]:
            return i
    best, best_d = 0, float("inf")
    for i, k in enumerate(keys):
        c = (k["x_start_norm"] + k["x_end_norm"]) * 0.5
        d = abs(c - x)
        if d < best_d:
            best, best_d = i, d
    return best


# ---------------------------------------------------------------------------
# Game Camera Overlay Widget
# ---------------------------------------------------------------------------

class GameCameraOverlayWidget(QWidget):
    """
    Right-side widget: camera feed + game overlays.
    Renders falling tiles, piano keys, hand trackers, precision messages.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._frame_rgb = None
        self._results   = None
        self._piano_keys = []
        self._table_y   = DEFAULT_TABLE_Y
        self._detecting = False

        self._game = None
        self._is_paused = False

        self._last_result    = None
        self._last_result_ts = 0.0

        self._state_overlay  = None
        self._final_score    = 0
        self._countdown_num  = 0   # 0 = hidden

    def set_frame(self, frame_rgb):
        self._frame_rgb = frame_rgb

    def set_results(self, results):
        self._results  = results
        self._detecting = (
            results is not None and results.multi_hand_landmarks is not None
        )

    def set_piano_keys(self, keys):
        self._piano_keys = keys

    def set_table_y(self, y):
        self._table_y = y

    def set_game(self, game):
        self._game = game

    def set_precision_result(self, result, ts):
        self._last_result    = result
        self._last_result_ts = ts

    def set_paused(self, paused):
        self._is_paused = paused

    def set_state_overlay(self, state, final_score=0):
        self._state_overlay = state
        self._final_score   = final_score

    def set_countdown(self, n: int) -> None:
        """Show countdown digit n (1-3). 0 = hidden."""
        self._countdown_num = n
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, QColor(GAME_BG_PANEL))

        if self._frame_rgb is not None:
            frame = np.ascontiguousarray(self._frame_rgb)
            fh, fw = frame.shape[:2]
            qimg = QImage(frame.data, fw, fh, fw * 3, QImage.Format_RGB888)
            painter.drawImage(0, 0, qimg.scaled(w, h, Qt.IgnoreAspectRatio,
                                                  Qt.FastTransformation))

        table_px = int(self._table_y * h)
        painter.fillRect(0, 0, w, table_px, QColor(0, 0, 0, 70))

        if self._game is not None and not self._is_paused:
            self._draw_tiles(painter, w, h)

        self._draw_piano_keys(painter, w, h)

        self._draw_precision_message(painter, w, h)

        if self._is_paused:
            self._draw_pause_overlay(painter, w, h)
        elif self._state_overlay in ("gameover_win", "gameover_lose"):
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))

        if self._countdown_num > 0:
            self._draw_countdown(painter, w, h)

        painter.end()

    def _draw_tiles(self, painter, w, h):
        if self._game is None:
            return
        now      = time.time()
        table_px = int(self._table_y * h)

        for tile in self._game.tiles:
            note  = tile.note
            r, g, b = _tile_color(note)

            x1_px = int(tile.x_start_norm * w)
            x2_px = int(tile.x_end_norm   * w)
            tw    = max(2, x2_px - x1_px - 2)

            lead_y = self._game.tile_y_norm(tile, now)
            tail_y = self._game.tile_tail_y_norm(tile, now)

            lead_px = int(lead_y * table_px)
            tail_px = int(tail_y * table_px)

            draw_y1 = max(0, tail_px)
            draw_y2 = min(table_px, lead_px)
            if draw_y2 <= draw_y1:
                continue
            tile_h = draw_y2 - draw_y1

            if tile.state == "hit":
                age   = now - tile.arrive_time
                alpha = max(0, min(255, int(220 * (1.0 - age / 0.35))))
                c = QColor(GAME_ACCENT)
                c.setAlpha(alpha)
                painter.fillRect(x1_px + 1, draw_y1, tw, tile_h, c)
                border_c = QColor(220, 200, 255, alpha)
                painter.setPen(QPen(border_c, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(x1_px + 1, draw_y1, tw, tile_h)

            elif tile.state == "miss":
                age   = now - tile.arrive_time
                alpha = max(0, min(255, int(180 * (1.0 - age / 0.5))))
                c = QColor(GAME_ACCENT_RED)
                c.setAlpha(alpha)
                painter.fillRect(x1_px + 1, draw_y1, tw, tile_h, c)

            else:
                c = QColor(r, g, b, 210)
                painter.fillRect(x1_px + 1, draw_y1, tw, tile_h, c)

                if lead_px >= table_px - 8:
                    pulse     = 0.5 + 0.5 * math.sin(now * 12)
                    edge_a    = int(120 + 120 * pulse)
                    edge_c    = QColor(200, 170, 255, edge_a)
                    painter.fillRect(x1_px + 1, max(0, draw_y2 - 4), tw, 4, edge_c)

                bc = QColor(min(255, r + 55), min(255, g + 55), min(255, b + 55), 160)
                painter.setPen(QPen(bc, 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(x1_px + 1, draw_y1, tw, tile_h)

    def _draw_piano_keys(self, painter, w, h):
        if not self._piano_keys:
            return
        table_px = int(self._table_y * h)
        total_h  = h - table_px
        if total_h <= 0:
            return
        black_h = int(total_h * BLACK_KEY_HEIGHT_RATIO)
        now     = time.time()

        for k in self._piano_keys:
            if k["is_black"]:
                continue
            x1 = int(k["x_start_norm"] * w)
            x2 = int(k["x_end_norm"]   * w)
            kw = max(1, x2 - x1)

            active = k["is_active"] or (now - k["last_hit"]) < 0.15
            if active:
                c = QColor(GAME_KEY_ACTIVE)
                c.setAlpha(210)
            else:
                c = QColor(GAME_KEY_WHITE)
                c.setAlpha(28)
            painter.fillRect(x1, table_px, kw, total_h, c)
            painter.setPen(QPen(QColor(100, 80, 150, 55), 1))
            painter.drawLine(x1, table_px, x1, h)

        for k in self._piano_keys:
            if not k["is_black"]:
                continue
            x1 = int(k["x_start_norm"] * w)
            x2 = int(k["x_end_norm"]   * w)
            kw = max(1, x2 - x1)

            active = k["is_active"] or (now - k["last_hit"]) < 0.15
            if active:
                c = QColor(GAME_KEY_ACTIVE)
                c.setAlpha(230)
            else:
                c = QColor(GAME_KEY_BLACK)
                c.setAlpha(170)
            painter.fillRect(x1, table_px, kw, black_h, c)
            painter.setPen(QPen(QColor(60, 40, 90, 90), 1))
            painter.drawRect(x1, table_px, kw, black_h)

        painter.setPen(QPen(QColor(GAME_ACCENT), 3))
        painter.drawLine(0, table_px, w, table_px)

        for i in range(1, 4):
            alpha = max(0, 50 - i * 14)
            gc = QColor(GAME_ACCENT)
            gc.setAlpha(alpha)
            painter.setPen(QPen(gc, 1))
            painter.drawLine(0, table_px - i, w, table_px - i)
            painter.drawLine(0, table_px + i, w, table_px + i)

    def _draw_hand_connections(self, painter, w, h):
        if not self._results or not self._results.multi_hand_landmarks:
            return
        connections = [
            (0,1),(1,2),(2,3),(3,4),
            (0,5),(5,6),(6,7),(7,8),
            (0,9),(9,10),(10,11),(11,12),
            (0,13),(13,14),(14,15),(15,16),
            (0,17),(17,18),(18,19),(19,20),
            (5,9),(9,13),(13,17),
        ]
        for lm in self._results.multi_hand_landmarks:
            pen = QPen(QColor(GAME_ACCENT), 2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            for a, b in connections:
                ax = int(lm.landmark[a].x * w)
                ay = int(lm.landmark[a].y * h)
                bx = int(lm.landmark[b].x * w)
                by = int(lm.landmark[b].y * h)
                painter.drawLine(ax, ay, bx, by)
            painter.setBrush(QBrush(QColor(GAME_ACCENT)))
            painter.setPen(Qt.NoPen)
            for pt in lm.landmark:
                px = int(pt.x * w)
                py = int(pt.y * h)
                painter.drawEllipse(px - 3, py - 3, 6, 6)

    def _draw_precision_message(self, painter, w, h):
        if not self._last_result:
            return
        now      = time.time()
        age      = now - self._last_result_ts
        duration = 0.9
        if age > duration:
            return

        alpha    = int(255 * max(0.0, 1.0 - age / duration))
        float_up = int(age / duration * 28)

        table_px = int(self._table_y * h)
        msg_y    = table_px - 65 - float_up

        result = self._last_result
        if result == "perfect":
            text = "PERFEITO!"
            col  = QColor(220, 200, 255, alpha)
        elif result == "good":
            text = "BOM!"
            col  = QColor(180, 155, 220, alpha)
        else:
            text = "ERROU"
            col  = QColor(196, 78, 106, alpha)

        f = QFont(FONT_FAMILY, FONT_SIZE_XL)
        f.setBold(True)
        painter.setFont(f)
        fm     = painter.fontMetrics()
        text_w = fm.horizontalAdvance(text)
        cx     = w // 2 - text_w // 2

        shadow = QColor(0, 0, 0, alpha // 2)
        painter.setPen(shadow)
        painter.drawText(cx + 2, msg_y + 2, text)

        painter.setPen(col)
        painter.drawText(cx, msg_y, text)

    def _draw_countdown(self, painter, w, h):
        n = self._countdown_num
        if n <= 0:
            return
        text = str(n)
        f = QFont(FONT_FAMILY, 120)
        f.setBold(True)
        painter.setFont(f)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text)
        cx = w // 2 - tw // 2
        cy = h // 2 + fm.ascent() // 2 - 10

        # glow layers
        glow_col = QColor(116, 98, 146)
        for r_offset, alpha in ((28, 30), (18, 60), (10, 100)):
            gc = QColor(glow_col)
            gc.setAlpha(alpha)
            painter.setPen(gc)
            painter.drawText(cx - r_offset // 2, cy - r_offset // 2, text)
            painter.drawText(cx + r_offset // 2, cy + r_offset // 2, text)

        painter.setPen(QColor(220, 200, 255))
        painter.drawText(cx, cy, text)

    def _draw_pause_overlay(self, painter, w, h):
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))

        f = QFont(FONT_FAMILY, 36)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(GAME_ACCENT))
        text = "PAUSADO"
        fm   = painter.fontMetrics()
        painter.drawText(w // 2 - fm.horizontalAdvance(text) // 2, h // 2, text)

        f2 = QFont(FONT_FAMILY, FONT_SIZE_SM)
        painter.setFont(f2)
        painter.setPen(QColor(GAME_TEXT_SECONDARY))
        sub = "Clique em Retomar para continuar"
        fm2 = painter.fontMetrics()
        painter.drawText(w // 2 - fm2.horizontalAdvance(sub) // 2, h // 2 + 42, sub)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_score(score: int) -> str:
    """Brazilian-style thousands separator: 2840 → '2.840'."""
    return f"{score:,}".replace(",", ".")


# ---------------------------------------------------------------------------
# Lives indicator widget
# ---------------------------------------------------------------------------

class LivesWidget(QWidget):
    """Draws filled/empty circles to represent lives remaining."""

    _R   = 7    # dot radius
    _GAP = 10   # gap between dots

    def __init__(self, max_lives: int = 5, parent=None):
        super().__init__(parent)
        self._max_lives = max_lives
        self._lives     = max_lives
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_lives(self, lives: int, max_lives: int | None = None) -> None:
        if max_lives is not None:
            self._max_lives = max_lives
        self._lives = max(0, min(self._max_lives, lives))
        self.update()

    def sizeHint(self):
        r, gap = self._R, self._GAP
        w = self._max_lives * (r * 2) + (self._max_lives - 1) * gap
        return QSize(w, r * 2 + 4)

    def paintEvent(self, event):
        r, gap = self._R, self._GAP
        w, h   = self.width(), self.height()
        n      = self._max_lives
        total_w = n * (r * 2) + (n - 1) * gap
        x0      = (w - total_w) // 2
        cy      = h // 2

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(n):
            cx = x0 + i * (r * 2 + gap) + r
            p.setPen(Qt.NoPen)
            if i < self._lives:
                p.setBrush(QBrush(QColor(GAME_ACCENT)))
            else:
                p.setBrush(QBrush(QColor(GAME_CARD_BORDER)))
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        p.end()


# ---------------------------------------------------------------------------
# Progress bar widget
# ---------------------------------------------------------------------------

class ProgressBarWidget(QWidget):
    """Horizontal progress bar painted with QPainter — avoids QSS conflicts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0   # 0.0 .. 1.0
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_progress(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h // 2

        # track
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(GAME_CARD_BORDER)))
        p.drawRoundedRect(0, 0, w, h, r, r)

        # fill
        fill_w = int(w * self._value)
        if fill_w > 0:
            p.setBrush(QBrush(QColor(GAME_ACCENT)))
            p.drawRoundedRect(0, 0, fill_w, h, r, r)

        # label
        pct = int(self._value * 100)
        p.setPen(QColor(GAME_TEXT_LIGHT if self._value > 0.5 else GAME_TEXT_SECONDARY))
        font = QFont(FONT_FAMILY, 9)
        font.setBold(True)
        p.setFont(font)
        txt = f"{pct}%"
        fm  = p.fontMetrics()
        p.drawText(w // 2 - fm.horizontalAdvance(txt) // 2,
                   h // 2 + fm.ascent() // 2 - 1, txt)
        p.end()


# ---------------------------------------------------------------------------
# Scaling label — font-size tracks widget height
# ---------------------------------------------------------------------------

class ScalingLabel(QLabel):
    """QLabel that resizes its font dynamically to fill available height."""

    def __init__(self, text="", scale=0.45, parent=None):
        super().__init__(text, parent)
        self._scale = scale

    def resizeEvent(self, event):
        super().resizeEvent(event)
        h = self.height()
        if h > 8:
            px = max(10, int(h * self._scale))
            self.setStyleSheet(f"font-size: {px}px; font-weight: bold;")


# ---------------------------------------------------------------------------
# Game Control Panel  (left side)
# ---------------------------------------------------------------------------

class GamePanel(QWidget):
    """Left panel — two stacked views:
    • Playing   : live stats (score, combo, lives, precision, progress) + song/diff info bar
    • Game-over : results summary + new-game options (song, difficulty, play button)
    """

    restart_clicked    = Signal()
    end_clicked        = Signal()
    pause_toggled      = Signal(bool)

    def __init__(self, song_names, parent=None):
        super().__init__(parent)
        self.setObjectName("gamePanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._song_names          = song_names
        self._current_difficulty  = "easy"
        self._current_song_idx    = 0
        self._prec_hits           = 0
        self._prec_total          = 0
        self._last_seen_result_ts = 0.0

        self._init_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_title_block())

        self._stack = QStackedWidget()
        self._playing_page  = self._build_playing_page()
        self._gameover_page = self._build_gameover_page()
        self._stack.addWidget(self._playing_page)   # idx 0
        self._stack.addWidget(self._gameover_page)  # idx 1
        outer.addWidget(self._stack, 1)

        # ── Bottom buttons: Encerrar + Pausar, centered ─────────────
        btn_area = QVBoxLayout()
        btn_area.setContentsMargins(12, 8, 12, 12)
        btn_area.setSpacing(6)

        self._pause_btn = QPushButton("⏸  Pausar")
        self._pause_btn.setObjectName("gamePauseBtn")
        self._pause_btn.setCheckable(True)
        self._pause_btn.clicked.connect(self._on_pause_click)
        btn_area.addWidget(self._pause_btn)

        self._end_btn = QPushButton("Encerrar")
        self._end_btn.setObjectName("gameEndBtn")
        self._end_btn.clicked.connect(self.end_clicked.emit)
        btn_area.addWidget(self._end_btn)

        outer.addLayout(btn_area)

    def _build_title_block(self) -> QWidget:
        """Title + icon block — card-sized visually, no border, no separator."""
        w = QWidget()
        w.setObjectName("gameTitleBlock")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(12, 14, 12, 14)
        vl.setAlignment(Qt.AlignCenter)
        vl.setSpacing(2)

        icon = QLabel("✦")
        icon.setObjectName("gameIconLabel")
        icon.setAlignment(Qt.AlignCenter)
        vl.addWidget(icon)

        title = QLabel("Talking Hands")
        title.setObjectName("gameHeaderLabel")
        title.setAlignment(Qt.AlignCenter)
        vl.addWidget(title)
        return w

    def _make_stat_card(self, value_obj_name: str, sub_text: str):
        """Returns (card_widget, value_ScalingLabel)."""
        card = QFrame()
        card.setObjectName("gameStatCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(2)
        val = ScalingLabel("0", scale=0.42)
        val.setObjectName(value_obj_name)
        val.setAlignment(Qt.AlignCenter)
        val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl.addWidget(val, 1)
        sub = QLabel(sub_text)
        sub.setObjectName("gameStatCardSub")
        sub.setAlignment(Qt.AlignCenter)
        vl.addWidget(sub)
        return card, val

    def _build_playing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)

        card, self._score_label = self._make_stat_card("gameScoreValue", "PONTOS")
        layout.addWidget(card, 1)

        card, self._combo_label = self._make_stat_card("gameComboValue", "COMBO")
        layout.addWidget(card, 1)

        card, self._precision_label = self._make_stat_card("gamePrecisionValue", "PRECISÃO")
        layout.addWidget(card, 1)

        # Progress bar
        prog_frame = QFrame()
        prog_frame.setObjectName("gameStatCard")
        prog_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        prog_vl = QVBoxLayout(prog_frame)
        prog_vl.setContentsMargins(10, 8, 10, 8)
        prog_vl.setSpacing(4)
        self._progress_bar = ProgressBarWidget()
        prog_vl.addWidget(self._progress_bar)
        prog_sub = QLabel("PROGRESSO")
        prog_sub.setObjectName("gameStatCardSub")
        prog_sub.setAlignment(Qt.AlignCenter)
        prog_vl.addWidget(prog_sub)
        layout.addWidget(prog_frame)

        # Bottom info bar: current song + difficulty badge
        info_bar = QFrame()
        info_bar.setObjectName("gameInfoBar")
        bar_row = QHBoxLayout(info_bar)
        bar_row.setContentsMargins(10, 8, 10, 8)
        bar_row.setSpacing(8)

        self._play_song_label = QLabel("-")
        self._play_song_label.setObjectName("gamePlaySongLabel")
        self._play_song_label.setWordWrap(True)
        bar_row.addWidget(self._play_song_label, 1)

        self._play_diff_label = QLabel("NORMAL")
        self._play_diff_label.setObjectName("gamePlayDiffLabel")
        bar_row.addWidget(self._play_diff_label)
        layout.addWidget(info_bar)

        self._fps_label = QLabel("FPS: --")
        self._fps_label.setObjectName("gameFpsLabel")
        layout.addWidget(self._fps_label)

        return page

    def _build_gameover_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Top half: results ─────────────────────────────────────────────
        results_w = QWidget()
        results_l = QVBoxLayout(results_w)
        results_l.setContentsMargins(8, 6, 8, 4)
        results_l.setSpacing(5)

        self._result_title = QLabel("FIM DE JOGO")
        self._result_title.setObjectName("gameResultTitle")
        self._result_title.setAlignment(Qt.AlignCenter)
        results_l.addWidget(self._result_title)

        card, self._result_score_label = self._make_stat_card("gameScoreValue", "PONTOS")
        results_l.addWidget(card, 2)

        side_row = QHBoxLayout()
        side_row.setSpacing(5)
        ccard, self._result_combo_label = self._make_stat_card("gameComboValue", "COMBO")
        pcard, self._result_prec_label  = self._make_stat_card("gamePrecisionValue", "PRECISÃO")
        side_row.addWidget(ccard)
        side_row.addWidget(pcard)
        results_l.addLayout(side_row, 1)

        outer.addWidget(results_w, 1)

        # ── Divider ───────────────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {GAME_BORDER_LIGHT};")
        outer.addWidget(div)

        # ── Bottom half: replay with the configuration selected in the menu ─
        newgame_w = QWidget()
        newgame_l = QVBoxLayout(newgame_w)
        newgame_l.setContentsMargins(8, 6, 8, 6)
        newgame_l.setSpacing(5)

        start_btn = QPushButton("▶  Jogar Novamente")
        start_btn.setObjectName("gameStartBtn")
        start_btn.setFixedHeight(BTN_HEIGHT + 2)
        start_btn.clicked.connect(self.restart_clicked.emit)
        newgame_l.addWidget(start_btn, 1)

        self._fps_label_go = QLabel("FPS: --")
        self._fps_label_go.setObjectName("gameFpsLabel")
        newgame_l.addWidget(self._fps_label_go)

        outer.addWidget(newgame_w, 1)

        return page

    # ── public API ────────────────────────────────────────────────────────

    def switch_to_playing(self) -> None:
        """Show the live-gameplay stats view and reset precision counters."""
        self._prec_hits           = 0
        self._prec_total          = 0
        self._last_seen_result_ts = 0.0
        self._update_diff_badge_color(self._current_difficulty)
        self._stack.setCurrentIndex(0)

    def switch_to_gameover(self, game, won: bool) -> None:
        """Populate results and switch to the game-over view."""
        title = "VOCÊ VENCEU!" if won else "FIM DE JOGO"
        self._result_title.setText(title)
        obj = "gameResultTitleWin" if won else "gameResultTitle"
        self._result_title.setObjectName(obj)
        self._result_title.style().unpolish(self._result_title)
        self._result_title.style().polish(self._result_title)

        self._result_score_label.setText(_fmt_score(game.score))
        self._result_combo_label.setText(f"×{game.combo}")
        precision = int(self._prec_hits / max(1, self._prec_total) * 100)
        self._result_prec_label.setText(f"{precision}%")
        self._stack.setCurrentIndex(1)

    def update_game_state(self, game) -> None:
        self._score_label.setText(_fmt_score(game.score))
        self._combo_label.setText(f"×{game.combo}")
        if game.last_result_ts != self._last_seen_result_ts and game.last_result:
            self._last_seen_result_ts = game.last_result_ts
            if game.last_result in ("perfect", "good"):
                self._prec_hits += 1
            self._prec_total += 1

        precision = int(self._prec_hits / max(1, self._prec_total) * 100)
        self._precision_label.setText(f"{precision}%")

        self._progress_bar.set_progress(game.progress)

    def update_song(self, idx: int) -> None:
        if 0 <= idx < len(self._song_names):
            name = self._song_names[idx]
            self._play_song_label.setText(name)
        self._current_song_idx = idx

    def set_difficulty(self, diff: str) -> None:
        self._current_difficulty = diff
        self._update_diff_badge_color(diff)

    def update_fps(self, fps: float) -> None:
        txt = f"FPS: {fps:.0f}"
        self._fps_label.setText(txt)
        self._fps_label_go.setText(txt)

    def reset_pause(self) -> None:
        self._pause_btn.setChecked(False)
        self._pause_btn.setText("⏸  Pausar")

    def _on_pause_click(self, checked: bool) -> None:
        self._pause_btn.setText("▶  Retomar" if checked else "⏸  Pausar")
        self.pause_toggled.emit(checked)

    def get_difficulty(self) -> str:
        return self._current_difficulty

    # ── private helpers ───────────────────────────────────────────────────

    def _add_section_title(self, layout, text):
        lbl = QLabel(text)
        lbl.setObjectName("gameSectionTitle")
        layout.addWidget(lbl)

    def _update_diff_badge_color(self, diff: str) -> None:
        color_map = {
            "easy":   GAME_DIFF_EASY,
            "medium": GAME_DIFF_MEDIUM,
            "hard":   GAME_DIFF_HARD,
        }
        col = color_map.get(diff, GAME_ACCENT)
        self._play_diff_label.setStyleSheet(
            f"background-color: {col}; color: {GAME_TEXT_LIGHT}; "
            f"border-radius: 6px; padding: 2px 8px; "
            f"font-size: {FONT_SIZE_SM}px; font-family: {FONT_FAMILY}; font-weight: bold;"
        )


# ---------------------------------------------------------------------------
# QSS - game-mode dark/purple theme
# ---------------------------------------------------------------------------

def _build_game_qss():
    return f"""
QMainWindow {{
    background-color: {GAME_BG_PANEL};
}}

#gamePanel {{
    background-color: {GAME_BG_PANEL};
    border-right: 1px solid {GAME_BORDER_LIGHT};
}}

#gamePanel QLabel {{
    color: {GAME_TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
}}

/* ── Header ─────────────────────────────────────────────────────────── */
QFrame#gamePanelHeader {{
    background-color: {GAME_BG_PANEL};
}}

/* ── Title block (no card frame, no separator) ───────────────────────── */
QWidget#gameTitleBlock {{
    background-color: {GAME_BG_PANEL};
}}

QLabel#gameIconLabel {{
    font-size: 20px;
    color: {GAME_ACCENT};
}}

QLabel#gameHeaderLabel {{
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    color: {GAME_TEXT_SECONDARY};
    letter-spacing: 2px;
}}

/* ── Stat cards ──────────────────────────────────────────────────────── */
QFrame#gameStatCard {{
    background-color: {GAME_BG_PANEL_ALT};
    border: 1px solid {GAME_CARD_BORDER};
    border-radius: {BORDER_RAD}px;
}}

QLabel#gameStatCardSub {{
    font-size: {FONT_SIZE_SM}px;
    color: {GAME_TEXT_SECONDARY};
    letter-spacing: 2px;
}}

/* value labels — font-size set dynamically by ScalingLabel.resizeEvent */
QLabel#gameScoreValue {{
    color: {GAME_ACCENT};
}}

QLabel#gameComboValue {{
    color: {GAME_TEXT_PRIMARY};
}}

QLabel#gamePrecisionValue {{
    color: {GAME_TEXT_PRIMARY};
}}

/* ── Section labels ─────────────────────────────────────────────────── */
QLabel#gameStatSectionLabel {{
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    color: {GAME_TEXT_SECONDARY};
    letter-spacing: 1px;
}}

QLabel#gameProgressLabel {{
    font-size: {FONT_SIZE_SM}px;
    color: {GAME_TEXT_SECONDARY};
}}

QLabel#gameFpsLabel {{
    font-size: {FONT_SIZE_SM}px;
    color: {GAME_TEXT_SECONDARY};
}}

/* ── Playing info bar (song + diff badge) ───────────────────────────── */
QFrame#gameInfoBar {{
    background-color: {GAME_BG_PANEL_ALT};
    border: 1px solid {GAME_CARD_BORDER};
    border-radius: {BORDER_RAD}px;
}}

QLabel#gamePlaySongLabel {{
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    color: {GAME_TEXT_PRIMARY};
}}

/* ── Game-over result title ─────────────────────────────────────────── */
QLabel#gameResultTitle {{
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    color: {GAME_ACCENT_RED};
}}

QLabel#gameResultTitleWin {{
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    color: {GAME_ACCENT};
}}

/* ── Song label in gameover page ────────────────────────────────────── */
QLabel#gameSongLabel {{
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    color: {GAME_TEXT_PRIMARY};
}}

/* ── Buttons ─────────────────────────────────────────────────────────── */
QPushButton#gameEndBtn {{
    background-color: transparent;
    color: {GAME_ACCENT_RED};
    border: 1px solid {GAME_ACCENT_RED};
    border-radius: {BORDER_RAD}px;
    padding: 8px 10px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#gameEndBtn:hover {{
    background-color: {GAME_ACCENT_RED};
    color: white;
}}

QPushButton#gamePauseBtn {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_TEXT_PRIMARY};
    border: 1px solid {GAME_CARD_BORDER};
    border-radius: {BORDER_RAD}px;
    padding: 10px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#gamePauseBtn:checked {{
    background-color: {GAME_ACCENT};
    color: {GAME_TEXT_LIGHT};
    border-color: {GAME_ACCENT};
}}
QPushButton#gamePauseBtn:hover {{
    border-color: {GAME_ACCENT};
    color: {GAME_ACCENT};
}}
QPushButton#gamePauseBtn:checked:hover {{
    background-color: #8B74A8;
    color: {GAME_TEXT_LIGHT};
}}

QPushButton#gameNavBtn {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_TEXT_PRIMARY};
    border: 1px solid {GAME_CARD_BORDER};
    border-radius: {BORDER_RAD}px;
    font-size: {FONT_SIZE_MD}px;
    font-family: {FONT_FAMILY};
    height: {BTN_HEIGHT - 10}px;
    padding: 2px;
}}
QPushButton#gameNavBtn:hover {{
    border-color: {GAME_ACCENT};
    color: {GAME_ACCENT};
}}

QPushButton#gameDiffBtn_easy, QPushButton#gameDiffBtn_medium, QPushButton#gameDiffBtn_hard {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_TEXT_PRIMARY};
    border: 1px solid {GAME_CARD_BORDER};
    border-radius: {BORDER_RAD}px;
    padding: 6px 4px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#gameDiffBtn_easy:checked,
QPushButton#gameDiffBtn_medium:checked,
QPushButton#gameDiffBtn_hard:checked {{
    background-color: {GAME_DIFF_SELECTED};
    color: #0F1A14;
    border-color: {GAME_DIFF_SELECTED};
    font-weight: bold;
}}
QPushButton#gameDiffBtn_easy:hover,
QPushButton#gameDiffBtn_medium:hover,
QPushButton#gameDiffBtn_hard:hover {{
    border-color: {GAME_ACCENT};
}}

QPushButton#gameStartBtn {{
    background-color: {GAME_ACCENT};
    color: {GAME_TEXT_LIGHT};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 10px;
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    font-family: {FONT_FAMILY};
}}
QPushButton#gameStartBtn:hover {{
    background-color: #8B74A8;
}}
"""


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class PianoTilesWindow(QMainWindow):
    """
    Fullscreen Piano Tiles window.
    Layout (mirrored vs practice mode):  [GamePanel 1/3 LEFT] | [Camera 2/3 RIGHT]
    Camera width is locked - no splitter drag.
    """

    def __init__(
        self,
        instrument_name="Piano",
        resolution_profile=None,
        show_trackers=True,
        hand_model_complexity=1,
        difficulty="easy",
        song="Twinkle Twinkle",
        nickname="",
        lighting_service: IdleLightingService | None = None,
    ):
        super().__init__()
        self.setWindowTitle("Talking Hands - Piano Tiles")
        self.setStyleSheet(_build_game_qss())

        self._instrument_name = instrument_name
        self._lighting_service = lighting_service

        self._audio_queue  = queue.Queue()
        self._fs           = None
        self._loaded_sfids = {}
        self._recorder     = MidiRecorder()
        self._init_audio()

        self._piano_keys = _build_game_keys()

        self._game = TilesGame()
        self._game.set_key_layout(self._piano_keys)
        self._current_difficulty = difficulty if difficulty in ("easy", "medium", "hard") else "easy"
        self._current_song_idx   = SONG_NAMES.index(song) if song in SONG_NAMES else 0
        self._nickname           = " ".join(str(nickname).split())[:24]
        self._score_saved        = False
        self._is_paused          = False
        self._table_y            = DEFAULT_TABLE_Y

        self._countdown_val   = 0
        self._countdown_timer = None

        self._finger_prev_y     = {}
        self._active_held_notes = {}
        self._pending_note_offs = []

        if resolution_profile:
            dw = int(resolution_profile["display_width"])
            dh = int(resolution_profile["display_height"])
            self._target_fps = int(resolution_profile["fps"])
        else:
            dw, dh           = 1920, 1080
            self._target_fps = 30
        dw, dh, _, _, _ = fit_resolution_to_screen(dw, dh)
        self._logical_w, self._logical_h = dw, dh

        self._cap = setup_video_capture(
            width=self._logical_w, height=self._logical_h, fps=self._target_fps,
        )
        self._cam_thread = CameraThread(self._cap)

        hc = max(0, min(1, int(hand_model_complexity)))
        self._hands_thread = MediaPipeHandsThread(
            mp.solutions.hands.Hands(
                max_num_hands=2, model_complexity=hc,
                min_detection_confidence=0.3, min_tracking_confidence=0.3,
            )
        )

        self._build_ui(show_trackers)

        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)
        self._frame_timer.start(1)

        self._fps_counter   = 0
        self._fps_last_time = time.time()

        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

        select_instrument(
            self._fs, instrument_name, self._loaded_sfids,
            self._recorder, channel=0, is_drum=False,
        )

        self._camera_widget.set_state_overlay(None)
        QTimer.singleShot(400, self._start_game)

    def _init_audio(self):
        self._fs, self._loaded_sfids = init_fluidsynth(driver="dsound")
        if self._fs is None:
            print("ERRO CRITICO DE AUDIO: Falha ao inicializar FluidSynth")
        else:
            self._loaded_sfids = load_all_soundfonts(self._fs)

    def _audio_loop(self):
        while True:
            item = self._audio_queue.get()
            if item is None:
                break
            action, note = item[0], item[1]
            if action == "on" and self._fs:
                self._fs.noteon(0, note, 127)
            elif action == "off" and self._fs:
                self._fs.noteoff(0, note)

    def _build_ui(self, show_trackers):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._panel = GamePanel(song_names=SONG_NAMES)
        self._panel.restart_clicked.connect(self._on_restart)
        self._panel.end_clicked.connect(self._on_end)
        self._panel.pause_toggled.connect(self._on_pause_toggled)

        self._camera_widget = GameCameraOverlayWidget()
        self._camera_widget.set_piano_keys(self._piano_keys)
        self._camera_widget.set_table_y(self._table_y)
        self._camera_widget.set_game(self._game)

        main_layout.addWidget(self._panel,         18)
        main_layout.addWidget(self._camera_widget, 82)

        self._panel.set_difficulty(self._current_difficulty)
        self._panel.update_song(self._current_song_idx)

    def _start_game(self):
        if self._countdown_timer is not None and self._countdown_timer.isActive():
            return
        self._score_saved = False
        self._finger_prev_y.clear()
        self._active_held_notes.clear()
        self._pending_note_offs.clear()
        self._is_paused = False
        self._panel.reset_pause()
        self._panel.switch_to_playing()
        self._camera_widget.set_paused(False)
        self._camera_widget.set_state_overlay(None)
        self._panel.update_song(self._current_song_idx)

        self._countdown_val = 3
        self._camera_widget.set_countdown(self._countdown_val)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setSingleShot(False)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start(1000)

    def _on_countdown_tick(self):
        self._countdown_val -= 1
        if self._countdown_val > 0:
            self._camera_widget.set_countdown(self._countdown_val)
        else:
            self._countdown_timer.stop()
            self._camera_widget.set_countdown(0)
            self._game.start(
                self._piano_keys,
                song=SONG_NAMES[self._current_song_idx],
                difficulty=self._current_difficulty,
            )
            self._panel.update_game_state(self._game)
            print(f">>> Piano Tiles [{self._current_difficulty.upper()}]"
                  f" - {SONG_NAMES[self._current_song_idx]}")

    @Slot()
    def _on_frame_tick(self):
        now = time.time()

        due = [(n, t) for n, t in self._pending_note_offs if now >= t]
        for note, _ in due:
            self._audio_queue.put(("off", note))
        for item in due:
            self._pending_note_offs.remove(item)

        frame, _ = self._cam_thread.get_latest()
        if frame is None:
            return

        frame     = cv2.resize(frame, (self._logical_w, self._logical_h))
        frame     = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        cam_w = self._camera_widget.width()
        cam_h = self._camera_widget.height()
        if cam_w > 0 and cam_h > 0:
            fh, fw = frame_rgb.shape[:2]
            want_aspect  = cam_w / cam_h
            frame_aspect = fw / fh
            if frame_aspect > want_aspect:
                new_fw = int(fh * want_aspect)
                x_off  = (fw - new_fw) // 2
                frame_rgb = frame_rgb[:, x_off:x_off + new_fw]
            elif frame_aspect < want_aspect:
                new_fh = int(fw / want_aspect)
                y_off  = (fh - new_fh) // 2
                frame_rgb = frame_rgb[y_off:y_off + new_fh, :]

        crh, crw = frame_rgb.shape[:2]
        frame_mp = prepare_mediapipe_frame(frame_rgb, crw, crh, 480)
        self._hands_thread.submit_frame(frame_mp)
        results = self._hands_thread.get_latest_result()

        if self._game.state == TilesGame.STATE_PLAYING and not self._is_paused:
            self._game.update(now=now)

            if results.multi_hand_landmarks:
                for idx, lm in enumerate(results.multi_hand_landmarks):
                    label = results.multi_handedness[idx].classification[0].label
                    self._process_taps(label, lm.landmark, now)

            self._panel.update_game_state(self._game)

            if self._game.last_result:
                self._camera_widget.set_precision_result(
                    self._game.last_result, self._game.last_result_ts,
                )

            if self._game.state == TilesGame.STATE_GAME_OVER:
                self._panel.update_game_state(self._game)
                won   = True
                state = "gameover_win" if won else "gameover_lose"
                self._camera_widget.set_state_overlay(state, self._game.score)
                self._panel.switch_to_gameover(self._game, won)
                if not self._score_saved:
                    self._score_saved = True
                    save_game_score(
                        "piano_tiles", self._nickname, self._game.score,
                        self._current_difficulty, SONG_NAMES[self._current_song_idx],
                        precision=self._game.precision,
                    )

        self._camera_widget.set_frame(frame_rgb)
        self._camera_widget.set_results(results)
        self._camera_widget.update()

        self._fps_counter += 1
        elapsed = now - self._fps_last_time
        if elapsed >= 1.0:
            self._panel.update_fps(self._fps_counter / elapsed)
            self._fps_counter   = 0
            self._fps_last_time = now

    def _process_taps(self, label, landmarks, now):
        for fid in ACTIVE_FINGERS:
            tip   = landmarks[fid]
            fkey  = (label, fid)
            prev_y = self._finger_prev_y.get(fkey, tip.y)
            curr_y = tip.y
            self._finger_prev_y[fkey] = curr_y

            if fkey in self._active_held_notes and prev_y >= self._table_y and curr_y < self._table_y:
                released = self._active_held_notes.pop(fkey)
                self._audio_queue.put(("off", released))
                self._pending_note_offs[:] = [
                    (n, t) for n, t in self._pending_note_offs if n != released
                ]

            if prev_y < self._table_y and curr_y >= self._table_y:
                ki   = _get_key_index_from_x(self._piano_keys, tip.x)
                note = int(self._piano_keys[ki]["note"])
                result = self._game.player_hit(note, now=now)
                if result in ("perfect", "good"):
                    self._flash_tile_hit(self._game.last_hit_duration)
                    if fkey in self._active_held_notes:
                        old = self._active_held_notes.pop(fkey)
                        self._audio_queue.put(("off", old))
                        self._pending_note_offs[:] = [
                            (n, t) for n, t in self._pending_note_offs if n != old
                        ]
                    self._audio_queue.put(("on", note))
                    self._active_held_notes[fkey] = note
                    self._pending_note_offs.append((note, now + 4.0))
                    self._piano_keys[ki]["last_hit"] = now

    def _flash_tile_hit(self, duration: float) -> None:
        """Acende a fita em roxo pela duração visual da nota acertada."""
        if self._lighting_service is None:
            return
        try:
            self._lighting_service.controller.flash(
                190, 0, 255,
                duration_ms=max(120, min(3000, int(duration * 1000)))
            )
        except Exception as exc:
            print(f"[lighting] piano tiles hit failed: {exc}")

    @Slot()
    def _on_restart(self):
        self._start_game()

    @Slot()
    def _on_end(self):
        self.close()

    @Slot(bool)
    def _on_pause_toggled(self, paused):
        self._is_paused = paused
        self._camera_widget.set_paused(paused)
        if paused:
            self._game.pause()
            for note in list(self._active_held_notes.values()):
                self._audio_queue.put(("off", note))
            self._active_held_notes.clear()
        else:
            self._game.unpause()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Space:
            if self._game.state in (TilesGame.STATE_IDLE, TilesGame.STATE_GAME_OVER):
                self._start_game()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._frame_timer.stop()
        for note in list(self._active_held_notes.values()):
            try:
                if self._fs:
                    self._fs.noteoff(0, note)
            except Exception:
                pass
        self._hands_thread.close()
        self._cam_thread.stop()
        self._cap.release()
        self._audio_queue.put(None)
        event.accept()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def start_piano_tiles_ui(
    chosen_instrument=None,
    resolution_profile=None,
    show_trackers=True,
    hand_model_complexity=1,
    difficulty="easy",
    song="Twinkle Twinkle",
    nickname="",
    lighting_service: IdleLightingService | None = None,
):
    """Launch the PySide6 Piano Tiles game. Drop-in for the old pygame version."""
    print(f">>> INICIANDO PIANO TILES UI [{difficulty.upper()}] - {song}")
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_font()

    win = PianoTilesWindow(
        instrument_name=chosen_instrument or "Piano",
        resolution_profile=resolution_profile,
        show_trackers=show_trackers,
        hand_model_complexity=hand_model_complexity,
        difficulty=difficulty,
        song=song,
        nickname=nickname,
        lighting_service=lighting_service,
    )
    win.showFullScreen()
    print(">>> MODO PRONTO")
    app.exec()
    print(">>> Piano Tiles UI encerrado.")


# Backward-compatible alias
start_piano_tiles = start_piano_tiles_ui


if __name__ == "__main__":
    start_piano_tiles_ui()
