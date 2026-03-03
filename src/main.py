#!/usr/bin/env python3
"""
Talking Hands CLI Launcher
Command-line interface for Talking Hands computer vision instruments platform.
"""
import argparse
import sys
import os
import re
import time
from importlib import import_module
import importlib.util
from pathlib import Path

# Setup imports - handle both normal and PyInstaller bundled environments
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running as PyInstaller bundle
    PROJECT_ROOT = Path(sys._MEIPASS)
    # Add the project root to sys.path so src modules can be imported
    sys.path.insert(0, str(PROJECT_ROOT))
else:
    # Running as normal Python script
    FILE_PATH = Path(__file__).resolve()
    PROJECT_ROOT = FILE_PATH.parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.engines.dependency_manager import verify_dependencies_before_launch


def safe_import_module(module_path):
    """
    Safely import a module, handling both normal and PyInstaller bundled environments.
    Prevents pyfluidsynth from crashing on hardcoded C:\\tools\\fluidsynth\\bin.
    """

    # Resolve project root
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        project_root = Path(sys._MEIPASS)
    else:
        project_root = PROJECT_ROOT

    fluidsynth_bin = project_root / "assets" / "fluidsynth-v2.5.1" / "bin"

    # Preconfigure correct FluidSynth path
    if fluidsynth_bin.exists():
        bin_str = str(fluidsynth_bin)
        os.environ["FLUIDSYNTH_PATH"] = bin_str

        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(bin_str)
            except Exception:
                pass

        current_path = os.environ.get("PATH", "")
        if bin_str not in current_path:
            os.environ["PATH"] = f"{bin_str};{current_path}"

    # --- CRITICAL PART: patch os.add_dll_directory ---
    original_add_dll_directory = getattr(os, "add_dll_directory", None)

    def safe_add_dll_directory(path):
        # Ignore pyfluidsynth's bad hardcoded path
        if path.lower() == r"c:\tools\fluidsynth\bin":
            return None
        return original_add_dll_directory(path)

    if original_add_dll_directory:
        os.add_dll_directory = safe_add_dll_directory

    try:
        return import_module(module_path)

    finally:
        # Restore original function to avoid side effects
        if original_add_dll_directory:
            os.add_dll_directory = original_add_dll_directory



def get_available_instruments():
    """Get instruments grouped by type"""
    catalog = {"keyboard": [], "drums": []}
    
    for name, data in settings.INSTRUMENTS.items():
        sf_key = data[0]
        if sf_key == "drums":
            catalog["drums"].append(name)
        else:
            catalog["keyboard"].append(name)
    
    return catalog

def validate_instrument(value):
    """Validate that the instrument exists"""
    catalog = get_available_instruments()
    all_instruments = catalog["keyboard"] + catalog["drums"]
    
    if value not in all_instruments:
        raise argparse.ArgumentTypeError(
            f"Instrument '{value}' not found. Available: {', '.join(all_instruments)}"
        )
    return value


def parse_resolution_arg(value):
    """
    Parse resolution profile string.
    Examples:
      108030 -> 1080p @ 30fps
      72060  -> 720p @ 60fps
      720120 -> 720p @ 120fps
    Returns a dict with runtime dimensions and fps.
    """
    raw = str(value).strip()
    if not re.fullmatch(r"\d{5,7}", raw):
        raise argparse.ArgumentTypeError(
            "Invalid -r format. Use numeric profile like 108030 (1080p 30fps)."
        )

    parsed = None
    for fps_digits in (3, 2):
        if len(raw) <= fps_digits:
            continue
        h_part = raw[:-fps_digits]
        fps_part = raw[-fps_digits:]
        height = int(h_part)
        fps = int(fps_part)

        if 240 <= height <= 4320 and 1 <= fps <= 240:
            parsed = (height, fps)
            break

    if parsed is None:
        raise argparse.ArgumentTypeError(
            "Could not parse -r. Use profiles like 108030, 72060, 720120."
        )

    display_h, fps = parsed
    display_w = int(round(display_h * (16 / 9)))
    if display_w % 2 != 0:
        display_w += 1
    if display_h % 2 != 0:
        display_h += 1

    logical_w = display_w
    logical_h = display_h

    return {
        "raw": raw,
        "display_width": display_w,
        "display_height": display_h,
        "logical_width": logical_w,
        "logical_height": logical_h,
        "fps": fps,
    }


