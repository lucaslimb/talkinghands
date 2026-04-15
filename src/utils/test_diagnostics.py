"""
Diagnóstico completo para os módulos _ui: pipeline FPS + latência real de áudio.

Mede o que realmente importa para os instrumentos _ui:
  1. Pipeline FPS — câmera + resize/flip + MediaPipe inferência (mesmo fluxo do _on_frame_tick)
  2. Latência real — MediaPipe inferência + queue dispatch + FluidSynth noteon
     (simula o caminho completo: dedo detectado → som emitido)

Uso:
    python src/utils/test_diagnostics.py              # Todos os testes
    python src/utils/test_diagnostics.py --pipeline    # Apenas pipeline FPS
    python src/utils/test_diagnostics.py --audio       # Apenas latência de áudio
"""

import sys
import os
import time
import queue
import threading
import argparse
import numpy as np
from pathlib import Path

# ── Resolve project root (same pattern as main.py / common.py) ──────────
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(PROJECT_ROOT))

# ── FluidSynth env setup (must happen before importing fluidsynth) ──────
_fluidsynth_bin = PROJECT_ROOT / "assets" / "fluidsynth-v2.5.1" / "bin"
if _fluidsynth_bin.exists():
    _bin_str = str(_fluidsynth_bin)
    os.environ["FLUIDSYNTH_PATH"] = _bin_str
    current_path = os.environ.get("PATH", "")
    if _bin_str not in current_path:
        os.environ["PATH"] = f"{_bin_str};{current_path}"
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(_bin_str)
        except Exception:
            pass

# Patch os.add_dll_directory to ignore pyfluidsynth's hardcoded bad path
_original_add_dll_directory = getattr(os, "add_dll_directory", None)
if _original_add_dll_directory:
    def _safe_add_dll_directory(path):
        if path.lower() == r"c:\tools\fluidsynth\bin":
            return None
        return _original_add_dll_directory(path)
    os.add_dll_directory = _safe_add_dll_directory

# ── Imports that depend on env ──────────────────────────────────────────
import cv2

try:
    import fluidsynth as _fs_mod
    HAS_FLUIDSYNTH = True
except Exception:
    HAS_FLUIDSYNTH = False

if _original_add_dll_directory:
    os.add_dll_directory = _original_add_dll_directory

try:
    import mediapipe as mp
    HAS_MEDIAPIPE = True
except Exception:
    HAS_MEDIAPIPE = False

from src.config import settings

# ═══════════════════════════════════════════════════════════════════════════
#  PIPELINE FPS TEST
#  Reproduces the _ui frame loop: camera grab → resize/flip → MediaPipe
# ═══════════════════════════════════════════════════════════════════════════

PIPELINE_DURATION   = 5       # seconds
PIPELINE_WARMUP     = 1.0     # seconds (let camera + MP settle)
CAM_READ_TIMEOUT    = 2.0


def _read_frame_with_timeout(cap, timeout=CAM_READ_TIMEOUT):
    result = {"ret": None, "frame": None}

    def _reader():
        try:
            result["ret"], result["frame"] = cap.read()
        except Exception:
            result["ret"] = False

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return False, None
    return result["ret"], result["frame"]


