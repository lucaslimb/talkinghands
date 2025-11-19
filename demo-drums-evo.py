import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import numpy as np

# ------------------------
# CONFIGURAÇÕES DE SENSIBILIDADE
# ------------------------
LIFT_THRESHOLD = 0.02   # Altura para armar 
TOUCH_THRESHOLD = 0.01  # Altura para bater
ARMED_TIMEOUT = 1.0      # Resetar se demorar muito

# Cores (BGR)
COLOR_IDLE = (100, 100, 100)
COLOR_ARMED = (0, 255, 255)
COLOR_HIT = (0, 255, 0)

# ------------------------
# DEFINIÇÃO DAS ZONAS DA BATERIA
# ------------------------
DRUM_ZONES = [
    # --- LINHA SUPERIOR ---
    {
        "name": "CRASH", "rect": (0.0, 0.0, 0.33, 0.5), 
        "note": 49, "color": (0, 200, 255), "last_hit": 0
    },
    {
        "name": "HI-TOM", "rect": (0.33, 0.0, 0.66, 0.5), 
        "note": 48, "color": (0, 0, 200), "last_hit": 0
    },
    {
        "name": "RIDE", "rect": (0.66, 0.0, 1.0, 0.5), 
        "note": 51, "color": (200, 0, 200), "last_hit": 0
    },
    # --- LINHA INFERIOR ---
    {
        "name": "HI-HAT", "rect": (0.0, 0.5, 0.33, 1.0), 
        "note": 42, "color": (0, 255, 255), "last_hit": 0
    },
    {
        "name": "SNARE", "rect": (0.33, 0.5, 0.66, 1.0), 
        "note": 38, "color": (0, 255, 0), "last_hit": 0
    },
    {
        "name": "LO-TOM", "rect": (0.66, 0.5, 1.0, 1.0), 
        "note": 41, "color": (50, 50, 150), "last_hit": 0
    },
]

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
try:
    fs = fluidsynth.Synth()
    fs.start(driver="dsound")  # Windows
    sfid = fs.sfload("HS R8 drums.sf2") 
    fs.program_select(0, sfid, 0, 0)
except Exception as e:
    print(f"ERRO DE AUDIO: {e}")
    print("Verifique se o arquivo .sf2 está na pasta e se o driver está correto.")

audio_queue = queue.Queue()

def audio_thread():
    while True:
        item = audio_queue.get()
        if item is None: break
        note = item
        fs.noteon(0, note, 127)

threading.Thread(target=audio_thread, daemon=True).start()

# ------------------------
# ESTADO GLOBAL
# ------------------------
hands_state = {
    "Left":  {"calibrated": False, "z_base": 0.0, "status": "IDLE", "timer": 0.0},
    "Right": {"calibrated": False, "z_base": 0.0, "status": "IDLE", "timer": 0.0}
}

# ------------------------
# FUNÇÕES AUXILIARES
# ------------------------

def get_zone_at(x, y):
    for i, zone in enumerate(DRUM_ZONES):
        x1, y1, x2, y2 = zone["rect"]
        if x1 <= x < x2 and y1 <= y < y2:
            return i
    return None

def draw_ui(frame):
    h, w, _ = frame.shape
    overlay = frame.copy()
    
    for zone in DRUM_ZONES:
        x1 = int(zone["rect"][0] * w)
        y1 = int(zone["rect"][1] * h)
        x2 = int(zone["rect"][2] * w)
        y2 = int(zone["rect"][3] * h)
        
        if (time.time() - zone["last_hit"]) < 0.15:
            cv2.rectangle(overlay, (x1, y1), (x2, y2), zone["color"], -1) 
        else:
            cv2.rectangle(overlay, (x1, y1), (x2, y2), zone["color"], 2)  
            
        cv2.putText(overlay, zone["name"], (x1 + 20, y1 + 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)

# ------------------------
# PROCESSAMENTO DE DEDO
# ------------------------
def processar_baqueta(label, lm_idx, z_base, w, h, frame):
    state = hands_state[label]
    
    cx, cy = int(lm_idx.x * w), int(lm_idx.y * h)
    z_current = lm_idx.z
    diff = z_base - z_current 
    
    current_time = time.time()
    zone_idx = get_zone_at(lm_idx.x, lm_idx.y)
    
    cor_baqueta = COLOR_IDLE
    raio = 10

    if state["status"] == "IDLE":
        if diff > LIFT_THRESHOLD:
            state["status"] = "ARMED"
            state["timer"] = current_time
            
    elif state["status"] == "ARMED":
        cor_baqueta = COLOR_ARMED
        raio = 15
        
        if (current_time - state["timer"]) > ARMED_TIMEOUT:
            state["status"] = "IDLE"
        
        elif diff < TOUCH_THRESHOLD:
            if zone_idx is not None:
                zone = DRUM_ZONES[zone_idx]
                audio_queue.put(zone["note"])
                zone["last_hit"] = current_time
                cv2.putText(frame, "HIT!", (cx, cy-30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 3)
            
            state["status"] = "IDLE"
            cor_baqueta = COLOR_HIT

    cv2.circle(frame, (cx, cy), raio, cor_baqueta, -1)
    cv2.circle(frame, (cx, cy), raio+2, (255, 255, 255), 2)

# ------------------------
# LOOP PRINCIPAL
# ------------------------
def main_thread():
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.7)
    
    # --- CORREÇÃO DE CAMERA ---
    print("Tentando abrir câmera...")
    cap = cv2.VideoCapture(0)
    
    is_calibrating = False
    calib_start_time = 0
    CALIB_DURATION = 3.0
    INDEX_FINGER = 8

    print(">>> Bateria Espacial Iniciada.")
    print(">>> [ESPAÇO] Calibrar | [B] Kick | [ESC] Sair")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Erro ao ler frame da câmera.")
            break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        
        draw_ui(frame)
        
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        if is_calibrating:
            remaining = CALIB_DURATION - (time.time() - calib_start_time)
            msg = f"MANTENHA DEDOS NA MESA: {remaining:.1f}" if remaining > 0 else "CALIBRANDO..."
            cv2.putText(frame, msg, (50, h//2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            
            if remaining <= 0:
                is_calibrating = False
                if results.multi_hand_landmarks:
                    found = []
                    for idx, lm in enumerate(results.multi_hand_landmarks):
                        lbl = results.multi_handedness[idx].classification[0].label
                        hands_state[lbl]["z_base"] = lm.landmark[INDEX_FINGER].z
                        hands_state[lbl]["calibrated"] = True
                        found.append(lbl)
                    print(f"Calibrado: {found}")
                else:
                    print("Erro: Mãos não encontradas.")

        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                
                if not hands_state[lbl]["calibrated"]:
                    cx_lbl = w - 150 if lbl == "Right" else 20
                    cv2.putText(frame, "NAO CALIBRADO", (cx_lbl, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
                    continue
                
                lm_index = lm.landmark[INDEX_FINGER]
                processar_baqueta(lbl, lm_index, hands_state[lbl]["z_base"], w, h, frame)

        cv2.imshow("Teclado Invisivel", frame)

        k = cv2.waitKey(1)
        if k == 32: 
            is_calibrating = True
            calib_start_time = time.time()
            hands_state["Left"]["calibrated"] = False
            hands_state["Right"]["calibrated"] = False
            hands_state["Left"]["status"] = "IDLE"
            hands_state["Right"]["status"] = "IDLE"
            
        if k == ord('b'): 
            audio_queue.put(36)
            
        if k == 27: break

    cap.release()
    cv2.destroyAllWindows()
    audio_queue.put(None)

if __name__ == "__main__":
    main_thread()