def parse_hands_model_complexity(value):
    """Parse MediaPipe Hands model complexity (allowed: 0 or 1)."""
    try:
        parsed = int(value)
    except Exception:
        raise argparse.ArgumentTypeError("Invalid --hands-mc. Use 0 or 1.")

    if parsed not in (0, 1):
        raise argparse.ArgumentTypeError("Invalid --hands-mc. Use 0 or 1.")
    return parsed


def parse_pose_model_complexity(value):
    """Parse MediaPipe Pose model complexity (allowed: 0, 1 or 2)."""
    try:
        parsed = int(value)
    except Exception:
        raise argparse.ArgumentTypeError("Invalid --pose-mc. Use 0, 1 or 2.")

    if parsed not in (0, 1, 2):
        raise argparse.ArgumentTypeError("Invalid --pose-mc. Use 0, 1 or 2.")
    return parsed


def parse_drums_elements_arg(value):
    """Parse comma-separated drums elements and validate against predefined list."""
    raw = str(value).strip()
    if not raw:
        raise argparse.ArgumentTypeError("Invalid --drm-elems value. Use comma-separated names.")

    elements = [token.strip().lower() for token in raw.split(",") if token.strip()]
    if not elements:
        raise argparse.ArgumentTypeError("Invalid --drm-elems value. Use comma-separated names.")

    allowed = set(getattr(settings, "DRUMS_PREDEFINED_ELEMENTS", []))
    invalid = [name for name in elements if name not in allowed]
    if invalid:
        allowed_txt = ",".join(sorted(allowed))
        raise argparse.ArgumentTypeError(
            f"Invalid drums elements: {', '.join(invalid)}. Allowed: {allowed_txt}"
        )

    dedup = []
    seen = set()
    for name in elements:
        if name not in seen:
            dedup.append(name)
            seen.add(name)
    return dedup

def get_instrument_type(instrument_name):
    """Determine instrument type from name"""
    catalog = get_available_instruments()
    
    if instrument_name in catalog["drums"]:
        return "drums"
    else:
        return "keyboard"

