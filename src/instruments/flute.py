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
    setup_video_capture, setup_pygame,
    draw_text, draw_recording_indicator, draw_playback_indicator
)

# Import fluidsynth AFTER common.py setup has run
import fluidsynth

NUM_HOLES = 7
HOLE_RADIUS = getattr(settings, 'HOLE_RADIUS', 0.019)
HOLE_SPACING = getattr(settings, 'HOLE_SPACING', 0.068)

DEFAULT_FLUTE_X = 0.6
DEFAULT_FLUTE_Y = 0.25

MOUTH_MIN_OPEN = 0.002
MOUTH_PEAK_OPEN = getattr(settings, 'MOUTH_PEAK_OPEN', 0.01)
MOUTH_MAX_OPEN = getattr(settings, 'MOUTH_MAX_OPEN', 0.05)
BLOW_KEY = 32

INVERT_BLOW_LOGIC = False

MOUTH_SMOOTHING_FACTOR = 0.3 
VELOCITY_CHANGE_THRESHOLD = 4

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

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
audio_queue = queue.Queue()
loaded_sfids = {}
recorder = MidiRecorder()

fs, loaded_sfids = init_fluidsynth(driver="dsound")
if fs is not None:
    sf_path = settings.SF2_PATHS.get("flute")
    if sf_path:
        sfid = load_single_soundfont(fs, "flute", sf_path)
        if sfid != -1:
            loaded_sfids["flute"] = sfid
        else:
            print("ERRO: SF2 de flauta não carregado.")
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
        recorder.set_instrument(sf_path, bank, preset, is_drum=False)
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

class FluteHole:
    def __init__(self, index, x_rel, y_rel):
        self.index = index
        self.x_rel = x_rel 
        self.y_rel = y_rel
        self.is_covered = False

holes = []

def update_hole_positions(start_x, start_y):
    holes.clear()
    for i in range(NUM_HOLES):
        h = FluteHole(i, start_x, start_y + (i * HOLE_SPACING))
        holes.append(h)

def get_mouth_distance(face_landmarks):
    if not face_landmarks: return 0.0
    upper = face_landmarks.landmark[13]
    lower = face_landmarks.landmark[14]
    return abs(upper.y - lower.y)

def process_interaction(hand_landmarks, w, h, screen):
    for hole in holes: hole.is_covered = False
    
    if hand_landmarks:
        for lm in hand_landmarks:
            fingers = [8, 12, 16, 20]
            for fid in fingers:
                tip = lm.landmark[fid]
                fx, fy = int(tip.x * w), int(tip.y * h)
                
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

