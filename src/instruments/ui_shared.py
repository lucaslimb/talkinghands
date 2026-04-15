"""
Talking Hands — Shared UI definitions for PySide6 instrument windows.
Centralizes design tokens, QSS, font loading, and reusable panel widgets
so that keyboard_ui.py and drums_ui.py stay consistent.
"""

import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "PlayfairDisplay-VariableFont_wght.ttf"

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

# Colors
COL_BG_DARK        = "#EEECEA"
COL_BG_PANEL       = "#EEECEA"
COL_BG_PANEL_ALT   = "#E5E2DD"
COL_ACCENT_GREEN   = "#7ECBA1"
COL_ACCENT_RED     = "#CF796B"
COL_TEXT_PRIMARY    = "#2C2C2C"
COL_TEXT_SECONDARY  = "#8A8A8A"
COL_TEXT_LIGHT      = "#ffffff"
COL_BTN_RECORD     = "#1E1E1B"
COL_BTN_PAUSE      = "#EEECEA"
COL_BORDER_LIGHT   = "#D5D2CD"
COL_OCTAVE_ACTIVE  = "#1E1E1B"
COL_OCTAVE_INACTIVE= "#EEECEA"
COL_SLIDER_TRACK   = "#D5D2CD"
COL_SLIDER_HANDLE  = "#2C2C2C"
COL_DETECTING_BG   = "#2a3a2a"
COL_DETECTING_DOT  = "#7ECBA1"
COL_NOTE_PILL_BG   = "#7ECBA1"
COL_KEY_ACTIVE     = "#7ECBA1"
COL_KEY_WHITE      = "#f5f5f5"
COL_KEY_BLACK      = "#1a1a1a"

# Font (loaded at runtime)
FONT_FAMILY = "Playfair Display"

def load_custom_font():
    global FONT_FAMILY
    if _FONT_PATH.exists():
        fid = QFontDatabase.addApplicationFont(str(_FONT_PATH))
        if fid >= 0:
            families = QFontDatabase.applicationFontFamilies(fid)
            if families:
                FONT_FAMILY = families[0]

FONT_SIZE_SM    = 12
FONT_SIZE_MD    = 14
FONT_SIZE_LG    = 18
FONT_SIZE_XL    = 24
FONT_SIZE_TIMER = 48

# Layout
PANEL_MIN_W = 380
PANEL_MAX_W = 520
BTN_HEIGHT  = 48
BORDER_RAD  = 8


# ---------------------------------------------------------------------------
# Global QSS builder — shared across instrument UIs
# ---------------------------------------------------------------------------

def build_global_qss():
    """Return the shared QSS string using current FONT_FAMILY."""
    return f"""
QMainWindow {{
    background-color: {COL_BG_DARK};
}}
#controlPanel {{
    background-color: {COL_BG_PANEL};
    border-left: 1px solid {COL_BORDER_LIGHT};
}}
#controlPanel QLabel {{
    color: {COL_TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
}}
#controlPanel QLabel#timerLabel {{
    font-size: {FONT_SIZE_TIMER}px;
    font-weight: bold;
    color: {COL_TEXT_PRIMARY};
}}
#controlPanel QLabel#timerSub {{
    font-size: {FONT_SIZE_SM}px;
    color: {COL_TEXT_SECONDARY};
}}
#controlPanel QLabel#sectionTitle {{
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    color: {COL_TEXT_SECONDARY};
    letter-spacing: 1px;
}}
#controlPanel QLabel#headerLabel {{
    font-size: {FONT_SIZE_LG}px;
    font-weight: bold;
    color: {COL_TEXT_PRIMARY};
}}
QPushButton#presetBtn {{
    background-color: {COL_BG_PANEL_ALT};
    color: {COL_TEXT_PRIMARY};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 8px 16px;
    font-size: {FONT_SIZE_MD}px;
    font-family: {FONT_FAMILY};
    white-space: nowrap;
}}
QPushButton#presetBtn:checked {{
    background-color: {COL_OCTAVE_ACTIVE};
    color: {COL_TEXT_LIGHT};
    border: none;
}}
QPushButton#presetBtn:hover {{
    background-color: {COL_BORDER_LIGHT};
}}
QPushButton#trackerBtn {{
    background-color: {COL_BG_PANEL_ALT};
    color: {COL_TEXT_PRIMARY};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 8px 16px;
    font-size: {FONT_SIZE_MD}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#trackerBtn:checked {{
    background-color: {COL_OCTAVE_ACTIVE};
    color: {COL_TEXT_LIGHT};
    border: none;
}}
QPushButton#recordBtn {{
    background-color: {COL_BTN_RECORD};
    color: {COL_TEXT_LIGHT};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 12px;
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    font-family: {FONT_FAMILY};
}}
QPushButton#recordBtn:hover {{
    background-color: #333333;
}}
QPushButton#stopBtn {{
    background-color: {COL_BTN_PAUSE};
    color: {COL_TEXT_PRIMARY};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 12px;
    font-size: {FONT_SIZE_MD}px;
    font-weight: bold;
    font-family: {FONT_FAMILY};
}}
QPushButton#stopBtn:hover {{
    background-color: #d8d4ce;
}}
QPushButton#endBtn {{
    background-color: transparent;
    color: {COL_ACCENT_RED};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 6px 16px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#endBtn:hover {{
    background-color: {COL_ACCENT_RED};
    color: white;
}}
QScrollArea#presetScroll {{
    background-color: transparent;
    border: none;
}}
QWidget#presetContainer {{
    background: {COL_BG_PANEL};
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {COL_SLIDER_TRACK};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COL_SLIDER_HANDLE};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: {COL_ACCENT_GREEN};
    border-radius: 3px;
}}
QPushButton#octaveBtn {{
    background-color: {COL_BG_PANEL_ALT};
    color: {COL_TEXT_PRIMARY};
    border: none;
    border-radius: {BORDER_RAD}px;
    padding: 8px 16px;
    font-size: {FONT_SIZE_MD}px;
    font-family: {FONT_FAMILY};
}}
QPushButton#octaveBtn:checked {{
    background-color: {COL_OCTAVE_ACTIVE};
    color: {COL_TEXT_LIGHT};
    border: none;
}}
QLabel#notePill {{
    background-color: {COL_NOTE_PILL_BG};
    color: white;
    border-radius: 12px;
    padding: 4px 12px;
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    font-family: {FONT_FAMILY};
}}
QLabel#notePillInactive {{
    background-color: {COL_BG_PANEL_ALT};
    color: {COL_TEXT_PRIMARY};
    border-radius: 12px;
    padding: 4px 12px;
    font-size: {FONT_SIZE_SM}px;
    font-family: {FONT_FAMILY};
}}
QLabel#detectingLabel {{
    background-color: {COL_DETECTING_BG};
    color: {COL_ACCENT_GREEN};
    border-radius: 12px;
    padding: 4px 12px;
    font-size: {FONT_SIZE_SM}px;
    font-weight: bold;
    font-family: {FONT_FAMILY};
}}
"""