def print_documentation():
    """Print comprehensive documentation and exit"""
    doc = """╔════════════════════════════════════════════════════════════════════════════════╗
║                          TALKING HANDS ENGINE GUIDE                          ║
╚════════════════════════════════════════════════════════════════════════════════╝

USAGE ON DEV ENV:
  python src/main.py [OPTIONS]

USAGE ON PRODUCTION (BUNDLED):
  THEngine.exe [OPTIONS]

STANDALONE OPTIONS:
  --test-cam                         Test camera Resolution and FPS capabilities and exit with result

GLOBAL OPTIONS:
  -h, --help                         Show help message and exit
    -i, --instrument INSTRUMENT_NAME   Instrument name to start (e.g., 'Classic', 'Power', 'Grand Piano', 'Recorder')
    -r, --resolution PROFILE           Resolution/FPS profile (HEIGHT+FPS). HEIGHT min/max: 240..4320, FPS min/max: 1..240 (default: 108030)
        --hands-mc {0,1}                   Hands model complexity (default: 1)
        --pose-mc {0,1,2}                  Pose model complexity for drums feet tracking (default: 1)
    -t, --trackers                     Show hand/face trackers on screen (default: False)

RECORDING BEHAVIOR:
    - MID e WAV são sempre gerados por padrão
    - Saída de notas MIDI: recordings/mids/
    - Saída de áudio final (gravações/mesclas): recordings/wav/

KEYBOARD OPTIONS:
    --kbd-lf LIFT_THRESHOLD            Lift threshold (float > 0, default: 0.02; suggested: 0.005..0.10)
    --kbd-sd SUSTAIN_DECAY             Sustain decay seconds (float > 0, default: 0.8; suggested: 0.05..5.0)
    --kbd-ts TOUCH_TOLERANCE           Touch tolerance (float > 0, default: 0.005; suggested: 0.001..0.05)

GAME MODE:
    --mode {play,game}                  Instrument mode (default: play)
                                          play  → standard free-play
                                          game  → Genius-style drum challenge (drums instruments only)
    --difficulty {easy,medium,hard}     Game difficulty (default: easy); only used with --mode game
                                          easy    → slow demo (0.55 s/hit), 12 s timeout,  default kit, +10 pts/hit
                                          medium  → medium demo (0.36 s/hit), 8 s timeout, +3 extra pads, +15 pts/hit
                                          hard    → fast demo (0.20 s/hit),  4.5 s timeout, +6 extra pads, +25 pts/hit
                                        Controls in game mode:
                                          SPACE → start / restart game
                                          1 / 2 / 3 → switch difficulty from IDLE or GAME OVER screen
                                          ESC   → exit

DRUMS OPTIONS:
    --drm-model {default,complete,override} Drum layout model (string values: default|complete|override, default: default)
    --drm-elems a,b,c                   Drums elements list (comma-separated). Allowed: crash,ride,splash,china,tom_hi,tom_mid,tom_low,hihat,open_hh,snare,snare_alt,rimshot,floor,kick,kick_alt,hh_pedal,cowbell,clap,tamb,ride_bell,crash2,ride2,vibra_slap,shaker,cabasa,maracas,guiro_s,guiro_l,agogo_hi,agogo_lo,clave,wood_hi,wood_lo,tri_mute,tri_open,bongo_hi,bongo_mid,bongo_lo,bongo_deep,conga_hi,conga_mid,conga_lo,timbale_hi,timbale_lo
    --drm-tt TOUCH_TOLERANCE            Touch tolerance (float > 0, default: 0.01; suggested: 0.001..0.10)
    --drm-tv TOUCH_VELOCITY             Touch velocity threshold (float > 0, default: 0.012; suggested: 0.001..0.10)

EXAMPLES:
    python src/main.py -i "Classic" -tf
    python src/main.py -i "Piano" -r 108030
    THEngine.exe -i "Grand Piano" --kbd-sd 0.5 --kbd-lf 0.025
"""
    print(doc)
    sys.exit(0)


