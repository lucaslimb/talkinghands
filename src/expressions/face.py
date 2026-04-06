"""
Face — instrumento de trilha sonora dirigido por expressão facial.

Cada emoção toca num canal MIDI dedicado com um timbre próprio, de forma que
em qualquer momento até 7 sons coexistem e se misturam proporcionalmente à
intensidade de cada emoção detectada no rosto.

O volume de cada canal é proporcional ao score daquela emoção, criando
transições orgânicas entre estados. Neutral não toca nenhum som — o seu
score controla a *velocidade* do fade geral: score alto = fade abrupto,
score baixo = fade lento e gradual (como uma cena cinematográfica).

Emoções e seus sons de trilha:
    Happiness  → Crystal (brilhante, etiléreo)
    Sadness    → Warm Pad (suave, melancolia)
    Anger      → Goblin   (grave, tensão)
    Fear       → Rain     (indefinido, perturbador)
    Surprise   → Space Voices (etiléreo, inesperado)
    Contempt   → Metallic Pad (frío, duro)
    Disgust    → Atmosphere   (profundo, opressivo)
    Neutral    → silêncio
"""

from pathlib import Path
import sys
import os
import threading
import queue
import warnings
import time
import math

import cv2
import mediapipe as mp
import numpy as np
import pygame

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.engines.recorder import MidiRecorder
from src.instruments.common import (
    init_fluidsynth, load_all_soundfonts,
    setup_video_capture, setup_pygame_with_scaling, fit_resolution_to_screen,
    CameraThread, prepare_mediapipe_frame,
)

import fluidsynth

from src.expressions.face_visualization import BrainVisualizer

# ── Parâmetros ────────────────────────────────────────────────────────────────
# Sensibilidade: EMA rápida e análise frequente
SMOOTH_EMOTION   = 0.15   # EMA — maior = resposta mais rápida
EMOTION_INTERVAL = 0.05   # analisar a cada ~50 ms (~20 fps)

# Volume suavizado por canal
SMOOTH_VOL   = 0.10   # EMA para volume de cada canal (transições lentas)
# Fator de amplificação: score 0..1 → volume 0..127
VOL_SCALE    = 127
# Volume mínimo de cada canal (mesmo com score baixo, emoções são audíveis)
VOL_MIN      = 20
# Limiar abaixo do qual um canal é considerado silencioso (UI)
VOL_THRESH   = 2
# Nota sustentada em cada canal (cada emoção tem sua própria nota)
MP_INPUT_HEIGHT = 480

# ── Configuração de canais por emoção ───────────────────────────────────
# Cada emoção tem: canal MIDI, instrumento (do settings.INSTRUMENTS), nota, reverb
# Neutral não tem entrada — controla apenas o fade geral.
EMOTION_CHANNELS = [
    # (emotion,    ch, instrument_name,   note, reverb)
    ("Happiness",  0, "Blue Planet",      64,    40),  # E4 — harmônico vivo, caloroso e positivo
    ("Sadness",    1, "Warm Pad",           57,   65),  # A3 — suave e melancolíco
    ("Anger",      2, "Goblin",             45,   15),  # A2 — grave e tenso
    ("Fear",       3, "Oohs",               40,   65),  # E2 — vocal orgânico e perturbador
    ("Surprise",   4, "Space Voices",       72,   30),  # C5 — etéreo, inesperado
    ("Contempt",   5, "Metallic Pad",       50,   20),  # D3 — frío e duro
    ("Disgust",    6, "Rain",               54,   80),  # F#3 — perturbador, instável
]

EMOTION_COLORS = {
    "Happiness": (255, 230,  50),
    "Sadness":   ( 80, 130, 220),
    "Anger":     (230,  50,  50),
    "Fear":      (180,  80, 230),
    "Surprise":  (255, 160,  30),
    "Contempt":  (160, 160, 100),
    "Disgust":   (100, 200,  80),
    "Neutral":   (180, 180, 180),
}




# ── EmotionTracker ────────────────────────────────────────────────────────────

