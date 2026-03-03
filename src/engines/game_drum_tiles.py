"""
Drum Tiles game engine (pure state machine, no pygame/cv2).

Coloured tiles fly from the screen edges toward their target drum pads.
The player must hit the correct drum as the tile arrives at the pad centre.

States: IDLE → PLAYING → GAME_OVER
"""

import time
import random
from dataclasses import dataclass
from typing import Optional


# ── Built-in songs  (element_key, duration_beats) ────────────────────────
# Uses elements from the default kit:
#   kick, snare, hihat, crash, ride, tom_hi, tom_low, floor
_SONGS: dict[str, list[tuple[str, float]]] = {
    "Basic Beat": [
        ("kick", 1), ("hihat", 1), ("snare", 1), ("hihat", 1),
        ("kick", 1), ("hihat", 1), ("snare", 1), ("hihat", 1),
        ("kick", 1), ("hihat", 1), ("snare", 1), ("hihat", 1),
        ("kick", 1), ("kick",  1), ("snare", 1), ("hihat", 1),
        ("kick", 1), ("hihat", 1), ("snare", 1), ("hihat", 1),
        ("kick", 1), ("kick",  1), ("snare", 1), ("crash", 2),
    ],
    "Rock Pattern": [
        ("crash", 1), ("kick", 1), ("snare", 1), ("kick",  1),
        ("snare", 1), ("hihat", 0.5), ("hihat", 0.5), ("kick", 1),
        ("snare", 1), ("tom_hi", 1), ("tom_low", 1), ("kick", 1),
        ("snare", 1), ("ride",  1), ("floor",  2),
        ("kick",  1), ("snare", 1), ("hihat", 0.5), ("hihat", 0.5),
        ("kick",  1), ("kick",  1), ("snare", 1), ("crash", 2),
    ],
    "Tom Run": [
        ("crash",   1), ("tom_hi",  1), ("tom_hi",  1), ("tom_low", 1),
        ("tom_low", 1), ("floor",   1), ("floor",   1), ("kick",    2),
        ("crash",   1), ("tom_hi", 0.5), ("tom_hi", 0.5), ("tom_low", 1),
        ("floor",   1), ("snare",   1), ("kick",    1), ("kick",    1),
        ("hihat", 0.5), ("tom_hi", 0.5), ("tom_low", 1), ("floor",   1),
        ("snare",   1), ("snare",   1), ("crash",   2),
    ],
    "Groove": [
        ("hihat", 0.5), ("hihat", 0.5), ("kick",  1), ("hihat", 0.5), ("hihat", 0.5),
        ("snare", 1),   ("hihat", 0.5), ("hihat", 0.5),
        ("kick",  1),   ("hihat", 0.5), ("ride",  0.5), ("snare", 1),
        ("floor", 1),   ("crash", 1),   ("kick",  0.5), ("kick",  0.5),
        ("hihat", 0.5), ("hihat", 0.5), ("kick",  1),   ("snare", 1),
        ("ride",  0.5), ("ride",  0.5), ("floor", 1),   ("crash", 2),
    ],
    "Ballad": [
        ("ride",  1),   ("ride",   1), ("snare", 2),
        ("ride",  1),   ("ride",   1), ("snare", 2),
        ("crash", 1),   ("tom_hi", 1), ("tom_low", 1), ("floor", 1),
        ("kick",  1),   ("kick",   1), ("snare", 2),
        ("ride", 0.5),  ("ride",  0.5), ("ride",  1),  ("snare", 2),
        ("tom_hi", 1),  ("tom_low", 1), ("crash", 2),
    ],
    "Random": [],   # sentinel – generates procedurally
}

SONG_NAMES: list[str] = list(_SONGS.keys())

_DEFAULT_ELEMENTS = [
    "kick", "snare", "hihat", "crash", "ride", "tom_hi", "tom_low", "floor",
]


def _generate_random(elements: list[str], n: int = 24) -> list[tuple[str, float]]:
    """Random sequence on available elements."""
    if not elements:
        elements = list(_DEFAULT_ELEMENTS)
    seq: list[tuple[str, float]] = []
    for _ in range(n):
        elem = random.choice(elements)
        dur  = random.choice([0.5, 1.0, 1.0, 1.0, 2.0])
        seq.append((elem, dur))
    return seq


# ── Tile dataclass ────────────────────────────────────────────────────────

