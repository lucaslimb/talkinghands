"""
Talking Hands — Piano UI (PySide6)
Fullscreen split layout: camera + instrument overlays on the left,
control panel on the right.
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

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSlider, QSizePolicy,
    QSplitter, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPen, QBrush

FILE_PATH = Path(__file__).resolve()
_PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# --- FluidSynth path setup BEFORE any module that imports fluidsynth ---
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

    # Patch pyfluidsynth's bad hardcoded path
    _orig = getattr(os, "add_dll_directory", None)
    if _orig:
        def _safe_add(p):
            if p.lower() == r"c:\tools\fluidsynth\bin":
                return None
            return _orig(p)
        os.add_dll_directory = _safe_add

_setup_fluidsynth_path()

from src.config import settings
from src.engines.recorder import MidiRecorder
from src.instruments.common import (
    init_fluidsynth, load_all_soundfonts, select_instrument,
    setup_video_capture, fit_resolution_to_screen,
    CameraThread, prepare_mediapipe_frame,
    MediaPipeHandsThread,
)

from src.instruments.ui_shared import (
    COL_BG_DARK, COL_BG_PANEL, COL_BG_PANEL_ALT, COL_ACCENT_GREEN,
    COL_ACCENT_RED, COL_TEXT_PRIMARY, COL_TEXT_SECONDARY, COL_TEXT_LIGHT,
    COL_BTN_RECORD, COL_BTN_PAUSE, COL_BORDER_LIGHT, COL_OCTAVE_ACTIVE,
    COL_SLIDER_TRACK, COL_SLIDER_HANDLE, COL_DETECTING_BG, COL_DETECTING_DOT,
    COL_KEY_ACTIVE, COL_NOTE_PILL_BG, COL_KEY_WHITE, COL_KEY_BLACK,
    FONT_FAMILY, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL,
    FONT_SIZE_TIMER, PANEL_MIN_W, PANEL_MAX_W, BTN_HEIGHT, BORDER_RAD,
    load_custom_font, build_global_qss, PROJECT_ROOT,
)

import fluidsynth as _fluidsynth

# ---------------------------------------------------------------------------
# Keyboard constants (reused from keyboard.py)
# ---------------------------------------------------------------------------
SUSTAIN_DECAY_DEFAULT = float(getattr(settings, "KEYBOARD_SUSTAIN_DECAY", 0.8))
LIFT_THRESHOLD_DEFAULT = float(getattr(settings, "KEYBOARD_LIFT_THRESHOLD", 0.02))
TOUCH_TOLERANCE_DEFAULT = float(getattr(settings, "KEYBOARD_TOUCH_TOLERANCE", 0.005))
DEFAULT_NUM_KEYS = int(getattr(settings, "KEYBOARD_DEFAULT_NUM_KEYS", 30))
MIN_NUM_KEYS = 12
MAX_NUM_KEYS = 72
# Rough target: ~40px per white key → derive total chromatic keys from white key count
TARGET_WHITE_KEY_WIDTH = 50  # pixels — larger keys by default
DEFAULT_TABLE_Y = float(getattr(settings, "KEYBOARD_DEFAULT_TABLE_Y", 0.80))
BLACK_KEY_HEIGHT_RATIO = 0.62
BLACK_KEY_WIDTH_RATIO = 0.44
ACTIVE_FINGERS = [4, 8, 12, 16, 20]
RELEASE_THRESHOLD = float(getattr(settings, "KEYBOARD_RELEASE_THRESHOLD", 0.015))
MIN_NOTE_DURATION = float(getattr(settings, "KEYBOARD_MIN_NOTE_DURATION", 0.1))
ARMED_TIMEOUT = float(getattr(settings, "KEYBOARD_ARMED_TIMEOUT", 2.5))
MAX_MISSING_TIME = float(getattr(settings, "KEYBOARD_MAX_MISSING_TIME", 0.1))

SCALE_INTERVALS = list(range(12))
BASE_NOTE = 48
BLACK_KEY_NOTE_CLASSES = {1, 3, 6, 8, 10}
WHITE_KEY_NOTE_CLASSES = {0, 2, 4, 5, 7, 9, 11}
WHITE_CLASS_TO_OFFSET = {0: 0.0, 2: 1.0, 4: 2.0, 5: 3.0, 7: 4.0, 9: 5.0, 11: 6.0}
BLACK_CLASS_TO_CENTER_OFFSET = {1: 0.5, 3: 1.5, 6: 3.5, 8: 4.5, 10: 5.5}

NOTE_LABELS_PT = {
    0: "Dó", 1: "Dó#", 2: "Ré", 3: "Ré#", 4: "Mi", 5: "Fá",
    6: "Fá#", 7: "Sol", 8: "Sol#", 9: "Lá", 10: "Lá#", 11: "Si",
}

KEYBOARD_SWIPE_INSTRUMENTS = [
    name for name, (sf_key, bank, preset) in settings.INSTRUMENTS.items()
    if sf_key == "master" and name not in ("Arms", "Maestro", "Face")
]

# ---------------------------------------------------------------------------
# Piano model helpers (from keyboard.py, minimized)
# ---------------------------------------------------------------------------

def is_black_key(midi_note):
    return (int(midi_note) % 12) in BLACK_KEY_NOTE_CLASSES


def build_note_pool():
    pool = []
    octave = 0
    while True:
        has = False
        for off in SCALE_INTERVALS:
            n = BASE_NOTE + octave * 12 + off
            if n > 127:
                continue
            pool.append(n)
            has = True
        if not has:
            break
        octave += 1
    return sorted(set(pool))


NOTE_POOL = build_note_pool()


def build_piano_keys(num_keys):
    selected = NOTE_POOL[:max(1, min(len(NOTE_POOL), num_keys))]
    keys = []
    for note_val in selected:
        keys.append({
            "note": note_val,
            "last_hit": 0.0,
            "is_active": False,
            "off_timer": 0.0,
            "is_black": is_black_key(note_val),
            "x_start_norm": 0.0,
            "x_end_norm": 1.0,
        })
    _apply_piano_geometry(keys)
    return keys


def _apply_piano_geometry(keys):
    if not keys:
        return
    whites = [k for k in sorted(keys, key=lambda k: k["note"]) if not k["is_black"]]
    if not whites:
        w = 1.0 / max(1, len(keys))
        for i, k in enumerate(keys):
            k["x_start_norm"] = i * w
            k["x_end_norm"] = min(1.0, (i + 1) * w)
        return
    ww = 1.0 / max(1, len(whites))
    for i, k in enumerate(whites):
        k["x_start_norm"] = i * ww
        k["x_end_norm"] = min(1.0, (i + 1) * ww)
    wbn = {int(k["note"]): k for k in whites}
    wn = sorted(wbn.keys())
    for k in keys:
        n = int(k["note"])
        if not k["is_black"]:
            continue
        prev = [x for x in wn if x < n]
        nxt = [x for x in wn if x > n]
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
        k["x_end_norm"] = min(1.0, center + bw * 0.5)


def get_key_index_from_x(keys, x_norm):
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


def calc_num_keys_for_width(pixel_width):
    """Derive a good chromatic key count from available pixel width."""
    white_keys = max(7, pixel_width // TARGET_WHITE_KEY_WIDTH)
    # ~7 white keys per 12 chromatic keys
    chromatic = int(white_keys * 12 / 7)
    return max(MIN_NUM_KEYS, min(MAX_NUM_KEYS, chromatic))


# ---------------------------------------------------------------------------
# Camera + Overlay Widget
# ---------------------------------------------------------------------------

class CameraOverlayWidget(QWidget):
    """Renders camera feed with piano keys, hand trackers and note animations."""

    note_played = Signal(int)  # emitted with MIDI note number

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._frame_rgb = None
        self._results = None
        self._piano_keys = []
        self._table_y = DEFAULT_TABLE_Y
        self._show_trackers = False
        self._show_scifi = True
        self._recent_notes = []  # list of (note, timestamp)
        self._detecting = False

    def set_frame(self, frame_rgb: np.ndarray):
        self._frame_rgb = frame_rgb

    def set_results(self, results):
        self._results = results
        self._detecting = results is not None and results.multi_hand_landmarks is not None

    def set_piano_keys(self, keys):
        self._piano_keys = keys

    def set_table_y(self, y):
        self._table_y = y

    def set_show_trackers(self, v):
        self._show_trackers = v

    def set_show_scifi(self, v):
        self._show_scifi = v

    def add_recent_note(self, midi_note):
        self._recent_notes.append((midi_note, time.time()))
        if len(self._recent_notes) > 8:
            self._recent_notes.pop(0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor(COL_BG_DARK))

        # Draw camera frame (already cropped to widget aspect ratio)
        if self._frame_rgb is not None:
            frame = np.ascontiguousarray(self._frame_rgb)
            fh, fw = frame.shape[:2]
            qimg = QImage(frame.data, fw, fh, fw * 3, QImage.Format_RGB888)
            scaled_img = qimg.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            painter.drawImage(0, 0, scaled_img)
        ox, oy, sw, sh = 0, 0, w, h

        # Soft green sci-fi tint + scanlines
        if self._show_scifi:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.fillRect(0, 0, w, h, QColor(0, 255, 80, 10))
            scanline_pen = QPen(QColor(0, 0, 0, 20), 1)
            painter.setPen(scanline_pen)
            for y_line in range(0, h, 7):
                painter.drawLine(0, y_line, w, y_line)

        # Draw piano keys overlay
        self._draw_piano_keys(painter, ox, oy, sw, sh)

        # Draw hand landmarks (connections) only when trackers enabled
        if self._show_trackers and self._results and self._results.multi_hand_landmarks:
            self._draw_hand_connections(painter, ox, oy, sw, sh)

        # Detecting indicator
        self._draw_detecting_indicator(painter)

        # Recent notes pills (bottom left, above piano)
        self._draw_recent_notes(painter, ox, oy, sw, sh)

        painter.end()

    def _draw_piano_keys(self, painter, ox, oy, sw, sh):
        if not self._piano_keys:
            return
        table_px = oy + int(self._table_y * sh)
        total_h = (oy + sh) - table_px
        if total_h <= 0:
            return
        black_h = int(total_h * BLACK_KEY_HEIGHT_RATIO)
        now = time.time()

        # White keys
        for k in self._piano_keys:
            if k["is_black"]:
                continue
            x1 = ox + int(k["x_start_norm"] * sw)
            x2 = ox + int(k["x_end_norm"] * sw)
            kw = max(1, x2 - x1)

            active = k["is_active"] or (now - k["last_hit"]) < 0.15
            bg = QColor(COL_KEY_ACTIVE) if active else QColor(255, 255, 255)
            bg.setAlpha(180 if active else 20)
            painter.fillRect(x1, table_px, kw, total_h, bg)

            painter.setPen(QPen(QColor(255, 255, 255, 45), 1))
            painter.drawLine(x1, table_px, x1, oy + sh)

        # Black keys
        for k in self._piano_keys:
            if not k["is_black"]:
                continue
            x1 = ox + int(k["x_start_norm"] * sw)
            x2 = ox + int(k["x_end_norm"] * sw)
            kw = max(1, x2 - x1)

            active = k["is_active"] or (now - k["last_hit"]) < 0.15
            bg = QColor(COL_KEY_ACTIVE) if active else QColor(COL_KEY_BLACK)
            bg.setAlpha(200 if active else 120)
            painter.fillRect(x1, table_px, kw, black_h, bg)

            painter.setPen(QPen(QColor(70, 70, 70), 1))
            painter.drawRect(x1, table_px, kw, black_h)

        # Table line
        painter.setPen(QPen(QColor(0, 0, 0, 72), 2))
        painter.drawLine(ox, table_px, ox + sw, table_px)

    def _draw_hand_connections(self, painter, ox, oy, sw, sh):
        if not self._results or not self._results.multi_hand_landmarks:
            return
        connections = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (0, 9), (9, 10), (10, 11), (11, 12),
            (0, 13), (13, 14), (14, 15), (15, 16),
            (0, 17), (17, 18), (18, 19), (19, 20),
            (5, 9), (9, 13), (13, 17),
        ]
        for lm in self._results.multi_hand_landmarks:
            pen = QPen(QColor(COL_ACCENT_GREEN), 2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            for a, b in connections:
                ax = ox + int(lm.landmark[a].x * sw)
                ay = oy + int(lm.landmark[a].y * sh)
                bx = ox + int(lm.landmark[b].x * sw)
                by = oy + int(lm.landmark[b].y * sh)
                painter.drawLine(ax, ay, bx, by)

            painter.setBrush(QBrush(QColor(COL_ACCENT_GREEN)))
            painter.setPen(Qt.NoPen)
            for pt in lm.landmark:
                px = ox + int(pt.x * sw)
                py = oy + int(pt.y * sh)
                painter.drawEllipse(px - 3, py - 3, 6, 6)

    def _draw_hand_trackers(self, painter, ox, oy, sw, sh):
        pass  # trackers drawn inline via connections

    def _draw_detecting_indicator(self, painter):
        if self._detecting:
            label = "DETECTANDO"
            f = QFont(FONT_FAMILY, FONT_SIZE_SM)
            f.setBold(True)
            painter.setFont(f)
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(label)

            dot_r = 10
            pad_l = 10  # left padding
            dot_gap = 8  # gap between dot and text
            pad_r = 12  # right padding
            card_w = pad_l + dot_r + dot_gap + text_w + pad_r
            card_h = 28

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(COL_DETECTING_BG)))
            painter.drawRoundedRect(12, 12, card_w, card_h, 14, 14)

            painter.setBrush(QBrush(QColor(COL_DETECTING_DOT)))
            painter.drawEllipse(12 + pad_l, 12 + (card_h - dot_r) // 2, dot_r, dot_r)

            painter.setPen(QColor(COL_ACCENT_GREEN))
            painter.setFont(f)
            text_x = 12 + pad_l + dot_r + dot_gap
            text_y = 12 + card_h // 2 + fm.ascent() // 2 - 1
            painter.drawText(text_x, text_y, label)

    def _draw_recent_notes(self, painter, ox, oy, sw, sh):
        if not self._recent_notes:
            return
        now = time.time()
        visible = [(n, t) for n, t in self._recent_notes if now - t < 5.0]
        if not visible:
            return

        table_px = oy + int(self._table_y * sh)
        px = ox + 10
        py = table_px - 30

        f = QFont(FONT_FAMILY, FONT_SIZE_SM)
        f.setBold(True)
        painter.setFont(f)

        for note, ts in reversed(visible[-6:]):
            label = NOTE_LABELS_PT.get(note % 12, "?")
            age = now - ts
            is_recent = age < 0.5

            if is_recent:
                pill_col = QColor(COL_NOTE_PILL_BG)
                pill_col.setAlpha(180)
                painter.setBrush(QBrush(pill_col))
                painter.setPen(Qt.NoPen)
            else:
                pill_col = QColor(COL_BG_PANEL_ALT)
                pill_col.setAlpha(150)
                painter.setBrush(QBrush(pill_col))
                painter.setPen(Qt.NoPen)

            tw = max(36, len(label) * 10 + 20)
            painter.drawRoundedRect(px, py, tw, 24, 12, 12)

            painter.setPen(QColor(COL_TEXT_LIGHT) if is_recent else QColor(COL_TEXT_PRIMARY))
            painter.drawText(px + 10, py + 17, label)
            px += tw + 6


# ---------------------------------------------------------------------------
# Control Panel Widget
# ---------------------------------------------------------------------------

class ControlPanel(QWidget):
    """Right-side panel with session info, parameter controls, recording buttons."""

    sustain_changed = Signal(float)
    lift_changed = Signal(float)
    tolerance_changed = Signal(float)
    preset_changed = Signal(str)
    octave_changed = Signal(int)
    record_clicked = Signal()
    stop_clicked = Signal()
    playback_clicked = Signal()
    end_clicked = Signal()
    tracker_toggled = Signal(bool)
    scifi_toggled = Signal(bool)

    def __init__(self, instrument_name="Piano", parent=None):
        super().__init__(parent)
        self.setObjectName("controlPanel")
        self.setMinimumWidth(PANEL_MIN_W)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._instrument_name = instrument_name
        self._session_start = time.time()
        self._is_recording = False

        self._init_ui()

        # Timer to update session clock
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # Header row
        header_row = QHBoxLayout()
        hdr = QLabel(f"Prática · Piano — {self._instrument_name}")
        hdr.setObjectName("headerLabel")
        header_row.addWidget(hdr)
        header_row.addStretch()

        self._end_btn = QPushButton("Encerrar")
        self._end_btn.setObjectName("endBtn")
        self._end_btn.clicked.connect(self.end_clicked.emit)
        header_row.addWidget(self._end_btn)
        layout.addLayout(header_row)

        # Timer
        self._timer_label = QLabel("00:00")
        self._timer_label.setObjectName("timerLabel")
        layout.addWidget(self._timer_label)

        timer_sub = QLabel("em sessão")
        timer_sub.setObjectName("timerSub")
        layout.addWidget(timer_sub)

        layout.addSpacing(8)

        # Octave selector
        self._add_section_title(layout, "Oitava")
        octave_row = QHBoxLayout()
        self._octave_btns = []
        for oct_val in [2, 3, 4, 5, 6]:
            btn = QPushButton(f"C{oct_val}")
            btn.setObjectName("octaveBtn")
            btn.setCheckable(True)
            btn.setChecked(oct_val == 4)
            btn.clicked.connect(lambda checked, o=oct_val: self._on_octave(o))
            octave_row.addWidget(btn)
            self._octave_btns.append((oct_val, btn))
        layout.addLayout(octave_row)

        layout.addSpacing(8)

        # Parameters section 
        self._add_section_title(layout, "Timbres")

        # Preset selector (horizontal scrollable button list)
        preset_scroll = QScrollArea()
        preset_scroll.setObjectName("presetScroll")
        preset_scroll.setWidgetResizable(True)
        preset_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        preset_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        preset_scroll.setFixedHeight(44)
        preset_scroll.setStyleSheet("")  # no inline override — use global QSS

        preset_container = QWidget()
        preset_container.setObjectName("presetContainer")
        preset_hlayout = QHBoxLayout(preset_container)
        preset_hlayout.setContentsMargins(0, 0, 0, 0)
        preset_hlayout.setSpacing(6)

        self._preset_btns = []
        for name in KEYBOARD_SWIPE_INSTRUMENTS:
            btn = QPushButton(name)
            btn.setObjectName("presetBtn")
            btn.setCheckable(True)
            btn.setChecked(name == self._instrument_name)
            btn.clicked.connect(lambda checked, n=name: self._on_preset_btn(n))
            preset_hlayout.addWidget(btn)
            self._preset_btns.append((name, btn))
        preset_hlayout.addStretch()

        preset_scroll.setWidget(preset_container)
        # Enable horizontal scroll with mouse wheel
        preset_scroll.wheelEvent = lambda e: preset_scroll.horizontalScrollBar().setValue(
            preset_scroll.horizontalScrollBar().value() - e.angleDelta().y()
        )
        layout.addWidget(preset_scroll)

        layout.addSpacing(4)

        # Record / Playback buttons (toggle style matching other buttons)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._add_section_title(layout, "Gravação")

        self._record_btn = QPushButton("● Gravar")
        self._record_btn.setObjectName("octaveBtn")
        self._record_btn.setCheckable(True)
        self._record_btn.setChecked(False)
        self._record_btn.setFixedHeight(BTN_HEIGHT)
        self._record_btn.clicked.connect(self._on_record_toggle)
        btn_row.addWidget(self._record_btn, 1)

        self._playback_btn = QPushButton("▶ Playback")
        self._playback_btn.setObjectName("octaveBtn")
        self._playback_btn.setCheckable(True)
        self._playback_btn.setChecked(False)
        self._playback_btn.setFixedHeight(BTN_HEIGHT)
        self._playback_btn.clicked.connect(self._on_playback_toggle)
        btn_row.addWidget(self._playback_btn, 1)

        layout.addLayout(btn_row)

        layout.addSpacing(8)

        # Configurações section
        self._add_section_title(layout, "Configurações")

        # Tracker toggle button
        self._tracker_btn = QPushButton("Trackers: OFF")
        self._tracker_btn.setObjectName("trackerBtn")
        self._tracker_btn.setCheckable(True)
        self._tracker_btn.setChecked(False)
        self._tracker_btn.setFixedHeight(BTN_HEIGHT)
        self._tracker_btn.clicked.connect(self._on_tracker_toggle)
        layout.addWidget(self._tracker_btn)

        # Sci-fi filter toggle
        self._scifi_btn = QPushButton("Filtro Sci-Fi: ON")
        self._scifi_btn.setObjectName("trackerBtn")
        self._scifi_btn.setCheckable(True)
        self._scifi_btn.setChecked(True)
        self._scifi_btn.setFixedHeight(BTN_HEIGHT)
        self._scifi_btn.clicked.connect(self._on_scifi_toggle)
        layout.addWidget(self._scifi_btn)

        layout.addSpacing(4)

        # Sustain decay slider
        sustain_init = int(SUSTAIN_DECAY_DEFAULT * 100)
        self._sustain_slider, self._sustain_val_label = self._add_slider(
            layout, "Sustentação (s)", 5, 500, sustain_init,
            lambda v: self._on_slider("sustain", v)
        )
        self._sustain_val_label.setText(f"{SUSTAIN_DECAY_DEFAULT:.2f}s")

        # Lift threshold slider (1-100 normalized)
        lift_norm = int(LIFT_THRESHOLD_DEFAULT / 0.1 * 100)
        self._lift_slider, self._lift_val_label = self._add_slider(
            layout, "Sensibilidade", 1, 100, max(1, min(100, lift_norm)),
            lambda v: self._on_slider("lift", v)
        )

        # Touch tolerance slider (1-100 normalized)
        tol_norm = int(TOUCH_TOLERANCE_DEFAULT / 0.05 * 100)
        self._tolerance_slider, self._tolerance_val_label = self._add_slider(
            layout, "Tolerância", 1, 100, max(1, min(100, tol_norm)),
            lambda v: self._on_slider("tolerance", v)
        )

        # FPS label
        self._fps_label = QLabel("FPS: --")
        self._fps_label.setObjectName("fpsLabel")
        self._fps_label.setStyleSheet(f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_SECONDARY}; font-family: {FONT_FAMILY};")
        layout.addWidget(self._fps_label)

        layout.addStretch()

    def _add_section_title(self, layout, text):
        lbl = QLabel(text)
        lbl.setObjectName("sectionTitle")
        layout.addWidget(lbl)

    def _add_slider(self, layout, label_text, min_val, max_val, default, callback):
        row = QVBoxLayout()
        row.setSpacing(2)

        header = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_SECONDARY};")
        header.addWidget(lbl)

        val_label = QLabel(str(default))
        val_label.setStyleSheet(f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_PRIMARY}; font-weight: bold;")
        val_label.setAlignment(Qt.AlignRight)
        header.addWidget(val_label)

        row.addLayout(header)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        slider.valueChanged.connect(callback)
        row.addWidget(slider)

        layout.addLayout(row)
        return slider, val_label

    def _on_slider(self, name, value):
        if name == "sustain":
            real = value / 100.0
            self._sustain_val_label.setText(f"{real:.2f}s")
            self.sustain_changed.emit(real)
        elif name == "lift":
            real = value / 100.0 * 0.1  # 1-100 maps to 0.001-0.1
            self._lift_val_label.setText(str(value))
            self.lift_changed.emit(real)
        elif name == "tolerance":
            real = value / 100.0 * 0.05  # 1-100 maps to 0.0005-0.05
            self._tolerance_val_label.setText(str(value))
            self.tolerance_changed.emit(real)

    def _on_octave(self, octave):
        for o, btn in self._octave_btns:
            btn.setChecked(o == octave)
        self.octave_changed.emit(octave)

    def _on_preset_btn(self, name):
        for n, btn in self._preset_btns:
            btn.setChecked(n == name)
        self.preset_changed.emit(name)

    def _on_tracker_toggle(self):
        enabled = self._tracker_btn.isChecked()
        self._tracker_btn.setText(f"Trackers: {'ON' if enabled else 'OFF'}")
        self.tracker_toggled.emit(enabled)

    def _on_scifi_toggle(self):
        enabled = self._scifi_btn.isChecked()
        self._scifi_btn.setText(f"Filtro Sci-Fi: {'ON' if enabled else 'OFF'}")
        self.scifi_toggled.emit(enabled)

    def update_fps(self, fps_value):
        self._fps_label.setText(f"FPS: {fps_value:.0f}")

    def _on_record_toggle(self):
        if not self._is_recording:
            self._is_recording = True
            self._record_btn.setText("⏹ Parar")
            self._record_btn.setChecked(True)
            self.record_clicked.emit()
        else:
            self._is_recording = False
            self._record_btn.setText("● Gravar")
            self._record_btn.setChecked(False)
            self.stop_clicked.emit()

    def _on_playback_toggle(self):
        self._is_playing = not getattr(self, '_is_playing', False)
        if self._is_playing:
            self._playback_btn.setText("⏹ Parar")
            self._playback_btn.setChecked(True)
        else:
            self._playback_btn.setText("▶ Playback")
            self._playback_btn.setChecked(False)
        self.playback_clicked.emit()

    def _update_clock(self):
        elapsed = int(time.time() - self._session_start)
        mins = elapsed // 60
        secs = elapsed % 60
        self._timer_label.setText(f"{mins:02d}:{secs:02d}")

    def set_instrument_name(self, name):
        self._instrument_name = name
        # Update header
        for child in self.findChildren(QLabel):
            if child.objectName() == "headerLabel":
                child.setText(f"Prática · {name}")
                break
        for n, btn in self._preset_btns:
            btn.setChecked(n == name)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class PianoWindow(QMainWindow):
    """Fullscreen piano window with camera on left, controls on right."""

    def __init__(self, instrument_name="Piano", resolution_profile=None,
                 show_trackers=False, hand_model_complexity=1,
                 user_sustain=None, lift_threshold=None, touch_tolerance=None):
        super().__init__()
        self.setWindowTitle("Talking Hands — Piano")
        self.setStyleSheet(build_global_qss())

        self._instrument_name = instrument_name
        self._show_trackers = show_trackers

        # Audio
        self._audio_queue = queue.Queue()
        self._fs = None
        self._loaded_sfids = {}
        self._recorder = MidiRecorder()
        self._init_audio()

        # Piano keys
        self._sustain_decay = user_sustain or SUSTAIN_DECAY_DEFAULT
        self._lift_threshold = lift_threshold or LIFT_THRESHOLD_DEFAULT
        self._touch_tolerance = touch_tolerance or TOUCH_TOLERANCE_DEFAULT
        self._table_y = DEFAULT_TABLE_Y
        self._piano_keys = build_piano_keys(DEFAULT_NUM_KEYS)
        self._recent_notes = []

        # Hands state
        self._hands_state = {
            hand: {
                "finger_status": {fid: "IDLE" for fid in ACTIVE_FINGERS},
                "finger_timers": {fid: 0.0 for fid in ACTIVE_FINGERS},
                "active_notes": {fid: None for fid in ACTIVE_FINGERS},
                "last_seen": {fid: 0.0 for fid in ACTIVE_FINGERS},
            }
            for hand in ("Left", "Right")
        }

        # Resolution
        if resolution_profile:
            dw = int(resolution_profile["display_width"])
            dh = int(resolution_profile["display_height"])
            self._target_fps = int(resolution_profile["fps"])
        else:
            dw, dh = 1920, 1080
            self._target_fps = 30

        dw, dh, _, _, _ = fit_resolution_to_screen(dw, dh)
        self._logical_w, self._logical_h = dw, dh

        # Camera + MediaPipe
        self._cap = setup_video_capture(width=self._logical_w, height=self._logical_h, fps=self._target_fps)
        self._cam_thread = CameraThread(self._cap)

        hand_complexity = max(0, min(1, int(hand_model_complexity)))
        self._hands_thread = MediaPipeHandsThread(
            mp.solutions.hands.Hands(
                max_num_hands=2, model_complexity=hand_complexity,
                min_detection_confidence=0.3, min_tracking_confidence=0.3,
            )
        )

        # Build UI
        self._build_ui(instrument_name)

        # Frame update timer — run as fast as possible (like keyboard.py)
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)
        self._frame_timer.start(1)  # 1ms = effectively uncapped, limited by processing time

        # FPS tracking
        self._fps_counter = 0
        self._fps_last_time = time.time()
        self._fps_value = 0.0

        # Audio thread
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

        # Select instrument
        select_instrument(self._fs, instrument_name, self._loaded_sfids,
                          self._recorder, channel=0, is_drum=False)

    def _init_audio(self):
        self._fs, self._loaded_sfids = init_fluidsynth(driver="dsound")
        if self._fs is None:
            print("ERRO CRÍTICO DE AUDIO: Falha ao inicializar FluidSynth")
        else:
            from src.instruments.common import load_all_soundfonts
            self._loaded_sfids = load_all_soundfonts(self._fs)

    def _build_ui(self, instrument_name):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter allows horizontal resize of camera
        self._splitter = QSplitter(Qt.Horizontal, central)
        self._splitter.setHandleWidth(4)
        self._splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {COL_BORDER_LIGHT};
            }}
        """)

        # Camera widget — minimum 1/3 of screen
        self._camera_widget = CameraOverlayWidget()
        self._camera_widget.set_piano_keys(self._piano_keys)
        self._camera_widget.set_table_y(self._table_y)
        self._camera_widget.set_show_trackers(False)
        self._splitter.addWidget(self._camera_widget)

        # Control panel
        self._panel = ControlPanel(instrument_name=instrument_name)
        self._panel.sustain_changed.connect(self._on_sustain_changed)
        self._panel.lift_changed.connect(self._on_lift_changed)
        self._panel.tolerance_changed.connect(self._on_tolerance_changed)
        self._panel.preset_changed.connect(self._on_preset_changed)
        self._panel.octave_changed.connect(self._on_octave_changed)
        self._panel.record_clicked.connect(self._on_record)
        self._panel.stop_clicked.connect(self._on_stop)
        self._panel.playback_clicked.connect(self._on_playback)
        self._panel.end_clicked.connect(self._on_end)
        self._panel.tracker_toggled.connect(self._on_tracker_toggled)
        self._panel.scifi_toggled.connect(self._on_scifi_toggled)
        self._splitter.addWidget(self._panel)

        # Set initial proportions (~40% camera, ~60% panel - more square/cropped camera)
        total = self._logical_w
        cam_w = int(total * 0.4)
        panel_w = total - cam_w
        self._splitter.setSizes([cam_w, panel_w])
        # Camera can shrink to 1/3 of screen
        self._camera_widget.setMinimumWidth(total // 3)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, True)  # panel can collapse for fullscreen

        # Threshold: if camera gets wider than this, go fullscreen
        self._fullscreen_threshold = int(total * 0.82)

        # Track current key count and last computed width for dynamic resizing
        self._current_num_keys = DEFAULT_NUM_KEYS
        self._last_cam_width = cam_w
        self._is_camera_fullscreen = False
        self._saved_splitter_sizes = None

        # Recalc keys when user drags the splitter
        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        main_layout.addWidget(self._splitter)

    # --- Audio ---

    def _audio_loop(self):
        while True:
            item = self._audio_queue.get()
            if item is None:
                break
            action, note = item[0], item[1]
            if action == "on":
                self._fs.noteon(0, note, 127)
                self._recorder.record_note_on(note)
            elif action == "off":
                self._fs.noteoff(0, note)
                self._recorder.record_note_off(note)

    # --- Frame loop ---

    @Slot()
    def _on_frame_tick(self):
        frame, grab_ts = self._cam_thread.get_latest()
        if frame is None:
            return

        frame = cv2.resize(frame, (self._logical_w, self._logical_h))
        frame = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Center-crop frame to match the camera widget's aspect ratio
        # so MediaPipe coordinates align with what the user sees.
        cam_w = self._camera_widget.width()
        cam_h = self._camera_widget.height()
        if cam_w > 0 and cam_h > 0:
            fh, fw = frame_rgb.shape[:2]
            widget_aspect = cam_w / cam_h
            frame_aspect = fw / fh
            if frame_aspect > widget_aspect:
                # Frame is wider than widget → crop sides
                new_fw = int(fh * widget_aspect)
                x_off = (fw - new_fw) // 2
                frame_rgb = frame_rgb[:, x_off:x_off + new_fw]
            elif frame_aspect < widget_aspect:
                # Frame is taller than widget → crop top/bottom
                new_fh = int(fw / widget_aspect)
                y_off = (fh - new_fh) // 2
                frame_rgb = frame_rgb[y_off:y_off + new_fh, :]

        # MediaPipe — fire-and-forget (non-blocking, reads stale result)
        crh, crw = frame_rgb.shape[:2]
        frame_mp = prepare_mediapipe_frame(frame_rgb, crw, crh, 480)
        self._hands_thread.submit_frame(frame_mp)
        results = self._hands_thread.get_latest_result()

        # Process fingers
        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                label = results.multi_handedness[idx].classification[0].label
                for fid in ACTIVE_FINGERS:
                    finger = lm.landmark[fid]
                    self._process_finger(label, fid, finger.y, finger.x)

        self._check_lost_fingers()
        self._check_active_keys_integrity()

        # Update camera widget — store frame reference (avoid copy)
        self._camera_widget.set_frame(frame_rgb)
        self._camera_widget.set_results(results)
        self._camera_widget.update()

        # Update FPS
        self._fps_counter += 1
        now_fps = time.time()
        elapsed_fps = now_fps - self._fps_last_time
        if elapsed_fps >= 1.0:
            self._fps_value = self._fps_counter / elapsed_fps
            self._fps_counter = 0
            self._fps_last_time = now_fps
            self._panel.update_fps(self._fps_value)

    # --- Finger processing (simplified from keyboard.py) ---

    def _process_finger(self, label, fid, y_current, x_current):
        state = self._hands_state[label]
        status = state["finger_status"][fid]
        last_time = state["finger_timers"][fid]
        now = time.time()
        state["last_seen"][fid] = now
        dist_above = self._table_y - y_current

        # Release orphan notes
        if status != "TOUCHING" and state["active_notes"][fid] is not None:
            self._audio_queue.put(("off", state["active_notes"][fid]))
            for k in self._piano_keys:
                if k["note"] == state["active_notes"][fid]:
                    k["is_active"] = False
                    break
            state["active_notes"][fid] = None

        if status == "IDLE":
            if dist_above > self._lift_threshold:
                state["finger_status"][fid] = "ARMED"
                state["finger_timers"][fid] = now

        elif status == "ARMED":
            if (now - last_time) > ARMED_TIMEOUT:
                state["finger_status"][fid] = "IDLE"
            elif y_current >= (self._table_y - self._touch_tolerance):
                ki = get_key_index_from_x(self._piano_keys, x_current)
                key = self._piano_keys[ki]
                note = key["note"]
                self._audio_queue.put(("on", note))
                state["active_notes"][fid] = note
                state["finger_status"][fid] = "TOUCHING"
                state["finger_timers"][fid] = now
                key["last_hit"] = now
                key["is_active"] = True
                self._recent_notes.append((note, now))
                if len(self._recent_notes) > 20:
                    self._recent_notes = self._recent_notes[-20:]
                self._camera_widget.add_recent_note(note)

        elif status == "TOUCHING":
            active_note = state["active_notes"][fid]
            if active_note is None:
                state["finger_status"][fid] = "ARMED"
                state["finger_timers"][fid] = now
                return

            ki = get_key_index_from_x(self._piano_keys, x_current)
            new_note = self._piano_keys[ki]["note"]

            if new_note != active_note:
                self._audio_queue.put(("off", active_note))
                for k in self._piano_keys:
                    if k["note"] == active_note:
                        k["is_active"] = False
                        break
                self._audio_queue.put(("on", new_note))
                state["active_notes"][fid] = new_note
                state["finger_timers"][fid] = now
                self._piano_keys[ki]["last_hit"] = now
                self._piano_keys[ki]["is_active"] = True
                self._recent_notes.append((new_note, now))

            time_held = now - last_time
            force_release = dist_above > (RELEASE_THRESHOLD * 2.0)
            normal_release = (dist_above > RELEASE_THRESHOLD) and (time_held > MIN_NOTE_DURATION)

            if force_release or normal_release:
                state["active_notes"][fid] = None
                state["finger_status"][fid] = "ARMED"
                state["finger_timers"][fid] = now

    def _check_lost_fingers(self):
        now = time.time()
        for hand in ("Left", "Right"):
            state = self._hands_state[hand]
            for fid in ACTIVE_FINGERS:
                if state["active_notes"][fid] is not None:
                    if (now - state["last_seen"][fid]) > MAX_MISSING_TIME:
                        note = state["active_notes"][fid]
                        self._audio_queue.put(("off", note))
                        for k in self._piano_keys:
                            if k["note"] == note:
                                k["is_active"] = False
                                break
                        state["active_notes"][fid] = None
                        state["finger_status"][fid] = "IDLE"

    def _check_active_keys_integrity(self):
        now = time.time()
        touched = set()
        for hand in ("Left", "Right"):
            state = self._hands_state[hand]
            for fid in ACTIVE_FINGERS:
                if state["finger_status"][fid] == "TOUCHING":
                    n = state["active_notes"][fid]
                    if n is not None:
                        touched.add(n)

        for key in self._piano_keys:
            if key["is_active"]:
                if key["note"] in touched:
                    key["off_timer"] = 0.0
                else:
                    if key["off_timer"] == 0.0:
                        key["off_timer"] = now
                    elif (now - key["off_timer"]) > self._sustain_decay:
                        self._audio_queue.put(("off", key["note"]))
                        key["is_active"] = False
                        key["off_timer"] = 0.0

    # --- Slot handlers ---

    @Slot(float)
    def _on_sustain_changed(self, value):
        self._sustain_decay = value

    @Slot(float)
    def _on_lift_changed(self, value):
        self._lift_threshold = value

    @Slot(float)
    def _on_tolerance_changed(self, value):
        self._touch_tolerance = value

    @Slot(str)
    def _on_preset_changed(self, name):
        if name in settings.INSTRUMENTS:
            self._instrument_name = name
            select_instrument(self._fs, name, self._loaded_sfids,
                              self._recorder, channel=0, is_drum=False)
            self._panel.set_instrument_name(name)

    @Slot(int)
    def _on_octave_changed(self, octave):
        # Rebuild keys with new base note centered on chosen octave
        global BASE_NOTE
        # C2=36, C3=48, C4=60, C5=72, C6=84
        new_base = (octave + 1) * 12
        num = self._current_num_keys
        pool = []
        for i in range(num):
            n = new_base + i
            if 0 <= n <= 127:
                pool.append(n)
        self._piano_keys = build_piano_keys(len(pool))
        # Override notes
        for i, k in enumerate(self._piano_keys):
            if i < len(pool):
                k["note"] = pool[i]
                k["is_black"] = is_black_key(pool[i])
        _apply_piano_geometry(self._piano_keys)
        self._camera_widget.set_piano_keys(self._piano_keys)

    @Slot()
    def _on_record(self):
        self._recorder.start()

    @Slot()
    def _on_stop(self):
        ts = int(time.time())
        name = self._instrument_name.replace(" ", "_")
        self._recorder.stop(f"keyboard_{name}_{ts}.mid")

    @Slot()
    def _on_playback(self):
        self._recorder.toggle_playback(self._fs)

    @Slot()
    def _on_end(self):
        self._recorder.stop_playback()
        self.close()

    @Slot(bool)
    def _on_tracker_toggled(self, enabled):
        self._show_trackers = enabled
        self._camera_widget.set_show_trackers(enabled)

    @Slot(bool)
    def _on_scifi_toggled(self, enabled):
        self._camera_widget.set_show_scifi(enabled)

    def _on_fullscreen_toggled(self, enabled):
        self._is_camera_fullscreen = enabled
        if enabled:
            self._saved_splitter_sizes = self._splitter.sizes()
            # Collapse panel to 0 but keep splitter handle visible
            total = self._splitter.width()
            self._splitter.setSizes([total, 0])
        else:
            if self._saved_splitter_sizes:
                self._splitter.setSizes(self._saved_splitter_sizes)
        # Recalc key count for new camera width
        QTimer.singleShot(50, self._recalc_keys_for_width)

    def _recalc_keys_for_width(self):
        cam_w = self._camera_widget.width()
        new_num = calc_num_keys_for_width(cam_w)
        if new_num != self._current_num_keys:
            self._current_num_keys = new_num
            self._rebuild_keys_current()

    def _rebuild_keys_current(self):
        """Rebuild piano keys preserving current octave base."""
        if self._piano_keys:
            base = self._piano_keys[0]["note"]
        else:
            base = BASE_NOTE
        pool = []
        for i in range(self._current_num_keys):
            n = base + i
            if 0 <= n <= 127:
                pool.append(n)
        self._piano_keys = build_piano_keys(len(pool))
        for i, k in enumerate(self._piano_keys):
            if i < len(pool):
                k["note"] = pool[i]
                k["is_black"] = is_black_key(pool[i])
        _apply_piano_geometry(self._piano_keys)
        self._camera_widget.set_piano_keys(self._piano_keys)

    def showFullScreen(self):
        super().showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cam_w = self._camera_widget.width()
        if abs(cam_w - self._last_cam_width) > 30:
            self._last_cam_width = cam_w
            self._recalc_keys_for_width()

    def _on_splitter_moved(self, pos, index):
        sizes = self._splitter.sizes()
        cam_w = sizes[0]
        panel_w = sizes[1]

        if not self._is_camera_fullscreen and cam_w >= self._fullscreen_threshold:
            # Dragged past threshold → enter fullscreen
            self._on_fullscreen_toggled(True)
        elif self._is_camera_fullscreen and panel_w > 60:
            # Dragged back from fullscreen → restore
            self._is_camera_fullscreen = False
            self._saved_splitter_sizes = None

        self._recalc_keys_for_width()

    def keyPressEvent(self, event):
        # ESC exits camera fullscreen first, then closes window
        if event.key() == Qt.Key_Escape:
            if self._is_camera_fullscreen:
                self._on_fullscreen_toggled(False)
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        # Cleanup
        self._frame_timer.stop()

        # Stop active notes
        for k in self._piano_keys:
            if k["is_active"]:
                try:
                    self._fs.noteoff(0, k["note"])
                except Exception:
                    pass
                k["is_active"] = False

        self._hands_thread.close()
        self._cam_thread.stop()
        self._cap.release()
        self._audio_queue.put(None)
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def start_piano_ui(chosen_instrument="Piano", user_sustain=None,
                   lift_threshold=None, touch_tolerance=None,
                   resolution_profile=None, show_trackers=False,
                   hand_model_complexity=1):
    """Launch the PySide6 piano UI. Drop-in replacement for start_piano()."""
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_font()

    win = PianoWindow(
        instrument_name=chosen_instrument,
        resolution_profile=resolution_profile,
        show_trackers=show_trackers,
        hand_model_complexity=hand_model_complexity,
        user_sustain=user_sustain,
        lift_threshold=lift_threshold,
        touch_tolerance=touch_tolerance,
    )
    win.showFullScreen()

    app.exec()
    print(">>> Piano UI encerrado.")


if __name__ == "__main__":
    start_piano_ui("Piano")