class EmotionTracker:
    """
    Analisa emoções faciais num thread de background usando hsemotion-onnx.
    Expõe `emotion` (str) e `scores` (dict label→float 0..1), suavizados por EMA.
    Degrada silenciosamente para "Neutral" se o modelo não estiver disponível.
    """

    LABELS = ["Anger", "Contempt", "Disgust", "Fear",
              "Happiness", "Neutral", "Sadness", "Surprise"]

    def __init__(self):
        self.emotion  = "Neutral"
        self.scores   = {lbl: (1.0 if lbl == "Neutral" else 0.0)
                         for lbl in self.LABELS}
        self._smooth  = {lbl: self.scores[lbl] for lbl in self.LABELS}
        self._lock    = threading.Lock()
        self._queue   = queue.Queue(maxsize=1)   # apenas o frame mais recente
        self._running = True
        self._recognizer = None
        self._face_det   = None
        self._load_model()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _load_model(self):
        """Carrega hsemotion e MediaPipe FaceDetection; falha silenciosamente."""
        try:
            warnings.filterwarnings("ignore", message="Unverified HTTPS")
            from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
            self._recognizer = HSEmotionRecognizer(model_name="enet_b0_8_best_vgaf")
            self._face_det   = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            )
            print(">>> EmotionTracker: modelo carregado.")
        except Exception as e:
            print(f">>> EmotionTracker: modelo não disponível ({e}). Usando Neutral.")
            self._recognizer = None
            self._face_det   = None

    def submit_frame(self, frame_rgb: np.ndarray):
        """Enfileira o frame mais recente para análise (descarta se ocupado)."""
        if self._recognizer is None:
            return
        try:
            self._queue.put_nowait(frame_rgb.copy())
        except queue.Full:
            pass

    def _worker(self):
        while self._running:
            try:
                frame_rgb = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._recognizer is None or self._face_det is None:
                continue
            try:
                result = self._face_det.process(frame_rgb)
                if not result.detections:
                    continue
                det  = result.detections[0]
                bbox = det.location_data.relative_bounding_box
                h, w = frame_rgb.shape[:2]
                x1 = max(0, int(bbox.xmin * w))
                y1 = max(0, int(bbox.ymin * h))
                x2 = min(w, x1 + int(bbox.width  * w))
                y2 = min(h, y1 + int(bbox.height * h))
                if x2 <= x1 or y2 <= y1:
                    continue
                face = cv2.cvtColor(frame_rgb[y1:y2, x1:x2], cv2.COLOR_RGB2BGR)
                emotion_label, logits = self._recognizer.predict_emotions(face, logits=True)
                # softmax
                exp   = np.exp(logits - logits.max())
                probs = exp / exp.sum()

                new_scores = {lbl: float(probs[i]) for i, lbl in enumerate(self.LABELS)}

                with self._lock:
                    for lbl in self.LABELS:
                        self._smooth[lbl] += SMOOTH_EMOTION * (
                            new_scores[lbl] - self._smooth[lbl]
                        )
                    self.emotion = max(self._smooth, key=self._smooth.get)
                    self.scores  = dict(self._smooth)
            except Exception:
                pass

    def stop(self):
        self._running = False
        self._thread.join(timeout=2.0)
        if self._face_det:
            try:
                self._face_det.close()
            except Exception:
                pass

    def get_modifiers(self) -> dict:
        """Kept for compatibility. Returns empty dict (not used by start_face)."""
        return {}

    def get_state(self):
        """Retorna (emotion_str, scores_dict) thread-safe."""
        with self._lock:
            return self.emotion, dict(self.scores)

    def get_weighted_modifier(self, key: str) -> float:
        """Kept for compatibility. Not used by start_face()."""
        return 0.0


# ── Fila de áudio (face) ──────────────────────────────────────────────────────

_face_audio_queue: "queue.Queue[tuple | None]" = queue.Queue()
_face_fs = None


def _face_audio_worker():
    while True:
        item = _face_audio_queue.get()
        if item is None:
            break
        try:
            action = item[0]
            if action == "noteon":
                _, ch, note, vel = item
                _face_fs.noteon(ch, note, vel)
            elif action == "noteoff":
                _, ch, note = item
                _face_fs.noteoff(ch, note)
            elif action == "cc":
                _, ch, ctrl, value = item
                _face_fs.cc(ch, ctrl, value)
        except Exception:
            pass


# ── Função principal ──────────────────────────────────────────────────────────

