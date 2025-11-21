import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import numpy as np

import settings

# ------------------------
# CONFIGURAÇÕES
# ------------------------
LIFT_THRESHOLD = 0.02
TOUCH_TOLERANCE = 0.005
RELEASE_THRESHOLD = 0.015
MIN_NOTE_DURATION = 0.1
ARMED_TIMEOUT = 2.5

SUSTAIN_DECAY = getattr(settings, 'SUSTAIN_DECAY', 0.8)

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

# ------------------------
# AUDIO SETUP (GLOBAL SYNTH)
# ------------------------
# Mantemos o Synth global para não recarregar SF2s pesados a cada reinício
audio_queue = queue.Queue()
loaded_sfids = {}

try:
    fs = fluidsynth.Synth()
    fs.start(driver="dsound")

    print(">>> Carregando bancos de som...")
    for nickname, path in settings.SF2_PATHS.items():
        sfid = fs.sfload(path)
        if sfid == -1:
            print(f"ERRO: Não foi possível carregar {path}")
        else:
            loaded_sfids[nickname] = sfid
            print(f"Carregado: {nickname} (ID: {sfid})")

except Exception as e:
    print(f"ERRO CRÍTICO DE AUDIO: {e}")
    exit()

def select_instrument_by_name(name, channel=0):
    if name not in settings.INSTRUMENTS:
        print(f"Instrumento '{name}' não encontrado.")
        return

    sf_nickname, bank, preset = settings.INSTRUMENTS[name]
    target_sfid = loaded_sfids.get(sf_nickname)
    if target_sfid is None:
        print(f"ERRO: O arquivo '{sf_nickname}' para este som não foi carregado corretamente.")
        return

    print(f">>> SOM: {name} | ARQUIVO: {sf_nickname} | ID: {target_sfid} | B: {bank} P: {preset}")
    fs.program_select(channel, target_sfid, bank, preset)

# ------------------------
# Thread de áudio (Lógica)
# ------------------------
def audio_thread_target():
    """Consome a fila e toca notas. Encerra se receber None."""
    while True:
        item = audio_queue.get()
        if item is None:
            break
        action, note = item
        try:
            if action == "on":
                fs.noteon(0, note, 127)
            elif action == "off":
                fs.noteoff(0, note)
        except Exception:
            pass

# NOTA: Removemos o start() global da thread aqui para iniciá-la dentro do start_piano

# ------------------------
# ESTADOS
# ------------------------
SCALE_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
BASE_NOTE = 48  # C3

PIANO_KEYS = []
for i in range(NUM_KEYS):
    octave = i // 7
    note_idx = i % 7
    note_val = BASE_NOTE + (octave * 12) + SCALE_INTERVALS[note_idx]
    PIANO_KEYS.append({"note": note_val, "last_hit": 0, "is_active": False, "off_timer": 0})

# Mantemos global para persistir calibração entre resets
global_state = {"table_y": 0.80, "calibrated": False}

hands_state = {
    "Left":  {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}},
    "Right": {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}}
}

def reset_hands_state():
    """Reseta o estado dos dedos para evitar travamentos ao reiniciar"""
    for hand in ["Left", "Right"]:
        for fid in ACTIVE_FINGERS:
            hands_state[hand]["finger_status"][fid] = "IDLE"
            hands_state[hand]["finger_timers"][fid] = 0.0
            hands_state[hand]["active_notes"][fid] = None
            hands_state[hand]["last_seen"][fid] = 0.0

# ------------------------
# LÓGICA DE PROCESSAMENTO
# ------------------------
def check_active_keys_integrity():
    current_time = time.time()
    notes_currently_touched = set()

    for hand in ["Left", "Right"]:
        state = hands_state[hand]
        for fid in ACTIVE_FINGERS:
            if state["finger_status"][fid] == "TOUCHING":
                note = state["active_notes"][fid]
                if note is not None:
                    notes_currently_touched.add(note)

    for key in PIANO_KEYS:
        if key["is_active"]:
            if key["note"] in notes_currently_touched:
                key["off_timer"] = 0
            else:
                if key["off_timer"] == 0:
                    key["off_timer"] = current_time
                elif (current_time - key["off_timer"]) > SUSTAIN_DECAY:
                    audio_queue.put(("off", key["note"]))
                    key["is_active"] = False
                    key["off_timer"] = 0

