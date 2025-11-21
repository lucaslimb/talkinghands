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
LIFT_THRESHOLD = 0.02   
TOUCH_TOLERANCE = 0.005 
RELEASE_THRESHOLD = 0.015 
MIN_NOTE_DURATION = 0.1  # Reduzi levemente para evitar travamentos
ARMED_TIMEOUT = 2.5    

# Tempo máximo que um dedo pode ficar "sumido" antes de cortarmos o som (Watchdog)
MAX_MISSING_TIME = 0.1 

NUM_KEYS = 30
ACTIVE_FINGERS = [4, 8, 12, 16, 20] 

# Cores
COLOR_TABLE_LINE = (0, 255, 0)     
COLOR_TABLE_FRONT = (30, 30, 30) 
COLOR_KEY_DIVIDER = (100, 100, 100)
COLOR_HIT = (0, 255, 255)          
COLOR_ARMED = (0, 165, 255)        
COLOR_HOLD = (0, 200, 0)           
SUSTAIN_DECAY = 0.8
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
    PIANO_KEYS.append({"note": note_val, "last_hit": 0, "is_active": False, "off_timer": 0})

try:
    fs = fluidsynth.Synth()
    fs.start(driver="dsound") 
    sfid = fs.sfload(r"sounds\universal\module_master.sf2")
except Exception as e:
    print(f"ERRO AUDIO: {e}")

# ------------------------
audio_queue = queue.Queue()

def audio_thread():
    while True:
        item = audio_queue.get()
        if item is None: 
            break
        
        action, note = item
        if action == "on":
            fs.noteon(0, note, 127)
        elif action == "off":
            fs.noteoff(0, note)

threading.Thread(target=audio_thread, daemon=True).start()

    # Dicionário de instrumentos do seu SF2 (exemplo parcial)
instruments = {
    "SynthPiano": (0, 6),
    "Honky-Tonk": (0, 2),
    "Square": (0, 106),
    "Crystal": (1, 41),
    "EP1": (0, 4),
    "WarmPad": (1, 6),
    "Oohs2": (0, 87)
}

def select_instrument_by_name(name, channel=0):
    """
    Seleciona o instrumento pelo nome, usando o banco e programa do dicionário
    """
    if name not in instruments:
        print(f"Instrumento '{name}' não encontrado. Usando padrão (0,0).")
        bank, preset = 0, 0
    else:
        bank, preset = instruments[name]
    fs.program_select(channel, sfid, bank, preset)

# ------------------------
# Exemplo de uso:
select_instrument_by_name("Honky-Tonk")

# ------------------------
# ESTADO GLOBAL
# ------------------------
global_state = {
    "table_y": 0.80, 
    "calibrated": False
}

hands_state = {
    "Left":  {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}},
    "Right": {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}}
}

for hand in ["Left", "Right"]:
    for fid in ACTIVE_FINGERS:
        hands_state[hand]["finger_status"][fid] = "IDLE"
        hands_state[hand]["finger_timers"][fid] = 0.0
        hands_state[hand]["active_notes"][fid] = None
        hands_state[hand]["last_seen"][fid] = 0.0

# ------------------------
# LÓGICA GEOMÉTRICA (ADAPTADA DO SEU CÓDIGO)
# ------------------------
# ------------------------
# VERIFICAÇÃO DE INTEGRIDADE (ANTI-GHOST NOTES)
# ------------------------
def check_active_keys_integrity():
    """
    Verifica se há teclas ativas que NÃO possuem nenhum dedo no estado TOUCHING reivindicando elas.
    Se houver, desliga o som imediatamente.
    """
    current_time = time.time()
    # 1. Coletar todas as notas que os dedos juram que estão tocando agora
    notes_currently_touched = set()

    for hand in ["Left", "Right"]:
        state = hands_state[hand]
        for fid in ACTIVE_FINGERS:
            # Só nos importamos se o dedo diz explicitamente que está TOUCHING
            if state["finger_status"][fid] == "TOUCHING":
                note = state["active_notes"][fid]
                if note is not None:
                    notes_currently_touched.add(note)

    # 2. Comparar com as teclas físicas do piano
    for key in PIANO_KEYS:
        if key["is_active"]:
            # CASO A: O dedo ainda está na tecla (ou voltou rápido)
            if key["note"] in notes_currently_touched:
                key["off_timer"] = 0  # Reseta o timer, a tecla está viva
            
            # CASO B: O dedo saiu (ou a câmera perdeu o dedo)
            else:
                # Se é a primeira vez que notamos que o dedo sumiu, inicia o timer
                if key["off_timer"] == 0:
                    key["off_timer"] = current_time
                
                # Se já passou o tempo de tolerância (Sustain), desliga
                elif (current_time - key["off_timer"]) > SUSTAIN_DECAY:
                    audio_queue.put(("off", key["note"]))
                    key["is_active"] = False
                    key["off_timer"] = 0 # Reseta para o futuro
                    # O noteoff do FluidSynth já faz um fade-out natural do instrumento

