"""
Piano Tiles–style keyboard game mode.

Coloured tiles fall from the top of the screen toward the piano keys.
The player must touch the correct key as each tile crosses the hit-line.

Entry point: start_piano_tiles(...)
"""

import cv2
import mediapipe as mp
import threading
import time
import sys
import math
import pygame
from pathlib import Path
from typing import Optional

FILE_PATH   = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# ── keyboard infrastructure ───────────────────────────────────────────────
# Import the module so we can use its utility functions and globals.
# keyboard.py starts FluidSynth at import time; we reuse that instance.
import src.instruments.keyboard as _kbd_mod
from src.instruments.keyboard import (
    build_piano_keys,
    apply_piano_geometry,
    get_key_index_from_x,
    is_black_key,
    select_instrument_by_name,
    set_keyboard_expression,
    set_keyboard_digital_gain,
    audio_queue,
    audio_thread_target,
    fs,
    BLACK_KEY_HEIGHT_RATIO,
    BLACK_KEY_WIDTH_RATIO,
    ACTIVE_FINGERS,
)
from src.instruments.common import (
    setup_video_capture,
    setup_pygame_with_scaling,
    fit_resolution_to_screen,
    draw_text,
)
from src.engines.game_tiles import TilesGame, SONG_NAMES
from src.config import settings
import random
import io
import numpy as np

# ── error sounds ──────────────────────────────────────────────────────────
# Loaded at startup; leading silence is stripped so playback is near-instant.

_ERROR_SOUNDS: list[pygame.mixer.Sound] = []
_error_sound_channel: Optional[pygame.mixer.Channel] = None
_last_error_time: float = 0.0
_ERROR_COOLDOWN  = 0.25   # seconds between error sound triggers


def _trim_silence(sound: pygame.mixer.Sound,
                  threshold: int = 200) -> pygame.mixer.Sound:
    """
    Return a new Sound with any leading silence stripped.
    `threshold` is the minimum absolute sample value that counts as non-silent.
    Falls back to the original if sndarray or numpy is unavailable.
    """
    try:
        arr = pygame.sndarray.array(sound)   # shape: (frames, channels) or (frames,)
        flat = np.abs(arr).max(axis=-1) if arr.ndim > 1 else np.abs(arr)
        nonzero = np.where(flat > threshold)[0]
        if len(nonzero) == 0:
            return sound
        start = max(0, int(nonzero[0]) - 64)   # keep 64 samples before first loud frame
        trimmed = arr[start:]
        return pygame.sndarray.make_sound(trimmed)
    except Exception:
        return sound


def _load_error_sounds() -> None:
    """Load all error_*.mp3 from assets/sounds into _ERROR_SOUNDS."""
    global _error_sound_channel
    if _ERROR_SOUNDS:           # already loaded — don't double-add
        return
    sounds_dir = PROJECT_ROOT / "assets" / "sounds"
    files      = sorted(sounds_dir.glob("error_*.mp3"))
    for f in files:
        try:
            snd = pygame.mixer.Sound(str(f))
            snd = _trim_silence(snd)
            snd.set_volume(0.3)
            _ERROR_SOUNDS.append(snd)
        except Exception as e:
            print(f"[tiles] Aviso: não foi possível carregar {f.name}: {e}")
    if _ERROR_SOUNDS:
        _error_sound_channel = pygame.mixer.Channel(7)  # dedicated channel
        print(f"[tiles] {len(_ERROR_SOUNDS)} error sound(s) carregados")
    else:
        print("[tiles] Nenhum error sound encontrado – erros serão silenciosos")


def _play_error_sound(now: float) -> None:
    """Play a random error sound if cooldown has elapsed."""
    global _last_error_time
    if not _ERROR_SOUNDS or _error_sound_channel is None:
        return
    if now - _last_error_time < _ERROR_COOLDOWN:
        return
    _last_error_time = now
    snd = random.choice(_ERROR_SOUNDS)
    _error_sound_channel.stop()
    _error_sound_channel.play(snd)

# ── colour palette (one colour per note class 0-11 → C..B) ───────────────
_NOTE_COLORS: list[tuple[int, int, int]] = [
    (255,  80,  80),  # 0  C   – red
    (255, 140,   0),  # 1  C#  – orange
    (255, 220,  50),  # 2  D   – yellow
    (150, 230,  50),  # 3  D#  – lime
    ( 60, 210,  90),  # 4  E   – green
    ( 50, 210, 200),  # 5  F   – teal
    ( 50, 150, 255),  # 6  F#  – sky-blue
    (100,  80, 255),  # 7  G   – indigo
    (180,  70, 255),  # 8  G#  – violet
    (255,  80, 200),  # 9  A   – pink
    (255, 120, 120),  # 10 A#  – salmon
    (200, 200, 200),  # 11 B   – light grey
]

