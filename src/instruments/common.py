# Common utilities shared across all instrument modules (drums, flute, keyboard)
# This module provides generalized functions to reduce code duplication

import cv2
import pygame
import sys
import os
import ctypes
import time
import threading
from pathlib import Path

from src.config import settings
from src.engines.recorder import MidiRecorder

# Configure FluidSynth path BEFORE importing fluidsynth
# This ensures the DLL can be found even on fresh installations
def _setup_fluidsynth_path():
    """Ensure FluidSynth DLL is in PATH before importing the module"""
    try:
        # Try to get the bundled FluidSynth path
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            project_root = Path(sys._MEIPASS)
        else:
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent.parent
        
        fluidsynth_bin = project_root / "assets" / "fluidsynth-v2.5.1" / "bin"
        
        if fluidsynth_bin.exists():
            bin_str = str(fluidsynth_bin)
            current_path = os.environ.get("PATH", "")
            
            # Add to PATH at the beginning (highest priority)
            if bin_str not in current_path:
                os.environ["PATH"] = f"{bin_str};{current_path}"
            
            # Set environment variables for pyfluidsynth
            os.environ["FLUIDSYNTH_PATH"] = bin_str
    except Exception as e:
        print(f"[!] Warning: Could not pre-configure FluidSynth path: {e}")

# Call before importing fluidsynth
_setup_fluidsynth_path()

import fluidsynth

_DPI_AWARENESS_SET = False


def _ensure_windows_dpi_awareness():
    """Set process DPI awareness on Windows so window/screen sizes are accurate."""
    global _DPI_AWARENESS_SET
    if _DPI_AWARENESS_SET or not sys.platform.startswith("win"):
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    _DPI_AWARENESS_SET = True


def get_primary_screen_size(default=(1280, 720)):
    """Return primary screen size as (width, height)."""
    if sys.platform.startswith("win"):
        try:
            _ensure_windows_dpi_awareness()
            user32 = ctypes.windll.user32
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            if width > 0 and height > 0:
                return width, height
        except Exception:
            pass

    try:
        if not pygame.display.get_init():
            pygame.display.init()
        info = pygame.display.Info()
        width = int(getattr(info, "current_w", 0))
        height = int(getattr(info, "current_h", 0))
        if width > 0 and height > 0:
            return width, height
    except Exception:
        pass

    return default


def fit_resolution_to_screen(width, height, min_width=640, min_height=360):
    """
    Fit requested resolution to current screen while preserving aspect ratio.
    Returns: (fit_w, fit_h, adjusted, screen_w, screen_h)
    """
    req_w = max(1, int(width))
    req_h = max(1, int(height))
    screen_w, screen_h = get_primary_screen_size()

    if req_w <= screen_w and req_h <= screen_h:
        return req_w, req_h, False, screen_w, screen_h

    scale = min(screen_w / req_w, screen_h / req_h)
    fit_w = max(min_width, int(req_w * scale))
    fit_h = max(min_height, int(req_h * scale))

    fit_w = min(fit_w, screen_w)
    fit_h = min(fit_h, screen_h)

    if fit_w % 2 != 0 and fit_w > 1:
        fit_w -= 1
    if fit_h % 2 != 0 and fit_h > 1:
        fit_h -= 1

    return fit_w, fit_h, True, screen_w, screen_h


# ========================
# AUDIO INITIALIZATION
# ========================

def init_fluidsynth(driver="dsound"):
    """
    Initialize FluidSynth synthesizer with specified driver.
    Returns: (fs_instance, loaded_sfids_dict) or (None, {}) on failure
    """
    try:
        # Ensure FluidSynth path is configured (safety check)
        _setup_fluidsynth_path()
        
        fs = fluidsynth.Synth()
        fs.start(driver=driver)
        return fs, {}
    except Exception as e:
        print(f"ERRO CRÍTICO DE AUDIO: {e}")
        # Try to provide helpful debugging info
        if "Could not find" in str(e) or "fluidsynth" in str(e).lower():
            print("  [!] FluidSynth library not found. Checking environment...")
            print(f"      PATH: {os.environ.get('PATH', 'NOT SET')[:100]}...")
            print(f"      FLUIDSYNTH_PATH: {os.environ.get('FLUIDSYNTH_PATH', 'NOT SET')}")
        return None, {}