@dataclass
class DrumTile:
    element_key: str
    from_side:   str    # "top" | "bottom" | "left" | "right"
    pad_x_norm:  float  # target pad centre x  (0..1)
    pad_y_norm:  float  # target pad centre y  (0..1)
    pad_rx_norm: float  # pad half-width  (for visual sizing)
    pad_ry_norm: float  # pad half-height (for visual sizing)
    spawn_time:  float
    arrive_time: float
    state:       str = "active"  # active | hit | miss
    score_earned: int = 0


# ── Game state machine ────────────────────────────────────────────────────

class DrumTilesGame:
    """Drum Tiles – tiles fly from screen edges toward drum pads."""

    DIFFICULTY_PROFILES: dict[str, dict] = {
        "easy": {
            "bpm":            60,
            "fall_duration":  2.5,
            "max_mistakes":   5,
            "hit_window":     0.45,
            "perfect_window": 0.15,
            "perfect_pts":    100,
            "good_pts":       50,
        },
        "medium": {
            "bpm":            90,
            "fall_duration":  1.8,
            "max_mistakes":   3,
            "hit_window":     0.35,
            "perfect_window": 0.10,
            "perfect_pts":    150,
            "good_pts":       75,
        },
        "hard": {
            "bpm":            130,
            "fall_duration":  1.2,
            "max_mistakes":   2,
            "hit_window":     0.22,
            "perfect_window": 0.07,
            "perfect_pts":    200,
            "good_pts":       100,
        },
    }

    STATE_IDLE      = "IDLE"
    STATE_PLAYING   = "PLAYING"
    STATE_GAME_OVER = "GAME_OVER"

    def __init__(self) -> None:
        self.state      = self.STATE_IDLE
        self.score      = 0
        self.best_score = 0
        self.mistakes   = 0
        self.combo      = 0
        self.tiles: list[DrumTile] = []

        self._sequence:        list[tuple[str, float]] = []
        self._seq_index:       int   = 0
        self._next_spawn_time: float = 0.0
        self._beat_dur:        float = 1.0
        self._song_name:       str   = ""

        self.last_result:    Optional[str] = None
        self.last_result_ts: float         = 0.0
        self.last_hit_key:   Optional[str] = None

        # difficulty attrs
        self.difficulty     = "easy"
        self.BPM            = 60
        self.FALL_DURATION  = 2.5
        self.MAX_MISTAKES   = 5
        self.HIT_WINDOW     = 0.45
        self.PERFECT_WINDOW = 0.15
        self.PERFECT_PTS    = 100
        self.GOOD_PTS       = 50

        # element_key → (pad_x, pad_y, rx, ry, from_side)
        self._pad_info: dict[str, tuple[float, float, float, float, str]] = {}
        self._available_elements: list[str] = list(_DEFAULT_ELEMENTS)

    # ── setup ─────────────────────────────────────────────────────────────

    def _apply_difficulty(self, difficulty: str) -> None:
        p = self.DIFFICULTY_PROFILES.get(difficulty, self.DIFFICULTY_PROFILES["easy"])
        self.BPM            = p["bpm"]
        self.FALL_DURATION  = p["fall_duration"]
        self.MAX_MISTAKES   = p["max_mistakes"]
        self.HIT_WINDOW     = p["hit_window"]
        self.PERFECT_WINDOW = p["perfect_window"]
        self.PERFECT_PTS    = p["perfect_pts"]
        self.GOOD_PTS       = p["good_pts"]
        self.difficulty     = difficulty

    def set_kit_layout(self, drum_kit: list) -> None:
        """Build pad-position cache from the live DRUM_KIT list."""
        self._pad_info.clear()
        self._available_elements.clear()
        for drum in drum_kit:
            k = drum.get("element_key", "")
            if not k or drum.get("foot_only", False):
                continue
            px, py = drum["pos"]
            rx, ry = drum["axes"]
            # choose approach side from pad position on screen
            if py < 0.5:
                side = "top"
            elif px < 0.35:
                side = "left"
            elif px > 0.65:
                side = "right"
            else:
                side = "bottom"
            self._pad_info[k] = (px, py, rx, ry, side)
            self._available_elements.append(k)

    def start(
        self,
        drum_kit: list,
        song: str = "Basic Beat",
        difficulty: str = "easy",
    ) -> None:
        self._apply_difficulty(difficulty)
        self.set_kit_layout(drum_kit)
        self.score      = 0
        self.mistakes   = 0
        self.combo      = 0
        self.tiles      = []
        self._seq_index = 0
        self._song_name = song
        self.last_result  = None
        self.last_hit_key = None

        avail = self._available_elements or list(_DEFAULT_ELEMENTS)
        if song == "Random":
            self._sequence = _generate_random(avail)
        else:
            raw = list(_SONGS.get(song, _SONGS["Basic Beat"]))
            # keep only elements that are actually in the current kit
            self._sequence = [(e, d) for e, d in raw if e in self._pad_info]
            if not self._sequence:
                self._sequence = _generate_random(avail)

        now = time.time()
        self._beat_dur        = 60.0 / max(1, self.BPM)
        self._next_spawn_time = now + 0.8   # brief lead-in
        self.state = self.STATE_PLAYING

    # ── per-frame update ──────────────────────────────────────────────────

    def update(self, now: float | None = None) -> None:
        if self.state != self.STATE_PLAYING:
            return
        if now is None:
            now = time.time()

        # ── spawn tiles ───────────────────────────────────────────────────
        while (self._seq_index < len(self._sequence)
               and now >= self._next_spawn_time):
            elem_key, beats = self._sequence[self._seq_index]
            if elem_key not in self._pad_info:
                self._seq_index       += 1
                self._next_spawn_time += beats * self._beat_dur
                continue
            px, py, rx, ry, side = self._pad_info[elem_key]
            arrive_time = self._next_spawn_time + self.FALL_DURATION
            self.tiles.append(DrumTile(
                element_key=elem_key,
                from_side=side,
                pad_x_norm=px, pad_y_norm=py,
                pad_rx_norm=rx, pad_ry_norm=ry,
                spawn_time=self._next_spawn_time,
                arrive_time=arrive_time,
            ))
            self._next_spawn_time += beats * self._beat_dur
            self._seq_index       += 1

        # ── expire missed tiles ───────────────────────────────────────────
        for tile in self.tiles:
            if tile.state == "active" and now > tile.arrive_time + self.HIT_WINDOW:
                tile.state          = "miss"
                self.mistakes      += 1
                self.combo          = 0
                self.last_result    = "miss"
                self.last_result_ts = now

        # prune old tile objects
        self.tiles = [
            t for t in self.tiles
            if t.state == "active" or (now - t.arrive_time) < 1.5
        ]

        # ── end conditions ────────────────────────────────────────────────
        if self.mistakes >= self.MAX_MISTAKES:
            self._end_game()
            return

        if (self._seq_index >= len(self._sequence)
                and not any(t.state == "active" for t in self.tiles)):
            self._end_game()

    def _end_game(self) -> None:
        self.state = self.STATE_GAME_OVER
        if self.score > self.best_score:
            self.best_score = self.score

    # ── player input ──────────────────────────────────────────────────────

    def player_hit(self, element_key: str, now: float | None = None) -> str:
        """
        Register a drum pad hit. Returns:
          'perfect' | 'good'  – scored hit
          'ignored'           – tile exists but timing too early/late
          'no_tile'           – no active tile on this pad
        """
        if self.state != self.STATE_PLAYING:
            return "ignored"
        if now is None:
            now = time.time()

        best_tile:  Optional[DrumTile] = None
        best_delta: float              = float("inf")

        for tile in self.tiles:
            if tile.state != "active" or tile.element_key != element_key:
                continue
            delta = abs(now - tile.arrive_time)
            if delta < best_delta:
                best_delta = delta
                best_tile  = tile

        if best_tile is None:
            return "no_tile"

        if best_delta <= self.PERFECT_WINDOW:
            pts, result = self.PERFECT_PTS, "perfect"
        elif best_delta <= self.HIT_WINDOW:
            pts, result = self.GOOD_PTS, "good"
        else:
            # tile found but timing too far off – counts as a miss
            self.combo          = 0
            self.mistakes      += 1
            self.last_result    = "miss"
            self.last_result_ts = now
            return "ignored"

        self.combo += 1
        if self.combo >= 5:
            pts = int(pts * 1.5)

        best_tile.state        = "hit"
        best_tile.score_earned = pts
        self.score            += pts
        self.last_result       = result
        self.last_result_ts    = now
        self.last_hit_key      = element_key
        return result

    # ── display helpers ───────────────────────────────────────────────────

    def tile_progress(self, tile: DrumTile, now: float) -> float:
        """0 = just spawned at screen edge, 1 = arrived at pad, >1 = past."""
        return (now - tile.spawn_time) / max(0.001, self.FALL_DURATION)

    @property
    def progress(self) -> float:
        total = len(self._sequence)
        return min(1.0, self._seq_index / total) if total else 1.0

    @property
    def lives_remaining(self) -> int:
        return max(0, self.MAX_MISTAKES - self.mistakes)

    @property
    def song_name(self) -> str:
        return self._song_name
