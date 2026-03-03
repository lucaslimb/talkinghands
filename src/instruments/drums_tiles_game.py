"""
Drum Tiles game mode.

Coloured tiles fly from the screen edges toward the corresponding drum pads.
The player must hit each drum as its tile arrives.

Entry point: start_drums_tiles(...)
"""

import cv2
import mediapipe as mp
import threading
import time
import sys
import os
import math
import random
import pygame
from pathlib import Path
from typing import Optional

FILE_PATH    = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# ── drums infrastructure ──────────────────────────────────────────────────
import src.instruments.drums as _drums_mod
from src.instruments.drums import (
    configure_drum_kit,
    apply_drum_note_profile,
    audio_queue,
    hands_state,
    reset_hands_state,
    check_collision,
    VELOCITY_THRESHOLD,
    TOUCH_VELOCITY,
    DRUM_MIN_VELOCITY,
    DRUM_MIN_HIT_INTERVAL_SEC,
    MIN_REHIT_PIXELS,
    DRUMS_INSTRUMENT_ELEMENT_PRESETS,
    DRUMS_INSTRUMENT_REPLACE_BASE,
    DRUM_ELEMENT_LIBRARY,
    FPSTracker,
)

# Live DRUM_KIT reference
def _kit() -> list:
    return _drums_mod.DRUM_KIT

# Colour map shared with genius game
from src.instruments.drums_game import (
    _ELEMENT_GAME_COLORS,
    _PALETTE_FALLBACK,
    _merge_elements_for_difficulty,
    DIFFICULTY_EXTRA_ELEMENTS,
)

from src.instruments.common import (
    init_fluidsynth,
    load_single_soundfont,
    setup_video_capture,
    setup_pygame_with_scaling,
    fit_resolution_to_screen,
    draw_text,
)
from src.engines.game_drum_tiles import DrumTilesGame, SONG_NAMES
from src.config import settings
import numpy as np
import fluidsynth

# ── element colour helper ─────────────────────────────────────────────────

def _elem_color(key: str, idx: int = 0) -> tuple[int, int, int]:
    if key in _ELEMENT_GAME_COLORS:
        return _ELEMENT_GAME_COLORS[key]
    return _PALETTE_FALLBACK[idx % len(_PALETTE_FALLBACK)]


# ── error sounds ──────────────────────────────────────────────────────────
_ERROR_SOUNDS: list[pygame.mixer.Sound] = []
_error_channel: Optional[pygame.mixer.Channel] = None
_last_error_ts: float = 0.0
_ERROR_COOLDOWN = 0.3


def _load_error_sounds() -> None:
    global _error_channel
    if _ERROR_SOUNDS:
        return
    sounds_dir = PROJECT_ROOT / "assets" / "sounds"
    for f in sorted(sounds_dir.glob("error_*.mp3")):
        try:
            snd = pygame.mixer.Sound(str(f))
            snd.set_volume(0.3)
            _ERROR_SOUNDS.append(snd)
        except Exception as e:
            print(f"[drum-tiles] Aviso: {f.name}: {e}")
    if _ERROR_SOUNDS:
        _error_channel = pygame.mixer.Channel(6)


def _play_error_sound(now: float) -> None:
    global _last_error_ts
    if not _ERROR_SOUNDS or _error_channel is None:
        return
    if now - _last_error_ts < _ERROR_COOLDOWN:
        return
    _last_error_ts = now
    _error_channel.stop()
    _error_channel.play(random.choice(_ERROR_SOUNDS))


# ── difficulty UI constants ───────────────────────────────────────────────
_DIFF_COLOR = {"easy": (80, 220, 100), "medium": (255, 200, 50), "hard": (255, 70, 70)}
_DIFF_LABEL = {"easy": "EASY", "medium": "MEDIUM", "hard": "HARD"}


# ── hit detection ─────────────────────────────────────────────────────────

