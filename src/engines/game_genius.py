"""
GeniusGame — state machine for the Genius / Simon-style drum game.

States
------
IDLE        → waiting to start (show intro screen)
DEMO        → replaying the current sequence with sound + colour flash
WAIT_INPUT  → player must reproduce the sequence
FEEDBACK    → brief flash after each player hit (correct or wrong)
GAME_OVER   → showing final score, waiting for restart

Difficulty
----------
  easy    – slow demo, 12 s timeout, default kit
  medium  – faster demo, 8 s timeout, +3 extra elements, higher velocity
  hard    – fastest demo, 4.5 s timeout, +6 extra elements, max velocity

Scoring
-------
  hit points + time-bonus per completed round (varies by difficulty).
  best_score is persisted across rounds in the same session.
"""

import random
import time


class GeniusGame:
    # ── public state labels ───────────────────────────────────────────────
    STATE_IDLE       = "IDLE"
    STATE_DEMO       = "DEMO"
    STATE_WAIT_INPUT = "WAIT_INPUT"
    STATE_FEEDBACK   = "FEEDBACK"
    STATE_GAME_OVER  = "GAME_OVER"

    # ── class-level defaults (easy) ────────────────────────────────────────
    DEMO_PRE_DELAY    = 1.20
    FEEDBACK_DURATION = 0.20

    # ── difficulty profiles ────────────────────────────────────────────────
    # Keys: demo_hit, demo_pause, demo_velocity, timeout, hit_points
    DIFFICULTY_PROFILES: dict[str, dict] = {
        "easy": {
            "demo_hit":       0.55,
            "demo_pause":     0.18,
            "demo_velocity":  100,
            "timeout":        12.0,
            "hit_points":     100,
        },
        "medium": {
            "demo_hit":       0.36,
            "demo_pause":     0.11,
            "demo_velocity":  112,
            "timeout":         8.0,
            "hit_points":     125,
        },
        "hard": {
            "demo_hit":       0.20,
            "demo_pause":     0.06,
            "demo_velocity":  127,
            "timeout":         4.5,
            "hit_points":     150,
        },
    }

    def __init__(self):
        self._available: list[str] = []   # element keys in the current kit

        # --- public readable state ---
        self.state               = self.STATE_IDLE
        self.sequence: list[str] = []     # current challenge sequence
        self.player_index        = 0      # index of the next expected hit
        self.score               = 0
        self.best_score          = 0
        self.round               = 0
        self.difficulty          = "easy"

        # ── active timing / scoring (set by _apply_difficulty) ────────────
        self.DEMO_HIT_DURATION  = 0.55
        self.DEMO_PAUSE         = 0.18
        self.DEMO_VELOCITY      = 100
        self.PLAYER_TIMEOUT     = 12.0
        self.HIT_POINTS         = 100
        self.last_round_bonus   = 0
        self.last_speed_bonus   = 0

        # element_key that should be highlighted this frame (DEMO only)
        self.highlighted_element: str | None = None

        # (note, velocity) the loop must send to audio this frame; consumed once read
        self.pending_play_note: tuple[int, int] | None = None

        # result of last player feedback: True = correct, False = wrong
        self.last_hit_correct: bool = True

        # --- private demo tracking ---
        self._demo_index  = 0
        self._demo_phase  = "show"   # "show" | "pause"
        self._demo_time   = 0.0      # next time to advance demo state

        # --- private turn/feedback tracking ---
        self._turn_start     = 0.0
        self._feedback_time  = 0.0

    # ── public API ──────────────────────────────────────────────────────

    def _apply_difficulty(self, difficulty: str) -> None:
        """Load timing and scoring parameters for the given difficulty key."""
        profile = self.DIFFICULTY_PROFILES.get(difficulty, self.DIFFICULTY_PROFILES["easy"])
        self.difficulty         = difficulty
        self.DEMO_HIT_DURATION  = profile["demo_hit"]
        self.DEMO_PAUSE         = profile["demo_pause"]
        self.DEMO_VELOCITY      = profile["demo_velocity"]
        self.PLAYER_TIMEOUT     = profile["timeout"]
        self.HIT_POINTS         = profile["hit_points"]

    def start(self, available_keys: list[str], difficulty: str = "easy") -> None:
        """Begin a brand-new game with the supplied drum element keys."""
        self._apply_difficulty(difficulty)
        self._available = list(available_keys)
        if not self._available:
            return
        self.sequence       = [random.choice(self._available)]
        self.score          = 0
        self.round          = 1
        self.player_index   = 0
        self.last_round_bonus = 0
        self.last_speed_bonus = 0
        self._start_demo()

    def restart(self, difficulty: str | None = None) -> None:
        """Restart from GAME_OVER or IDLE using the existing kit."""
        if self._available:
            self.start(self._available, difficulty=difficulty or self.difficulty)

    def player_hit(self, element_key: str, now: float | None = None) -> str:
        """
        Called when the player physically hits *element_key*.

        Returns
        -------
        "correct"  – hit matches the expected element
        "wrong"    – hit does not match (triggers FEEDBACK → GAME_OVER)
        "ignored"  – not the player's turn right now
        """
        if self.state != self.STATE_WAIT_INPUT:
            return "ignored"

        if now is None:
            now = time.time()

        expected = self.sequence[self.player_index]

        if element_key == expected:
            self.score += self.HIT_POINTS
            self.last_hit_correct = True
            self._feedback_time   = now
            self.state            = self.STATE_FEEDBACK
            return "correct"
        else:
            self.last_hit_correct = False
            self._feedback_time   = now
            self.state            = self.STATE_FEEDBACK
            return "wrong"

    def update(self, drum_kit: list[dict], now: float | None = None) -> None:
        """
        Advance the state machine.  Call once per rendered frame.

        drum_kit  – list of drum dicts (the live DRUM_KIT from drums.py)
        """
        if now is None:
            now = time.time()

        # reset per-frame outputs
        self.pending_play_note = None

        if self.state == self.STATE_DEMO:
            self._update_demo(drum_kit, now)

        elif self.state == self.STATE_WAIT_INPUT:
            if now - self._turn_start > self.PLAYER_TIMEOUT:
                self._trigger_game_over()

        elif self.state == self.STATE_FEEDBACK:
            if now - self._feedback_time >= self.FEEDBACK_DURATION:
                if self.last_hit_correct:
                    self.player_index += 1
                    if self.player_index >= len(self.sequence):
                        # ── full sequence matched ──────────────────────────
                        self.last_round_bonus = self._round_bonus()
                        self.last_speed_bonus = self._speed_bonus(now, self.last_round_bonus)
                        self.score += self.last_round_bonus + self.last_speed_bonus
                        # extend sequence
                        self.sequence.append(random.choice(self._available))
                        self.round += 1
                        self._start_demo()
                    else:
                        # more hits expected in this round
                        self.state = self.STATE_WAIT_INPUT
                else:
                    self._trigger_game_over()

    def _round_bonus(self) -> int:
        if self.round <= 4:
            return 100 * self.round
        if self.round <= 9:
            return 150 * self.round
        return 200 * self.round

    def _speed_bonus(self, now: float, round_bonus: int) -> int:
        remaining_fraction = max(0.0, 1.0 - (now - self._turn_start) / self.PLAYER_TIMEOUT)
        return round(round_bonus * 0.25 * remaining_fraction)

    # ── helpers ───────────────────────────────────────────────────────────

    def _start_demo(self) -> None:
        self.state               = self.STATE_DEMO
        self._demo_index         = 0
        self._demo_phase         = "show"
        self._demo_time          = time.time() + self.DEMO_PRE_DELAY
        self.highlighted_element = None
        self.pending_play_note   = None

    def _update_demo(self, drum_kit: list[dict], now: float) -> None:
        if now < self._demo_time:
            return  # still waiting for next transition

        if self._demo_index >= len(self.sequence):
            # demo finished → player's turn
            self.highlighted_element = None
            self.player_index        = 0
            self.state               = self.STATE_WAIT_INPUT
            self._turn_start         = time.time()
            return

        elem_key = self.sequence[self._demo_index]

        if self._demo_phase == "show":
            self.highlighted_element = elem_key
            # queue the note to be played this frame
            drum = next((d for d in drum_kit if d.get("element_key") == elem_key), None)
            if drum:
                self.pending_play_note = (drum["note"], self.DEMO_VELOCITY)
            self._demo_phase = "pause"
            self._demo_time  = now + self.DEMO_HIT_DURATION

        else:  # "pause"
            self.highlighted_element = None
            self._demo_index += 1
            self._demo_phase = "show"
            self._demo_time  = now + self.DEMO_PAUSE

    def _trigger_game_over(self) -> None:
        self.state               = self.STATE_GAME_OVER
        self.highlighted_element = None
        if self.score > self.best_score:
            self.best_score = self.score

    # ── convenience properties ────────────────────────────────────────────

    @property
    def is_idle(self)      -> bool: return self.state == self.STATE_IDLE
    @property
    def is_demo(self)      -> bool: return self.state == self.STATE_DEMO
    @property
    def is_player_turn(self)-> bool: return self.state == self.STATE_WAIT_INPUT
    @property
    def is_feedback(self)  -> bool: return self.state == self.STATE_FEEDBACK
    @property
    def is_game_over(self) -> bool: return self.state == self.STATE_GAME_OVER

    @property
    def remaining_time(self) -> float:
        """Seconds left in the player's turn (0 when it's not the player's turn)."""
        if self.state != self.STATE_WAIT_INPUT:
            return 0.0
        elapsed = time.time() - self._turn_start
        return max(0.0, self.PLAYER_TIMEOUT - elapsed)

    @property
    def sequence_length(self) -> int:
        return len(self.sequence)
