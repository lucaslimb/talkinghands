from pathlib import Path
import sys
import os
import cv2
import mediapipe as mp
import threading
import queue
import time
import ctypes
import pygame
import numpy as np

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.config import settings
from src.engines.recorder import MidiRecorder
from src.instruments.common import (
    init_fluidsynth, load_all_soundfonts, select_instrument,
    setup_video_capture, setup_pygame_with_scaling, fit_resolution_to_screen,
    draw_text, draw_recording_indicator, draw_playback_indicator,
    process_frame_to_pygame
)

# Import fluidsynth AFTER common.py setup has run
import fluidsynth

RELEASE_THRESHOLD = float(getattr(settings, 'KEYBOARD_RELEASE_THRESHOLD', 0.015))
MIN_NOTE_DURATION = float(getattr(settings, 'KEYBOARD_MIN_NOTE_DURATION', 0.1))
ARMED_TIMEOUT = float(getattr(settings, 'KEYBOARD_ARMED_TIMEOUT', 2.5))
SUSTAIN_DECAY = float(getattr(settings, 'KEYBOARD_SUSTAIN_DECAY', getattr(settings, 'SUSTAIN_DECAY', 0.8)))
TOUCH_TOLERANCE = float(getattr(settings, 'KEYBOARD_TOUCH_TOLERANCE', getattr(settings, 'TOUCH_TOLERANCE', 0.005)))
LIFT_THRESHOLD = float(getattr(settings, 'KEYBOARD_LIFT_THRESHOLD', getattr(settings, 'LIFT_THRESHOLD', 0.02)))
MAX_MISSING_TIME = float(getattr(settings, 'KEYBOARD_MAX_MISSING_TIME', 0.1))
DEFAULT_EXPRESSION = int(getattr(settings, 'KEYBOARD_DEFAULT_EXPRESSION', 127))
VOLUME_LEVEL_MIN = int(getattr(settings, 'KEYBOARD_VOLUME_LEVEL_MIN', -50))
VOLUME_LEVEL_MAX = int(getattr(settings, 'KEYBOARD_VOLUME_LEVEL_MAX', 50))
KEYBOARD_MAX_DIGITAL_GAIN = float(getattr(settings, 'KEYBOARD_MAX_DIGITAL_GAIN', 2.0))

# Barra de volume lateral (coordenadas normalizadas)
VOLUME_BAR_X_LEFT   = float(getattr(settings, 'KEYBOARD_VOLUME_BAR_X_LEFT',   0.944))
VOLUME_BAR_X_RIGHT  = float(getattr(settings, 'KEYBOARD_VOLUME_BAR_X_RIGHT',  0.979))
VOLUME_BAR_Y_TOP    = float(getattr(settings, 'KEYBOARD_VOLUME_BAR_Y_TOP',    0.15))
VOLUME_BAR_Y_BOTTOM = float(getattr(settings, 'KEYBOARD_VOLUME_BAR_Y_BOTTOM', 0.72))
# Gesto de índicador para controle de volume
INDEX_GRAB_X_MARGIN = float(getattr(settings, 'KEYBOARD_INDEX_GRAB_X_MARGIN', 0.03))
INDEX_GRAB_Y_MARGIN = float(getattr(settings, 'KEYBOARD_INDEX_GRAB_Y_MARGIN', 0.055))

DEFAULT_NUM_KEYS = int(getattr(settings, 'KEYBOARD_DEFAULT_NUM_KEYS', 30))
MIN_NUM_KEYS = int(getattr(settings, 'KEYBOARD_MIN_NUM_KEYS', 12))
MAX_NUM_KEYS = 72
NUM_KEYS = DEFAULT_NUM_KEYS
DEFAULT_TABLE_Y = float(getattr(settings, 'KEYBOARD_DEFAULT_TABLE_Y', 0.80))
MIN_TABLE_Y = float(getattr(settings, 'KEYBOARD_MIN_TABLE_Y', 0.45))
MAX_TABLE_Y = float(getattr(settings, 'KEYBOARD_MAX_TABLE_Y', 0.93))
TABLE_LINE_HITBOX_PX = 14
ACTIVE_FINGERS = [4, 8, 12, 16, 20]
show_menu = False

COLOR_TABLE_LINE = (0, 0, 0, 72)
COLOR_TABLE_FRONT = (30, 30, 30)
COLOR_KEY_DIVIDER = (100, 100, 100)
COLOR_HIT = (255, 255, 0)     # Amarelo (RGB)
COLOR_ARMED = (255, 165, 0)   # Laranja (RGB)
COLOR_HOLD = (0, 200, 0)      # Verde Escuro
COLOR_KEY_WHITE_BG = (0, 0, 0, 30)
COLOR_KEY_BLACK_BG = (0, 0, 0, 72)
BLACK_KEY_HEIGHT_RATIO = 0.62
BLACK_KEY_WIDTH_RATIO = 0.44

