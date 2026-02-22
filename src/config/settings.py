import os
import sys
from pathlib import Path

# Handle development, PyInstaller Windows bundle, and Linux installations
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running as PyInstaller bundle (Windows exe)
    BASE_DIR = Path(sys._MEIPASS)
elif 'TALKING_HANDS_HOME' in os.environ:
    # Running from Linux installation (set by launcher or venv)
    BASE_DIR = Path(os.environ['TALKING_HANDS_HOME'])
else:
    # Running as normal Python script (development)
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

ASSETS_DIR = BASE_DIR / "assets"
SOUNDFONTS_DIR = ASSETS_DIR / "soundfonts"

# Recordings directory: use ~/Documents on Linux, project folder on Windows
if sys.platform.startswith('linux'):
    RECORDINGS_DIR = Path.home() / "Documents" / "TalkingHands Recordings"
else:
    RECORDINGS_DIR = BASE_DIR / "recordings"

os.makedirs(RECORDINGS_DIR, exist_ok=True)

SF2_PATHS = {
    "master": str(SOUNDFONTS_DIR / "keyboard" / "module_master.sf2"),
    "drums":  str(SOUNDFONTS_DIR / "drums" / "Drums.sf2"),
    "flute":  str(SOUNDFONTS_DIR / "flute" / "Chris_Flutes_and_Harmonicas.sf2"),
}

RECORDINGS_FOLDER = str(RECORDINGS_DIR)

INSTRUMENTS = {
    # Sound name: (file key, bank, preset)
    "Piano":          ("master", 0, 0),
    "Piano 2":        ("master", 0, 1),
    "Drawbar":        ("master", 0, 8),
    "Accordion":      ("master", 0, 7),
    "Glass Trem":     ("master", 0, 23),
    "Santur":         ("master", 0, 32),
    "Guitar Chimes":  ("master", 0, 37),
    "Synth Bass":     ("master", 0, 54),
    "Blow Wave":      ("master", 0, 101),
    "Square":         ("master", 0, 106),
    "Crystal":        ("master", 1, 41),
    "Metallic Pad":   ("master", 1, 23),
    "Atmosphere":     ("master", 1, 49),
    "EP1":            ("master", 0, 4),
    "Goblin":         ("master", 1, 61),
    "Warm Pad":       ("master", 1, 6),
    "Rain":           ("master", 1, 29),
    "Lite Organ":     ("master", 0, 12),
    "Oohs":           ("master", 0, 87),
    "Flute Bell":     ("master", 0, 97),
    "Koto LA":        ("master", 1, 89),

    "Drum":      ("drums", 128, 0),
    "Drum 2":    ("drums", 128, 1),
    "Drum 3":    ("drums", 128, 2),
    "Drum 4":    ("drums", 128, 3),
    "Drum 5":    ("drums", 128, 4),
    "Drum 6":    ("drums", 128, 5),
    "Drum 7":    ("drums", 128, 6),
    "Drum 8":    ("drums", 128, 7),
    "Drum 9":    ("drums", 128, 8),
    "Drum 10":   ("drums", 128, 9),
    "Drum 11":   ("drums", 128, 10),
    "Drum 12":   ("drums", 128, 11),

    "Harmonica":            ("flute", 0, 0),
    "Recorder":             ("flute", 0, 4),
    "Plastic Flute Short":  ("flute", 0, 11),
    "Plastic Flute Low":    ("flute", 0, 12),
    "Plastic Flute High":   ("flute", 0, 14),
    "Plastic Flute Mid":    ("flute", 0, 13),
    "Tin Whistle":          ("flute", 0, 16),
}

# Keyboard defaults
KEYBOARD_SUSTAIN_DECAY = 0.8
KEYBOARD_LIFT_THRESHOLD = 0.02
KEYBOARD_TOUCH_TOLERANCE = 0.005
KEYBOARD_RELEASE_THRESHOLD = 0.015
KEYBOARD_MIN_NOTE_DURATION = 0.1
KEYBOARD_ARMED_TIMEOUT = 2.5
KEYBOARD_MAX_MISSING_TIME = 0.1
KEYBOARD_DEFAULT_NUM_KEYS = 30
KEYBOARD_MIN_NUM_KEYS = 12
KEYBOARD_DEFAULT_TABLE_Y = 0.80
KEYBOARD_MIN_TABLE_Y = 0.45
KEYBOARD_MAX_TABLE_Y = 0.93

# Drums defaults
DRUMS_TOUCH_TOLERANCE = 0.01
DRUMS_TOUCH_VELOCITY = 0.012
DRUMS_VELOCITY_THRESHOLD = 0.002
DRUMS_MIN_VELOCITY = 50
DRUMS_MIN_REHIT_PIXELS = 32
DRUMS_FOOT_REHIT_PIXELS = 36
DRUMS_SYNTH_GAIN = 1.8

# Flute defaults
FLUTE_DEFAULT_X = 0.6
FLUTE_DEFAULT_Y = 0.25
FLUTE_MOUTH_MIN_OPEN = 0.002
FLUTE_MOUTH_PEAK_OPEN = 0.01
FLUTE_MOUTH_MAX_OPEN = 0.05
FLUTE_HOLE_RADIUS = 0.019
FLUTE_HOLE_SPACING = 0.068
FLUTE_MOUTH_SMOOTHING_FACTOR = 0.3
FLUTE_VELOCITY_CHANGE_THRESHOLD = 4
FLUTE_MOUTH_FOLLOW_SENSITIVITY = 0.22
FLUTE_MOUTH_FOLLOW_OFFSET_Y = 0.09
FLUTE_MOUTH_ANGLE_SENSITIVITY = 1.0
FLUTE_MOUTH_CLOSE_STOP_THRESHOLD = 0.0006
FLUTE_MOUTH_PEAK_NEAR_CLOSE_FACTOR = 0.25

# Legacy aliases (compatibility)
SUSTAIN_DECAY = KEYBOARD_SUSTAIN_DECAY
LIFT_THRESHOLD = KEYBOARD_LIFT_THRESHOLD
TOUCH_TOLERANCE = KEYBOARD_TOUCH_TOLERANCE
TOUCH_VELOCITY = DRUMS_TOUCH_VELOCITY
MOUTH_PEAK_OPEN = FLUTE_MOUTH_PEAK_OPEN
MOUTH_MAX_OPEN = FLUTE_MOUTH_MAX_OPEN
HOLE_RADIUS = FLUTE_HOLE_RADIUS
HOLE_SPACING = FLUTE_HOLE_SPACING

# Gravação
RECORD_SAVE_MID = True              
RECORD_SAVE_MP3 = False             
RECORD_SAVE_WAV = False             
RECORD_SEPARATE_PLAYBACK_FOLDER = False