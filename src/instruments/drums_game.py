"""
Genius-style drum game mode.

Wraps the drums infrastructure (DRUM_KIT, audio_queue, hand tracking)
around GeniusGame to produce a Simon-says / Genius style challenge.

Entry point: start_drums_game(...)
"""

import cv2
import mediapipe as mp
import threading
import time
import sys
import os
import math
import pygame
from pathlib import Path

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# ── drums infrastructure (audio, kit, tracking helpers) ──────────────────
# Import the module itself so we always see the current DRUM_KIT reference
# (configure_drum_kit *reassigns* the global, so a direct ``from … import``
# would leave us with a stale list).
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

# Convenience accessor – always reads the live reference
def _kit() -> list:
    return _drums_mod.DRUM_KIT
from src.instruments.common import (
    init_fluidsynth,
    load_single_soundfont,
    setup_video_capture,
    setup_pygame_with_scaling,
    fit_resolution_to_screen,
    draw_text,
)
from src.engines.game_genius import GeniusGame
from src.config import settings

import fluidsynth

# ── per-element game colours (Genius style) ──────────────────────────────
_ELEMENT_GAME_COLORS: dict[str, tuple[int, int, int]] = {
    "crash":      (255,  70,  70),
    "ride":       ( 70, 150, 255),
    "tom_hi":     (255, 210,  50),
    "tom_low":    ( 70, 230, 120),
    "hihat":      (255, 130,   0),
    "snare":      (200,  80, 255),
    "floor":      (  0, 210, 200),
    "kick":       (255,  60, 180),
    "open_hh":    (255, 180,   0),
    "splash":     (255, 100, 100),
    "china":      (100, 255, 180),
    "tom_mid":    (180, 255,  80),
    "rimshot":    (255, 255, 100),
    "snare_alt":  (160, 100, 255),
    "kick_alt":   (255, 100, 130),
    "hh_pedal":   (200, 200, 200),
    "cowbell":    (255, 200, 100),
    "clap":       (255, 130, 200),
    "tamb":       (255, 160,  60),
    "ride_bell":  ( 80, 220, 240),
    "crash2":     (255,  90,  90),
    "ride2":      ( 90, 160, 255),
    "vibra_slap": (220, 220,  60),
    "shaker":     (180, 255, 150),
    "cabasa":     (255, 150, 100),
    "maracas":    (150, 255, 200),
    "bongo_hi":   (255, 120,  80),
    "bongo_mid":  (200, 180, 255),
    "bongo_lo":   (100, 240, 180),
    "bongo_deep": ( 60, 180, 255),
    "conga_hi":   (255, 200,  60),
    "conga_mid":  (200, 255, 100),
    "conga_lo":   ( 80, 200, 255),
    "timbale_hi": (255, 100, 200),
    "timbale_lo": (150, 100, 255),
}

# Fallback colour palette generated from hashed index
_PALETTE_FALLBACK = [
    (255, 80, 80), (80, 200, 255), (80, 255, 130), (255, 220, 50),
    (200, 80, 255), (255, 130, 0), (0, 210, 200), (255, 60, 180),
]

# ── difficulty configuration ──────────────────────────────────────────────
# Extra elements added on top of the base kit per difficulty level.
# 'medium' adds 3, 'hard' adds 6 (always a superset of medium's extras).
DIFFICULTY_EXTRA_ELEMENTS: dict[str, list[str]] = {
    "easy":   [],
    "medium": ["tom_mid", "open_hh", "cowbell"],
    "hard":   ["tom_mid", "open_hh", "cowbell", "splash", "clap", "rimshot"],
}

_DIFFICULTY_COLOR: dict[str, tuple[int, int, int]] = {
    "easy":   ( 80, 220, 100),
    "medium": (255, 200,  50),
    "hard":   (255,  70,  70),
}

_DIFFICULTY_LABEL: dict[str, str] = {
    "easy":   "EASY",
    "medium": "MEDIUM",
    "hard":   "HARD",
}


def _element_color(element_key: str, index: int = 0) -> tuple[int, int, int]:
    """Return a stable bright colour for the given drum element."""
    if element_key in _ELEMENT_GAME_COLORS:
        return _ELEMENT_GAME_COLORS[element_key]
    return _PALETTE_FALLBACK[index % len(_PALETTE_FALLBACK)]