def create_argparse():
    """Create and configure the argument parser"""
    parser = argparse.ArgumentParser(
        prog="Talking Hands",
        description="Virtual instrument platform using computer vision",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,  # Disable default help to prevent automatic exit
    )
    
    # Add custom help argument
    parser.add_argument(
        "-h", "--help",
        action="store_true",
        help="Show help message and exit"
    )
    
    # Test FPS argument
    parser.add_argument(
        "--test-cam",
        action="store_true",
        help="Test camera FPS capabilities and exit with result"
    )
    
    # Global arguments
    parser.add_argument(
        "-i", "--instrument",
        type=validate_instrument,
        required=False,  
        help="Instrument name to start (e.g., 'Classic', 'Power', 'Grand Piano', 'Recorder')"
    )

    parser.add_argument(
        "-r", "--resolution",
        type=parse_resolution_arg,
        default=parse_resolution_arg("108030"),
        metavar="PROFILE",
        help="Display/FPS profile HEIGHT+FPS (HEIGHT 240..4320, FPS 1..240). Ex: 108030 = 1080p 30fps"
    )

    parser.add_argument(
        "--hands-mc",
        type=parse_hands_model_complexity,
        default=1,
        metavar="VALUE",
        dest="hands_mc",
        help="Hands model complexity (0 or 1, default: 1)."
    )

    parser.add_argument(
        "--pose-mc",
        type=parse_pose_model_complexity,
        default=1,
        metavar="VALUE",
        dest="pose_mc",
        help="Pose model complexity for drums feet model (0..2, default: 1)."
    )
    
    parser.add_argument(
        "-t", "--trackers",
        action="store_true",
        help="Show hand/face trackers on screen (bool flag, default: False)"
    )
    
    # Recording format options are fixed by design (MID + WAV always on)
    
    # Keyboard arguments
    kbd_group = parser.add_argument_group("Keyboard Options")
    kbd_group.add_argument(
        "--kbd-lf", "--keyboard-lf",
        type=float,
        default=None,
        metavar="LIFT_THRESHOLD",
        help="Lift threshold (float > 0, default: 0.02; suggested: 0.005..0.10)."
    )
    kbd_group.add_argument(
        "--kbd-sd", "--keyboard-sd",
        type=float,
        default=None,
        metavar="SUSTAIN_DECAY",
        help="Sustain decay in seconds (float > 0, default: 0.8; suggested: 0.05..5.0)."
    )
    kbd_group.add_argument(
        "--kbd-ts", "--keyboard-ts",
        type=float,
        default=None,
        metavar="TOUCH_TOLERANCE",
        help="Touch sensitivity/tolerance (float > 0, default: 0.005; suggested: 0.001..0.05)."
    )
    
    # Mode argument
    parser.add_argument(
        "--mode",
        choices=["play", "game"],
        default="play",
        metavar="MODE",
        help="Instrument mode: 'play' (default free-play) or 'game' (Genius-style drum challenge)."
    )

    parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard"],
        default="easy",
        metavar="LEVEL",
        help="Game difficulty when --mode game is used: easy | medium | hard (default: easy)."
    )

    parser.add_argument(
        "--song",
        default="Twinkle Twinkle",
        metavar="SONG",
        help=(
            "Song for Piano Tiles game mode (keyboard + --mode game). "
            "Options: 'Twinkle Twinkle', 'Ode to Joy', 'Happy Birthday', "
            "'Mary Had a Little Lamb', 'Jingle Bells (refrao)', 'Random' (default: 'Twinkle Twinkle')."
        ),
    )

    # Drums arguments
    drums_group = parser.add_argument_group("Drums Options")
    drums_group.add_argument(
        "--drm-model", "--drums-model",
        choices=["default", "complete", "override"],
        default="default",
        dest="drums_model",
        help="Drum layout model (string: default|complete|override, default: default)."
    )
    drums_group.add_argument(
        "--drm-elems", "--drums-elements",
        type=parse_drums_elements_arg,
        default=None,
        dest="drm_elems",
        metavar="a,b,c",
        help="Drums elements list (CSV). Allowed: crash,ride,splash,china,tom_hi,tom_mid,tom_low,hihat,open_hh,snare,snare_alt,rimshot,floor,kick,kick_alt,hh_pedal,cowbell,clap,tamb,ride_bell,crash2,ride2,vibra_slap,shaker,cabasa,maracas,guiro_s,guiro_l,agogo_hi,agogo_lo,clave,wood_hi,wood_lo,tri_mute,tri_open,bongo_hi,bongo_mid,bongo_lo,bongo_deep,conga_hi,conga_mid,conga_lo,timbale_hi,timbale_lo."
    )
    drums_group.add_argument(
        "--drm-tt", "--drums-tt",
        type=float,
        default=None,
        metavar="TOUCH_TOLERANCE",
        help="Touch tolerance (float > 0, default: 0.01; suggested: 0.001..0.10)."
    )
    drums_group.add_argument(
        "--drm-tv", "--drums-tv",
        type=float,
        default=None,
        metavar="TOUCH_VELOCITY",
        help="Touch velocity threshold (float > 0, default: 0.012; suggested: 0.001..0.10)."
    )
    
    return parser


def parse_args():
    """Parse command line arguments"""
    # Check for help flag BEFORE parsing (for early exit)
    if "-h" in sys.argv or "--help" in sys.argv:
        print_documentation()
    
    parser = create_argparse()
    args = parser.parse_args()
    
    # Validate that instrument is provided (unless help or test-cam was requested)
    if not args.instrument and not args.help and not args.test_cam:
        parser.print_help()
        print("\nERROR: --instrument is required")
        sys.exit(1)
    
    # Handle help flag
    if args.help:
        print_documentation()
    
    return args


