"""
Maestro — modo principal: mãos + expressão facial.

Combina o controle gestual (pitch, pan, effects, percussão) com detecção
de emoção facial para seleção automática do timbre. Cada emoção mapeia
para um som diferente; a transição é automática e suavizada.

EMOÇÃO → SOM:
  Neutral   → Warm Pad     (neutro, base)
  Happiness → Crystal      (brilhante)
  Sadness   → Eventide     (melancólico)
  Anger     → Goblin       (tenso)
  Fear      → Rain         (perturbador)
  Surprise  → Space Voices (etéreo)
  Contempt  → Metallic Pad (frio)
  Disgust   → Atmosphere   (opressivo)

MAPEAMENTO GESTUAL:
  Mão direita (melodia):
    Y         → pitch contínuo (C3..C6, MIDI 48..84)
    X         → pan estéreo (CC 10)
    Abertura  → brilho / timbre (CC 74)
    Oscilação rápida (4..10 Hz) → vibrato (pitch LFO adaptativo)
    Oscilação lenta  (1..4  Hz) → tremolo (amplitude LFO)
    Descida rápida   → kick  (canal 9, nota 36)
    Lateral rápido   → snare (canal 9, nota 38)

  Mão esquerda (expressão):
    Y         → volume / expression (CC 11)
    X         → reverb send (CC 91)
    Abertura  → chorus (CC 93)
    Fechar mão rápido → accent (velocity spike momentânea)
    Abrir mão rápido  → swell (boost temporário de reverb)
"""

from pathlib import Path
import sys
import os
import collections
import math
import queue
import threading
import time

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

import cv2
import mediapipe as mp
import numpy as np
import pygame

from src.config import settings
from src.engines.recorder import MidiRecorder
from src.instruments.common import (
    init_fluidsynth, load_all_soundfonts, select_instrument,
    setup_video_capture, setup_pygame_with_scaling, fit_resolution_to_screen,
    draw_text, draw_recording_indicator, draw_playback_indicator,
    CameraThread, prepare_mediapipe_frame,
)
import fluidsynth

from src.expressions.face import EmotionTracker, EMOTION_COLORS
from src.expressions.face_visualization import BrainVisualizer

# ── Constantes ─────────────────────────────────────────────────────────────────
MELODY_CH   = 0
DRUMS_CH    = 9

PITCH_LOW   = 48        # C3 — posição mais baixa
PITCH_HIGH  = 84        # C6 — posição mais alta
BEND_UNIT   = 2048      # unidades por semitom (pyfluidsynth)

# Vibrato — detectado por oscilações rápidas da mão direita
VIB_FREQ_MIN  = 3.5     # Hz: abaixo disso é tremolo
VIB_FREQ_MAX  = 10.0    # Hz: acima disso é ruído/jitter
VIB_MAX_RATE  = 8.0     # Hz máximo exibido no painel
VIB_MAX_DEPTH = 3.5     # semitons de desvio máximo do vibrato
VIB_AMP_SCALE = 40.0    # amp_normalizada → semitons

# Tremolo — oscilações mais lentas modulam amplitude
TREM_FREQ_MIN = 1.0     # Hz mínimo para tremolo
TREM_FREQ_MAX = 5.0     # Hz máximo para tremolo
TREM_DEPTH    = 0.75    # profundidade de modulação de amplitude (0..1)
TREM_AMP_SCALE = 22.0   # amp_normalizada → profundidade 0..1

# Suavização EMA (alpha = quão rápido segue o sinal)
SMOOTH_FAST   = 0.28
SMOOTH_MED    = 0.15
SMOOTH_SLOW   = 0.08

# Zonas de tela ativa por mão (coords de câmera — display é espelhado!)
# Mão direita do usuário → camera_x < 0.5 (lado direito do display espelhado)
# Mão esquerda do usuário → camera_x > 0.5 (lado esquerdo do display espelhado)
RIGHT_HAND_X_MAX = 0.50   # mão D ativa quando camera_x < este valor
LEFT_HAND_X_MIN  = 0.50   # mão E ativa quando camera_x > este valor

# Volume Y com padding — faixa confortável sem precisar esticar o braço
VOL_Y_PAD_TOP = 0.25   # Y acima disto = volume máximo  (25% do topo)
VOL_Y_PAD_BOT = 0.75   # Y abaixo disto = volume zero   (75% do topo)

# Gesto de apontar (kick / snare) — velocidade mínima do jab
POINT_VY_THRESHOLD = 0.8   # jab vertical   (kick e snare)
POINT_VX_THRESHOLD = 0.8   # jab lateral    (snare alternativo)
PERC_COOLDOWN      = 0.35  # cooldown independente para kick/snare (evita double-hit)
# Gesto de deslocamento vertical explícito para kick/snare
PERC_SWIPE_DIST     = 0.20  # deslocamento vertical mínimo para baixo (20% da tela)
PERC_SWIPE_MAX_TIME = 0.80  # janela de tempo máxima para o gesto (s)
ACCENT_CLOSE_RATE  = -3.0  # taxa de fechamento — mais negativo = mais difícil
SWELL_OPEN_RATE    = 3.0   # taxa de abertura   — maior = mais difícil de acionar
GESTURE_COOLDOWN   = 0.28  # segundos mínimos entre dois triggers do mesmo tipo

# Histerese do vibrato: frames mantidos após perder detecção
VIB_HOLD_FRAMES    = 10

