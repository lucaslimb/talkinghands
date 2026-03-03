"""
Piano Tiles–style game engine (pure state machine, no pygame/cv2).

Tiles fall from the top of the screen toward the hit-line at the bottom.
The player must touch the correct key as the tile crosses the hit-line.

States: IDLE → PLAYING → GAME_OVER
"""

import time
import random
from dataclasses import dataclass
from typing import Optional


# ── Built-in songs  (midi_note, duration_in_beats) ───────────────────────
# Reference: C4=60  D4=62  E4=64  F4=65  G4=67  A4=69  B4=71  C5=72
_SONGS: dict[str, list[tuple[int, float]]] = {
    "Twinkle Twinkle": [
        (60,1),(60,1),(67,1),(67,1),(69,1),(69,1),(67,2),
        (65,1),(65,1),(64,1),(64,1),(62,1),(62,1),(60,2),
        (67,1),(67,1),(65,1),(65,1),(64,1),(64,1),(62,2),
        (67,1),(67,1),(65,1),(65,1),(64,1),(64,1),(62,2),
        (60,1),(60,1),(67,1),(67,1),(69,1),(69,1),(67,2),
        (65,1),(65,1),(64,1),(64,1),(62,1),(62,1),(60,2),
    ],
    "Ode to Joy": [
        (64,1),(64,1),(65,1),(67,1),(67,1),(65,1),(64,1),(62,1),
        (60,1),(60,1),(62,1),(64,1),(64,1.5),(62,.5),(62,2),
        (64,1),(64,1),(65,1),(67,1),(67,1),(65,1),(64,1),(62,1),
        (60,1),(60,1),(62,1),(64,1),(62,1.5),(60,.5),(60,2),
        (62,1),(62,1),(64,1),(60,1),(62,1),(64,.5),(65,.5),(64,1),(60,1),
        (62,1),(64,.5),(65,.5),(64,1),(62,1),(60,1),(62,1),(55,2),
    ],
    "Happy Birthday": [
        (60,.75),(60,.25),(62,1),(60,1),(65,1),(64,2),
        (60,.75),(60,.25),(62,1),(60,1),(67,1),(65,2),
        (60,.75),(60,.25),(72,1),(69,1),(65,1),(64,1),(62,2),
        (70,.75),(70,.25),(69,1),(65,1),(67,1),(65,2),
    ],
    "Mary Had a Little Lamb": [
        (64,1),(62,1),(60,1),(62,1),(64,1),(64,1),(64,2),
        (62,1),(62,1),(62,2),(64,1),(67,1),(67,2),
        (64,1),(62,1),(60,1),(62,1),(64,1),(64,1),(64,1),(64,1),
        (62,1),(62,1),(64,1),(62,1),(60,4),
    ],
    "Jingle Bells (refrao)": [
        (64,1),(64,1),(64,2),
        (64,1),(64,1),(64,2),
        (64,1),(67,1),(60,1),(62,1),(64,4),
        (65,1),(65,1),(65,1),(65,1),(65,1),(64,1),(64,1),(64,.5),(64,.5),
        (64,1),(62,1),(62,1),(64,1),(62,2),(67,2),
        (64,1),(64,1),(64,2),
        (64,1),(64,1),(64,2),
        (64,1),(67,1),(60,1),(62,1),(64,4),
        (65,1),(65,1),(65,1),(65,1),(65,1),(64,1),(64,1),(64,.5),(64,.5),
        (67,1),(67,1),(65,1),(62,1),(60,4),
    ],
    "Random": [],   # sentinel — built procedurally
}

# All song names (for cycling in the game UI)
SONG_NAMES: list[str] = list(_SONGS.keys())

# C‑major scale C4..C5 used for random generation
_SCALE_NOTES = [60, 62, 64, 65, 67, 69, 71, 72]


