import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import numpy as np
import sys
import os
import pygame  # NOVO
from instruments.recorder import MidiRecorder

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.append(root_dir)

try:
    from config import settings
except ImportError:
    print("ERRO: Config não encontrada.")
    sys.exit()

VELOCITY_THRESHOLD = 0.002 
TOUCH_VELOCITY = getattr(settings, 'TOUCH_VELOCITY')
TOUCH_TOLERANCE = getattr(settings, 'TOUCH_TOLERANCE', 0.01)
ELLIPSE_THRESHOLD = 1.0 - TOUCH_TOLERANCE 

# CORES (Convertidas para RGB para o Pygame)
# No OpenCV (0,0,255) era vermelho. No Pygame é Azul.
# Então ajustamos para o padrão RGB:
COLOR_RED = (255, 0, 0)        # Vermelho
COLOR_HIT_FILL = (255, 0, 0)   # Vermelho
COLOR_READY = (255, 255, 0)    # Amarelo
COLOR_IDLE = (100, 100, 100)   # Cinza
COLOR_TEXT = (255, 255, 255)   # Branco
COLOR_GREEN = (0, 255, 0)      # Verde

show_menu = True

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

FIXED_SF2_PATH = r"sounds\drums\Drums.sf2"

try:
    fs = fluidsynth.Synth()
    fs.start(driver="dsound") 
    
    print(f">>> Carregando SoundFont Fixo: {FIXED_SF2_PATH}...")
    
    if not os.path.isabs(FIXED_SF2_PATH):
        abs_path = os.path.join(root_dir, FIXED_SF2_PATH)
    else:
        abs_path = FIXED_SF2_PATH
        
    if os.path.exists(abs_path):
        drum_sfid = fs.sfload(abs_path)
        if drum_sfid != -1:
            print(f"Sucesso! ID do SF2: {drum_sfid}")
            # Inicializa o preset em todos os canais de polifonia
            for i in range(POLYPHONY_CHANNELS):
                fs.program_select(i, drum_sfid, 128, 0)
        else:
            print(f"ERRO CRÍTICO: Falha ao carregar o arquivo {abs_path}")
    else:
        print(f"ERRO CRÍTICO: Arquivo não encontrado em {abs_path}")

except Exception as e:
    print(f"ERRO CRÍTICO AUDIO: {e}")

def select_kit_by_name(name):
    if drum_sfid == -1: return False
    if name not in settings.INSTRUMENTS: return False
    _, bank, preset = settings.INSTRUMENTS[name]
    print(f">>> SELECIONANDO KIT: {name} | B: {bank} P: {preset}")
    
    # Aplica o kit em todos os canais para manter consistência no rodízio
    for i in range(POLYPHONY_CHANNELS):
        fs.program_select(i, drum_sfid, bank, preset)
    abs_sf2_path = os.path.join(root_dir, FIXED_SF2_PATH) if not os.path.isabs(FIXED_SF2_PATH) else FIXED_SF2_PATH
    recorder.set_instrument(abs_sf2_path, bank, preset, is_drum=True)

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

# ------------------------
# MÃOS
# ------------------------
hands_state = {
    "Left":  {"prev_y": 0.0, "can_hit": True},
    "Right": {"prev_y": 0.0, "can_hit": True}
}

def reset_hands_state():
    hands_state["Left"] = {"prev_y": 0.0, "can_hit": True}
    hands_state["Right"] = {"prev_y": 0.0, "can_hit": True}

def check_collision(x, y, drum):
    h, k = drum["pos"]
    rx, ry = drum["axes"]
    
    if drum["shape"] == "rect":
        x_min, x_max = h - rx, h + rx
        y_min, y_max = k - ry, k + ry
        tol = TOUCH_TOLERANCE
        return (x_min + tol <= x <= x_max - tol) and (y_min + tol <= y <= y_max - tol)
    else:
        # Equação da Elipse
        val = ((x - h)**2 / rx**2) + ((y - k)**2 / ry**2)
        return val <= ELLIPSE_THRESHOLD

# MODIFICADO: Recebe screen e font do Pygame
def process_hand(label, landmarks, w, h, screen, font):
    # Ponto de Referência: Ponta do Dedão (Landmark 4)
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
                hit_surf = font.render("HIT!", True, COLOR_GREEN)
                screen.blit(hit_surf, (cursor_pos[0], cursor_pos[1] - 35))
            
            can_hit = False 
            cursor_color = COLOR_GREEN
            radius = 15

    state["prev_y"] = ref_y
    state["can_hit"] = can_hit

    # PYGAME: Desenho do cursor
    pygame.draw.circle(screen, cursor_color, cursor_pos, radius)
    pygame.draw.circle(screen, (255, 255, 255), cursor_pos, radius + 2, 2)

