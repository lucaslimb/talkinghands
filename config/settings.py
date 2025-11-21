SF2_PATHS = {
    "master": r"sounds\universal\module_master.sf2",
    "drums":  r"sounds\drums\Drums.sf2"
}

INSTRUMENTS = {
    # Sound name - file path, banco, preset
    "Piano 1":     ("master", 0, 0),
    "Piano 2":     ("master", 0, 1),
    "Accordion":     ("master", 0, 7),
    "Square":     ("master", 0, 106),
    "Crystal":    ("master", 1, 41),
    "Atmosphere":    ("master", 1, 49),
    "EP1":        ("master", 0, 4),
    "Warm Pad":    ("master", 1, 6),
    "Rain":    ("master", 1, 29),
    "Lite Organ":    ("master", 0, 12),
    "Oohs":      ("master", 0, 87),
    "Flute Bell":      ("master", 0, 97),

    "Drum 1":  ("drums", 128, 0),
    "Drum 2":  ("drums", 128, 1),
    "Drum 3":  ("drums", 128, 2),
    "Drum 4":  ("drums", 128, 3),
    "Drum 5":  ("drums", 128, 4),
    "Drum 6":  ("drums", 128, 5),
    "Drum 7":  ("drums", 128, 6),
    "Drum 8":  ("drums", 128, 7),
    "Drum 9":  ("drums", 128, 8),
    "Drum 10":  ("drums", 128, 9),
    "Drum 11":  ("drums", 128, 10),
    "Drum 12":  ("drums", 128, 11),
}

SUSTAIN_DECAY = 0.8
LIFT_THRESHOLD = 0.02
TOUCH_TOLERANCE = 0.005