def start_face(
    chosen_instrument="Face",
    rec_options=None,
    resolution_profile=None,
    show_trackers=False,
    hand_model_complexity=1,
):
    """Instrumento Face: trilha sonora dirigida por expressão facial.
    Cada emoção toca num canal MIDI independente com seu próprio timbre.
    O volume de cada canal é proporcional ao score daquela emoção.
    Neutral silencia tudo — gradualmente (score baixo) ou abruptamente
    (score alto)."""
    global _face_fs

    # ── Resolução ─────────────────────────────────────────────────────────
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

    # ── Áudio ─────────────────────────────────────────────────────────────
    _face_fs, loaded_sfids = init_fluidsynth(driver="dsound")
    if _face_fs is None:
        print("ERRO CRÍTICO DE AUDIO: FluidSynth não inicializado.")
        return

    loaded_sfids = load_all_soundfonts(_face_fs)
    master_sfid  = loaded_sfids.get("master")
    if master_sfid is None:
        print("ERRO: soundfont 'master' não carregado.")
        return

    try:
        _face_fs.setting('synth.gain', 2.0)
    except Exception:
        pass

    # Configurar cada canal com o instrumento da emoção correspondente
    from src.config import settings as _settings
    for emotion, ch, instr_name, note, reverb in EMOTION_CHANNELS:
        sf_key, bank, preset = _settings.INSTRUMENTS.get(
            instr_name, ("master", 1, 6)
        )
        sfid = loaded_sfids.get(sf_key, master_sfid)
        _face_fs.program_select(ch, sfid, bank, preset)
        _face_fs.cc(ch, 7,  127)  # channel volume
        _face_fs.cc(ch, 11,   0)  # expression — inicia silencioso
        _face_fs.cc(ch, 91, reverb)

    audio_thread = threading.Thread(target=_face_audio_worker, daemon=True)
    audio_thread.start()

    # Disparar nota sustentada em cada canal (sempre ligada, volume controla o som)
    for emotion, ch, instr_name, note, reverb in EMOTION_CHANNELS:
        _face_audio_queue.put(("noteon", ch, note, 100))

    # ── EmotionTracker ────────────────────────────────────────────────────
    tracker = EmotionTracker()
    last_emotion_ts = 0.0

    # ── Câmera ────────────────────────────────────────────────────────────
    cap = setup_video_capture(logical_w, logical_h, target_fps)
    cam = CameraThread(cap)

    # ── Pygame ────────────────────────────────────────────────────────────
    screen, surface, font = setup_pygame_with_scaling(
        logical_w, logical_h, display_w, display_h,
        title="Face — Trilha Sonora Emocional"
    )
    clock = pygame.time.Clock()

    # ── Estado ────────────────────────────────────────────────────────────
    show_viz  = True
    last_emotion_ts = 0.0

    # Volume suavizado por emoção (0..127), inicializa em 0 (silencioso)
    s_vols = {emotion: 0.0 for emotion, _, _, _, _ in EMOTION_CHANNELS}
    s_vols["Neutral"] = 0.0  # apenas para UI

    # ── Visualizador neural ─────────────────────────────────────────────
    brain_viz = BrainVisualizer(logical_w, logical_h)

    print(">>> Face pronto. Aponte o rosto para a câmera.")
    print("    Expressões faciais são a única entrada — cada emoção toca um som.")
    print("    V=visualização  ESC=sair")

    # ── Loop principal ────────────────────────────────────────────────────
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_v:
                    show_viz = not show_viz

        frame, _ = cam.get_latest()
        if frame is None:
            clock.tick(target_fps)
            continue

        now = time.perf_counter()

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_frame  = prepare_mediapipe_frame(frame_rgb, logical_w, logical_h, MP_INPUT_HEIGHT)

        # Submeter frame ao tracker periodicamente
        if now - last_emotion_ts >= EMOTION_INTERVAL:
            tracker.submit_frame(mp_frame)
            last_emotion_ts = now

        _, scores = tracker.get_state()
        neutral_score = scores.get("Neutral", 0.0)

        # Velocidade do fade: score de Neutral interpola entre EMA lenta e rápida.
        # Neutral baixo (0) → alpha=0.04 (fade gradual, cinematográfico)
        # Neutral alto (1)  → alpha=0.40 (fade abrupto)
        fade_alpha = 0.04 + neutral_score * 0.36

        for emotion, ch, _, _, _ in EMOTION_CHANNELS:
            score = scores.get(emotion, 0.0)

            # Score da emoção é atenuado proporcionalmente ao Neutral:
            # quanto mais Neutral, mais o score de cada emoção é comprimido
            effective  = score * (1.0 - neutral_score)
            # Volume mínimo (VOL_MIN) garante que mesmo emoções de baixo score
            # sejam audíveis; ambos escalam a zero quando Neutral domina.
            target_vol = (VOL_MIN + effective * (VOL_SCALE - VOL_MIN)) * (1.0 - neutral_score)

            s_vols[emotion] = s_vols[emotion] + fade_alpha * (target_vol - s_vols[emotion])
            vol = max(0, min(127, int(s_vols[emotion])))
            _face_audio_queue.put(("cc", ch, 11, vol))

        s_vols["Neutral"] = neutral_score * 127  # apenas para UI

        # ── Atualizar visualizador ──────────────────────────────────────────
        brain_viz.update_emotions(scores)
        brain_viz.update(1.0 / target_fps)

        # ── Render ─────────────────────────────────────────────────────────
        frame_display = cv2.resize(frame_rgb, (logical_w, logical_h))
        frame_display = cv2.flip(frame_display, 1)
        surface.blit(
            pygame.image.frombuffer(frame_display.tobytes(), (logical_w, logical_h), "RGB"),
            (0, 0),
        )

        # Overlay da visualização neural sobre o vídeo
        if show_viz:
            brain_viz.draw_overlay(surface, darken_alpha=60)

        pygame.transform.scale(surface, (display_w, display_h), screen)
        pygame.display.flip()
        clock.tick(target_fps)

    # ── Limpeza ───────────────────────────────────────────────────────────
    for emotion, ch, _, note, _ in EMOTION_CHANNELS:
        try:
            _face_fs.noteoff(ch, note)
        except Exception:
            pass

    _face_audio_queue.put(None)
    audio_thread.join(timeout=2.0)

    tracker.stop()
    cam.stop()
    cap.release()
    pygame.quit()
    try:
        _face_fs.delete()
    except Exception:
        pass