_DIFFICULTY_COLOR: dict[str, tuple[int, int, int]] = {
    "easy":   ( 80, 220, 100),
    "medium": (255, 200,  50),
    "hard":   (255,  70,  70),
}
_DIFFICULTY_LABEL: dict[str, str] = {
    "easy": "EASY", "medium": "MEDIUM", "hard": "HARD",
}

# Notes range used for the game keyboard (covers all built-in songs + a bit extra)
_GAME_BASE_NOTE  = 55   # G3  – gives enough room below C4
_GAME_NUM_KEYS   = 22   # G3 → A4  (covers 55..76: all song notes + some extra)


def _note_color(midi_note: int) -> tuple[int, int, int]:
    return _NOTE_COLORS[int(midi_note) % 12]


def _build_game_keys() -> list[dict]:
    """Build a fixed-range piano key list  for game mode."""
    keys = []
    for i in range(_GAME_NUM_KEYS):
        note = _GAME_BASE_NOTE + i
        keys.append({
            "note": note,
            "last_hit": 0,
            "is_active": False,
            "off_timer": 0,
            "is_black": is_black_key(note),
            "x_start_norm": 0.0,
            "x_end_norm":   1.0,
        })
    apply_piano_geometry(keys)
    return keys


# ── finger tap detection ──────────────────────────────────────────────────

_finger_prev_y: dict[tuple[str, int], float] = {}
_pending_note_offs: list[tuple[int, float]] = []   # (note, off_time) – fallback release
_active_held_notes: dict[tuple[str, int], int] = {}  # (label, fid) → midi note


def _reset_finger_state() -> None:
    _finger_prev_y.clear()
    _pending_note_offs.clear()
    _active_held_notes.clear()


def _process_taps(
    label: str,
    landmarks,
    piano_keys: list[dict],
    table_y: float,
    game: TilesGame,
    now: float,
) -> list[int]:
    """
    Detect downward fingertip crossings over the hit-line (note on)
    and upward crossings (note off), so notes are held while the finger
    presses down and released when the finger lifts.
    Returns list of notes that were freshly tapped this frame.
    Plays error sound when a hit is ignored (wrong key or bad timing).
    """
    tapped: list[int] = []
    for fid in ACTIVE_FINGERS:
        tip    = landmarks[fid]
        fkey   = (label, fid)
        prev_y = _finger_prev_y.get(fkey, 0.0)
        curr_y = tip.y

        _finger_prev_y[fkey] = curr_y

        # ── note release: finger lifted back above hit-line ───────────────
        if fkey in _active_held_notes and prev_y >= table_y and curr_y < table_y:
            released = _active_held_notes.pop(fkey)
            audio_queue.put(("off", released))
            # remove the fallback off entry too
            _pending_note_offs[:] = [(n, t) for n, t in _pending_note_offs if n != released]

        # ── tap: downward crossing through hit-line ───────────────────────
        if prev_y < table_y and curr_y >= table_y:
            key_idx = get_key_index_from_x(tip.x)
            if 0 <= key_idx < len(piano_keys):
                note   = int(piano_keys[key_idx]["note"])
                result = game.player_hit(note, now=now)
                if result in ("perfect", "good"):
                    # release any note this finger was already holding
                    if fkey in _active_held_notes:
                        old = _active_held_notes.pop(fkey)
                        audio_queue.put(("off", old))
                        _pending_note_offs[:] = [(n, t) for n, t in _pending_note_offs if n != old]
                    audio_queue.put(("on", note))
                    _active_held_notes[fkey] = note
                    # fallback: auto-release after 4 s in case lift is missed
                    _pending_note_offs.append((note, now + 4.0))
                    piano_keys[key_idx]["last_hit"] = now
                    tapped.append(note)
                elif result == "no_tile" and game.state == game.STATE_PLAYING:
                    _play_error_sound(now)
    return tapped


def _flush_note_offs(now: float) -> None:
    due = [(n, t) for n, t in _pending_note_offs if now >= t]
    for note, _ in due:
        audio_queue.put(("off", note))
    for item in due:
        _pending_note_offs.remove(item)


# ── rendering helpers ─────────────────────────────────────────────────────

