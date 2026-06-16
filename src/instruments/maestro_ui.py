"""
Talking Hands — Maestro UI (PySide6)
Fullscreen split layout: camera + hand/emotion overlays on the left,
control panel on the right.

Replaces the pygame-based start_maestro() with a PySide6 window that follows
the same visual language as keyboard_ui.py and drums_ui.py.

Emotion detection still drives automatic instrument selection, but instead of
the rotating neural-visualiser circle, the current emotion is shown as a
colour-coded badge in the control panel.
"""

import sys
import os
import time
import threading
import queue
import math
import collections
import cv2
import numpy as np
import mediapipe as mp
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QProgressBar, QFrame, QSizePolicy,
    QSplitter,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QImage, QPainter, QColor, QFont, QPen, QBrush,
)

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
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
    FONT_FAMILY, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL,
    FONT_SIZE_TIMER, PANEL_MIN_W, BTN_HEIGHT, BORDER_RAD,
    load_custom_font, build_global_qss,
)

from src.expressions.face import EmotionTracker, EMOTION_COLORS

import fluidsynth as _fluidsynth

# ---------------------------------------------------------------------------
# Re-use signal processing helpers from the original maestro implementation
# ---------------------------------------------------------------------------
from src.expressions.maestro import (
    SignalSmoother, OscillationDetector, GestureVelocityTracker,
    DiscreteGestureDetector, _hand_openness, _is_pointing, _note_name,
    EMOTION_INSTRUMENTS,
    # Tuning constants
    MELODY_CH, DRUMS_CH,
    PITCH_LOW, PITCH_HIGH, BEND_UNIT,
    VIB_FREQ_MIN, VIB_FREQ_MAX, VIB_MAX_RATE, VIB_MAX_DEPTH, VIB_AMP_SCALE,
    VIB_HOLD_FRAMES,
    TREM_FREQ_MIN, TREM_FREQ_MAX, TREM_DEPTH, TREM_AMP_SCALE,
    SMOOTH_FAST, SMOOTH_MED, SMOOTH_SLOW,
    RIGHT_HAND_X_MAX, LEFT_HAND_X_MIN,
    VOL_Y_PAD_TOP, VOL_Y_PAD_BOT,
    PERC_SWIPE_DIST, PERC_SWIPE_MAX_TIME, PERC_COOLDOWN,
    ACCENT_DURATION, SWELL_DURATION,
    KICK_NOTE, SNARE_NOTE, HIT_VELOCITY,
    NORMAL_VELOCITY, MAX_VELOCITY,
    HAND_ABSENT_SECS, MP_INPUT_HEIGHT,
    NOTE_NAMES,
)

# ---------------------------------------------------------------------------
# Maestro-specific constants
# ---------------------------------------------------------------------------
EMOTION_INTERVAL = 0.05   # ~20 fps face submissions
EVENT_FADE_SECS  = 1.8    # how long event flashes stay visible

# ---------------------------------------------------------------------------
# Camera + Overlay Widget
# ---------------------------------------------------------------------------

