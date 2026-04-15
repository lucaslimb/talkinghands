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
    QLabel, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
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
from src.engines.recorder import MidiRecorder
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
GAME_KEY_ACTIVE     = "#746292"   # same as accent
GAME_KEY_WHITE      = "#1C1830"   # dark "white" key surface
GAME_KEY_BLACK      = "#0C0A18"   # very dark black key surface
GAME_DIFF_EASY      = "#4E7C5E"   # muted forest green
GAME_DIFF_MEDIUM    = "#7A6830"   # muted gold
GAME_DIFF_HARD      = "#8A3A50"   # deep rose

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
        self._show_trackers = True
        self._detecting = False

        self._game = None
        self._is_paused = False

        self._last_result    = None
        self._last_result_ts = 0.0

        self._state_overlay = None
        self._final_score   = 0

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

    def set_show_trackers(self, v):
        self._show_trackers = v

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
        painter.fillRect(0, 0, w, h, QColor(15, 8, 28, 25))

        pen = QPen(QColor(0, 0, 0, 12), 1)
        painter.setPen(pen)
        for y_line in range(0, h, 8):
            painter.drawLine(0, y_line, w, y_line)

        if self._game is not None and not self._is_paused:
            self._draw_tiles(painter, w, h)

        self._draw_piano_keys(painter, w, h)

        if self._show_trackers and self._results and self._results.multi_hand_landmarks:
            self._draw_hand_connections(painter, w, h)

        self._draw_detecting_indicator(painter)
        self._draw_precision_message(painter, w, h)

        if self._is_paused:
            self._draw_pause_overlay(painter, w, h)
        elif self._state_overlay == "ready":
            self._draw_ready_overlay(painter, w, h)
        elif self._state_overlay in ("gameover_win", "gameover_lose"):
            self._draw_gameover_overlay(painter, w, h)

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

    def _draw_detecting_indicator(self, painter):
        if not self._detecting:
            return
        label = "DETECTANDO"
        f = QFont(FONT_FAMILY, FONT_SIZE_SM)
        f.setBold(True)
        painter.setFont(f)
        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(label)

        dot_r, pad_l, dot_gap, pad_r = 10, 10, 8, 12
        card_w = pad_l + dot_r + dot_gap + text_w + pad_r
        card_h = 28
        card_x = self.width() - card_w - 12

        bg_c = QColor(GAME_BG_PANEL)
        bg_c.setAlpha(210)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_c))
        painter.drawRoundedRect(card_x, 12, card_w, card_h, 14, 14)

        painter.setBrush(QBrush(QColor(GAME_ACCENT)))
        painter.drawEllipse(card_x + pad_l, 12 + (card_h - dot_r) // 2, dot_r, dot_r)

        painter.setPen(QColor(GAME_ACCENT))
        painter.setFont(f)
        painter.drawText(card_x + pad_l + dot_r + dot_gap,
                         12 + card_h // 2 + fm.ascent() // 2 - 1, label)

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

    def _draw_ready_overlay(self, painter, w, h):
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 140))

        f = QFont(FONT_FAMILY, 32)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(GAME_ACCENT))
        text = "PIANO TILES"
        fm   = painter.fontMetrics()
        painter.drawText(w // 2 - fm.horizontalAdvance(text) // 2, h // 2 - 20, text)

        f2 = QFont(FONT_FAMILY, FONT_SIZE_MD)
        painter.setFont(f2)
        painter.setPen(QColor(GAME_TEXT_SECONDARY))
        sub = "Iniciando..."
        fm2 = painter.fontMetrics()
        painter.drawText(w // 2 - fm2.horizontalAdvance(sub) // 2, h // 2 + 28, sub)

    def _draw_gameover_overlay(self, painter, w, h):
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 150))

        won   = (self._state_overlay == "gameover_win")
        title = "VOCE VENCEU!" if won else "FIM DE JOGO"
        tcol  = QColor(180, 155, 220) if won else QColor(196, 78, 106)

        f = QFont(FONT_FAMILY, 32)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(tcol)
        fm = painter.fontMetrics()
        painter.drawText(w // 2 - fm.horizontalAdvance(title) // 2, h // 2 - 24, title)

        f2 = QFont(FONT_FAMILY, FONT_SIZE_LG)
        painter.setFont(f2)
        painter.setPen(QColor(GAME_TEXT_PRIMARY))
        sc = f"Score: {self._final_score}"
        fm2 = painter.fontMetrics()
        painter.drawText(w // 2 - fm2.horizontalAdvance(sc) // 2, h // 2 + 22, sc)

        f3 = QFont(FONT_FAMILY, FONT_SIZE_SM)
        painter.setFont(f3)
        painter.setPen(QColor(GAME_TEXT_SECONDARY))
        hint = "Use o painel para reiniciar"
        fm3 = painter.fontMetrics()
        painter.drawText(w // 2 - fm3.horizontalAdvance(hint) // 2, h // 2 + 56, hint)


# ---------------------------------------------------------------------------
# Game Control Panel  (left side)
# ---------------------------------------------------------------------------

class GamePanel(QWidget):
    """Left panel with score, combo, lives, song selector, difficulty, pause."""

    restart_clicked    = Signal()
    end_clicked        = Signal()
    difficulty_changed = Signal(str)
    song_prev          = Signal()
    song_next          = Signal()
    pause_toggled      = Signal(bool)
    tracker_toggled    = Signal(bool)

    def __init__(self, song_names, parent=None):
        super().__init__(parent)
        self.setObjectName("gamePanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._song_names         = song_names
        self._current_difficulty = "easy"
        self._is_paused          = False
        self._trackers_on        = True

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        hdr = QLabel("Piano Tiles")
        hdr.setObjectName("gameHeaderLabel")
        header_row.addWidget(hdr)
        header_row.addStretch()

        self._end_btn = QPushButton("Encerrar")
        self._end_btn.setObjectName("gameEndBtn")
        self._end_btn.clicked.connect(self.end_clicked.emit)
        header_row.addWidget(self._end_btn)
        layout.addLayout(header_row)

        self._score_label = QLabel("0")
        self._score_label.setObjectName("gameScoreLabel")
        layout.addWidget(self._score_label)

        score_sub = QLabel("pontos")
        score_sub.setObjectName("gameScoreSub")
        layout.addWidget(score_sub)

        layout.addSpacing(2)

        cr = QHBoxLayout()
        self._combo_label = QLabel("Combo: 0")
        self._combo_label.setObjectName("gameComboLabel")
        cr.addWidget(self._combo_label)
        cr.addStretch()
        self._best_label = QLabel("Melhor: 0")
        self._best_label.setObjectName("gameBestLabel")
        cr.addWidget(self._best_label)
        layout.addLayout(cr)

        layout.addSpacing(4)

        self._add_section_title(layout, "Vidas")
        self._lives_label = QLabel("v v v v v")
        self._lives_label.setObjectName("gameLivesLabel")
        layout.addWidget(self._lives_label)

        layout.addSpacing(6)

        self._progress_label = QLabel("Progresso: 0%")
        self._progress_label.setObjectName("gameProgressLabel")
        layout.addWidget(self._progress_label)

        layout.addSpacing(6)

        self._add_section_title(layout, "Musica")
        song_row = QHBoxLayout()
        song_row.setSpacing(6)

        prev_btn = QPushButton("<")
        prev_btn.setObjectName("gameNavBtn")
        prev_btn.setFixedWidth(40)
        prev_btn.clicked.connect(self.song_prev.emit)
        song_row.addWidget(prev_btn)

        self._song_label = QLabel(self._song_names[0] if self._song_names else "-")
        self._song_label.setObjectName("gameSongLabel")
        self._song_label.setAlignment(Qt.AlignCenter)
        self._song_label.setWordWrap(True)
        song_row.addWidget(self._song_label, 1)

        next_btn = QPushButton(">")
        next_btn.setObjectName("gameNavBtn")
        next_btn.setFixedWidth(40)
        next_btn.clicked.connect(self.song_next.emit)
        song_row.addWidget(next_btn)
        layout.addLayout(song_row)

        layout.addSpacing(6)

        self._add_section_title(layout, "Dificuldade")
        diff_row = QHBoxLayout()
        diff_row.setSpacing(6)
        self._diff_btns = {}
        for diff, lbl in _DIFF_LABELS.items():
            btn = QPushButton(lbl)
            btn.setObjectName(f"gameDiffBtn_{diff}")
            btn.setCheckable(True)
            btn.setChecked(diff == self._current_difficulty)
            btn.clicked.connect(lambda _checked, d=diff: self._on_difficulty(d))
            diff_row.addWidget(btn)
            self._diff_btns[diff] = btn
        layout.addLayout(diff_row)

        layout.addSpacing(8)

        self._pause_btn = QPushButton("|| Pausar")
        self._pause_btn.setObjectName("gamePauseBtn")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setFixedHeight(BTN_HEIGHT)
        self._pause_btn.clicked.connect(self._on_pause_toggle)

        if not TilesGame.STATE_GAME_OVER:
            layout.addWidget(self._pause_btn)

        self._restart_btn = QPushButton("Reiniciar")
        self._restart_btn.setObjectName("gameRestartBtn")
        self._restart_btn.setFixedHeight(BTN_HEIGHT)
        self._restart_btn.clicked.connect(self.restart_clicked.emit)
        layout.addWidget(self._restart_btn)

        layout.addSpacing(8)

        self._add_section_title(layout, "Configuracões")

        self._tracker_btn = QPushButton("Trackers: ON")
        self._tracker_btn.setObjectName("gameTrackerBtn")
        self._tracker_btn.setCheckable(True)
        self._tracker_btn.setChecked(True)
        self._tracker_btn.setFixedHeight(BTN_HEIGHT)
        self._tracker_btn.clicked.connect(self._on_tracker_toggle)
        layout.addWidget(self._tracker_btn)

        self._fps_label = QLabel("FPS: --")
        self._fps_label.setObjectName("gameFpsLabel")
        layout.addWidget(self._fps_label)

        layout.addStretch()

    def _add_section_title(self, layout, text):
        lbl = QLabel(text)
        lbl.setObjectName("gameSectionTitle")
        layout.addWidget(lbl)

    def _on_difficulty(self, diff):
        self._current_difficulty = diff
        for d, btn in self._diff_btns.items():
            btn.setChecked(d == diff)
        self.difficulty_changed.emit(diff)

    def _on_pause_toggle(self):
        self._is_paused = not self._is_paused
        self._pause_btn.setText("Retomar" if self._is_paused else "|| Pausar")
        self.pause_toggled.emit(self._is_paused)

    def _on_tracker_toggle(self):
        self._trackers_on = self._tracker_btn.isChecked()
        self._tracker_btn.setText(f"Trackers: {'ON' if self._trackers_on else 'OFF'}")
        self.tracker_toggled.emit(self._trackers_on)

    def update_game_state(self, game):
        self._score_label.setText(str(game.score))

        combo_text = f"Combo: {game.combo}"
        self._combo_label.setText(combo_text)

        if game.best_score > 0:
            self._best_label.setText(f"Melhor: {game.best_score}")

        lives     = game.lives_remaining
        max_lives = game.MAX_MISTAKES
        hearts_on  = "v " * lives
        hearts_off = "o " * (max_lives - lives)
        self._lives_label.setText((hearts_on + hearts_off).strip())

        pct = int(game.progress * 100)
        self._progress_label.setText(f"Progresso: {pct}%")

    def update_song(self, idx):
        if 0 <= idx < len(self._song_names):
            self._song_label.setText(self._song_names[idx])

    def update_fps(self, fps):
        self._fps_label.setText(f"FPS: {fps:.0f}")

    def reset_pause(self):
        self._is_paused = False
        self._pause_btn.setChecked(False)
        self._pause_btn.setText("|| Pausar")

    def get_difficulty(self):
        return self._current_difficulty


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

QLabel#gameHeaderLabel {{
    font-size: {FONT_SIZE_LG}px;
    font-weight: bold;
    color: {GAME_TEXT_PRIMARY};
}}

QLabel#gameScoreLabel {{
    font-size: {FONT_SIZE_TIMER}px;
    font-weight: bold;
    color: {GAME_ACCENT};
}}