def processar_dedo(label, fid, y_current, x_current, table_y, cx, cy, frame, h_frame):
    state = hands_state[label]
    status = state["finger_status"][fid]
    
    last_action_time = state["finger_timers"][fid]
    current_time = time.time()
    
    # ATUALIZAÇÃO CRÍTICA: Marca que o dedo foi visto agora
    state["last_seen"][fid] = current_time
    
    dist_above_table = table_y - y_current

    # --- SANITY CHECK (Correção de Loop) ---
    # Se o sistema diz que NÃO está tocando, mas tem nota registrada: MATA A NOTA.
    if status != "TOUCHING" and state["active_notes"][fid] is not None:
        note_to_kill = state["active_notes"][fid]
        audio_queue.put(("off", note_to_kill))
        for k in PIANO_KEYS:
            if k["note"] == note_to_kill: 
                k["is_active"] = False
                break
        state["active_notes"][fid] = None

    # --- MÁQUINA DE ESTADOS ---

    if status == "IDLE":
        if dist_above_table > LIFT_THRESHOLD:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    elif status == "ARMED":
        if (current_time - last_action_time) > ARMED_TIMEOUT:
            state["finger_status"][fid] = "IDLE"
            
        elif y_current >= (table_y - TOUCH_TOLERANCE):
            key_idx = int(x_current * NUM_KEYS)
            key_idx = max(0, min(key_idx, NUM_KEYS - 1))
            
            key_data = PIANO_KEYS[key_idx]
            note = key_data["note"]
            
            audio_queue.put(("on", note))
            state["active_notes"][fid] = note
            state["finger_status"][fid] = "TOUCHING"
            state["finger_timers"][fid] = current_time 
            
            key_data["last_hit"] = current_time
            key_data["is_active"] = True
            
            cv2.circle(frame, (cx, int(table_y * h_frame)), 15, COLOR_HIT, -1)

    elif status == "TOUCHING":
        active_note = state["active_notes"][fid]
        hit_time = state["finger_timers"][fid]
        
        # Se por algum milagre active_note for None mas estamos em TOUCHING, reseta
        if active_note is None:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time
            return

        # --- 1. GLISSANDO ---
        current_key_idx = int(x_current * NUM_KEYS)
        current_key_idx = max(0, min(current_key_idx, NUM_KEYS - 1))
        new_note = PIANO_KEYS[current_key_idx]["note"]
        
        if new_note != active_note:
            # Desliga nota anterior
            audio_queue.put(("off", active_note))
            for k in PIANO_KEYS:
                if k["note"] == active_note: k["is_active"] = False; break

            # Liga nova nota
            audio_queue.put(("on", new_note))
            state["active_notes"][fid] = new_note
            state["finger_timers"][fid] = current_time # Reseta timer para nova nota
            
            PIANO_KEYS[current_key_idx]["last_hit"] = current_time
            PIANO_KEYS[current_key_idx]["is_active"] = True

        # --- 2. RELEASE ---
        time_held = current_time - hit_time

        # Condição de soltura: subiu o suficiente E passou o tempo mínimo
        # ADIÇÃO: Se subiu MUITO (2x threshold), solta imediatamente ignorando tempo mínimo (segurança)
        force_release = dist_above_table > (RELEASE_THRESHOLD * 2.0)
        normal_release = (dist_above_table > RELEASE_THRESHOLD) and (time_held > MIN_NOTE_DURATION)

        if force_release or normal_release:
            audio_queue.put(("off", active_note))
            for k in PIANO_KEYS:
                if k["note"] == active_note: k["is_active"] = False; break
            
            state["active_notes"][fid] = None
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    # Desenho
    color = COLOR_ARMED if status == "ARMED" else (100,100,100)
    if status == "TOUCHING": color = COLOR_HOLD
    cv2.circle(frame, (cx, cy), 5, color, -1)