def _generate_random(n: int = 36) -> list[tuple[int, float]]:
    """Random-walk melody on C major."""
    seq: list[tuple[int, float]] = []
    idx = 4  # start on E4
    for _ in range(n):
        idx = max(0, min(len(_SCALE_NOTES) - 1, idx + random.choice([-2, -1, 0, 1, 2])))
        dur = random.choice([0.5, 1.0, 1.0, 1.0, 1.5, 2.0])
        seq.append((_SCALE_NOTES[idx], dur))
    return seq


# ── Tile dataclass ────────────────────────────────────────────────────────

@dataclass
class Tile:
    note: int
    x_start_norm: float     # piano key left edge (0..1)
    x_end_norm:   float     # piano key right edge (0..1)
    spawn_time:   float     # wall-clock time when this tile started falling
    arrive_time:  float     # wall-clock time when leading edge reaches hit-line
    duration:     float     # visual body height in seconds (for long notes)
    state:        str = "active"    # active | hit | miss | expired
    score_earned: int = 0


# ── Game state machine ────────────────────────────────────────────────────

class TilesGame:
    """Piano Tiles–style game."""

    # ── difficulty profiles ───────────────────────────────────────────────
    DIFFICULTY_PROFILES: dict[str, dict] = {
        "easy": {
            "bpm":             60,
            "fall_duration":   2.5,     # seconds a tile takes from top → hit-line
            "max_mistakes":    5,
            "hit_window":      0.45,    # ±s around arrive_time counts as hit
            "perfect_window":  0.15,
            "perfect_pts":     100,
            "good_pts":        50,
        },
        "medium": {
            "bpm":             90,
            "fall_duration":   1.8,
            "max_mistakes":    3,
            "hit_window":      0.35,
            "perfect_window":  0.10,
            "perfect_pts":     150,
            "good_pts":        75,
        },
        "hard": {
            "bpm":             130,
            "fall_duration":   1.2,
            "max_mistakes":    2,
            "hit_window":      0.22,
            "perfect_window":  0.07,
            "perfect_pts":     200,
            "good_pts":        100,
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
        self.tiles: list[Tile] = []

        self._sequence:       list[tuple[int, float]] = []
        self._seq_index:      int   = 0
        self._next_spawn_time:float = 0.0
        self._beat_dur:       float = 1.0
        self._song_name:      str   = ""

        self.last_result:    Optional[str]   = None   # "perfect"|"good"|"miss"
        self.last_result_ts: float           = 0.0
        self.pending_play_note: Optional[int] = None  # engine → audio bridge

        # difficulty attrs (overwritten by _apply_difficulty)
        self.difficulty     = "easy"
        self.BPM            = 60
        self.FALL_DURATION  = 2.5
        self.MAX_MISTAKES   = 5
        self.HIT_WINDOW     = 0.45
        self.PERFECT_WINDOW = 0.15
        self.PERFECT_PTS    = 100
        self.GOOD_PTS       = 50

        # note → (x_start_norm, x_end_norm) cache
        self._note_to_x: dict[int, tuple[float, float]] = {}

    # ── setup helpers ─────────────────────────────────────────────────────

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

    def set_key_layout(self, piano_keys: list) -> None:
        """Cache note→x-range mapping from a PIANO_KEYS snapshot."""
        self._note_to_x = {
            int(k["note"]): (float(k["x_start_norm"]), float(k["x_end_norm"]))
            for k in piano_keys
        }

    def start(
        self,
        piano_keys: list,
        song: str = "Twinkle Twinkle",
        difficulty: str = "easy",
    ) -> None:
        self._apply_difficulty(difficulty)
        self.set_key_layout(piano_keys)
        self.score      = 0
        self.mistakes   = 0
        self.combo      = 0
        self.tiles      = []
        self._seq_index = 0
        self._song_name = song
        self.last_result       = None
        self.pending_play_note = None

        if song == "Random":
            self._sequence = _generate_random(40)
        else:
            self._sequence = list(_SONGS.get(song, _SONGS["Twinkle Twinkle"]))

        now = time.time()
        self._beat_dur        = 60.0 / max(1, self.BPM)
        self._next_spawn_time = now + 0.6   # brief lead-in before first tile
        self.state = self.STATE_PLAYING

    def restart(self, piano_keys: list, difficulty: str | None = None) -> None:
        self.start(
            piano_keys,
            song=self._song_name or "Twinkle Twinkle",
            difficulty=difficulty or self.difficulty,
        )

    # ── per-frame update ──────────────────────────────────────────────────

    def update(self, now: float | None = None) -> None:
        if self.state != self.STATE_PLAYING:
            return
        if now is None:
            now = time.time()

        self.pending_play_note = None

        # ── spawn new tiles ───────────────────────────────────────────────
        while (self._seq_index < len(self._sequence)
               and now >= self._next_spawn_time):
            note, beats = self._sequence[self._seq_index]
            x_pair = self._note_to_x.get(note)
            if x_pair is None:
                # map to the closest visible key
                if self._note_to_x:
                    note   = min(self._note_to_x, key=lambda n: abs(n - note))
                    x_pair = self._note_to_x[note]
                else:
                    self._seq_index       += 1
                    self._next_spawn_time += beats * self._beat_dur
                    continue
            x_start, x_end  = x_pair
            arrive_time      = self._next_spawn_time + self.FALL_DURATION
            tile_visual_dur  = max(0.18, beats * self._beat_dur * 0.65)

            self.tiles.append(Tile(
                note=note,
                x_start_norm=x_start,
                x_end_norm=x_end,
                spawn_time=self._next_spawn_time,
                arrive_time=arrive_time,
                duration=tile_visual_dur,
            ))

            # audio cue: play note as tile spawns (demo melody)
            self.pending_play_note = note
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

        # prune old tiles from memory
        self.tiles = [
            t for t in self.tiles
            if t.state == "active" or (now - t.arrive_time) < 1.8
        ]

        # ── check end conditions ──────────────────────────────────────────
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

    def player_hit(self, note: int, now: float | None = None) -> str:
        """
        Register a key touch. Returns 'perfect' | 'good' | 'ignored'.
        Only the closest active tile for that note is evaluated.
        """
        if self.state != self.STATE_PLAYING:
            return "ignored"
        if now is None:
            now = time.time()

        best_tile:  Optional[Tile] = None
        best_delta: float          = float("inf")

        for tile in self.tiles:
            if tile.state != "active" or tile.note != note:
                continue
            delta = abs(now - tile.arrive_time)
            if delta < best_delta:
                best_delta = delta
                best_tile  = tile

        if best_tile is None:
            return "no_tile"   # no active tile on this key at all

        if best_delta <= self.PERFECT_WINDOW:
            pts    = self.PERFECT_PTS
            result = "perfect"
        elif best_delta <= self.HIT_WINDOW:
            pts    = self.GOOD_PTS
            result = "good"
        else:
            return "ignored"

        self.combo += 1
        if self.combo >= 5:
            pts = int(pts * 1.5)

        best_tile.state        = "hit"
        best_tile.score_earned = pts
        self.score            += pts
        self.last_result       = result
        self.last_result_ts    = now
        return result

    # ── display helpers ───────────────────────────────────────────────────

    def tile_y_norm(self, tile: Tile, now: float) -> float:
        """
        Normalised y of the tile's leading edge.
        0 = just spawned at top, 1 = exactly at hit-line, >1 = past hit-line.
        """
        return (now - tile.spawn_time) / max(0.001, self.FALL_DURATION)

    def tile_tail_y_norm(self, tile: Tile, now: float) -> float:
        """Normalised y of the tile's trailing (top) edge."""
        body_frac = tile.duration / max(0.001, self.FALL_DURATION)
        return self.tile_y_norm(tile, now) - body_frac

    # ── properties ────────────────────────────────────────────────────────

    @property
    def song_name(self) -> str:
        return self._song_name

    @property
    def progress(self) -> float:
        total = len(self._sequence)
        return min(1.0, self._seq_index / total) if total else 1.0

    @property
    def lives_remaining(self) -> int:
        return max(0, self.MAX_MISTAKES - self.mistakes)
