# Copilot Instructions for Talking Hands

## Project Overview
- **Talking Hands** is a Python-based virtual instrument platform using computer vision and real-time audio synthesis.
- The system tracks hand and face positions via webcam, mapping gestures to musical actions for keyboard, drums, and flute.
- Audio synthesis is handled by FluidSynth soundfonts, with a focus on low-latency performance.

## Architecture & Key Components
- **src/main.py**: Entry point; launches the main application and instrument selection UI.
- **src/instruments/**: Contains instrument logic for keyboard, drums, and flute. Each instrument is modular and can be calibrated for user/environment.
- **src/engines/recorder.py**: Handles audio/MIDI recording and export (WAV, MP3, MID).
- **src/config/settings.py**: Stores configuration and calibration logic for instruments and user preferences.
- **src/utils/utils.py**: Shared utility functions (e.g., hand/face landmark processing, file management).
- **assets/soundfonts/**: Soundfont files for each instrument (drums, flute, keyboard).

## Developer Workflows
- **Run the app**: `python src/main.py` (ensure webcam and soundfont files are available)
- **Dependencies**: Install via `pip install -r requirements.txt` (uses OpenCV, MediaPipe, pyFluidSynth, CustomTkinter, PyGame)
- **Recording/Export**: Use the instrument GUI to record and export audio/MIDI. Files are saved in the `recordings/` directory.
- **Instrument Calibration**: Each instrument supports calibration via the GUI for hand/face position and sensitivity.

## Project Conventions
- Instrument modules follow a pattern: input (vision/gesture) → mapping → sound trigger.
- Soundfont paths and instrument configs are managed in `settings.py`.
- UI logic is split: launcher (CustomTkinter) vs. instrument GUIs (PyGame).
- Use descriptive, English-named functions and classes, even if comments/UI are in Portuguese.
- All persistent data (recordings, configs) is stored in project subfolders, not user home.

## Integration & Extensibility
- To add a new instrument: create a new module in `src/instruments/`, update the launcher UI, and add soundfonts to `assets/soundfonts/`.
- For new vision models, extend `utils.py` and update instrument modules as needed.
- External soundfonts must be in `.sf2` format and referenced in `settings.py`.

## Examples
- See `src/instruments/drums.py` for gesture-to-sound mapping and velocity sensitivity.
- See `src/engines/recorder.py` for how recordings are managed and exported.

---
For more details, see the [README.md](../README.md).