def get_defaults():
    """Load default values from settings"""
    defaults = {
        "keyboard": {
            "sustain": float(getattr(settings, 'KEYBOARD_SUSTAIN_DECAY', getattr(settings, 'SUSTAIN_DECAY', 0.8))),
            "lift": float(getattr(settings, 'KEYBOARD_LIFT_THRESHOLD', getattr(settings, 'LIFT_THRESHOLD', 0.02))),
            "tolerance": float(getattr(settings, 'KEYBOARD_TOUCH_TOLERANCE', getattr(settings, 'TOUCH_TOLERANCE', 0.005))),
        },
        "drums": {
            "tolerance": float(getattr(settings, 'DRUMS_TOUCH_TOLERANCE', 0.01)),
            "touch_velocity": float(getattr(settings, 'DRUMS_TOUCH_VELOCITY', getattr(settings, 'TOUCH_VELOCITY', 0.012))),
        },
        "recording": {
            "mid": bool(getattr(settings, 'RECORD_SAVE_MID', True)),
            "wav": bool(getattr(settings, 'RECORD_SAVE_WAV', True)),
        }
    }
    return defaults


def build_recording_options(args):
    """Build recording options dict from args"""
    return {
        "save_mid": True,
        "save_wav": True,
    }


def detect_auto_model_complexity(resolution_profile):
    """Probe runtime capability and choose model complexities for AUTO mode."""
    hand_complexity = 0
    pose_complexity = 0

    try:
        import cv2
        import mediapipe as mp

        target_fps = int((resolution_profile or {}).get("fps", 30))
        sample_count = 24
        min_ratio = 0.70

        width = int((resolution_profile or {}).get("display_width", 1280))
        height = int((resolution_profile or {}).get("display_height", 720))

        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)

        frames_rgb = []
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, target_fps)
            time.sleep(0.35)

            while len(frames_rgb) < sample_count:
                ok, frame = cap.read()
                if not ok:
                    break
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames_rgb.append(frame_rgb)

            cap.release()

        if not frames_rgb:
            print(">>> AUTO probe: sem frames da câmera; fallback para complexidade mínima.")
            return {
                "hand_model_complexity": hand_complexity,
                "drums_pose_model_complexity": pose_complexity,
            }

        def benchmark_hands(level):
            start_t = time.perf_counter()
            model = mp.solutions.hands.Hands(
                max_num_hands=2,
                model_complexity=level,
                min_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            )
            try:
                for frame_rgb in frames_rgb:
                    model.process(frame_rgb)
            finally:
                model.close()
            elapsed = max(1e-6, time.perf_counter() - start_t)
            return len(frames_rgb) / elapsed

        def benchmark_pose(level):
            start_t = time.perf_counter()
            model = mp.solutions.pose.Pose(
                model_complexity=level,
                min_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            )
            try:
                for frame_rgb in frames_rgb:
                    model.process(frame_rgb)
            finally:
                model.close()
            elapsed = max(1e-6, time.perf_counter() - start_t)
            return len(frames_rgb) / elapsed

        hand_candidate = 0
        for level in (1, 0):
            try:
                measured = benchmark_hands(level)
                if measured >= (target_fps * min_ratio):
                    hand_candidate = level
                    break
            except Exception:
                continue
        hand_complexity = hand_candidate

        pose_candidate = 0
        for level in (2, 1, 0):
            try:
                measured = benchmark_pose(level)
                if measured >= (target_fps * min_ratio):
                    pose_candidate = level
                    break
            except Exception:
                continue
        pose_complexity = pose_candidate

        print(
            f">>> AUTO probe: hands={hand_complexity}, drums_pose={pose_complexity} (target fps={target_fps})"
        )

    except Exception as exc:
        print(f">>> AUTO probe falhou ({exc}); usando fallback seguro.")

    return {
        "hand_model_complexity": hand_complexity,
        "drums_pose_model_complexity": pose_complexity,
    }


