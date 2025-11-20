import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import numpy as np

# ------------------------
# CONFIGURAÇÕES (HIGH PERFORMANCE & ESTABILIDADE)
# ------------------------
# O quanto precisa subir para ficar "ARMADO" (Pronto para tocar)
LIFT_THRESHOLD = 0.02   

# O quão perto da linha da mesa para ativar o "TOQUE"
TOUCH_TOLERANCE = 0.005 

# O quanto precisa subir para considerar que "SOLTOU" a tecla (Histerese)
# Isso deve ser maior que o TOUCH_TOLERANCE para evitar que o som corte com tremores
RELEASE_THRESHOLD = 0.015 

# Tempo mínimo que uma nota fica tocando (evita sons "engasgados" em toques rápidos)
MIN_NOTE_DURATION = 0.15 

# Tempo limite para cancelar o movimento se não bater
ARMED_TIMEOUT = 2.5    

NUM_KEYS = 30
ACTIVE_FINGERS = [4, 8, 12, 16, 20] 

# Cores (BGR) - Simples para desenhar rápido
COLOR_TABLE_LINE = (0, 255, 0)     
COLOR_TABLE_FRONT = (30, 30, 30) 
COLOR_KEY_DIVIDER = (100, 100, 100)
COLOR_HIT = (0, 255, 255)          
COLOR_ARMED = (0, 165, 255)        
COLOR_HOLD = (0, 200, 0)           

# ------------------------
# GERAR TECLAS
# ------------------------
SCALE_INTERVALS = [0, 2, 4, 5, 7, 9, 11] 
BASE_NOTE = 48 # C3

PIANO_KEYS = []
for i in range(NUM_KEYS):
    octave = i // 7
    note_idx = i % 7
    note_val = BASE_NOTE + (octave * 12) + SCALE_INTERVALS[note_idx]
    PIANO_KEYS.append({"note": note_val, "last_hit": 0, "is_active": False})

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
try:
    fs = fluidsynth.Synth()
    fs.start(driver="dsound") 
    # Verifique se o caminho está correto
    sfid = fs.sfload(r"sounds\keyboard\Retro_Synth_PC.sf2") 
    fs.program_select(0, sfid, 0, 0)
except Exception as e:
    print(f"ERRO AUDIO: {e}")

audio_queue = queue.Queue()

def audio_thread():
    while True:
        item = audio_queue.get()
        if item is None: break
        
        action, note = item
        if action == "on":
            # Toca nota (Velocity 127 = Forte)
            fs.noteon(0, note, 127)
        elif action == "off":
            fs.noteoff(0, note)

threading.Thread(target=audio_thread, daemon=True).start()

# ------------------------
# ESTADO GLOBAL
# ------------------------
global_state = {
    "table_y": 0.80, 
    "calibrated": False
}

hands_state = {
    "Left":  {"finger_status": {}, "finger_timers": {}, "active_notes": {}},
    "Right": {"finger_status": {}, "finger_timers": {}, "active_notes": {}}
}

for hand in ["Left", "Right"]:
    for fid in ACTIVE_FINGERS:
        hands_state[hand]["finger_status"][fid] = "IDLE"
        hands_state[hand]["finger_timers"][fid] = 0.0
        hands_state[hand]["active_notes"][fid] = None