# ------------------------
# AUDIO SETUP
# ------------------------
audio_queue = queue.Queue()
loaded_sfids = {}
recorder = MidiRecorder()

fs, loaded_sfids = init_fluidsynth(driver="dsound")
if fs is None:
    print("ERRO CRÍTICO DE AUDIO: Falha ao inicializar FluidSynth")
    exit()

loaded_sfids = load_all_soundfonts(fs)

def select_instrument_by_name(name, channel=0):
    # Wrapper around common.select_instrument() for compatibility
    return select_instrument(fs, name, loaded_sfids, recorder, channel=channel, is_drum=False)

def audio_thread_target():
    """Consome a fila e toca notas. Encerra se receber None."""
    while True:
        item = audio_queue.get()
        if item is None:
            break
        action, note = item
        try:
            if action == "on":
                fs.noteon(0, note, 127)
                recorder.record_note_on(note) 
            elif action == "off":
                fs.noteoff(0, note)
                recorder.record_note_off(note)
        except Exception:
            pass


def clamp_midi(value):
    return max(0, min(127, int(value)))


def set_keyboard_expression(expression_value):
    safe_value = clamp_midi(expression_value)
    try:
        fs.cc(0, 11, safe_value)
        if hasattr(recorder, "record_cc"):
            recorder.record_cc(0, 11, safe_value)
    except Exception:
        pass
    return safe_value


def set_keyboard_digital_gain(gain_value):
    safe_gain = max(1.0, float(gain_value))

    try:
        if hasattr(fs, "set_gain"):
            fs.set_gain(float(safe_gain))
            return safe_gain
        if hasattr(fs, "gain") and callable(fs.gain):
            fs.gain(float(safe_gain))
            return safe_gain
        if hasattr(fs, "setting"):
            fs.setting("synth.gain", float(safe_gain))
            return safe_gain
    except Exception:
        pass

    return 1.0


def apply_volume_level(level):
    safe_level = max(VOLUME_LEVEL_MIN, min(VOLUME_LEVEL_MAX, int(level)))

    if safe_level <= 0:
        expression = int(round(((safe_level - VOLUME_LEVEL_MIN) / max(1, (0 - VOLUME_LEVEL_MIN))) * 127.0))
        set_keyboard_expression(expression)
        set_keyboard_digital_gain(1.0)
    else:
        set_keyboard_expression(127)
        gain_ratio = safe_level / float(max(1, VOLUME_LEVEL_MAX))
        gain_value = 1.0 + ((max(1.0, KEYBOARD_MAX_DIGITAL_GAIN) - 1.0) * gain_ratio)
        set_keyboard_digital_gain(gain_value)

    return safe_level


def vol_to_y_norm(level):
    """Converte nível de volume (-50..+50) em coordenada y normalizada na barra."""
    center = (VOLUME_BAR_Y_TOP + VOLUME_BAR_Y_BOTTOM) / 2.0
    half_range = (VOLUME_BAR_Y_BOTTOM - VOLUME_BAR_Y_TOP) / 2.0
    # +50 -> topo (y menor), -50 -> base (y maior)
    ratio = -float(level) / 50.0
    return center + ratio * half_range


def y_norm_to_vol(y_norm):
    """Converte coordenada y normalizada em nível de volume (-50..+50)."""
    center = (VOLUME_BAR_Y_TOP + VOLUME_BAR_Y_BOTTOM) / 2.0
    half_range = (VOLUME_BAR_Y_BOTTOM - VOLUME_BAR_Y_TOP) / 2.0
    if half_range == 0:
        return 0
    ratio = (y_norm - center) / half_range
    level = int(round(-ratio * 50.0))
    return max(VOLUME_LEVEL_MIN, min(VOLUME_LEVEL_MAX, level))


# ------------------------
# ESTADOS
# ------------------------
SCALE_INTERVALS = list(range(12))
BASE_NOTE = 48  # C3
BLACK_KEY_NOTE_CLASSES = {1, 3, 6, 8, 10}
WHITE_KEY_NOTE_CLASSES = {0, 2, 4, 5, 7, 9, 11}
WHITE_CLASS_TO_OFFSET = {0: 0.0, 2: 1.0, 4: 2.0, 5: 3.0, 7: 4.0, 9: 5.0, 11: 6.0}
BLACK_CLASS_TO_CENTER_OFFSET = {1: 0.5, 3: 1.5, 6: 3.5, 8: 4.5, 10: 5.5}

NOTE_LABELS_PT = {
    0: "Dó",
    1: "Dó#/Réb",
    2: "Ré",
    3: "Ré#/Mib",
    4: "Mi",
    5: "Fá",
    6: "Fá#/Solb",
    7: "Sol",
    8: "Sol#/Láb",
    9: "Lá",
    10: "Lá#/Sib",
    11: "Si",
}