def processar_dedo(label, fid, y_current, x_current, table_y, cx, cy, frame, h_frame):
    state = hands_state[label]
    status = state["finger_status"][fid]
    last_action_time = state["finger_timers"][fid]
    current_time = time.time()
    state["last_seen"][fid] = current_time
    dist_above_table = table_y - y_current

    if status != "TOUCHING" and state["active_notes"][fid] is not None:
        note_to_kill = state["active_notes"][fid]
        audio_queue.put(("off", note_to_kill))
        for k in PIANO_KEYS:
            if k["note"] == note_to_kill:
                k["is_active"] = False
                break
        state["active_notes"][fid] = None

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
        if active_note is None:
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time
            return

        current_key_idx = int(x_current * NUM_KEYS)
        current_key_idx = max(0, min(current_key_idx, NUM_KEYS - 1))
        new_note = PIANO_KEYS[current_key_idx]["note"]

        if new_note != active_note:
            audio_queue.put(("off", active_note))
            for k in PIANO_KEYS:
                if k["note"] == active_note:
                    k["is_active"] = False
                    break
            audio_queue.put(("on", new_note))
            state["active_notes"][fid] = new_note
            state["finger_timers"][fid] = current_time
            PIANO_KEYS[current_key_idx]["last_hit"] = current_time
            PIANO_KEYS[current_key_idx]["is_active"] = True

        time_held = current_time - hit_time
        force_release = dist_above_table > (RELEASE_THRESHOLD * 2.0)
        normal_release = (dist_above_table > RELEASE_THRESHOLD) and (time_held > MIN_NOTE_DURATION)

        if force_release or normal_release:
            # audio_queue.put(("off", active_note))
            # for k in PIANO_KEYS:
            #     if k["note"] == active_note:
            #         k["is_active"] = False
            #         break
            state["active_notes"][fid] = None
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    color = COLOR_ARMED if status == "ARMED" else (100,100,100)
    if status == "TOUCHING":
        color = COLOR_HOLD
    cv2.circle(frame, (cx, cy), 5, color, -1)

def check_lost_fingers():
    current_time = time.time()
    for hand in ["Left", "Right"]:
        state = hands_state[hand]
        for fid in ACTIVE_FINGERS:
            if state["active_notes"][fid] is not None:
                if (current_time - state["last_seen"][fid]) > MAX_MISSING_TIME:
                    note = state["active_notes"][fid]
                    audio_queue.put(("off", note))
                    for k in PIANO_KEYS:
                        if k["note"] == note:
                            k["is_active"] = False
                            break
                    state["active_notes"][fid] = None
                    state["finger_status"][fid] = "IDLE"

def draw_ui_fast(frame, table_y, w, h):
    table_px = int(table_y * h)
    key_width = w / NUM_KEYS
    overlay = frame.copy()
    cv2.line(frame, (0, table_px), (w, table_px), COLOR_TABLE_LINE, 2)
    for i, key in enumerate(PIANO_KEYS):
        x1 = int(i * key_width)
        cv2.line(frame, (x1, table_px), (x1, h), COLOR_KEY_DIVIDER, 1)
        if key["is_active"] or (time.time() - key["last_hit"]) < 0.15:
            x2 = int((i + 1) * key_width)
            cv2.rectangle(overlay, (x1, table_px), (x2, h), COLOR_HIT, -1)
    cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)

# ------------------------
# FUNÇÃO PÚBLICA (START)
# ------------------------
def start_piano(chosen_instrument, user_sustain=None):
    """
    Inicializa o loop do piano. Ao sair (ESC), limpa recursos e retorna ao caller.
    """
    # 1. Configura Sustain
    if user_sustain is not None and user_sustain > 0:
        global SUSTAIN_DECAY
        SUSTAIN_DECAY = user_sustain
        print(f">>> Sustain configurado: {SUSTAIN_DECAY}s")

    # 2. Seleciona Som
    select_instrument_by_name(chosen_instrument)

    # 3. Inicia Thread de Áudio para esta sessão
    # Usamos daemon=True para garantir que morra se o main crashar
    audio_t = threading.Thread(target=audio_thread_target, daemon=True)
    audio_t.start()
    
    # 4. Reseta estado das mãos (importante se for um re-start)
    reset_hands_state()

    # 5. Setup OpenCV / MediaPipe
    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=1,
                                     min_detection_confidence=0.3, min_tracking_confidence=0.3)
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    is_calibrating = False
    calib_start_time = 0

    print(">>> PIANO INICIADO (Pressione ESC para voltar ao menu)")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

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
                        cv2.putText(frame, "[ESPACO] CALIBRAR", (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

                    for fid in ACTIVE_FINGERS:
                        finger = lm.landmark[fid]
                        cx, cy = int(finger.x * w), int(finger.y * h)
                        processar_dedo(lbl, fid, finger.y, finger.x, global_state["table_y"], cx, cy, frame, h)

            check_lost_fingers()
            check_active_keys_integrity()

            cv2.imshow("FastPiano", frame)

            k = cv2.waitKey(1)
            if k == 32: # ESPAÇO
                is_calibrating = True
                calib_start_time = time.time()
                reset_hands_state()
            
            if k == 27: # ESC
                break # Sai do loop, caindo no finally
    finally:
        # Limpeza
        cap.release()
        cv2.destroyAllWindows()
        # Envia sinal para matar a thread de áudio desta sessão
        audio_queue.put(None)
        print(">>> Sessão encerrada.")

if __name__ == "__main__":
    default = next(iter(settings.INSTRUMENTS.keys()))
    start_piano(default)