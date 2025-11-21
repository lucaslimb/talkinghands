import cv2
import mediapipe as mp
import threading
import queue
import fluidsynth
import time
import math

# ------------------------
# CONFIGURAÇÕES
# ------------------------
PINCH_THRESHOLD = 0.05  # Distância máxima entre polegar e indicador para ativar
MIN_NOTE = 40           # Nota mais grave (Mão embaixo)
MAX_NOTE = 90           # Nota mais aguda (Mão no topo)
SMOOTHING = 0.5         # Suavização do movimento (0.0 a 1.0)

# Cores
COLOR_INACTIVE = (100, 100, 100)
COLOR_ACTIVE = (0, 255, 255) # Amarelo Fluorescente

# ------------------------
# SETUP DE ÁUDIO
# ------------------------
try:
    fs = fluidsynth.Synth()
    fs.start(driver="dsound")  # Windows
    # Tente usar um SoundFont GM (General MIDI) aqui para ter o som de Theremin (Prog 91)
    # Se usar o "Retro_Synth_PC.sf2", verifique se ele tem presets variados.
    sfid = fs.sfload("sounds/keyboard/Retro_Synth_PC.sf2") 
    
    # --- SELEÇÃO DO SOM ---
    # Canal 0, SoundFont ID, Banco 0, Preset 91 (Space Voice/Theremin no GM)
    # Se o som ficar mudo, tente Preset 80 (Square Wave) ou 0 (Piano) para testar.
    fs.program_select(0, sfid, 0, 91) 
    
except Exception as e:
    print(f"ERRO DE AUDIO: {e}")

audio_queue = queue.Queue()

# Estado do Áudio Global
current_playing_note = None

def audio_manager():
    """Gerencia o som monofônico (uma nota por vez, estilo Theremin)"""
    global current_playing_note
    while True:
        item = audio_queue.get()
        if item is None: break
        
        action, val = item
        
        if action == "play":
            # Se a nota mudou, troca (Glissando)
            if current_playing_note != val:
                if current_playing_note is not None:
                    fs.noteoff(0, current_playing_note)
                fs.noteon(0, val, 127) # Volume máximo
                current_playing_note = val
                
        elif action == "stop":
            if current_playing_note is not None:
                fs.noteoff(0, current_playing_note)
                current_playing_note = None

threading.Thread(target=audio_manager, daemon=True).start()

# ------------------------
# FUNÇÕES AUXILIARES
# ------------------------
def calc_distance(p1, p2):
    return math.hypot(p1.x - p2.x, p1.y - p2.y)

def map_range(value, in_min, in_max, out_min, out_max):
    val = (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min
    return max(min(val, out_max), out_min)

# ------------------------
# LOOP PRINCIPAL
# ------------------------
def main_thread():
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7) # 1 mão é suficiente pro Theremin
    mp_draw = mp.solutions.drawing_utils
    
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened(): cap = cv2.VideoCapture(0)

    print(">>> Theremin Invisível Iniciado.")
    print(">>> Junte POLEGAR e INDICADOR para tocar.")
    print(">>> Mova para CIMA (Agudo) ou BAIXO (Grave).")

    prev_y = 0.5 # Para suavização

    while True:
        ret, frame = cap.read()
        if not ret: break

        # Espelhamento é essencial para parecer um espelho
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        active = False
        frequency_y = 0
        
        if results.multi_hand_landmarks:
            for lm in results.multi_hand_landmarks:
                mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
                
                # Pontos de interesse
                thumb = lm.landmark[4]
                index = lm.landmark[8]
                
                # Calcular Distância (Pinça)
                dist = calc_distance(thumb, index)
                
                # Ponto médio da pinça (onde está a "mão")
                mid_x = int((thumb.x + index.x) / 2 * w)
                mid_y = int((thumb.y + index.y) / 2 * h)
                
                # Visualizar a pinça
                cx_t, cy_t = int(thumb.x * w), int(thumb.y * h)
                cx_i, cy_i = int(index.x * w), int(index.y * h)
                
                # LÓGICA DE ATIVAÇÃO
                if dist < PINCH_THRESHOLD:
                    active = True
                    
                    # Suavização do movimento Y para o som não "tremer" tanto
                    smooth_y = (prev_y * SMOOTHING) + (mid_y/h * (1.0 - SMOOTHING))
                    prev_y = smooth_y
                    
                    # Mapear Y para Nota MIDI
                    # Y=0 (topo) -> MAX_NOTE
                    # Y=1 (base) -> MIN_NOTE
                    note_float = map_range(smooth_y, 0.0, 1.0, MAX_NOTE, MIN_NOTE)
                    note_int = int(note_float)
                    
                    audio_queue.put(("play", note_int))
                    
                    # Visual Ativo
                    cv2.line(frame, (cx_t, cy_t), (cx_i, cy_i), COLOR_ACTIVE, 3)
                    cv2.circle(frame, (mid_x, mid_y), 10, COLOR_ACTIVE, -1)
                    
                    # Mostrar Nota/Frequência
                    cv2.putText(frame, f"Note: {note_int}", (mid_x + 20, mid_y), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_ACTIVE, 2)
                    
                    # Desenhar linha horizontal de referência
                    cv2.line(frame, (0, mid_y), (w, mid_y), (255, 255, 255, 100), 1)
                    
                else:
                    # Pinça aberta = Silêncio
                    audio_queue.put(("stop", 0))
                    cv2.line(frame, (cx_t, cy_t), (cx_i, cy_i), COLOR_INACTIVE, 1)

        else:
            # Nenhuma mão = Silêncio
            audio_queue.put(("stop", 0))

        # Feedback na tela
        status_text = "TOCANDO" if active else "PAUSA (Faca Pinca)"
        col = COLOR_ACTIVE if active else COLOR_INACTIVE
        cv2.putText(frame, status_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, col, 2)
        
        # Barra lateral de frequência (Visualização)
        if active:
            bar_h = int(prev_y * h)
            cv2.rectangle(frame, (w-30, 0), (w, h), (50, 50, 50), -1)
            # Invertido: Barra enche de baixo pra cima conforme fica agudo? 
            # Vamos fazer visual direto: onde está a mão
            cv2.rectangle(frame, (w-30, bar_h-5), (w, bar_h+5), COLOR_ACTIVE, -1)

        cv2.imshow("Theremin de Mao", frame)
        if cv2.waitKey(1) == 27: break

    cap.release()
    cv2.destroyAllWindows()
    audio_queue.put(None)
    fs.delete()

if __name__ == "__main__":
    main_thread()