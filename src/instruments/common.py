# Common utilities shared across all instrument modules (drums, flute, keyboard)
# This module provides generalized functions to reduce code duplication

import cv2
import pygame
import fluidsynth
import sys
import os
from pathlib import Path

from src.config import settings
from src.engines.recorder import MidiRecorder


# ========================
# AUDIO INITIALIZATION
# ========================

def init_fluidsynth(driver="dsound"):
    """
    Initialize FluidSynth synthesizer with specified driver.
    Returns: (fs_instance, loaded_sfids_dict) or (None, {}) on failure
    """
    try:
        fs = fluidsynth.Synth()
        fs.start(driver=driver)
        return fs, {}
    except Exception as e:
        print(f"ERRO CRÍTICO DE AUDIO: {e}")
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
            recorder.set_instrument(sf_path, bank, preset, is_drum=is_drum)
        
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
    
    return cap


# ========================
# PYGAME INITIALIZATION
# ========================

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
    pygame.draw.circle(screen, (255, 0, 0), (width - 90, 30), 10)
    draw_text(screen, "REC", (width - 75, 20), font, (255, 0, 0))


def draw_playback_indicator(screen, width, font):
    """
    Draw a playback indicator ("PLAYBACK" text) in top-right area.
    Typical usage: if recorder.is_playing: draw_playback_indicator(...)
    """
    draw_text(screen, "PLAYBACK", (width - 200, 30), font, (255, 0, 0))


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
