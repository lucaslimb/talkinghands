import cv2
import mediapipe as mp
import threading
import queue
import time
import numpy as np
import sys
import os
import pygame
from pathlib import Path

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.engines.recorder import MidiRecorder
from src.instruments.common import (
    init_fluidsynth, load_single_soundfont, select_instrument,
    setup_video_capture, setup_pygame_with_scaling, fit_resolution_to_screen,
    draw_text, draw_recording_indicator, draw_playback_indicator,
    CameraThread, prepare_mediapipe_frame,
)

# Import fluidsynth AFTER common.py setup has run
import fluidsynth

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.append(root_dir)

from src.config import settings

VELOCITY_THRESHOLD = float(getattr(settings, 'DRUMS_VELOCITY_THRESHOLD', 0.002))
TOUCH_VELOCITY = float(getattr(settings, 'DRUMS_TOUCH_VELOCITY', getattr(settings, 'TOUCH_VELOCITY', 0.012)))
TOUCH_TOLERANCE = float(getattr(settings, 'DRUMS_TOUCH_TOLERANCE', 0.01))
ELLIPSE_THRESHOLD = 1.0 - TOUCH_TOLERANCE 
DRUM_MIN_VELOCITY = int(getattr(settings, 'DRUMS_MIN_VELOCITY', 50))
MIN_REHIT_PIXELS = int(getattr(settings, 'DRUMS_MIN_REHIT_PIXELS', 32))
FOOT_REHIT_PIXELS = int(getattr(settings, 'DRUMS_FOOT_REHIT_PIXELS', 36))
DRUM_MIN_HIT_INTERVAL_SEC = float(getattr(settings, 'DRUMS_MIN_HIT_INTERVAL_SEC', 0.045))
DRUM_CUSTOM_RECT_THICKNESS = float(getattr(settings, 'DRUMS_CUSTOM_RECT_THICKNESS', 1.20))
DRUM_RESIZE_EDGE_TOLERANCE_PX = int(getattr(settings, 'DRUMS_RESIZE_EDGE_TOLERANCE_PX', 10))
DRUM_MIN_HALF_WIDTH_NORM = float(getattr(settings, 'DRUMS_MIN_HALF_WIDTH_NORM', 0.02))
DRUM_MIN_HALF_HEIGHT_NORM = float(getattr(settings, 'DRUMS_MIN_HALF_HEIGHT_NORM', 0.015))

COLOR_RED = (100, 100, 100)     # Cinza claro (mesma cor das teclas brancas do piano)
COLOR_HIT_FILL = (0, 0, 0)     # Preto (mesma cor de fundo das teclas pretas do piano)
COLOR_READY = (255, 255, 0)    # Amarelo
COLOR_IDLE = (100, 100, 100)   # Cinza
COLOR_TEXT = (255, 255, 255)   # Branco
COLOR_GREEN = (0, 255, 0)      # Verde

show_menu = False


class FPSTracker:
    def __init__(self, update_interval=10):
        self.frame_count = 0
        self.start_time = time.time()
        self.current_fps = 0.0
        self.update_interval = update_interval

    def update(self):
        self.frame_count += 1
        if self.frame_count % self.update_interval == 0:
            elapsed = time.time() - self.start_time
            self.current_fps = self.frame_count / elapsed if elapsed > 0 else 0

    def get_fps(self):
        return self.current_fps


fps_tracker = FPSTracker(update_interval=10)