def _merge_elements_for_difficulty(
    base_elements: list[str] | None,
    difficulty: str,
) -> list[str] | None:
    """
    Merge the user-supplied base element list with the difficulty extras.
    Returns None when base_elements is None (let configure_drum_kit use its own defaults).
    When base_elements is provided, appends the difficulty extras (deduped).
    """
    extras = DIFFICULTY_EXTRA_ELEMENTS.get(difficulty, [])
    if not extras:
        return base_elements   # easy or empty extras – nothing to add

    if base_elements is None:
        # No explicit base – return just the extras so configure_drum_kit
        # adds them on top of the fixed default layout.
        return list(extras)

    merged = list(base_elements)
    seen   = set(merged)
    for e in extras:
        if e not in seen and e in DRUM_ELEMENT_LIBRARY:
            merged.append(e)
            seen.add(e)
    return merged


# ── per-element feedback state (used by game renderer) ───────────────────
# Maps element_key → {"result": "correct"|"wrong", "ts": float}
_HIT_FEEDBACK: dict[str, dict] = {}


def _record_feedback(element_key: str, result: str) -> None:
    _HIT_FEEDBACK[element_key] = {"result": result, "ts": time.time()}


def _clear_old_feedback(ttl: float = 0.25) -> None:
    now = time.time()
    expired = [k for k, v in _HIT_FEEDBACK.items() if now - v["ts"] > ttl]
    for k in expired:
        del _HIT_FEEDBACK[k]


# ── game hit detection (replaces the free-play process_hand) ─────────────

def _process_hand_game(
    label: str,
    landmarks,
    w: int,
    h: int,
    screen,
    game: GeniusGame,
    show_trackers: bool = False,
) -> None:
    """Detect hand hits and route them through game logic."""
    ref = landmarks[4]      # fingertip landmark
    ref_x, ref_y = ref.x, ref.y

    state  = hands_state[label]
    prev_y = state["prev_y"]
    can_hit = state["can_hit"]
    dy = ref_y - prev_y

    # find colliding drum
    hit_drum = None
    for drum in _kit():
        if drum.get("foot_only", False):
            continue
        if check_collision(ref_x, ref_y, drum):
            hit_drum = drum
            break

    # reset can_hit when hand leaves or moves up
    drum_center_y = hit_drum["pos"][1] if hit_drum else 0.0
    if hit_drum is None or dy < -VELOCITY_THRESHOLD:
        can_hit = True
    else:
        if ref_y < drum_center_y and dy < -VELOCITY_THRESHOLD:
            can_hit = True

    cursor_pos    = (int(ref_x * w), int(ref_y * h))
    cursor_color  = (100, 100, 100)
    cursor_radius = 10

    if hit_drum is not None:
        if can_hit:
            cursor_color = (255, 255, 0)

        is_moving_down = dy > VELOCITY_THRESHOLD
        moved_enough   = True
        if state["last_hit_pos"] is not None and state["last_hit_drum"] == hit_drum["id"]:
            lx, ly  = state["last_hit_pos"]
            moved_enough = (
                (cursor_pos[0] - lx) ** 2 + (cursor_pos[1] - ly) ** 2
                >= MIN_REHIT_PIXELS ** 2
            )

        now = time.time()
        if (can_hit and is_moving_down and moved_enough and
                (now - float(hit_drum.get("last_hit", 0))) >= DRUM_MIN_HIT_INTERVAL_SEC):

            velocity    = int(min(max((dy - TOUCH_VELOCITY) * 10000, DRUM_MIN_VELOCITY), 127))
            elem_key    = hit_drum.get("element_key", "")
            result      = game.player_hit(elem_key, now=now)

            if result in ("correct", "wrong"):
                audio_queue.put((hit_drum["note"], velocity))
                hit_drum["last_hit"] = now
                can_hit = False
                _record_feedback(elem_key, result)
                cursor_color  = (0, 255, 100) if result == "correct" else (255, 50, 50)
                cursor_radius = 15

            state["last_hit_pos"]  = cursor_pos
            state["last_hit_drum"] = hit_drum["id"]

    state["prev_y"]  = ref_y
    state["can_hit"] = can_hit

    if show_trackers:
        pygame.draw.circle(screen, cursor_color, cursor_pos, cursor_radius)
        pygame.draw.circle(screen, (255, 255, 255), cursor_pos, cursor_radius + 2, 2)


# ── game-mode drum renderer ───────────────────────────────────────────────