NOTE_LABELS_EN = {
    0: "C",
    1: "C#/Db",
    2: "D",
    3: "D#/Eb",
    4: "E",
    5: "F",
    6: "F#/Gb",
    7: "G",
    8: "G#/Ab",
    9: "A",
    10: "A#/Bb",
    11: "B",
}


def get_note_label(note, key_width):
    midi_note = int(note)
    note_class = midi_note % 12
    octave = (midi_note // 12) - 1

    pt_name = NOTE_LABELS_PT.get(note_class, "")
    en_name = NOTE_LABELS_EN.get(note_class, "")

    if key_width < 56:
        primary_en = en_name.split('/')[0]
        return f"{primary_en}{octave}"

    if key_width < 92:
        primary_pt = pt_name.split('/')[0]
        primary_en = en_name.split('/')[0]
        return f"{primary_pt}{octave}-{primary_en}{octave}"

    return f"{pt_name}{octave} - {en_name}{octave}"


def is_black_key(midi_note):
    return (int(midi_note) % 12) in BLACK_KEY_NOTE_CLASSES


def _compute_raw_key_units(midi_note):
    note = int(midi_note)
    note_class = note % 12
    octave = note // 12

    if note_class in WHITE_KEY_NOTE_CLASSES:
        left = (octave * 7.0) + WHITE_CLASS_TO_OFFSET[note_class]
        right = left + 1.0
        return left, right, False

    center = (octave * 7.0) + BLACK_CLASS_TO_CENTER_OFFSET[note_class]
    half_width = BLACK_KEY_WIDTH_RATIO * 0.5
    return center - half_width, center + half_width, True


def apply_piano_geometry(keys):
    if not keys:
        return

    sorted_keys = sorted(keys, key=lambda item: int(item["note"]))
    white_keys = [key for key in sorted_keys if not is_black_key(key["note"])]

    if not white_keys:
        n = len(sorted_keys)
        width = 1.0 / max(1, n)
        for idx, key in enumerate(sorted_keys):
            key["is_black"] = bool(is_black_key(key["note"]))
            key["x_start_norm"] = idx * width
            key["x_end_norm"] = min(1.0, (idx + 1) * width)
        return

    white_count = len(white_keys)
    white_width = 1.0 / max(1, white_count)

    for idx, key in enumerate(white_keys):
        key["is_black"] = False
        key["x_start_norm"] = idx * white_width
        key["x_end_norm"] = min(1.0, (idx + 1) * white_width)

    white_by_note = {int(key["note"]): key for key in white_keys}
    white_notes = sorted(white_by_note.keys())

    for key in sorted_keys:
        note = int(key["note"])
        if not is_black_key(note):
            continue

        key["is_black"] = True
        prev_candidates = [n for n in white_notes if n < note]
        next_candidates = [n for n in white_notes if n > note]

        prev_note = prev_candidates[-1] if prev_candidates else None
        next_note = next_candidates[0] if next_candidates else None

        if prev_note is not None and next_note is not None:
            prev_white = white_by_note[prev_note]
            next_white = white_by_note[next_note]
            center = (prev_white["x_end_norm"] + next_white["x_start_norm"]) * 0.5
        elif prev_note is not None:
            prev_white = white_by_note[prev_note]
            center = prev_white["x_end_norm"] - (white_width * 0.5)
        elif next_note is not None:
            next_white = white_by_note[next_note]
            center = next_white["x_start_norm"] + (white_width * 0.5)
        else:
            center = 0.5

        black_width = white_width * BLACK_KEY_WIDTH_RATIO
        key["x_start_norm"] = max(0.0, center - (black_width * 0.5))
        key["x_end_norm"] = min(1.0, center + (black_width * 0.5))


def get_key_index_from_x(x_norm):
    if not PIANO_KEYS:
        return 0

    x = max(0.0, min(1.0, float(x_norm)))

    for idx, key in enumerate(PIANO_KEYS):
        if key.get("is_black") and key["x_start_norm"] <= x <= key["x_end_norm"]:
            return idx

    for idx, key in enumerate(PIANO_KEYS):
        if (not key.get("is_black")) and key["x_start_norm"] <= x <= key["x_end_norm"]:
            return idx

    best_idx = 0
    best_dist = float("inf")
    for idx, key in enumerate(PIANO_KEYS):
        center = (key["x_start_norm"] + key["x_end_norm"]) * 0.5
        dist = abs(center - x)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx
    return best_idx

def build_note_pool():
    pool = []
    octave = 0

    while True:
        octave_has_note = False
        for note_offset in SCALE_INTERVALS:
            note_value = BASE_NOTE + (octave * 12) + note_offset
            if note_value > 127:
                continue
            pool.append(note_value)
            octave_has_note = True

        if not octave_has_note:
            break
        octave += 1

    return sorted(set(pool))


NOTE_POOL = build_note_pool()
MAX_NUM_KEYS = len(NOTE_POOL)


def select_notes_for_key_count(num_keys):
    available = len(NOTE_POOL)
    if available == 0:
        return []

    if num_keys <= 1:
        return [NOTE_POOL[0]]

    if num_keys >= available:
        return NOTE_POOL.copy()

    return NOTE_POOL[:num_keys]


def build_piano_keys(num_keys):
    keys = []
    selected_notes = select_notes_for_key_count(num_keys)
    for note_val in selected_notes:
        keys.append({"note": note_val, "last_hit": 0, "is_active": False, "off_timer": 0, "is_black": is_black_key(note_val), "x_start_norm": 0.0, "x_end_norm": 1.0})
    apply_piano_geometry(keys)
    return keys


PIANO_KEYS = build_piano_keys(NUM_KEYS)


def stop_all_active_notes():
    for key in PIANO_KEYS:
        if key["is_active"]:
            audio_queue.put(("off", key["note"]))
            key["is_active"] = False
            key["off_timer"] = 0


def set_num_keys(new_num_keys):
    global NUM_KEYS, PIANO_KEYS
    safe_num = max(MIN_NUM_KEYS, min(MAX_NUM_KEYS, int(new_num_keys)))
    if safe_num == NUM_KEYS:
        return

    stop_all_active_notes()
    reset_hands_state()
    NUM_KEYS = safe_num
    PIANO_KEYS = build_piano_keys(NUM_KEYS)


def clamp_table_y(y_value):
    return max(MIN_TABLE_Y, min(MAX_TABLE_Y, float(y_value)))


def keys_from_table_y(table_y):
    default_height = max(0.05, 1.0 - DEFAULT_TABLE_Y)
    current_height = max(0.05, 1.0 - table_y)
    estimate = round(DEFAULT_NUM_KEYS * (default_height / current_height))
    return max(MIN_NUM_KEYS, min(MAX_NUM_KEYS, int(estimate)))

global_state = {
    "table_y": DEFAULT_TABLE_Y,
    "calibrated": False,
    "resize_mode": None,
    "resize_active": False,
    "resize_start_mouse_y": 0,
    "resize_start_table_y": DEFAULT_TABLE_Y,
    "calibration_pending": False,
    "calibration_end_ts": 0.0,
    "last_lowest_finger_y": None,
}

hands_state = {
    "Left":  {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}},
    "Right": {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}}
}

