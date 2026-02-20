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
    draw_text, draw_recording_indicator, draw_playback_indicator
)

# Import fluidsynth AFTER common.py setup has run
import fluidsynth

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.append(root_dir)

from src.config import settings

VELOCITY_THRESHOLD = 0.002 
TOUCH_VELOCITY = getattr(settings, 'TOUCH_VELOCITY')
TOUCH_TOLERANCE = getattr(settings, 'TOUCH_TOLERANCE', 0.01)
ELLIPSE_THRESHOLD = 1.0 - TOUCH_TOLERANCE 

COLOR_RED = (255, 0, 0)        # Vermelho
COLOR_HIT_FILL = (255, 0, 0)  
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
DRUM_KIT = [
    # --- LINHA SUPERIOR (PRATOS) ---
    {"id": 0, "pos": (0.20, 0.40), "axes": (0.12, 0.08), "note": 49, "name": "CRASH", "shape": "ellipse"},
    {"id": 1, "pos": (0.80, 0.40), "axes": (0.12, 0.08), "note": 51, "name": "RIDE",  "shape": "ellipse"},
    
    # --- LINHA DO MEIO (TOMS) ---
    {"id": 2, "pos": (0.38, 0.60), "axes": (0.09, 0.06), "note": 48, "name": "HI-TOM", "shape": "ellipse"},
    {"id": 3, "pos": (0.62, 0.60), "axes": (0.09, 0.06), "note": 45, "name": "LO-TOM", "shape": "ellipse"},
    
    # --- LINHA INFERIOR (TAMBORES PRINCIPAIS) ---
    {"id": 4, "pos": (0.20, 0.85), "axes": (0.11, 0.09), "note": 42, "name": "HI-HAT", "shape": "ellipse"},
    {"id": 5, "pos": (0.50, 0.80), "axes": (0.13, 0.10), "note": 38, "name": "SNARE",  "shape": "ellipse"},
    {"id": 6, "pos": (0.80, 0.85), "axes": (0.11, 0.09), "note": 41, "name": "FLOOR",  "shape": "ellipse"},
    
    # --- BUMBO (KICK) ---
    {"id": 7, "pos": (0.50, 0.96), "axes": (0.15, 0.03), "note": 36, "name": "KICK",   "shape": "rect"},
]

INITIAL_POSITIONS = {d["id"]: d["pos"] for d in DRUM_KIT}

for drum in DRUM_KIT:
    drum["last_hit"] = 0
    drum["color"] = COLOR_RED 

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
    recorder.set_instrument(FIXED_SF2_PATH, bank, preset, is_drum=True)

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

hands_state = {
    "Left":  {"prev_y": 0.0, "can_hit": True},
    "Right": {"prev_y": 0.0, "can_hit": True}
}

def reset_hands_state():
    hands_state["Left"] = {"prev_y": 0.0, "can_hit": True}
    hands_state["Right"] = {"prev_y": 0.0, "can_hit": True}

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

def process_hand(label, landmarks, w, h, screen, font):
    ref_point = landmarks[4] 
    ref_x, ref_y = ref_point.x, ref_point.y
    
    state = hands_state[label]
    prev_y = state["prev_y"]
    can_hit = state["can_hit"]
    
    dy = ref_y - prev_y
    
    hit_drum_id = None
    for drum in DRUM_KIT:
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
        is_moving_down = dy > VELOCITY_THRESHOLD
        
        if can_hit:
            cursor_color = COLOR_READY
            
        if can_hit and is_moving_down:
            target_drum = next((d for d in DRUM_KIT if d["id"] == hit_drum_id), None)
            if target_drum:
                velocity = int(min(max((dy - TOUCH_VELOCITY) * 8000, 30), 127))
                audio_queue.put((target_drum["note"], velocity))
                target_drum["last_hit"] = time.time()
                
                # PYGAME: Texto de Hit
                # hit_surf = font.render("HIT!", True, COLOR_GREEN)
                # screen.blit(hit_surf, (cursor_pos[0], cursor_pos[1] - 35))
            
            can_hit = False 
            cursor_color = COLOR_GREEN
            radius = 15

    state["prev_y"] = ref_y
    state["can_hit"] = can_hit

    pygame.draw.circle(screen, cursor_color, cursor_pos, radius)
    pygame.draw.circle(screen, (255, 255, 255), cursor_pos, radius + 2, 2)