_HIT_FLASH: dict[int, dict] = {}   # note → {"result": str, "ts": float}


def _record_hit_flash(note: int, result: str, now: float) -> None:
    _HIT_FLASH[note] = {"result": result, "ts": now}


def _draw_piano_keys(surface, piano_keys: list[dict], w: int, h: int,
                     table_y: float, now: float) -> None:
    """Draw simplified piano keys at the bottom (table_y → screen bottom)."""
    table_px = int(table_y * h)
    total_h  = h - table_px
    black_h  = int(total_h * BLACK_KEY_HEIGHT_RATIO)

    overlay = pygame.Surface((w, h), pygame.SRCALPHA)

    white_keys = [k for k in piano_keys if not k["is_black"]]
    black_keys = [k for k in piano_keys if     k["is_black"]]

    for key in white_keys:
        x1   = int(key["x_start_norm"] * w)
        x2   = int(key["x_end_norm"]   * w)
        kw   = max(1, x2 - x1)
        note = int(key["note"])
        col  = _note_color(note)

        # base: very dim tint
        pygame.draw.rect(overlay, (*col, 18), (x1, table_px, kw, total_h))
        # divider
        pygame.draw.line(surface, (80, 80, 80), (x1, table_px), (x1, h), 1)

        # recent tap flash
        if (now - key["last_hit"]) < 0.25:
            alpha = int(160 * (1.0 - (now - key["last_hit"]) / 0.25))
            pygame.draw.rect(overlay, (*col, alpha), (x1, table_px, kw, total_h))

    for key in black_keys:
        x1   = int(key["x_start_norm"] * w)
        x2   = int(key["x_end_norm"]   * w)
        kw   = max(1, x2 - x1)
        note = int(key["note"])
        col  = _note_color(note)

        pygame.draw.rect(overlay, (20, 20, 20, 200), (x1, table_px, kw, black_h))
        pygame.draw.rect(surface, (60, 60, 60),       (x1, table_px, kw, black_h), 1)

        if (now - key["last_hit"]) < 0.25:
            alpha = int(180 * (1.0 - (now - key["last_hit"]) / 0.25))
            pygame.draw.rect(overlay, (*col, alpha), (x1, table_px, kw, black_h))

    surface.blit(overlay, (0, 0))

    # hit line – bright strip along table_y
    pygame.draw.line(surface, (255, 255, 255), (0, table_px), (w, table_px), 3)


def _draw_tiles(surface, game: TilesGame, w: int, h: int,
                table_y: float, now: float) -> None:
    """Draw all actively falling / recently-hit tiles."""
    table_px = int(table_y * h)
    overlay  = pygame.Surface((w, table_px), pygame.SRCALPHA)

    for tile in game.tiles:
        note  = tile.note
        col   = _note_color(note)
        x1_px = int(tile.x_start_norm * w)
        x2_px = int(tile.x_end_norm   * w)
        tw    = max(2, x2_px - x1_px - 2)  # 1px gap each side

        lead_y  = game.tile_y_norm(tile, now)     # 0..1 relative to table area
        tail_y  = game.tile_tail_y_norm(tile, now)

        lead_px = int(lead_y * table_px)
        tail_px = int(tail_y * table_px)

        # clamp to the visible lane
        draw_y1 = max(0, tail_px)
        draw_y2 = min(table_px, lead_px)

        if draw_y2 <= draw_y1:
            continue

        tile_h = draw_y2 - draw_y1

        if tile.state == "hit":
            # fade-out green
            age   = now - tile.arrive_time
            alpha = max(0, min(255, int(200 * (1.0 - age / 0.4))))
            pygame.draw.rect(overlay, (80, 255, 120, alpha),
                             (x1_px + 1, draw_y1, tw, tile_h))
            pygame.draw.rect(overlay, (200, 255, 200, alpha),
                             (x1_px + 1, draw_y1, tw, tile_h), 2)

        elif tile.state == "miss":
            # fade-out red
            age   = now - tile.arrive_time
            alpha = max(0, min(255, int(180 * (1.0 - age / 0.5))))
            pygame.draw.rect(overlay, (255, 60, 60, alpha),
                             (x1_px + 1, draw_y1, tw, tile_h))
        else:
            # active tile: solid fill + bright border
            pygame.draw.rect(overlay, (*col, 210),
                             (x1_px + 1, draw_y1, tw, tile_h))
            # highlight the leading edge (closest to hit-line)
            if lead_px <= table_px + 2:
                # in hit zone – flash bright
                pulse = 0.5 + 0.5 * math.sin(now * 12)
                edge_alpha = int(160 + 90 * pulse)
                pygame.draw.rect(overlay, (255, 255, 255, edge_alpha),
                                 (x1_px + 1, draw_y1, tw, 4))
            else:
                pygame.draw.rect(overlay, (255, 255, 255, 140),
                                 (x1_px + 1, draw_y1, tw, tile_h), 2)

    surface.blit(overlay, (0, 0))


