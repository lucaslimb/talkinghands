from pathlib import Path
import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import ctypes
import sys
import os
import pygame  # NOVO
import numpy as np # NOVO

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.config import settings
from src.engines.audio.recorder import MidiRecorder

RELEASE_THRESHOLD = 0.015
MIN_NOTE_DURATION = 0.1
ARMED_TIMEOUT = 2.5
SUSTAIN_DECAY = getattr(settings, 'SUSTAIN_DECAY', 0.8)
TOUCH_TOLERANCE = getattr(settings, 'TOUCH_TOLERANCE', 0.005)
LIFT_THRESHOLD = getattr(settings, 'LIFT_THRESHOLD', 0.02)
MAX_MISSING_TIME = 0.1

NUM_KEYS = 30
ACTIVE_FINGERS = [4, 8, 12, 16, 20]
show_menu = True

# CORES (Convertidas para RGB para o Pygame)
COLOR_TABLE_LINE = (0, 255, 0)
COLOR_TABLE_FRONT = (30, 30, 30)
COLOR_KEY_DIVIDER = (100, 100, 100)
COLOR_HIT = (255, 255, 0)     # Amarelo (RGB)
COLOR_ARMED = (255, 165, 0)   # Laranja (RGB)
COLOR_HOLD = (0, 200, 0)      # Verde Escuro

# ------------------------
# AUDIO SETUP (INTACTO)
# ------------------------
audio_queue = queue.Queue()
loaded_sfids = {}
recorder = MidiRecorder()

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
    if target_sfid is not None:
        print(f">>> SOM: {name} (B:{bank} P:{preset})")
        fs.program_select(channel, target_sfid, bank, preset)
        
        sf_path = settings.SF2_PATHS.get(sf_nickname)
            
        recorder.set_instrument(sf_path, bank, preset, is_drum=False)
        return True
    return False

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
                recorder.record_note_on(note) 
            elif action == "off":
                fs.noteoff(0, note)
                recorder.record_note_off(note)
        except Exception:
            pass

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

global_state = {"table_y": 0.80, "calibrated": False}

hands_state = {
    "Left":  {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}},
    "Right": {"finger_status": {}, "finger_timers": {}, "active_notes": {}, "last_seen": {}}
}

def reset_hands_state():
    for hand in ["Left", "Right"]:
        for fid in ACTIVE_FINGERS:
            hands_state[hand]["finger_status"][fid] = "IDLE"
            hands_state[hand]["finger_timers"][fid] = 0.0
            hands_state[hand]["active_notes"][fid] = None
            hands_state[hand]["last_seen"][fid] = 0.0

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

# MODIFICADO: Recebe screen (Pygame surface) em vez de frame (OpenCV image)
def processar_dedo(label, fid, y_current, x_current, table_y, cx, cy, screen, h_frame):
    state = hands_state[label]
    status = state["finger_status"][fid]
    last_action_time = state["finger_timers"][fid]
    current_time = time.time()
    state["last_seen"][fid] = current_time
    dist_above_table = table_y - y_current

    # Lógica de estados (MANTIDA IDÊNTICA)
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
            
            # DESENHO PYGAME: Feedback visual do toque
            # cx e cy aqui são relativos a 640x480.
            pygame.draw.circle(screen, COLOR_HIT, (cx, int(table_y * h_frame)), 15)

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
            state["active_notes"][fid] = None
            state["finger_status"][fid] = "ARMED"
            state["finger_timers"][fid] = current_time

    # DESENHO PYGAME: Indicador na ponta do dedo
    color = COLOR_ARMED if status == "ARMED" else (100,100,100)
    if status == "TOUCHING":
        color = COLOR_HOLD
    pygame.draw.circle(screen, color, (cx, cy), 5)

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

# NOVO: Função para renderizar texto no Pygame
def draw_text(surface, text, pos, font, color=(255, 255, 255)):
    text_surf = font.render(text, True, color)
    surface.blit(text_surf, pos)