def resolve_execution_runtime(args):
    """Resolve effective runtime profile and model complexities from CLI parameters."""
    runtime_config = {
        "hand_model_complexity": int(getattr(args, "hands_mc", 1)),
        "drums_pose_model_complexity": int(getattr(args, "pose_mc", 1)),
    }
    resolution = args.resolution
    return resolution, runtime_config


def start_drums(args, rec_opts, resolution_profile, runtime_config):
    """Start drums instrument (free-play or game mode based on args.mode)"""
    defaults = get_defaults()

    mode = getattr(args, "mode", "play")

    # ── Genius game mode ──────────────────────────────────────────────────
    if mode == "game":
        print(f"\n>>> STARTING GENIUS DRUMS GAME: {args.instrument}")
        print(f"    Drum Model: {args.drums_model}")
        print(f"    Drum Elements: {','.join(args.drm_elems) if args.drm_elems else 'auto(default)'}")
        print(f"    Difficulty: {args.difficulty.upper()}")
        drums_game = safe_import_module("src.instruments.drums_game")
        drums_game.start_drums_game(
            chosen_instrument=args.instrument,
            resolution_profile=resolution_profile,
            show_trackers=args.trackers,
            drum_model=args.drums_model,
            drums_elements=args.drm_elems,
            hand_model_complexity=runtime_config["hand_model_complexity"],
            difficulty=args.difficulty,
        )
        return

    # ── standard free-play mode ───────────────────────────────────────────
    tolerance = args.drm_tt if args.drm_tt is not None else defaults["drums"]["tolerance"]
    touch_velocity = args.drm_tv if args.drm_tv is not None else defaults["drums"]["touch_velocity"]
    
    print(f"\n>>> STARTING DRUMS: {args.instrument}")
    print(f"    Drum Model: {args.drums_model}")
    print(f"    Drum Elements: {','.join(args.drm_elems) if args.drm_elems else 'auto(default)'}")
    if args.drums_model == "override" and not args.drm_elems:
        print("    Aviso: 'override' sem --drm-elems não altera o kit base.")
    print(f"    Tolerance: {tolerance}")
    print(f"    Touch Velocity: {touch_velocity}")
    
    drums = safe_import_module("src.instruments.drums")
    drums.start_drums(
        chosen_instrument=args.instrument,
        user_tolerance=tolerance,
        rec_options=rec_opts,
        touch_velocity=touch_velocity,
        resolution_profile=resolution_profile,
        show_trackers=args.trackers,
        drum_model=args.drums_model,
        drums_elements=args.drm_elems,
        hand_model_complexity=runtime_config["hand_model_complexity"],
        pose_model_complexity=runtime_config["drums_pose_model_complexity"],
    )


def start_keyboard(args, rec_opts, resolution_profile, runtime_config):
    """Start keyboard/piano instrument (free-play or Piano Tiles game mode)."""
    defaults = get_defaults()

    mode = getattr(args, "mode", "play")

    # ── Piano Tiles game mode ─────────────────────────────────────────────
    if mode == "game":
        song = getattr(args, "song", "Twinkle Twinkle")
        print(f"\n>>> STARTING PIANO TILES GAME: {args.instrument}")
        print(f"    Difficulty: {args.difficulty.upper()}")
        print(f"    Song: {song}")
        keyboard_game = safe_import_module("src.instruments.keyboard_game")
        keyboard_game.start_piano_tiles(
            chosen_instrument=args.instrument,
            resolution_profile=resolution_profile,
            show_trackers=args.trackers,
            hand_model_complexity=runtime_config["hand_model_complexity"],
            difficulty=args.difficulty,
            song=song,
        )
        return

    # ── standard free-play mode ───────────────────────────────────────────
    sustain   = args.kbd_sd if args.kbd_sd is not None else defaults["keyboard"]["sustain"]
    lift      = args.kbd_lf if args.kbd_lf is not None else defaults["keyboard"]["lift"]
    tolerance = args.kbd_ts if args.kbd_ts is not None else defaults["keyboard"]["tolerance"]

    print(f"\n>>> STARTING KEYBOARD: {args.instrument}")
    print(f"    Sustain Decay: {sustain}s")
    print(f"    Lift Threshold: {lift}")
    print(f"    Touch Tolerance: {tolerance}")

    keyboard = safe_import_module("src.instruments.keyboard")
    keyboard.start_piano(
        chosen_instrument=args.instrument,
        user_sustain=sustain,
        lift_threshold=lift,
        touch_tolerance=tolerance,
        rec_options=rec_opts,
        resolution_profile=resolution_profile,
        show_trackers=args.trackers,
        hand_model_complexity=runtime_config["hand_model_complexity"],
    )