def _process_hand_tiles(
    label: str,
    landmarks,
    w: int,
    h: int,
    game: DrumTilesGame,
    now: float,
    show_trackers: bool,
    surface,
) -> None:
    """
    Velocity-based collision detection for drum tiles.
    On hit: calls game.player_hit; plays audio on score, error sound on no_tile.
    """
    ref    = landmarks[4]   # thumb tip (like the genius game)
    ref_x, ref_y = ref.x, ref.y

    state   = hands_state[label]
    prev_y  = state["prev_y"]
    can_hit = state["can_hit"]
    dy      = ref_y - prev_y

    hit_drum = None
    for drum in _kit():
        if drum.get("foot_only", False):
            continue
        if check_collision(ref_x, ref_y, drum):
            hit_drum = drum
            break

    drum_center_y = hit_drum["pos"][1] if hit_drum else 0.0
    if hit_drum is None or dy < -VELOCITY_THRESHOLD:
        can_hit = True
    else:
        if ref_y < drum_center_y and dy < -VELOCITY_THRESHOLD:
            can_hit = True

    cursor_pos    = (int(ref_x * w), int(ref_y * h))
    cursor_color  = (100, 100, 100)
    cursor_radius = 10

    if hit_drum is not None and can_hit:
        is_moving_down = dy > VELOCITY_THRESHOLD
        moved_enough   = True
        if state["last_hit_pos"] is not None and state["last_hit_drum"] == hit_drum["id"]:
            lx, ly = state["last_hit_pos"]
            moved_enough = (
                (cursor_pos[0] - lx) ** 2 + (cursor_pos[1] - ly) ** 2
                >= MIN_REHIT_PIXELS ** 2
            )

        if (is_moving_down and moved_enough and
                (now - float(hit_drum.get("last_hit", 0))) >= DRUM_MIN_HIT_INTERVAL_SEC):

            velocity  = int(min(max((dy - TOUCH_VELOCITY) * 10000, DRUM_MIN_VELOCITY), 127))
            elem_key  = hit_drum.get("element_key", "")
            result    = game.player_hit(elem_key, now=now)

            if result in ("perfect", "good"):
                audio_queue.put((hit_drum["note"], velocity))
                hit_drum["last_hit"] = now
                can_hit = False
                cursor_color  = (0, 255, 100)
                cursor_radius = 15
            elif result == "no_tile":
                _play_error_sound(now)
                hit_drum["last_hit"] = now
                can_hit = False
                cursor_color  = (255, 80, 80)
                cursor_radius = 12
            else:
                # "ignored" = bad timing
                hit_drum["last_hit"] = now
                can_hit = False
                cursor_color  = (255, 180, 0)

            state["last_hit_pos"]  = cursor_pos
            state["last_hit_drum"] = hit_drum["id"]

    state["prev_y"]  = ref_y
    state["can_hit"] = can_hit

    if show_trackers:
        pygame.draw.circle(surface, cursor_color, cursor_pos, cursor_radius)
        pygame.draw.circle(surface, (255, 255, 255), cursor_pos, cursor_radius + 2, 2)


# ── tile renderer ─────────────────────────────────────────────────────────
_START_SCALE = 3.5   # shrinking circle starts this many times larger than the pad


