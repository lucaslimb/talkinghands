import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import numpy as np

# ------------------------
# CONFIGURAÇÕES (VISÃO FRONTAL)
# ------------------------
# Y vai de 0.0 (Topo) a 1.0 (Fundo/Baixo)
# Altura que o dedo precisa subir ACIMA da linha para ARMAR (ex: 0.1 = 10% da tela)
LIFT_THRESHOLD = 0.025  

# Tolerância para validar o toque na linha (ajuste fino)
TOUCH_TOLERANCE = 0.003

# Tempo limite
ARMED_TIMEOUT = 2.5    

NUM_KEYS = 30
ACTIVE_FINGERS = [4, 8, 12, 16, 20] 

# Cores (BGR)
COLOR_TABLE_LINE = (0, 255, 0)     # Verde
COLOR_KEY_DIVIDER = (60, 60, 60)   # Cinza escuro
COLOR_HIT = (0, 255, 255)          # Amarelo
COLOR_ARMED = (0, 165, 255)        # Laranja

# ------------------------
# GERAR TECLAS (Dó Maior)
# ------------------------
SCALE_INTERVALS = [0, 2, 4, 5, 7, 9, 11] 
BASE_NOTE = 48 # C3

PIANO_KEYS = []
for i in range(NUM_KEYS):
    octave = i // 7
    note_idx = i % 7
    note_val = BASE_NOTE + (octave * 12) + SCALE_INTERVALS[note_idx]
    PIANO_KEYS.append({"note": note_val, "last_hit": 0})

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
        fs.noteon(0, note, 127) # Velocity máxima para impacto

threading.Thread(target=audio_thread, daemon=True).start()

# ------------------------
# ESTADO GLOBAL
# ------------------------
global_state = {
    "table_y": 0.85, # Altura padrão da mesa (85% da tela, lá embaixo)
    "calibrated": False
}

hands_state = {
    "Left":  {"finger_status": {}, "finger_timers": {}},
    "Right": {"finger_status": {}, "finger_timers": {}}
}

# Inicializa
for hand in ["Left", "Right"]:
    for fid in ACTIVE_FINGERS:
        hands_state[hand]["finger_status"][fid] = "IDLE"
        hands_state[hand]["finger_timers"][fid] = 0.0

# ------------------------
# LÓGICA GEOMÉTRICA (EIXO Y)
# ------------------------
def processar_dedo(label, fid, y_current, x_current, table_y, cx, cy, frame):
    state = hands_state[label]
    status = state["finger_status"][fid]
    last_action_time = state["finger_timers"][fid]
    current_time = time.time()
    
    h, w, _ = frame.shape
    
    # Distância do dedo em relação à linha da mesa
    # table_y é maior (mais baixo). y_current é menor (mais alto).
    dist_above_table = table_y - y_current

    cor_dedo = (100, 100, 100) # Cinza IDLE

    # --- MÁQUINA DE ESTADOS ---

    if status == "IDLE":
        # Se subiu o suficiente acima da linha
        if dist_above_table > LIFT_THRESHOLD:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    elif status == "ARMED":
        cor_dedo = COLOR_ARMED
        
        # Visual: Linha elástica ligando dedo à mesa
        table_px = int(table_y * h)
        cv2.line(frame, (cx, cy), (cx, table_px), COLOR_ARMED, 1)

        # 1. Timeout: Se demorou demais lá em cima
        if (current_time - last_action_time) > ARMED_TIMEOUT:
            state["finger_status"][fid] = "IDLE"
            # Feedback visual de cancelamento
            cv2.circle(frame, (cx, cy), 8, (255, 0, 255), 2)

        # 2. TOQUE: Cruzou a linha da mesa para baixo
        elif y_current >= (table_y - TOUCH_TOLERANCE):
            # Determinar qual tecla (baseado no X)
            key_idx = int(x_current * NUM_KEYS)
            key_idx = max(0, min(key_idx, NUM_KEYS - 1))
            
            # Tocar nota
            key_data = PIANO_KEYS[key_idx]
            audio_queue.put(key_data["note"])
            key_data["last_hit"] = current_time
            
            # Resetar
            state["finger_status"][fid] = "IDLE"
            
            # Visual de Impacto na linha da mesa
            hit_x = cx
            hit_y = int(table_y * h)
            cv2.circle(frame, (hit_x, hit_y), 20, COLOR_HIT, -1)

    # Desenha a ponta do dedo com um contorno para destacar se a imagem estiver ruim
    cv2.circle(frame, (cx, cy), 6, cor_dedo, -1)
    cv2.circle(frame, (cx, cy), 8, (0,0,0), 1) # Contorno preto

