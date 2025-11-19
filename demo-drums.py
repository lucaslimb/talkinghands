import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time

# ------------------------
# CONFIGURAÇÕES
# ------------------------
LIFT_THRESHOLD = 0.03   # Altura para armar
TOUCH_THRESHOLD = 0.015 # Altura para bater (tocar)
ARMED_TIMEOUT = 1    # Segundos para cancelar se não bater

ACTIVE_FINGERS = [4, 8, 12, 16, 20] 

# --- MAPA DE BATERIA (General MIDI) ---
# 36: Kick (Bumbo)
# 38: Snare (Caixa)
# 42: Closed Hi-Hat (Chimbal Fechado)
# 46: Open Hi-Hat (Chimbal Aberto)
# 49: Crash Cymbal (Prato de Ataque)
# 51: Ride Cymbal (Prato de Condução)
# 41: Low Tom (Surdo)
# 45: Mid Tom
# 48: High Tom

NOTE_MAP = {
    "Left":  {
        20: 36, # Pinky:  KICK (Bumbo)
        16: 41, # Ring:   LOW TOM (Surdo)
        12: 45, # Middle: MID TOM
        8:  38, # Index:  SNARE (Caixa)
        4:  46  # Thumb:  OPEN HI-HAT (Chimbal Aberto)
    },
    "Right": {
        4:  42, # Thumb:  CLOSED HI-HAT (Chimbal Fechado)
        8:  38, # Index:  SNARE (Caixa - repetida para facilitar viradas)
        12: 48, # Middle: HIGH TOM
        16: 49, # Ring:   CRASH (Prato Ataque)
        20: 51  # Pinky:  RIDE (Prato Condução)
    }
}

# Dicionário apenas para mostrar o nome na tela
NOTE_NAMES = {
    36: "KICK", 38: "SNARE", 41: "L-TOM", 42: "CL-HAT",
    45: "M-TOM", 46: "OP-HAT", 48: "H-TOM", 49: "CRASH", 51: "RIDE"
}

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
fs = fluidsynth.Synth()
fs.start(driver="dsound")  # Windows. Use 'alsa' no Linux.

# --- CARREGANDO O SF2 DA BATERIA ---
sfid = fs.sfload("HS R8 drums.sf2") 
fs.program_select(0, sfid, 0, 0)

audio_queue = queue.Queue()

def audio_thread():
    while True:
        item = audio_queue.get()
        if item is None: break
        note = item
        # Canal 0 (ou 9 em alguns synths, mas SF2 dedicados costumam usar o 0)
        # Velocity 127 (máximo) para batida forte de bateria
        fs.noteon(0, note, 127)

threading.Thread(target=audio_thread, daemon=True).start()

# ------------------------
# ESTADO GLOBAL
# ------------------------
hands_state = {
    "Left":  {
        "calibrated": False, 
        "z_base": 0.0, 
        "finger_status": {}, 
        "finger_timers": {} 
    },
    "Right": {
        "calibrated": False, 
        "z_base": 0.0, 
        "finger_status": {}, 
        "finger_timers": {}
    }
}

# Inicializa status
for hand in ["Left", "Right"]:
    for fid in ACTIVE_FINGERS:
        hands_state[hand]["finger_status"][fid] = "IDLE"
        hands_state[hand]["finger_timers"][fid] = 0.0

# ------------------------
# LÓGICA DO DEDO
# ------------------------
def processar_dedo(label, fid, z_current, z_base, cx, cy, frame):
    state = hands_state[label]
    status = state["finger_status"][fid]
    last_action_time = state["finger_timers"][fid]
    
    diff = z_base - z_current 
    
    cor = (100, 100, 100) # Cinza (Idle)
    raio = 6
    
    current_time = time.time()

    # --- ESTADO 1: IDLE ---
    if status == "IDLE":
        if diff > LIFT_THRESHOLD:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    # --- ESTADO 2: ARMED ---
    elif status == "ARMED":
        cor = (0, 255, 255) # Amarelo
        raio = 8
        
        # Timeout
        if (current_time - last_action_time) > ARMED_TIMEOUT:
            state["finger_status"][fid] = "IDLE"
            cv2.circle(frame, (cx, cy), 10, (255, 0, 255), 2)
        
        # BATIDA
        elif diff < TOUCH_THRESHOLD:
            note = NOTE_MAP[label][fid]
            audio_queue.put(note)
            
            state["finger_status"][fid] = "IDLE"
            
            # Visual Verde + Nome da Peça
            drum_name = NOTE_NAMES.get(note, str(note))
            cv2.circle(frame, (cx, cy), 20, (0, 255, 0), -1) 
            cv2.putText(frame, drum_name, (cx-30, cy-30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.circle(frame, (cx, cy), raio, cor, -1)

# ------------------------
# LOOP PRINCIPAL
# ------------------------
def main_thread():
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.7)
    mp_draw = mp.solutions.drawing_utils
    
    cap = cv2.VideoCapture(0)
    
    is_calibrating = False
    calib_start_time = 0
    CALIB_DURATION = 3.0

    print(">>> Pressione ESPAÇO para calibrar.")

    while True:
        ret, frame = cap.read()
        if not ret: break

        # 1. Espelhamento
        frame = cv2.flip(frame, 1)
        
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        # 2. Calibração
        if is_calibrating:
            remaining = CALIB_DURATION - (time.time() - calib_start_time)
            if remaining > 0:
                cv2.putText(frame, f"MAOS NA MESA: {remaining:.1f}", (50, h//2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            else:
                is_calibrating = False
                if results.multi_hand_landmarks:
                    hands_found = []
                    for idx, lm in enumerate(results.multi_hand_landmarks):
                        lbl = results.multi_handedness[idx].classification[0].label
                        hands_found.append(lbl)
                        avg_z = sum([lm.landmark[i].z for i in ACTIVE_FINGERS]) / len(ACTIVE_FINGERS)
                        hands_state[lbl]["z_base"] = avg_z
                        hands_state[lbl]["calibrated"] = True
                    print(f"Calibrado: {hands_found}")
                else:
                    print("Erro: Nenhuma mão detectada.")

        # 3. Processamento
        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                state = hands_state[lbl]
                
                mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
                
                # Posição do texto corrigida
                cx_lbl = w - 250 if lbl == "Right" else 20

                if not state["calibrated"]:
                    cv2.putText(frame, "NAO CALIBRADO", (cx_lbl, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
                    continue

                for fid in ACTIVE_FINGERS:
                    lm_finger = lm.landmark[fid]
                    cx, cy = int(lm_finger.x * w), int(lm_finger.y * h)
                    
                    processar_dedo(lbl, fid, lm_finger.z, state["z_base"], cx, cy, frame)

        cv2.putText(frame, "BATERIA INVISIVEL | [ESPACO] Calibrar", (10, h-20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
        
        cv2.imshow("Invisible Drums", frame)
        
        k = cv2.waitKey(1)
        if k == 32: # Espaço
            is_calibrating = True
            calib_start_time = time.time()
            for key in hands_state:
                hands_state[key]["calibrated"] = False
                for fid in ACTIVE_FINGERS:
                    hands_state[key]["finger_status"][fid] = "IDLE"
        
        if k == 27: break

    cap.release()
    cv2.destroyAllWindows()
    audio_queue.put(None)

if __name__ == "__main__":
    main_thread()