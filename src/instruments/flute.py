import cv2
import mediapipe as mp
import threading
import queue
import time
import math
import numpy as np
import sys
import os
import pygame
from pathlib import Path

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.config import settings
from src.engines.recorder import MidiRecorder
from src.instruments.common import (
    init_fluidsynth, load_single_soundfont, select_instrument,
    setup_video_capture, setup_pygame_with_scaling, fit_resolution_to_screen,
    draw_text, draw_recording_indicator, draw_playback_indicator
)

# Import fluidsynth AFTER common.py setup has run
import fluidsynth

NUM_HOLES = 7
HOLE_RADIUS = float(getattr(settings, 'FLUTE_HOLE_RADIUS', getattr(settings, 'HOLE_RADIUS', 0.019)))
HOLE_SPACING = float(getattr(settings, 'FLUTE_HOLE_SPACING', getattr(settings, 'HOLE_SPACING', 0.068)))

DEFAULT_FLUTE_X = float(getattr(settings, 'FLUTE_DEFAULT_X', 0.6))
DEFAULT_FLUTE_Y = float(getattr(settings, 'FLUTE_DEFAULT_Y', 0.25))

MOUTH_MIN_OPEN = float(getattr(settings, 'FLUTE_MOUTH_MIN_OPEN', 0.002))
MOUTH_PEAK_OPEN = float(getattr(settings, 'FLUTE_MOUTH_PEAK_OPEN', getattr(settings, 'MOUTH_PEAK_OPEN', 0.01)))
MOUTH_MAX_OPEN = float(getattr(settings, 'FLUTE_MOUTH_MAX_OPEN', getattr(settings, 'MOUTH_MAX_OPEN', 0.05)))
BLOW_KEY = 32

INVERT_BLOW_LOGIC = False
INVERT_ANGLE_LOGIC = False

MOUTH_SMOOTHING_FACTOR = float(getattr(settings, 'FLUTE_MOUTH_SMOOTHING_FACTOR', 0.3))
VELOCITY_CHANGE_THRESHOLD = int(getattr(settings, 'FLUTE_VELOCITY_CHANGE_THRESHOLD', 4))
MOUTH_FOLLOW_SENSITIVITY = float(getattr(settings, 'FLUTE_MOUTH_FOLLOW_SENSITIVITY', 0.22))
MOUTH_FOLLOW_OFFSET_Y = float(getattr(settings, 'FLUTE_MOUTH_FOLLOW_OFFSET_Y', 0.09))
MOUTH_ANGLE_SENSITIVITY = float(getattr(settings, 'FLUTE_MOUTH_ANGLE_SENSITIVITY', 1.0))
FLUTE_VERTICAL_BASE_ANGLE = math.pi * 0.5
MOUTH_CLOSE_STOP_THRESHOLD = float(getattr(settings, 'FLUTE_MOUTH_CLOSE_STOP_THRESHOLD', getattr(settings, 'MOUTH_CLOSE_STOP_THRESHOLD', 0.0006)))
MOUTH_PEAK_NEAR_CLOSE_FACTOR = float(getattr(settings, 'FLUTE_MOUTH_PEAK_NEAR_CLOSE_FACTOR', getattr(settings, 'MOUTH_PEAK_NEAR_CLOSE_FACTOR', 0.25)))

PLAYBACK_CHANNEL = 0
LIVE_CHANNEL = 1

COLOR_HOLE_OPEN = (150, 150, 150)
COLOR_HOLE_CLOSED = (0, 200, 0)
COLOR_FLUTE_BODY_EMPTY = (30, 30, 30) 
COLOR_BLOW_ACTIVE = (255, 255, 0)  # Amarelo (RGB)    
COLOR_LIP_POINT = (255, 0, 0)      # Vermelho (RGB)
COLOR_TEXT = (255, 255, 255)

BASE_NOTE = 60 # C4
SCALE_FLUTE = [0, 2, 4, 5, 7, 9, 11, 12] 

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


