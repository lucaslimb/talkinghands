import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import numpy as np
import sys
import os
# Math removido pois is_fist foi removido

# --- SETUP DE CAMINHOS ---
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.append(root_dir)

try:
    from config import settings
except ImportError:
    print("ERRO: Config não encontrada.")
    sys.exit()

# ------------------------
# CONFIGURAÇÕES & SENSIBILIDADE
# ------------------------
VELOCITY_THRESHOLD = 0.002 

TOUCH_TOLERANCE = getattr(settings, 'TOUCH_TOLERANCE', 0.01)
ELLIPSE_THRESHOLD = 1.0 - TOUCH_TOLERANCE 

# Cores (BGR)
COLOR_RED = (0, 0, 255)
COLOR_HIT_FILL = (0, 0, 255)   # Vermelho preenchido
COLOR_READY = (0, 255, 255)    # Amarelo (Pronto para bater)
COLOR_IDLE = (100, 100, 100)   # Cinza
COLOR_TEXT = (255, 255, 255)

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
    {"id": 4, "pos": (0.20, 0.80), "axes": (0.11, 0.09), "note": 42, "name": "HI-HAT", "shape": "ellipse"},
    {"id": 5, "pos": (0.50, 0.80), "axes": (0.13, 0.10), "note": 38, "name": "SNARE",  "shape": "ellipse"},
    {"id": 6, "pos": (0.80, 0.80), "axes": (0.11, 0.09), "note": 41, "name": "FLOOR",  "shape": "ellipse"},
    
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
            fs.program_select(0, drum_sfid, 128, 0)
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
    fs.program_select(0, drum_sfid, bank, preset)
    return True

def audio_thread_target():
    while True:
        note = audio_queue.get()
        if note is None: break
        fs.noteon(0, note, 127)

# REMOVIDO: A inicialização global da thread foi removida daqui.
# audio_t = threading.Thread(target=audio_thread_target, daemon=True)
# audio_t.start()

# ------------------------
# ESTADO DAS MÃOS
# ------------------------
hands_state = {
    "Left":  {"prev_y": 0.0, "can_hit": True},
    "Right": {"prev_y": 0.0, "can_hit": True}
}

def reset_hands_state():
    # Reseta o estado ao reiniciar para evitar bugs de movimento
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
        val = ((x - h)**2 / rx**2) + ((y - k)**2 / ry**2)
        return val <= ELLIPSE_THRESHOLD