def draw_flute_ui_pygame(screen, w, h, velocity, face_landmarks, font, is_dragging=False):
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    
    if not holes: return

    start_hole = holes[0]
    end_hole = holes[-1]
    
    x_center = int(start_hole.x_rel * w)
    
    y_start = int((start_hole.y_rel - 0.08) * h)
    y_end = int((end_hole.y_rel + 0.08) * h)
    flute_height = y_end - y_start
    
    tube_width = 25 
    
    body_rect = pygame.Rect(x_center - tube_width//2, y_start, tube_width, flute_height)
    
    body_color = (*COLOR_FLUTE_BODY_EMPTY, 200)
    border_color = (100, 100, 100)
    
    if is_dragging:
        body_color = (255, 165, 0, 150) # Laranja transparente
        border_color = (255, 255, 255)
    pygame.draw.rect(overlay, (*COLOR_FLUTE_BODY_EMPTY, 200), body_rect)
    
    if velocity > 0:
        fill_ratio = velocity / 127.0
        fill_height = int(flute_height * fill_ratio)
        fill_rect = pygame.Rect(x_center - tube_width//2, y_start, tube_width, fill_height)
        pygame.draw.rect(overlay, (*COLOR_BLOW_ACTIVE, 200), fill_rect)

    pygame.draw.rect(overlay, (100, 100, 100), body_rect, 2)
    
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

    # 5. Pontos da Boca (Face Mesh)
    if face_landmarks:
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
def start_flute(chosen_instrument, mouth_peak=0.01, mouth_max=0.05, hole_radius=0.019, hole_spacing=0.068, invert_blow=False, rec_options=None):
    
    global MOUTH_PEAK_OPEN, MOUTH_MAX_OPEN, HOLE_RADIUS, HOLE_SPACING, INVERT_BLOW_LOGIC
    MOUTH_PEAK_OPEN = mouth_peak
    MOUTH_MAX_OPEN = mouth_max
    HOLE_RADIUS = hole_radius
    HOLE_SPACING = hole_spacing
    INVERT_BLOW_LOGIC = invert_blow
    
    if rec_options:
        recorder.set_options(rec_options)
        
    select_instrument_by_name(chosen_instrument)
    
    mp_hands = mp.solutions.hands
    mp_face = mp.solutions.face_mesh
    
    hands = mp_hands.Hands(max_num_hands=2, model_complexity=1, min_detection_confidence=0.5)
    face_mesh = mp_face.FaceMesh(max_num_faces=1, refine_landmarks=True)
    
    # PYGAME & CAPTURE SETUP
    LOGICAL_W, LOGICAL_H = 1280, 720
    cap = setup_video_capture(width=LOGICAL_W, height=LOGICAL_H, fps=60)
    
    screen, font = setup_pygame(window_width=LOGICAL_W, window_height=LOGICAL_H, title="Talking Hands - Flauta")

    print(f">>> FLAUTA INICIADA: {chosen_instrument}")
    print(f"    Peak: {mouth_peak}, Max: {mouth_max}, Inv: {invert_blow}")
    
# --- VARIÁVEIS DE ESTADO E POSIÇÃO ---
    flute_x = DEFAULT_FLUTE_X
    flute_y = DEFAULT_FLUTE_Y
    
    update_hole_positions(flute_x, flute_y)

    dragging_flute = False
    drag_offset = (0, 0)

    last_note = -1
    is_playing = False
    
    avg_mouth_dist = 0.0
    last_sent_velocity = 0
    show_gui = True
    manual_blow = False

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
                        
                        update_hole_positions(flute_x, flute_y)

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
                        update_hole_positions(flute_x, flute_y)
                        print(">>> Posição da flauta resetada.")
                    elif event.key == pygame.K_0: show_gui = not show_gui
                    
            keys = pygame.key.get_pressed()
            if keys[pygame.K_SPACE]:
                manual_blow = True

            # 2. CAPTURE
            ret, frame = cap.read()
            if not ret: break

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
            
            avg_mouth_dist = (current_mouth_dist * MOUTH_SMOOTHING_FACTOR) + (avg_mouth_dist * (1.0 - MOUTH_SMOOTHING_FACTOR))
                
            velocity = 0
            if manual_blow:
                velocity = 127
            elif avg_mouth_dist >= MOUTH_MIN_OPEN:
                
                ratio = 0.0
                
                if INVERT_BLOW_LOGIC:
                    ratio = (avg_mouth_dist - MOUTH_MIN_OPEN) / (MOUTH_MAX_OPEN - MOUTH_MIN_OPEN)
                else:
                    if avg_mouth_dist <= MOUTH_PEAK_OPEN:
                        ratio = (avg_mouth_dist - MOUTH_MIN_OPEN) / (MOUTH_PEAK_OPEN - MOUTH_MIN_OPEN)
                    elif avg_mouth_dist < MOUTH_MAX_OPEN:
                        ratio = 1.0 - ((avg_mouth_dist - MOUTH_PEAK_OPEN) / (MOUTH_MAX_OPEN - MOUTH_PEAK_OPEN))
                
                velocity = int(max(0.0, min(ratio, 1.0)) * 127)

            frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), 'RGB')
            screen.blit(frame_surface, (0, 0))

            res_hands = hands.process(frame_rgb)
            process_interaction(res_hands.multi_hand_landmarks, LOGICAL_W, LOGICAL_H, screen)
            
            if velocity > 0:
                target_note = calculate_current_note()
                
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

            draw_flute_ui_pygame(screen, LOGICAL_W, LOGICAL_H, last_sent_velocity, face_landmarks_data, font, dragging_flute)            
            
            if show_gui:
                instructions = [
                    "ESC   -> sair",
                    "1 -> iniciar gravacao",
                    "2 -> encerrar gravacao",
                    "3 -> iniciar/interromper playback",
                    "5 -> resetar posicao da flauta",
                    "0 -> ocultar/mostrar menu"
                ]

                y0 = 30
                for i, txt in enumerate(instructions):
                    draw_text(screen, txt, (20, y0 + i * 25), font)
            
            pygame.display.flip()

    finally:
        cap.release()
        pygame.quit()
        audio_queue.put(None)
        print(">>> Flauta encerrada.")

if __name__ == "__main__":
    start_flute("Recorder", invert_blow=True)