def main():
    """Main CLI entry point"""
    try:
        
        # Verify and install dependencies if needed
        # if not verify_dependencies_before_launch():
        #     print("ERROR: Could not verify all dependencies. Application cannot start.")
        #     sys.exit(1)
        
        args = parse_args()
        
        # Handle --test-cam early and exit
        if args.test_cam:
            print("\n>>> Running camera + model complexity test...\n")
            # Load test-fps.py module by spec (handles hyphen in filename)
            test_fps_path = PROJECT_ROOT / "src" / "utils" / "test-fps.py"
            spec = importlib.util.spec_from_file_location("test_fps", test_fps_path)
            test_fps_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(test_fps_module)

            best_profile = None
            if hasattr(test_fps_module, "run_camera_profile_test"):
                best_profile = test_fps_module.run_camera_profile_test(print_output=True)

            if best_profile is None:
                best_profile = parse_resolution_arg("72030")

            selected_complexities = detect_auto_model_complexity(best_profile)
            print("\n>>> Suggested standalone runtime config:")
            print(f"    Resolution profile: {best_profile['raw']}")
            print(f"    Hands complexity: {selected_complexities['hand_model_complexity']}")
            print(f"    Pose complexity: {selected_complexities['drums_pose_model_complexity']}")
            print(
                f"    CLI: -r {best_profile['raw']} "
                f"--hands-mc {selected_complexities['hand_model_complexity']} "
                f"--pose-mc {selected_complexities['drums_pose_model_complexity']}"
            )
            sys.exit(0)
        
        # Validate settings
        if not settings.INSTRUMENTS:
            print("ERROR: No instruments found in configuration.")
            sys.exit(1)
        
        # Build recording options
        rec_opts = build_recording_options(args)
        effective_resolution, runtime_config = resolve_execution_runtime(args)
        
        print(f">>> Recording options:")
        print(f"    .MID: {rec_opts['save_mid']}")
        print(f"    .WAV: {rec_opts['save_wav']}")
        print(f"    MIDs folder: {getattr(settings, 'MIDS_DIR', 'recordings/mids')}")
        print(f"    WAV folder: {getattr(settings, 'WAV_DIR', 'recordings/wav')}")
        print(
            f">>> Model complexity: hands={runtime_config['hand_model_complexity']}, "
            f"drums_pose={runtime_config['drums_pose_model_complexity']}"
        )

        if effective_resolution:
            print(f">>> Resolution profile: {effective_resolution['raw']}")
            print(f"    Display: {effective_resolution['display_width']}x{effective_resolution['display_height']}")
            print(f"    Logical: {effective_resolution['logical_width']}x{effective_resolution['logical_height']}")
            print(f"    FPS: {effective_resolution['fps']}")
        
        # Determine instrument type and start
        instrument_type = get_instrument_type(args.instrument)
        
        if instrument_type == "drums":
            start_drums(args, rec_opts, effective_resolution, runtime_config)
        else:  # keyboard
            start_keyboard(args, rec_opts, effective_resolution, runtime_config)
        
        print(">>> Returning to menu...")
        
    except KeyboardInterrupt:
        print("\n>>> Application terminated by user.")
        sys.exit(0)
    except Exception as e:
        print(f">>> ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()