QLabel#gameScoreSub {{
    font-size: {FONT_SIZE_SM}px;
    color: {GAME_TEXT_SECONDARY};
}}

QLabel#gameComboLabel {{
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    color: {GAME_TEXT_PRIMARY};
}}

QLabel#gameBestLabel {{
    font-size: {FONT_SIZE_SM}px;
    color: {GAME_TEXT_SECONDARY};
}}

QLabel#gameLivesLabel {{
    font-size: {FONT_SIZE_LG}px;
    color: {GAME_ACCENT};
    letter-spacing: 2px;
}}

QLabel#gameProgressLabel {{
    font-size: {FONT_SIZE_SM}px;
    color: {GAME_TEXT_SECONDARY};
}}

QLabel#gameSectionTitle {{
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    color: {GAME_TEXT_SECONDARY};
    letter-spacing: 1px;
}}

QLabel#gameSongLabel {{
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    color: {GAME_TEXT_PRIMARY};
}}

QLabel#gameFpsLabel {{
    font-size: {FONT_SIZE_SM}px;
    color: {GAME_TEXT_SECONDARY};
}}

QPushButton#gameEndBtn {{
    background-color: transparent;
    color: {GAME_ACCENT_RED};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 6px 16px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#gameEndBtn:hover {{
    background-color: {GAME_ACCENT_RED};
    color: white;
}}