def _draw_game_drums(
    surface,
    w: int,
    h: int,
    font,
    game: GeniusGame,
    indexed_elements: list[tuple[int, str]],    # (index, element_key)
) -> None:
    """
    Draw drum pads with Genius colours.
    Highlighted element (during DEMO) pulses brightly.
    Player-feedback flashes green/red.
    """
    now    = time.time()
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    _clear_old_feedback()

    for drum in _kit():
        elem_key  = drum.get("element_key", "")
        idx       = next((i for i, k in indexed_elements if k == elem_key), 0)
        base_color = _element_color(elem_key, idx)

        cx_px = int(drum["pos"][0] * w)
        cy_px = int(drum["pos"][1] * h)
        rx_px = int(drum["axes"][0] * w)
        ry_px = int(drum["axes"][1] * h)

        rect = pygame.Rect(cx_px - rx_px, cy_px - ry_px, rx_px * 2, ry_px * 2)

        # ── determine how to draw this pad ───────────────────────────────
        is_highlight = (game.highlighted_element == elem_key)
        feedback     = _HIT_FEEDBACK.get(elem_key)
        is_correct_fb = feedback and feedback["result"] == "correct"
        is_wrong_fb   = feedback and feedback["result"] == "wrong"

        if is_highlight:
            # pulsing bright fill
            pulse = 0.5 + 0.5 * math.sin((now * 8))
            alpha = int(180 + 70 * pulse)
            fill_color  = (*base_color, alpha)
            border_w    = 4
            border_color = (255, 255, 255)
        elif is_correct_fb:
            fill_color  = (0, 255, 100, 210)
            border_w    = 4
            border_color = (200, 255, 200)
        elif is_wrong_fb:
            fill_color  = (255, 50, 50, 210)
            border_w    = 4
            border_color = (255, 200, 200)
        else:
            # dim normal state
            fill_color  = (*base_color, 35)
            border_w    = 2
            border_color = tuple(max(0, c - 60) for c in base_color)

        # draw
        if drum["shape"] == "rect":
            pygame.draw.rect(overlay, fill_color, rect)
            pygame.draw.rect(overlay, (*border_color, 220), rect, border_w)
        else:
            pygame.draw.ellipse(overlay, fill_color, rect)
            pygame.draw.ellipse(overlay, (*border_color, 220), rect, border_w)

    surface.blit(overlay, (0, 0))