# Aqui inicializamos os estados para cada dedo ativo
def reset_hands_state():
    for hand in ["Left", "Right"]:
        for fid in ACTIVE_FINGERS:
            hands_state[hand]["finger_status"][fid] = "IDLE"
            hands_state[hand]["finger_timers"][fid] = 0.0
            hands_state[hand]["active_notes"][fid] = None
            hands_state[hand]["last_seen"][fid] = 0.0

# Aqui verificamos se as notas ativas ainda estão sendo tocadas ou se devem ser desligadas por falta de contato ou por sustain expirado
def check_active_keys_integrity():
    current_time = time.time()
    notes_currently_touched = set()

    for hand in ["Left", "Right"]:
        state = hands_state[hand]
        for fid in ACTIVE_FINGERS:
            if state["finger_status"][fid] == "TOUCHING":
                note = state["active_notes"][fid]
                if note is not None:
                    notes_currently_touched.add(note)

    for key in PIANO_KEYS:
        if key["is_active"]:
            if key["note"] in notes_currently_touched:
                key["off_timer"] = 0
            else:
                if key["off_timer"] == 0:
                    key["off_timer"] = current_time
                elif (current_time - key["off_timer"]) > SUSTAIN_DECAY:
                    audio_queue.put(("off", key["note"]))
                    key["is_active"] = False
                    key["off_timer"] = 0