QPushButton#gameNavBtn {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_TEXT_PRIMARY};
    border: 1px solid {GAME_BORDER_LIGHT};
    border-radius: {BORDER_RAD}px;
    font-size: {FONT_SIZE_MD}px;
    font-family: {FONT_FAMILY};
    height: {BTN_HEIGHT}px;
    padding: 4px;
}}
QPushButton#gameNavBtn:hover {{
    background-color: {GAME_ACCENT};
    color: {GAME_TEXT_LIGHT};
    border-color: {GAME_ACCENT};
}}

QPushButton#gameDiffBtn_easy, QPushButton#gameDiffBtn_medium, QPushButton#gameDiffBtn_hard {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_TEXT_PRIMARY};
    border: 1px solid {GAME_BORDER_LIGHT};
    border-radius: {BORDER_RAD}px;
    padding: 8px 4px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#gameDiffBtn_easy:checked {{
    background-color: {GAME_DIFF_EASY};
    color: {GAME_TEXT_LIGHT};
    border-color: {GAME_DIFF_EASY};
}}
QPushButton#gameDiffBtn_medium:checked {{
    background-color: {GAME_DIFF_MEDIUM};
    color: {GAME_TEXT_LIGHT};
    border-color: {GAME_DIFF_MEDIUM};
}}
QPushButton#gameDiffBtn_hard:checked {{
    background-color: {GAME_DIFF_HARD};
    color: {GAME_TEXT_LIGHT};
    border-color: {GAME_DIFF_HARD};
}}
QPushButton#gameDiffBtn_easy:hover,
QPushButton#gameDiffBtn_medium:hover,
QPushButton#gameDiffBtn_hard:hover {{
    border-color: {GAME_ACCENT};
}}