# AUXILIAR: Desenhar texto
def draw_text(surface, text, pos, font, color=COLOR_TEXT):
    txt_surf = font.render(text, True, color)
    surface.blit(txt_surf, pos)

# MODIFICADO: Desenho com Pygame
def draw_drums_pygame(screen, w, h, font):
    # Surface transparente para efeitos de alpha
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    
    for drum in DRUM_KIT:
        # Conversão de coordenadas normalizadas para Pixels e Rects
        # Pos (h, k) é o centro. Axes (rx, ry) são os raios.
        # Pygame Rect precisa de (left, top, width, height)
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
        
        # Efeito de Hit
        if (time.time() - drum["last_hit"]) < 0.15:
            fill_alpha = 200 # Mais opaco no hit
            color = COLOR_HIT_FILL
        
        # Cor com Alpha
        color_with_alpha = (*color, fill_alpha)
        
        if drum["shape"] == "rect":
            # Preenchimento
            pygame.draw.rect(overlay, color_with_alpha, drum_rect)
            # Borda
            pygame.draw.rect(overlay, color, drum_rect, 2)
        else:
            # Preenchimento
            pygame.draw.ellipse(overlay, color_with_alpha, drum_rect)
            # Borda
            pygame.draw.ellipse(overlay, color, drum_rect, 2)
            
        # Nome do tambor (opcional, centralizado)
        # name_surf = font.render(drum["name"], True, (255,255,255))
        # screen.blit(name_surf, (cx_px - name_surf.get_width()//2, cy_px))

    # Aplica o overlay na tela principal
    screen.blit(overlay, (0, 0))

    if recorder.is_recording:
        pygame.draw.circle(screen, (255, 0, 0), (w - 90, 30), 10)
        draw_text(screen, "REC", (w - 75, 20), font, (255, 0, 0))
        
    if recorder.is_playing:
        draw_text(screen, "PLAYBACK", (w - 200, 30), font, (255, 0, 0))
        
    if show_menu:
        instructions = [
            "ESC   -> sair",
            "1 -> iniciar gravacao",
            "2 -> encerrar gravacao",
            "3 -> iniciar/interromper playback",
            "0 -> ocultar/mostrar menu"
        ]
        y0 = 30
        for i, txt in enumerate(instructions):
            draw_text(screen, txt, (20, y0 + i * 25), font)


# ------------------------
# LOOP PRINCIPAL
# ------------------------
def start_drums(chosen_instrument=None, user_tolerance=None, rec_options=None, touch_velocity=None):
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
    LOGICAL_W, LOGICAL_H = 1280, 720
    
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened(): cap = cv2.VideoCapture(0)
    
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LOGICAL_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, LOGICAL_H)
    
    pygame.init()
    # Usando resolução lógica direta para evitar erros de buffer e distorção
    screen = pygame.display.set_mode((LOGICAL_W, LOGICAL_H))
    pygame.display.set_caption("Talking Hands - Bateria")
    
    # Fonte
    font = pygame.font.SysFont("Arial", 18, bold=True)
    
    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=1, min_detection_confidence=0.3, min_tracking_confidence=0.3)
    
    print(">>> [ESPAÇO] Kick (Atalho Teclado) | [ESC] Sair")
    
    running = True
    try:
        while running:
            # 1. EVENTOS PYGAME
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
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
                    elif event.key == pygame.K_4:
                        recorder.stop_playback()
                    elif event.key == pygame.K_0:
                        show_menu = not show_menu
                    # Atalho de depuração/teclado físico para o Bumbo (Kick)
                    elif event.key == pygame.K_SPACE:
                        audio_queue.put((36, 127)) # 36 = Kick

            # 2. CAPTURA E VÍDEO
            ret, frame = cap.read()
            if not ret: break
            
            # Força o tamanho correto para o buffer do pygame
            frame = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Desenha o vídeo na tela
            frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), 'RGB')
            screen.blit(frame_surface, (0, 0))
            
            # 3. DESENHO DOS TAMBORES (Overlay)
            draw_drums_pygame(screen, LOGICAL_W, LOGICAL_H, font)
            
            # 4. PROCESSAMENTO MEDIAPIPE E CURSORES
            # Note que passamos 'screen' e 'font' para process_hand desenhar
            results = hands.process(frame_rgb)
            
            if results.multi_hand_landmarks:
                for idx, landmarks in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label
                    process_hand(lbl, landmarks.landmark, LOGICAL_W, LOGICAL_H, screen, font)
            
            # 5. ATUALIZA TELA
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