def process_hand(label, landmarks, w, h, frame):
    # Ponto de Referência: Ponta do Dedão (Landmark 4)
    ref_point = landmarks[4] 
    ref_x, ref_y = ref_point.x, ref_point.y
    
    state = hands_state[label]
    prev_y = state["prev_y"]
    can_hit = state["can_hit"]
    
    # Calcula velocidade vertical (dy > 0 descendo)
    dy = ref_y - prev_y
    
    # Verifica Colisão usando a Ponta do Dedão
    hit_drum_id = None
    for drum in DRUM_KIT:
        if check_collision(ref_x, ref_y, drum):
            hit_drum_id = drum["id"]
            break
    
    # --- LÓGICA DE RESET ---
    drum_center_y = 0
    if hit_drum_id is not None:
        target_drum = next((d for d in DRUM_KIT if d["id"] == hit_drum_id), None)
        if target_drum:
            drum_center_y = target_drum["pos"][1]
    
    if hit_drum_id is None:
        can_hit = True # Reseta se sair do tambor
    else:
        # Reseta se subir acima da metade do tambor
        is_upper_half = ref_y < drum_center_y
        is_moving_up = dy < -VELOCITY_THRESHOLD
        if is_upper_half and is_moving_up:
            can_hit = True

    # --- LÓGICA DE BATIDA ---
    cursor_pos = (int(ref_x * w), int(ref_y * h))
    radius = 10 
    
    # Cor padrão
    cursor_color = COLOR_IDLE 

    if hit_drum_id is not None:
        is_moving_down = dy > VELOCITY_THRESHOLD
        
        if can_hit:
            cursor_color = COLOR_READY # Amarelo (Pronto para bater)
            
        if can_hit and is_moving_down:
            target_drum = next((d for d in DRUM_KIT if d["id"] == hit_drum_id), None)
            if target_drum:
                audio_queue.put(target_drum["note"])
                target_drum["last_hit"] = time.time()
                
                cv2.putText(frame, "HIT!", (cursor_pos[0], cursor_pos[1] - 35), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            can_hit = False 
            cursor_color = (0, 255, 0) # Verde ao bater
            radius = 15

    state["prev_y"] = ref_y
    state["can_hit"] = can_hit

    # Desenha Cursor (Ponta do Dedão)
    cv2.circle(frame, cursor_pos, radius, cursor_color, -1)
    cv2.circle(frame, cursor_pos, radius+2, (255,255,255), 2)

def draw_drums(frame, w, h):
    overlay = frame.copy()
    
    for drum in DRUM_KIT:
        cx_px = int(drum["pos"][0] * w)
        cy_px = int(drum["pos"][1] * h)
        ax_px = int(drum["axes"][0] * w)
        ay_px = int(drum["axes"][1] * h)
        
        color = drum["color"]
        fill = 2 
        
        if (time.time() - drum["last_hit"]) < 0.15:
            fill = -1 
            color = COLOR_HIT_FILL
        
        if drum["shape"] == "rect":
            pt1 = (cx_px - ax_px, cy_px - ay_px)
            pt2 = (cx_px + ax_px, cy_px + ay_px)
            cv2.rectangle(overlay, pt1, pt2, color, fill)
        else:
            cv2.ellipse(overlay, (cx_px, cy_px), (ax_px, ay_px), 0, 0, 360, color, fill)
        
        text_size = cv2.getTextSize(drum["name"], cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        text_x = cx_px - text_size[0] // 2
        text_y = cy_px + text_size[1] // 2
        
        txt_col = COLOR_TEXT
        cv2.putText(overlay, drum["name"], (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, txt_col, 1)

    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

# ------------------------
# LOOP PRINCIPAL
# ------------------------
def start_drums(chosen_instrument=None, user_sustain=None, user_lift=None, user_tolerance=None):
    print(">>> INICIANDO BATERIA (Ponta do Dedão)")
    
    if user_tolerance:
        global ELLIPSE_THRESHOLD
        ELLIPSE_THRESHOLD = 1.0 - user_tolerance
    
    if chosen_instrument:
        success = select_kit_by_name(chosen_instrument)
        if not success: print("Usando kit padrão.")
    else:
        print("Usando kit padrão.")

    # --- CORREÇÃO: INICIAR THREAD AQUI ---
    # Inicia a thread de áudio para esta sessão específica
    audio_t = threading.Thread(target=audio_thread_target, daemon=True)
    audio_t.start()
    
    # Reseta estado para evitar que a mão comece "armada" em posições erradas
    reset_hands_state()

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened(): cap = cv2.VideoCapture(0)
    
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=1, min_detection_confidence=0.3, min_tracking_confidence=0.3)
    
    print(">>> [ESPAÇO] Kick | [ESC] Sair")
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            
            draw_drums(frame, w, h)
            
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb)
            
            if results.multi_hand_landmarks:
                for idx, landmarks in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label
                    process_hand(lbl, landmarks.landmark, w, h, frame)
            
            width, height = 1920, 1080
            frame = cv2.resize(frame, (width, height))
            cv2.imshow("Virtual Drums", frame)
            
            k = cv2.waitKey(1)
            if k == 27: break
            if k == 32: 
                kick_drum = next((d for d in DRUM_KIT if d["name"] == "KICK"), None)
                if kick_drum:
                    audio_queue.put(kick_drum["note"]) 
                    kick_drum["last_hit"] = time.time()
                
    except Exception as e:
        print(f"Erro Runtime: {e}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        # Mata a thread ao sair enviando None para a fila
        audio_queue.put(None)
        print(">>> Bateria Encerrada.")

if __name__ == "__main__":
    start_drums("Perfect Drums 1")