import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time

# ------------------------
# CONFIGURAÇÕES
# ------------------------
LIFT_THRESHOLD = 0.025   # Altura para armar
TOUCH_THRESHOLD = 0.015 # Altura para bater (tocar)
ARMED_TIMEOUT = 1     # Segundos para cancelar se não bater

ACTIVE_FINGERS = [4, 8, 12, 16, 20] 
# Mapeamento de Notas (Escala Pentatônica para soar bem)
NOTE_MAP = {
    "Left":  {20: 48, 16: 50, 12: 52, 8: 55, 4: 57}, # Graves
    "Right": {4: 60, 8: 62, 12: 64, 16: 67, 20: 69}  # Agudos
}

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
fs = fluidsynth.Synth()
fs.start(driver="dsound") 
sfid = fs.sfload("Retro_Synth_PC.sf2") 
fs.program_select(0, sfid, 0, 0)

audio_queue = queue.Queue()

def audio_thread():
    while True:
        item = audio_queue.get()
        if item is None: break
        note = item
        fs.noteon(0, note, 120)

threading.Thread(target=audio_thread, daemon=True).start()

# ------------------------
# ESTADO GLOBAL
# ------------------------
# Agora incluímos 'finger_timers' para controlar o timeout
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
    
    # Diferença de altura (Positivo = levantado, Perto de 0 = na mesa)
    diff = z_base - z_current 
    
    # Cores padrão
    cor = (100, 100, 100) # Cinza (Idle)
    raio = 6
    
    current_time = time.time()

    # --- ESTADO 1: IDLE (Descansando na mesa) ---
    if status == "IDLE":
        # Se subir muito, ARMA o gatilho
        if diff > LIFT_THRESHOLD:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time # Marca a hora que subiu

    # --- ESTADO 2: ARMED (Levantado, pronto para bater) ---
    elif status == "ARMED":
        cor = (0, 255, 255) # Amarelo
        raio = 8
        
        # VERIFICAÇÃO DE TIMEOUT: Se demorou muito pra descer, reseta
        if (current_time - last_action_time) > ARMED_TIMEOUT:
            state["finger_status"][fid] = "IDLE"
            print(f"Timeout: Dedo {fid} resetado.")
            # Efeito visual rápido de cancelamento (roxo)
            cv2.circle(frame, (cx, cy), 10, (255, 0, 255), 2)
        
        # VERIFICAÇÃO DE BATIDA: Se desceu rápido (voltou pra mesa)
        elif diff < TOUCH_THRESHOLD:
            # Toca a nota
            note = NOTE_MAP[label][fid]
            audio_queue.put(note)
            
            # Volta para IDLE
            state["finger_status"][fid] = "IDLE"
            
            # Visual Verde (Sucesso)
            cv2.circle(frame, (cx, cy), 15, (0, 255, 0), -1) 
            cv2.putText(frame, str(note), (cx-20, cy-20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    # Desenha o estado atual
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

        # --- 1. INVERSÃO / ESPELHAMENTO ---
        frame = cv2.flip(frame, 1)
        
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        # --- LÓGICA DE CALIBRAÇÃO ---
        if is_calibrating:
            remaining = CALIB_DURATION - (time.time() - calib_start_time)
            if remaining > 0:
                cv2.putText(frame, f"MANTENHA MAOS NA MESA: {remaining:.1f}", (50, h//2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            else:
                is_calibrating = False
                if results.multi_hand_landmarks:
                    hands_found = []
                    for idx, lm in enumerate(results.multi_hand_landmarks):
                        lbl = results.multi_handedness[idx].classification[0].label
                        hands_found.append(lbl)
                        # Calcula média do Z
                        avg_z = sum([lm.landmark[i].z for i in ACTIVE_FINGERS]) / len(ACTIVE_FINGERS)
                        hands_state[lbl]["z_base"] = avg_z
                        hands_state[lbl]["calibrated"] = True
                    print(f"Calibrado: {hands_found}")
                else:
                    print("Erro: Nenhuma mão vista no final do timer.")

        # --- PROCESSAMENTO ---
        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                state = hands_state[lbl]
                
                mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
                
                # --- CORREÇÃO AQUI ---
                # Definimos a posição X do texto ANTES de usar no putText
                # Se for "Right" (mão direita), texto na direita. "Left", na esquerda.
                cx_lbl = w - 250 if lbl == "Right" else 20

                if not state["calibrated"]:
                    cv2.putText(frame, "NAO CALIBRADO", (cx_lbl, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
                    continue

                for fid in ACTIVE_FINGERS:
                    lm_finger = lm.landmark[fid]
                    cx, cy = int(lm_finger.x * w), int(lm_finger.y * h)
                    
                    processar_dedo(lbl, fid, lm_finger.z, state["z_base"], cx, cy, frame)

        # Instruções
        cv2.putText(frame, "[ESPACO] Calibrar | [ESC] Sair", (10, h-20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
        
        cv2.imshow("Teclado Invisivel", frame)
        
        k = cv2.waitKey(1)
        if k == 32: # Espaço
            is_calibrating = True
            calib_start_time = time.time()
            for key in hands_state:
                hands_state[key]["calibrated"] = False
                for fid in ACTIVE_FINGERS:
                    hands_state[key]["finger_status"][fid] = "IDLE"
        
        if k == 27: break # Esc

    cap.release()
    cv2.destroyAllWindows()
    audio_queue.put(None)

if __name__ == "__main__":
    main_thread()