---
name: flute
description: This custom agent operates the virtual flute instrument in Talking Hands, interpreting hand and mouth positions to play flute sounds and managing recording/playback.
model: GPT-5.3-Codex (copilot)
# tools: ['vscode', 'execute', 'read', 'agent', 'edit', 'search', 'web', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
---
# Talking Hands — Custom Agent (Flute)

Agent, this file is your dedicated operational guide for `src/instruments/flute.py` and shared dependencies in `src/instruments/common.py`.

## Core Contracts You Must Preserve

1. Keep FluidSynth setup/import order and bundled path usage.
2. Keep real-time responsiveness in frame/audio paths.
3. Preserve normalized coordinates for hole positions and drag interactions.
4. Preserve channel separation between live play and playback.
5. Preserve recorder note and CC behavior.

## Shared Backbone (`common.py`) Relevant to Flute

- `init_fluidsynth()` + `load_single_soundfont()` handle synth and SF2 loading.
- `setup_video_capture()`, `setup_pygame_with_scaling()`, `fit_resolution_to_screen()` provide runtime infrastructure.
- Shared draw helpers power on-screen text and recording/playback indicators.

Agent rule: refactor shared behavior into `common.py`; keep flute-specific musical logic local.

## Flute Architecture Deep Dive

### Initialization
1. Module initializes synth/recorder and loads flute SF2 into `loaded_sfids`.
2. Uses channel split:
   - `PLAYBACK_CHANNEL = 0`
   - `LIVE_CHANNEL = 1`
3. `select_instrument_by_name()` configures both channels with same program and expression CC.
4. `start_flute(...)` applies runtime options, starts MediaPipe Hands + Face Mesh loop.

### Flute Geometry and Fingering
- `NUM_HOLES=7`, configurable radius/spacing.
- `update_hole_positions()` rebuilds hole layout from flute origin.
- Finger tips used for coverage: `[8, 12, 16, 20]` for each detected hand.
- Hole coverage test uses radial distance threshold (`radius * 1.3`).

Note selection:
- `calculate_current_note()` finds first open hole and maps to `SCALE_FLUTE` from `BASE_NOTE`.

### Blow and Expression Mapping
- Mouth openness from Face Mesh landmarks `13` (upper lip) and `14` (lower lip).
- Smoothed with `MOUTH_SMOOTHING_FACTOR`.
- Velocity from mouth curve with options:
  - `mouth_peak`
  - `mouth_max`
  - `invert_blow`
- Manual blow override on `SPACE` sends max velocity.

CC behavior:
- Sends `CC11` only when change exceeds `VELOCITY_CHANGE_THRESHOLD` to reduce message spam.

### Audio Queue Protocol
- `("note_on", note, _)`
- `("note_off", 0, 0)`
- `("cc", controller, value)`

Audio worker enforces one current live note and performs safe note transitions.

### Flute Controls Contract
- `1`: start recording
- `2`: stop/save MIDI
- `3`: toggle playback
- `5`: reset flute position
- `9`: toggle trackers
- `0`: toggle menu
- `ESC`: exit

## Safe Change Strategy

1. Preserve channel split (live vs playback).
2. Preserve CC11 thresholding (avoid dense CC spam).
3. Preserve drag interactions and normalized hole layout.
4. Preserve mouth mapping behavior and runtime overrides.
5. Preserve teardown (`cap.release`, `pygame.quit`, queue sentinel).

## Quick Validation Checklist

- Instrument program still set on both channels.
- Note transitions do not leave hanging notes.
- CC11 updates remain smooth and rate-limited.
- Fingering + blow logic still jointly gate audible output.