# MODIFICADO: Usa Pygame Surface e Fontes
def draw_ui_fast_pygame(screen, table_y, w, h, font):
    table_px = int(table_y * h)
    key_width = w / NUM_KEYS
    
    # 1. Desenhar a linha da mesa
    pygame.draw.line(screen, COLOR_TABLE_LINE, (0, table_px), (w, table_px), 2)
    
    # 2. Criar surface para transparência (teclas)
    # Surface com suporte a Alpha (transparência)
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    
    for i, key in enumerate(PIANO_KEYS):
        x1 = int(i * key_width)
        # Linha divisória
        pygame.draw.line(screen, COLOR_KEY_DIVIDER, (x1, table_px), (x1, h), 1)
        
        # Tecla ativa (retângulo com transparência)
        if key["is_active"] or (time.time() - key["last_hit"]) < 0.15:
            x2 = int((i + 1) * key_width)
            rect_h = h - table_px
            # (R, G, B, Alpha) -> Alpha 76 é aprox 0.3 do OpenCV (255 * 0.3)
            pygame.draw.rect(overlay, (*COLOR_HIT, 76), (x1, table_px, x2-x1, rect_h))
    
    # Aplica o overlay transparente na tela principal
    screen.blit(overlay, (0,0))

    if recorder.is_recording:
        pygame.draw.circle(screen, (255, 0, 0), (w - 90, 30), 10)
        draw_text(screen, "REC", (w - 75, 20), font, (255, 0, 0))
        
    if recorder.is_playing:
        draw_text(screen, "PLAYBACK", (w - 200, 30), font, (255, 0, 0))

    if show_menu:
        instructions = [
            "ESC   -> sair",
            "ESPACO -> calibrar",
            "1 -> iniciar gravacao",
            "2 -> encerrar gravacao",
            "3 -> iniciar/interromper playback",
            "0 -> ocultar/mostrar menu"
        ]
        y0 = 30
        for i, txt in enumerate(instructions):
            draw_text(screen, txt, (20, y0 + i * 25), font)