def load_single_soundfont(fs, nickname, path):
    """
    Load a single soundfont file into FluidSynth.
    Returns: soundfont_id (or -1 if failed)
    """
    if not os.path.exists(path):
        print(f"AVISO: Arquivo SF2 não encontrado: {path}")
        return -1
    
    try:
        sfid = fs.sfload(path)
        if sfid != -1:
            print(f"Carregado: {nickname} (ID: {sfid})")
        else:
            print(f"ERRO: Falha ao carregar {path}")
        return sfid
    except Exception as e:
        print(f"ERRO ao carregar {nickname}: {e}")
        return -1


def load_all_soundfonts(fs):
    """
    Load all soundfonts from settings.SF2_PATHS into FluidSynth.
    Returns: dict mapping nickname to soundfont_id
    """
    loaded_sfids = {}
    if not fs:
        return loaded_sfids
    
    print(">>> Carregando bancos de som...")
    for nickname, path in settings.SF2_PATHS.items():
        sfid = load_single_soundfont(fs, nickname, path)
        if sfid != -1:
            loaded_sfids[nickname] = sfid
    
    return loaded_sfids


def select_instrument(fs, instrument_name, loaded_sfids, recorder, channel=0, is_drum=False):
    """
    Select an instrument by name and configure FluidSynth + recorder.
    Handles bank/preset lookup from settings.INSTRUMENTS.
    
    Returns: True if successful, False otherwise
    """
    if not fs or instrument_name not in settings.INSTRUMENTS:
        if instrument_name not in settings.INSTRUMENTS:
            print(f"Instrumento '{instrument_name}' não encontrado.")
        return False
    
    sf_key, bank, preset = settings.INSTRUMENTS[instrument_name]
    target_sfid = loaded_sfids.get(sf_key)
    
    if target_sfid is None:
        print(f"ERRO: SoundFont '{sf_key}' não carregado.")
        return False
    
    try:
        fs.program_select(channel, target_sfid, bank, preset)
        print(f">>> SOM: {instrument_name} (B:{bank} P:{preset})")
        
        sf_path = settings.SF2_PATHS.get(sf_key)
        if sf_path:
            recorder.set_instrument(sf_path, bank, preset, is_drum=is_drum, instrument_name=instrument_name)
        
        return True
    except Exception as e:
        print(f"ERRO ao selecionar instrumento: {e}")
        return False


# ========================
# VIDEO CAPTURE SETUP
# ========================

def setup_video_capture(width=1280, height=720, fps=60):
    """
    Initialize and configure video capture from webcam.
    
    Returns: cv2.VideoCapture object
    """
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    return cap


class CameraThread:
    """Thread de captura contínua — sempre disponibiliza o frame mais recente."""
    def __init__(self, cap):
        self._cap = cap
        self._lock = threading.Lock()
        self._frame = None
        self._grab_ts = 0.0
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                continue
            ts = time.perf_counter()
            with self._lock:
                self._frame = frame
                self._grab_ts = ts

    def get_latest(self):
        """Retorna (frame, grab_timestamp) ou (None, 0)."""
        with self._lock:
            if self._frame is None:
                return None, 0.0
            return self._frame.copy(), self._grab_ts

    def stop(self):
        self._running = False
        self._thread.join(timeout=2.0)


def prepare_mediapipe_frame(frame_rgb, logical_w, logical_h, mp_input_height=480):
    """Reduz resolução do frame RGB para inferência MediaPipe (landmarks normalizados).

    Retorna o frame reduzido ou o original se já for menor ou igual a mp_input_height.
    """
    if logical_h <= mp_input_height:
        return frame_rgb
    mp_w = int(logical_w * mp_input_height / logical_h)
    return cv2.resize(frame_rgb, (mp_w, mp_input_height))