def _draw_hud(surface, w: int, h: int, font, big_font,
              game: TilesGame, difficulty: str, now: float,
              song: str = "") -> None:
    """Draw top HUD bar: song title, score, combo, precision flash, progress."""
    bar_h = 72
    strip = pygame.Surface((w, bar_h), pygame.SRCALPHA)
    strip.fill((0, 0, 0, 160))
    surface.blit(strip, (0, 0))

    diff_col = _DIFFICULTY_COLOR.get(difficulty, (200, 200, 200))
    diff_lbl = _DIFFICULTY_LABEL.get(difficulty, difficulty.upper())

    # song name – big, centred in upper half of bar
    if song:
        title = big_font.render(song, True, (255, 220, 60))
        surface.blit(title, (w // 2 - title.get_width() // 2, 4))

    # "PIANO TILES" subtitle – small, centred in lower portion of bar
    sub = font.render("PIANO TILES", True, (160, 140, 80))
    surface.blit(sub, (w // 2 - sub.get_width() // 2, 50))

    # difficulty badge – left, vertically centred
    diff_surf = font.render(diff_lbl, True, diff_col)
    ph = diff_surf.get_height() + 8
    pw = diff_surf.get_width()  + 16
    pill = pygame.Surface((pw, ph), pygame.SRCALPHA)
    pill.fill((*diff_col, 40))
    pygame.draw.rect(pill, (*diff_col, 180), pill.get_rect(), 2)
    py = bar_h // 2 - ph // 2
    surface.blit(pill,      (14, py))
    surface.blit(diff_surf, (22, py + 4))

    # score + best – right side
    draw_text(surface, f"Score: {game.score}",      (w - 210, 8),  font, (255, 255, 255))
    if game.best_score > 0:
        draw_text(surface, f"Best: {game.best_score}", (w - 210, 28), font, (200, 200, 200))

    # last result flash – inside HUD bar, right of score
    if game.last_result and (now - game.last_result_ts) < 0.7:
        age   = now - game.last_result_ts
        alpha = int(255 * (1.0 - age / 0.7))
        res   = game.last_result
        if res == "perfect":
            rc, txt = (255, 230, 60), "PERFECT!"
        elif res == "good":
            rc, txt = (100, 200, 255), "GOOD"
        else:
            rc, txt = (255, 80, 80),  "MISS"
        rs = font.render(txt, True, rc)
        rs.set_alpha(alpha)
        surface.blit(rs, (w - 210, 50))

    # combo badge – below the bar, left side
    if game.combo >= 3:
        combo_txt  = f"x{game.combo} COMBO"
        combo_col  = (255, 230, 60) if game.combo < 10 else (255, 100, 255)
        combo_surf = font.render(combo_txt, True, combo_col)
        surface.blit(combo_surf, (14, bar_h + 6))

    # song progress bar at very bottom of HUD strip
    prog_w = int(w * game.progress)
    pygame.draw.rect(surface, (50, 50, 50),   (0, bar_h - 4, w, 4))
    pygame.draw.rect(surface, diff_col,       (0, bar_h - 4, prog_w, 4))


def _draw_idle_overlay(surface, w: int, h: int, font, big_font,
                       difficulty: str, song: str) -> None:
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    surface.blit(overlay, (0, 0))

    diff_col = _DIFFICULTY_COLOR.get(difficulty, (200, 200, 200))
    diff_lbl = _DIFFICULTY_LABEL.get(difficulty, difficulty.upper())
    cx, cy   = w // 2, h // 2

    t  = big_font.render("PIANO TILES", True, (255, 220, 60))
    surface.blit(t, (cx - t.get_width() // 2, cy - 100))

    s1 = font.render(f"Song: {song}", True, (200, 200, 255))
    surface.blit(s1, (cx - s1.get_width() // 2, cy - 40))

    s2 = font.render("← → change song     1: EASY   2: MEDIUM   3: HARD", True, (180, 180, 180))
    surface.blit(s2, (cx - s2.get_width() // 2, cy))

    s3 = font.render(f"SPACE to start as [{diff_lbl}]", True, diff_col)
    surface.blit(s3, (cx - s3.get_width() // 2, cy + 40))

    s4 = font.render("ESC — leave", True, (120, 120, 120))
    surface.blit(s4, (cx - s4.get_width() // 2, cy + 75))


def _draw_gameover_overlay(surface, w: int, h: int, font, big_font,
                           game: TilesGame, difficulty: str) -> None:
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    surface.blit(overlay, (0, 0))

    diff_col = _DIFFICULTY_COLOR.get(difficulty, (200, 200, 200))
    diff_lbl = _DIFFICULTY_LABEL.get(difficulty, difficulty.upper())
    cx, cy   = w // 2, h // 2

    won = game.mistakes < game.MAX_MISTAKES  # finished the song!
    if won:
        title_t  = "YOU WIN!" if not (game.score == game.best_score and game.score > 0) else "NEW BEST!"
        title_c  = (80, 255, 160)
    else:
        title_t  = "GAME OVER"
        title_c  = (255, 70, 70)

    t  = big_font.render(title_t, True, title_c)
    surface.blit(t, (cx - t.get_width() // 2, cy - 90))

    sc_txt = f"Score: {game.score}     Best: {game.best_score}"
    s1 = font.render(sc_txt, True, (220, 220, 220))
    surface.blit(s1, (cx - s1.get_width() // 2, cy - 20))

    s2 = font.render(f"1: EASY   2: MEDIUM   3: HARD   |   SPACE to replay [{diff_lbl}]",
                     True, diff_col)
    surface.blit(s2, (cx - s2.get_width() // 2, cy + 30))

    s3 = font.render("ESC — leave game", True, (130, 130, 130))
    surface.blit(s3, (cx - s3.get_width() // 2, cy + 65))


# ── main entry point ──────────────────────────────────────────────────────

def start_piano_tiles(
    chosen_instrument: str | None = None,
    resolution_profile=None,
    show_trackers: bool = False,
    hand_model_complexity: int = 1,
    difficulty: str = "easy",
    song: str = "Twinkle Twinkle",
) -> None:
    """
    Start the Piano Tiles game loop.

    difficulty  – "easy" | "medium" | "hard"
    song        – any key in SONG_NAMES
    """
    print(f">>> INICIANDO PIANO TILES [{difficulty.upper()}] — {song}")

    # ── instrument / audio setup ────────────────────────────────────────
    if chosen_instrument:
        select_instrument_by_name(chosen_instrument)
    set_keyboard_expression(127)
    set_keyboard_digital_gain(1.0)

    audio_t = threading.Thread(target=audio_thread_target, daemon=True)
    audio_t.start()

    # ── build game key layout ────────────────────────────────────────────
    piano_keys = _build_game_keys()

    # Override PIANO_KEYS in keyboard module so get_key_index_from_x works
    _kbd_mod.PIANO_KEYS = piano_keys

    # ── game state ───────────────────────────────────────────────────────
    game = TilesGame()
    current_difficulty = difficulty if difficulty in ("easy", "medium", "hard") else "easy"
    current_song_idx   = SONG_NAMES.index(song) if song in SONG_NAMES else 0
    TABLE_Y            = 0.72   # hit-line at 72% from top of frame

    # ── resolution / pygame ──────────────────────────────────────────────
    if resolution_profile:
        DISPLAY_W  = int(resolution_profile["display_width"])
        DISPLAY_H  = int(resolution_profile["display_height"])
        TARGET_FPS = int(resolution_profile["fps"])
    else:
        DISPLAY_W, DISPLAY_H, TARGET_FPS = 1280, 720, 60

    DISPLAY_W, DISPLAY_H, adjusted, _, _ = fit_resolution_to_screen(DISPLAY_W, DISPLAY_H)
    if adjusted:
        print(f">>> Resolução ajustada: {DISPLAY_W}x{DISPLAY_H}")
    LOGICAL_W, LOGICAL_H = DISPLAY_W, DISPLAY_H

    cap              = setup_video_capture(width=LOGICAL_W, height=LOGICAL_H, fps=TARGET_FPS)
    window_display, main_surface, font = setup_pygame_with_scaling(
        logical_width=LOGICAL_W, logical_height=LOGICAL_H,
        display_width=DISPLAY_W, display_height=DISPLAY_H,
        title="Talking Hands — Piano Tiles",
    )
    big_font = pygame.font.SysFont("Arial", 42, bold=True)

    # ── error sounds (must be after pygame.mixer is initialised) ─────────
    _load_error_sounds()

    # ── MediaPipe ────────────────────────────────────────────────────────
    hands = mp.solutions.hands.Hands(
        max_num_hands=2,
        model_complexity=max(0, min(1, int(hand_model_complexity))),
        min_detection_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    _reset_finger_state()

    running = True

    try:
        while running:
            now = time.time()

            # ── events ───────────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

                    elif event.key == pygame.K_SPACE:
                        if game.state in (game.STATE_IDLE, game.STATE_GAME_OVER):
                            _reset_finger_state()
                            game.start(piano_keys,
                                       song=SONG_NAMES[current_song_idx],
                                       difficulty=current_difficulty)

                    # difficulty
                    elif event.key == pygame.K_1:
                        current_difficulty = "easy"
                        print(">>> Dificuldade: EASY")
                    elif event.key == pygame.K_2:
                        current_difficulty = "medium"
                        print(">>> Dificuldade: MEDIUM")
                    elif event.key == pygame.K_3:
                        current_difficulty = "hard"
                        print(">>> Dificuldade: HARD")

                    # song selection (only when idle / game over)
                    elif event.key in (pygame.K_RIGHT, pygame.K_LEFT):
                        if game.state in (game.STATE_IDLE, game.STATE_GAME_OVER):
                            direction = 1 if event.key == pygame.K_RIGHT else -1
                            current_song_idx = (current_song_idx + direction) % len(SONG_NAMES)
                            print(f">>> Música: {SONG_NAMES[current_song_idx]}")

            # ── camera frame ─────────────────────────────────────────────
            ret, frame = cap.read()
            if not ret:
                break

            frame     = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame     = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_surf = pygame.image.frombuffer(
                frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), "RGB"
            )
            main_surface.blit(frame_surf, (0, 0))

            # ── game update ───────────────────────────────────────────────
            game.update(now=now)

            # flush scheduled note-offs
            _flush_note_offs(now)

            # ── draw tile lane overlay (dark bands on the sides/none) ─────
            lane_overlay = pygame.Surface((LOGICAL_W, int(TABLE_Y * LOGICAL_H)), pygame.SRCALPHA)
            lane_overlay.fill((0, 0, 0, 60))
            main_surface.blit(lane_overlay, (0, 0))

            # ── draw tiles ────────────────────────────────────────────────
            _draw_tiles(main_surface, game, LOGICAL_W, LOGICAL_H, TABLE_Y, now)

            # ── draw piano keys at bottom ─────────────────────────────────
            _draw_piano_keys(main_surface, piano_keys, LOGICAL_W, LOGICAL_H, TABLE_Y, now)

            # ── hand tracking ─────────────────────────────────────────────
            results = hands.process(frame_rgb)
            if results.multi_hand_landmarks:
                for idx, lm in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label
                    _process_taps(lbl, lm.landmark, piano_keys, TABLE_Y, game, now)

                    if show_trackers:
                        for fid in ACTIVE_FINGERS:
                            tip = lm.landmark[fid]
                            cx  = int(tip.x * LOGICAL_W)
                            cy  = int(tip.y * LOGICAL_H)
                            pygame.draw.circle(main_surface, (255, 255, 0), (cx, cy), 6, 2)

            # ── HUD ───────────────────────────────────────────────────────
            if game.state == game.STATE_PLAYING:
                _draw_hud(main_surface, LOGICAL_W, LOGICAL_H,
                          font, big_font, game, current_difficulty, now,
                          song=SONG_NAMES[current_song_idx])

            elif game.state == game.STATE_IDLE:
                _draw_idle_overlay(main_surface, LOGICAL_W, LOGICAL_H,
                                   font, big_font, current_difficulty,
                                   SONG_NAMES[current_song_idx])

            elif game.state == game.STATE_GAME_OVER:
                _draw_gameover_overlay(main_surface, LOGICAL_W, LOGICAL_H,
                                       font, big_font, game, current_difficulty)

            window_display.blit(main_surface, (0, 0))
            pygame.display.flip()

    except Exception as exc:
        print(f"Erro Runtime (piano tiles): {exc}")
        import traceback
        traceback.print_exc()

    finally:
        try:
            hands.close()
        except Exception:
            pass
        cap.release()
        pygame.quit()
        audio_queue.put(None)
        print(">>> Piano Tiles Encerrado.")