def _draw_game_hud(
    surface,
    w: int,
    h: int,
    font,
    big_font,
    game: GeniusGame,
    indexed_elements: list[tuple[int, str]],
    difficulty: str = "easy",
) -> None:
    """Draw score, round, sequence progress, timer and state banners."""
    now = time.time()

    # ── top strip (semi-transparent) ─────────────────────────────────────
    strip = pygame.Surface((w, 70), pygame.SRCALPHA)
    strip.fill((0, 0, 0, 140))
    surface.blit(strip, (0, 0))

    # title (centered horizontally)
    title_surf = big_font.render("GENIUS DRUMS", True, (255, 220, 60))
    surface.blit(title_surf, (w // 2 - title_surf.get_width() // 2, 8))

    # score
    score_text = f"Score: {game.score}"
    draw_text(surface, score_text, (w - 200, 10), font, (255, 255, 255))
    if game.best_score > 0:
        best_text = f"Best:  {game.best_score}"
        draw_text(surface, best_text, (w - 200, 32), font, (200, 200, 200))

    # ── difficulty badge (left, vertically centered in the 70 px strip) ───
    diff_col   = _DIFFICULTY_COLOR.get(difficulty, (200, 200, 200))
    diff_label = _DIFFICULTY_LABEL.get(difficulty, difficulty.upper())
    diff_surf  = font.render(diff_label, True, diff_col)
    pill_w = diff_surf.get_width() + 16
    pill_h = diff_surf.get_height() + 8
    pill = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
    pill.fill((*diff_col, 40))
    pygame.draw.rect(pill, (*diff_col, 180), pill.get_rect(), 2)
    pill_x = 14
    pill_y = 35 - pill_h // 2          # vertical center of 70px strip
    surface.blit(pill, (pill_x, pill_y))
    surface.blit(diff_surf, (pill_x + 8, pill_y + 4))

    # ── sequence progress dots ────────────────────────────────────────────
    if game.state in (game.STATE_WAIT_INPUT, game.STATE_FEEDBACK, game.STATE_DEMO):
        seq_len   = game.sequence_length
        dot_r     = 8
        spacing   = dot_r * 3
        total_w   = seq_len * spacing
        start_x   = w // 2 - total_w // 2

        for i, elem_key in enumerate(game.sequence):
            cx = start_x + i * spacing + dot_r
            cy = 58

            if (game.state == game.STATE_WAIT_INPUT or game.state == game.STATE_FEEDBACK):
                if i < game.player_index:
                    # completed hit — solid white
                    pygame.draw.circle(surface, (220, 220, 220), (cx, cy), dot_r)
                    pygame.draw.circle(surface, (255, 255, 255), (cx, cy), dot_r, 2)
                elif i == game.player_index:
                    # next expected — pulsing white border
                    pulse = 0.5 + 0.5 * math.sin(now * 7)
                    r_anim = int(dot_r + 3 * pulse)
                    pygame.draw.circle(surface, (60, 60, 60), (cx, cy), dot_r)
                    pygame.draw.circle(surface, (200, 200, 200), (cx, cy), r_anim, 3)
                else:
                    # future — dark
                    pygame.draw.circle(surface, (60, 60, 60), (cx, cy), dot_r)
                    pygame.draw.circle(surface, (100, 100, 100), (cx, cy), dot_r, 2)
            else:
                # DEMO: highlight current element, rest dark
                if game.sequence[i] == game.highlighted_element and i == game._demo_index - 1:
                    pygame.draw.circle(surface, (220, 220, 220), (cx, cy), dot_r)
                    pygame.draw.circle(surface, (255, 255, 255), (cx, cy), dot_r, 2)
                else:
                    pygame.draw.circle(surface, (70, 70, 70), (cx, cy), dot_r)
                    pygame.draw.circle(surface, (120, 120, 120), (cx, cy), dot_r, 2)

    # ── timer bar (player's turn only) ───────────────────────────────────
    if game.state == game.STATE_WAIT_INPUT:
        remaining = game.remaining_time
        frac      = remaining / max(0.01, game.PLAYER_TIMEOUT)
        bar_h     = 6
        bar_y     = 68
        bar_w_max = w - 40
        bar_w     = int(bar_w_max * frac)

        r = int(255 * (1.0 - frac))
        g = int(255 * frac)
        bar_color = (min(255, r), min(255, g), 50)

        pygame.draw.rect(surface, (40, 40, 40), (20, bar_y, bar_w_max, bar_h))
        if bar_w > 0:
            pygame.draw.rect(surface, bar_color, (20, bar_y, bar_w, bar_h))

    # ── state banners ─────────────────────────────────────────────────────
    if game.state == game.STATE_IDLE:
        diff_col = _DIFFICULTY_COLOR.get(difficulty, (200, 200, 200))
        diff_lbl = _DIFFICULTY_LABEL.get(difficulty, difficulty.upper())
        _draw_center_banner(
            surface, w, h, big_font, font,
            "GENIUS DRUMS",
            f"1:EASY   2:MEDIUM   3:HARD   |   SPACE to start as [{diff_lbl}]",
            (255, 220, 60), diff_col,
        )

    elif game.state == game.STATE_DEMO:
        _draw_small_banner(surface, w, h // 2 + 30, font,
                           "  WATCH  ", (40, 40, 120, 180), (180, 180, 255))

    elif game.state == game.STATE_WAIT_INPUT:
        _draw_small_banner(surface, w, h // 2 + 30, font,
                           "  YOUR TURN  ", (20, 80, 20, 180), (100, 255, 120))

    elif game.state == game.STATE_GAME_OVER:
        is_new_best = game.score == game.best_score and game.score > 0
        diff_col = _DIFFICULTY_COLOR.get(difficulty, (200, 200, 200))
        diff_lbl = _DIFFICULTY_LABEL.get(difficulty, difficulty.upper())

        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))

        cx = w // 2
        cy = h // 2

        # line 1 – "GAME OVER"
        go_surf = big_font.render("GAME OVER", True, (255, 70, 70))
        surface.blit(go_surf, (cx - go_surf.get_width() // 2, cy - 80))

        # line 2 – score
        if is_new_best:
            score_line = f"NEW BEST!   {game.score} pts"
            score_col  = (255, 230, 60)
        else:
            score_line = f"Score: {game.score}     Best: {game.best_score}"
            score_col  = (220, 220, 220)
        sc_surf = font.render(score_line, True, score_col)
        surface.blit(sc_surf, (cx - sc_surf.get_width() // 2, cy - 20))

        # line 3 – difficulty options
        diff_line = f"1: EASY     2: MEDIUM     3: HARD     |     SPACE to replay [{diff_lbl}]"
        dl_surf = font.render(diff_line, True, diff_col)
        surface.blit(dl_surf, (cx - dl_surf.get_width() // 2, cy + 40))

        # line 4 – ESC hint
        esc_surf = font.render("ESC — leave game", True, (160, 160, 160))
        surface.blit(esc_surf, (cx - esc_surf.get_width() // 2, cy + 75))


def _draw_center_banner(surface, w, h, big_font, font,
                         title, subtitle,
                         title_color, sub_color) -> None:
    """Full-screen semi-transparent overlay with centered text."""
    overlay = pygame.Surface((w, h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    surface.blit(overlay, (0, 0))

    t_surf = big_font.render(title, True, title_color)
    s_surf = font.render(subtitle, True, sub_color)
    cx = w // 2
    cy = h // 2
    surface.blit(t_surf, (cx - t_surf.get_width() // 2, cy - 50))
    surface.blit(s_surf, (cx - s_surf.get_width() // 2, cy + 20))


def _draw_small_banner(surface, w, y, font, text, bg_color, text_color) -> None:
    """Small semi-transparent pill banner centred horizontally at y."""
    surf = font.render(text, True, text_color)
    pad  = 14
    bw   = surf.get_width()  + pad * 2
    bh   = surf.get_height() + pad
    bx   = w // 2 - bw // 2
    btn  = pygame.Surface((bw, bh), pygame.SRCALPHA)
    btn.fill(bg_color)
    surface.blit(btn, (bx, y))
    surface.blit(surf, (bx + pad, y + pad // 2))


# ── main entry point ──────────────────────────────────────────────────────

def start_drums_game(
    chosen_instrument=None,
    resolution_profile=None,
    show_trackers: bool = False,
    drum_model: str = "default",
    drums_elements=None,
    hand_model_complexity: int = 1,
    difficulty: str = "easy",
):
    """
    Start the Genius-style drum game.

    difficulty  – "easy" | "medium" | "hard"
                  Controls demo speed, player timeout and number of extra
                  drum elements added to the kit.  Can also be changed
                  in-game with keys 1 / 2 / 3 from the IDLE or GAME_OVER screen.
    """
    print(f">>> INICIANDO GENIUS DRUMS GAME [{difficulty.upper()}]")

    # ── apply instrument profile ─────────────────────────────────────────
    apply_drum_note_profile(chosen_instrument)

    normalized_model = str(drum_model).strip().lower()
    replace_base     = False
    base_elements    = drums_elements   # elements explicitly requested by user (may be None)

    if not replace_base and base_elements is None and chosen_instrument in DRUMS_INSTRUMENT_ELEMENT_PRESETS:
        preset_elements = DRUMS_INSTRUMENT_ELEMENT_PRESETS.get(chosen_instrument, [])
        base_elements   = [e for e in preset_elements if e in DRUM_ELEMENT_LIBRARY]
        if chosen_instrument in DRUMS_INSTRUMENT_REPLACE_BASE:
            replace_base = True

    def _apply_kit(diff: str) -> tuple:
        """(Re)configure DRUM_KIT for the given difficulty. Returns (unique_avail, indexed_elements)."""
        merged = _merge_elements_for_difficulty(base_elements, diff)
        configure_drum_kit(
            normalized_model,
            drums_elements=merged,
            replace_base=replace_base,
            instrument_name=chosen_instrument,
        )
        avail: list = []
        seen_k: set = set()
        for d in _kit():
            k = d.get("element_key", "")
            if not d.get("foot_only", False) and k not in seen_k:
                avail.append(k)
                seen_k.add(k)
        indexed = list(enumerate(avail))
        return avail, indexed

    # Initial kit build
    current_difficulty = difficulty if difficulty in ("easy", "medium", "hard") else "easy"
    unique_avail, indexed_elements = _apply_kit(current_difficulty)

    # ── audio setup ──────────────────────────────────────────────────────
    FIXED_SF2_PATH = settings.SF2_PATHS["drums"]
    fs_local, _ = init_fluidsynth(driver="dsound")
    POLYPHONY_CHANNELS = 16
    drum_sfid = -1
    if fs_local is not None:
        drum_sfid = load_single_soundfont(fs_local, "drums", FIXED_SF2_PATH)
        if drum_sfid != -1:
            for i in range(POLYPHONY_CHANNELS):
                fs_local.program_select(i, drum_sfid, 128, 0)

    if chosen_instrument and drum_sfid != -1:
        if chosen_instrument in settings.INSTRUMENTS:
            _, bank, preset = settings.INSTRUMENTS[chosen_instrument]
            for i in range(POLYPHONY_CHANNELS):
                fs_local.program_select(i, drum_sfid, bank, preset)
            print(f">>> Kit: {chosen_instrument}")

    # patch the module-level audio_queue consumer to use this fs instance
    import numpy as np

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

    # ── resolution / pygame setup ─────────────────────────────────────────
    if resolution_profile:
        DISPLAY_W  = int(resolution_profile["display_width"])
        DISPLAY_H  = int(resolution_profile["display_height"])
        TARGET_FPS = int(resolution_profile["fps"])
    else:
        DISPLAY_W, DISPLAY_H, TARGET_FPS = 1280, 720, 60

    DISPLAY_W, DISPLAY_H, adjusted, sw, sh = fit_resolution_to_screen(DISPLAY_W, DISPLAY_H)
    if adjusted:
        print(f">>> Resolução ajustada: {DISPLAY_W}x{DISPLAY_H}")

    LOGICAL_W, LOGICAL_H = DISPLAY_W, DISPLAY_H

    cap = setup_video_capture(width=LOGICAL_W, height=LOGICAL_H, fps=TARGET_FPS)
    window_display, main_surface, font = setup_pygame_with_scaling(
        logical_width=LOGICAL_W, logical_height=LOGICAL_H,
        display_width=DISPLAY_W, display_height=DISPLAY_H,
        title="Talking Hands — Genius Drums",
    )
    big_font   = pygame.font.SysFont("Arial", 42, bold=True)
    names_font = pygame.font.SysFont("Arial", 12, bold=False)

    # ── game state ────────────────────────────────────────────────────────
    game = GeniusGame()

    fps_tracker = FPSTracker(update_interval=10)

    # ── MediaPipe setup ───────────────────────────────────────────────────
    hand_complexity = max(0, min(1, int(hand_model_complexity)))
    hands = mp.solutions.hands.Hands(
        max_num_hands=2,
        model_complexity=hand_complexity,
        min_detection_confidence=0.3,
        min_tracking_confidence=0.3,
    )

    reset_hands_state()
    running = True

    try:
        while running:
            # ── pygame events ─────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE:
                        if game.state in (game.STATE_IDLE, game.STATE_GAME_OVER):
                            game.start(unique_avail, difficulty=current_difficulty)

                    # ── difficulty selection (IDLE or GAME_OVER only) ───────
                    elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                        if game.state in (game.STATE_IDLE, game.STATE_GAME_OVER):
                            new_diff = {pygame.K_1: "easy",
                                        pygame.K_2: "medium",
                                        pygame.K_3: "hard"}[event.key]
                            if new_diff != current_difficulty:
                                current_difficulty          = new_diff
                                unique_avail, indexed_elements = _apply_kit(current_difficulty)
                                print(f">>> Dificuldade: {current_difficulty.upper()}  "
                                      f"({len(unique_avail)} elementos)")

            # ── grab frame ────────────────────────────────────────────────
            ret, frame = cap.read()
            if not ret:
                break

            fps_tracker.update()

            frame = cv2.resize(frame, (LOGICAL_W, LOGICAL_H))
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            frame_surface = pygame.image.frombuffer(
                frame_rgb.tobytes(), (LOGICAL_W, LOGICAL_H), "RGB"
            )
            main_surface.blit(frame_surface, (0, 0))

            # ── game tick ─────────────────────────────────────────────────
            game.update(_kit())

            # play demo note if one was queued by the state machine
            if game.pending_play_note is not None:
                audio_queue.put(game.pending_play_note)

            # ── draw drums ────────────────────────────────────────────────
            _draw_game_drums(main_surface, LOGICAL_W, LOGICAL_H,
                             names_font, game, indexed_elements)

            # ── hand tracking (only process input during player turn / feedback) ──
            results = hands.process(frame_rgb)
            if results.multi_hand_landmarks:
                for idx, landmarks in enumerate(results.multi_hand_landmarks):
                    lbl = results.multi_handedness[idx].classification[0].label
                    _process_hand_game(
                        lbl, landmarks.landmark,
                        LOGICAL_W, LOGICAL_H,
                        main_surface, game,
                        show_trackers=show_trackers,
                    )

            # ── HUD overlay ───────────────────────────────────────────────
            _draw_game_hud(main_surface, LOGICAL_W, LOGICAL_H,
                           font, big_font, game, indexed_elements,
                           difficulty=current_difficulty)

            window_display.blit(main_surface, (0, 0))
            pygame.display.flip()

    except Exception as exc:
        print(f"Erro Runtime (game): {exc}")
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
        print(">>> Genius Drums Encerrado.")