# Aqui processamos cada dedo, verificando seu status atual e decidindo se deve armar para toque, iniciar um toque, mudar de nota ou liberar a nota
def processar_dedo(label, fid, y_current, x_current, table_y, cx, cy, screen, h_frame, show_trackers=False):
    state = hands_state[label]
    status = state["finger_status"][fid]
    last_action_time = state["finger_timers"][fid]
    current_time = time.time()
    state["last_seen"][fid] = current_time
    dist_above_table = table_y - y_current

    if status != "TOUCHING" and state["active_notes"][fid] is not None:
        note_to_kill = state["active_notes"][fid]
        audio_queue.put(("off", note_to_kill))
        for k in PIANO_KEYS:
            if k["note"] == note_to_kill:
                k["is_active"] = False
                break
        state["active_notes"][fid] = None

    if status == "IDLE":
        if dist_above_table > LIFT_THRESHOLD:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    elif status == "ARMED":
        if (current_time - last_action_time) > ARMED_TIMEOUT:
            state["finger_status"][fid] = "IDLE"
        elif y_current >= (table_y - TOUCH_TOLERANCE):
            key_idx = get_key_index_from_x(x_current)
            key_data = PIANO_KEYS[key_idx]
            note = key_data["note"]
            audio_queue.put(("on", note))
            state["active_notes"][fid] = note
            state["finger_status"][fid] = "TOUCHING"
            state["finger_timers"][fid] = current_time
            key_data["last_hit"] = current_time
            key_data["is_active"] = True
            
            if show_trackers:
                pygame.draw.circle(screen, COLOR_HIT, (cx, int(table_y * h_frame)), 15)

    elif status == "TOUCHING":
        active_note = state["active_notes"][fid]
        hit_time = state["finger_timers"][fid]
        if active_note is None:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time
            return

        current_key_idx = get_key_index_from_x(x_current)
        new_note = PIANO_KEYS[current_key_idx]["note"]

        if new_note != active_note:
            audio_queue.put(("off", active_note))
            for k in PIANO_KEYS:
                if k["note"] == active_note:
                    k["is_active"] = False
                    break
            audio_queue.put(("on", new_note))
            state["active_notes"][fid] = new_note
            state["finger_timers"][fid] = current_time
            PIANO_KEYS[current_key_idx]["last_hit"] = current_time
            PIANO_KEYS[current_key_idx]["is_active"] = True

        time_held = current_time - hit_time
        force_release = dist_above_table > (RELEASE_THRESHOLD * 2.0)
        normal_release = (dist_above_table > RELEASE_THRESHOLD) and (time_held > MIN_NOTE_DURATION)

        if force_release or normal_release:
            state["active_notes"][fid] = None
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    color = COLOR_ARMED if status == "ARMED" else (100,100,100)
    if status == "TOUCHING":
        color = COLOR_HOLD
    if show_trackers:
        pygame.draw.circle(screen, color, (cx, cy), 5)

# Aqui verificamos se algum dedo que deveria estar tocando ou armado desapareceu (perda de rastreamento) e desligamos a nota correspondente para evitar que fique presa
def check_lost_fingers():
    current_time = time.time()
    for hand in ["Left", "Right"]:
        state = hands_state[hand]
        for fid in ACTIVE_FINGERS:
            if state["active_notes"][fid] is not None:
                if (current_time - state["last_seen"][fid]) > MAX_MISSING_TIME:
                    note = state["active_notes"][fid]
                    audio_queue.put(("off", note))
                    for k in PIANO_KEYS:
                        if k["note"] == note:
                            k["is_active"] = False
                            break
                    state["active_notes"][fid] = None
                    state["finger_status"][fid] = "IDLE"


def update_index_volume_for_hand(label, landmarks, volume_state):
    """Controla o volume pela posição do indicador sobre a barra lateral.
    O indicador 'gruda' na risca quando está sobre ela e dentro da barra;
    solta imediatamente ao sair da faixa horizontal da barra."""
    index_tip = landmarks.landmark[8]
    ix = index_tip.x
    iy = index_tip.y

    in_bar_x = (VOLUME_BAR_X_LEFT - INDEX_GRAB_X_MARGIN) <= ix <= (VOLUME_BAR_X_RIGHT + INDEX_GRAB_X_MARGIN)

    # Se esta mão já está com grab ativo
    if volume_state["is_grabbed"] and volume_state["grab_hand"] == label:
        if in_bar_x:
            new_level = y_norm_to_vol(iy)
            if new_level != volume_state["level"]:
                volume_state["level"] = apply_volume_level(new_level)
            return True
        else:
            # Dedo saiu da barra - libera imediatamente
            volume_state["is_grabbed"] = False
            volume_state["grab_hand"] = None
            return False

    # Tenta iniciar grab: dedo dentro da barra perto da risca do nível atual
    if in_bar_x:
        current_vol_y = vol_to_y_norm(volume_state["level"])
        if abs(iy - current_vol_y) <= INDEX_GRAB_Y_MARGIN:
            volume_state["is_grabbed"] = True
            volume_state["grab_hand"] = label
            return True

    return False

# draw_text is imported from src.instruments.common