# ------------------------
# FUNÇÃO DE SEGURANÇA (WATCHDOG)
# ------------------------
def check_lost_fingers():
    """Verifica se algum dedo sumiu enquanto tocava"""
    current_time = time.time()
    
    for hand in ["Left", "Right"]:
        state = hands_state[hand]
        for fid in ACTIVE_FINGERS:
            # Se a nota está ativa mas o dedo não é visto há muito tempo
            if state["active_notes"][fid] is not None:
                if (current_time - state["last_seen"][fid]) > MAX_MISSING_TIME:
                    
                    note = state["active_notes"][fid]
                    audio_queue.put(("off", note))
                    
                    for k in PIANO_KEYS:
                        if k["note"] == note: k["is_active"] = False; break
                    
                    state["active_notes"][fid] = None
                    state["finger_status"][fid] = "IDLE"
                    # print(f"Watchdog limpou dedo {fid}")

# ------------------------
# UI
# ------------------------
def draw_ui_fast(frame, table_y, w, h):
    table_px = int(table_y * h)
    key_width = w / NUM_KEYS
    
    # Cria uma cópia para fazer o efeito transparente (overlay)
    overlay = frame.copy()
    
    # Desenha a linha da mesa (sólida)
    cv2.line(frame, (0, table_px), (w, table_px), COLOR_TABLE_LINE, 2)
    
    for i, key in enumerate(PIANO_KEYS):
        x1 = int(i * key_width)
        cv2.line(frame, (x1, table_px), (x1, h), COLOR_KEY_DIVIDER, 1)
        
        # Se a tecla estiver ativa, desenha no OVERLAY, não no frame direto
        if key["is_active"] or (time.time() - key["last_hit"]) < 0.15:
            x2 = int((i + 1) * key_width)
            # Desenha retângulo no overlay
            cv2.rectangle(overlay, (x1, table_px), (x2, h), COLOR_HIT, -1)
            
    # Mistura o overlay com o frame original
    # 0.7 = 70% imagem original, 0.3 = 30% do retângulo amarelo
    cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)

# ------------------------
# MAIN LOOP
# ------------------------
def main_thread():
    hands = mp.solutions.hands.Hands(
        max_num_hands=2, 
        model_complexity=0, 
        min_detection_confidence=0.3, 
        min_tracking_confidence=0.3
    )
    
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened(): cap = cv2.VideoCapture(0)
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    is_calibrating = False
    calib_start_time = 0
    
    print(">>> PIANO PROTEGIDO (ANTI-LOOP)")

    while True:
        ret, frame = cap.read()
        if not ret: break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape 
        
        draw_ui_fast(frame, global_state["table_y"], w, h)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

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

        if results.multi_hand_landmarks:
            for idx, lm in enumerate(results.multi_hand_landmarks):
                lbl = results.multi_handedness[idx].classification[0].label
                
                if not global_state["calibrated"]:
                    cv2.putText(frame, "[ESPACO] CALIBRAR", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

                for fid in ACTIVE_FINGERS:
                    finger = lm.landmark[fid]
                    cx, cy = int(finger.x * w), int(finger.y * h)
                    processar_dedo(lbl, fid, finger.y, finger.x, global_state["table_y"], cx, cy, frame, h)

        # --- SEGURANÇA 1: Dedos que sumiram da câmera ---
        check_lost_fingers()

        # --- SEGURANÇA 2: Teclas ativas sem dono (NOVA FUNÇÃO) ---
        check_active_keys_integrity()   # <--- ADICIONE AQUI

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