QPushButton#gamePauseBtn {{
    background-color: {GAME_ACCENT};
    color: {GAME_TEXT_LIGHT};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 12px;
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    font-family: {FONT_FAMILY};
}}
QPushButton#gamePauseBtn:checked {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_ACCENT};
    border: 1px solid {GAME_ACCENT};
}}

QPushButton#gameRestartBtn {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_TEXT_PRIMARY};
    border: 1px solid {GAME_BORDER_LIGHT};
    border-radius: {BORDER_RAD}px;
    padding: 12px;
    font-size: {FONT_SIZE_MD}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#gameRestartBtn:hover {{
    border-color: {GAME_ACCENT};
    color: {GAME_ACCENT};
}}

QPushButton#gameTrackerBtn {{
    background-color: {GAME_BG_PANEL_ALT};
    color: {GAME_TEXT_PRIMARY};
    border: 1px solid {GAME_BORDER_LIGHT};
    border-radius: {BORDER_RAD}px;
    padding: 8px 16px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#gameTrackerBtn:checked {{
    background-color: {GAME_ACCENT};
    color: {GAME_TEXT_LIGHT};
    border-color: {GAME_ACCENT};
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
    ):
        super().__init__()
        self.setWindowTitle("Talking Hands - Piano Tiles")
        self.setStyleSheet(_build_game_qss())

        self._instrument_name = instrument_name

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
        self._is_paused          = False
        self._table_y            = DEFAULT_TABLE_Y

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

        self._camera_widget.set_state_overlay("ready")
        QTimer.singleShot(900, self._start_game)

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
        self._panel.difficulty_changed.connect(self._on_difficulty_changed)
        self._panel.song_prev.connect(lambda: self._on_song_changed(-1))
        self._panel.song_next.connect(lambda: self._on_song_changed(+1))
        self._panel.pause_toggled.connect(self._on_pause_toggled)
        self._panel.tracker_toggled.connect(self._on_tracker_toggled)

        self._camera_widget = GameCameraOverlayWidget()
        self._camera_widget.set_piano_keys(self._piano_keys)
        self._camera_widget.set_table_y(self._table_y)
        self._camera_widget.set_show_trackers(show_trackers)
        self._camera_widget.set_game(self._game)

        main_layout.addWidget(self._panel,         1)
        main_layout.addWidget(self._camera_widget, 2)

        self._panel.update_song(self._current_song_idx)

    def _start_game(self):
        self._finger_prev_y.clear()
        self._active_held_notes.clear()
        self._pending_note_offs.clear()
        self._is_paused = False
        self._panel.reset_pause()
        self._camera_widget.set_paused(False)
        self._camera_widget.set_state_overlay(None)

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

            if self._game.pending_play_note is not None:
                demo = self._game.pending_play_note
                self._audio_queue.put(("on", demo))
                self._pending_note_offs.append((demo, now + 0.28))

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
                won   = self._game.mistakes < self._game.MAX_MISTAKES
                state = "gameover_win" if won else "gameover_lose"
                self._camera_widget.set_state_overlay(state, self._game.score)

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

    @Slot()
    def _on_restart(self):
        self._start_game()

    @Slot()
    def _on_end(self):
        self.close()

    @Slot(str)
    def _on_difficulty_changed(self, diff):
        self._current_difficulty = diff
        if self._game.state == TilesGame.STATE_PLAYING:
            self._start_game()

    def _on_song_changed(self, delta):
        self._current_song_idx = (self._current_song_idx + delta) % len(SONG_NAMES)
        self._panel.update_song(self._current_song_idx)
        if self._game.state == TilesGame.STATE_PLAYING:
            self._start_game()

    @Slot(bool)
    def _on_pause_toggled(self, paused):
        self._is_paused = paused
        self._camera_widget.set_paused(paused)
        if paused:
            for note in list(self._active_held_notes.values()):
                self._audio_queue.put(("off", note))
            self._active_held_notes.clear()

    @Slot(bool)
    def _on_tracker_toggled(self, enabled):
        self._camera_widget.set_show_trackers(enabled)

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
    )
    win.showFullScreen()
    app.exec()
    print(">>> Piano Tiles UI encerrado.")


# Backward-compatible alias
start_piano_tiles = start_piano_tiles_ui


if __name__ == "__main__":
    start_piano_tiles_ui()