# ------------------------
# LÓGICA GEOMÉTRICA OTIMIZADA
# ------------------------
def processar_dedo(label, fid, y_current, x_current, table_y, cx, cy, frame, h_frame):
    state = hands_state[label]
    status = state["finger_status"][fid]
    
    last_action_time = state["finger_timers"][fid]
    current_time = time.time()
    
    # Distância: Positivo = Dedo acima da mesa. Negativo = Dedo cruzou a mesa (fundo).
    dist_above_table = table_y - y_current

    # --- MÁQUINA DE ESTADOS ---

    if status == "IDLE":
        # Só arma se subir acima do LIFT (mais alto)
        if dist_above_table > LIFT_THRESHOLD:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    elif status == "ARMED":
        # Timeout: Se ficou muito tempo parado no ar
        if (current_time - last_action_time) > ARMED_TIMEOUT:
            state["finger_status"][fid] = "IDLE"
            
        # TOQUE: Chegou perto da linha (TOUCH_TOLERANCE é pequeno)
        elif y_current >= (table_y - TOUCH_TOLERANCE):
            key_idx = int(x_current * NUM_KEYS)
            key_idx = max(0, min(key_idx, NUM_KEYS - 1))
            
            key_data = PIANO_KEYS[key_idx]
            note = key_data["note"]
            
            audio_queue.put(("on", note))
            state["active_notes"][fid] = note
            state["finger_status"][fid] = "TOUCHING"
            state["finger_timers"][fid] = current_time # Guarda hora do toque para calcular duração
            
            key_data["last_hit"] = current_time
            key_data["is_active"] = True
            
            # Feedback visual de impacto
            cv2.circle(frame, (cx, int(table_y * h_frame)), 15, COLOR_HIT, -1)

    elif status == "TOUCHING":
        active_note = state["active_notes"][fid]
        hit_time = state["finger_timers"][fid] # Hora que começou a tocar
        
        # --- 1. GLISSANDO (Mudança de tecla) ---
        current_key_idx = int(x_current * NUM_KEYS)
        current_key_idx = max(0, min(current_key_idx, NUM_KEYS - 1))
        new_note = PIANO_KEYS[current_key_idx]["note"]
        
        if active_note is not None and new_note != active_note:
            # Desliga nota anterior
            audio_queue.put(("off", active_note))
            for k in PIANO_KEYS:
                if k["note"] == active_note: k["is_active"] = False; break

            # Liga nova nota
            audio_queue.put(("on", new_note))
            state["active_notes"][fid] = new_note
            # Atualiza timer para a nova nota (para garantir duração mínima dela também)
            state["finger_timers"][fid] = current_time 
            
            PIANO_KEYS[current_key_idx]["last_hit"] = current_time
            PIANO_KEYS[current_key_idx]["is_active"] = True

        # --- 2. RELEASE (Levantar o dedo) ---
        # Só solta se:
        # a) O dedo subiu acima do RELEASE_THRESHOLD (que é mais alto que o ponto de toque)
        # b) E JÁ PASSOU o tempo mínimo de duração da nota (evita cortes abruptos)
        
        time_held = current_time - hit_time

        if dist_above_table > RELEASE_THRESHOLD and time_held > MIN_NOTE_DURATION:
            if active_note is not None:
                audio_queue.put(("off", active_note))
                for k in PIANO_KEYS:
                    if k["note"] == active_note: k["is_active"] = False; break
            
            state["active_notes"][fid] = None
            
            # IMPORTANTE: Voltamos para ARMED.
            # Como RELEASE_THRESHOLD > LIFT_THRESHOLD, o dedo já está alto o suficiente
            # para ser considerado "Armado" novamente. Isso permite bater de novo rápido.
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    # Desenho do dedo
    color = COLOR_ARMED if status == "ARMED" else (100,100,100)
    if status == "TOUCHING": color = COLOR_HOLD
    cv2.circle(frame, (cx, cy), 5, color, -1)

# ------------------------
# UI OTIMIZADA (DESENHO DIRETO)
# ------------------------
def draw_ui_fast(frame, table_y, w, h):
    table_px = int(table_y * h)
    key_width = w / NUM_KEYS
    
    # Linha da mesa
    cv2.line(frame, (0, table_px), (w, table_px), COLOR_TABLE_LINE, 2)
    
    for i, key in enumerate(PIANO_KEYS):
        x1 = int(i * key_width)
        cv2.line(frame, (x1, table_px), (x1, h), COLOR_KEY_DIVIDER, 1)
        
        if key["is_active"] or (time.time() - key["last_hit"]) < 0.15:
            x2 = int((i + 1) * key_width)
            cv2.rectangle(frame, (x1, table_px), (x2, h), COLOR_HIT, -1)

# ------------------------
# MAIN LOOP
# ------------------------
def main_thread():
    hands = mp.solutions.hands.Hands(
        max_num_hands=2, 
        model_complexity=1, 
        min_detection_confidence=0.7, 
        min_tracking_confidence=0.6
    )
    
    # Camera Config
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened(): cap = cv2.VideoCapture(0)
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    is_calibrating = False
    calib_start_time = 0
    
    print(">>> PIANO ESTÁVEL (COM SUSTAIN)")
    print(">>> Resolução: 640x480 | FPS Alvo: 60")

    while True:
        ret, frame = cap.read()
        if not ret: break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape 
        
        draw_ui_fast(frame, global_state["table_y"], w, h)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        # Calibração
        if is_calibrating:
            cv2.putText(frame, "CALIBRANDO...", (50, h//2), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,255), 2)
            if (time.time() - calib_start_time) > 3.0:
                is_calibrating = False
                if results.multi_hand_landmarks:
                    total_y = 0
                    count = 0
                    for lm in results.multi_hand_landmarks:
                        for fid in ACTIVE_FINGERS:
                            total_y += lm.landmark[fid].y
                            count += 1
                    if count > 0:
                        global_state["table_y"] = min((total_y / count), 0.95)
                        global_state["calibrated"] = True
                        print(f"Calibrado Y={global_state['table_y']:.2f}")

        # Processamento
        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                
                if not global_state["calibrated"]:
                    cv2.putText(frame, "[ESPACO] CALIBRAR", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

                for fid in ACTIVE_FINGERS:
                    finger = lm.landmark[fid]
                    cx, cy = int(finger.x * w), int(finger.y * h)
                    processar_dedo(lbl, fid, finger.y, finger.x, global_state["table_y"], cx, cy, frame, h)

        cv2.imshow("FastPiano", frame)
        
        k = cv2.waitKey(1)
        if k == 32: 
            is_calibrating = True
            calib_start_time = time.time()
            for key in hands_state:
                for fid in ACTIVE_FINGERS:
                    hands_state[key]["finger_status"][fid] = "IDLE"
                    hands_state[key]["active_notes"][fid] = None
        if k == 27: break

    cap.release()
    cv2.destroyAllWindows()
    audio_queue.put(None)

if __name__ == "__main__":
    main_thread()