import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import numpy as np

# ------------------------
# CONFIGURAÇÕES
# ------------------------
LIFT_THRESHOLD = 0.1   # Altura para armar
TOUCH_THRESHOLD = 0.015  # Altura para bater (tocar)
ARMED_TIMEOUT = 0.5      # Tempo para cancelar movimento

NUM_KEYS = 20            # Quantidade de teclas na tela

# Cores (BGR)
COLOR_KEY_BORDER = (100, 100, 100)
COLOR_KEY_HIT = (0, 255, 255) # Amarelo ao tocar

ACTIVE_FINGERS = [4, 8, 12, 16, 20] 

# ------------------------
# GERAR TECLAS (Escala de Dó Maior)
# ------------------------
# C3 = 48. Padrão Maior: Tom, Tom, Semi, Tom, Tom, Tom, Semi
SCALE_INTERVALS = [0, 2, 4, 5, 7, 9, 11] # C, D, E, F, G, A, B
BASE_NOTE = 48 # C3

PIANO_KEYS = []
for i in range(NUM_KEYS):
    octave = i // 7
    note_idx = i % 7
    note_val = BASE_NOTE + (octave * 12) + SCALE_INTERVALS[note_idx]
    
    PIANO_KEYS.append({
        "note": note_val,
        "last_hit": 0,
        "label": str(note_val) # Poderia ser "C", "D", etc.
    })

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
try:
    fs = fluidsynth.Synth()
    fs.start(driver="dsound") 
    sfid = fs.sfload("Retro_Synth_PC.sf2") 
    fs.program_select(0, sfid, 0, 0)
except Exception as e:
    print(f"ERRO AUDIO: {e}")

audio_queue = queue.Queue()

def audio_thread():
    while True:
        item = audio_queue.get()
        if item is None: break
        note = item
        fs.noteon(0, note, 100)
        # Opcional: NoteOff automático curto para efeito percussivo
        # time.sleep(0.3)
        # fs.noteoff(0, note)

threading.Thread(target=audio_thread, daemon=True).start()

# ------------------------
# ESTADO GLOBAL
# ------------------------
hands_state = {
    "Left":  {"calibrated": False, "z_base": 0.0, "finger_status": {}, "finger_timers": {}},
    "Right": {"calibrated": False, "z_base": 0.0, "finger_status": {}, "finger_timers": {}}
}

# Inicializa status
for hand in ["Left", "Right"]:
    for fid in ACTIVE_FINGERS:
        hands_state[hand]["finger_status"][fid] = "IDLE"
        hands_state[hand]["finger_timers"][fid] = 0.0

# ------------------------
# FUNÇÕES DE UI (DESENHO)
# ------------------------
def draw_piano_ui(frame):
    h, w, _ = frame.shape
    overlay = frame.copy()
    key_width = w / NUM_KEYS
    
    for i, key in enumerate(PIANO_KEYS):
        x1 = int(i * key_width)
        x2 = int((i + 1) * key_width)
        
        # Se foi tocada recentemente, pinta o retângulo
        if (time.time() - key["last_hit"]) < 0.2:
            cv2.rectangle(overlay, (x1, 0), (x2, h), COLOR_KEY_HIT, -1)
        
        # Desenha divisórias
        cv2.line(overlay, (x1, 0), (x1, h), COLOR_KEY_BORDER, 1)
        
        # Opcional: Nota no rodapé
        # cv2.putText(overlay, str(key["note"]), (x1+5, h-20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200,200,200), 1)

    cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)

# ------------------------
# LÓGICA DO DEDO
# ------------------------
def processar_dedo(label, fid, z_current, z_base, x_norm, frame_w, frame):
    state = hands_state[label]
    status = state["finger_status"][fid]
    last_action_time = state["finger_timers"][fid]
    
    # Diferença de altura
    diff = z_base - z_current 
    current_time = time.time()

    # --- MÁQUINA DE ESTADOS ---

    if status == "IDLE":
        if diff > LIFT_THRESHOLD:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    elif status == "ARMED":
        # Timeout
        if (current_time - last_action_time) > ARMED_TIMEOUT:
            state["finger_status"][fid] = "IDLE"
        
        # BATIDA DETECTADA
        elif diff < TOUCH_THRESHOLD:
            # 1. Calcular qual tecla foi tocada baseado no X normalizado (0.0 a 1.0)
            key_idx = int(x_norm * NUM_KEYS)
            
            # Proteção para não sair do array
            key_idx = max(0, min(key_idx, NUM_KEYS - 1))
            
            # 2. Pegar a nota e tocar
            key_data = PIANO_KEYS[key_idx]
            audio_queue.put(key_data["note"])
            
            # 3. Atualizar visual
            key_data["last_hit"] = current_time
            
            # Resetar dedo
            state["finger_status"][fid] = "IDLE"
            
            # Feedback pontual
            cx = int(x_norm * frame_w)
            # cy não temos exato aqui sem passar, mas podemos desenhar no topo ou usar logica extra
            # Vamos apenas desenhar na UI global

# ------------------------
# LOOP PRINCIPAL
# ------------------------
def main_thread():
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        max_num_hands=2, 
        model_complexity=0, # Mais rápido
        min_detection_confidence=0.5, 
        min_tracking_confidence=0.5
    )
    
    # Tenta abrir câmera rápido
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened(): cap = cv2.VideoCapture(0)

    is_calibrating = False
    calib_start_time = 0
    CALIB_DURATION = 3.0

    print(">>> PIANO ESPACIAL 20 TECLAS")
    print(">>> Espaço: Calibrar | ESC: Sair")

    while True:
        ret, frame = cap.read()
        if not ret: break

        # Espelhar (Mão direita na tela -> lado direito do piano = Agudos)
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        
        # Desenhar Teclas
        draw_piano_ui(frame)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        # Calibração
        if is_calibrating:
            remaining = CALIB_DURATION - (time.time() - calib_start_time)
            if remaining > 0:
                cv2.putText(frame, f"MAOS NA MESA: {remaining:.1f}", (50, h//2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            else:
                is_calibrating = False
                if results.multi_hand_landmarks:
                    for idx, lm in enumerate(results.multi_hand_landmarks):
                        lbl = results.multi_handedness[idx].classification[0].label
                        # Média Z de todos os dedos
                        avg_z = sum([lm.landmark[i].z for i in ACTIVE_FINGERS]) / len(ACTIVE_FINGERS)
                        hands_state[lbl]["z_base"] = avg_z
                        hands_state[lbl]["calibrated"] = True
                    print("Calibrado!")

        # Processamento das Mãos
        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                state = hands_state[lbl]
                
                if not state["calibrated"]:
                    cx_lbl = w - 200 if lbl == "Right" else 20
                    cv2.putText(frame, "NAO CALIBRADO", (cx_lbl, 50), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
                    continue

                # Verificar todos os dedos ativos
                for fid in ACTIVE_FINGERS:
                    finger = lm.landmark[fid]
                    
                    # Desenha bolinha para ver onde o dedo está
                    cx, cy = int(finger.x * w), int(finger.y * h)
                    
                    # Cor baseada no estado
                    status = state["finger_status"][fid]
                    color = (100,100,100)
                    if status == "ARMED": color = (0, 255, 255)
                    
                    cv2.circle(frame, (cx, cy), 5, color, -1)
                    
                    # Processa lógica de toque passando a posição X normalizada (0.0 a 1.0)
                    processar_dedo(lbl, fid, finger.z, state["z_base"], finger.x, w, frame)

        cv2.imshow("Virtual Piano 20 Keys", frame)
        
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