# ------------------------
# START
# ------------------------
def start_piano(chosen_instrument, user_sustain=None, lift_threshold=None, touch_tolerance=None, rec_options=None):

    if user_sustain is not None and user_sustain > 0:
        global SUSTAIN_DECAY
        SUSTAIN_DECAY = user_sustain

    if lift_threshold is not None and lift_threshold > 0:
        global LIFT_THRESHOLD
        LIFT_THRESHOLD = lift_threshold

    if touch_tolerance is not None and touch_tolerance > 0:
        global TOUCH_TOLERANCE
        TOUCH_TOLERANCE = touch_tolerance

    global show_menu

    if rec_options:
        recorder.set_options(rec_options)

    select_instrument_by_name(chosen_instrument)

    audio_t = threading.Thread(target=audio_thread_target, daemon=True)
    audio_t.start()
    
    reset_hands_state()

    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=1,
                                     min_detection_confidence=0.3, min_tracking_confidence=0.3)
    
    # Câmera Setup
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    # 1. AJUSTE: Aumentar resolução de captura para HD (Melhora qualidade e zoom)
    LOGICAL_W, LOGICAL_H = 1280, 720 
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LOGICAL_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, LOGICAL_H)
    cap.set(cv2.CAP_PROP_FPS, 60) # 30 FPS é mais seguro para HD em USB 2.0
    
    # PYGAME SETUP
    pygame.init()
    
    # 2. AJUSTE: Janela do mesmo tamanho da captura (Evita esticar/pixelar)
    DISPLAY_W, DISPLAY_H = 1280, 720 
    
    # Se quiser tela cheia REAL, descomente a linha abaixo e comente a de cima:
    # window_display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    # DISPLAY_W, DISPLAY_H = window_display.get_size()
    
    window_display = pygame.display.set_mode((DISPLAY_W, DISPLAY_H))
    pygame.display.set_caption("Talking Hands - Pygame HD")
    
    # Surface lógica (Se usar tela cheia, o código vai escalar isso aqui)
    main_surface = pygame.Surface((LOGICAL_W, LOGICAL_H))
    
    # Fonte
    caminho_fonte = "assets/ShadowsOfSecurity-5zW8.ttf" 
    tamanho_fonte = 16
    try:
        # Carrega arquivo externo (Ideal para estilizar o jogo)
        main_font = pygame.font.Font(caminho_fonte, tamanho_fonte)
        calib_font = pygame.font.Font(caminho_fonte, tamanho_fonte + 4)
    except FileNotFoundError:
        print(f"AVISO: Fonte {caminho_fonte} não encontrada. Usando Arial.")
        # Fallback (Plano B) caso o arquivo não exista
        main_font = pygame.font.SysFont("Arial", 18, bold=True)
        calib_font = pygame.font.SysFont("Arial", 24, bold=True)

    is_calibrating = False
    calib_start_time = 0

    print(">>> TECLADO INICIADO (Pygame)")
    running = True

    try:
        while running:
            # 1. EVENTOS PYGAME (Substitui waitKey)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        recorder.stop_playback()
                        running = False
                    elif event.key == pygame.K_SPACE:
                        is_calibrating = True
                        calib_start_time = time.time()
                        reset_hands_state()
                    elif event.key == pygame.K_1:
                        recorder.start()
                    elif event.key == pygame.K_2:
                        timestamp = int(time.time())
                        filename = f"keyboard_{chosen_instrument.replace(' ', '_')}_{timestamp}.mid"
                        recorder.stop(filename)
                    elif event.key == pygame.K_3:
                        recorder.toggle_playback(fs)
                    elif event.key == pygame.K_4:
                        recorder.stop_playback()
                    elif event.key == pygame.K_0:
                        show_menu = not show_menu

            # 2. CAPTURA E FORÇAR TAMANHO (A CORREÇÃO É AQUI)
            ret, frame = cap.read()
            if not ret:
                break

            # --- CORREÇÃO DO ERRO DE BUFFER ---
            # Força o frame a ter exatamente o tamanho que configuramos (1280x720)
            # Isso garante que a contagem de bytes bata com o esperado pelo frombuffer
            frame = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            # ----------------------------------

            # A. Espelhar
            frame = cv2.flip(frame, 1)
            
            # B. Converter para RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # C. PROCESSAMENTO MEDIAPIPE (Usa a imagem RGB já redimensionada)
            results = hands.process(frame_rgb)

            # D. CRIAÇÃO DA IMAGEM PYGAME
            # Agora frame_rgb tem GARANTIDAMENTE o tamanho (LOGICAL_W, LOGICAL_H)
            frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), 'RGB')
            
            main_surface.blit(frame_surface, (0, 0))

            # 3. DRAW UI (Desenhamos SOBRE o vídeo)
            # Passamos main_surface, que tem tamanho LOGICAL_W x LOGICAL_H
            draw_ui_fast_pygame(main_surface, global_state["table_y"], LOGICAL_W, LOGICAL_H, main_font)

            # 4. DESENHO DOS PONTOS (Mãos)
            if results.multi_hand_landmarks:
                for idx, lm in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label

                    for fid in ACTIVE_FINGERS:
                        finger = lm.landmark[fid]
                        
                        # Cálculo de coordenadas
                        # Como main_surface tem o tamanho LOGICAL_W/H, a matemática bate perfeito
                        cx, cy = int(finger.x * LOGICAL_W), int(finger.y * LOGICAL_H)
                        
                        processar_dedo(lbl, fid, finger.y, finger.x, global_state["table_y"], cx, cy, main_surface, LOGICAL_H)

            # 5. ATUALIZAÇÕES FINAIS
            check_lost_fingers()
            check_active_keys_integrity()
            
            # Escala a superfície lógica (640x480) para o tamanho da janela (1920x1080)
            scaled_surface = pygame.transform.scale(main_surface, (DISPLAY_W, DISPLAY_H))
            window_display.blit(scaled_surface, (0, 0))
            
            pygame.display.flip()
            # pygame.time.Clock().tick(60) # Opcional: limitar FPS se necessário

    finally:
        print(">>> Encerrando notas ativas...")
        for key in PIANO_KEYS:
            if key["is_active"]:
                try:
                    fs.noteoff(0, key["note"])
                except:
                    pass
                key["is_active"] = False

        cap.release()
        pygame.quit()
        audio_queue.put(None)
        print(">>> Sessão encerrada.")

if __name__ == "__main__":
    default = next(iter(settings.INSTRUMENTS.keys()))
    start_piano(default)