# Velocidade e notas
NORMAL_VELOCITY  = 88
MAX_VELOCITY     = 127
ACCENT_DURATION  = 0.20   # segundos de duração do accent (decaimento)
SWELL_DURATION   = 0.90   # segundos do boost de reverb
KICK_NOTE        = 36
SNARE_NOTE       = 38
HIT_VELOCITY     = 110

HAND_ABSENT_SECS = 0.12
MP_INPUT_HEIGHT  = 480
EVENT_FADE_SECS  = 1.8

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Emoção → instrumento automático (a face define o timbre)
EMOTION_INSTRUMENTS = {
    "Neutral":   "Warm Pad",
    "Happiness": "Crystal",
    "Sadness":   "Eventide",
    "Anger":     "Goblin",
    "Fear":      "Rain",
    "Surprise":  "Space Voices",
    "Contempt":  "Metallic Pad",
    "Disgust":   "Atmosphere",
}
EMOTION_INTERVAL = 0.05   # submissão de frames ao tracker (~20 fps)


# ═══════════════════════════════════════════════════════════════════════════════
# Módulo 1 — SignalSmoother
# ═══════════════════════════════════════════════════════════════════════════════

class SignalSmoother:
    """Filtro EMA (exponential moving average) para suavização de sinal contínuo."""

    def __init__(self, alpha=0.15, initial=None):
        self.alpha = float(alpha)
        self.value = float(initial) if initial is not None else None

    def update(self, new_value):
        v = float(new_value)
        if self.value is None:
            self.value = v
        else:
            self.value += self.alpha * (v - self.value)
        return self.value

    def reset(self, value=None):
        self.value = float(value) if value is not None else None


# ═══════════════════════════════════════════════════════════════════════════════
# Módulo 2 — OscillationDetector
# ═══════════════════════════════════════════════════════════════════════════════

class OscillationDetector:
    """
    Analisa um buffer deslizante de posição e extrai frequência e amplitude
    das oscilações periódicas. Usado para detectar vibrato e tremolo em tempo real.

    Usa um baseline EMA lento (alpha=0.04) para remover a componente DC de deriva
    (mudança de pitch), deixando apenas as oscilações rápidas no buffer.
    """

    def __init__(self, window=32, baseline_alpha=0.04):
        self.window          = window
        self._baseline_alpha = float(baseline_alpha)
        self._baseline       = None   # rastreia deriva lenta do sinal
        self._values         = collections.deque(maxlen=window)  # sinal filtrado
        self._times          = collections.deque(maxlen=window)

    def update(self, value, timestamp):
        """
        Adiciona nova amostra e retorna (frequency_hz, amplitude_normalized).
        Amplitude é aprox. peak-to-peak / 2 (desvio padrão × 2).
        """
        v = float(value)

        # Baseline lento (filtro passa-baixa) acompanha mudanças de pitch
        # sem ser afetado por oscilações rápidas de vibrato
        if self._baseline is None:
            self._baseline = v
        else:
            self._baseline += self._baseline_alpha * (v - self._baseline)

        # Passa-alta: apenas as oscilações rápidas entram no buffer
        filtered = v - self._baseline
        self._values.append(filtered)
        self._times.append(float(timestamp))

        if len(self._values) < 10:
            return 0.0, 0.0

        vals  = np.array(self._values)
        times = np.array(self._times)

        amplitude = float(np.std(vals)) * 2.0  # aprox. peak-to-peak / 2

        # Piso de ruído — evitar detecção em sinal estático / jitter leve
        if amplitude < 0.006:
            return 0.0, 0.0

        # Contar zero-crossings para estimar frequência fundamental
        signs = np.sign(vals)
        for i in range(1, len(signs)):
            if signs[i] == 0:
                signs[i] = signs[i - 1]

        crossings = int(np.sum(np.abs(np.diff(signs)) > 0))
        duration  = float(times[-1] - times[0])

        if duration < 0.08:
            return 0.0, 0.0

        freq = (crossings / 2.0) / duration
        return freq, amplitude

    def reset(self):
        self._values.clear()
        self._times.clear()
        self._baseline = None


# ═══════════════════════════════════════════════════════════════════════════════
# Módulo 3 — GestureVelocityTracker
# ═══════════════════════════════════════════════════════════════════════════════