# draw_text is imported from src.instruments.common

def draw_drums_pygame(screen, w, h, font, dragging_drum=None):
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
        fill_alpha = 50 # Transparência leve (aprox 0.4 do OpenCV)
        
        if (time.time() - drum["last_hit"]) < 0.15:
            fill_alpha = 200 
            color = COLOR_HIT_FILL

        if dragging_drum and drum["id"] == dragging_drum["id"]:
            color = (255, 165, 0) # Laranja
            fill_alpha = 100
        
        color_with_alpha = (*color, fill_alpha)
        
        if drum["shape"] == "rect":

            pygame.draw.rect(overlay, color_with_alpha, drum_rect)
            pygame.draw.rect(overlay, color, drum_rect, 2)
        else:
            pygame.draw.ellipse(overlay, color_with_alpha, drum_rect)
            pygame.draw.ellipse(overlay, color, drum_rect, 2)
            
        # Nome do tambor
        # name_surf = font.render(drum["name"], True, (255,255,255))
        # screen.blit(name_surf, (cx_px - name_surf.get_width()//2, cy_px))

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
            "5 -> resetar posicao da bateria",
            "0 -> ocultar/mostrar menu"
        ]
        y0 = 30
        for i, txt in enumerate(instructions):
            draw_text(screen, txt, (20, y0 + i * 25), font)

        fps_text = f"FPS: {fps_tracker.get_fps():.1f}"
        draw_text(screen, fps_text, (w - 120, 30), font)

 # Loop principal
def start_drums(chosen_instrument=None, user_tolerance=None, rec_options=None, touch_velocity=None, resolution_profile=None):
    print(">>> INICIANDO BATERIA (Pygame)")
    
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

    window_display, main_surface, font = setup_pygame_with_scaling(
        logical_width=LOGICAL_W,
        logical_height=LOGICAL_H,
        display_width=DISPLAY_W,
        display_height=DISPLAY_H,
        title="Talking Hands - Bateria"
    )
    
    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=1, min_detection_confidence=0.3, min_tracking_confidence=0.3)
        
    dragging_drum = None
    drag_offset = (0, 0)

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
                            if is_mouse_over_drum(mx, my, drum, LOGICAL_W, LOGICAL_H):
                                dragging_drum = drum
                                norm_mx = mx / LOGICAL_W
                                norm_my = my / LOGICAL_H
                                drag_offset = (drum["pos"][0] - norm_mx, drum["pos"][1] - norm_my)
                                break

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        dragging_drum = None
                
                elif event.type == pygame.MOUSEMOTION:
                    if dragging_drum:
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
                    elif event.key == pygame.K_0:
                        show_menu = not show_menu
                    elif event.key == pygame.K_SPACE:
                        audio_queue.put((36, 127)) # 36 = Kick

            ret, frame = cap.read()
            if not ret: break

            fps_tracker.update()
            
            frame = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), 'RGB')
            main_surface.blit(frame_surface, (0, 0))
            
            draw_drums_pygame(main_surface, LOGICAL_W, LOGICAL_H, font, dragging_drum)
            
            results = hands.process(frame_rgb)
            
            if results.multi_hand_landmarks:
                for idx, landmarks in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label
                    process_hand(lbl, landmarks.landmark, LOGICAL_W, LOGICAL_H, main_surface, font)

            window_display.blit(main_surface, (0, 0))
            
            pygame.display.flip()
                
    except Exception as e:
        print(f"Erro Runtime: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cap.release()
        pygame.quit()
        audio_queue.put(None)
        print(">>> Bateria Encerrada.")

if __name__ == "__main__":
    start_drums("Perfect Drums 1")