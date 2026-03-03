# Talking Hands — Copilot Instructions

## Project architecture (read this first)
- CLI entrypoint is `src/main.py`; it parses args, selects instrument type from `settings.INSTRUMENTS`, and dispatches to one of:
	- `src/instruments/keyboard.py` (`start_piano`)
	- `src/instruments/drums.py` (`start_drums`)
- Core shared helpers live in `src/instruments/common.py` (FluidSynth init/load, pygame/camera setup, UI helpers).
- Recording/export pipeline is centralized in `src/engines/recorder.py` (`MidiRecorder`): captures note/CC events, writes MIDI, optionally renders WAV, optionally converts to MP3.
- Global configuration is in `src/config/settings.py` (soundfont paths, instrument map, thresholds, recording defaults, OS-specific recordings path).

## Runtime and dependency rules (critical)
- This repo assumes bundled FluidSynth under `assets/fluidsynth-v2.5.1`; do not hardcode other install paths.
- Preserve `_MEIPASS` + env setup patterns used in `src/main.py`, `src/instruments/common.py`, and `src/engines/recorder.py`.
- Keep `FLUIDSYNTH_PATH` and `PATH` adjustments before importing `fluidsynth`.
- On Windows, audio driver is expected as `driver="dsound"`.

## Data flow and interaction patterns
- CV loop pattern in instrument modules: `cv2.VideoCapture` -> MediaPipe inference -> normalized gesture logic -> enqueue audio events -> pygame render.
- Instruments use normalized coordinates and thresholds (0..1 space); tune via settings/CLI flags instead of pixel constants.
- Audio playback is asynchronous via `queue.Queue` + background threads; avoid blocking operations in frame loops.
- Recording/playback controls are keyboard-driven inside pygame loops (`1` start rec, `2` stop rec, `3` playback toggle, `ESC` exit; `0` hide/show menu).

## Developer workflows
- Create env and install deps: `pip install -r requirements.txt`
- Run CLI help/docs: `python src/main.py -h`
- Quick camera profile test: `python src/main.py --test-cam`
- Run an instrument: `python src/main.py -i "Piano"` (or any key from `settings.INSTRUMENTS`)
- Build Windows executable: `python builders/build.py`
- Force FluidSynth asset setup (if missing): `python builders/setup_fluidsynth.py`

## Project-specific conventions
- Prefer extending shared utilities in `src/instruments/common.py` instead of duplicating init/render helpers.
- When adding instruments, register names in `settings.INSTRUMENTS` using `(sf_key, bank, preset)` and reuse `select_instrument` flow.
- Keep recordings behavior aligned with `MidiRecorder.options` (`save_mid`, `save_wav`, `save_mp3`, `separate_playback`).
- MP3 export depends on `ffmpeg` in PATH; keep fallback behavior (warn, don’t crash) consistent.
- Comments/UI text are partly Portuguese; maintain existing language style in touched module.

## Packaging and assets
- Keep soundfonts under `assets/soundfonts/*` and FluidSynth binaries under `assets/fluidsynth-v2.5.1/*`.
- Do not break PyInstaller data collection in `builders/build.py` (`--add-data`, `--add-binary`, `--collect-submodules mediapipe`).
- `*.sf2` are expected in repo/LFS workflow; avoid changing `.gitattributes` behavior during feature work.
