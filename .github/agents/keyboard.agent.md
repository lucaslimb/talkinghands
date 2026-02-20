---
name: keyboard
description: This custom agent operates the virtual keyboard instrument in Talking Hands, interpreting finger positions to play notes and managing recording/playback.
model: GPT-5.3-Codex (copilot)
# tools: ['vscode', 'execute', 'read', 'agent', 'edit', 'search', 'web', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
---
# Talking Hands — Custom Agent (Keyboard)

Agent, this file is your dedicated operational guide for `src/instruments/keyboard.py` and shared dependencies in `src/instruments/common.py`.

## Core Contracts You Must Preserve

1. Keep FluidSynth path setup before importing `fluidsynth`.
2. Keep Windows audio driver compatibility with `driver="dsound"`.
3. Keep frame loop real-time safe; do not add blocking operations.
4. Keep normalized-coordinate interaction logic (`0..1`).
5. Preserve recorder integration and keyboard shortcuts.

## Shared Backbone (`common.py`) Relevant to Keyboard

- `_setup_fluidsynth_path()` manages bundled FluidSynth discovery and env vars.
- `init_fluidsynth()` initializes synth and returns `(fs, loaded_sfids)` shape.
- `load_all_soundfonts()` loads all configured SF2 paths.
- `select_instrument()` resolves instrument map `(sf_key, bank, preset)` and updates recorder metadata.
- `setup_video_capture()` and `setup_pygame_with_scaling()` provide camera/display setup.
- `fit_resolution_to_screen()` prevents oversized window creation.
- UI helpers (`draw_text`, recording/playback indicators) are shared UX primitives.

Agent rule: if a keyboard helper is generic, move it to `common.py` instead of duplicating.

## Keyboard Architecture Deep Dive

### Initialization
1. Module initializes `fs`, `loaded_sfids`, `recorder`, and loads all soundfonts.
2. `start_piano(...)` applies runtime thresholds, selects instrument, starts audio worker, then starts MediaPipe + video + pygame pipeline.

### Key Model
- `NUM_KEYS=30`, note mapping from `BASE_NOTE=48` with `SCALE_INTERVALS=[0,2,4,5,7,9,11]`.
- Each key holds `note`, `last_hit`, `is_active`, and `off_timer`.

### Finger State Engine (Critical)
Tracked fingers per hand: `[4, 8, 12, 16, 20]`.

Per-finger state:
- `finger_status`: `IDLE | ARMED | TOUCHING`
- `finger_timers`
- `active_notes`
- `last_seen`

Transition logic in `processar_dedo(...)`:
- `IDLE -> ARMED` when finger lifts above table threshold.
- `ARMED -> TOUCHING` when finger reaches table zone and triggers note-on.
- `TOUCHING` supports note glide when crossing virtual key boundaries.
- Release moves back to `ARMED` using force/normal release checks.

### Anti-Stuck Mechanisms
- `check_lost_fingers()` turns notes off when tracking disappears (`MAX_MISSING_TIME`).
- `check_active_keys_integrity()` applies sustain timeout logic (`SUSTAIN_DECAY`).

### Audio Queue Protocol
- `("on", note)` => `fs.noteon(...)` + recorder note-on.
- `("off", note)` => `fs.noteoff(...)` + recorder note-off.

### Keyboard Controls Contract
- `1`: start recording
- `2`: stop/save MIDI
- `3`: toggle playback
- `4`: stop playback
- `9`: toggle trackers
- `0`: toggle menu
- `ESC`: exit

## Safe Change Strategy

1. Do not flatten state-machine logic into simple collision checks.
2. Keep threshold overrides settings/CLI-compatible.
3. Preserve stuck-note protections first when refactoring.
4. Preserve teardown order (`noteoff cleanup`, `cap.release`, `pygame.quit`, queue sentinel).

## Quick Validation Checklist

- FluidSynth import order unchanged.
- No blocking work added inside main loop.
- Note on/off recorder events still emitted.
- Keyboard shortcuts still functional.
- Exit does not leave sounding notes.