def _draw_tiles(surface, w: int, h: int, game: DrumTilesGame, now: float) -> None:
    """
    Each tile is a large shrinking ellipse centred on its target pad.
    Progress 0 → starts at _START_SCALE * pad size, transparent.
    Progress 1 → exactly matches pad size, fully opaque ring.
    The player should hit when the ring coincides with the static pad outline.
    """
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)

    for tile in game.tiles:
        col     = _elem_color(tile.element_key)
        p       = game.tile_progress(tile, now)
        pad_xpx = int(tile.pad_x_norm * w)
        pad_ypx = int(tile.pad_y_norm * h)
        rx_px   = max(10, int(tile.pad_rx_norm * w))
        ry_px   = max(6,  int(tile.pad_ry_norm * h))
        pad_rect = pygame.Rect(pad_xpx - rx_px, pad_ypx - ry_px, rx_px * 2, ry_px * 2)

        # ── hit flash: brief green fill at pad size ────────────────────────
        if tile.state == "hit":
            age   = now - tile.arrive_time
            alpha = max(0, min(255, int(230 * (1.0 - age / 0.45))))
            pygame.draw.ellipse(overlay, (80, 255, 140, alpha), pad_rect)
            pygame.draw.ellipse(overlay, (220, 255, 220, min(alpha, 200)), pad_rect, 3)
            continue

        # ── miss flash: brief red fill at pad size ─────────────────────────
        if tile.state == "miss":
            age   = now - tile.arrive_time
            alpha = max(0, min(255, int(200 * (1.0 - age / 0.5))))
            pygame.draw.ellipse(overlay, (255, 50, 50, alpha), pad_rect)
            continue

        # ── active: shrinking ring ─────────────────────────────────────────
        p_clamped = max(0.0, min(1.0, p))

        # scale: linearly goes from START_SCALE → 1.0
        scale = _START_SCALE - (_START_SCALE - 1.0) * p_clamped
        crx   = max(rx_px, int(rx_px * scale))
        cry   = max(ry_px, int(ry_px * scale))
        ring_rect = pygame.Rect(pad_xpx - crx, pad_ypx - cry, crx * 2, cry * 2)

        # ring fades in as it approaches: at p=0 alpha~15, at p=1 alpha~220
        ring_alpha = max(0, min(255, int(220 * (p_clamped * 0.9 + 0.1))))
        # faint fill so the pad underneath stays visible
        fill_alpha = max(0, min(255, int(30 * p_clamped)))
        # ring gets thinner as it converges
        thickness  = max(2, int(5 * (1.0 - p_clamped) + 2))

        # extra pulse when in hit window
        in_zone = p >= 0.82
        if in_zone:
            pulse      = 0.5 + 0.5 * math.sin(now * 14)
            ring_alpha = min(255, ring_alpha + int(30 * pulse))
            thickness  = max(2, thickness + int(2 * pulse))

        pygame.draw.ellipse(overlay, (*col, fill_alpha), ring_rect)
        pygame.draw.ellipse(overlay, (*col, ring_alpha), ring_rect, thickness)

    surface.blit(overlay, (0, 0))


# ── pad renderer (static target rings the shrinking circle collapses onto) ──

def _draw_pads(surface, w: int, h: int, game: DrumTilesGame, now: float) -> None:
    """
    Draw the static target outlines at exact pad size.
    These are the "bullseye" the shrinking ring collapses onto.
    They pulse brighter when the tile enters the hit window.
    """
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)

    for drum in _kit():
        k = drum.get("element_key", "")
        if drum.get("foot_only", False) or not k:
            continue
        col = _elem_color(k)
        cx  = int(drum["pos"][0] * w)
        cy  = int(drum["pos"][1] * h)
        rx  = int(drum["axes"][0] * w)
        ry  = int(drum["axes"][1] * h)
        rect = pygame.Rect(cx - rx, cy - ry, rx * 2, ry * 2)

        in_zone = any(
            t.state == "active" and t.element_key == k
            and game.tile_progress(t, now) >= 0.82
            for t in game.tiles
        )

        if in_zone:
            # bright pulsing target so player knows when to hit
            pulse   = 0.5 + 0.5 * math.sin(now * 12)
            b_alpha = max(0, min(255, int(160 + 90 * pulse)))
            pygame.draw.ellipse(overlay, (*col, 50), rect)
            pygame.draw.ellipse(overlay, (255, 255, 255, b_alpha), rect, 3)
        else:
            # dim static marker
            pygame.draw.ellipse(overlay, (*col, 15), rect)
            pygame.draw.ellipse(overlay, (*col, 70), rect, 2)

    surface.blit(overlay, (0, 0))


# ── HUD ───────────────────────────────────────────────────────────────────

