SF2_PATHS = {
    "master": r"sounds\universal\module_master.sf2",
    "nines":  r"sounds\synths\module90.sf2",
    "retro":  r"sounds\keyboard\Retro_Synth_PC.sf2",
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
    
    "Vibes":   ("nines", 0, 39), 
    "Phantasy": ("nines", 0, 48),
    "SuperPipes":  ("nines", 0, 89),

    "Harp": ("retro", 0, 46),
    "SynthDrum": ("retro", 0, 118),
    "SciFi":  ("retro", 0, 103),
    "Goblins":  ("retro", 0, 101),
    "TronViolin":  ("retro", 0, 40)
}

SUSTAIN_DECAY = 0.8