class GestureVelocityTracker:
    """Rastreia velocidade e aceleração 2D de um ponto-chave da mão."""

    def __init__(self, history_len=6, smooth_alpha=0.30):
        self._positions  = collections.deque(maxlen=history_len)
        self._times      = collections.deque(maxlen=history_len)
        self._vx         = SignalSmoother(smooth_alpha, 0.0)
        self._vy         = SignalSmoother(smooth_alpha, 0.0)

    def update(self, x, y, timestamp):
        """Retorna (vx, vy) suavizados em coordenadas normalizadas/segundo."""
        self._positions.append((float(x), float(y)))
        self._times.append(float(timestamp))

        if len(self._positions) < 2:
            return 0.0, 0.0

        dt = self._times[-1] - self._times[-2]
        if dt < 1e-6:
            return self._vx.value or 0.0, self._vy.value or 0.0

        dx = self._positions[-1][0] - self._positions[-2][0]
        dy = self._positions[-1][1] - self._positions[-2][1]
        self._vx.update(dx / dt)
        self._vy.update(dy / dt)
        return self._vx.value, self._vy.value

    def reset(self):
        self._positions.clear()
        self._times.clear()
        self._vx.reset(0.0)
        self._vy.reset(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Módulo 4 — DiscreteGestureDetector
# ═══════════════════════════════════════════════════════════════════════════════

class DiscreteGestureDetector:
    """
    Detecta eventos gestuais discretos a partir de velocidade e abertura da mão.

    Eventos emitidos:
      "accent" — fechamento rápido da mão  (openness cai rapidamente)
      "swell"  — abertura rápida da mão    (openness sobe rapidamente)
    Kick/snare detectados por gesto de apontar — ver _is_pointing() e main loop.
    """

    def __init__(self):
        self._last             = {"accent": 0.0, "swell": 0.0}
        self._prev_openness    = 0.5
        self._prev_openness_ts = 0.0

    def update(self, vx, vy, openness, timestamp):
        events = []

        def _fire(name):
            if (timestamp - self._last[name]) >= GESTURE_COOLDOWN:
                self._last[name] = timestamp
                return True
            return False

        # Taxa de variação de abertura
        dt = max(0.02, timestamp - self._prev_openness_ts)
        openness_rate = (float(openness) - self._prev_openness) / dt

        # Accent: fechamento brusco (exige movimento rápido E mão bem fechada)
        if openness_rate < ACCENT_CLOSE_RATE and openness < 0.20 and _fire("accent"):
            events.append("accent")

        # Swell: abertura brusca (exige movimento rápido E mão bem aberta)
        if openness_rate > SWELL_OPEN_RATE and openness > 0.75 and _fire("swell"):
            events.append("swell")

        self._prev_openness    = float(openness)
        self._prev_openness_ts = timestamp
        return events


# ── Helpers de landmarks ────────────────────────────────────────────────────────

def _hand_openness(lm):
    """Abertura da mão: 0 = punho fechado, 1 = totalmente aberta."""
    tips = [4, 8, 12, 16, 20]
    avg = sum(
        math.sqrt((lm[t].x - lm[0].x) ** 2 + (lm[t].y - lm[0].y) ** 2)
        for t in tips
    ) / len(tips)
    return max(0.0, min(1.0, (avg - 0.08) / 0.17))


def _hand_depth(lm):
    """Profundidade aproximada pelo tamanho aparente: 0 = longe, 1 = perto."""
    dx = lm[0].x - lm[9].x
    dy = lm[0].y - lm[9].y
    size = math.sqrt(dx * dx + dy * dy)
    return max(0.0, min(1.0, (size - 0.07) / 0.15))


def _is_pointing(lm):
    """Detecta gesto de apontar: indicador estendido, médio/anelar/mínimo curvados.
    Funciona no espaço de câmera não-espelhado — Y menor = mais alto na imagem."""
    index_ext   = lm[8].y < lm[6].y    # ponta do indicador acima do PIP
    middle_curl = lm[12].y > lm[10].y  # médio curvado
    ring_curl   = lm[16].y > lm[14].y  # anelar curvado
    pinky_curl  = lm[20].y > lm[18].y  # mínimo curvado
    return index_ext and middle_curl and ring_curl and pinky_curl


def _note_name(midi_note):
    n = max(0, min(127, int(midi_note)))
    return f"{NOTE_NAMES[n % 12]}{(n // 12) - 1}"


# ── UI helpers ──────────────────────────────────────────────────────────────────

def _draw_param_bar(surface, label, value_0_1, x, y, font, color=(100, 200, 255), bar_w=90):
    """Rótulo + barra horizontal proporcional ao valor (0..1)."""
    bar_x = x + 152
    bar_h = 11
    draw_text(surface, label, (x, y), font, (190, 190, 210))
    pygame.draw.rect(surface, (35, 35, 42), (bar_x, y + 1, bar_w, bar_h))
    fill = max(0, min(bar_w, int(bar_w * max(0.0, min(1.0, value_0_1)))))
    if fill > 0:
        pygame.draw.rect(surface, color, (bar_x, y + 1, fill, bar_h))
    pygame.draw.rect(surface, (70, 70, 82), (bar_x, y + 1, bar_w, bar_h), 1)


def _draw_lfo_indicator(surface, label, lfo_phase, active, x, y, font, color):
    """Pequeno semicírculo animado para indicar LFO ativo."""
    if active:
        radius = 6
        cx, cy = x + 8, y + 6
        pygame.draw.circle(surface, color, (cx, cy), radius, 1)
        dot_x = int(cx + radius * math.sin(lfo_phase))
        dot_y = int(cy - radius * math.cos(lfo_phase))
        pygame.draw.circle(surface, color, (dot_x, dot_y), 3)
    draw_text(surface, label, (x + 20, y), font, color if active else (80, 80, 90))


# ═══════════════════════════════════════════════════════════════════════════════
# Fila e worker de áudio
# ═══════════════════════════════════════════════════════════════════════════════

_audio_queue = queue.Queue()
_recorder    = MidiRecorder()
_fs          = None   # FluidSynth — definido em start_maestro
_drums_ready = False  # True se soundfont de percussão foi carregado


def _audio_worker():
    """Consome a fila e encaminha eventos ao FluidSynth de forma assíncrona."""
    while True:
        item = _audio_queue.get()
        if item is None:
            break
        try:
            action = item[0]
            if action == "noteon":
                _, ch, note, vel = item
                _fs.noteon(ch, note, int(vel))
                if ch == MELODY_CH:
                    _recorder.record_note_on(note)

            elif action == "noteoff":
                _, ch, note = item
                _fs.noteoff(ch, note)
                if ch == MELODY_CH:
                    _recorder.record_note_off(note)

            elif action == "bend":
                _, value = item
                _fs.pitch_bend(MELODY_CH, int(value))

            elif action == "cc":
                _, ch, ctrl, value = item
                _fs.cc(ch, int(ctrl), int(value))
                if ch == MELODY_CH and hasattr(_recorder, "record_cc"):
                    _recorder.record_cc(ch, ctrl, value)

        except Exception:
            pass


def _trigger_perc(note, vel=HIT_VELOCITY):
    """Enfileira um hit percussivo (noteon+noteoff com delay via timer)."""
    if not _drums_ready:
        return
    _audio_queue.put(("noteon", DRUMS_CH, note, vel))
    t = threading.Timer(0.06, lambda: _audio_queue.put(("noteoff", DRUMS_CH, note)))
    t.daemon = True
    t.start()


# ═══════════════════════════════════════════════════════════════════════════════
# Renderização do painel UI
# ═══════════════════════════════════════════════════════════════════════════════

def _render_ui(
    surface, font, w, h,
    playing, current_note,
    s_pitch, s_pan_r, s_bright_r,
    s_vib_rate, s_vib_depth,
    s_trem_rate, s_trem_depth,
    s_volume, s_reverb, s_chorus,
    vib_phase, trem_phase,
    accent_decay, swell_decay,
    event_log, now,
    current_instrument="", current_emotion="Neutral",
):
    # ── Painel direito — Mão direita (aparece visual-direita no display espelhado) ──
    px = w - 260
    py = 14
    draw_text(surface, "MAO DIREITA  (melodia)", (px, py), font, (140, 200, 255))
    py += 22

    note_str   = _note_name(current_note) if playing else "--"
    pitch_val  = s_pitch.value or float((PITCH_LOW + PITCH_HIGH) / 2)
    pitch_frac = (pitch_val - (PITCH_LOW - 6)) / ((PITCH_HIGH + 6) - (PITCH_LOW - 6))
    _draw_param_bar(surface, f"PITCH     {note_str}",
                    max(0.0, min(1.0, pitch_frac)), px, py, font, (140, 220, 255))
    py += 18

    pan_val  = (s_pan_r.value or 64.0) / 127.0
    pan_lbl  = "C" if abs(pan_val - 0.5) < 0.05 else ("L" if pan_val < 0.5 else "R")
    _draw_param_bar(surface, f"PAN       {pan_lbl}",
                    pan_val, px, py, font, (160, 230, 130))
    py += 18

    bright_r = s_bright_r.value or 64.0
    _draw_param_bar(surface, f"TIMBRE    {int(bright_r)}",
                    bright_r / 127.0, px, py, font, (255, 215, 70))
    py += 26

    # Vibrato
    vr = s_vib_rate.value or 0.0
    vd = s_vib_depth.value or 0.0
    vib_active = vr > 0.3
    _draw_lfo_indicator(surface, f"VIBRATO  {vr:.1f} Hz / {vd:.2f} st",
                        vib_phase, vib_active, px, py, font, (200, 150, 255))
    py += 18
    _draw_param_bar(surface, "  rate",
                    vr / VIB_MAX_RATE, px, py, font, (200, 150, 255))
    py += 14
    _draw_param_bar(surface, "  depth",
                    min(1.0, vd / VIB_MAX_DEPTH), px, py, font, (180, 120, 255))
    py += 26

    # Tremolo
    tr = s_trem_rate.value or 0.0
    td = s_trem_depth.value or 0.0
    trem_active = tr > 0.3
    _draw_lfo_indicator(surface, f"TREMOLO  {tr:.1f} Hz / {td:.2f}",
                        trem_phase, trem_active, px, py, font, (255, 165, 60))
    py += 18
    _draw_param_bar(surface, "  rate",
                    tr / TREM_FREQ_MAX, px, py, font, (255, 165, 60))
    py += 14
    _draw_param_bar(surface, "  depth",
                    min(1.0, td), px, py, font, (255, 120, 40))
    py += 22

    if accent_decay > 0.01:
        a = min(255, int(255 * accent_decay))
        draw_text(surface, f"! ACCENT  {int(accent_decay * 100)}%",
                  (px, py), font, (255, a // 2, a // 4))

    # ── Painel esquerdo — Mão esquerda (aparece visual-esquerda no display espelhado) ──
    ox, oy = 14, 14
    draw_text(surface, "MAO ESQUERDA  (expressao)", (ox, oy), font, (140, 255, 190))
    oy += 22

    vol_val = s_volume.value or 127.0
    _draw_param_bar(surface, f"VOLUME   {int(vol_val)}",
                    vol_val / 127.0, ox, oy, font, (100, 255, 140))
    oy += 18

    rev_val = s_reverb.value or 20.0
    _draw_param_bar(surface, f"REVERB   {int(rev_val)}",
                    rev_val / 127.0, ox, oy, font, (80, 180, 255))
    oy += 18

    cho_val = s_chorus.value or 0.0
    _draw_param_bar(surface, f"CHORUS   {int(cho_val)}",
                    cho_val / 80.0, ox, oy, font, (80, 220, 255))
    oy += 22

    if swell_decay > 0.01:
        a = min(255, int(255 * swell_decay))
        draw_text(surface, f"~ SWELL  {int(swell_decay * 100)}%",
                  (ox, oy), font, (a // 4, a // 2, 255))
    oy += 18

    # ── Log de eventos discretos (bottom) ─────────────────────────────────
    event_defs = [
        ("kick",   "KICK",   (255, 120,  60)),
        ("snare",  "SNARE",  (255, 210,  70)),
        ("accent", "ACCENT", (255,  80,  80)),
        ("swell",  "SWELL",  (80,  210, 255)),
    ]
    ex_base = 22
    for idx, (ename, elabel, ecolor) in enumerate(event_defs):
        best_alpha = 0.0
        for evt_name, evt_ts in event_log:
            if evt_name == ename:
                age = now - evt_ts
                if age < EVENT_FADE_SECS:
                    best_alpha = max(best_alpha, 1.0 - (age / EVENT_FADE_SECS))
        if best_alpha > 0.01:
            col = tuple(max(0, min(255, int(c * best_alpha))) for c in ecolor)
            draw_text(surface, elabel, (ex_base + idx * 100, h - 46), font, col)

    draw_text(surface, "1=Gravar  2=Parar  3=Playback  V=Visual  0=Menu  ESC=Sair",
              (20, h - 26), font, (140, 140, 155))

    # ── Instrumento + emoção — centro inferior ─────────────────────────────
    emo_color = EMOTION_COLORS.get(current_emotion, (180, 180, 180))
    instr_label = current_instrument.upper()
    draw_text(surface, f"[ {instr_label} ]", (w // 2 - 90, h - 48), font, (220, 210, 255))
    draw_text(surface, current_emotion.upper(), (w // 2 - 90, h - 66), font, emo_color)


# ═══════════════════════════════════════════════════════════════════════════════
# Função principal
# ═══════════════════════════════════════════════════════════════════════════════

def start_maestro(
    chosen_instrument="Maestro",
    rec_options=None,
    resolution_profile=None,
    show_trackers=False,
    hand_model_complexity=1,
):
    global _fs, _drums_ready

    if rec_options is None:
        rec_options = {"save_mid": True, "save_wav": True}

    # ── Resolução ───────────────────────────────────────────────────────────
    if resolution_profile:
        logical_w  = resolution_profile["logical_width"]
        logical_h  = resolution_profile["logical_height"]
        display_w  = resolution_profile["display_width"]
        display_h  = resolution_profile["display_height"]
        target_fps = resolution_profile["fps"]
    else:
        logical_w = display_w = 1280
        logical_h = display_h = 720
        target_fps = 30

    display_w, display_h, _, _, _ = fit_resolution_to_screen(display_w, display_h)

    # ── Áudio ───────────────────────────────────────────────────────────────
    _fs, loaded_sfids = init_fluidsynth(driver="dsound")
    if _fs is None:
        print("ERRO CRÍTICO DE AUDIO: FluidSynth não inicializado.")
        return

    loaded_sfids = load_all_soundfonts(_fs)
    initial_instr = EMOTION_INSTRUMENTS.get("Neutral", "Warm Pad")
    select_instrument(_fs, initial_instr, loaded_sfids, _recorder,
                      channel=MELODY_CH, is_drum=False)

    # Canal de percussão (canal 9, banco 128)
    drums_sfid = loaded_sfids.get("drums")
    _drums_ready = False
    if drums_sfid is not None:
        try:
            _fs.program_select(DRUMS_CH, drums_sfid, 128, 0)
            _drums_ready = True
            print(">>> Canal de percussão inicializado (canal 9).")
        except Exception as exc:
            print(f"[!] Canal de percussão não disponível: {exc}")

    _recorder.options.update(rec_options)

    try:
        _fs.setting("synth.gain", 2.0)
    except Exception:
        pass
    _fs.cc(MELODY_CH, 7,  127)   # channel volume
    _fs.cc(MELODY_CH, 11, 127)   # expression
    _fs.cc(MELODY_CH, 91, 20)    # reverb inicial
    _fs.cc(MELODY_CH, 93, 0)     # chorus inicial

    audio_thread = threading.Thread(target=_audio_worker, daemon=True)
    audio_thread.start()

    # ── Câmera ──────────────────────────────────────────────────────────────
    cap = setup_video_capture(logical_w, logical_h, target_fps)
    cam = CameraThread(cap)

    # ── EmotionTracker (face → timbre) ──────────────────────────────────────
    emotion_tracker = EmotionTracker()
    last_emotion_ts = 0.0
    current_emotion = "Neutral"
    current_instr_name = initial_instr

    # ── MediaPipe Hands ─────────────────────────────────────────────────────
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        max_num_hands=2,
        model_complexity=hand_model_complexity,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    # ── Pygame ──────────────────────────────────────────────────────────────
    screen, surface, font = setup_pygame_with_scaling(
        logical_w, logical_h, display_w, display_h,
        title="Maestro",
    )
    clock = pygame.time.Clock()

    # ── Visualizador neural (face) ──────────────────────────────────────
    brain_viz = BrainVisualizer(logical_w, logical_h)
    show_viz = True

    # ── Sinais suavizados — Mão direita ─────────────────────────────────────
    s_pitch    = SignalSmoother(SMOOTH_MED,  float((PITCH_LOW + PITCH_HIGH) / 2))
    s_pan_r    = SignalSmoother(SMOOTH_MED,  64.0)
    s_bright_r = SignalSmoother(SMOOTH_MED,  64.0)
    s_vib_rate   = SignalSmoother(SMOOTH_MED, 0.0)
    s_vib_depth  = SignalSmoother(SMOOTH_MED, 0.0)
    s_trem_rate  = SignalSmoother(SMOOTH_MED, 0.0)
    s_trem_depth = SignalSmoother(SMOOTH_MED, 0.0)

    # ── Sinais suavizados — Mão esquerda ────────────────────────────────────
    s_volume = SignalSmoother(SMOOTH_MED,  127.0)
    s_reverb = SignalSmoother(SMOOTH_FAST, 20.0)
    s_chorus = SignalSmoother(SMOOTH_MED,  0.0)

    # ── Detectores de feature ────────────────────────────────────────────────
    right_osc     = OscillationDetector(window=32)
    right_vel     = GestureVelocityTracker(history_len=6)
    right_gesture = DiscreteGestureDetector()

    left_vel      = GestureVelocityTracker(history_len=6)
    left_gesture  = DiscreteGestureDetector()

    # ── Estado do instrumento ────────────────────────────────────────────────
    playing       = False
    current_note  = -1
    vib_phase     = 0.0
    trem_phase    = 0.0
    last_right_ts = 0.0
    last_time     = time.perf_counter()
    show_menu     = True
    vib_hold      = 0     # frames de histerese para manter vibrato ativo

    accent_decay  = 0.0   # 0..1, decai ao longo de ACCENT_DURATION
    swell_decay   = 0.0   # 0..1, decai ao longo de SWELL_DURATION
    event_log     = []    # lista de (name, timestamp)
    last_kick_ts  = 0.0   # cooldown kick  (gesto de apontar mão direita)
    last_snare_ts = 0.0   # cooldown snare (gesto de apontar mão esquerda)
    kick_origin_y  = None  # origem Y para gesto de kick
    kick_origin_t  = None
    snare_origin_y = None  # origem Y para gesto de snare
    snare_origin_t = None

    print(">>> Maestro pronto (mãos + face).")
    print("    Mao D: Y=pitch   X=pan   abertura=timbre   oscilacao=vibrato/tremolo")
    print("    Mao E: Y=volume  X=reverb  abertura=chorus")
    print("    Gestos: descida D=kick | descida E=snare | fechar=accent | abrir=swell")
    print("    Face: emoção detectada define o timbre automaticamente.")
    print("    1=gravar  2=parar  3=playback  V=visual  0=menu  ESC=sair")

    # ── Loop principal ───────────────────────────────────────────────────────
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_0:
                    show_menu = not show_menu
                elif event.key == pygame.K_v:
                    show_viz = not show_viz
                elif event.key == pygame.K_1:
                    if not _recorder.is_recording:
                        _recorder.start_recording()
                elif event.key == pygame.K_2:
                    if _recorder.is_recording:
                        _recorder.stop_recording()
                elif event.key == pygame.K_3:
                    if _recorder.is_playing:
                        _recorder.stop_playback()
                    else:
                        _recorder.start_playback(_fs, MELODY_CH)
        frame, _ = cam.get_latest()
        if frame is None:
            clock.tick(target_fps)
            continue

        now       = time.perf_counter()
        dt        = min(now - last_time, 0.10)
        last_time = now

        # Avança fases dos LFOs, independente da detecção de mão
        vib_rate_hz  = s_vib_rate.value  or 0.0
        trem_rate_hz = s_trem_rate.value or 0.0
        vib_phase  = (vib_phase  + vib_rate_hz  * dt * 2.0 * math.pi) % (2.0 * math.pi)
        trem_phase = (trem_phase + trem_rate_hz * dt * 2.0 * math.pi) % (2.0 * math.pi)

        # Decaimento de accent e swell
        accent_decay = max(0.0, accent_decay - dt / ACCENT_DURATION)
        swell_decay  = max(0.0, swell_decay  - dt / SWELL_DURATION)

        # Limpeza do event_log — manter só os últimos 20 eventos recentes
        if len(event_log) > 20:
            event_log = [(n, t) for n, t in event_log if (now - t) < EVENT_FADE_SECS * 2]

        # ── Submissão de frame ao EmotionTracker ───────────────────────────
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_frame  = prepare_mediapipe_frame(frame_rgb, logical_w, logical_h, MP_INPUT_HEIGHT)
        if now - last_emotion_ts >= EMOTION_INTERVAL:
            emotion_tracker.submit_frame(mp_frame)
            last_emotion_ts = now

        # Emoção dominante → troca automática de timbre
        detected_emotion, emotion_scores = emotion_tracker.get_state()
        if detected_emotion != current_emotion:
            new_instr = EMOTION_INSTRUMENTS.get(detected_emotion)
            if new_instr and new_instr != current_instr_name:
                select_instrument(_fs, new_instr, loaded_sfids, _recorder, MELODY_CH)
                current_instr_name = new_instr
                current_emotion = detected_emotion
                event_log.append(("emotion", now))

        brain_viz.update_emotions(emotion_scores)
        brain_viz.update(dt)

        # ── Processamento MediaPipe Hands ──────────────────────────────────
        results   = hands.process(mp_frame)

        right_lm = None
        left_lm  = None

        if results.multi_hand_landmarks and results.multi_handedness:
            for hand_lm, handedness in zip(
                results.multi_hand_landmarks, results.multi_handedness
            ):
                lm    = hand_lm.landmark
                label = handedness.classification[0].label
                # MediaPipe assume imagem espelhada (selfie). Como alimentamos
                # o frame NÃO espelhado, os rótulos estão invertidos em relação
                # ao usuário → trocar "Right"↔"Left" para corrigir.
                if label == "Right":
                    left_lm = lm
                else:
                    right_lm = lm
                if show_trackers:
                    mp.solutions.drawing_utils.draw_landmarks(
                        frame_rgb, hand_lm, mp_hands.HAND_CONNECTIONS
                    )

        # ═══════════════════════════════════════════════════════════════════
        # Mão direita — melodia, vibrato, tremolo, kick
        # Ativa apenas na metade direita do display (camera_x < 0.5)
        # ═══════════════════════════════════════════════════════════════════
        if right_lm is not None and right_lm[0].x < RIGHT_HAND_X_MAX:
            last_right_ts = now
            rx, ry = right_lm[0].x, right_lm[0].y
            # Re-normaliza X dentro da metade direita → 0 (centro visual) .. 1 (borda direita)
            rx_norm = (RIGHT_HAND_X_MAX - rx) / RIGHT_HAND_X_MAX
            r_open = _hand_openness(right_lm)

            # Velocidade 2D (coords brutas de câmera para manter escalas dos thresholds)
            vx_r, vy_r = right_vel.update(rx, ry, now)

            # Detector de oscilação no eixo X (vibrato lateral do pulso)
            # Usar X em vez de Y evita confundir mudança de pitch com vibrato
            osc_freq, osc_amp = right_osc.update(rx, now)

            # Vibrato: frequências altas (3.5..10 Hz) com histerese
            # — histerese evita que frames isolados sem detecção derrubem o efeito
            if VIB_FREQ_MIN <= osc_freq <= VIB_FREQ_MAX:
                vib_hold = VIB_HOLD_FRAMES
                s_vib_rate.update(osc_freq)
                s_vib_depth.update(min(VIB_MAX_DEPTH, osc_amp * VIB_AMP_SCALE))
            else:
                if vib_hold > 0:
                    vib_hold -= 1
                    # Mantém os valores atuais — não atualiza para 0
                else:
                    s_vib_rate.update(0.0)
                    s_vib_depth.update(0.0)

            # Tremolo: frequências baixas (1..5 Hz)
            if TREM_FREQ_MIN <= osc_freq <= TREM_FREQ_MAX:
                s_trem_rate.update(osc_freq)
                s_trem_depth.update(min(1.0, osc_amp * TREM_AMP_SCALE))
            else:
                s_trem_rate.update(0.0)
                s_trem_depth.update(0.0)

            # Pitch: eixo Y — cima = agudo (full screen height)
            target_pitch = PITCH_LOW + (1.0 - ry) * (PITCH_HIGH - PITCH_LOW)
            target_pitch = max(PITCH_LOW - 6.0, min(PITCH_HIGH + 6.0, target_pitch))
            smooth_pitch = s_pitch.update(target_pitch)
            smooth_pitch = max(PITCH_LOW - 6.0, min(PITCH_HIGH + 6.0, smooth_pitch))

            # Pan: rx_norm dentro da metade direita (0=centro visual, 1=borda direita)
            s_pan_r.update(rx_norm * 127.0)
            _audio_queue.put(("cc", MELODY_CH, 10, int(s_pan_r.value)))

            # Timbre: abertura da mão → CC 74 (brightness) — curva ^0.6 para resposta mais forte
            s_bright_r.update(pow(r_open, 0.6) * 127.0)
            _audio_queue.put(("cc", MELODY_CH, 74, int(s_bright_r.value)))

            # Kick: deslocamento vertical ≥ 30% da tela em 0.8 s (mão direita)
            ry_now = right_lm[0].y
            if kick_origin_y is None:
                kick_origin_y, kick_origin_t = ry_now, now
            else:
                dy_k = ry_now - kick_origin_y   # positivo = descida
                dt_k = now - kick_origin_t
                if dt_k <= PERC_SWIPE_MAX_TIME:
                    if dy_k >= PERC_SWIPE_DIST and (now - last_kick_ts) >= PERC_COOLDOWN:
                        last_kick_ts  = now
                        kick_origin_y = None
                        kick_origin_t = None
                        _trigger_perc(KICK_NOTE)
                        event_log.append(("kick", now))
                else:
                    kick_origin_y, kick_origin_t = ry_now, now

            # Accent / Swell (abertura ou fechamento rápido da mão)
            for evt in right_gesture.update(vx_r, vy_r, r_open, now):
                event_log.append((evt, now))
                if evt == "accent":
                    accent_decay = 1.0
                elif evt == "swell":
                    swell_decay = 1.0

            # Nota MIDI + pitch bend (fracionário + vibrato LFO)
            new_note  = int(round(smooth_pitch))
            frac_bend = int((smooth_pitch - new_note) * BEND_UNIT)
            vib_bend  = int(
                math.sin(vib_phase) * (s_vib_depth.value or 0.0) * BEND_UNIT
            )
            total_bend = max(-8000, min(8000, frac_bend + vib_bend))

            # Velocity dinâmica: accent eleva momentaneamente
            vel = max(1, min(127, NORMAL_VELOCITY + int(accent_decay * (MAX_VELOCITY - NORMAL_VELOCITY))))

            if not playing:
                _audio_queue.put(("noteon", MELODY_CH, new_note, vel))
                _audio_queue.put(("bend", total_bend))
                current_note = new_note
                playing = True
            else:
                if new_note != current_note:
                    _audio_queue.put(("noteon",  MELODY_CH, new_note, vel))
                    _audio_queue.put(("noteoff", MELODY_CH, current_note))
                    current_note = new_note
                _audio_queue.put(("bend", total_bend))

        else:
            kick_origin_y = None
            kick_origin_t = None
            right_vel.reset()
            right_osc.reset()
            vib_hold = 0
            s_vib_rate.update(0.0)
            s_vib_depth.update(0.0)
            s_trem_rate.update(0.0)
            s_trem_depth.update(0.0)
            if playing and (now - last_right_ts) > HAND_ABSENT_SECS:
                _audio_queue.put(("bend", 0))
                _audio_queue.put(("noteoff", MELODY_CH, current_note))
                playing = False

        # ═══════════════════════════════════════════════════════════════════
        # Mão esquerda — volume, reverb, chorus, accent/swell
        # ═══════════════════════════════════════════════════════════════════
        # Mão esquerda: ativa apenas na metade esquerda do display
        # (camera_x > 0.5 = lado esquerdo visual após flip do display)
        if left_lm is not None and left_lm[0].x > LEFT_HAND_X_MIN:
            lx, ly = left_lm[0].x, left_lm[0].y
            # Re-normaliza X dentro da metade esquerda → 0 (centro visual) .. 1 (borda esquerda)
            lx_norm = (lx - LEFT_HAND_X_MIN) / (1.0 - LEFT_HAND_X_MIN)
            l_open = _hand_openness(left_lm)

            vx_l, vy_l = left_vel.update(lx, ly, now)

            # Snare: deslocamento vertical ≥ 30% da tela em 0.8 s (mão esquerda)
            if snare_origin_y is None:
                snare_origin_y, snare_origin_t = ly, now
            else:
                dy_s = ly - snare_origin_y   # positivo = descida
                dt_s = now - snare_origin_t
                if dt_s <= PERC_SWIPE_MAX_TIME:
                    if dy_s >= PERC_SWIPE_DIST and (now - last_snare_ts) >= PERC_COOLDOWN:
                        last_snare_ts  = now
                        snare_origin_y = None
                        snare_origin_t = None
                        _trigger_perc(SNARE_NOTE)
                        event_log.append(("snare", now))
                else:
                    snare_origin_y, snare_origin_t = ly, now

            # Accent / Swell
            for evt in left_gesture.update(vx_l, vy_l, l_open, now):
                event_log.append((evt, now))
                if evt == "accent":
                    accent_decay = 1.0
                elif evt == "swell":
                    swell_decay = 1.0

            # Volume: Y com padding — VOL_Y_PAD_TOP=máx, VOL_Y_PAD_BOT=zero
            vol_raw = 1.0 - (ly - VOL_Y_PAD_TOP) / (VOL_Y_PAD_BOT - VOL_Y_PAD_TOP)
            s_volume.update(max(0.0, min(127.0, vol_raw * 127.0)))

            # Reverb: lx_norm → curva ^0.6 para resposta mais forte + boost de swell
            base_reverb = pow(lx_norm, 0.6) * 127.0 + swell_decay * 80.0
            s_reverb.update(min(127.0, base_reverb))

            # Chorus: abertura → curva ^0.6 para resposta mais forte
            s_chorus.update(pow(l_open, 0.6) * 127.0)

            # Volume final modulado pelo tremolo LFO
            trem_mod    = (s_trem_depth.value or 0.0) * TREM_DEPTH
            trem_factor = 1.0 - trem_mod * max(0.0, (1.0 - math.sin(trem_phase))) * 0.5
            vol_final   = max(0, min(127, int((s_volume.value or 127.0) * trem_factor)))

            _audio_queue.put(("cc", MELODY_CH, 11, vol_final))
            _audio_queue.put(("cc", MELODY_CH, 91, int(s_reverb.value or 20)))
            _audio_queue.put(("cc", MELODY_CH, 93, int(s_chorus.value or 0)))

        else:
            snare_origin_y = None
            snare_origin_t = None
            left_vel.reset()

        # ── Render ────────────────────────────────────────────────────────
        frame_display = cv2.resize(frame_rgb, (logical_w, logical_h))
        frame_display = cv2.flip(frame_display, 1)
        surface.blit(
            pygame.image.frombuffer(
                frame_display.tobytes(), (logical_w, logical_h), "RGB"
            ),
            (0, 0),
        )

        if show_viz:
            brain_viz.draw_overlay(surface, darken_alpha=60)

        if show_menu:
            _render_ui(
                surface, font, logical_w, logical_h,
                playing, current_note,
                s_pitch, s_pan_r, s_bright_r,
                s_vib_rate, s_vib_depth,
                s_trem_rate, s_trem_depth,
                s_volume, s_reverb, s_chorus,
                vib_phase, trem_phase,
                accent_decay, swell_decay,
                event_log, now,
                current_instrument=current_instr_name,
                current_emotion=current_emotion,
            )

        if _recorder.is_recording:
            draw_recording_indicator(surface, logical_w, logical_h, font)
        if _recorder.is_playing:
            draw_playback_indicator(surface, logical_w, font)

        pygame.transform.scale(surface, (display_w, display_h), screen)
        pygame.display.flip()
        clock.tick(target_fps)

    # ── Limpeza ──────────────────────────────────────────────────────────────
    if playing and current_note >= 0:
        try:
            _fs.noteoff(MELODY_CH, current_note)
        except Exception:
            pass

    if _recorder.is_recording:
        _recorder.stop_recording()

    _audio_queue.put(None)
    audio_thread.join(timeout=2.0)

    emotion_tracker.stop()
    hands.close()
    cam.stop()
    cap.release()
    pygame.quit()
    try:
        _fs.delete()
    except Exception:
        pass