# ------------------------
# MAPEAMENTO DA BATERIA
# ------------------------
DRUM_ELEMENT_LIBRARY = {
    "crash":   {"name": "CRASH",    "note": 49, "shape": "ellipse", "row": "top",    "size": 1.15, "ry_ratio": 0.34, "foot_only": False},
    "ride":    {"name": "RIDE",     "note": 51, "shape": "ellipse", "row": "top",    "size": 1.15, "ry_ratio": 0.34, "foot_only": False},
    "splash":  {"name": "SPLASH",   "note": 55, "shape": "ellipse", "row": "top",    "size": 0.85, "ry_ratio": 0.34, "foot_only": False},
    "china":   {"name": "CHINA",    "note": 52, "shape": "ellipse", "row": "top",    "size": 1.00, "ry_ratio": 0.34, "foot_only": False},
    "tom_hi":  {"name": "HI-TOM",   "note": 48, "shape": "ellipse", "row": "mid",    "size": 0.95, "ry_ratio": 0.42, "foot_only": False},
    "tom_mid": {"name": "MID-TOM",  "note": 47, "shape": "ellipse", "row": "mid",    "size": 0.95, "ry_ratio": 0.42, "foot_only": False},
    "tom_low": {"name": "LO-TOM",   "note": 45, "shape": "ellipse", "row": "mid",    "size": 1.00, "ry_ratio": 0.42, "foot_only": False},
    "hihat":   {"name": "HI-HAT",   "note": 42, "shape": "ellipse", "row": "bottom", "size": 1.00, "ry_ratio": 0.45, "foot_only": False},
    "open_hh": {"name": "OPEN-HH",  "note": 46, "shape": "ellipse", "row": "top",    "size": 0.95, "ry_ratio": 0.34, "foot_only": False},
    "snare":   {"name": "SNARE",    "note": 38, "shape": "ellipse", "row": "bottom", "size": 1.15, "ry_ratio": 0.45, "foot_only": False},
    "rimshot": {"name": "RIMSHOT",  "note": 37, "shape": "rect",    "row": "bottom", "size": 0.62, "ry_ratio": 0.28, "foot_only": False},
    "snare_alt": {"name": "SNARE-ALT","note": 40, "shape": "ellipse", "row": "bottom", "size": 1.00, "ry_ratio": 0.42, "foot_only": False},
    "floor":   {"name": "FLOOR",    "note": 41, "shape": "ellipse", "row": "bottom", "size": 1.05, "ry_ratio": 0.45, "foot_only": False},
    "kick":    {"name": "KICK",     "note": 36, "shape": "rect",    "row": "foot",   "size": 1.40, "ry_ratio": 0.16, "foot_only": False},
    "kick_alt": {"name": "KICK-ALT", "note": 35, "shape": "rect",    "row": "foot",   "size": 1.30, "ry_ratio": 0.16, "foot_only": False},
    "hh_pedal":{"name": "HH-PEDAL", "note": 44, "shape": "rect",    "row": "foot",   "size": 0.65, "ry_ratio": 0.22, "foot_only": True},
    "cowbell": {"name": "COWBELL",  "note": 56, "shape": "rect",    "row": "top",    "size": 0.60, "ry_ratio": 0.30, "foot_only": False},
    "clap":    {"name": "CLAP",     "note": 39, "shape": "rect",    "row": "bottom", "size": 0.70, "ry_ratio": 0.28, "foot_only": False},
    "tamb":    {"name": "TAMB",     "note": 54, "shape": "rect",    "row": "top",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "ride_bell": {"name": "RIDE-BELL","note": 53, "shape": "rect",    "row": "top",    "size": 0.62, "ry_ratio": 0.30, "foot_only": False},
    "crash2":  {"name": "CRASH 2",  "note": 57, "shape": "ellipse", "row": "top",    "size": 1.05, "ry_ratio": 0.34, "foot_only": False},
    "ride2":   {"name": "RIDE 2",   "note": 59, "shape": "ellipse", "row": "top",    "size": 1.05, "ry_ratio": 0.34, "foot_only": False},
    "vibra_slap": {"name": "VIBRA",  "note": 58, "shape": "rect",    "row": "mid",    "size": 0.55, "ry_ratio": 0.30, "foot_only": False},
    "shaker":  {"name": "SHAKER",   "note": 82, "shape": "rect",    "row": "top",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "cabasa":  {"name": "CABASA",   "note": 69, "shape": "rect",    "row": "mid",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "maracas": {"name": "MARACAS",  "note": 70, "shape": "rect",    "row": "mid",    "size": 0.55, "ry_ratio": 0.28, "foot_only": False},
    "guiro_s": {"name": "GUIRO-S",  "note": 73, "shape": "rect",    "row": "mid",    "size": 0.52, "ry_ratio": 0.28, "foot_only": False},
    "guiro_l": {"name": "GUIRO-L",  "note": 74, "shape": "rect",    "row": "mid",    "size": 0.52, "ry_ratio": 0.28, "foot_only": False},
    "agogo_hi": {"name": "AGOGO-H", "note": 67, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "agogo_lo": {"name": "AGOGO-L", "note": 68, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "clave":   {"name": "CLAVE",    "note": 75, "shape": "rect",    "row": "bottom", "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "wood_hi": {"name": "WOOD-HI",  "note": 76, "shape": "rect",    "row": "bottom", "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "wood_lo": {"name": "WOOD-LO",  "note": 77, "shape": "rect",    "row": "bottom", "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "tri_mute": {"name": "TRI-MUTE", "note": 80, "shape": "rect",    "row": "top",    "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "tri_open": {"name": "TRI-OPEN", "note": 81, "shape": "rect",    "row": "top",    "size": 0.50, "ry_ratio": 0.28, "foot_only": False},
    "bongo_hi": {"name": "BONGO-H",  "note": 60, "shape": "ellipse", "row": "mid",    "size": 0.62, "ry_ratio": 1.00, "foot_only": False},
    "bongo_mid": {"name": "BONGO-M", "note": 63, "shape": "ellipse", "row": "mid",    "size": 0.62, "ry_ratio": 1.00, "foot_only": False},
    "bongo_lo": {"name": "BONGO-L",  "note": 61, "shape": "ellipse", "row": "mid",    "size": 0.66, "ry_ratio": 1.00, "foot_only": False},
    "bongo_deep": {"name": "BONGO-D", "note": 64, "shape": "ellipse", "row": "mid",    "size": 0.70, "ry_ratio": 1.00, "foot_only": False},
    "conga_hi": {"name": "CONGA-H",  "note": 62, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "conga_mid": {"name": "CONGA-M", "note": 63, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "conga_lo": {"name": "CONGA-L",  "note": 64, "shape": "rect",    "row": "mid",    "size": 0.58, "ry_ratio": 0.30, "foot_only": False},
    "timbale_hi": {"name": "TIMB-H", "note": 65, "shape": "rect",    "row": "mid",    "size": 0.56, "ry_ratio": 0.30, "foot_only": False},
    "timbale_lo": {"name": "TIMB-L", "note": 66, "shape": "rect",    "row": "mid",    "size": 0.56, "ry_ratio": 0.30, "foot_only": False},
}

_NOTE_OVERRIDES = getattr(settings, "DRUMS_NOTE_OVERRIDES", {}) or {}
for _element_key, _note_value in _NOTE_OVERRIDES.items():
    if _element_key in DRUM_ELEMENT_LIBRARY:
        try:
            _note = int(_note_value)
            if 0 <= _note <= 127:
                DRUM_ELEMENT_LIBRARY[_element_key]["note"] = _note
        except Exception:
            pass

BASE_DRUM_NOTES = {key: int(cfg.get("note", 0)) for key, cfg in DRUM_ELEMENT_LIBRARY.items()}
DRUMS_INSTRUMENT_NOTE_VARIATIONS = getattr(settings, "DRUMS_INSTRUMENT_NOTE_VARIATIONS", {}) or {}
DRUMS_INSTRUMENT_ELEMENT_PRESETS = getattr(settings, "DRUMS_INSTRUMENT_ELEMENT_PRESETS", {}) or {}
DRUMS_INSTRUMENT_REPLACE_BASE = set(getattr(settings, "DRUMS_INSTRUMENT_REPLACE_BASE", []))


def apply_drum_note_profile(instrument_name=None):
    for key, note in BASE_DRUM_NOTES.items():
        if key in DRUM_ELEMENT_LIBRARY:
            DRUM_ELEMENT_LIBRARY[key]["note"] = note

    profile = DRUMS_INSTRUMENT_NOTE_VARIATIONS.get(instrument_name, {}) if instrument_name else {}
    applied_count = 0
    for key, note_value in profile.items():
        if key not in DRUM_ELEMENT_LIBRARY:
            continue
        try:
            note = int(note_value)
            if 0 <= note <= 127:
                DRUM_ELEMENT_LIBRARY[key]["note"] = note
                applied_count += 1
        except Exception:
            continue

    if instrument_name and profile:
        print(f">>> Perfil de notas aplicado: {instrument_name} ({applied_count} variações)")

FIXED_BASE_LAYOUT_DEFAULT = [
    {"element_key": "crash",  "pos": (0.20, 0.40), "axes": (0.13, 0.045)},
    {"element_key": "ride",   "pos": (0.80, 0.40), "axes": (0.13, 0.045)},
    {"element_key": "tom_hi", "pos": (0.38, 0.60), "axes": (0.10, 0.045)},
    {"element_key": "tom_low","pos": (0.62, 0.60), "axes": (0.10, 0.045)},
    {"element_key": "hihat",  "pos": (0.20, 0.85), "axes": (0.12, 0.055)},
    {"element_key": "snare",  "pos": (0.50, 0.80), "axes": (0.14, 0.060)},
    {"element_key": "floor",  "pos": (0.80, 0.85), "axes": (0.12, 0.055)},
    {"element_key": "kick",   "pos": (0.50, 0.96), "axes": (0.16, 0.025), "foot_only": False},
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

LATIN_REPLACEMENT_LAYOUT = [
    {"element_key": "bongo_hi",   "pos": (0.20, 0.40), "axes": (0.09, 0.09)},
    {"element_key": "bongo_mid",  "pos": (0.80, 0.40), "axes": (0.09, 0.09)},
    {"element_key": "bongo_lo",   "pos": (0.38, 0.60), "axes": (0.10, 0.10)},
    {"element_key": "bongo_deep", "pos": (0.62, 0.60), "axes": (0.11, 0.11)},
    {"element_key": "conga_mid",  "pos": (0.50, 0.80), "axes": (0.11, 0.07)},
    {"element_key": "maracas",    "pos": (0.20, 0.85), "axes": (0.10, 0.06)},
    {"element_key": "cabasa",     "pos": (0.80, 0.85), "axes": (0.10, 0.06)},
]

DEFAULT_DRUM_ELEMENTS = list(getattr(settings, "DRUMS_DEFAULT_ELEMENTS", ["crash", "ride", "tom_hi", "tom_low", "hihat", "snare", "floor", "kick"]))
COMPLETE_EXTRA_ELEMENTS = list(getattr(settings, "DRUMS_COMPLETE_EXTRA_ELEMENTS", ["hh_pedal"]))

DRUM_KIT = []
INITIAL_POSITIONS = {}
current_drum_model = "default"
current_drum_elements = []

def _clone_kit(source):
    return [dict(item) for item in source]

def _expand_elements(drum_model="default", drums_elements=None):
    if drums_elements:
        selected = [e for e in drums_elements if e in DRUM_ELEMENT_LIBRARY]
    else:
        selected = [e for e in DEFAULT_DRUM_ELEMENTS if e in DRUM_ELEMENT_LIBRARY]
        if str(drum_model).strip().lower() == "complete":
            selected.extend([e for e in COMPLETE_EXTRA_ELEMENTS if e in DRUM_ELEMENT_LIBRARY])

    dedup = []
    seen = set()
    for item in selected:
        if item not in seen:
            dedup.append(item)
            seen.add(item)

    if not dedup:
        dedup = ["snare", "kick"]
    return dedup


def _make_drum_from_entry(entry, complete_mode=False):
    key = entry["element_key"]
    template = DRUM_ELEMENT_LIBRARY[key]
    drum = dict(template)
    drum["element_key"] = key
    drum["pos"] = tuple(entry["pos"])
    drum["axes"] = tuple(entry["axes"])
    if "foot_only" in entry:
        drum["foot_only"] = bool(entry["foot_only"])
    elif key == "kick":
        drum["foot_only"] = bool(complete_mode)
    return drum


def _build_fixed_base_kit(drum_model="default"):
    complete_mode = str(drum_model).strip().lower() == "complete"
    source = FIXED_BASE_LAYOUT_COMPLETE if complete_mode else FIXED_BASE_LAYOUT_DEFAULT
    return [_make_drum_from_entry(entry, complete_mode=complete_mode) for entry in source]


def _build_layout_kit(layout_entries, selected_elements):
    selected_set = set(selected_elements or [])
    kit_data = []
    for entry in layout_entries:
        key = entry.get("element_key")
        if key not in DRUM_ELEMENT_LIBRARY:
            continue
        if selected_set and key not in selected_set:
            continue
        kit_data.append(_make_drum_from_entry(entry, complete_mode=False))
    return kit_data


def _drums_overlap(d1, d2, gap=0.008):
    x1, y1 = d1["pos"]
    x2, y2 = d2["pos"]
    rx1, ry1 = d1["axes"]
    rx2, ry2 = d2["axes"]
    return (abs(x1 - x2) < (rx1 + rx2 + gap)) and (abs(y1 - y2) < (ry1 + ry2 + gap))


def _fits_without_overlap(candidate, kit_data):
    for drum in kit_data:
        if _drums_overlap(candidate, drum):
            return False
    return True


def _shrink_row(kit_data, row_name, factor=0.92, min_rx=0.03):
    for drum in kit_data:
        if drum.get("row") != row_name:
            continue
        rx, ry = drum["axes"]
        new_rx = max(min_rx, rx * factor)
        scale = new_rx / rx if rx > 0 else 1.0
        drum["axes"] = (new_rx, ry * scale)


def _add_extra_elements(kit_data, extras_to_add):
    pending = list(extras_to_add)
    slot_usage = [False] * len(EXTRA_SLOTS)

    for extra_key in pending:
        template = DRUM_ELEMENT_LIBRARY.get(extra_key)
        if not template:
            continue

        preferred_row = template.get("row", "mid")
        ordered_slots = [
            (idx, slot) for idx, slot in enumerate(EXTRA_SLOTS)
            if not slot_usage[idx]
        ]
        ordered_slots.sort(key=lambda x: 0 if x[1]["row"] == preferred_row else 1)

        placed = False
        for idx, slot in ordered_slots:
            candidate = dict(template)
            candidate["element_key"] = extra_key
            candidate["pos"] = tuple(slot["pos"])

            rx = slot["base_rx"] * float(template.get("size", 1.0))
            ry = rx * float(template.get("ry_ratio", 0.35))
            if str(template.get("shape", "")).lower() == "rect":
                ry *= max(1.0, DRUM_CUSTOM_RECT_THICKNESS)
            candidate["axes"] = (rx, ry)

            if not _fits_without_overlap(candidate, kit_data):
                _shrink_row(kit_data, slot["row"], factor=0.92)
                if not _fits_without_overlap(candidate, kit_data):
                    continue

            slot_usage[idx] = True
            kit_data.append(candidate)
            placed = True
            break

        if not placed:
            print(f"AVISO: Sem espaço para elemento extra '{extra_key}'.")


def configure_drum_kit(drum_model="default", drums_elements=None, replace_base=False, instrument_name=None):
    global DRUM_KIT, INITIAL_POSITIONS, current_drum_model, current_drum_elements

    normalized_model = (drum_model or "default").strip().lower()
    if normalized_model not in ("default", "complete", "override"):
        normalized_model = "default"

    selected = _expand_elements(normalized_model, drums_elements)

    if replace_base:
        if instrument_name == "Latin":
            DRUM_KIT = _build_layout_kit(LATIN_REPLACEMENT_LAYOUT, selected)
            placed_keys = {d["element_key"] for d in DRUM_KIT}
            missing = [e for e in selected if e not in placed_keys]
            if missing:
                _add_extra_elements(DRUM_KIT, missing)
        else:
            DRUM_KIT = []
            if selected:
                _add_extra_elements(DRUM_KIT, selected)
    else:
        DRUM_KIT = _build_fixed_base_kit(normalized_model)
        base_keys = {d["element_key"] for d in DRUM_KIT}
        extras = [e for e in selected if e not in base_keys]
        if extras:
            _add_extra_elements(DRUM_KIT, extras)

    for idx, drum in enumerate(DRUM_KIT):
        drum["id"] = idx
        drum["last_hit"] = 0
        drum["color"] = COLOR_RED
        drum.setdefault("foot_only", False)

    INITIAL_POSITIONS = {d["id"]: d["pos"] for d in DRUM_KIT}
    current_drum_model = normalized_model
    current_drum_elements = [d["element_key"] for d in DRUM_KIT]


configure_drum_kit("default")

# ------------------------
# AUDIO SETUP
# ------------------------
audio_queue = queue.Queue()
fs = None
drum_sfid = -1 
POLYPHONY_CHANNELS = 16
recorder = MidiRecorder()

FIXED_SF2_PATH = settings.SF2_PATHS["drums"]

fs, _ = init_fluidsynth(driver="dsound")
if fs is not None:
    print(f">>> Carregando SoundFont Fixo: {FIXED_SF2_PATH}...")
    drum_sfid = load_single_soundfont(fs, "drums", FIXED_SF2_PATH)
    if drum_sfid != -1:
        print(f"Sucesso! ID do SF2: {drum_sfid}")
        for i in range(POLYPHONY_CHANNELS):
            fs.program_select(i, drum_sfid, 128, 0)
    else:
        print(f"ERRO CRÍTICO: Falha ao carregar o arquivo {FIXED_SF2_PATH}")
else:
    print(f"ERRO CRÍTICO: Falha ao inicializar FluidSynth")

def select_kit_by_name(name):
    if drum_sfid == -1: return False
    if name not in settings.INSTRUMENTS: return False
    _, bank, preset = settings.INSTRUMENTS[name]
    print(f">>> SELECIONANDO KIT: {name} | B: {bank} P: {preset}")
    
    for i in range(POLYPHONY_CHANNELS):
        fs.program_select(i, drum_sfid, bank, preset)
    recorder.set_instrument(FIXED_SF2_PATH, bank, preset, is_drum=True, instrument_name=name)

    return True

def audio_thread_target():
    channel = 0
    while True:
        item = audio_queue.get()
        if item is None:
            break

        note, velocity = item
        channel = np.random.randint(0, POLYPHONY_CHANNELS)
        fs.noteon(channel, note, velocity)
        recorder.record_note_on(note, velocity=velocity)

def is_mouse_over_drum(mx, my, drum, w, h):
    cx = drum["pos"][0] * w
    cy = drum["pos"][1] * h
    rx = drum["axes"][0] * w
    ry = drum["axes"][1] * h
    
    if drum["shape"] == "rect":
        return (cx - rx < mx < cx + rx) and (cy - ry < my < cy + ry)
    else:
        return ((mx - cx)**2 / rx**2) + ((my - cy)**2 / ry**2) <= 1.0


def remove_drum_at_mouse(mx, my, w, h):
    global DRUM_KIT, current_drum_elements

    for idx in range(len(DRUM_KIT) - 1, -1, -1):
        drum = DRUM_KIT[idx]
        if is_mouse_over_drum(mx, my, drum, w, h):
            removed = DRUM_KIT.pop(idx)
            current_drum_elements = [d["element_key"] for d in DRUM_KIT]
            print(f">>> Elemento removido: {removed.get('name', removed.get('element_key', '?'))}")
            return True
    return False


def _detect_resize_handle(mx, my, drum, w, h, tol_px=DRUM_RESIZE_EDGE_TOLERANCE_PX):
    cx = drum["pos"][0] * w
    cy = drum["pos"][1] * h
    rx = drum["axes"][0] * w
    ry = drum["axes"][1] * h

    left = cx - rx
    right = cx + rx
    top = cy - ry
    bottom = cy + ry

    if mx < left - tol_px or mx > right + tol_px or my < top - tol_px or my > bottom + tol_px:
        return None

    candidates = []
    if top <= my <= bottom:
        dl = abs(mx - left)
        dr = abs(mx - right)
        if dl <= tol_px:
            candidates.append((dl, "left"))
        if dr <= tol_px:
            candidates.append((dr, "right"))

    if left <= mx <= right:
        dt = abs(my - top)
        db = abs(my - bottom)
        if dt <= tol_px:
            candidates.append((dt, "top"))
        if db <= tol_px:
            candidates.append((db, "bottom"))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _apply_resize_from_handle(drum, handle, mx, my, w, h):
    cx, cy = drum["pos"]
    rx, ry = drum["axes"]

    left = cx - rx
    right = cx + rx
    top = cy - ry
    bottom = cy + ry

    norm_mx = mx / w
    norm_my = my / h

    min_rx = DRUM_MIN_HALF_WIDTH_NORM
    min_ry = DRUM_MIN_HALF_HEIGHT_NORM

    if handle == "left":
        new_left = max(0.0, min(norm_mx, right - 2.0 * min_rx))
        new_cx = (new_left + right) * 0.5
        new_rx = (right - new_left) * 0.5
        drum["pos"] = (new_cx, cy)
        drum["axes"] = (new_rx, ry)
    elif handle == "right":
        new_right = min(1.0, max(norm_mx, left + 2.0 * min_rx))
        new_cx = (left + new_right) * 0.5
        new_rx = (new_right - left) * 0.5
        drum["pos"] = (new_cx, cy)
        drum["axes"] = (new_rx, ry)
    elif handle == "top":
        new_top = max(0.0, min(norm_my, bottom - 2.0 * min_ry))
        new_cy = (new_top + bottom) * 0.5
        new_ry = (bottom - new_top) * 0.5
        drum["pos"] = (cx, new_cy)
        drum["axes"] = (rx, new_ry)
    elif handle == "bottom":
        new_bottom = min(1.0, max(norm_my, top + 2.0 * min_ry))
        new_cy = (top + new_bottom) * 0.5
        new_ry = (new_bottom - top) * 0.5
        drum["pos"] = (cx, new_cy)
        drum["axes"] = (rx, new_ry)

hands_state = {
    "Left":  {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None},
    "Right": {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}
}

feet_state = {
    "LeftFoot":  {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None},
    "RightFoot": {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}
}

def reset_hands_state():
    hands_state["Left"] = {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}
    hands_state["Right"] = {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}

def reset_feet_state():
    feet_state["LeftFoot"] = {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}
    feet_state["RightFoot"] = {"prev_y": 0.0, "can_hit": True, "last_hit_pos": None, "last_hit_drum": None}

def reset_drum_positions():
    for drum in DRUM_KIT:
        if drum["id"] in INITIAL_POSITIONS:
            drum["pos"] = INITIAL_POSITIONS[drum["id"]]
    print(">>> Posições resetadas.")

def check_collision(x, y, drum):
    h, k = drum["pos"]
    rx, ry = drum["axes"]
    
    if drum["shape"] == "rect":
        x_min, x_max = h - rx, h + rx
        y_min, y_max = k - ry, k + ry
        tol = TOUCH_TOLERANCE
        return (x_min + tol <= x <= x_max - tol) and (y_min + tol <= y <= y_max - tol)
    else:
        val = ((x - h)**2 / rx**2) + ((y - k)**2 / ry**2)
        return val <= ELLIPSE_THRESHOLD

def try_trigger_hit(state, hit_drum_id, dy, cursor_pos, min_rehit_pixels=MIN_REHIT_PIXELS):
    if hit_drum_id is None:
        return False

    can_hit = state["can_hit"]
    is_moving_down = dy > VELOCITY_THRESHOLD
    moved_enough_after_last_hit = True

    if state["last_hit_pos"] is not None and state["last_hit_drum"] == hit_drum_id:
        last_x, last_y = state["last_hit_pos"]
        dx_px = cursor_pos[0] - last_x
        dy_px = cursor_pos[1] - last_y
        moved_enough_after_last_hit = (dx_px * dx_px + dy_px * dy_px) >= (min_rehit_pixels * min_rehit_pixels)

    if can_hit and is_moving_down and moved_enough_after_last_hit:
        target_drum = next((d for d in DRUM_KIT if d["id"] == hit_drum_id), None)
        if target_drum:
            now = time.time()
            if (now - float(target_drum.get("last_hit", 0))) < DRUM_MIN_HIT_INTERVAL_SEC:
                return False
            velocity = int(min(max((dy - TOUCH_VELOCITY) * 10000, DRUM_MIN_VELOCITY), 127))
            audio_queue.put((target_drum["note"], velocity))
            target_drum["last_hit"] = now
            state["last_hit_pos"] = cursor_pos
            state["last_hit_drum"] = hit_drum_id
            state["can_hit"] = False
            return True
    return False

def process_hand(label, landmarks, w, h, screen, font, show_trackers=False):
    ref_point = landmarks[4] 
    ref_x, ref_y = ref_point.x, ref_point.y
    
    state = hands_state[label]
    prev_y = state["prev_y"]
    can_hit = state["can_hit"]
    
    dy = ref_y - prev_y
    
    hit_drum_id = None
    for drum in DRUM_KIT:
        if drum.get("foot_only", False):
            continue
        if check_collision(ref_x, ref_y, drum):
            hit_drum_id = drum["id"]
            break
    
    drum_center_y = 0
    if hit_drum_id is not None:
        target_drum = next((d for d in DRUM_KIT if d["id"] == hit_drum_id), None)
        if target_drum:
            drum_center_y = target_drum["pos"][1]
    
    if hit_drum_id is None or dy < -VELOCITY_THRESHOLD:
        can_hit = True
    else:
        is_upper_half = ref_y < drum_center_y
        is_moving_up = dy < -VELOCITY_THRESHOLD
        if is_upper_half and is_moving_up:
            can_hit = True

    # --- LÓGICA DE BATIDA ---
    cursor_pos = (int(ref_x * w), int(ref_y * h))
    radius = 10 
    
    cursor_color = COLOR_IDLE 

    if hit_drum_id is not None:
        if can_hit:
            cursor_color = COLOR_READY

        if try_trigger_hit(state, hit_drum_id, dy, cursor_pos, min_rehit_pixels=MIN_REHIT_PIXELS):
            can_hit = False
            cursor_color = COLOR_GREEN
            radius = 15

    state["prev_y"] = ref_y
    state["can_hit"] = can_hit

    if show_trackers:
        pygame.draw.circle(screen, cursor_color, cursor_pos, radius)
        pygame.draw.circle(screen, (255, 255, 255), cursor_pos, radius + 2, 2)

def process_foot(label, landmark, w, h, screen, show_trackers=False):
    if landmark is None:
        return

    ref_x, ref_y = landmark.x, landmark.y
    state = feet_state[label]
    prev_y = state["prev_y"]
    can_hit = state["can_hit"]
    dy = ref_y - prev_y

    hit_drum_id = None
    foot_targets = [d["id"] for d in DRUM_KIT if d.get("foot_only", False)]
    if not foot_targets:
        state["prev_y"] = ref_y
        return

    for drum_id in foot_targets:
        drum = next((d for d in DRUM_KIT if d["id"] == drum_id), None)
        if drum and check_collision(ref_x, ref_y, drum):
            hit_drum_id = drum_id
            break

    if hit_drum_id is None or dy < -VELOCITY_THRESHOLD:
        can_hit = True

    state["can_hit"] = can_hit
    cursor_pos = (int(ref_x * w), int(ref_y * h))
    cursor_color = (80, 170, 255)
    radius = 9

    if state["can_hit"]:
        cursor_color = (0, 230, 255)

    if try_trigger_hit(state, hit_drum_id, dy, cursor_pos, min_rehit_pixels=FOOT_REHIT_PIXELS):
        cursor_color = (0, 255, 0)
        radius = 13

    state["prev_y"] = ref_y

    if show_trackers:
        pygame.draw.circle(screen, cursor_color, cursor_pos, radius)
        pygame.draw.circle(screen, (255, 255, 255), cursor_pos, radius + 2, 2)

# draw_text is imported from src.instruments.common

def draw_drums_pygame(screen, w, h, font, dragging_drum=None, show_names=False, names_font=None):
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    
    for drum in DRUM_KIT:

        cx_px = int(drum["pos"][0] * w)
        cy_px = int(drum["pos"][1] * h)
        rx_px = int(drum["axes"][0] * w)
        ry_px = int(drum["axes"][1] * h)
        
        width = rx_px * 2
        height = ry_px * 2
        left = cx_px - rx_px
        top = cy_px - ry_px
        
        drum_rect = pygame.Rect(left, top, width, height)
        
        color = drum["color"]
        fill_alpha = 30  # Transparência leve (igual alpha das teclas brancas do piano)
        
        if (time.time() - drum["last_hit"]) < 0.15:
            fill_alpha = 72  # Alpha das teclas pretas do piano
            color = COLOR_HIT_FILL

        if dragging_drum and drum["id"] == dragging_drum["id"]:
            color = (255, 165, 0) # Laranja
            fill_alpha = 100
        
        color_with_alpha = (*color, fill_alpha)
        
        if drum["shape"] == "rect":
            if drum.get("element_key") == "kick":
                pygame.draw.rect(overlay, color, drum_rect, 2)
            else:
                pygame.draw.rect(overlay, color_with_alpha, drum_rect)
                pygame.draw.rect(overlay, color, drum_rect, 2)
        else:
            pygame.draw.ellipse(overlay, color_with_alpha, drum_rect)
            pygame.draw.ellipse(overlay, color, drum_rect, 2)
            
        if show_names:
            draw_font = names_font if names_font is not None else font
            name_surf = draw_font.render(drum["name"], True, (240, 240, 240))
            screen.blit(name_surf, (cx_px - name_surf.get_width() // 2, cy_px - name_surf.get_height() // 2))

    screen.blit(overlay, (0, 0))

    if recorder.is_recording:
        draw_recording_indicator(screen, w, h, font)
        
    if recorder.is_playing:
        draw_playback_indicator(screen, w, font)
        
    if show_menu:
        instructions = [
            "ESC   -> sair",
            "1 -> iniciar gravacao",
            "2 -> encerrar gravacao",
            "3 -> iniciar/interromper playback",
            "Mouse interno -> reposicionar elemento",
            "Mouse na borda -> redimensionar pela borda",
            "Mouse direito -> remover elemento",
            "5 -> resetar posicao da bateria",
            "8 -> ocultar/mostrar nomes",
            "9 -> ocultar/mostrar trackers",
            "0 -> ocultar/mostrar menu"
        ]
        y0 = 30
        for i, txt in enumerate(instructions):
            draw_text(screen, txt, (20, y0 + i * 25), font)

        fps_text = f"FPS: {fps_tracker.get_fps():.1f}"
        draw_text(screen, fps_text, (w - 120, 30), font)

 # Loop principal
def start_drums(chosen_instrument=None, user_tolerance=None, rec_options=None, touch_velocity=None, resolution_profile=None, show_trackers=False, drum_model="default", drums_elements=None, hand_model_complexity=1, pose_model_complexity=0):
    print(">>> INICIANDO BATERIA (Pygame)")
    tracker_visible = bool(show_trackers)
    requested_model = str(drum_model).strip().lower()
    use_feet_model = requested_model in ("complete", "override")
    apply_drum_note_profile(chosen_instrument)
    effective_elements = drums_elements
    replace_base = bool(requested_model == "override" and effective_elements is not None)

    if replace_base:
        print(f">>> Override ativo via CLI: {', '.join(effective_elements)}")

    if (not replace_base) and effective_elements is None and chosen_instrument in DRUMS_INSTRUMENT_ELEMENT_PRESETS:
        preset_elements = DRUMS_INSTRUMENT_ELEMENT_PRESETS.get(chosen_instrument, [])
        effective_elements = [e for e in preset_elements if e in DRUM_ELEMENT_LIBRARY]
        if effective_elements:
            print(f">>> Preset de elementos aplicado: {chosen_instrument} -> {', '.join(effective_elements)}")
        if chosen_instrument in DRUMS_INSTRUMENT_REPLACE_BASE:
            replace_base = True
            print(f">>> Preset substitui kit base: {chosen_instrument}")

    configure_drum_kit(
        requested_model,
        drums_elements=effective_elements,
        replace_base=replace_base,
        instrument_name=chosen_instrument,
    )
    print(f">>> Modelo de bateria: {current_drum_model}")
    print(f">>> Elementos: {', '.join(current_drum_elements)}")
    
    if user_tolerance:
        global ELLIPSE_THRESHOLD
        ELLIPSE_THRESHOLD = 1.0 - user_tolerance

    if touch_velocity is not None and touch_velocity > 0:
        global TOUCH_VELOCITY
        TOUCH_VELOCITY = touch_velocity
        print(f">>> Velocity configurado: {TOUCH_VELOCITY}")
    
    if chosen_instrument:
        success = select_kit_by_name(chosen_instrument)
        if not success: print("Usando kit padrão.")
    else:
        print("Usando kit padrão.")

    global show_menu

    if rec_options:
        recorder.set_options(rec_options)

    audio_t = threading.Thread(target=audio_thread_target, daemon=True)
    audio_t.start()
    
    reset_hands_state()
    if use_feet_model:
        reset_feet_state()

    # --- SETUP VÍDEO E PYGAME ---
    if resolution_profile:
        DISPLAY_W = int(resolution_profile["display_width"])
        DISPLAY_H = int(resolution_profile["display_height"])
        TARGET_FPS = int(resolution_profile["fps"])
    else:
        DISPLAY_W, DISPLAY_H = 1280, 720
        TARGET_FPS = 60

    DISPLAY_W, DISPLAY_H, adjusted, screen_w, screen_h = fit_resolution_to_screen(DISPLAY_W, DISPLAY_H)
    if adjusted:
        print(f">>> Resolução ajustada para caber na tela: {DISPLAY_W}x{DISPLAY_H} (monitor {screen_w}x{screen_h})")

    LOGICAL_W, LOGICAL_H = DISPLAY_W, DISPLAY_H

    cap = setup_video_capture(width=LOGICAL_W, height=LOGICAL_H, fps=TARGET_FPS)
    cam_thread = CameraThread(cap)

    window_display, main_surface, font = setup_pygame_with_scaling(
        logical_width=LOGICAL_W,
        logical_height=LOGICAL_H,
        display_width=DISPLAY_W,
        display_height=DISPLAY_H,
        title="Talking Hands - Bateria"
    )
    
    hand_complexity = max(0, min(1, int(hand_model_complexity)))
    pose_complexity = max(0, min(2, int(pose_model_complexity)))

    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=hand_complexity, min_detection_confidence=0.3, min_tracking_confidence=0.3)
    pose = None
    if use_feet_model:
        pose = mp.solutions.pose.Pose(model_complexity=pose_complexity, min_detection_confidence=0.3, min_tracking_confidence=0.3)
        
    dragging_drum = None
    resizing_drum = None
    resize_handle = None
    drag_offset = (0, 0)
    names_visible = False
    names_font = pygame.font.SysFont("Arial", 12, bold=False)

    running = True
    try:
        while running:
            # 1. EVENTOS PYGAME
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1: # Clique Esquerdo
                        mx, my = event.pos
                        for drum in DRUM_KIT:
                            handle = _detect_resize_handle(mx, my, drum, LOGICAL_W, LOGICAL_H)
                            if handle is not None:
                                resizing_drum = drum
                                resize_handle = handle
                                dragging_drum = None
                                break

                            if is_mouse_over_drum(mx, my, drum, LOGICAL_W, LOGICAL_H):
                                dragging_drum = drum
                                resizing_drum = None
                                resize_handle = None
                                norm_mx = mx / LOGICAL_W
                                norm_my = my / LOGICAL_H
                                drag_offset = (drum["pos"][0] - norm_mx, drum["pos"][1] - norm_my)
                                break
                    elif event.button == 3: # Clique Direito
                        mx, my = event.pos
                        removed = remove_drum_at_mouse(mx, my, LOGICAL_W, LOGICAL_H)
                        if removed:
                            dragging_drum = None
                            resizing_drum = None
                            resize_handle = None

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        dragging_drum = None
                        resizing_drum = None
                        resize_handle = None
                
                elif event.type == pygame.MOUSEMOTION:
                    if resizing_drum is not None and resize_handle is not None:
                        mx, my = event.pos
                        _apply_resize_from_handle(resizing_drum, resize_handle, mx, my, LOGICAL_W, LOGICAL_H)
                    elif dragging_drum:
                        mx, my = event.pos
                        norm_mx = mx / LOGICAL_W
                        norm_my = my / LOGICAL_H
                        
                        # Atualiza a posição baseada no mouse + offset inicial
                        new_x = norm_mx + drag_offset[0]
                        new_y = norm_my + drag_offset[1]
                        
                        new_x = max(0.05, min(new_x, 0.95))
                        new_y = max(0.05, min(new_y, 0.95))
                        
                        dragging_drum["pos"] = (new_x, new_y)

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        recorder.stop_playback()
                        running = False
                    elif event.key == pygame.K_1:
                        recorder.start()
                    elif event.key == pygame.K_2:
                        ts = int(time.time())
                        clean_name = chosen_instrument.replace(' ', '_') if chosen_instrument else "Drums"
                        recorder.stop(f"drums_{clean_name}_{ts}.mid")
                    elif event.key == pygame.K_3:
                        recorder.toggle_playback(fs)
                    elif event.key == pygame.K_5:
                        reset_drum_positions()
                    elif event.key == pygame.K_8:
                        names_visible = not names_visible
                    elif event.key == pygame.K_9:
                        tracker_visible = not tracker_visible
                    elif event.key == pygame.K_0:
                        show_menu = not show_menu
                    elif event.key == pygame.K_SPACE:
                        audio_queue.put((36, 127)) # 36 = Kick

            frame, grab_ts = cam_thread.get_latest()
            if frame is None:
                time.sleep(0.001)
                continue

            fps_tracker.update()
            
            frame = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), 'RGB')
            main_surface.blit(frame_surface, (0, 0))
            
            draw_drums_pygame(
                main_surface,
                LOGICAL_W,
                LOGICAL_H,
                font,
                dragging_drum,
                show_names=names_visible,
                names_font=names_font,
            )
            
            frame_mp = prepare_mediapipe_frame(frame_rgb, LOGICAL_W, LOGICAL_H)
            results = hands.process(frame_mp)
            pose_results = pose.process(frame_mp) if pose is not None else None
            
            if results.multi_hand_landmarks:
                for idx, landmarks in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label
                    process_hand(lbl, landmarks.landmark, LOGICAL_W, LOGICAL_H, main_surface, font, show_trackers=tracker_visible)

            if pose_results and pose_results.pose_landmarks:
                foot_lm = pose_results.pose_landmarks.landmark
                process_foot("LeftFoot", foot_lm[31], LOGICAL_W, LOGICAL_H, main_surface, show_trackers=tracker_visible)
                process_foot("RightFoot", foot_lm[32], LOGICAL_W, LOGICAL_H, main_surface, show_trackers=tracker_visible)

            window_display.blit(main_surface, (0, 0))
            
            pygame.display.flip()
                
    except Exception as e:
        print(f"Erro Runtime: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            hands.close()
            if pose is not None:
                pose.close()
        except Exception:
            pass
        cam_thread.stop()
        cap.release()
        pygame.quit()
        audio_queue.put(None)
        print(">>> Bateria Encerrada.")

if __name__ == "__main__":
    start_drums("Classic")