class MaestroOverlayWidget(QWidget):
    """Renders camera feed with hand tracker connections and event overlays."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._frame_rgb = None
        self._results = None
        self._show_trackers = False
        self._show_scifi = True
        self._detecting = False

        # Live gesture state (set by window on each tick)
        self._event_log: list[tuple[str, float]] = []
        self._playing = False
        self._current_note = -1

    # --- Data setters ---

    def set_frame(self, frame_rgb: np.ndarray):
        self._frame_rgb = frame_rgb

    def set_results(self, results):
        self._results = results
        self._detecting = results is not None and results.multi_hand_landmarks is not None

    def set_show_trackers(self, v: bool):
        self._show_trackers = v

    def set_show_scifi(self, v: bool):
        self._show_scifi = v

    def set_gesture_state(self, event_log, playing, current_note):
        self._event_log = event_log
        self._playing = playing
        self._current_note = current_note

    # --- Painting ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor(COL_BG_DARK))

        # Camera frame
        if self._frame_rgb is not None:
            frame = np.ascontiguousarray(self._frame_rgb)
            fh, fw = frame.shape[:2]
            qimg = QImage(frame.data, fw, fh, fw * 3, QImage.Format_RGB888)
            scaled = qimg.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            painter.drawImage(0, 0, scaled)

        # Sci-fi tint + scanlines
        if self._show_scifi:
            painter.fillRect(0, 0, w, h, QColor(0, 180, 255, 8))
            pen = QPen(QColor(0, 0, 0, 18), 1)
            painter.setPen(pen)
            for y_line in range(0, h, 7):
                painter.drawLine(0, y_line, w, y_line)

        # Subtle centre divider — shows left/right hand zones
        divider_x = w // 2
        pen = QPen(QColor(255, 255, 255, 28), 1, Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(divider_x, 0, divider_x, h)

        # Hand connections (optional)
        if self._show_trackers and self._results and self._results.multi_hand_landmarks:
            self._draw_hand_connections(painter, w, h)

        # "DETECTANDO" badge
        self._draw_detecting_indicator(painter)

        # Event flash overlays (kick / snare / accent / swell)
        self._draw_event_flashes(painter, w, h)

        # Active note name (top-centre when playing)
        if self._playing and self._current_note >= 0:
            note_str = _note_name(self._current_note)
            f = QFont(FONT_FAMILY, FONT_SIZE_LG)
            f.setBold(True)
            painter.setFont(f)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(note_str)
            nx = (w - tw) // 2
            ny = 44
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 90)))
            painter.drawRoundedRect(nx - 12, ny - fm.ascent() - 4, tw + 24, fm.height() + 8, 6, 6)
            painter.setPen(QColor(200, 230, 255))
            painter.drawText(nx, ny, note_str)

        painter.end()

    def _draw_hand_connections(self, painter, w, h):
        connections = [
            (0,1),(1,2),(2,3),(3,4),
            (0,5),(5,6),(6,7),(7,8),
            (0,9),(9,10),(10,11),(11,12),
            (0,13),(13,14),(14,15),(15,16),
            (0,17),(17,18),(18,19),(19,20),
            (5,9),(9,13),(13,17),
        ]
        for lm in self._results.multi_hand_landmarks:
            pen = QPen(QColor(COL_ACCENT_GREEN), 2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            for a, b in connections:
                ax = int(lm.landmark[a].x * w)
                ay = int(lm.landmark[a].y * h)
                bx = int(lm.landmark[b].x * w)
                by = int(lm.landmark[b].y * h)
                painter.drawLine(ax, ay, bx, by)
            painter.setBrush(QBrush(QColor(COL_ACCENT_GREEN)))
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
        dot_r = 10
        pad_l = 10
        dot_gap = 8
        pad_r = 12
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

    def _draw_event_flashes(self, painter, w, h):
        now = time.time()
        events_defs = [
            ("kick",   "KICK",   QColor(255, 120, 60),  w // 4,     h - 60),
            ("snare",  "SNARE",  QColor(255, 210, 70),  w // 4 * 3, h - 60),
            ("accent", "ACCENT", QColor(255, 80,  80),  w // 4,     h - 30),
            ("swell",  "SWELL",  QColor(80,  210, 255), w // 4 * 3, h - 30),
        ]
        f = QFont(FONT_FAMILY, FONT_SIZE_MD)
        f.setBold(True)
        painter.setFont(f)
        fm = painter.fontMetrics()
        for ename, elabel, base_col, ex, ey in events_defs:
            best_alpha = 0.0
            for evt_name, evt_ts in self._event_log:
                if evt_name == ename:
                    age = now - evt_ts
                    if age < EVENT_FADE_SECS:
                        best_alpha = max(best_alpha, 1.0 - (age / EVENT_FADE_SECS))
            if best_alpha < 0.02:
                continue
            col = QColor(base_col)
            col.setAlphaF(best_alpha)
            tw = fm.horizontalAdvance(elabel)
            nx = ex - tw // 2
            painter.setPen(Qt.NoPen)
            bg = QColor(0, 0, 0, int(120 * best_alpha))
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(nx - 8, ey - fm.ascent() - 4, tw + 16, fm.height() + 8, 6, 6)
            painter.setPen(col)
            painter.drawText(nx, ey, elabel)


# ---------------------------------------------------------------------------
# Control Panel Widget
# ---------------------------------------------------------------------------

class MaestroControlPanel(QWidget):
    """Right-side panel: emotion badge, signal bars, recording controls."""

    record_clicked  = Signal()
    stop_clicked    = Signal()
    playback_clicked = Signal()
    end_clicked     = Signal()
    tracker_toggled = Signal(bool)
    scifi_toggled   = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlPanel")
        self.setMinimumWidth(PANEL_MIN_W)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._session_start = time.time()
        self._is_recording = False

        self._init_ui()

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(10)

        # Header row
        header_row = QHBoxLayout()
        hdr = QLabel("Maestro")
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
        sub = QLabel("em sessão")
        sub.setObjectName("timerSub")
        layout.addWidget(sub)

        layout.addSpacing(4)

        # ── Expressão Facial ─────────────────────────────────────────────────
        self._add_section_title(layout, "Expressão Facial")

        # Emotion badge
        self._emotion_badge = QLabel("Neutral")
        self._emotion_badge.setAlignment(Qt.AlignCenter)
        self._emotion_badge.setFixedHeight(36)
        self._emotion_badge.setStyleSheet(
            f"background: #2C2C2C; color: white; border-radius: {BORDER_RAD}px;"
            f"font-size: {FONT_SIZE_MD}px; font-family: {FONT_FAMILY}; font-weight: bold;"
        )
        layout.addWidget(self._emotion_badge)

        # Instrument auto-selected by emotion
        instr_row = QHBoxLayout()
        instr_lbl = QLabel("Instrumento:")
        instr_lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_SECONDARY};")
        instr_row.addWidget(instr_lbl)
        self._instr_val = QLabel("Warm Pad")
        self._instr_val.setStyleSheet(f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_PRIMARY}; font-weight: bold;")
        self._instr_val.setAlignment(Qt.AlignRight)
        instr_row.addWidget(self._instr_val)
        layout.addLayout(instr_row)

        layout.addSpacing(4)

        # ── Mão Direita (melodia) ────────────────────────────────────────────
        self._add_section_title(layout, "Mão Direita — Melodia")

        # Current note display
        note_row = QHBoxLayout()
        note_lbl = QLabel("Nota:")
        note_lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_SECONDARY};")
        note_row.addWidget(note_lbl)
        self._note_val = QLabel("--")
        self._note_val.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}px; color: {COL_TEXT_PRIMARY}; font-weight: bold;"
            f"font-family: {FONT_FAMILY};"
        )
        self._note_val.setAlignment(Qt.AlignRight)
        note_row.addWidget(self._note_val)
        layout.addLayout(note_row)

        self._pitch_bar  = self._add_param_bar(layout, "Pitch",   QColor(140, 220, 255))
        self._pan_bar    = self._add_param_bar(layout, "Pan",     QColor(160, 230, 130))
        self._timbre_bar = self._add_param_bar(layout, "Timbre",  QColor(255, 215, 70))

        self._add_section_title(layout, "Vibrato / Tremolo")
        self._vib_rate_bar   = self._add_param_bar(layout, "Vibrato rate",  QColor(200, 150, 255))
        self._vib_depth_bar  = self._add_param_bar(layout, "Vibrato depth", QColor(180, 120, 255))
        self._trem_rate_bar  = self._add_param_bar(layout, "Tremolo rate",  QColor(255, 165, 60))
        self._trem_depth_bar = self._add_param_bar(layout, "Tremolo depth", QColor(255, 120, 40))

        layout.addSpacing(4)

        # ── Mão Esquerda (expressão) ─────────────────────────────────────────
        self._add_section_title(layout, "Mão Esquerda — Expressão")
        self._vol_bar    = self._add_param_bar(layout, "Volume",  QColor(100, 255, 140))
        self._reverb_bar = self._add_param_bar(layout, "Reverb",  QColor(80,  180, 255))
        self._chorus_bar = self._add_param_bar(layout, "Chorus",  QColor(80,  220, 255))

        layout.addSpacing(4)

        # ── Eventos discretos ────────────────────────────────────────────────
        events_row = QHBoxLayout()
        events_row.setSpacing(6)
        self._event_labels: dict[str, QLabel] = {}
        for ename, elabel in [("kick","KICK"),("snare","SNARE"),("accent","ACCENT"),("swell","SWELL")]:
            lbl = QLabel(elabel)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedHeight(26)
            lbl.setStyleSheet(
                f"border-radius: {BORDER_RAD}px; font-size: {FONT_SIZE_SM}px;"
                f"font-family: {FONT_FAMILY}; font-weight: bold;"
                f"background: transparent; color: transparent;"
            )
            events_row.addWidget(lbl)
            self._event_labels[ename] = lbl
        layout.addLayout(events_row)

        layout.addSpacing(4)

        # ── Gravação ─────────────────────────────────────────────────────────
        self._add_section_title(layout, "Gravação")
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._record_btn = QPushButton("● Gravar")
        self._record_btn.setObjectName("octaveBtn")
        self._record_btn.setCheckable(True)
        self._record_btn.setFixedHeight(BTN_HEIGHT)
        self._record_btn.clicked.connect(self._on_record_toggle)
        btn_row.addWidget(self._record_btn, 1)

        self._playback_btn = QPushButton("▶ Playback")
        self._playback_btn.setObjectName("octaveBtn")
        self._playback_btn.setCheckable(True)
        self._playback_btn.setFixedHeight(BTN_HEIGHT)
        self._playback_btn.clicked.connect(self._on_playback_toggle)
        btn_row.addWidget(self._playback_btn, 1)
        layout.addLayout(btn_row)

        layout.addSpacing(4)

        # ── Configurações ─────────────────────────────────────────────────────
        self._add_section_title(layout, "Configurações")

        self._tracker_btn = QPushButton("Trackers: OFF")
        self._tracker_btn.setObjectName("trackerBtn")
        self._tracker_btn.setCheckable(True)
        self._tracker_btn.setFixedHeight(BTN_HEIGHT)
        self._tracker_btn.clicked.connect(self._on_tracker_toggle)
        layout.addWidget(self._tracker_btn)

        self._scifi_btn = QPushButton("Filtro Sci-Fi: ON")
        self._scifi_btn.setObjectName("trackerBtn")
        self._scifi_btn.setCheckable(True)
        self._scifi_btn.setChecked(True)
        self._scifi_btn.setFixedHeight(BTN_HEIGHT)
        self._scifi_btn.clicked.connect(self._on_scifi_toggle)
        layout.addWidget(self._scifi_btn)

        layout.addSpacing(4)

        self._fps_label = QLabel("FPS: --")
        self._fps_label.setObjectName("fpsLabel")
        self._fps_label.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_SECONDARY}; font-family: {FONT_FAMILY};"
        )
        layout.addWidget(self._fps_label)

        layout.addStretch()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _add_section_title(self, layout, text):
        lbl = QLabel(text)
        lbl.setObjectName("sectionTitle")
        layout.addWidget(lbl)

    def _add_param_bar(self, layout, label_text: str, color: QColor) -> QProgressBar:
        """Add a label + QProgressBar row and return the bar widget."""
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(96)
        lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_SECONDARY};")
        row.addWidget(lbl)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        hex_color = color.name()
        bar.setStyleSheet(f"""
            QProgressBar {{
                background: {COL_SLIDER_TRACK};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {hex_color};
                border-radius: 4px;
            }}
        """)
        row.addWidget(bar, 1)
        layout.addLayout(row)
        return bar

    # ── Update methods (called from frame tick) ───────────────────────────────

    def update_emotion(self, emotion: str, instrument: str):
        self._emotion_badge.setText(emotion)
        rgb = EMOTION_COLORS.get(emotion, (180, 180, 180))
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        # Choose text colour (dark on light backgrounds)
        brightness = 0.299 * r + 0.587 * g + 0.114 * b
        text_col = "#1E1E1B" if brightness > 140 else "#FFFFFF"
        self._emotion_badge.setStyleSheet(
            f"background: rgb({r},{g},{b}); color: {text_col}; border-radius: {BORDER_RAD}px;"
            f"font-size: {FONT_SIZE_MD}px; font-family: {FONT_FAMILY}; font-weight: bold;"
        )
        self._instr_val.setText(instrument)

    def update_note(self, playing: bool, current_note: int):
        if playing and current_note >= 0:
            self._note_val.setText(_note_name(current_note))
        else:
            self._note_val.setText("--")

    def update_right_hand(self, pitch_frac, pan_frac, timbre_frac,
                           vib_rate_frac, vib_depth_frac,
                           trem_rate_frac, trem_depth_frac):
        self._pitch_bar.setValue(int(max(0.0, min(1.0, pitch_frac)) * 1000))
        self._pan_bar.setValue(int(max(0.0, min(1.0, pan_frac)) * 1000))
        self._timbre_bar.setValue(int(max(0.0, min(1.0, timbre_frac)) * 1000))
        self._vib_rate_bar.setValue(int(max(0.0, min(1.0, vib_rate_frac)) * 1000))
        self._vib_depth_bar.setValue(int(max(0.0, min(1.0, vib_depth_frac)) * 1000))
        self._trem_rate_bar.setValue(int(max(0.0, min(1.0, trem_rate_frac)) * 1000))
        self._trem_depth_bar.setValue(int(max(0.0, min(1.0, trem_depth_frac)) * 1000))

    def update_left_hand(self, vol_frac, reverb_frac, chorus_frac):
        self._vol_bar.setValue(int(max(0.0, min(1.0, vol_frac)) * 1000))
        self._reverb_bar.setValue(int(max(0.0, min(1.0, reverb_frac)) * 1000))
        self._chorus_bar.setValue(int(max(0.0, min(1.0, chorus_frac)) * 1000))

    def update_events(self, event_log: list, now: float):
        _event_colors = {
            "kick":   ("255,120,60",  "30,15,5"),
            "snare":  ("255,210,70",  "30,25,5"),
            "accent": ("255,80,80",   "30,5,5"),
            "swell":  ("80,210,255",  "5,25,30"),
        }
        for ename, lbl in self._event_labels.items():
            best_alpha = 0.0
            for evt_name, evt_ts in event_log:
                if evt_name == ename:
                    age = now - evt_ts
                    if age < EVENT_FADE_SECS:
                        best_alpha = max(best_alpha, 1.0 - age / EVENT_FADE_SECS)
            if best_alpha > 0.02 and ename in _event_colors:
                fg, bg = _event_colors[ename]
                alpha_i = int(best_alpha * 255)
                lbl.setStyleSheet(
                    f"border-radius: {BORDER_RAD}px; font-size: {FONT_SIZE_SM}px;"
                    f"font-family: {FONT_FAMILY}; font-weight: bold;"
                    f"background: rgba({bg},{ int(best_alpha * 180) });"
                    f"color: rgba({fg},{alpha_i});"
                )
            else:
                lbl.setStyleSheet(
                    f"border-radius: {BORDER_RAD}px; font-size: {FONT_SIZE_SM}px;"
                    f"font-family: {FONT_FAMILY}; font-weight: bold;"
                    f"background: transparent; color: transparent;"
                )

    def update_fps(self, fps: float):
        self._fps_label.setText(f"FPS: {fps:.0f}")

    # ── Internal slots ────────────────────────────────────────────────────────

    def _update_clock(self):
        elapsed = int(time.time() - self._session_start)
        self._timer_label.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

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
        self._is_playing = not getattr(self, "_is_playing", False)
        if self._is_playing:
            self._playback_btn.setText("⏹ Parar")
            self._playback_btn.setChecked(True)
        else:
            self._playback_btn.setText("▶ Playback")
            self._playback_btn.setChecked(False)
        self.playback_clicked.emit()

    def _on_tracker_toggle(self):
        enabled = self._tracker_btn.isChecked()
        self._tracker_btn.setText(f"Trackers: {'ON' if enabled else 'OFF'}")
        self.tracker_toggled.emit(enabled)

    def _on_scifi_toggle(self):
        enabled = self._scifi_btn.isChecked()
        self._scifi_btn.setText(f"Filtro Sci-Fi: {'ON' if enabled else 'OFF'}")
        self.scifi_toggled.emit(enabled)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MaestroWindow(QMainWindow):
    """Fullscreen Maestro window: camera on the left, controls on the right."""

    def __init__(self, resolution_profile=None, show_trackers=False,
                 hand_model_complexity=1, rec_options=None):
        super().__init__()
        self.setWindowTitle("Talking Hands — Maestro")
        self.setStyleSheet(build_global_qss())

        # ── Config ──────────────────────────────────────────────────────────
        self._show_trackers = show_trackers
        self._rec_options = rec_options or {"save_mid": True, "save_wav": True}

        if resolution_profile:
            dw = int(resolution_profile["display_width"])
            dh = int(resolution_profile["display_height"])
            self._target_fps = int(resolution_profile["fps"])
        else:
            dw, dh = 1920, 1080
            self._target_fps = 30

        dw, dh, _, _, _ = fit_resolution_to_screen(dw, dh)
        self._logical_w, self._logical_h = dw, dh

        # ── Audio ────────────────────────────────────────────────────────────
        self._audio_queue: queue.Queue = queue.Queue()
        self._fs = None
        self._loaded_sfids = {}
        self._recorder = MidiRecorder()
        self._recorder.options.update(self._rec_options)
        self._drums_ready = False
        self._init_audio()

        # ── Camera / MediaPipe ───────────────────────────────────────────────
        self._cap = setup_video_capture(
            width=self._logical_w, height=self._logical_h, fps=self._target_fps
        )
        self._cam_thread = CameraThread(self._cap)

        hand_complexity = max(0, min(1, int(hand_model_complexity)))
        self._hands_thread = MediaPipeHandsThread(
            mp.solutions.hands.Hands(
                max_num_hands=2, model_complexity=hand_complexity,
                min_detection_confidence=0.5, min_tracking_confidence=0.5,
            )
        )

        # ── Emotion tracker ──────────────────────────────────────────────────
        self._emotion_tracker = EmotionTracker()
        self._last_emotion_ts = 0.0
        self._current_emotion = "Neutral"
        initial_instr = EMOTION_INSTRUMENTS.get("Neutral", "Warm Pad")
        self._current_instr_name = initial_instr

        # ── Signal smoothers — right hand ────────────────────────────────────
        self._s_pitch     = SignalSmoother(SMOOTH_MED, float((PITCH_LOW + PITCH_HIGH) / 2))
        self._s_pan_r     = SignalSmoother(SMOOTH_MED, 64.0)
        self._s_bright_r  = SignalSmoother(SMOOTH_MED, 64.0)
        self._s_vib_rate  = SignalSmoother(SMOOTH_MED, 0.0)
        self._s_vib_depth = SignalSmoother(SMOOTH_MED, 0.0)
        self._s_trem_rate = SignalSmoother(SMOOTH_MED, 0.0)
        self._s_trem_depth = SignalSmoother(SMOOTH_MED, 0.0)

        # ── Signal smoothers — left hand ─────────────────────────────────────
        self._s_volume = SignalSmoother(SMOOTH_MED,  127.0)
        self._s_reverb = SignalSmoother(SMOOTH_FAST, 20.0)
        self._s_chorus = SignalSmoother(SMOOTH_MED,  0.0)

        # ── Feature detectors ────────────────────────────────────────────────
        self._right_osc     = OscillationDetector(window=32)
        self._right_vel     = GestureVelocityTracker(history_len=6)
        self._right_gesture = DiscreteGestureDetector()
        self._left_vel      = GestureVelocityTracker(history_len=6)
        self._left_gesture  = DiscreteGestureDetector()

        # ── Play state ───────────────────────────────────────────────────────
        self._playing       = False
        self._current_note  = -1
        self._vib_phase     = 0.0
        self._trem_phase    = 0.0
        self._last_right_ts = 0.0
        self._last_time     = time.perf_counter()
        self._vib_hold      = 0
        self._accent_decay  = 0.0
        self._swell_decay   = 0.0
        self._event_log: list[tuple[str, float]] = []

        self._kick_origin_y = None
        self._kick_origin_t = None
        self._snare_origin_y = None
        self._snare_origin_t = None
        self._last_kick_ts  = 0.0
        self._last_snare_ts = 0.0

        # ── FPS tracking ─────────────────────────────────────────────────────
        self._fps_counter   = 0
        self._fps_last_time = time.time()
        self._fps_value     = 0.0

        # ── Build UI ─────────────────────────────────────────────────────────
        self._build_ui()

        # ── Audio thread ─────────────────────────────────────────────────────
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

        # ── Frame timer ──────────────────────────────────────────────────────
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)
        self._frame_timer.start(1)

    # ── Audio init ───────────────────────────────────────────────────────────

    def _init_audio(self):
        self._fs, _ = init_fluidsynth(driver="dsound")
        if self._fs is None:
            print("ERRO CRÍTICO DE AUDIO: FluidSynth não inicializado.")
            return

        self._loaded_sfids = load_all_soundfonts(self._fs)
        initial_instr = EMOTION_INSTRUMENTS.get("Neutral", "Warm Pad")
        select_instrument(
            self._fs, initial_instr, self._loaded_sfids,
            self._recorder, channel=MELODY_CH, is_drum=False,
        )

        # Percussion channel (channel 9, bank 128)
        drums_sfid = self._loaded_sfids.get("drums")
        self._drums_ready = False
        if drums_sfid is not None:
            try:
                self._fs.program_select(DRUMS_CH, drums_sfid, 128, 0)
                self._drums_ready = True
                print(">>> Canal de percussão inicializado (canal 9).")
            except Exception as exc:
                print(f"[!] Canal de percussão não disponível: {exc}")

        try:
            self._fs.setting("synth.gain", 2.0)
        except Exception:
            pass
        self._fs.cc(MELODY_CH, 7,  127)
        self._fs.cc(MELODY_CH, 11, 127)
        self._fs.cc(MELODY_CH, 91, 20)
        self._fs.cc(MELODY_CH, 93, 0)

    # ── Audio worker ─────────────────────────────────────────────────────────

    def _audio_loop(self):
        while True:
            item = self._audio_queue.get()
            if item is None:
                break
            try:
                action = item[0]
                if action == "noteon":
                    _, ch, note, vel = item
                    self._fs.noteon(ch, note, int(vel))
                    if ch == MELODY_CH:
                        self._recorder.record_note_on(note)
                elif action == "noteoff":
                    _, ch, note = item
                    self._fs.noteoff(ch, note)
                    if ch == MELODY_CH:
                        self._recorder.record_note_off(note)
                elif action == "bend":
                    _, value = item
                    self._fs.pitch_bend(MELODY_CH, int(value))
                elif action == "cc":
                    _, ch, ctrl, value = item
                    self._fs.cc(ch, int(ctrl), int(value))
                    if ch == MELODY_CH and hasattr(self._recorder, "record_cc"):
                        self._recorder.record_cc(ch, ctrl, value)
            except Exception:
                pass

    # ── Percussion helper ─────────────────────────────────────────────────────

    def _trigger_perc(self, note, vel=HIT_VELOCITY):
        if not self._drums_ready:
            return
        self._audio_queue.put(("noteon", DRUMS_CH, note, vel))
        t = threading.Timer(
            0.06, lambda: self._audio_queue.put(("noteoff", DRUMS_CH, note))
        )
        t.daemon = True
        t.start()

    # ── UI builder ───────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal, central)
        self._splitter.setHandleWidth(4)
        self._splitter.setStyleSheet(f"""
            QSplitter::handle {{ background-color: {COL_BORDER_LIGHT}; }}
        """)

        self._camera_widget = MaestroOverlayWidget()
        self._camera_widget.set_show_trackers(self._show_trackers)
        self._splitter.addWidget(self._camera_widget)

        self._panel = MaestroControlPanel()
        self._panel.record_clicked.connect(self._on_record)
        self._panel.stop_clicked.connect(self._on_stop)
        self._panel.playback_clicked.connect(self._on_playback)
        self._panel.end_clicked.connect(self._on_end)
        self._panel.tracker_toggled.connect(self._on_tracker_toggled)
        self._panel.scifi_toggled.connect(self._on_scifi_toggled)
        self._splitter.addWidget(self._panel)

        total = self._logical_w
        cam_w = int(total * 0.60)
        self._splitter.setSizes([cam_w, total - cam_w])
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, True)

        main_layout.addWidget(self._splitter)

    # ── Frame tick — all gesture processing happens here ─────────────────────

    @Slot()
    def _on_frame_tick(self):
        frame, _ = self._cam_thread.get_latest()
        if frame is None:
            return

        # Resize + mirror
        frame = cv2.resize(frame, (self._logical_w, self._logical_h))
        frame = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Centre-crop to camera widget aspect ratio
        cam_w = self._camera_widget.width()
        cam_h = self._camera_widget.height()
        if cam_w > 0 and cam_h > 0:
            fh, fw = frame_rgb.shape[:2]
            wa = cam_w / cam_h
            fa = fw / fh
            if fa > wa:
                nfw = int(fh * wa)
                xoff = (fw - nfw) // 2
                frame_rgb = frame_rgb[:, xoff:xoff + nfw]
            elif fa < wa:
                nfh = int(fw / wa)
                yoff = (fh - nfh) // 2
                frame_rgb = frame_rgb[yoff:yoff + nfh, :]

        # MediaPipe input frame (smaller resolution)
        crh, crw = frame_rgb.shape[:2]
        frame_mp = prepare_mediapipe_frame(frame_rgb, crw, crh, MP_INPUT_HEIGHT)

        # ── Emotion tracker ──────────────────────────────────────────────────
        now = time.perf_counter()
        if now - self._last_emotion_ts >= EMOTION_INTERVAL:
            self._emotion_tracker.submit_frame(frame_mp)
            self._last_emotion_ts = now

        detected_emotion, emotion_scores = self._emotion_tracker.get_state()
        if detected_emotion != self._current_emotion:
            new_instr = EMOTION_INSTRUMENTS.get(detected_emotion)
            if new_instr and new_instr != self._current_instr_name:
                select_instrument(
                    self._fs, new_instr, self._loaded_sfids,
                    self._recorder, MELODY_CH,
                )
                self._current_instr_name = new_instr
            self._current_emotion = detected_emotion
        self._panel.update_emotion(self._current_emotion, self._current_instr_name)

        # ── Timing ──────────────────────────────────────────────────────────
        dt = min(now - self._last_time, 0.10)
        self._last_time = now

        # LFO phase advance
        vib_rate_hz  = self._s_vib_rate.value  or 0.0
        trem_rate_hz = self._s_trem_rate.value or 0.0
        self._vib_phase  = (self._vib_phase  + vib_rate_hz  * dt * 2.0 * math.pi) % (2.0 * math.pi)
        self._trem_phase = (self._trem_phase + trem_rate_hz * dt * 2.0 * math.pi) % (2.0 * math.pi)

        # Decay event envelopes
        self._accent_decay = max(0.0, self._accent_decay - dt / ACCENT_DURATION)
        self._swell_decay  = max(0.0, self._swell_decay  - dt / SWELL_DURATION)

        # Trim event log
        if len(self._event_log) > 20:
            self._event_log = [
                (n, t) for n, t in self._event_log
                if (now - t) < EVENT_FADE_SECS * 2
            ]

        # ── MediaPipe Hands ──────────────────────────────────────────────────
        self._hands_thread.submit_frame(frame_mp)
        results = self._hands_thread.get_latest_result()

        right_lm = None
        left_lm  = None

        if results.multi_hand_landmarks and results.multi_handedness:
            for hand_lm, handedness in zip(
                results.multi_hand_landmarks, results.multi_handedness
            ):
                lm    = hand_lm.landmark
                label = handedness.classification[0].label
                # MediaPipe labels are mirrored for selfie; we feed non-mirrored
                # frame → swap Left↔Right to match user's perspective.
                if label == "Right":
                    left_lm = lm
                else:
                    right_lm = lm

        # ════════════════════════════════════════════════════════════════════
        # Right hand — melody, vibrato, tremolo, kick
        # ════════════════════════════════════════════════════════════════════
        if right_lm is not None and right_lm[0].x < RIGHT_HAND_X_MAX:
            self._last_right_ts = now
            rx, ry = right_lm[0].x, right_lm[0].y
            rx_norm = (RIGHT_HAND_X_MAX - rx) / RIGHT_HAND_X_MAX
            r_open  = _hand_openness(right_lm)

            vx_r, vy_r = self._right_vel.update(rx, ry, now)
            osc_freq, osc_amp = self._right_osc.update(rx, now)

            # Vibrato (fast oscillation, 3.5..10 Hz)
            if VIB_FREQ_MIN <= osc_freq <= VIB_FREQ_MAX:
                self._vib_hold = VIB_HOLD_FRAMES
                self._s_vib_rate.update(osc_freq)
                self._s_vib_depth.update(min(VIB_MAX_DEPTH, osc_amp * VIB_AMP_SCALE))
            else:
                if self._vib_hold > 0:
                    self._vib_hold -= 1
                else:
                    self._s_vib_rate.update(0.0)
                    self._s_vib_depth.update(0.0)

            # Tremolo (slow oscillation, 1..5 Hz)
            if TREM_FREQ_MIN <= osc_freq <= TREM_FREQ_MAX:
                self._s_trem_rate.update(osc_freq)
                self._s_trem_depth.update(min(1.0, osc_amp * TREM_AMP_SCALE))
            else:
                self._s_trem_rate.update(0.0)
                self._s_trem_depth.update(0.0)

            # Pitch — Y axis
            target_pitch = PITCH_LOW + (1.0 - ry) * (PITCH_HIGH - PITCH_LOW)
            target_pitch = max(PITCH_LOW - 6.0, min(PITCH_HIGH + 6.0, target_pitch))
            smooth_pitch = self._s_pitch.update(target_pitch)
            smooth_pitch = max(PITCH_LOW - 6.0, min(PITCH_HIGH + 6.0, smooth_pitch))

            # Pan — X axis
            self._s_pan_r.update(rx_norm * 127.0)
            self._audio_queue.put(("cc", MELODY_CH, 10, int(self._s_pan_r.value)))

            # Timbre — hand openness → CC 74 brightness
            self._s_bright_r.update(pow(r_open, 0.6) * 127.0)
            self._audio_queue.put(("cc", MELODY_CH, 74, int(self._s_bright_r.value)))

            # Kick: vertical swipe downward ≥ PERC_SWIPE_DIST
            ry_now = right_lm[0].y
            if self._kick_origin_y is None:
                self._kick_origin_y, self._kick_origin_t = ry_now, now
            else:
                dy_k = ry_now - self._kick_origin_y
                dt_k = now - self._kick_origin_t
                if dt_k <= PERC_SWIPE_MAX_TIME:
                    if dy_k >= PERC_SWIPE_DIST and (now - self._last_kick_ts) >= PERC_COOLDOWN:
                        self._last_kick_ts = now
                        self._kick_origin_y = None
                        self._kick_origin_t = None
                        self._trigger_perc(KICK_NOTE)
                        self._event_log.append(("kick", now))
                else:
                    self._kick_origin_y, self._kick_origin_t = ry_now, now

            # Accent / Swell gestures
            for evt in self._right_gesture.update(vx_r, vy_r, r_open, now):
                self._event_log.append((evt, now))
                if evt == "accent":
                    self._accent_decay = 1.0
                elif evt == "swell":
                    self._swell_decay = 1.0

            # MIDI note + pitch bend (fractional + vibrato LFO)
            new_note   = int(round(smooth_pitch))
            frac_bend  = int((smooth_pitch - new_note) * BEND_UNIT)
            vib_bend   = int(
                math.sin(self._vib_phase)
                * (self._s_vib_depth.value or 0.0)
                * BEND_UNIT
            )
            total_bend = max(-8000, min(8000, frac_bend + vib_bend))
            vel = max(1, min(127, NORMAL_VELOCITY + int(
                self._accent_decay * (MAX_VELOCITY - NORMAL_VELOCITY)
            )))

            if not self._playing:
                self._audio_queue.put(("noteon", MELODY_CH, new_note, vel))
                self._audio_queue.put(("bend", total_bend))
                self._current_note = new_note
                self._playing = True
            else:
                if new_note != self._current_note:
                    self._audio_queue.put(("noteon",  MELODY_CH, new_note, vel))
                    self._audio_queue.put(("noteoff", MELODY_CH, self._current_note))
                    self._current_note = new_note
                self._audio_queue.put(("bend", total_bend))

        else:
            self._kick_origin_y = None
            self._kick_origin_t = None
            self._right_vel.reset()
            self._right_osc.reset()
            self._vib_hold = 0
            self._s_vib_rate.update(0.0)
            self._s_vib_depth.update(0.0)
            self._s_trem_rate.update(0.0)
            self._s_trem_depth.update(0.0)
            if self._playing and (now - self._last_right_ts) > HAND_ABSENT_SECS:
                self._audio_queue.put(("bend", 0))
                self._audio_queue.put(("noteoff", MELODY_CH, self._current_note))
                self._playing = False

        # ════════════════════════════════════════════════════════════════════
        # Left hand — volume, reverb, chorus, snare
        # ════════════════════════════════════════════════════════════════════
        if left_lm is not None and left_lm[0].x > LEFT_HAND_X_MIN:
            lx, ly = left_lm[0].x, left_lm[0].y
            lx_norm = (lx - LEFT_HAND_X_MIN) / (1.0 - LEFT_HAND_X_MIN)
            l_open  = _hand_openness(left_lm)

            vx_l, vy_l = self._left_vel.update(lx, ly, now)

            # Snare: vertical swipe downward (left hand)
            if self._snare_origin_y is None:
                self._snare_origin_y, self._snare_origin_t = ly, now
            else:
                dy_s = ly - self._snare_origin_y
                dt_s = now - self._snare_origin_t
                if dt_s <= PERC_SWIPE_MAX_TIME:
                    if dy_s >= PERC_SWIPE_DIST and (now - self._last_snare_ts) >= PERC_COOLDOWN:
                        self._last_snare_ts = now
                        self._snare_origin_y = None
                        self._snare_origin_t = None
                        self._trigger_perc(SNARE_NOTE)
                        self._event_log.append(("snare", now))
                else:
                    self._snare_origin_y, self._snare_origin_t = ly, now

            # Accent / Swell gestures
            for evt in self._left_gesture.update(vx_l, vy_l, l_open, now):
                self._event_log.append((evt, now))
                if evt == "accent":
                    self._accent_decay = 1.0
                elif evt == "swell":
                    self._swell_decay = 1.0

            # Volume: Y with padding
            vol_raw = 1.0 - (ly - VOL_Y_PAD_TOP) / (VOL_Y_PAD_BOT - VOL_Y_PAD_TOP)
            self._s_volume.update(max(0.0, min(127.0, vol_raw * 127.0)))

            # Reverb: lx_norm + swell boost
            base_reverb = pow(lx_norm, 0.6) * 127.0 + self._swell_decay * 80.0
            self._s_reverb.update(min(127.0, base_reverb))

            # Chorus: hand openness
            self._s_chorus.update(pow(l_open, 0.6) * 127.0)

            # Tremolo-modulated volume
            trem_mod    = (self._s_trem_depth.value or 0.0) * TREM_DEPTH
            trem_factor = 1.0 - trem_mod * max(
                0.0, (1.0 - math.sin(self._trem_phase))
            ) * 0.5
            vol_final = max(0, min(127, int((self._s_volume.value or 127.0) * trem_factor)))

            self._audio_queue.put(("cc", MELODY_CH, 11, vol_final))
            self._audio_queue.put(("cc", MELODY_CH, 91, int(self._s_reverb.value or 20)))
            self._audio_queue.put(("cc", MELODY_CH, 93, int(self._s_chorus.value or 0)))

        else:
            self._snare_origin_y = None
            self._snare_origin_t = None
            self._left_vel.reset()

        # ── Update camera widget ─────────────────────────────────────────────
        self._camera_widget.set_frame(frame_rgb)
        self._camera_widget.set_results(results)
        self._camera_widget.set_gesture_state(
            self._event_log, self._playing, self._current_note
        )
        self._camera_widget.update()

        # ── Update control panel ─────────────────────────────────────────────
        pitch_val  = self._s_pitch.value or float((PITCH_LOW + PITCH_HIGH) / 2)
        pitch_frac = (pitch_val - PITCH_LOW) / (PITCH_HIGH - PITCH_LOW)

        self._panel.update_note(self._playing, self._current_note)
        self._panel.update_right_hand(
            pitch_frac=max(0.0, min(1.0, pitch_frac)),
            pan_frac=(self._s_pan_r.value or 64.0) / 127.0,
            timbre_frac=(self._s_bright_r.value or 64.0) / 127.0,
            vib_rate_frac=(self._s_vib_rate.value or 0.0) / VIB_MAX_RATE,
            vib_depth_frac=min(1.0, (self._s_vib_depth.value or 0.0) / VIB_MAX_DEPTH),
            trem_rate_frac=(self._s_trem_rate.value or 0.0) / TREM_FREQ_MAX,
            trem_depth_frac=min(1.0, self._s_trem_depth.value or 0.0),
        )
        self._panel.update_left_hand(
            vol_frac=(self._s_volume.value or 127.0) / 127.0,
            reverb_frac=(self._s_reverb.value or 20.0) / 127.0,
            chorus_frac=(self._s_chorus.value or 0.0) / 127.0,
        )
        self._panel.update_events(self._event_log, now)

        # ── FPS ──────────────────────────────────────────────────────────────
        self._fps_counter += 1
        now_fps = time.time()
        elapsed_fps = now_fps - self._fps_last_time
        if elapsed_fps >= 1.0:
            self._fps_value = self._fps_counter / elapsed_fps
            self._fps_counter = 0
            self._fps_last_time = now_fps
            self._panel.update_fps(self._fps_value)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    @Slot()
    def _on_record(self):
        self._recorder.start()

    @Slot()
    def _on_stop(self):
        ts = int(time.time())
        self._recorder.stop(f"Maestro_{ts}.mid")

    @Slot()
    def _on_playback(self):
        self._recorder.toggle_playback(self._fs)

    @Slot()
    def _on_end(self):
        self._recorder.stop_playback()
        self.close()

    @Slot(bool)
    def _on_tracker_toggled(self, enabled: bool):
        self._show_trackers = enabled
        self._camera_widget.set_show_trackers(enabled)

    @Slot(bool)
    def _on_scifi_toggled(self, enabled: bool):
        self._camera_widget.set_show_scifi(enabled)

    # ── Window events ─────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._frame_timer.stop()

        # Stop playing note
        if self._playing and self._current_note >= 0:
            try:
                self._fs.noteoff(MELODY_CH, self._current_note)
            except Exception:
                pass

        if self._recorder.is_recording:
            ts = int(time.time())
            self._recorder.stop(f"Maestro_{ts}.mid")

        self._emotion_tracker.stop()
        self._hands_thread.close()
        self._cam_thread.stop()
        self._cap.release()
        self._audio_queue.put(None)

        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def start_maestro_ui(resolution_profile=None, show_trackers=False,
                     hand_model_complexity=1, rec_options=None):
    """Launch the PySide6 Maestro UI."""
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_font()

    win = MaestroWindow(
        resolution_profile=resolution_profile,
        show_trackers=show_trackers,
        hand_model_complexity=hand_model_complexity,
        rec_options=rec_options,
    )
    win.showFullScreen()
    print(">>> MODO PRONTO")
    app.exec()
    print(">>> Maestro UI encerrado.")


if __name__ == "__main__":
    start_maestro_ui()