def draw_volume_bar(screen, w, h, font, volume_state):
    """Desenha a barra de volume vertical no lado direito da tela (sem borda)."""
    x1 = int(VOLUME_BAR_X_LEFT * w)
    x2 = int(VOLUME_BAR_X_RIGHT * w)
    y1 = int(VOLUME_BAR_Y_TOP * h)
    y2 = int(VOLUME_BAR_Y_BOTTOM * h)
    bar_w = max(1, x2 - x1)
    bar_h = max(1, y2 - y1)

    # Fundo muito transparente, sem borda
    bg = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 28))
    screen.blit(bg, (x1, y1))

    # Risca central (volume 0 = padrão do soundfont)
    zero_y = int(vol_to_y_norm(0) * h)
    pygame.draw.line(screen, (70, 70, 70), (x1, zero_y), (x2, zero_y), 1)

    # Risca do nível atual
    level = volume_state["level"]
    vol_y = int(vol_to_y_norm(level) * h)
    if level > 0:
        line_color = (60, 160, 60)
    elif level < 0:
        line_color = (160, 70, 70)
    else:
        line_color = (140, 140, 140)

    thickness = 3 if volume_state.get("is_grabbed") else 1
    pygame.draw.line(screen, line_color, (x1 - 2, vol_y), (x2 + 2, vol_y), thickness)

    # Label numérico próximo à risca
    label_txt = f"{level:+d}" if level != 0 else "0"
    txt_surf = font.render(label_txt, True, line_color)
    txt_y = vol_y - txt_surf.get_height() - 2 if vol_y > y1 + 20 else vol_y + 4
    screen.blit(txt_surf, (x1, txt_y))


# FPS Tracker
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