class _EmptyHandsResult:
    """Sentinel retornado antes do primeiro resultado real de MediaPipeHandsThread."""
    multi_hand_landmarks = None
    multi_handedness = None
    multi_hand_world_landmarks = None


class _EmptyPoseResult:
    """Sentinel retornado antes do primeiro resultado real de MediaPipePoseThread."""
    pose_landmarks = None
    pose_world_landmarks = None
    segmentation_mask = None


class MediaPipeHandsThread:
    """Executa inferência MediaPipe Hands em thread de fundo (modo stream).

    O frame mais recente é sempre processado; frames antigos ainda não
    consumidos são descartados automaticamente para minimizar latência.

    Uso:
        mp_hands_thread = MediaPipeHandsThread(hands_model)
        # dentro do loop principal:
        mp_hands_thread.submit_frame(frame_mp)
        results = mp_hands_thread.get_latest_result()
        # ao encerrar:
        mp_hands_thread.close()  # para a thread E chama hands_model.close()
    """

    _EMPTY = _EmptyHandsResult()

    def __init__(self, hands_model):
        self._hands = hands_model
        self._frame_lock = threading.Lock()
        self._pending_frame = None
        self._frame_event = threading.Event()
        self._result_lock = threading.Lock()
        self._result = self._EMPTY
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            self._frame_event.wait(timeout=0.05)
            self._frame_event.clear()
            with self._frame_lock:
                frame = self._pending_frame
                self._pending_frame = None
            if frame is None:
                continue
            result = self._hands.process(frame)
            with self._result_lock:
                self._result = result

    def submit_frame(self, frame):
        """Armazena o frame mais recente; descarta o frame pendente anterior."""
        with self._frame_lock:
            self._pending_frame = frame
        self._frame_event.set()

    def get_latest_result(self):
        """Retorna o resultado mais recente disponível (nunca None)."""
        with self._result_lock:
            return self._result

    def stop(self):
        self._running = False
        self._frame_event.set()
        self._thread.join(timeout=2.0)

    def close(self):
        self.stop()
        self._hands.close()


class MediaPipePoseThread:
    """Executa inferência MediaPipe Pose em thread de fundo (modo stream).

    Mesma semântica de MediaPipeHandsThread.
    """

    _EMPTY = _EmptyPoseResult()

    def __init__(self, pose_model):
        self._pose = pose_model
        self._frame_lock = threading.Lock()
        self._pending_frame = None
        self._frame_event = threading.Event()
        self._result_lock = threading.Lock()
        self._result = self._EMPTY
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            self._frame_event.wait(timeout=0.05)
            self._frame_event.clear()
            with self._frame_lock:
                frame = self._pending_frame
                self._pending_frame = None
            if frame is None:
                continue
            result = self._pose.process(frame)
            with self._result_lock:
                self._result = result

    def submit_frame(self, frame):
        with self._frame_lock:
            self._pending_frame = frame
        self._frame_event.set()

    def get_latest_result(self):
        with self._result_lock:
            return self._result

    def stop(self):
        self._running = False
        self._frame_event.set()
        self._thread.join(timeout=2.0)

    def close(self):
        self.stop()
        self._pose.close()


# ========================
# PYGAME INITIALIZATION
# ========================

def _focus_window():
    """Traz a janela pygame para o foco no Windows."""
    try:
        import ctypes
        hwnd = pygame.display.get_wm_info().get("window")
        if hwnd:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.BringWindowToTop(hwnd)
    except Exception:
        pass


def setup_pygame(window_width=1280, window_height=720, title="Talking Hands", borderless=True):
    """
    Initialize pygame, create display window, and setup font.
    
    Args:
        borderless (bool): If True, creates a borderless window (no title bar, minimize, close buttons)
    
    Returns: (screen_surface, font_object)
    """
    pygame.init()
    flags = pygame.NOFRAME if borderless else 0
    screen = pygame.display.set_mode((window_width, window_height), flags)
    pygame.display.set_caption(title)
    font = pygame.font.SysFont("Arial", 18, bold=True)
    _focus_window()
    return screen, font