def get_midi_note_label(note):
    midi_note = int(note)
    note_class = midi_note % 12
    octave = (midi_note // 12) - 1
    pt_name = NOTE_LABELS_PT.get(note_class, "")
    en_name = NOTE_LABELS_EN.get(note_class, "")
    return f"{pt_name}{octave} - {en_name}{octave}"


def get_flute_note_for_first_open_index(first_open_index):
    scale_index = NUM_HOLES - int(first_open_index)
    scale_index = max(0, min(scale_index, len(SCALE_FLUTE) - 1))
    return BASE_NOTE + SCALE_FLUTE[scale_index]

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
audio_queue = queue.Queue()
loaded_sfids = {}
recorder = MidiRecorder()

fs, loaded_sfids = init_fluidsynth(driver="dsound")
if fs is not None:
    flute_sf2_items = [
        (sf_key, sf_path)
        for sf_key, sf_path in settings.SF2_PATHS.items()
        if str(sf_key).startswith("flute")
    ]
    if not flute_sf2_items:
        print("ERRO: Nenhum SF2 de flauta configurado em settings.SF2_PATHS.")
    for sf_key, sf_path in flute_sf2_items:
        sfid = load_single_soundfont(fs, sf_key, sf_path)
        if sfid != -1:
            loaded_sfids[sf_key] = sfid
        else:
            print(f"ERRO: SF2 de flauta não carregado para key '{sf_key}'.")
else:
    print(f"ERRO CRÍTICO DE AUDIO: Falha ao inicializar FluidSynth")

def select_instrument_by_name(name):
    if name not in settings.INSTRUMENTS: return
    
    sf_key, bank, preset = settings.INSTRUMENTS[name]
    target_sfid = loaded_sfids.get(sf_key)
    
    if target_sfid is not None:
        # Configura o instrumento no Canal de Playback (0)
        fs.program_select(PLAYBACK_CHANNEL, target_sfid, bank, preset)
        fs.cc(PLAYBACK_CHANNEL, 11, 127) # Garante volume no playback
        
        # [FIX] Configura o MESMO instrumento no Canal Ao Vivo (1)
        fs.program_select(LIVE_CHANNEL, target_sfid, bank, preset)
        fs.cc(LIVE_CHANNEL, 11, 127) # Reseta volume inicial
        
        sf_path = settings.SF2_PATHS.get(sf_key)
        recorder.set_instrument(sf_path, bank, preset, is_drum=False, instrument_name=name)
        print(f">>> FLUTE: {name} (B:{bank} P:{preset})")

def audio_thread():
    current_note = None
    is_playing = False

    while True:
        item = audio_queue.get()
        if item is None: break
        
        type_msg, val1, val2 = item
        
        if type_msg == "note_on":
            note = val1
            if current_note != note:
                if current_note is not None: 
                    fs.noteoff(LIVE_CHANNEL, current_note)
                    recorder.record_note_off(current_note)
                
                fs.noteon(LIVE_CHANNEL, note, 127) 
                recorder.record_note_on(note)
                current_note = note
                is_playing = True
            elif not is_playing:
                fs.noteon(LIVE_CHANNEL, note, 127)
                recorder.record_note_on(note)
                is_playing = True
        
        elif type_msg == "note_off":
            if current_note is not None:
                fs.noteoff(LIVE_CHANNEL, current_note)
                recorder.record_note_off(current_note)
                current_note = None
                is_playing = False
        
        elif type_msg == "cc":
            controller = val1
            value = val2
            
            fs.cc(LIVE_CHANNEL, controller, value)
            
            try:
                if hasattr(recorder, 'record_cc'):
                    recorder.record_cc(PLAYBACK_CHANNEL, controller, value)
            except:
                pass

threading.Thread(target=audio_thread, daemon=True).start()


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

class FluteHole:
    def __init__(self, index, x_rel, y_rel):
        self.index = index
        self.x_rel = x_rel 
        self.y_rel = y_rel
        self.is_covered = False

holes = []

def update_hole_positions(start_x, start_y):
    update_hole_positions_with_angle(start_x, start_y, 0.0)

def update_hole_positions_with_angle(start_x, start_y, angle_rad=0.0):
    holes.clear()
    for i in range(NUM_HOLES):
        offset = i * HOLE_SPACING
        x = start_x + math.cos(angle_rad) * offset
        y = start_y + math.sin(angle_rad) * offset
        h = FluteHole(i, x, y)
        holes.append(h)

def get_mouth_distance(face_landmarks):
    if not face_landmarks: return 0.0
    upper = face_landmarks.landmark[13]
    lower = face_landmarks.landmark[14]
    return abs(upper.y - lower.y)

def get_mouth_center(face_landmarks):
    if not face_landmarks:
        return None
    upper = face_landmarks.landmark[13]
    lower = face_landmarks.landmark[14]
    return ((upper.x + lower.x) * 0.5, (upper.y + lower.y) * 0.5)

def get_mouth_tilt_angle(face_landmarks):
    if not face_landmarks:
        return FLUTE_VERTICAL_BASE_ANGLE

    left_corner = face_landmarks.landmark[61]
    right_corner = face_landmarks.landmark[291]
    mouth_line_angle = math.atan2(
        (right_corner.y - left_corner.y),
        (right_corner.x - left_corner.x),
    )
    if INVERT_ANGLE_LOGIC:
        mouth_line_angle = -mouth_line_angle

    flute_angle = FLUTE_VERTICAL_BASE_ANGLE + (mouth_line_angle * MOUTH_ANGLE_SENSITIVITY)
    min_angle = FLUTE_VERTICAL_BASE_ANGLE - 1.2
    max_angle = FLUTE_VERTICAL_BASE_ANGLE + 1.2
    return max(min_angle, min(max_angle, flute_angle))

def update_flute_position_from_mouth(flute_x, flute_y, mouth_center, sensitivity):
    if mouth_center is None:
        return flute_x, flute_y

    sens = max(0.0, min(float(sensitivity), 1.0))
    target_x = mouth_center[0]
    target_y = mouth_center[1] + MOUTH_FOLLOW_OFFSET_Y

    next_x = flute_x + (target_x - flute_x) * sens
    next_y = flute_y + (target_y - flute_y) * sens

    next_x = max(0.05, min(next_x, 0.95))
    next_y = max(0.05, min(next_y, 0.8))
    return next_x, next_y

def process_interaction(hand_landmarks, w, h, screen, show_trackers=False):
    for hole in holes: hole.is_covered = False
    
    if hand_landmarks:
        for lm in hand_landmarks:
            fingers = [8, 12, 16, 20]
            for fid in fingers:
                tip = lm.landmark[fid]
                fx, fy = int(tip.x * w), int(tip.y * h)
                
                if show_trackers:
                    pygame.draw.circle(screen, (255, 0, 0), (fx, fy), 6)
                
                for hole in holes:
                    hx, hy = int(hole.x_rel * w), int(hole.y_rel * h)
                    radius = int(HOLE_RADIUS * w)
                    
                    if math.hypot(fx - hx, fy - hy) < (radius * 1.3):
                        hole.is_covered = True

def calculate_current_note():
    first_open_index = -1
    for i in range(NUM_HOLES):
        if not holes[i].is_covered:
            first_open_index = i
            break
    
    if first_open_index == -1: scale_index = 0
    else: scale_index = NUM_HOLES - first_open_index
        
    scale_index = max(0, min(scale_index, len(SCALE_FLUTE) - 1))
    return BASE_NOTE + SCALE_FLUTE[scale_index]

def is_mouse_over_flute(mx, my, w, h):
    if not holes: return False
    
    # Pega o primeiro e o último furo para calcular a altura total
    start_hole = holes[0]
    end_hole = holes[-1]
    
    # Calcula a área visual da flauta (igual ao draw_flute_ui)
    x_center = int(start_hole.x_rel * w)
    y_start = int((start_hole.y_rel - 0.08) * h)
    y_end = int((end_hole.y_rel + 0.08) * h)
    
    tube_width = 30 # Um pouco mais largo para facilitar o clique
    
    # Verifica se o mouse está dentro do retângulo da flauta
    return (x_center - tube_width < mx < x_center + tube_width) and (y_start < my < y_end)

# draw_text is imported from src.instruments.common

def draw_flute_ui_pygame(screen, w, h, velocity, face_landmarks, font, is_dragging=False, show_trackers=False, show_note_name=False, current_note=None, note_font=None):
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    
    if not holes: return

    start_hole = holes[0]
    end_hole = holes[-1]
    
    sx = start_hole.x_rel * w
    sy = start_hole.y_rel * h
    ex = end_hole.x_rel * w
    ey = end_hole.y_rel * h

    dx = ex - sx
    dy = ey - sy
    length = max(1.0, math.hypot(dx, dy))
    ux = dx / length
    uy = dy / length

    extension_px = int(0.08 * h)
    x_start = int(sx - ux * extension_px)
    y_start = int(sy - uy * extension_px)
    x_end = int(ex + ux * extension_px)
    y_end = int(ey + uy * extension_px)

    tube_width = 25

    body_color = (*COLOR_FLUTE_BODY_EMPTY, 110)
    border_color = (100, 100, 100)

    if is_dragging:
        body_color = (255, 165, 0, 150)
        border_color = (255, 255, 255)

    pygame.draw.line(overlay, border_color, (x_start, y_start), (x_end, y_end), tube_width + 4)
    pygame.draw.line(overlay, body_color, (x_start, y_start), (x_end, y_end), tube_width)

    if velocity > 0:
        fill_ratio = velocity / 127.0
        x_fill = int(x_start + (x_end - x_start) * fill_ratio)
        y_fill = int(y_start + (y_end - y_start) * fill_ratio)
        pygame.draw.line(overlay, (*COLOR_BLOW_ACTIVE, 200), (x_start, y_start), (x_fill, y_fill), tube_width)

    pygame.draw.line(overlay, border_color, (x_start, y_start), (x_end, y_end), 2)
    
    # 4. Furos
    hole_alpha = 180 
    for hole in holes:
        cx = int(hole.x_rel * w)
        cy = int(hole.y_rel * h)
        radius = int(HOLE_RADIUS * w)
        
        base_color = COLOR_HOLE_CLOSED if hole.is_covered else COLOR_HOLE_OPEN
        color_with_alpha = (*base_color, hole_alpha)
        
        if velocity > 0 and not hole.is_covered:
            pygame.draw.circle(overlay, (255, 255, 255), (cx, cy), radius - 2)
        
        pygame.draw.circle(overlay, color_with_alpha, (cx, cy), radius)
        pygame.draw.circle(overlay, (50, 50, 50), (cx, cy), radius, 1)

    if show_note_name:
        draw_font = note_font if note_font is not None else font

        for hole in holes:
            cx = int(hole.x_rel * w)
            cy = int(hole.y_rel * h)
            radius = int(HOLE_RADIUS * w)

            hole_note = get_flute_note_for_first_open_index(hole.index)
            note_label = get_midi_note_label(hole_note)
            is_current = (current_note is not None and int(current_note) == int(hole_note))
            label_color = (255, 240, 80) if is_current else (245, 245, 245)

            label_surface = draw_font.render(note_label, True, label_color)
            shadow_surface = draw_font.render(note_label, True, (20, 20, 20))

            label_x = cx + radius + 8
            label_y = cy - (label_surface.get_height() // 2)

            if label_x + label_surface.get_width() > (w - 6):
                label_x = cx - radius - 8 - label_surface.get_width()
            label_x = max(6, label_x)
            label_y = max(6, min(h - label_surface.get_height() - 6, label_y))

            screen.blit(shadow_surface, (label_x + 1, label_y + 1))
            screen.blit(label_surface, (label_x, label_y))

        closed_note = BASE_NOTE + SCALE_FLUTE[0]
        closed_label = f"{get_midi_note_label(closed_note)}"
        closed_color = (255, 240, 80) if (current_note is not None and int(current_note) == int(closed_note)) else (230, 230, 230)
        closed_surface = draw_font.render(closed_label, True, closed_color)
        closed_shadow = draw_font.render(closed_label, True, (20, 20, 20))

        closed_x = max(8, int(x_start - (closed_surface.get_width() // 2)))
        closed_x = min(w - closed_surface.get_width() - 8, closed_x)
        closed_y = max(8, min(h - closed_surface.get_height() - 8, int(y_start - 30)))

        screen.blit(closed_shadow, (closed_x + 1, closed_y + 1))
        screen.blit(closed_surface, (closed_x, closed_y))

    # 5. Pontos da Boca (Face Mesh)
    if show_trackers and face_landmarks:
        up = face_landmarks.landmark[13]
        low = face_landmarks.landmark[14]
        cx_u, cy_u = int(up.x * w), int(up.y * h)
        cx_l, cy_l = int(low.x * w), int(low.y * h)
        pygame.draw.circle(overlay, COLOR_LIP_POINT, (cx_u, cy_u), 2)
        pygame.draw.circle(overlay, COLOR_LIP_POINT, (cx_l, cy_l), 2)
    
    screen.blit(overlay, (0,0))

    if recorder.is_recording:
        draw_recording_indicator(screen, w, h, font)
        
    if recorder.is_playing:
        draw_playback_indicator(screen, w, font)
# ------------------------
# FUNÇÃO PRINCIPAL
# ------------------------
def start_flute(chosen_instrument, mouth_peak=0.01, mouth_max=0.05, hole_radius=0.019, hole_spacing=0.068, invert_blow=False, invert_angle=False, follow_sensitivity=0.22, rec_options=None, resolution_profile=None, show_trackers=False, hand_model_complexity=1):
    
    global MOUTH_PEAK_OPEN, MOUTH_MAX_OPEN, HOLE_RADIUS, HOLE_SPACING, INVERT_BLOW_LOGIC, INVERT_ANGLE_LOGIC
    MOUTH_PEAK_OPEN = mouth_peak
    MOUTH_MAX_OPEN = mouth_max
    HOLE_RADIUS = hole_radius
    HOLE_SPACING = hole_spacing
    INVERT_BLOW_LOGIC = invert_blow
    INVERT_ANGLE_LOGIC = bool(invert_angle)
    tracker_visible = bool(show_trackers)
    
    if rec_options:
        recorder.set_options(rec_options)
        
    select_instrument_by_name(chosen_instrument)
    
    mp_hands = mp.solutions.hands
    mp_face = mp.solutions.face_mesh
    
    model_complexity = max(0, min(1, int(hand_model_complexity)))
    hands = mp_hands.Hands(max_num_hands=2, model_complexity=model_complexity, min_detection_confidence=0.5)
    face_mesh = mp_face.FaceMesh(max_num_faces=1, refine_landmarks=True)
    
    # PYGAME & CAPTURE SETUP
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

    window_display, main_surface, font = setup_pygame_with_scaling(
        logical_width=LOGICAL_W,
        logical_height=LOGICAL_H,
        display_width=DISPLAY_W,
        display_height=DISPLAY_H,
        title="Talking Hands - Flauta"
    )

    print(f">>> FLAUTA INICIADA: {chosen_instrument}")
    print(f"    Peak: {mouth_peak}, Max: {mouth_max}, Inv: {invert_blow}")
    print(f"    Angle Invert: {invert_angle}")
    print(f"    Follow Sensitivity: {follow_sensitivity}")
    
# --- VARIÁVEIS DE ESTADO E POSIÇÃO ---
    flute_x = DEFAULT_FLUTE_X
    flute_y = DEFAULT_FLUTE_Y
    flute_angle = FLUTE_VERTICAL_BASE_ANGLE
    
    update_hole_positions_with_angle(flute_x, flute_y, flute_angle)

    dragging_flute = False
    drag_offset = (0, 0)

    last_note = -1
    is_playing = False
    
    avg_mouth_dist = 0.0
    last_sent_velocity = 0
    show_gui = False
    manual_blow = False
    note_names_visible = False
    note_font = pygame.font.SysFont("Arial", 14, bold=False)

    running = True

    try:
        while running:
            # 1. INPUT PYGAME
            manual_blow = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1: # Clique Esquerdo
                        mx, my = event.pos
                        if is_mouse_over_flute(mx, my, LOGICAL_W, LOGICAL_H):
                            dragging_flute = True
                            norm_mx = mx / LOGICAL_W
                            norm_my = my / LOGICAL_H
                            drag_offset = (flute_x - norm_mx, flute_y - norm_my)

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        dragging_flute = False

                elif event.type == pygame.MOUSEMOTION:
                    if dragging_flute:
                        mx, my = event.pos
                        norm_mx = mx / LOGICAL_W
                        norm_my = my / LOGICAL_H
                        
                        flute_x = norm_mx + drag_offset[0]
                        flute_y = norm_my + drag_offset[1]
                        
                        flute_x = max(0.05, min(flute_x, 0.95))
                        flute_y = max(0.05, min(flute_y, 0.8))
                        
                        update_hole_positions_with_angle(flute_x, flute_y, flute_angle)

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        recorder.stop_playback()
                        running = False
                    elif event.key == pygame.K_1: recorder.start()
                    elif event.key == pygame.K_2: recorder.stop(f"flute_{int(time.time())}.mid")
                    elif event.key == pygame.K_3: 
                        fs.cc(PLAYBACK_CHANNEL, 11, 127)
                        recorder.toggle_playback(fs)
                    elif event.key == pygame.K_5:
                        flute_x = DEFAULT_FLUTE_X
                        flute_y = DEFAULT_FLUTE_Y
                        flute_angle = FLUTE_VERTICAL_BASE_ANGLE
                        update_hole_positions_with_angle(flute_x, flute_y, flute_angle)
                        print(">>> Posição da flauta resetada.")
                    elif event.key == pygame.K_8:
                        note_names_visible = not note_names_visible
                    elif event.key == pygame.K_9:
                        tracker_visible = not tracker_visible
                    elif event.key == pygame.K_0: show_gui = not show_gui
                    
            keys = pygame.key.get_pressed()
            if keys[pygame.K_SPACE]:
                manual_blow = True

            # 2. CAPTURE
            ret, frame = cap.read()
            if not ret: break

            fps_tracker.update()

            frame = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 3. LÓGICA DE SOPRO (Face) 
            res_face = face_mesh.process(frame_rgb)
            current_mouth_dist = 0.0
            face_landmarks_data = None
            
            if res_face.multi_face_landmarks:
                face_landmarks_data = res_face.multi_face_landmarks[0]
                current_mouth_dist = get_mouth_distance(face_landmarks_data)

                if not dragging_flute:
                    mouth_center = get_mouth_center(face_landmarks_data)
                    target_angle = get_mouth_tilt_angle(face_landmarks_data)
                    flute_angle = flute_angle + (target_angle - flute_angle) * max(0.0, min(follow_sensitivity, 1.0))
                    flute_x, flute_y = update_flute_position_from_mouth(
                        flute_x,
                        flute_y,
                        mouth_center,
                        follow_sensitivity,
                    )
                    update_hole_positions_with_angle(flute_x, flute_y, flute_angle)
            
            avg_mouth_dist = (current_mouth_dist * MOUTH_SMOOTHING_FACTOR) + (avg_mouth_dist * (1.0 - MOUTH_SMOOTHING_FACTOR))
                
            velocity = 0
            if manual_blow:
                velocity = 127
            elif avg_mouth_dist > MOUTH_CLOSE_STOP_THRESHOLD:
                
                ratio = 0.0
                
                if INVERT_BLOW_LOGIC:
                    ratio = (avg_mouth_dist - MOUTH_MIN_OPEN) / (MOUTH_MAX_OPEN - MOUTH_MIN_OPEN)
                else:
                    peak_near_close = MOUTH_CLOSE_STOP_THRESHOLD + ((MOUTH_PEAK_OPEN - MOUTH_CLOSE_STOP_THRESHOLD) * MOUTH_PEAK_NEAR_CLOSE_FACTOR)
                    peak_near_close = max(MOUTH_CLOSE_STOP_THRESHOLD + 1e-6, peak_near_close)

                    if avg_mouth_dist <= peak_near_close:
                        ratio = (avg_mouth_dist - MOUTH_CLOSE_STOP_THRESHOLD) / (peak_near_close - MOUTH_CLOSE_STOP_THRESHOLD)
                    elif avg_mouth_dist < MOUTH_MAX_OPEN:
                        ratio = 1.0 - ((avg_mouth_dist - peak_near_close) / (MOUTH_MAX_OPEN - peak_near_close))
                
                velocity = int(max(0.0, min(ratio, 1.0)) * 127)

            frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), 'RGB')
            main_surface.blit(frame_surface, (0, 0))

            res_hands = hands.process(frame_rgb)
            process_interaction(res_hands.multi_hand_landmarks, LOGICAL_W, LOGICAL_H, main_surface, show_trackers=tracker_visible)
            target_note = calculate_current_note()
            
            if velocity > 0:
                if abs(velocity - last_sent_velocity) > VELOCITY_CHANGE_THRESHOLD or velocity == 127:
                    audio_queue.put(("cc", 11, velocity))
                    last_sent_velocity = velocity
                
                if target_note != last_note or not is_playing:
                    audio_queue.put(("note_on", target_note, 0))
                    last_note = target_note
                    is_playing = True
            else:
                if is_playing:
                    audio_queue.put(("note_off", 0, 0))
                    audio_queue.put(("cc", 11, 0))
                    is_playing = False
                    last_note = -1
                    last_sent_velocity = 0

            draw_flute_ui_pygame(
                main_surface,
                LOGICAL_W,
                LOGICAL_H,
                velocity,
                face_landmarks_data,
                font,
                dragging_flute,
                show_trackers=tracker_visible,
                show_note_name=note_names_visible,
                current_note=target_note,
                note_font=note_font,
            )
            
            if show_gui:
                instructions = [
                    "ESC   -> sair",
                    "1 -> iniciar gravacao",
                    "2 -> encerrar gravacao",
                    "3 -> iniciar/interromper playback",
                    "5 -> resetar posicao da flauta",
                    "8 -> ocultar/mostrar nomes das notas",
                    "9 -> ocultar/mostrar trackers",
                    "0 -> ocultar/mostrar menu"
                ]

                y0 = 30
                for i, txt in enumerate(instructions):
                    draw_text(main_surface, txt, (20, y0 + i * 25), font)

                fps_text = f"FPS: {fps_tracker.get_fps():.1f}"
                draw_text(main_surface, fps_text, (LOGICAL_W - 120, 30), font)

            window_display.blit(main_surface, (0, 0))
            
            pygame.display.flip()

    finally:
        cap.release()
        pygame.quit()
        audio_queue.put(None)
        print(">>> Flauta encerrada.")

if __name__ == "__main__":
    start_flute("Recorder", invert_blow=True)