def draw_ui_fast_pygame(screen, table_y, w, h, font, show_note_names=False, names_font=None, volume_state=None):
    table_px = int(table_y * h)
    total_h = h - table_px
    black_h = int(total_h * BLACK_KEY_HEIGHT_RATIO)
    
    pygame.draw.line(screen, COLOR_TABLE_LINE, (0, table_px), (w, table_px), 2)
    
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    
    white_keys = [key for key in PIANO_KEYS if not key.get("is_black")]
    black_keys = [key for key in PIANO_KEYS if key.get("is_black")]

    for key in white_keys:
        x1 = int(key["x_start_norm"] * w)
        x2 = int(key["x_end_norm"] * w)
        key_w = max(1, x2 - x1)

        pygame.draw.rect(overlay, COLOR_KEY_WHITE_BG, (x1, table_px, key_w, total_h))
        pygame.draw.line(screen, COLOR_KEY_DIVIDER, (x1, table_px), (x1, h), 1)

        if key["is_active"] or (time.time() - key["last_hit"]) < 0.15:
            pygame.draw.rect(overlay, (*COLOR_HIT, 76), (x1, table_px, key_w, total_h))

        if show_note_names:
            draw_font = names_font if names_font is not None else font
            label = get_note_label(key["note"], key_w)
            if label:
                text_surface = draw_font.render(label, True, (245, 245, 245))
                text_x = x1 + max(2, int((key_w - text_surface.get_width()) / 2))
                text_y = table_px + 8
                shadow_surface = draw_font.render(label, True, (20, 20, 20))
                screen.blit(shadow_surface, (text_x + 1, text_y + 1))
                screen.blit(text_surface, (text_x, text_y))

    if white_keys:
        last_white_x = int(white_keys[-1]["x_end_norm"] * w)
        pygame.draw.line(screen, COLOR_KEY_DIVIDER, (last_white_x, table_px), (last_white_x, h), 1)

    for key in black_keys:
        x1 = int(key["x_start_norm"] * w)
        x2 = int(key["x_end_norm"] * w)
        key_w = max(1, x2 - x1)

        pygame.draw.rect(overlay, COLOR_KEY_BLACK_BG, (x1, table_px, key_w, black_h))
        pygame.draw.rect(screen, (70, 70, 70), (x1, table_px, key_w, black_h), 1)

        if key["is_active"] or (time.time() - key["last_hit"]) < 0.15:
            pygame.draw.rect(overlay, (*COLOR_HIT, 90), (x1, table_px, key_w, black_h))

        if show_note_names:
            draw_font = names_font if names_font is not None else font
            label = get_note_label(key["note"], key_w)
            if label:
                text_surface = draw_font.render(label, True, (245, 245, 245))
                text_x = x1 + max(1, int((key_w - text_surface.get_width()) / 2))
                text_y = table_px + 6
                shadow_surface = draw_font.render(label, True, (20, 20, 20))
                screen.blit(shadow_surface, (text_x + 1, text_y + 1))
                screen.blit(text_surface, (text_x, text_y))
    
    screen.blit(overlay, (0,0))

    if recorder.is_recording:
        draw_recording_indicator(screen, w, h, font)
        
    if recorder.is_playing:
        draw_playback_indicator(screen, w, font)

    if show_menu:
        instructions = [
            "ESC   -> sair",
            "ESPACO -> calibrar (3s)",
            "Mouse Esq. na linha -> redimensionar + ajustar teclas",
            "Mouse Dir. na linha -> redimensionar altura",
            "Pinça (indicador+polegar) na barra direita -> volume +/-",
            "1 -> iniciar gravacao",
            "2 -> encerrar gravacao",
            "3 -> iniciar/interromper playback",
            "8 -> ocultar/mostrar nomes das notas",
            "9 -> ocultar/mostrar trackers",
            "0 -> ocultar/mostrar menu"
        ]
        y0 = 30
        for i, txt in enumerate(instructions):
            draw_text(screen, txt, (20, y0 + i * 25), font)
    
        fps_text = f"FPS: {fps_tracker.get_fps():.1f}"
        draw_text(screen, fps_text, (w - 120, 30), font)

    if global_state["calibration_pending"]:
        remaining = max(0.0, global_state["calibration_end_ts"] - time.time())
        draw_text(screen, f"Calibrando em {remaining:.1f}s", (w // 2 - 110, 30), font, (255, 220, 0))

    if global_state["resize_active"]:
        draw_text(screen, f"Teclas: {NUM_KEYS}", (w // 2 - 60, 58), font, (255, 220, 0))

    if volume_state is not None:
        draw_volume_bar(screen, w, h, font, volume_state)


def draw_hand_trackers(results, w, h, screen):
    if not results or not results.multi_hand_landmarks:
        return

    for idx, lm in enumerate(results.multi_hand_landmarks):
        lbl = results.multi_handedness[idx].classification[0].label
        state = hands_state.get(lbl, {})
        finger_state = state.get("finger_status", {})

        for fid in ACTIVE_FINGERS:
            finger = lm.landmark[fid]
            cx, cy = int(finger.x * w), int(finger.y * h)
            status = finger_state.get(fid, "IDLE")
            color = COLOR_ARMED if status == "ARMED" else (120, 120, 120)
            if status == "TOUCHING":
                color = COLOR_HOLD
            pygame.draw.circle(screen, color, (cx, cy), 5)

# ------------------------
# START
# ------------------------
def start_piano(chosen_instrument, user_sustain=None, lift_threshold=None, touch_tolerance=None, rec_options=None, resolution_profile=None, show_trackers=False, hand_model_complexity=1):

    if user_sustain is not None and user_sustain > 0:
        global SUSTAIN_DECAY
        SUSTAIN_DECAY = user_sustain

    if lift_threshold is not None and lift_threshold > 0:
        global LIFT_THRESHOLD
        LIFT_THRESHOLD = lift_threshold

    if touch_tolerance is not None and touch_tolerance > 0:
        global TOUCH_TOLERANCE
        TOUCH_TOLERANCE = touch_tolerance

    global show_menu
    tracker_visible = bool(show_trackers)
    names_visible = False

    if rec_options:
        recorder.set_options(rec_options)

    select_instrument_by_name(chosen_instrument)
    set_keyboard_expression(DEFAULT_EXPRESSION)
    set_keyboard_digital_gain(1.0)
    current_level = apply_volume_level(0)

    audio_t = threading.Thread(target=audio_thread_target, daemon=True)
    audio_t.start()
    
    reset_hands_state()

    model_complexity = max(0, min(1, int(hand_model_complexity)))
    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=model_complexity,
                                     min_detection_confidence=0.3, min_tracking_confidence=0.3)
    
    if resolution_profile:
        DISPLAY_W = int(resolution_profile["display_width"])
        DISPLAY_H = int(resolution_profile["display_height"])
        TARGET_FPS = int(resolution_profile["fps"])
    else:
        DISPLAY_W, DISPLAY_H = 1920, 1080
        TARGET_FPS = 30

    DISPLAY_W, DISPLAY_H, adjusted, screen_w, screen_h = fit_resolution_to_screen(DISPLAY_W, DISPLAY_H)
    if adjusted:
        print(f">>> Resolução ajustada para caber na tela: {DISPLAY_W}x{DISPLAY_H} (monitor {screen_w}x{screen_h})")

    LOGICAL_W, LOGICAL_H = DISPLAY_W, DISPLAY_H

    # Câmera Setup - Quality
    # LOGICAL_W, LOGICAL_H = 854, 480
    # DISPLAY_W, DISPLAY_H = 1920, 1080
    
    cap = setup_video_capture(width=LOGICAL_W, height=LOGICAL_H, fps=TARGET_FPS)
    
    window_display, main_surface, main_font = setup_pygame_with_scaling(
        logical_width=LOGICAL_W, logical_height=LOGICAL_H,
        display_width=DISPLAY_W, display_height=DISPLAY_H,
        title="Talking Hands - Teclado"
    )
    names_font = pygame.font.SysFont("Arial", 12, bold=False)
    volume_state = {
        "is_grabbed": False,
        "grab_hand": None,
        "level": current_level,
        "display_until": 0.0,
    }

    print(">>> TECLADO INICIADO (Pygame)")
    running = True

    try:
        while running:
            # 1. EVENTOS PYGAME
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    table_px = int(global_state["table_y"] * LOGICAL_H)
                    mx, my = event.pos
                    near_line = abs(my - table_px) <= TABLE_LINE_HITBOX_PX

                    if near_line and event.button in (1, 3):
                        global_state["resize_active"] = True
                        global_state["resize_mode"] = "left" if event.button == 1 else "right"
                        global_state["resize_start_mouse_y"] = my
                        global_state["resize_start_table_y"] = global_state["table_y"]

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button in (1, 3):
                        global_state["resize_active"] = False
                        global_state["resize_mode"] = None

                elif event.type == pygame.MOUSEMOTION:
                    if global_state["resize_active"] and global_state["resize_mode"] in ("left", "right"):
                        _, my = event.pos
                        delta_norm = (my - global_state["resize_start_mouse_y"]) / max(1, LOGICAL_H)
                        new_table_y = clamp_table_y(global_state["resize_start_table_y"] + delta_norm)
                        global_state["table_y"] = new_table_y

                        if global_state["resize_mode"] == "left":
                            set_num_keys(keys_from_table_y(new_table_y))

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        recorder.stop_playback()
                        running = False
                    elif event.key == pygame.K_SPACE:
                        global_state["calibration_pending"] = True
                        global_state["calibration_end_ts"] = time.time() + 3.0
                        global_state["last_lowest_finger_y"] = None
                    elif event.key == pygame.K_1:
                        recorder.start()
                    elif event.key == pygame.K_2:
                        timestamp = int(time.time())
                        filename = f"keyboard_{chosen_instrument.replace(' ', '_')}_{timestamp}.mid"
                        recorder.stop(filename)
                    elif event.key == pygame.K_3:
                        recorder.toggle_playback(fs)
                    elif event.key == pygame.K_4:
                        recorder.stop_playback()
                    elif event.key == pygame.K_9:
                        tracker_visible = not tracker_visible
                    elif event.key == pygame.K_8:
                        names_visible = not names_visible
                    elif event.key == pygame.K_0:
                        show_menu = not show_menu

            ret, frame = cap.read()
            if not ret:
                break

            fps_tracker.update()

            frame = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), 'RGB')
            main_surface.blit(frame_surface, (0, 0))

            results = hands.process(frame_rgb)

            current_lowest = None
            if results.multi_hand_landmarks:
                for idx, lm in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label

                    is_volume_control = update_index_volume_for_hand(lbl, lm, volume_state)

                    for fid in ACTIVE_FINGERS:
                        finger = lm.landmark[fid]
                        if current_lowest is None or finger.y > current_lowest:
                            current_lowest = finger.y

                        if is_volume_control:
                            continue

                        cx, cy = int(finger.x * LOGICAL_W), int(finger.y * LOGICAL_H)
                        processar_dedo(lbl, fid, finger.y, finger.x, global_state["table_y"], cx, cy, main_surface, LOGICAL_H, show_trackers=False)

                global_state["last_lowest_finger_y"] = current_lowest
            else:
                # Sem mãos detectadas: libera grab se ativo
                if volume_state["is_grabbed"]:
                    volume_state["is_grabbed"] = False
                    volume_state["grab_hand"] = None
                    volume_state["display_until"] = time.time() + 1.0

            draw_ui_fast_pygame(
                main_surface,
                global_state["table_y"],
                LOGICAL_W,
                LOGICAL_H,
                main_font,
                show_note_names=names_visible,
                names_font=names_font,
                volume_state=volume_state,
            )

            if tracker_visible:
                draw_hand_trackers(results, LOGICAL_W, LOGICAL_H, main_surface)

            if global_state["calibration_pending"] and time.time() >= global_state["calibration_end_ts"]:
                target_y = global_state["last_lowest_finger_y"]
                if target_y is not None:
                    stop_all_active_notes()
                    reset_hands_state()
                    global_state["table_y"] = max(0.0, min(0.995, float(target_y)))
                    set_num_keys(DEFAULT_NUM_KEYS)
                    global_state["calibrated"] = True
                global_state["calibration_pending"] = False

            check_lost_fingers()
            check_active_keys_integrity()
            
            window_display.blit(main_surface, (0, 0))
            
            pygame.display.flip()
            # pygame.time.Clock().tick(60) limitar FPS se necessário

    finally:
        print(">>> Encerrando notas ativas...")
        for key in PIANO_KEYS:
            if key["is_active"]:
                try:
                    fs.noteoff(0, key["note"])
                except:
                    pass
                key["is_active"] = False

        cap.release()
        pygame.quit()
        audio_queue.put(None)
        print(">>> Sessão encerrada.")

if __name__ == "__main__":
    default = next(iter(settings.INSTRUMENTS.keys()))
    start_piano(default)