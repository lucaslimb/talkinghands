"""
Talking Hands — Drums UI (PySide6)
Fullscreen split layout: camera + drum overlays on the left,
control panel on the right.
"""

import sys
import os
import time
import threading
import queue
import math
import copy
import cv2
import numpy as np
import mediapipe as mp
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSlider, QFrame, QSizePolicy,
    QSplitter, QScrollArea, QMenu, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize, QPointF
from PySide6.QtGui import (
    QImage, QPainter, QColor, QFont, QPen, QBrush,
    QRadialGradient, QMouseEvent,
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
from src.engines.lighting_controller import IdleLightingService
from src.instruments.common import (
    init_fluidsynth, load_single_soundfont, select_instrument,
    setup_video_capture, fit_resolution_to_screen,
    CameraThread, prepare_mediapipe_frame,
    MediaPipeHandsThread, MediaPipePoseThread,
)
from src.instruments.ui_shared import (
    COL_BG_DARK, COL_BG_PANEL, COL_BG_PANEL_ALT, COL_ACCENT_GREEN,
    COL_ACCENT_RED, COL_TEXT_PRIMARY, COL_TEXT_SECONDARY, COL_TEXT_LIGHT,
    COL_BTN_RECORD, COL_BTN_PAUSE, COL_BORDER_LIGHT, COL_OCTAVE_ACTIVE,
    COL_SLIDER_TRACK, COL_SLIDER_HANDLE, COL_DETECTING_BG, COL_DETECTING_DOT,
    COL_KEY_ACTIVE, COL_NOTE_PILL_BG,
    FONT_FAMILY, FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL,
    FONT_SIZE_TIMER, PANEL_MIN_W, BTN_HEIGHT, BORDER_RAD,
    load_custom_font, build_global_qss,
)

import fluidsynth as _fluidsynth

# ---------------------------------------------------------------------------
# Drums-specific constants (from settings)
# ---------------------------------------------------------------------------
VELOCITY_THRESHOLD     = float(getattr(settings, 'DRUMS_VELOCITY_THRESHOLD', 0.002))
TOUCH_VELOCITY         = float(getattr(settings, 'DRUMS_TOUCH_VELOCITY', 0.012))
TOUCH_TOLERANCE        = float(getattr(settings, 'DRUMS_TOUCH_TOLERANCE', 0.01))
ELLIPSE_THRESHOLD      = 1.0 - TOUCH_TOLERANCE
DRUM_MIN_VELOCITY      = int(getattr(settings, 'DRUMS_MIN_VELOCITY', 50))
MIN_REHIT_PIXELS       = int(getattr(settings, 'DRUMS_MIN_REHIT_PIXELS', 32))
FOOT_REHIT_PIXELS      = int(getattr(settings, 'DRUMS_FOOT_REHIT_PIXELS', 36))
DRUM_MIN_HIT_INTERVAL  = float(getattr(settings, 'DRUMS_MIN_HIT_INTERVAL_SEC', 0.045))
LIGHTING_FADEOUT_MS    = int(getattr(settings, 'DRUMS_LIGHTING_FADEOUT_MS', 220))
CYMBAL_ELEMENTS = {
    "crash", "crash2", "ride", "ride2", "splash", "china", "ride_bell",
    "hihat", "open_hh", "hh_pedal",
}
DRUM_CUSTOM_RECT_THICK = float(getattr(settings, 'DRUMS_CUSTOM_RECT_THICKNESS', 1.20))
DRUM_RESIZE_EDGE_TOL   = int(getattr(settings, 'DRUMS_RESIZE_EDGE_TOLERANCE_PX', 10))
DRUM_MIN_HALF_W_NORM   = float(getattr(settings, 'DRUMS_MIN_HALF_WIDTH_NORM', 0.02))
DRUM_MIN_HALF_H_NORM   = float(getattr(settings, 'DRUMS_MIN_HALF_HEIGHT_NORM', 0.015))
POLYPHONY_CHANNELS     = 16
FIXED_SF2_PATH         = settings.SF2_PATHS["drums"]

# Swipe kit gesture
SWIPE_OPEN_MIN  = 0.7
SWIPE_DIST      = 0.25
SWIPE_MAX_TIME  = 1.5
SWIPE_COOLDOWN  = 1.0

DRUMS_SWIPE_KITS = [
    "Classic", "Power", "Vintage", "Bright",
    "Power Tight", "Power Wide", "Latin",
]

# ---------------------------------------------------------------------------
# Drum element library (identical to drums.py)
# ---------------------------------------------------------------------------
DRUM_ELEMENT_LIBRARY = {
    "crash":      {"name": "CRASH",     "note": 49, "shape": "ellipse", "row": "top",    "size": 1.15, "ry_ratio": 0.34, "foot_only": False},
    "ride":       {"name": "RIDE",      "note": 51, "shape": "ellipse", "row": "top",    "size": 1.15, "ry_ratio": 0.34, "foot_only": False},
    "splash":     {"name": "SPLASH",    "note": 55, "shape": "ellipse", "row": "top",    "size": 0.85, "ry_ratio": 0.34, "foot_only": False},
    "china":      {"name": "CHINA",     "note": 52, "shape": "ellipse", "row": "top",    "size": 1.00, "ry_ratio": 0.34, "foot_only": False},
    "tom_hi":     {"name": "HI-TOM",    "note": 48, "shape": "ellipse", "row": "mid",    "size": 0.95, "ry_ratio": 0.42, "foot_only": False},
    "tom_mid":    {"name": "MID-TOM",   "note": 47, "shape": "ellipse", "row": "mid",    "size": 0.95, "ry_ratio": 0.42, "foot_only": False},
    "tom_low":    {"name": "LO-TOM",    "note": 45, "shape": "ellipse", "row": "mid",    "size": 1.00, "ry_ratio": 0.42, "foot_only": False},
    "hihat":      {"name": "HI-HAT",    "note": 42, "shape": "ellipse", "row": "bottom", "size": 1.00, "ry_ratio": 0.45, "foot_only": False},
    "open_hh":    {"name": "OPEN-HH",   "note": 46, "shape": "ellipse", "row": "top",    "size": 0.95, "ry_ratio": 0.34, "foot_only": False},
    "snare":      {"name": "SNARE",     "note": 38, "shape": "ellipse", "row": "bottom", "size": 1.15, "ry_ratio": 0.45, "foot_only": False},
    "rimshot":    {"name": "RIMSHOT",   "note": 37, "shape": "rect",    "row": "bottom", "size": 0.62, "ry_ratio": 0.28, "foot_only": False},
    "snare_alt":  {"name": "SNARE-ALT", "note": 40, "shape": "ellipse", "row": "bottom", "size": 1.00, "ry_ratio": 0.42, "foot_only": False},
    "floor":      {"name": "FLOOR",     "note": 41, "shape": "ellipse", "row": "bottom", "size": 1.05, "ry_ratio": 0.45, "foot_only": False},
    "kick":       {"name": "KICK",      "note": 36, "shape": "rect",    "row": "foot",   "size": 1.40, "ry_ratio": 0.16, "foot_only": False},
    "kick_alt":   {"name": "KICK-ALT",  "note": 35, "shape": "rect",    "row": "foot",   "size": 1.30, "ry_ratio": 0.16, "foot_only": False},
    "hh_pedal":   {"name": "HH-PEDAL",  "note": 44, "shape": "rect",    "row": "foot",   "size": 0.65, "ry_ratio": 0.22, "foot_only": True},
    "cowbell":    {"name": "COWBELL",   "note": 56, "shape": "rect",    "row": "top",    "size": 0.60, "ry_ratio": 0.30, "foot_only": False},
    "clap":       {"name": "CLAP",      "note": 39, "shape": "rect",    "row": "bottom", "size": 0.70, "ry_ratio": 0.28, "foot_only": False},
    "tamb":       {"name": "TAMB",      "note": 54, "shape": "rect",    "row": "top",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "ride_bell":  {"name": "RIDE-BELL", "note": 53, "shape": "rect",    "row": "top",    "size": 0.62, "ry_ratio": 0.30, "foot_only": False},
    "crash2":     {"name": "CRASH 2",   "note": 57, "shape": "ellipse", "row": "top",    "size": 1.05, "ry_ratio": 0.34, "foot_only": False},
    "ride2":      {"name": "RIDE 2",    "note": 59, "shape": "ellipse", "row": "top",    "size": 1.05, "ry_ratio": 0.34, "foot_only": False},
    "vibra_slap": {"name": "VIBRA",     "note": 58, "shape": "rect",    "row": "mid",    "size": 0.55, "ry_ratio": 0.30, "foot_only": False},
    "shaker":     {"name": "SHAKER",    "note": 82, "shape": "rect",    "row": "top",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "cabasa":     {"name": "CABASA",    "note": 69, "shape": "rect",    "row": "mid",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "maracas":    {"name": "MARACAS",   "note": 70, "shape": "rect",    "row": "mid",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "guiro_s":    {"name": "GUIRO-S",   "note": 73, "shape": "rect",    "row": "mid",    "size": 0.52, "ry_ratio": 0.28, "foot_only": False},
    "guiro_l":    {"name": "GUIRO-L",   "note": 74, "shape": "rect",    "row": "mid",    "size": 0.52, "ry_ratio": 0.28, "foot_only": False},
    "agogo_hi":   {"name": "AGOGO-H",   "note": 67, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "agogo_lo":   {"name": "AGOGO-L",   "note": 68, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "clave":      {"name": "CLAVE",     "note": 75, "shape": "rect",    "row": "bottom", "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "wood_hi":    {"name": "WOOD-HI",   "note": 76, "shape": "rect",    "row": "bottom", "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "wood_lo":    {"name": "WOOD-LO",   "note": 77, "shape": "rect",    "row": "bottom", "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "tri_mute":   {"name": "TRI-MUTE",  "note": 80, "shape": "rect",    "row": "top",    "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "tri_open":   {"name": "TRI-OPEN",  "note": 81, "shape": "rect",    "row": "top",    "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "bongo_hi":   {"name": "BONGO-H",   "note": 60, "shape": "ellipse", "row": "mid",    "size": 0.62, "ry_ratio": 1.00, "foot_only": False},
    "bongo_mid":  {"name": "BONGO-M",   "note": 63, "shape": "ellipse", "row": "mid",    "size": 0.62, "ry_ratio": 1.00, "foot_only": False},
    "bongo_lo":   {"name": "BONGO-L",   "note": 61, "shape": "ellipse", "row": "mid",    "size": 0.66, "ry_ratio": 1.00, "foot_only": False},
    "bongo_deep": {"name": "BONGO-D",   "note": 64, "shape": "ellipse", "row": "mid",    "size": 0.70, "ry_ratio": 1.00, "foot_only": False},
    "conga_hi":   {"name": "CONGA-H",   "note": 62, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "conga_mid":  {"name": "CONGA-M",   "note": 63, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "conga_lo":   {"name": "CONGA-L",   "note": 64, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "timbale_hi": {"name": "TIMB-H",    "note": 65, "shape": "rect",    "row": "mid",    "size": 0.56, "ry_ratio": 0.30, "foot_only": False},
    "timbale_lo": {"name": "TIMB-L",    "note": 66, "shape": "rect",    "row": "mid",    "size": 0.56, "ry_ratio": 0.30, "foot_only": False},
}

# Apply settings overrides
_NOTE_OVERRIDES = getattr(settings, "DRUMS_NOTE_OVERRIDES", {}) or {}
for _ek, _nv in _NOTE_OVERRIDES.items():
    if _ek in DRUM_ELEMENT_LIBRARY:
        try:
            _n = int(_nv)
            if 0 <= _n <= 127:
                DRUM_ELEMENT_LIBRARY[_ek]["note"] = _n
        except Exception:
            pass

BASE_DRUM_NOTES = {k: int(c.get("note", 0)) for k, c in DRUM_ELEMENT_LIBRARY.items()}
DRUMS_INSTRUMENT_NOTE_VARIATIONS = getattr(settings, "DRUMS_INSTRUMENT_NOTE_VARIATIONS", {}) or {}
DRUMS_INSTRUMENT_ELEMENT_PRESETS = getattr(settings, "DRUMS_INSTRUMENT_ELEMENT_PRESETS", {}) or {}
DRUMS_INSTRUMENT_REPLACE_BASE = set(getattr(settings, "DRUMS_INSTRUMENT_REPLACE_BASE", []))

DEFAULT_DRUM_ELEMENTS = list(getattr(settings, "DRUMS_DEFAULT_ELEMENTS",
    ["crash", "ride", "tom_hi", "tom_low", "hihat", "snare", "floor", "kick"]))
COMPLETE_EXTRA_ELEMENTS = list(getattr(settings, "DRUMS_COMPLETE_EXTRA_ELEMENTS", ["hh_pedal"]))

# ---------------------------------------------------------------------------
# Kit grouping for the panel (similar elements → expandable groups)
# ---------------------------------------------------------------------------
KIT_GROUPS = [
    {"label": "Cymbals",  "items": ["crash", "crash2", "ride", "ride2", "splash", "china", "ride_bell"]},
    {"label": "Hi-Hat",   "items": ["hihat", "open_hh", "hh_pedal"]},
    {"label": "Toms",     "items": ["tom_hi", "tom_mid", "tom_low"]},
    {"label": "Snare",    "items": ["snare", "snare_alt", "rimshot", "clap"]},
    {"label": "Kick",     "items": ["kick", "kick_alt"]},
    {"label": "Floor",    "items": ["floor"]},
    {"label": "Latin",    "items": ["bongo_hi", "bongo_mid", "bongo_lo", "bongo_deep",
                                     "conga_hi", "conga_mid", "conga_lo",
                                     "timbale_hi", "timbale_lo"]},
    {"label": "Aux",      "items": ["cowbell", "tamb", "shaker", "cabasa", "maracas",
                                     "vibra_slap", "guiro_s", "guiro_l",
                                     "agogo_hi", "agogo_lo", "clave",
                                     "wood_hi", "wood_lo", "tri_mute", "tri_open"]},
]

# ---------------------------------------------------------------------------
# Layouts (from drums.py)
# ---------------------------------------------------------------------------
FIXED_BASE_LAYOUT_DEFAULT = [
    {"element_key": "crash",   "pos": (0.20, 0.40), "axes": (0.13, 0.045)},
    {"element_key": "ride",    "pos": (0.80, 0.40), "axes": (0.13, 0.045)},
    {"element_key": "tom_hi",  "pos": (0.38, 0.60), "axes": (0.10, 0.045)},
    {"element_key": "tom_low", "pos": (0.62, 0.60), "axes": (0.10, 0.045)},
    {"element_key": "hihat",   "pos": (0.20, 0.85), "axes": (0.12, 0.055)},
    {"element_key": "snare",   "pos": (0.50, 0.80), "axes": (0.14, 0.060)},
    {"element_key": "floor",   "pos": (0.80, 0.85), "axes": (0.12, 0.055)},
    {"element_key": "kick",    "pos": (0.50, 0.96), "axes": (0.16, 0.025), "foot_only": False},
]

FIXED_BASE_LAYOUT_COMPLETE = [
    {"element_key": "crash",    "pos": (0.20, 0.40), "axes": (0.13, 0.045)},
    {"element_key": "ride",     "pos": (0.80, 0.40), "axes": (0.13, 0.045)},
    {"element_key": "tom_hi",   "pos": (0.38, 0.60), "axes": (0.10, 0.045)},
    {"element_key": "tom_low",  "pos": (0.62, 0.60), "axes": (0.10, 0.045)},
    {"element_key": "hihat",    "pos": (0.20, 0.85), "axes": (0.12, 0.055)},
    {"element_key": "snare",    "pos": (0.50, 0.80), "axes": (0.14, 0.060)},
    {"element_key": "floor",    "pos": (0.80, 0.85), "axes": (0.12, 0.055)},
    {"element_key": "kick",     "pos": (0.50, 0.96), "axes": (0.16, 0.033), "foot_only": True},
    {"element_key": "hh_pedal", "pos": (0.25, 0.96), "axes": (0.07, 0.030), "foot_only": True},
]

LATIN_REPLACEMENT_LAYOUT = [
    {"element_key": "bongo_hi",   "pos": (0.20, 0.40), "axes": (0.09, 0.09)},
    {"element_key": "bongo_mid",  "pos": (0.80, 0.40), "axes": (0.09, 0.09)},
    {"element_key": "bongo_lo",   "pos": (0.38, 0.60), "axes": (0.10, 0.10)},
    {"element_key": "bongo_deep", "pos": (0.62, 0.60), "axes": (0.11, 0.11)},
    {"element_key": "conga_mid",  "pos": (0.50, 0.80), "axes": (0.11, 0.07)},
    {"element_key": "maracas",    "pos": (0.20, 0.85), "axes": (0.10, 0.06)},
    {"element_key": "cabasa",     "pos": (0.80, 0.85), "axes": (0.10, 0.06)},
]

EXTRA_SLOTS = [
    {"pos": (0.50, 0.33), "base_rx": 0.09,  "row": "top"},
    {"pos": (0.35, 0.33), "base_rx": 0.08,  "row": "top"},
    {"pos": (0.65, 0.33), "base_rx": 0.08,  "row": "top"},
    {"pos": (0.12, 0.55), "base_rx": 0.07,  "row": "mid"},
    {"pos": (0.88, 0.55), "base_rx": 0.07,  "row": "mid"},
    {"pos": (0.50, 0.66), "base_rx": 0.08,  "row": "mid"},
    {"pos": (0.34, 0.73), "base_rx": 0.075, "row": "bottom"},
    {"pos": (0.66, 0.73), "base_rx": 0.075, "row": "bottom"},
    {"pos": (0.68, 0.93), "base_rx": 0.06,  "row": "foot"},
]

# ---------------------------------------------------------------------------
# Drum kit building helpers (mirrors drums.py logic)
# ---------------------------------------------------------------------------

def apply_drum_note_profile(instrument_name=None):
    for key, note in BASE_DRUM_NOTES.items():
        if key in DRUM_ELEMENT_LIBRARY:
            DRUM_ELEMENT_LIBRARY[key]["note"] = note
    profile = DRUMS_INSTRUMENT_NOTE_VARIATIONS.get(instrument_name, {}) if instrument_name else {}
    for key, nv in profile.items():
        if key in DRUM_ELEMENT_LIBRARY:
            try:
                n = int(nv)
                if 0 <= n <= 127:
                    DRUM_ELEMENT_LIBRARY[key]["note"] = n
            except Exception:
                pass


def _make_drum(entry, complete_mode=False):
    key = entry["element_key"]
    template = DRUM_ELEMENT_LIBRARY[key]
    drum = dict(template)
    drum["element_key"] = key
    drum["pos"] = list(entry["pos"])
    drum["axes"] = list(entry["axes"])
    if "foot_only" in entry:
        drum["foot_only"] = bool(entry["foot_only"])
    elif key == "kick":
        drum["foot_only"] = bool(complete_mode)
    return drum


def _drums_overlap(d1, d2, gap=0.008):
    x1, y1 = d1["pos"]
    x2, y2 = d2["pos"]
    rx1, ry1 = d1["axes"]
    rx2, ry2 = d2["axes"]
    return (abs(x1 - x2) < (rx1 + rx2 + gap)) and (abs(y1 - y2) < (ry1 + ry2 + gap))


def _fits(candidate, kit):
    return all(not _drums_overlap(candidate, d) for d in kit)


def _shrink_row(kit, row, factor=0.92, min_rx=0.03):
    for d in kit:
        if d.get("row") != row:
            continue
        rx, ry = d["axes"]
        new_rx = max(min_rx, rx * factor)
        s = new_rx / rx if rx > 0 else 1.0
        d["axes"] = [new_rx, ry * s]


def _add_extras(kit, extras):
    slot_used = [False] * len(EXTRA_SLOTS)
    for ek in extras:
        tmpl = DRUM_ELEMENT_LIBRARY.get(ek)
        if not tmpl:
            continue
        pref_row = tmpl.get("row", "mid")
        slots = [(i, s) for i, s in enumerate(EXTRA_SLOTS) if not slot_used[i]]
        slots.sort(key=lambda x: 0 if x[1]["row"] == pref_row else 1)
        placed = False
        for idx, slot in slots:
            cand = dict(tmpl)
            cand["element_key"] = ek
            cand["pos"] = list(slot["pos"])
            rx = slot["base_rx"] * float(tmpl.get("size", 1.0))
            ry = rx * float(tmpl.get("ry_ratio", 0.35))
            if str(tmpl.get("shape", "")).lower() == "rect":
                ry *= max(1.0, DRUM_CUSTOM_RECT_THICK)
            cand["axes"] = [rx, ry]
            if not _fits(cand, kit):
                _shrink_row(kit, slot["row"])
                if not _fits(cand, kit):
                    continue
            slot_used[idx] = True
            kit.append(cand)
            placed = True
            break


def build_drum_kit(drum_model="default", elements=None, instrument_name=None):
    """Build and return a list of drum dicts ready for rendering."""
    model = (drum_model or "default").strip().lower()
    complete = model == "complete"

    # Determine element list
    if elements:
        selected = [e for e in elements if e in DRUM_ELEMENT_LIBRARY]
    else:
        selected = list(DEFAULT_DRUM_ELEMENTS)
        if complete:
            selected.extend([e for e in COMPLETE_EXTRA_ELEMENTS if e not in selected])

    # Check instrument presets
    replace_base = False
    if elements is None and instrument_name in DRUMS_INSTRUMENT_ELEMENT_PRESETS:
        preset = DRUMS_INSTRUMENT_ELEMENT_PRESETS[instrument_name]
        selected = [e for e in preset if e in DRUM_ELEMENT_LIBRARY]
        if instrument_name in DRUMS_INSTRUMENT_REPLACE_BASE:
            replace_base = True

    # Deduplicate
    seen = set()
    dedup = []
    for e in selected:
        if e not in seen:
            dedup.append(e)
            seen.add(e)
    if not dedup:
        dedup = ["snare", "kick"]

    # Build kit
    if replace_base:
        if instrument_name == "Latin":
            kit = [_make_drum(entry) for entry in LATIN_REPLACEMENT_LAYOUT
                   if entry["element_key"] in DRUM_ELEMENT_LIBRARY]
            placed = {d["element_key"] for d in kit}
            missing = [e for e in dedup if e not in placed]
            if missing:
                _add_extras(kit, missing)
        else:
            kit = []
            _add_extras(kit, dedup)
    else:
        source = FIXED_BASE_LAYOUT_COMPLETE if complete else FIXED_BASE_LAYOUT_DEFAULT
        kit = [_make_drum(entry, complete) for entry in source]
        base_keys = {d["element_key"] for d in kit}
        extras = [e for e in dedup if e not in base_keys]
        if extras:
            _add_extras(kit, extras)

    # Finalize
    for idx, d in enumerate(kit):
        d["id"] = idx
        d["last_hit"] = 0.0
        d.setdefault("foot_only", False)

    return kit


# ---------------------------------------------------------------------------
# Collision / hit helpers
# ---------------------------------------------------------------------------

def check_collision(x, y, drum):
    h, k = drum["pos"]
    rx, ry = drum["axes"]
    tol = TOUCH_TOLERANCE
    if drum["shape"] == "rect":
        return (h - rx + tol <= x <= h + rx - tol) and (k - ry + tol <= y <= k + ry - tol)
    val = ((x - h) ** 2 / rx ** 2) + ((y - k) ** 2 / ry ** 2)
    return val <= ELLIPSE_THRESHOLD


def is_mouse_over(mx_norm, my_norm, drum):
    h, k = drum["pos"]
    rx, ry = drum["axes"]
    if drum["shape"] == "rect":
        return (h - rx < mx_norm < h + rx) and (k - ry < my_norm < k + ry)
    return ((mx_norm - h) ** 2 / rx ** 2) + ((my_norm - k) ** 2 / ry ** 2) <= 1.0


def detect_resize_handle(mx, my, drum, w, h, tol=DRUM_RESIZE_EDGE_TOL):
    cx = drum["pos"][0] * w
    cy = drum["pos"][1] * h
    rx = drum["axes"][0] * w
    ry = drum["axes"][1] * h
    left, right, top, bottom = cx - rx, cx + rx, cy - ry, cy + ry
    if mx < left - tol or mx > right + tol or my < top - tol or my > bottom + tol:
        return None
    cands = []
    if top <= my <= bottom:
        dl = abs(mx - left)
        dr = abs(mx - right)
        if dl <= tol: cands.append((dl, "left"))
        if dr <= tol: cands.append((dr, "right"))
    if left <= mx <= right:
        dt = abs(my - top)
        db = abs(my - bottom)
        if dt <= tol: cands.append((dt, "top"))
        if db <= tol: cands.append((db, "bottom"))
    if not cands:
        return None
    cands.sort(key=lambda c: c[0])
    return cands[0][1]


def apply_resize(drum, handle, mx, my, w, h):
    cx, cy = drum["pos"]
    rx, ry = drum["axes"]
    l, r, t, b = cx - rx, cx + rx, cy - ry, cy + ry
    nm = mx / w
    nn = my / h
    min_rx, min_ry = DRUM_MIN_HALF_W_NORM, DRUM_MIN_HALF_H_NORM
    if handle == "left":
        nl = max(0.0, min(nm, r - 2 * min_rx))
        drum["pos"][0] = (nl + r) * 0.5
        drum["axes"][0] = (r - nl) * 0.5
    elif handle == "right":
        nr = min(1.0, max(nm, l + 2 * min_rx))
        drum["pos"][0] = (l + nr) * 0.5
        drum["axes"][0] = (nr - l) * 0.5
    elif handle == "top":
        nt = max(0.0, min(nn, b - 2 * min_ry))
        drum["pos"][1] = (nt + b) * 0.5
        drum["axes"][1] = (b - nt) * 0.5
    elif handle == "bottom":
        nb = min(1.0, max(nn, t + 2 * min_ry))
        drum["pos"][1] = (t + nb) * 0.5
        drum["axes"][1] = (nb - t) * 0.5


# ---------------------------------------------------------------------------
# Swipe openness helper
# ---------------------------------------------------------------------------

def _swipe_openness(lm):
    tips = [4, 8, 12, 16, 20]
    avg = sum(math.sqrt((lm[t].x - lm[0].x) ** 2 + (lm[t].y - lm[0].y) ** 2) for t in tips) / 5
    return max(0.0, min(1.0, (avg - 0.08) / 0.17))


# ═══════════════════════════════════════════════════════════════════════════
# Camera + Drums overlay widget
# ═══════════════════════════════════════════════════════════════════════════

class DrumOverlayWidget(QWidget):
    """Renders camera feed with drum elements, hand/foot trackers, and hit animations."""

    drum_hit = Signal(int, int)  # (note, velocity)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self._frame_rgb = None
        self._results = None
        self._pose_results = None
        self._drum_kit = []
        self._initial_positions = {}
        self._show_trackers = False
        self._show_scifi = True
        self._show_names = True
        self._detecting = False

        # Mouse drag/resize state
        self._dragging_drum = None
        self._drag_offset = (0.0, 0.0)
        self._resizing_drum = None
        self._resize_handle = None

    # --- Data setters ---

    def set_frame(self, frame_rgb):
        self._frame_rgb = frame_rgb

    def set_results(self, results):
        self._results = results
        self._detecting = results is not None and results.multi_hand_landmarks is not None

    def set_pose_results(self, results):
        self._pose_results = results

    def set_drum_kit(self, kit):
        self._drum_kit = kit
        self._initial_positions = {d["id"]: list(d["pos"]) for d in kit}

    def set_show_trackers(self, v):
        self._show_trackers = v

    def set_show_scifi(self, v):
        self._show_scifi = v

    def set_show_names(self, v):
        self._show_names = v

    def reset_positions(self):
        for d in self._drum_kit:
            if d["id"] in self._initial_positions:
                d["pos"] = list(self._initial_positions[d["id"]])

    # --- Mouse interaction (drag/resize) ---

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            mx, my = event.position().x(), event.position().y()
            w, h = self.width(), self.height()
            # Check resize handles first
            for drum in reversed(self._drum_kit):
                handle = detect_resize_handle(mx, my, drum, w, h)
                if handle:
                    self._resizing_drum = drum
                    self._resize_handle = handle
                    self._dragging_drum = None
                    return
            # Check interior drag
            nm = mx / w
            nn = my / h
            for drum in reversed(self._drum_kit):
                if is_mouse_over(nm, nn, drum):
                    self._dragging_drum = drum
                    self._drag_offset = (drum["pos"][0] - nm, drum["pos"][1] - nn)
                    self._resizing_drum = None
                    return
        elif event.button() == Qt.RightButton:
            mx, my = event.position().x(), event.position().y()
            w, h = self.width(), self.height()
            nm, nn = mx / w, my / h
            for idx in range(len(self._drum_kit) - 1, -1, -1):
                if is_mouse_over(nm, nn, self._drum_kit[idx]):
                    self._drum_kit.pop(idx)
                    break

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging_drum = None
            self._resizing_drum = None
            self._resize_handle = None

    def mouseMoveEvent(self, event: QMouseEvent):
        mx, my = event.position().x(), event.position().y()
        w, h = self.width(), self.height()
        if self._resizing_drum and self._resize_handle:
            apply_resize(self._resizing_drum, self._resize_handle, mx, my, w, h)
        elif self._dragging_drum:
            nm = mx / w + self._drag_offset[0]
            nn = my / h + self._drag_offset[1]
            self._dragging_drum["pos"][0] = max(0.05, min(0.95, nm))
            self._dragging_drum["pos"][1] = max(0.05, min(0.95, nn))

    # --- Paint ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor(COL_BG_DARK))

        # Camera frame (center-cropped)
        if self._frame_rgb is not None:
            frame = np.ascontiguousarray(self._frame_rgb)
            fh, fw = frame.shape[:2]
            qimg = QImage(frame.data, fw, fh, fw * 3, QImage.Format_RGB888)
            scaled = qimg.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            painter.drawImage(0, 0, scaled)

        # Sci-fi tint + scanlines
        if self._show_scifi:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.fillRect(0, 0, w, h, QColor(0, 255, 80, 10))
            pen = QPen(QColor(0, 0, 0, 20), 1)
            painter.setPen(pen)
            for y_line in range(0, h, 7):
                painter.drawLine(0, y_line, w, y_line)

        # Draw drum elements
        self._draw_drums(painter, w, h)

        # Hand connections (when trackers enabled)
        if self._show_trackers and self._results and self._results.multi_hand_landmarks:
            self._draw_hand_trackers(painter, w, h)

        # Foot trackers
        if self._show_trackers and self._pose_results and self._pose_results.pose_landmarks:
            self._draw_foot_trackers(painter, w, h)

        # Detecting indicator
        self._draw_detecting(painter)

        painter.end()

    def _draw_drums(self, painter, w, h):
        now = time.time()
        for drum in self._drum_kit:
            cx = int(drum["pos"][0] * w)
            cy = int(drum["pos"][1] * h)
            rx = int(drum["axes"][0] * w)
            ry = int(drum["axes"][1] * h)

            is_hit = (now - drum["last_hit"]) < 0.15
            is_dragging = (self._dragging_drum and drum["id"] == self._dragging_drum["id"])

            # --- Color scheme (green active, like keyboard) ---
            accent = QColor(COL_KEY_ACTIVE)
            if is_hit:
                fill = QColor(accent)
                fill.setAlpha(70)
                border_col = QColor(accent)
                border_col.setAlpha(220)
                border_w = 2.5
            elif is_dragging:
                fill = QColor(255, 165, 0, 50)
                border_col = QColor(255, 165, 0, 180)
                border_w = 2.0
            else:
                fill = QColor(255, 255, 255, 18)
                border_col = QColor(255, 255, 255, 70)
                border_w = 1.2

            painter.setPen(QPen(border_col, border_w))
            painter.setBrush(QBrush(fill))

            if drum["shape"] == "rect":
                painter.drawRoundedRect(cx - rx, cy - ry, rx * 2, ry * 2, 6, 6)
            else:
                painter.drawEllipse(cx - rx, cy - ry, rx * 2, ry * 2)

            # Hit flash glow
            if is_hit:
                glow = QRadialGradient(cx, cy, max(rx, ry))
                glow_col = QColor(accent)
                glow_col.setAlpha(50)
                glow.setColorAt(0.0, glow_col)
                glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(glow))
                if drum["shape"] == "rect":
                    painter.drawRoundedRect(cx - rx, cy - ry, rx * 2, ry * 2, 6, 6)
                else:
                    painter.drawEllipse(cx - rx, cy - ry, rx * 2, ry * 2)

            # Name label
            if self._show_names:
                f = QFont(FONT_FAMILY, max(8, min(11, rx // 4)))
                painter.setFont(f)
                painter.setPen(QColor(255, 255, 255, 160 if not is_hit else 240))
                fm = painter.fontMetrics()
                name = drum.get("name", drum.get("element_key", ""))
                tw = fm.horizontalAdvance(name)
                painter.drawText(cx - tw // 2, cy + fm.ascent() // 2, name)

    def _draw_hand_trackers(self, painter, w, h):
        connections = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (0, 9), (9, 10), (10, 11), (11, 12),
            (0, 13), (13, 14), (14, 15), (15, 16),
            (0, 17), (17, 18), (18, 19), (19, 20),
        ]
        for hand_lm in self._results.multi_hand_landmarks:
            lm = hand_lm.landmark
            painter.setPen(QPen(QColor(COL_ACCENT_GREEN), 1.5))
            for a, b in connections:
                x1, y1 = int(lm[a].x * w), int(lm[a].y * h)
                x2, y2 = int(lm[b].x * w), int(lm[b].y * h)
                painter.drawLine(x1, y1, x2, y2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(COL_ACCENT_GREEN)))
            for pt in lm:
                px, py = int(pt.x * w), int(pt.y * h)
                painter.drawEllipse(px - 3, py - 3, 6, 6)

    def _draw_foot_trackers(self, painter, w, h):
        lm = self._pose_results.pose_landmarks.landmark
        for idx in (31, 32):
            pt = lm[idx]
            px, py = int(pt.x * w), int(pt.y * h)
            painter.setPen(QPen(QColor(80, 170, 255, 200), 2))
            painter.setBrush(QBrush(QColor(80, 170, 255, 60)))
            painter.drawEllipse(px - 9, py - 9, 18, 18)

    def _draw_detecting(self, painter):
        if not self._detecting:
            return
        label = "DETECTANDO"
        f = QFont(FONT_FAMILY, FONT_SIZE_SM)
        f.setBold(True)
        painter.setFont(f)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label)
        dot_r, pad_l, dot_gap, pad_r = 10, 10, 8, 12
        card_w = pad_l + dot_r + dot_gap + tw + pad_r
        card_h = 28
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(COL_DETECTING_BG)))
        painter.drawRoundedRect(12, 12, card_w, card_h, 14, 14)
        painter.setBrush(QBrush(QColor(COL_DETECTING_DOT)))
        painter.drawEllipse(12 + pad_l, 12 + (card_h - dot_r) // 2, dot_r, dot_r)
        painter.setPen(QColor(COL_ACCENT_GREEN))
        painter.setFont(f)
        tx = 12 + pad_l + dot_r + dot_gap
        ty = 12 + card_h // 2 + fm.ascent() // 2 - 1
        painter.drawText(tx, ty, label)


# ═══════════════════════════════════════════════════════════════════════════
# Control Panel
# ═══════════════════════════════════════════════════════════════════════════

class DrumControlPanel(QWidget):
    """Right panel: kit selection, recording, toggles, sliders."""

    kit_changed = Signal(str)
    element_added = Signal(str)
    record_clicked = Signal()
    stop_clicked = Signal()
    playback_clicked = Signal()
    end_clicked = Signal()
    tracker_toggled = Signal(bool)
    scifi_toggled = Signal(bool)
    feet_toggled = Signal(bool)
    names_toggled = Signal(bool)
    reset_clicked = Signal()
    velocity_changed = Signal(float)
    tolerance_changed = Signal(float)

    def __init__(self, instrument_name="Classic", parent=None):
        super().__init__(parent)
        self.setObjectName("controlPanel")
        self.setMinimumWidth(PANEL_MIN_W)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._instrument_name = instrument_name
        self._session_start = time.time()
        self._is_recording = False

        self._init_ui()

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

    def set_instrument_name(self, name):
        self._instrument_name = name
        self._header_label.setText(f"Prática · Bateria — {name}")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        self._header_label = QLabel(f"Prática · {self._instrument_name}")
        self._header_label.setObjectName("headerLabel")
        header_row.addWidget(self._header_label)
        header_row.addStretch()

        end_btn = QPushButton("Encerrar")
        end_btn.setObjectName("endBtn")
        end_btn.clicked.connect(self.end_clicked.emit)
        header_row.addWidget(end_btn)
        layout.addLayout(header_row)

        # Timer
        self._timer_label = QLabel("00:00")
        self._timer_label.setObjectName("timerLabel")
        layout.addWidget(self._timer_label)
        tsub = QLabel("em sessão")
        tsub.setObjectName("timerSub")
        layout.addWidget(tsub)

        layout.addSpacing(8)

        # Kit selection (horizontal scrollable)
        self._add_section_title(layout, "Timbres")
        self._kit_btns = []
        kit_scroll = QScrollArea()
        kit_scroll.setObjectName("presetScroll")
        kit_scroll.setWidgetResizable(True)
        kit_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        kit_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        kit_scroll.setFixedHeight(44)
        kit_scroll.setStyleSheet("")  # use global QSS

        container = QWidget()
        container.setObjectName("presetContainer")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        for name in DRUMS_SWIPE_KITS:
            btn = QPushButton(name)
            btn.setObjectName("presetBtn")
            btn.setCheckable(True)
            btn.setChecked(name == self._instrument_name)
            btn.clicked.connect(lambda _, n=name: self._on_kit_btn(n))
            row.addWidget(btn, 1)
            self._kit_btns.append((name, btn))

        kit_scroll.setWidget(container)
        # Enable horizontal scroll with mouse wheel
        kit_scroll.wheelEvent = lambda e: kit_scroll.horizontalScrollBar().setValue(
            kit_scroll.horizontalScrollBar().value() - e.angleDelta().y()
        )
        layout.addWidget(kit_scroll)

        layout.addSpacing(4)

        # Kit parts — expandable groups (scrollable)
        self._add_section_title(layout, "Kit")
        kit_parts_scroll = QScrollArea()
        kit_parts_scroll.setWidgetResizable(True)
        kit_parts_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        kit_parts_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        kit_parts_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        kit_parts_inner = QWidget()
        kit_parts_inner.setObjectName("kitPartsInner")
        kit_parts_inner.setStyleSheet("QWidget#kitPartsInner { background: transparent; }")
        self._group_area = QVBoxLayout(kit_parts_inner)
        self._group_area.setContentsMargins(0, 0, 0, 0)
        self._group_area.setSpacing(4)
        self._group_widgets = []
        for group in KIT_GROUPS:
            gw = self._make_group_widget(group)
            self._group_area.addWidget(gw)
            self._group_widgets.append(gw)
        self._group_area.addStretch()

        kit_parts_scroll.setWidget(kit_parts_inner)
        layout.addWidget(kit_parts_scroll, 1)  # stretch factor 1 — takes remaining space

        layout.addSpacing(8)

        # Record / Playback
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

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

        # Configurações — 2x2 grid
        self._add_section_title(layout, "Configurações")

        cfg_grid = QGridLayout()
        cfg_grid.setSpacing(8)

        self._tracker_btn = QPushButton("Trackers: OFF")
        self._tracker_btn.setObjectName("trackerBtn")
        self._tracker_btn.setCheckable(True)
        self._tracker_btn.setChecked(False)
        self._tracker_btn.setFixedHeight(BTN_HEIGHT)
        self._tracker_btn.clicked.connect(self._on_tracker_toggle)
        cfg_grid.addWidget(self._tracker_btn, 0, 0)

        self._scifi_btn = QPushButton("Sci-Fi: ON")
        self._scifi_btn.setObjectName("trackerBtn")
        self._scifi_btn.setCheckable(True)
        self._scifi_btn.setChecked(True)
        self._scifi_btn.setFixedHeight(BTN_HEIGHT)
        self._scifi_btn.clicked.connect(self._on_scifi_toggle)
        cfg_grid.addWidget(self._scifi_btn, 0, 1)

        self._names_btn = QPushButton("Nomes: ON")
        self._names_btn.setObjectName("trackerBtn")
        self._names_btn.setCheckable(True)
        self._names_btn.setChecked(True)
        self._names_btn.setFixedHeight(BTN_HEIGHT)
        self._names_btn.clicked.connect(self._on_names_toggle)
        cfg_grid.addWidget(self._names_btn, 1, 0)

        self._feet_btn = QPushButton("Pés (Pose): OFF")
        self._feet_btn.setObjectName("trackerBtn")
        self._feet_btn.setCheckable(True)
        self._feet_btn.setChecked(False)
        self._feet_btn.setFixedHeight(BTN_HEIGHT)
        self._feet_btn.clicked.connect(self._on_feet_toggle)
        cfg_grid.addWidget(self._feet_btn, 1, 1)

        layout.addLayout(cfg_grid)

        layout.addSpacing(4)

        # Velocity slider
        vel_init = int(TOUCH_VELOCITY * 1000)
        self._vel_slider, self._vel_label = self._add_slider(
            layout, "Sensibilidade", 1, 50, max(1, min(50, vel_init)),
            lambda v: self._on_slider("velocity", v)
        )

        # Tolerance slider
        tol_init = int(TOUCH_TOLERANCE * 100)
        self._tol_slider, self._tol_label = self._add_slider(
            layout, "Tolerância", 1, 20, max(1, min(20, tol_init)),
            lambda v: self._on_slider("tolerance", v)
        )

        # Reset positions button
        reset_btn = QPushButton("Resetar Posições")
        reset_btn.setObjectName("trackerBtn")
        reset_btn.setFixedHeight(BTN_HEIGHT)
        reset_btn.clicked.connect(self.reset_clicked.emit)
        layout.addWidget(reset_btn)

        # FPS
        self._fps_label = QLabel("FPS: --")
        self._fps_label.setObjectName("fpsLabel")
        self._fps_label.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}px; color: {COL_TEXT_SECONDARY}; font-family: {FONT_FAMILY};")
        layout.addWidget(self._fps_label)

    # --- Group widget builder ---

    def _make_group_widget(self, group):
        """Create an expandable group with a header button and hidden item buttons."""
        container = QWidget()
        vlayout = QVBoxLayout(container)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(2)

        header_btn = QPushButton(f"▸ {group['label']}")
        header_btn.setObjectName("trackerBtn")
        header_btn.setFixedHeight(36)
        vlayout.addWidget(header_btn)

        items_widget = QWidget()
        items_widget.setVisible(False)
        items_layout = QVBoxLayout(items_widget)
        items_layout.setContentsMargins(16, 0, 0, 0)
        items_layout.setSpacing(2)

        for ek in group["items"]:
            tmpl = DRUM_ELEMENT_LIBRARY.get(ek)
            if not tmpl:
                continue
            lbl = tmpl["name"]
            item_btn = QPushButton(lbl)
            item_btn.setObjectName("presetBtn")
            item_btn.setFixedHeight(32)
            item_btn.setProperty("element_key", ek)
            item_btn.clicked.connect(lambda _, k=ek: self._on_add_element(k))
            items_layout.addWidget(item_btn)

        vlayout.addWidget(items_widget)

        def toggle_expand():
            vis = not items_widget.isVisible()
            items_widget.setVisible(vis)
            header_btn.setText(f"{'▾' if vis else '▸'} {group['label']}")

        header_btn.clicked.connect(toggle_expand)
        return container

    def _on_add_element(self, element_key):
        self.element_added.emit(element_key)

    # --- Helpers ---

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

    # --- Callbacks ---

    def _on_kit_btn(self, name):
        for n, btn in self._kit_btns:
            btn.setChecked(n == name)
        self.kit_changed.emit(name)

    def _on_tracker_toggle(self):
        on = self._tracker_btn.isChecked()
        self._tracker_btn.setText(f"Trackers: {'ON' if on else 'OFF'}")
        self.tracker_toggled.emit(on)

    def _on_scifi_toggle(self):
        on = self._scifi_btn.isChecked()
        self._scifi_btn.setText(f"Sci-Fi: {'ON' if on else 'OFF'}")
        self.scifi_toggled.emit(on)

    def _on_names_toggle(self):
        on = self._names_btn.isChecked()
        self._names_btn.setText(f"Nomes: {'ON' if on else 'OFF'}")
        self.names_toggled.emit(on)

    def _on_feet_toggle(self):
        on = self._feet_btn.isChecked()
        self._feet_btn.setText(f"Pés (Pose): {'ON' if on else 'OFF'}")
        self.feet_toggled.emit(on)

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

    def _on_slider(self, name, value):
        if name == "velocity":
            real = value / 1000.0
            self._vel_label.setText(str(value))
            self.velocity_changed.emit(real)
        elif name == "tolerance":
            real = value / 100.0
            self._tol_label.setText(str(value))
            self.tolerance_changed.emit(real)

    def _update_clock(self):
        elapsed = int(time.time() - self._session_start)
        mins, secs = divmod(elapsed, 60)
        self._timer_label.setText(f"{mins:02d}:{secs:02d}")

    def update_fps(self, fps):
        self._fps_label.setText(f"FPS: {fps:.0f}")


# ═══════════════════════════════════════════════════════════════════════════
# Main Window
# ═══════════════════════════════════════════════════════════════════════════

class DrumsWindow(QMainWindow):
    """Fullscreen drums window with camera on left, controls on right."""

    def __init__(self, instrument_name="Classic", resolution_profile=None,
                 show_trackers=False, drum_model="default", drums_elements=None,
                 hand_model_complexity=1, pose_model_complexity=0,
                 user_tolerance=None, touch_velocity=None, rec_options=None,
                 lighting_service: IdleLightingService | None = None):
        super().__init__()
        self.setWindowTitle("Talking Hands — Bateria")
        self.setStyleSheet(build_global_qss())

        self._instrument_name = instrument_name
        self._drum_model = (drum_model or "default").strip().lower()
        self._use_feet = self._drum_model == "complete"
        self._show_trackers = show_trackers
        self._lighting_service = lighting_service

        # Audio
        self._audio_queue = queue.Queue()
        self._fs = None
        self._drum_sfid = -1
        self._recorder = MidiRecorder()
        if rec_options:
            self._recorder.set_options(rec_options)
        self._init_audio()

        # Apply note profile
        apply_drum_note_profile(instrument_name)

        # Build drum kit
        self._drum_kit = build_drum_kit(
            self._drum_model, drums_elements, instrument_name)

        # Tune thresholds
        self._touch_velocity = touch_velocity if touch_velocity else TOUCH_VELOCITY
        self._touch_tolerance = user_tolerance if user_tolerance else TOUCH_TOLERANCE

        # Hands + feet state
        self._hands_state = {
            side: {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}
            for side in ("Left", "Right")
        }
        self._feet_state = {
            side: {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}
            for side in ("LeftFoot", "RightFoot")
        }

        # Swipe state
        self._swipe_kit_idx = DRUMS_SWIPE_KITS.index(instrument_name) \
            if instrument_name in DRUMS_SWIPE_KITS else 0
        self._swipe_state = {"Right": {"ox": None, "ot": None}, "Left": {"ox": None, "ot": None}}
        self._last_swipe_ts = 0.0

        # Resolution
        if resolution_profile:
            dw = int(resolution_profile["display_width"])
            dh = int(resolution_profile["display_height"])
            self._target_fps = int(resolution_profile["fps"])
        else:
            dw, dh = 1280, 720
            self._target_fps = 60

        dw, dh, _, _, _ = fit_resolution_to_screen(dw, dh)
        self._logical_w, self._logical_h = dw, dh

        # Camera
        self._cap = setup_video_capture(width=dw, height=dh, fps=self._target_fps)
        self._cam_thread = CameraThread(self._cap)

        # MediaPipe hands
        hand_complexity = max(0, min(1, int(hand_model_complexity)))
        self._hands_thread = MediaPipeHandsThread(
            mp.solutions.hands.Hands(
                max_num_hands=2, model_complexity=hand_complexity,
                min_detection_confidence=0.3, min_tracking_confidence=0.3,
            )
        )

        # MediaPipe pose (for feet)
        self._pose_thread = None
        if self._use_feet:
            self._start_pose_thread(pose_model_complexity)

        # Build UI
        self._build_ui()

        # Frame timer
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)
        self._frame_timer.start(1)

        # FPS tracking
        self._fps_count = 0
        self._fps_last = time.time()
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps)
        self._fps_timer.start(1000)

        # Audio thread
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

        # Select kit
        if instrument_name:
            self._select_kit(instrument_name)

    def _start_pose_thread(self, complexity=0):
        pc = max(0, min(2, int(complexity)))
        self._pose_thread = MediaPipePoseThread(
            mp.solutions.pose.Pose(
                model_complexity=pc,
                min_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            )
        )

    def _init_audio(self):
        self._fs, _ = init_fluidsynth(driver="dsound")
        if self._fs:
            self._drum_sfid = load_single_soundfont(self._fs, "drums", FIXED_SF2_PATH)
            if self._drum_sfid != -1:
                for i in range(POLYPHONY_CHANNELS):
                    self._fs.program_select(i, self._drum_sfid, 128, 0)

    def _select_kit(self, name):
        if self._drum_sfid == -1 or name not in settings.INSTRUMENTS:
            return
        _, bank, preset = settings.INSTRUMENTS[name]
        for i in range(POLYPHONY_CHANNELS):
            self._fs.program_select(i, self._drum_sfid, bank, preset)
        self._recorder.set_instrument(FIXED_SF2_PATH, bank, preset, is_drum=True, instrument_name=name)
        self._instrument_name = name
        self._panel.set_instrument_name(name)

    def _audio_loop(self):
        while True:
            item = self._audio_queue.get()
            if item is None:
                break
            note, velocity = item
            ch = np.random.randint(0, POLYPHONY_CHANNELS)
            self._fs.noteon(ch, note, velocity)
            self._recorder.record_note_on(note, velocity=velocity)

    def _trigger_lighting(self, target):
        if self._lighting_service is None:
            return
        try:
            self._lighting_service.controller.drum_hit(
                target.get("element_key") in CYMBAL_ELEMENTS,
                LIGHTING_FADEOUT_MS,
            )
        except Exception as exc:
            print(f"[lighting] drum hit failed: {exc}")

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

        # Camera widget
        self._camera_widget = DrumOverlayWidget()
        self._camera_widget.set_drum_kit(self._drum_kit)
        self._camera_widget.set_show_trackers(self._show_trackers)
        self._splitter.addWidget(self._camera_widget)

        # Panel
        self._panel = DrumControlPanel(instrument_name=self._instrument_name)
        self._panel.kit_changed.connect(self._on_kit_changed)
        self._panel.record_clicked.connect(self._on_record)
        self._panel.stop_clicked.connect(self._on_stop)
        self._panel.playback_clicked.connect(self._on_playback)
        self._panel.end_clicked.connect(self._on_end)
        self._panel.tracker_toggled.connect(self._on_tracker_toggled)
        self._panel.scifi_toggled.connect(self._on_scifi_toggled)
        self._panel.names_toggled.connect(self._on_names_toggled)
        self._panel.feet_toggled.connect(self._on_feet_toggled)
        self._panel.reset_clicked.connect(self._on_reset)
        self._panel.velocity_changed.connect(self._on_velocity_changed)
        self._panel.tolerance_changed.connect(self._on_tolerance_changed)
        self._panel.element_added.connect(self._on_element_added)
        self._splitter.addWidget(self._panel)

        # 50/50 default, camera min 50%
        total = self._logical_w
        cam_w = total // 2
        self._splitter.setSizes([cam_w, total - cam_w])
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, True)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)

        self._is_camera_fullscreen = False
        self._in_fullscreen_change = False
        self._saved_splitter_sizes = None

        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        main_layout.addWidget(self._splitter)

    # --- Frame tick ---

    def _on_frame_tick(self):
        frame, _ = self._cam_thread.get_latest()
        if frame is None:
            return

        self._fps_count += 1

        w_widget = self._camera_widget.width()
        h_widget = self._camera_widget.height()
        if w_widget < 1 or h_widget < 1:
            return

        # Resize and flip
        frame = cv2.resize(frame, (self._logical_w, self._logical_h))
        frame = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Center-crop to widget aspect ratio
        fh, fw = frame_rgb.shape[:2]
        widget_ar = w_widget / h_widget
        frame_ar = fw / fh
        if frame_ar > widget_ar:
            new_w = int(fh * widget_ar)
            x0 = (fw - new_w) // 2
            frame_rgb = np.ascontiguousarray(frame_rgb[:, x0:x0 + new_w])
        elif frame_ar < widget_ar:
            new_h = int(fw / widget_ar)
            y0 = (fh - new_h) // 2
            frame_rgb = np.ascontiguousarray(frame_rgb[y0:y0 + new_h, :])

        self._camera_widget.set_frame(frame_rgb)

        # MediaPipe
        from src.instruments.common import prepare_mediapipe_frame
        mp_frame = prepare_mediapipe_frame(frame_rgb, self._logical_w, self._logical_h)
        self._hands_thread.submit_frame(mp_frame)
        results = self._hands_thread.get_latest_result()
        self._camera_widget.set_results(results)

        if self._pose_thread:
            self._pose_thread.submit_frame(mp_frame)
            pose_results = self._pose_thread.get_latest_result()
            self._camera_widget.set_pose_results(pose_results)
        else:
            pose_results = None
            self._camera_widget.set_pose_results(None)

        # Process hands
        if results and results.multi_hand_landmarks:
            for idx, hand_lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                self._process_hand(lbl, hand_lm.landmark)

            # Swipe gesture
            self._process_swipe(results)

        # Process feet
        if pose_results and pose_results.pose_landmarks and self._use_feet:
            lm = pose_results.pose_landmarks.landmark
            self._process_foot("LeftFoot", lm[31])
            self._process_foot("RightFoot", lm[32])

        self._camera_widget.update()

    def _process_hand(self, label, lm):
        ref = lm[4]  # thumb tip
        rx, ry = ref.x, ref.y
        state = self._hands_state[label]
        dy = ry - state["prev_y"]

        hit_drum_id = None
        for d in self._drum_kit:
            if d.get("foot_only"):
                continue
            if check_collision(rx, ry, d):
                hit_drum_id = d["id"]
                break

        if hit_drum_id is None or dy < -VELOCITY_THRESHOLD:
            state["can_hit"] = True
        else:
            target = next((d for d in self._drum_kit if d["id"] == hit_drum_id), None)
            if target and ry < target["pos"][1] and dy < -VELOCITY_THRESHOLD:
                state["can_hit"] = True

        # Try hit
        if hit_drum_id is not None and state["can_hit"] and dy > VELOCITY_THRESHOLD:
            moved = True
            if state["last_hit_pos"] and state["last_hit_drum"] == hit_drum_id:
                lx, ly = state["last_hit_pos"]
                moved = ((rx - lx) ** 2 + (ry - ly) ** 2) >= (MIN_REHIT_PIXELS / 1000) ** 2

            if moved:
                target = next((d for d in self._drum_kit if d["id"] == hit_drum_id), None)
                if target:
                    now = time.time()
                    if (now - target["last_hit"]) >= DRUM_MIN_HIT_INTERVAL:
                        vel = int(min(max((dy - self._touch_velocity) * 10000,
                                         DRUM_MIN_VELOCITY), 127))
                        self._trigger_lighting(target)
                        self._audio_queue.put((target["note"], vel))
                        target["last_hit"] = now
                        state["last_hit_pos"] = (rx, ry)
                        state["last_hit_drum"] = hit_drum_id
                        state["can_hit"] = False

        state["prev_y"] = ry

    def _process_foot(self, label, landmark):
        if landmark is None:
            return
        rx, ry = landmark.x, landmark.y
        state = self._feet_state[label]
        dy = ry - state["prev_y"]

        hit_drum_id = None
        for d in self._drum_kit:
            if not d.get("foot_only"):
                continue
            if check_collision(rx, ry, d):
                hit_drum_id = d["id"]
                break

        if hit_drum_id is None or dy < -VELOCITY_THRESHOLD:
            state["can_hit"] = True

        if hit_drum_id is not None and state["can_hit"] and dy > VELOCITY_THRESHOLD:
            moved = True
            if state["last_hit_pos"] and state["last_hit_drum"] == hit_drum_id:
                lx, ly = state["last_hit_pos"]
                moved = ((rx - lx) ** 2 + (ry - ly) ** 2) >= (FOOT_REHIT_PIXELS / 1000) ** 2
            if moved:
                target = next((d for d in self._drum_kit if d["id"] == hit_drum_id), None)
                if target:
                    now = time.time()
                    if (now - target["last_hit"]) >= DRUM_MIN_HIT_INTERVAL:
                        vel = int(min(max((dy - self._touch_velocity) * 10000,
                                         DRUM_MIN_VELOCITY), 127))
                        self._trigger_lighting(target)
                        self._audio_queue.put((target["note"], vel))
                        target["last_hit"] = now
                        state["last_hit_pos"] = (rx, ry)
                        state["last_hit_drum"] = hit_drum_id
                        state["can_hit"] = False

        state["prev_y"] = ry

    def _process_swipe(self, results):
        t_now = time.perf_counter()
        if (t_now - self._last_swipe_ts) <= SWIPE_COOLDOWN:
            self._swipe_state["Right"]["ox"] = None
            self._swipe_state["Left"]["ox"] = None
            return
        for si, hand_lm in enumerate(results.multi_hand_landmarks):
            lbl = results.multi_handedness[si].classification[0].label
            op = _swipe_openness(hand_lm.landmark)
            st = self._swipe_state[lbl]
            if op >= SWIPE_OPEN_MIN:
                xnow = hand_lm.landmark[0].x
                if st["ox"] is None:
                    st["ox"], st["ot"] = xnow, t_now
                else:
                    dx = xnow - st["ox"]
                    dt = t_now - st["ot"]
                    if dt <= SWIPE_MAX_TIME:
                        if lbl == "Right" and dx <= -SWIPE_DIST:
                            self._swipe_kit_idx = (self._swipe_kit_idx + 1) % len(DRUMS_SWIPE_KITS)
                            self._select_kit(DRUMS_SWIPE_KITS[self._swipe_kit_idx])
                            self._last_swipe_ts = t_now
                            st["ox"] = None
                        elif lbl == "Left" and dx >= SWIPE_DIST:
                            self._swipe_kit_idx = (self._swipe_kit_idx - 1) % len(DRUMS_SWIPE_KITS)
                            self._select_kit(DRUMS_SWIPE_KITS[self._swipe_kit_idx])
                            self._last_swipe_ts = t_now
                            st["ox"] = None
                    else:
                        st["ox"], st["ot"] = xnow, t_now
            else:
                st["ox"] = None

    # --- Slots ---

    def _on_kit_changed(self, name):
        apply_drum_note_profile(name)
        # Rebuild kit if instrument has preset elements
        elements = None
        replace = False
        if name in DRUMS_INSTRUMENT_ELEMENT_PRESETS:
            elements = DRUMS_INSTRUMENT_ELEMENT_PRESETS[name]
            if name in DRUMS_INSTRUMENT_REPLACE_BASE:
                replace = True
        model = "complete" if self._use_feet else "default"
        if replace or elements:
            self._drum_kit = build_drum_kit(model, elements, name)
            self._camera_widget.set_drum_kit(self._drum_kit)
        self._select_kit(name)
        self._swipe_kit_idx = DRUMS_SWIPE_KITS.index(name) if name in DRUMS_SWIPE_KITS else 0

    def _on_element_added(self, element_key):
        # Prevent duplicates
        existing_keys = {d["element_key"] for d in self._drum_kit}
        if element_key in existing_keys:
            return
        tmpl = DRUM_ELEMENT_LIBRARY.get(element_key)
        if not tmpl:
            return
        # Use _add_extras to find a valid slot
        new_kit = list(self._drum_kit)
        _add_extras(new_kit, [element_key])
        if len(new_kit) > len(self._drum_kit):
            # Finalize the new element
            new_el = new_kit[-1]
            new_el["id"] = max((d["id"] for d in self._drum_kit), default=-1) + 1
            new_el["last_hit"] = 0.0
            new_el.setdefault("foot_only", False)
            self._drum_kit.append(new_el)
            self._camera_widget.set_drum_kit(self._drum_kit)

    @Slot()
    def _on_record(self):
        self._recorder.start()

    @Slot()
    def _on_stop(self):
        ts = int(time.time())
        name = self._instrument_name.replace(" ", "_")
        self._recorder.stop(f"drums_{name}_{ts}.mid")

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

    @Slot(bool)
    def _on_names_toggled(self, enabled):
        self._camera_widget.set_show_names(enabled)

    @Slot(bool)
    def _on_feet_toggled(self, enabled):
        self._use_feet = enabled
        if enabled:
            if not self._pose_thread:
                self._start_pose_thread()
            # Rebuild kit in complete mode
            self._drum_kit = build_drum_kit("complete", None, self._instrument_name)
            self._camera_widget.set_drum_kit(self._drum_kit)
            # Reset feet state
            for s in self._feet_state.values():
                s.update({"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None})
        else:
            if self._pose_thread:
                self._pose_thread.close()
                self._pose_thread = None
            self._drum_kit = build_drum_kit("default", None, self._instrument_name)
            self._camera_widget.set_drum_kit(self._drum_kit)

    @Slot()
    def _on_reset(self):
        self._camera_widget.reset_positions()

    @Slot(float)
    def _on_velocity_changed(self, val):
        self._touch_velocity = val

    @Slot(float)
    def _on_tolerance_changed(self, val):
        self._touch_tolerance = val

    def _update_fps(self):
        now = time.time()
        elapsed = now - self._fps_last
        if elapsed > 0:
            fps = self._fps_count / elapsed
            self._panel.update_fps(fps)
        self._fps_count = 0
        self._fps_last = now

    # --- Splitter / fullscreen ---

    def _on_splitter_moved(self, pos, index):
        if self._in_fullscreen_change:
            return
        sizes = self._splitter.sizes()
        cam_w, panel_w = sizes[0], sizes[1]
        total = self._splitter.width()
        half = total // 2

        # Block dragging camera below 50%
        if cam_w < half:
            self._in_fullscreen_change = True
            self._splitter.setSizes([half, total - half])
            self._in_fullscreen_change = False
            return

        threshold = int(total * 0.82)
        if not self._is_camera_fullscreen and cam_w >= threshold:
            self._on_fullscreen(True)
        elif self._is_camera_fullscreen and panel_w > 60:
            self._is_camera_fullscreen = False
            self._saved_splitter_sizes = None

    def _on_fullscreen(self, enabled):
        self._in_fullscreen_change = True
        self._is_camera_fullscreen = enabled
        if enabled:
            self._saved_splitter_sizes = self._splitter.sizes()
            total = self._splitter.width()
            self._splitter.setSizes([total, 0])
        else:
            if self._saved_splitter_sizes:
                self._splitter.setSizes(self._saved_splitter_sizes)
        self._in_fullscreen_change = False
        QTimer.singleShot(50, self._camera_widget.update)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self._is_camera_fullscreen:
                self._on_fullscreen(False)
                return
        super().keyPressEvent(event)

    def showFullScreen(self):
        super().showFullScreen()
        # Re-apply 50/50 split after window reaches actual screen size
        QTimer.singleShot(100, self._apply_default_split)

    def _apply_default_split(self):
        total = self._splitter.width()
        if total > 0:
            self._in_fullscreen_change = True
            self._splitter.setSizes([total // 2, total - total // 2])
            self._in_fullscreen_change = False

    def closeEvent(self, event):
        self._frame_timer.stop()
        self._hands_thread.close()
        if self._pose_thread:
            self._pose_thread.close()
        self._cam_thread.stop()
        self._cap.release()
        self._audio_queue.put(None)
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def start_drums_ui(chosen_instrument="Classic", user_tolerance=None,
                   touch_velocity=None, rec_options=None,
                   resolution_profile=None, show_trackers=False,
                   drum_model="default", drums_elements=None,
                   hand_model_complexity=1, pose_model_complexity=0,
                   lighting_service: IdleLightingService | None = None):
    """Launch the PySide6 drums UI. Drop-in replacement for start_drums()."""
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_font()

    win = DrumsWindow(
        instrument_name=chosen_instrument,
        resolution_profile=resolution_profile,
        show_trackers=show_trackers,
        drum_model=drum_model,
        drums_elements=drums_elements,
        hand_model_complexity=hand_model_complexity,
        pose_model_complexity=pose_model_complexity,
        user_tolerance=user_tolerance,
        touch_velocity=touch_velocity,
        rec_options=rec_options,
        lighting_service=lighting_service,
    )
    win.showFullScreen()
    print(">>> MODO PRONTO")
    app.exec()
    print(">>> Bateria UI encerrada.")


if __name__ == "__main__":
    start_drums_ui("Classic")