def _draw_hud(
    surface, w: int, h: int, font, big_font,
    game: DrumTilesGame, difficulty: str, now: float, song: str = "",
) -> None:
    bar_h = 72
    strip = pygame.Surface((w, bar_h), pygame.SRCALPHA)
    strip.fill((0, 0, 0, 160))
    surface.blit(strip, (0, 0))

    diff_col = _DIFF_COLOR.get(difficulty, (200, 200, 200))
    diff_lbl = _DIFF_LABEL.get(difficulty, difficulty.upper())

    # song name centred, top
    if song:
        t = big_font.render(song, True, (255, 220, 60))
        surface.blit(t, (w // 2 - t.get_width() // 2, 4))

    # subtitle
    sub = font.render("DRUM TILES", True, (160, 140, 80))
    surface.blit(sub, (w // 2 - sub.get_width() // 2, 50))

    # difficulty badge – left
    ds = font.render(diff_lbl, True, diff_col)
    ph = ds.get_height() + 8
    pw = ds.get_width()  + 16
    pill = pygame.Surface((pw, ph), pygame.SRCALPHA)
    pill.fill((*diff_col, 40))
    pygame.draw.rect(pill, (*diff_col, 180), pill.get_rect(), 2)
    py = bar_h // 2 - ph // 2
    surface.blit(pill, (14, py))
    surface.blit(ds,   (22, py + 4))

    # score – right
    draw_text(surface, f"Score: {game.score}",      (w - 210, 8),  font, (255, 255, 255))
    if game.best_score > 0:
        draw_text(surface, f"Best: {game.best_score}", (w - 210, 28), font, (200, 200, 200))

    # lives (hearts) – right of diff badge
    lx = pw + 28
    for i in range(game.MAX_MISTAKES):
        alive = i < game.lives_remaining
        col   = (255, 80, 100) if alive else (60, 60, 60)
        pygame.draw.circle(surface, col, (lx + i * 22, bar_h // 2), 7)
        if alive:
            pygame.draw.circle(surface, (255, 160, 180), (lx + i * 22, bar_h // 2), 7, 2)

    # result flash – top right
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

    # combo badge – below bar, left
    if game.combo >= 3:
        ctxt = f"x{game.combo} COMBO"
        ccol = (255, 230, 60) if game.combo < 10 else (255, 100, 255)
        cs   = font.render(ctxt, True, ccol)
        surface.blit(cs, (14, bar_h + 6))

    # progress bar – bottom of strip
    pw2 = int(w * game.progress)
    pygame.draw.rect(surface, (50, 50, 50), (0, bar_h - 4, w, 4))
    pygame.draw.rect(surface, diff_col,     (0, bar_h - 4, pw2, 4))


def _draw_idle_overlay(
    surface, w: int, h: int, font, big_font,
    difficulty: str, song: str,
) -> None:
    ov = pygame.Surface((w, h), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 160))
    surface.blit(ov, (0, 0))

    diff_col = _DIFF_COLOR.get(difficulty, (200, 200, 200))
    diff_lbl = _DIFF_LABEL.get(difficulty, difficulty.upper())
    cx, cy   = w // 2, h // 2

    t = big_font.render("DRUM TILES", True, (255, 220, 60))
    surface.blit(t, (cx - t.get_width() // 2, cy - 100))

    s1 = font.render(f"Song: {song}", True, (200, 200, 255))
    surface.blit(s1, (cx - s1.get_width() // 2, cy - 40))

    s2 = font.render("← → change song     1: EASY   2: MEDIUM   3: HARD", True, (180, 180, 180))
    surface.blit(s2, (cx - s2.get_width() // 2, cy))

    s3 = font.render(f"SPACE to start as [{diff_lbl}]", True, diff_col)
    surface.blit(s3, (cx - s3.get_width() // 2, cy + 40))

    s4 = font.render("ESC — leave", True, (120, 120, 120))
    surface.blit(s4, (cx - s4.get_width() // 2, cy + 75))


def _draw_gameover_overlay(
    surface, w: int, h: int, font, big_font,
    game: DrumTilesGame, difficulty: str, song: str = "",
) -> None:
    ov = pygame.Surface((w, h), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 160))
    surface.blit(ov, (0, 0))

    diff_col = _DIFF_COLOR.get(difficulty, (200, 200, 200))
    diff_lbl = _DIFF_LABEL.get(difficulty, difficulty.upper())
    cx, cy   = w // 2, h // 2

    won = game.mistakes < game.MAX_MISTAKES
    if won:
        title_t = "NEW BEST!" if (game.score == game.best_score and game.score > 0) else "YOU WIN!"
        title_c = (80, 255, 160)
    else:
        title_t = "GAME OVER"
        title_c = (255, 70, 70)

    t = big_font.render(title_t, True, title_c)
    surface.blit(t, (cx - t.get_width() // 2, cy - 100))

    sc = font.render(f"Score: {game.score}     Best: {game.best_score}", True, (220, 220, 220))
    surface.blit(sc, (cx - sc.get_width() // 2, cy - 40))

    if song:
        ss = font.render(f"◄  {song}  ►", True, (200, 200, 255))
        surface.blit(ss, (cx - ss.get_width() // 2, cy))

    s2 = font.render(f"1: EASY   2: MEDIUM   3: HARD   |   SPACE to replay [{diff_lbl}]",
                     True, diff_col)
    surface.blit(s2, (cx - s2.get_width() // 2, cy + 42))

    s3 = font.render("ESC — leave game", True, (130, 130, 130))
    surface.blit(s3, (cx - s3.get_width() // 2, cy + 77))


# ── main entry point ──────────────────────────────────────────────────────

def start_drums_tiles(
    chosen_instrument=None,
    resolution_profile=None,
    show_trackers: bool = False,
    drum_model: str = "default",
    drums_elements=None,
    hand_model_complexity: int = 1,
    difficulty: str = "easy",
    song: str = "Basic Beat",
) -> None:
    """
    Start the Drum Tiles game.

    difficulty – "easy" | "medium" | "hard"
    song       – any key in SONG_NAMES
    """
    print(f">>> INICIANDO DRUM TILES [{difficulty.upper()}] — {song}")

    # ── instrument / kit setup ────────────────────────────────────────────
    apply_drum_note_profile(chosen_instrument)

    norm_model  = str(drum_model).strip().lower()
    replace_base = False
    base_elems   = drums_elements

    if not replace_base and base_elems is None and chosen_instrument in DRUMS_INSTRUMENT_ELEMENT_PRESETS:
        preset = DRUMS_INSTRUMENT_ELEMENT_PRESETS.get(chosen_instrument, [])
        base_elems = [e for e in preset if e in DRUM_ELEMENT_LIBRARY]
        if chosen_instrument in DRUMS_INSTRUMENT_REPLACE_BASE:
            replace_base = True

    def _apply_kit(diff: str) -> list[str]:
        merged = _merge_elements_for_difficulty(base_elems, diff)
        configure_drum_kit(
            norm_model,
            drums_elements=merged,
            replace_base=replace_base,
            instrument_name=chosen_instrument,
        )
        avail: list[str] = []
        seen:  set[str]  = set()
        for d in _kit():
            k = d.get("element_key", "")
            if not d.get("foot_only", False) and k and k not in seen:
                avail.append(k)
                seen.add(k)
        return avail

    current_difficulty = difficulty if difficulty in ("easy", "medium", "hard") else "easy"
    _apply_kit(current_difficulty)

    # ── audio ─────────────────────────────────────────────────────────────
    FIXED_SF2_PATH     = settings.SF2_PATHS["drums"]
    fs_local, _        = init_fluidsynth(driver="dsound")
    POLYPHONY_CHANNELS = 16
    drum_sfid          = -1

    if fs_local is not None:
        drum_sfid = load_single_soundfont(fs_local, "drums", FIXED_SF2_PATH)
        if drum_sfid != -1:
            for i in range(POLYPHONY_CHANNELS):
                fs_local.program_select(i, drum_sfid, 128, 0)

    if chosen_instrument and drum_sfid != -1 and chosen_instrument in settings.INSTRUMENTS:
        _, bank, preset = settings.INSTRUMENTS[chosen_instrument]
        for i in range(POLYPHONY_CHANNELS):
            fs_local.program_select(i, drum_sfid, bank, preset)

    def _audio_thread():
        while True:
            item = audio_queue.get()
            if item is None:
                break
            note, velocity = item
            ch = int(np.random.randint(0, POLYPHONY_CHANNELS))
            fs_local.noteon(ch, note, velocity)

    audio_t = threading.Thread(target=_audio_thread, daemon=True)
    audio_t.start()

    # ── resolution / pygame ───────────────────────────────────────────────
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

    cap = setup_video_capture(width=LOGICAL_W, height=LOGICAL_H, fps=TARGET_FPS)
    window_display, main_surface, font = setup_pygame_with_scaling(
        logical_width=LOGICAL_W, logical_height=LOGICAL_H,
        display_width=DISPLAY_W, display_height=DISPLAY_H,
        title="Talking Hands — Drum Tiles",
    )
    big_font = pygame.font.SysFont("Arial", 42, bold=True)

    # error sounds (after pygame.mixer init)
    _load_error_sounds()

    # ── game state ────────────────────────────────────────────────────────
    game = DrumTilesGame()
    current_song_idx = SONG_NAMES.index(song) if song in SONG_NAMES else 0

    # ── MediaPipe ─────────────────────────────────────────────────────────
    hands = mp.solutions.hands.Hands(
        max_num_hands=2,
        model_complexity=max(0, min(1, int(hand_model_complexity))),
        min_detection_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    reset_hands_state()

    running = True

    try:
        while running:
            now = time.time()

            # ── events ────────────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

                    elif event.key == pygame.K_SPACE:
                        if game.state in (game.STATE_IDLE, game.STATE_GAME_OVER):
                            _apply_kit(current_difficulty)
                            reset_hands_state()
                            game.start(
                                _kit(),
                                song=SONG_NAMES[current_song_idx],
                                difficulty=current_difficulty,
                            )

                    elif event.key == pygame.K_1:
                        current_difficulty = "easy"
                    elif event.key == pygame.K_2:
                        current_difficulty = "medium"
                    elif event.key == pygame.K_3:
                        current_difficulty = "hard"

                    elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        if game.state in (game.STATE_IDLE, game.STATE_GAME_OVER):
                            d = 1 if event.key == pygame.K_RIGHT else -1
                            current_song_idx = (current_song_idx + d) % len(SONG_NAMES)
                            print(f">>> Música: {SONG_NAMES[current_song_idx]}")

            # ── camera frame ──────────────────────────────────────────────
            ret, frame = cap.read()
            if not ret:
                break

            frame      = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame      = cv2.flip(frame, 1)
            frame_rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_surf = pygame.image.frombuffer(
                frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), "RGB"
            )
            main_surface.blit(frame_surf, (0, 0))

            # ── game tick ─────────────────────────────────────────────────
            game.update(now=now)

            # ── draw pads ─────────────────────────────────────────────────
            _draw_pads(main_surface, LOGICAL_W, LOGICAL_H, game, now)

            # ── draw tiles ────────────────────────────────────────────────
            _draw_tiles(main_surface, LOGICAL_W, LOGICAL_H, game, now)

            # ── hand tracking ─────────────────────────────────────────────
            results = hands.process(frame_rgb)
            if results.multi_hand_landmarks:
                for idx, lm in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label
                    _process_hand_tiles(
                        lbl, lm.landmark,
                        LOGICAL_W, LOGICAL_H,
                        game, now, show_trackers, main_surface,
                    )

            # ── overlays ──────────────────────────────────────────────────
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
                                       font, big_font, game, current_difficulty,
                                       song=SONG_NAMES[current_song_idx])

            window_display.blit(main_surface, (0, 0))
            pygame.display.flip()

    except Exception as exc:
        print(f"Erro Runtime (drum tiles): {exc}")
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
        print(">>> Drum Tiles Encerrado.")