def setup_pygame_with_scaling(logical_width=1280, logical_height=720, 
                               display_width=1280, display_height=720, title="Talking Hands", borderless=True):
    """
    Setup pygame with logical and display surfaces (allows upscaling/downscaling).
    Useful for rendering at logical resolution then scaling to display resolution.
    
    Returns: (display_screen, logical_surface, font_object)
    """
    pygame.init()
    flags = pygame.NOFRAME if borderless else 0
    display_screen = pygame.display.set_mode((display_width, display_height), flags)
    pygame.display.set_caption(title)
    
    logical_surface = pygame.Surface((logical_width, logical_height))
    font = pygame.font.SysFont("Arial", 18, bold=True)
    _focus_window()
    return display_screen, logical_surface, font


# ========================
# PYGAME DRAWING UTILITIES
# ========================

def draw_text(surface, text, pos, font, color=(255, 255, 255)):
    """
    Render text and blit onto pygame surface.
    
    Args:
        surface: pygame Surface to draw on
        text: string to render
        pos: (x, y) tuple for position
        font: pygame font object
        color: (R, G, B) tuple
    """
    txt_surf = font.render(text, True, color)
    surface.blit(txt_surf, pos)


def draw_recording_indicator(screen, width, height, font):
    """
    Draw a red recording indicator (circle + "REC" text) in top-right corner.
    Typical usage: if recorder.is_recording: draw_recording_indicator(...)
    """
    indicator_y = 68
    pygame.draw.circle(screen, (255, 0, 0), (width - 120, indicator_y), 10)
    draw_text(screen, "REC", (width - 105, indicator_y - 10), font, (255, 0, 0))


def draw_playback_indicator(screen, width, font):
    """
    Draw a playback indicator ("PLAYBACK" text) in top-right area.
    Typical usage: if recorder.is_playing: draw_playback_indicator(...)
    """
    draw_text(screen, "PLAYBACK", (width - 220, 92), font, (255, 0, 0))


def draw_menu_instructions(screen, width, height, font, instructions_list):
    """
    Draw a list of instruction strings on screen at standard position.
    
    Args:
        screen: pygame Surface
        width, height: screen dimensions
        font: pygame font object
        instructions_list: list of strings, e.g., ["ESC -> exit", "1 -> start"]
    """
    y0 = 30
    for i, txt in enumerate(instructions_list):
        draw_text(screen, txt, (20, y0 + i * 25), font)


# ========================
# FRAME PROCESSING
# ========================

def process_frame_to_pygame(frame, width, height, flip=True, flip_axis=1):
    """
    Convert OpenCV frame to pygame surface.
    
    Args:
        frame: BGR frame from cv2.VideoCapture
        width, height: target dimensions
        flip: whether to flip frame (mirror)
        flip_axis: 0=vertical, 1=horizontal (default mirrors left-right)
    
    Returns: pygame Surface
    """
    frame = cv2.resize(frame, (width, height))
    if flip:
        frame = cv2.flip(frame, flip_axis)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame_surface = pygame.image.frombuffer(frame_rgb.tobytes(), (width, height), 'RGB')
    return frame_surface


# ========================
# RECORDER UTILITIES
# ========================

def create_recording_filename(instrument_name, prefix="", timestamp=None):
    """
    Generate standardized recording filename.
    
    Args:
        instrument_name: name of instrument
        prefix: optional prefix (e.g., "drums", "flute")
        timestamp: optional Unix timestamp; if None, uses current time
    
    Returns: formatted filename string
    """
    import time as time_module
    
    ts = timestamp if timestamp else int(time_module.time())
    clean_name = instrument_name.replace(' ', '_') if instrument_name else "Unknown"
    
    if prefix:
        return f"{prefix}_{clean_name}_{ts}.mid"
    else:
        return f"{clean_name}_{ts}.mid"