# ------------------------
# DESENHO DA INTERFACE (TECLAS + MESA)
# ------------------------
def draw_ui(frame, table_y):
    h, w, _ = frame.shape
    overlay = frame.copy()
    
    # 1. Desenhar Teclas (Fundo)
    key_width = w / NUM_KEYS
    table_px = int(table_y * h)
    
    for i, key in enumerate(PIANO_KEYS):
        x1 = int(i * key_width)
        x2 = int((i + 1) * key_width)
        
        # Se tecla tocada recentemente
        if (time.time() - key["last_hit"]) < 0.2:
            # Pinta a coluna inteira ou só a parte de baixo? Vamos pintar tudo levemente
            cv2.rectangle(overlay, (x1, 0), (x2, h), COLOR_HIT, -1)
        
        # Divisórias das teclas (apenas visuais)
        cv2.line(overlay, (x1, 0), (x1, h), COLOR_KEY_DIVIDER, 1)

    # 2. Desenhar a LINHA DA MESA (Fundamental)
    cv2.line(overlay, (0, table_px), (w, table_px), COLOR_TABLE_LINE, 3)
    cv2.putText(overlay, "LINHA DA MESA (Espaco para ajustar)", (10, table_px - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_TABLE_LINE, 1)

    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

# ------------------------
# MAIN LOOP
# ------------------------
def main_thread():
    mp_hands = mp.solutions.hands
    
    # --- AJUSTE CRÍTICO PARA VISÃO FRONTAL ---
    # model_complexity=1: Usa o modelo mais pesado e preciso (melhor para oclusão)
    # min_detection_confidence=0.3: Aceita mãos mesmo que a IA esteja "na dúvida" (ajuda em ângulos ruins)
    # min_tracking_confidence=0.4: Tenta manter o rastreio mesmo se falhar um pouco
    hands = mp_hands.Hands(
        max_num_hands=2, 
        model_complexity=1, 
        min_detection_confidence=0.3, 
        min_tracking_confidence=0.4
    )
    
    mp_draw = mp.solutions.drawing_utils
    
    # Tenta backend rápido
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened(): cap = cv2.VideoCapture(0)

    is_calibrating = False
    calib_start_time = 0
    CALIB_DURATION = 3.0

    print(">>> PIANO FRONTAL (MODO ROBUSTO)")
    print(">>> DICA: Incline a câmera levemente para ver os nós dos dedos.")

    while True:
        ret, frame = cap.read()
        if not ret: break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        
        draw_ui(frame, global_state["table_y"])

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        # Feedback visual se perdeu as mãos
        if not results.multi_hand_landmarks:
             cv2.putText(frame, "PROCURANDO MAOS...", (w//2 - 150, h//2), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        # --- CALIBRAÇÃO ---
        if is_calibrating:
            remaining = CALIB_DURATION - (time.time() - calib_start_time)
            if remaining > 0:
                cv2.putText(frame, f"CALIBRANDO... MANTENHA NA MESA: {remaining:.1f}", (50, h//2), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)
            else:
                is_calibrating = False
                if results.multi_hand_landmarks:
                    total_y = 0
                    count = 0
                    # Pega a média Y de todas as pontas dos dedos
                    for lm in results.multi_hand_landmarks:
                        for fid in ACTIVE_FINGERS:
                            total_y += lm.landmark[fid].y
                            count += 1
                    
                    if count > 0:
                        # Define a linha da mesa baseada na posição dos dedos
                        new_table_y = total_y / count
                        # Adiciona um offset minúsculo (0.02) para a linha ficar logo abaixo da ponta do dedo
                        global_state["table_y"] = min(new_table_y + 0.01, 0.95) 
                        global_state["calibrated"] = True
                        print(f"Mesa calibrada em Y={global_state['table_y']:.2f}")
                else:
                    print("Nenhuma mão detectada durante calibração.")

        # --- PROCESSAMENTO ---
        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                
                # Desenha o esqueleto (ajuda a ver se a IA pegou certo)
                mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
                
                if not global_state["calibrated"]:
                    cv2.putText(frame, "PRECISA CALIBRAR (TECLA ESPACO)", (w//2 - 200, 50), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)

                for fid in ACTIVE_FINGERS:
                    finger = lm.landmark[fid]
                    cx, cy = int(finger.x * w), int(finger.y * h)
                    
                    processar_dedo(lbl, fid, finger.y, finger.x, global_state["table_y"], cx, cy, frame)

        cv2.imshow("Frontal Piano", frame)
        
        k = cv2.waitKey(1)
        if k == 32: # Espaço inicia calibração
            is_calibrating = True
            calib_start_time = time.time()
            for key in hands_state:
                for fid in ACTIVE_FINGERS:
                    hands_state[key]["finger_status"][fid] = "IDLE"
        
        if k == 27: break

    cap.release()
    cv2.destroyAllWindows()
    audio_queue.put(None)

if __name__ == "__main__":
    main_thread()