def run_pipeline_test(verbose=True):
    """Measure real pipeline FPS: camera → resize/flip → MediaPipe inference.

    This matches the _on_frame_tick() flow in keyboard_ui / drums_ui.
    Returns result dict or None.
    """
    if verbose:
        print("\n╔══════════════════════════════════════╗")
        print("║     TESTE DE PIPELINE FPS (_ui)      ║")
        print("╚══════════════════════════════════════╝\n")

    if not HAS_MEDIAPIPE:
        if verbose:
            print("  ERRO: MediaPipe não disponível.\n")
        return None

    # ── Open camera (same as common.py setup_video_capture) ─────────────
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        if verbose:
            print("  ERRO: Não foi possível abrir a webcam.\n")
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if verbose:
        print(f"  Câmera: {actual_w}x{actual_h}")

    # ── Init MediaPipe Hands (same params as _ui files) ─────────────────
    hands = mp.solutions.hands.Hands(
        max_num_hands=2,
        model_complexity=1,
        min_detection_confidence=0.3,
        min_tracking_confidence=0.3,
    )

    # ── Warmup (let auto-exposure + MP JIT settle) ──────────────────────
    if verbose:
        print(f"  Aquecendo ({PIPELINE_WARMUP}s) …", end=" ", flush=True)

    warmup_start = time.perf_counter()
    while time.perf_counter() - warmup_start < PIPELINE_WARMUP:
        ret, frame = _read_frame_with_timeout(cap)
        if not ret:
            continue
        frame = cv2.resize(frame, (1280, 720))
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        hands.process(rgb)

    if verbose:
        print("OK")

    # ── Measure pipeline FPS ────────────────────────────────────────────
    if verbose:
        print(f"  Medindo pipeline ({PIPELINE_DURATION}s) …", end=" ", flush=True)

    frame_times = []
    mp_times = []
    frames = 0
    start = time.perf_counter()

    while time.perf_counter() - start < PIPELINE_DURATION:
        t0 = time.perf_counter()

        ret, frame = cap.read()
        if not ret:
            continue

        # Same processing as _on_frame_tick
        frame = cv2.resize(frame, (1280, 720))
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # MediaPipe inference (synchronous here to measure real cost)
        t_mp0 = time.perf_counter()
        hands.process(rgb)
        t_mp1 = time.perf_counter()
        mp_times.append(t_mp1 - t_mp0)

        t1 = time.perf_counter()
        frame_times.append(t1 - t0)
        frames += 1

    elapsed = time.perf_counter() - start
    hands.close()
    cap.release()

    if frames == 0:
        if verbose:
            print("FALHOU (0 frames)\n")
        return None

    fps = frames / elapsed
    avg_frame_ms = (sum(frame_times) / len(frame_times)) * 1000
    avg_mp_ms = (sum(mp_times) / len(mp_times)) * 1000
    min_mp_ms = min(mp_times) * 1000
    max_mp_ms = max(mp_times) * 1000

    # P95 frame time
    sorted_ft = sorted(frame_times)
    p95_frame_ms = sorted_ft[int(len(sorted_ft) * 0.95)] * 1000

    if verbose:
        print(f"{fps:.1f} fps")
        print()
        print("  ── Pipeline ──")
        print(f"  FPS total:             {fps:.1f}")
        print(f"  Frame médio:           {avg_frame_ms:.1f} ms")
        print(f"  Frame P95:             {p95_frame_ms:.1f} ms")
        print(f"  MediaPipe médio:       {avg_mp_ms:.1f} ms")
        print(f"  MediaPipe min/max:     {min_mp_ms:.1f} / {max_mp_ms:.1f} ms")

        # The _ui files run MP in a background thread, so effective FPS
        # is higher (camera read + resize only ~2-5ms overhead).
        # Pipeline FPS here is synchronous (worst case).
        overhead_ms = avg_frame_ms - avg_mp_ms
        async_fps = 1000.0 / max(overhead_ms, 1.0)
        print(f"  Overhead sem MP:       {overhead_ms:.1f} ms  (~{min(async_fps, 999):.0f} fps teórico c/ MP async)")
        print()

    return {
        "fps": round(fps, 1),
        "avg_frame_ms": round(avg_frame_ms, 1),
        "p95_frame_ms": round(p95_frame_ms, 1),
        "avg_mediapipe_ms": round(avg_mp_ms, 1),
        "min_mediapipe_ms": round(min_mp_ms, 1),
        "max_mediapipe_ms": round(max_mp_ms, 1),
        "overhead_ms": round(avg_frame_ms - avg_mp_ms, 1),
        "frames": frames,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  AUDIO LATENCY TEST
#  Uses the REAL async threading from common.py (CameraThread +
#  MediaPipeHandsThread + audio queue) — same architecture as _ui files.
# ═══════════════════════════════════════════════════════════════════════════

AUDIO_WARMUP_SEC   = 2.0      # let MP thread + audio settle
AUDIO_MEASURE_SEC  = 5.0      # measurement window
AUDIO_NOTE         = 60       # middle C
AUDIO_VELOCITY     = 100
AUDIO_NOTE_DUR     = 0.05     # seconds note stays on
AUDIO_NOTE_GAP     = 0.15     # gap between notes


def run_audio_test(verbose=True):
    """Measure realistic end-to-end latency using the SAME async architecture
    as the _ui instruments: CameraThread + MediaPipeHandsThread + audio queue.

    The main loop runs at ~1ms intervals (matching QTimer(1) from _ui):
      1. CameraThread grabs latest frame (background, non-blocking)
      2. submit_frame() to MediaPipeHandsThread (instant, fire-and-forget)
      3. get_latest_result() returns most recent completed result (instant)
      4. If result has hands → gesture logic → queue.put() with timestamp
      5. Audio thread: queue.get() → noteon() → records play timestamp

    We measure the time between "result became available" and "noteon called",
    plus the staleness of the MP result (how old it is when consumed).

    Returns result dict or None.
    """
    if verbose:
        print("\n╔══════════════════════════════════════╗")
        print("║     TESTE DE LATÊNCIA DE ÁUDIO       ║")
        print("╚══════════════════════════════════════╝\n")

    if not HAS_FLUIDSYNTH:
        if verbose:
            print("  ERRO: FluidSynth não disponível.\n")
        return None
    if not HAS_MEDIAPIPE:
        if verbose:
            print("  ERRO: MediaPipe não disponível.\n")
        return None

    # ── Init FluidSynth ─────────────────────────────────────────────────
    if verbose:
        print("  Inicializando FluidSynth …", end=" ", flush=True)

    t0 = time.perf_counter()
    try:
        fs = _fs_mod.Synth()
        fs.start(driver="dsound")
    except Exception as e:
        if verbose:
            print(f"ERRO: {e}\n")
        return None
    init_time = (time.perf_counter() - t0) * 1000
    if verbose:
        print(f"{init_time:.0f} ms")

    # ── Load soundfont ──────────────────────────────────────────────────
    sf_path = settings.SF2_PATHS.get("master")
    if not sf_path or not os.path.exists(sf_path):
        sf_path = settings.SF2_PATHS.get("drums")
    if not sf_path or not os.path.exists(sf_path):
        if verbose:
            print("  ERRO: Nenhum soundfont encontrado.\n")
        fs.delete()
        return None
    if verbose:
        print(f"  Carregando soundfont ({Path(sf_path).name}) …", end=" ", flush=True)
    t0 = time.perf_counter()
    sfid = fs.sfload(sf_path)
    load_time = (time.perf_counter() - t0) * 1000
    if sfid == -1:
        if verbose:
            print("FALHOU\n")
        fs.delete()
        return None
    if verbose:
        print(f"{load_time:.0f} ms")
    fs.program_select(0, sfid, 0, 0)

    # ── Open camera (same as common.py) ─────────────────────────────────
    if verbose:
        print("  Abrindo câmera …", end=" ", flush=True)
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        if verbose:
            print("FALHOU\n")
        fs.delete()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if verbose:
        print("OK")

    # ── Start CameraThread + MediaPipeHandsThread (same as _ui) ────────
    from src.instruments.common import (
        CameraThread, MediaPipeHandsThread, prepare_mediapipe_frame
    )

    cam_thread = CameraThread(cap)
    hands_model = mp.solutions.hands.Hands(
        max_num_hands=2,
        model_complexity=1,
        min_detection_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    mp_thread = MediaPipeHandsThread(hands_model)

    # ── Audio queue (same pattern as _ui) ───────────────────────────────
    audio_q = queue.Queue()
    play_records = []     # (enqueue_ts, play_ts)
    ready_event = threading.Event()

    def _audio_loop():
        ready_event.set()
        while True:
            item = audio_q.get()
            if item is None:
                break
            action, note, vel, enqueue_ts = item
            if action == "on":
                fs.noteon(0, note, vel)
                play_records.append((enqueue_ts, time.perf_counter()))
            elif action == "off":
                fs.noteoff(0, note)

    audio_t = threading.Thread(target=_audio_loop, daemon=True)
    audio_t.start()
    ready_event.wait()

    # ── Warmup (let all threads settle) ─────────────────────────────────
    if verbose:
        print(f"  Aquecendo ({AUDIO_WARMUP_SEC}s) …", end=" ", flush=True)

    warmup_start = time.perf_counter()
    while time.perf_counter() - warmup_start < AUDIO_WARMUP_SEC:
        frame, _ = cam_thread.get_latest()
        if frame is not None:
            frame = cv2.resize(frame, (1280, 720))
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_frame = prepare_mediapipe_frame(rgb, 1280, 720)
            mp_thread.submit_frame(mp_frame)
            mp_thread.get_latest_result()
        time.sleep(0.001)

    # Warmup audio path
    for _ in range(5):
        audio_q.put(("on", AUDIO_NOTE, AUDIO_VELOCITY, time.perf_counter()))
        time.sleep(AUDIO_NOTE_DUR)
        audio_q.put(("off", AUDIO_NOTE, 0, 0))
        time.sleep(0.05)
    play_records.clear()

    if verbose:
        print("OK")

    # ── Measure: MP pipeline delay + queue latency ────────────────────
    #
    # MP pipeline delay: submit a single frame → wait until result changes.
    # This measures the real async delay (submit → new result available),
    # exactly as experienced in the _ui main loop.
    #
    # Queue latency: enqueue → noteon (same as before).
    #
    if verbose:
        print(f"  Medindo latência async ({AUDIO_MEASURE_SEC}s) …", end=" ", flush=True)

    mp_pipeline_delays = []
    queue_latencies = []
    notes_played = 0

    measure_start = time.perf_counter()
    while time.perf_counter() - measure_start < AUDIO_MEASURE_SEC:
        # Grab a fresh frame
        frame, _ = cam_thread.get_latest()
        if frame is None:
            time.sleep(0.001)
            continue

        frame = cv2.resize(frame, (1280, 720))
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_frame = prepare_mediapipe_frame(rgb, 1280, 720)

        # Snapshot current result identity
        old_result = mp_thread.get_latest_result()
        old_id = id(old_result)

        # Submit frame and start timing
        t_submit = time.perf_counter()
        mp_thread.submit_frame(mp_frame)

        # Poll until a new result appears (MP thread finished inference)
        while True:
            new_result = mp_thread.get_latest_result()
            if id(new_result) != old_id:
                break
            # Safety timeout
            if time.perf_counter() - t_submit > 0.5:
                break
            time.sleep(0.0005)

        t_result = time.perf_counter()
        pipeline_delay = t_result - t_submit
        mp_pipeline_delays.append(pipeline_delay)

        # Check if hand was detected → trigger note through queue
        has_hands = (new_result is not None
                     and getattr(new_result, "multi_hand_landmarks", None) is not None)

        if has_hands:
            t_enqueue = time.perf_counter()
            audio_q.put(("on", AUDIO_NOTE, AUDIO_VELOCITY, t_enqueue))
            notes_played += 1

            # Brief note
            time.sleep(AUDIO_NOTE_DUR)
            audio_q.put(("off", AUDIO_NOTE, 0, 0))
            time.sleep(AUDIO_NOTE_GAP)
        else:
            time.sleep(0.01)

    # ── Cleanup ─────────────────────────────────────────────────────────
    audio_q.put(None)
    audio_t.join(timeout=2)
    mp_thread.close()
    cam_thread.stop()
    cap.release()

    # ── Compute latencies ───────────────────────────────────────────────
    for enq_ts, play_ts in play_records:
        queue_latencies.append(play_ts - enq_ts)

    n_mp = len(mp_pipeline_delays)
    n_queue = len(queue_latencies)

    if n_mp == 0:
        if verbose:
            print("FALHOU (0 amostras MP)\n")
        fs.delete()
        return None

    def _stats(arr):
        arr_ms = [x * 1000 for x in arr]
        avg = sum(arr_ms) / len(arr_ms)
        mn = min(arr_ms)
        mx = max(arr_ms)
        s = sorted(arr_ms)
        p95 = s[min(int(len(s) * 0.95), len(s) - 1)]
        return avg, mn, mx, p95

    mp_avg, mp_min, mp_max, mp_p95 = _stats(mp_pipeline_delays)

    if n_queue > 0:
        q_avg, q_min, q_max, q_p95 = _stats(queue_latencies)
    else:
        q_avg = q_min = q_max = q_p95 = 0.0

    # Total e2e: MP pipeline delay + queue dispatch
    e2e_avg = mp_avg + q_avg
    e2e_p95 = mp_p95 + q_p95

    if verbose:
        print(f"OK ({n_mp} ciclos MP, {notes_played} notas)")
        print()
        print("  ── Detalhamento ──")
        print(f"  FluidSynth init:       {init_time:.0f} ms")
        print(f"  Soundfont load:        {load_time:.0f} ms")
        print()
        print(f"  MP pipeline delay:     avg {mp_avg:.1f} ms  (P95 {mp_p95:.1f}, min {mp_min:.1f}, max {mp_max:.1f})")
        if n_queue > 0:
            print(f"  Queue → noteon:        avg {q_avg:.2f} ms  (P95 {q_p95:.2f}, min {q_min:.2f}, max {q_max:.2f})")
        else:
            print(f"  Queue → noteon:        N/A (mão não detectada)")
        print(f"  ─────────────────────────────────────")
        print(f"  Total (dedo → som):    avg {e2e_avg:.1f} ms  (P95 {e2e_p95:.1f})")
        print()

        if e2e_avg < 15:
            verdict = "EXCELENTE — imperceptível"
        elif e2e_avg < 30:
            verdict = "BOM — praticamente imperceptível"
        elif e2e_avg < 50:
            verdict = "ACEITÁVEL — leve atraso"
        elif e2e_avg < 100:
            verdict = "MEDIOCRE — atraso perceptível"
        else:
            verdict = "RUIM — atraso significativo"
        print(f"  Veredito:              {verdict}")
        print()

    fs.delete()

    return {
        "init_ms": round(init_time, 1),
        "sf_load_ms": round(load_time, 1),
        "mp_pipeline_avg_ms": round(mp_avg, 1),
        "mp_pipeline_p95_ms": round(mp_p95, 1),
        "queue_avg_ms": round(q_avg, 2),
        "queue_p95_ms": round(q_p95, 2),
        "e2e_avg_ms": round(e2e_avg, 1),
        "e2e_p95_ms": round(e2e_p95, 1),
        "notes_played": notes_played,
        "mp_samples": n_mp,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  COMBINED RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_all_diagnostics(verbose=True):
    """Run pipeline FPS + audio latency diagnostics. Returns combined dict."""
    pipeline = run_pipeline_test(verbose=verbose)
    audio    = run_audio_test(verbose=verbose)

    if verbose:
        print("╔══════════════════════════════════════╗")
        print("║         RESULTADO FINAL              ║")
        print("╚══════════════════════════════════════╝\n")
        if pipeline:
            overhead = pipeline["overhead_ms"]
            print(f"  Pipeline:  {pipeline['fps']:.0f} fps sync "
                  f"(MP {pipeline['avg_mediapipe_ms']:.0f}ms + overhead {overhead:.0f}ms)")
        else:
            print("  Pipeline:  INDISPONÍVEL")
        if audio:
            print(f"  Latência:  {audio['e2e_avg_ms']:.1f}ms dedo→som "
                  f"(MP {audio['mp_pipeline_avg_ms']:.0f}ms + queue {audio['queue_avg_ms']:.1f}ms)")
        else:
            print("  Latência:  INDISPONÍVEL")
        print()

    return {"pipeline": pipeline, "audio": audio}


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnóstico: pipeline FPS e latência de áudio (_ui)")
    parser.add_argument("--pipeline", action="store_true", help="Testar apenas pipeline FPS")
    parser.add_argument("--audio",    action="store_true", help="Testar apenas latência de áudio")
    args = parser.parse_args()

    if args.pipeline:
        run_pipeline_test()
    elif args.audio:
        run_audio_test()
    else:
        run_all_diagnostics()
