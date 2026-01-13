import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = BASE_DIR / "assets"
SOUNDFONTS_DIR = ASSETS_DIR / "soundfonts"
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

# Keyboard
SUSTAIN_DECAY = 0.8
LIFT_THRESHOLD = 0.02

# Drums
TOUCH_TOLERANCE = 0.005
TOUCH_VELOCITY = 0.012

# Flute
MOUTH_PEAK_OPEN = 0.01
MOUTH_MAX_OPEN = 0.05
HOLE_RADIUS = 0.019
HOLE_SPACING = 0.068

# Gravação
RECORD_SAVE_MID = True              
RECORD_SAVE_MP3 = False             
RECORD_SAVE_WAV = False             
RECORD_SEPARATE_PLAYBACK_FOLDER = False