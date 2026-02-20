---
name: drum
description: This custom agent operates the virtual drum instrument in Talking Hands, interpreting hand positions to play drum sounds and managing recording/playback.
model: GPT-5.3-Codex (copilot)
# tools: ['vscode', 'execute', 'read', 'agent', 'edit', 'search', 'web', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
---
# Talking Hands — Custom Agent (Drums)

Agent, this file is your dedicated operational guide for `src/instruments/drums.py` and shared dependencies in `src/instruments/common.py`.

## Core Contracts You Must Preserve

1. Keep FluidSynth setup order and bundled binary path usage.
2. Keep Windows audio compatibility with `driver="dsound"`.
3. Preserve real-time loop performance (no blocking operations).
4. Preserve normalized geometry for drum hit zones and drag behavior.
5. Preserve recorder note event flow and runtime control keys.

## Shared Backbone (`common.py`) Relevant to Drums

- `init_fluidsynth()` is still the synth entrypoint.
- `load_single_soundfont()` loads fixed drum SF2 file.
- `fit_resolution_to_screen()`, `setup_video_capture()`, and `setup_pygame_with_scaling()` are display/capture foundations.
- Shared draw helpers provide consistent UI indicators and text rendering.

Agent rule: shared helpers belong in `common.py`; keep instrument-specific logic in `drums.py`.

## Drums Architecture Deep Dive

### Initialization
1. Module initializes synth and applies drum gain (`DRUM_SYNTH_GAIN`).
2. Loads fixed drum SF2 (`settings.SF2_PATHS["drums"]`).
3. Configures polyphonic channels (`POLYPHONY_CHANNELS=16`) with bank/preset and CC volume/expression.
4. `start_drums(...)` applies runtime options, starts audio worker, then enters frame loop.

### Drum Zone Model
- `DRUM_KIT` defines zone `id`, normalized `pos`, normalized `axes`, `shape` (`ellipse`/`rect`), MIDI `note`, and visual state.
- Zones are draggable with mouse and resettable via `reset_drum_positions()`.

### Hit Detection and Triggering
- Reference point: thumb tip landmark (`landmarks[4]`).
- Collision: `check_collision(...)` using ellipse equation or rectangle bounds.
- Trigger requires:
  - in-zone collision,
  - downward motion (`dy > VELOCITY_THRESHOLD`),
  - armed hand state (`can_hit`),
  - enough pixel displacement since last hit on same zone (`MIN_REHIT_PIXELS`).

Velocity mapping:
- `velocity = clamp((dy - TOUCH_VELOCITY) * 10000, DRUM_MIN_VELOCITY, 127)`.

### Anti-Retrigger Logic
- `can_hit` becomes `False` after hit.
- Hand re-arms when leaving zone or showing upward movement.
- Additional distance gate prevents jitter spam on the same drum.

### Audio Queue Protocol
- Queue payload: `(note, velocity)`.
- Worker picks random channel for polyphony and sends `noteon` + recorder note-on.

### Drums Controls Contract
- `1`: start recording
- `2`: stop/save MIDI
- `3`: toggle playback
- `5`: reset drum positions
- `9`: toggle trackers
- `0`: toggle menu
- `SPACE`: quick kick (note 36)
- `ESC`: exit

## Safe Change Strategy

1. Preserve random-channel polyphony behavior.
2. Preserve draggable-zone UX and normalized coordinates.
3. Keep anti-double-trigger logic intact when tuning thresholds.
4. Keep teardown path stable (`cap.release`, `pygame.quit`, queue sentinel).

## Quick Validation Checklist

- Drum SF2 still loads from configured project path.
- Hits still require directional motion and arming.
- Re-hit lockout still prevents rapid duplicate triggers.
- Controls and playback/recording flow still work.
