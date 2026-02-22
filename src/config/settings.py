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
    RECORDINGS_ROOT = Path.home() / "Documents" / "TalkingHands Recordings"
else:
    RECORDINGS_ROOT = BASE_DIR / "recordings"

MIDS_DIR = RECORDINGS_ROOT / "mids"
WAV_DIR = RECORDINGS_ROOT / "wav"
RECORDINGS_DIR = RECORDINGS_ROOT  # compat

os.makedirs(MIDS_DIR, exist_ok=True)
os.makedirs(WAV_DIR, exist_ok=True)

SF2_PATHS = {
    "master": str(SOUNDFONTS_DIR / "keyboard" / "module_master.sf2"),
    "drums":  str(SOUNDFONTS_DIR / "drums" / "NewDrums.sf2"),
    "flute_general": str(SOUNDFONTS_DIR / "flute" / "FlutesGeneral.sf2"),
    "flute_alt":     str(SOUNDFONTS_DIR / "flute" / "Flutes.sf2"),
}

RECORDINGS_FOLDER = str(RECORDINGS_ROOT)

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
    "Honky-Tonk":     ("master", 0, 2),
    "Soft EP":        ("master", 0, 3),
    "EP2":            ("master", 0, 5),
    "Synth Piano":    ("master", 0, 6),
    "Rotary Organ":   ("master", 0, 11),
    "Celesta":        ("master", 0, 14),
    "Vibraphone":     ("master", 0, 17),
    "Glass Hit":      ("master", 0, 21),
    "Breath Bells":   ("master", 0, 24),
    "Acoustic Guitar 1": ("master", 0, 33),
    "Oud":            ("master", 0, 42),
    "Acoustic Bass":  ("master", 0, 44),
    "Fretless 1":     ("master", 0, 47),
    "Fantasy LA":     ("master", 1, 0),
    "Eventide":       ("master", 1, 1),
    "Polysynth":      ("master", 1, 8),
    "Space Voices":   ("master", 1, 10),
    "Warm Voices":    ("master", 1, 11),
    "Ocean Pad":      ("master", 1, 18),
    "Digital Pad":    ("master", 1, 20),
    "Synth Glass":    ("master", 1, 22),
    "Silver Pad":     ("master", 1, 25),
    "Petrichor":      ("master", 1, 35),
    "Blue Planet":    ("master", 1, 39),
    "Ambient Bell":   ("master", 1, 51),
    "Bamboo Forest":  ("master", 1, 52),

    "Classic":     ("drums", 128, 0),
    "Power":       ("drums", 128, 16),
    "Vintage":     ("drums", 128, 0),
    "Bright":      ("drums", 128, 0),
    "Power Tight": ("drums", 128, 16),
    "Power Wide":  ("drums", 128, 16),
    "Latin": ("drums", 128, 0),

    "Harmonica":    ("flute_general", 0, 0),
    "Recorder":     ("flute_general", 0, 5),
    "PlasticFlute": ("flute_general", 0, 10),
    "TinWhistle":   ("flute_general", 0, 15),
    "RecorderAltSopr": ("flute_alt", 0, 4),
    "RecorderTenor":   ("flute_alt", 0, 5),
    "BassRecorder":    ("flute_alt", 0, 6),
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
DRUMS_MIN_HIT_INTERVAL_SEC = 0.045
DRUMS_CUSTOM_RECT_THICKNESS = 1.20
DRUMS_SYNTH_GAIN = 1.8
DRUMS_NOTE_OVERRIDES = {
    "kick": 36,
    "snare": 38,
    "floor": 41,
    "hihat": 42,
    "tom_hi": 48,
    "tom_low": 45,
    "crash": 49,
    "ride": 51,
}
DRUMS_INSTRUMENT_NOTE_VARIATIONS = {
    "Vintage": {
        "kick": 35,
        "snare": 40,
        "floor": 43,
        "hihat": 42,
        "tom_hi": 48,
        "tom_low": 45,
        "crash": 49,
        "ride": 51,
    },
    "Bright": {
        "kick": 35,
        "snare": 40,
        "floor": 43,
        "hihat": 46,
        "tom_hi": 50,
        "tom_low": 45,
        "crash": 57,
        "ride": 59,
    },
    "Power Tight": {
        "kick": 35,
        "snare": 40,
        "floor": 41,
        "hihat": 42,
        "tom_hi": 50,
        "tom_low": 45,
        "crash": 49,
        "ride": 51,
    },
    "Power Wide": {
        "kick": 35,
        "snare": 38,
        "floor": 43,
        "hihat": 46,
        "tom_hi": 48,
        "tom_low": 45,
        "crash": 57,
        "ride": 59,
    },
}
DRUMS_INSTRUMENT_ELEMENT_PRESETS = {
    "Latin": ["bongo_hi", "bongo_mid", "bongo_lo", "bongo_deep", "conga_mid", "maracas", "cabasa"],
}
DRUMS_INSTRUMENT_REPLACE_BASE = ["Latin"]
DRUMS_PREDEFINED_ELEMENTS = [
    "crash", "ride", "splash", "china",
    "tom_hi", "tom_mid", "tom_low",
    "hihat", "open_hh", "snare", "snare_alt", "rimshot", "floor", "kick", "kick_alt",
    "hh_pedal", "cowbell", "clap", "tamb", "ride_bell", "crash2", "ride2", "vibra_slap", "shaker",
    "cabasa", "maracas", "guiro_s", "guiro_l",
    "agogo_hi", "agogo_lo", "clave", "wood_hi", "wood_lo", "tri_mute", "tri_open",
    "bongo_hi", "bongo_mid", "bongo_lo", "bongo_deep", "conga_hi", "conga_mid", "conga_lo", "timbale_hi", "timbale_lo",
]
DRUMS_DEFAULT_ELEMENTS = ["crash", "ride", "tom_hi", "tom_low", "hihat", "snare", "floor", "kick"]
DRUMS_COMPLETE_EXTRA_ELEMENTS = ["hh_pedal"]

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

# Gravação (sempre ativa para MID e WAV)
RECORD_SAVE_MID = True
RECORD_SAVE_WAV = True