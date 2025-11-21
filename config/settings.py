SF2_PATHS = {
    "master": r"sounds\universal\module_master.sf2",
    "drums":  r"sounds\drums\Drums.sf2"
}

INSTRUMENTS = {
    # Sound name - file path, banco, preset
    "Square":     ("master", 0, 106),
    "Crystal":    ("master", 1, 41),
    "Atmosphere":    ("master", 1, 49),
    "EP1":        ("master", 0, 4),
    "WarmPad":    ("master", 1, 6),
    "Rain":    ("master", 1, 29),
    "LiteOrgan":    ("master", 0, 12),
    "Oohs2":      ("master", 0, 87),
    "FluteBell":      ("master", 0, 97),

    "Perfect Drums 1":  ("drums", 128, 0),
    "Perfect Drums 2":  ("drums", 128, 1),
    "Perfect Drums 3":  ("drums", 128, 2),
}

SUSTAIN_DECAY = 0.8
LIFT_THRESHOLD = 0.02
TOUCH_TOLERANCE = 0.005
