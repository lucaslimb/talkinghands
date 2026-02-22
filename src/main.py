#!/usr/bin/env python3
"""
Talking Hands CLI Launcher
Command-line interface for Talking Hands computer vision instruments platform.
"""
import argparse
import sys
import os
import re
from importlib import import_module, reload
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
    catalog = {"keyboard": [], "drums": [], "flute": []}
    
    for name, data in settings.INSTRUMENTS.items():
        sf_key = data[0]
        if sf_key == "drums":
            catalog["drums"].append(name)
        elif sf_key == "flute":
            catalog["flute"].append(name)
        else:
            catalog["keyboard"].append(name)
    
    return catalog

def validate_instrument(value):
    """Validate that the instrument exists"""
    catalog = get_available_instruments()
    all_instruments = catalog["keyboard"] + catalog["drums"] + catalog["flute"]
    
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

def get_instrument_type(instrument_name):
    """Determine instrument type from name"""
    catalog = get_available_instruments()
    
    if instrument_name in catalog["drums"]:
        return "drums"
    elif instrument_name in catalog["flute"]:
        return "flute"
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
  -i, --instrument INSTRUMENT_NAME   Instrument name to start (e.g., 'Perfect Drums 1', 'Grand Piano', 'Recorder')
    -r, --resolution PROFILE           Resolution/FPS profile (HEIGHT+FPS). HEIGHT min/max: 240..4320, FPS min/max: 1..240 (default: 108030)
    -t, --trackers                     Show hand/face trackers on screen (boolean flag: False|True, default: False)
    -f, --separate-folders             Keep playback and recordings in different folders (boolean flag: False|True, default: False)

RECORDING FORMATS OPTIONS:
    --mid                              Save .MID files (boolean flag: False|True, default: True)
    --no-mid                           Disable .MID file saving (sets --mid=False)
    --mp3                              Save .MP3 files (boolean flag: False|True, default: False)
    --wav                              Save .WAV files (boolean flag: False|True, default: False)

KEYBOARD OPTIONS:
    --kbd-lf LIFT_THRESHOLD            Lift threshold (float > 0, default: 0.02; suggested: 0.005..0.10)
    --kbd-sd SUSTAIN_DECAY             Sustain decay seconds (float > 0, default: 0.8; suggested: 0.05..5.0)
    --kbd-ts TOUCH_TOLERANCE           Touch tolerance (float > 0, default: 0.005; suggested: 0.001..0.05)

DRUMS OPTIONS:
    --drm-model {default,complete}      Drum layout model (string values: default|complete, default: default)
    --drm-tt TOUCH_TOLERANCE            Touch tolerance (float > 0, default: 0.01; suggested: 0.001..0.10)
    --drm-tv TOUCH_VELOCITY             Touch velocity threshold (float > 0, default: 0.012; suggested: 0.001..0.10)

FLUTE OPTIONS:
    --flt-inv                           Invert blow logic (boolean flag: False|True, default: False)
    --flt-ang-inv                       Invert flute angle follow (boolean flag: False|True, default: False)
    --flt-max MOUTH_MAX                 Maximum mouth opening threshold (float > 0, default: 0.05; suggested: 0.005..0.20)
    --flt-min MOUTH_MIN                 Minimum/peak mouth opening threshold (float > 0, default: 0.01; suggested: 0.001..0.10)
    --flt-fs VALUE                      Mouth-follow sensitivity (float min/max: 0.0..1.0, default: 0.22)
    --flt-p {small,medium,large}        Hole size preset (string values: small|medium|large, default: medium)

EXAMPLES:
  python main.py -i "Perfect Drums 1" -tf
    python main.py -i "Piano" -r 108030
    python main.py -i "Grand Piano" --kbd-sd 0.5 --kbd-lf 0.025
    python main.py -i "Recorder" --flt-max 0.06 --flt-p medium
    python main.py -i "Quality Flute" --flt-inv --flt-ang-inv
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
        epilog="""
    Examples:
    python main.py -i "Perfect Drums 1" -tf
    python main.py -i "Grand Piano" --kbd-sd 0.5 --kbd-lf 0.025
    python main.py -i "Recorder" --flt-max 0.06 --flt-p medium
    python main.py -i "Quality Flute" --flt-inv --flt-ang-inv
        """
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
        required=False,  # Made optional to allow help without instrument
        help="Instrument name to start (e.g., 'Perfect Drums 1', 'Grand Piano', 'Recorder')"
    )

    parser.add_argument(
        "-r", "--resolution",
        type=parse_resolution_arg,
        default=parse_resolution_arg("108030"),
        metavar="PROFILE",
        help="Display/FPS profile HEIGHT+FPS (HEIGHT 240..4320, FPS 1..240). Ex: 108030 = 1080p 30fps"
    )
    
    parser.add_argument(
        "-t", "--trackers",
        action="store_true",
        help="Show hand/face trackers on screen (bool flag, default: False)"
    )
    
    parser.add_argument(
        "-f", "--separate-folders",
        action="store_true",
        help="Keep playback and recordings in different folders (bool flag, default: False)"
    )
    
    # Recording format options
    rec_group = parser.add_argument_group("Recording Formats")
    rec_group.add_argument(
        "--mid",
        action="store_true",
        default=True,
        help="Save .MID files (bool flag, default: True)"
    )
    rec_group.add_argument(
        "--no-mid",
        action="store_false",
        dest="mid",
        help="Disable .MID file saving"
    )
    rec_group.add_argument(
        "--mp3",
        action="store_true",
        help="Save .MP3 files (bool flag, default: False)"
    )
    rec_group.add_argument(
        "--wav",
        action="store_true",
        help="Save .WAV files (bool flag, default: False)"
    )
    
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
    
    # Drums arguments
    drums_group = parser.add_argument_group("Drums Options")
    drums_group.add_argument(
        "--drm-model", "--drums-model",
        choices=["default", "complete"],
        default="default",
        dest="drums_model",
        help="Drum layout model (string: default|complete, default: default)."
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
    
    # Flute arguments
    flute_group = parser.add_argument_group("Flute Options")
    flute_group.add_argument(
        "--flt-inv", "--flute-inv",
        action="store_true",
        dest="flute_invert",
        help="Invert blow logic (bool flag, default: False)."
    )

    flute_group.add_argument(
        "--flt-ang-inv", "--flute-angle-inv",
        action="store_true",
        dest="flute_angle_invert",
        help="Invert flute angle follow (bool flag, default: False)."
    )

    flute_group.add_argument(
        "--flt-max", "--flute-max",
        type=float,
        default=None,
        metavar="MOUTH_MAX",
        help="Maximum mouth opening threshold (float > 0, default: 0.05; suggested: 0.005..0.20)."
    )
    flute_group.add_argument(
        "--flt-min", "--flute-min",
        type=float,
        default=None,
        metavar="MOUTH_MIN",
        help="Minimum/peak mouth opening threshold (float > 0, default: 0.01; suggested: 0.001..0.10)."
    )
    flute_group.add_argument(
        "--flt-fs", "--flute-follow-sens",
        type=float,
        default=0.22,
        metavar="VALUE",
        dest="flute_follow_sens",
        help="Mouth-follow sensitivity (float 0.0..1.0, default: 0.22)."
    )
    flute_group.add_argument(
        "--flt-p", "--flute-p", "--flute-precision",
        choices=["small", "medium", "large"],
        default="medium",
        dest="flute_precision",
        help="Hole size preset (string: small|medium|large, default: medium)."
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
        "flute": {
            "mouth_peak": float(getattr(settings, 'FLUTE_MOUTH_PEAK_OPEN', getattr(settings, 'MOUTH_PEAK_OPEN', 0.01))),
            "mouth_max": float(getattr(settings, 'FLUTE_MOUTH_MAX_OPEN', getattr(settings, 'MOUTH_MAX_OPEN', 0.05))),
        },
        "recording": {
            "mid": bool(getattr(settings, 'RECORD_SAVE_MID', True)),
            "mp3": bool(getattr(settings, 'RECORD_SAVE_MP3', False)),
            "wav": bool(getattr(settings, 'RECORD_SAVE_WAV', False)),
            "separate_playback": bool(getattr(settings, 'RECORD_SEPARATE_PLAYBACK_FOLDER', False)),
        }
    }
    return defaults


def build_recording_options(args):
    """Build recording options dict from args"""
    defaults = get_defaults()
    
    return {
        "save_mid": args.mid,
        "save_mp3": args.mp3,
        "save_wav": args.wav,
        "separate_playback": args.separate_folders or defaults["recording"]["separate_playback"]
    }


def get_flute_hole_params(precision):
    """Convert precision string to hole parameters"""
    params = {
        "small": (0.015, 0.058),
        "medium": (
            float(getattr(settings, 'FLUTE_HOLE_RADIUS', getattr(settings, 'HOLE_RADIUS', 0.019))),
            float(getattr(settings, 'FLUTE_HOLE_SPACING', getattr(settings, 'HOLE_SPACING', 0.068))),
        ),
        "large": (0.023, 0.077),
    }
    return params.get(precision, params["medium"])


def start_drums(args, rec_opts):
    """Start drums instrument"""
    defaults = get_defaults()
    
    # Use provided values or defaults
    tolerance = args.drums_tt if args.drums_tt is not None else defaults["drums"]["tolerance"]
    touch_velocity = args.drums_tv if args.drums_tv is not None else defaults["drums"]["touch_velocity"]
    
    print(f"\n>>> STARTING DRUMS: {args.instrument}")
    print(f"    Drum Model: {args.drums_model}")
    print(f"    Tolerance: {tolerance}")
    print(f"    Touch Velocity: {touch_velocity}")
    
    drums = safe_import_module("src.instruments.drums")
    drums.start_drums(
        chosen_instrument=args.instrument,
        user_tolerance=tolerance,
        rec_options=rec_opts,
        touch_velocity=touch_velocity,
        resolution_profile=args.resolution,
        show_trackers=args.trackers,
        drum_model=args.drums_model,
    )


def start_flute(args, rec_opts):
    """Start flute instrument"""
    defaults = get_defaults()
    
    # Use provided values or defaults
    mouth_peak = args.flute_min if args.flute_min is not None else defaults["flute"]["mouth_peak"]
    mouth_max = args.flute_max if args.flute_max is not None else defaults["flute"]["mouth_max"]
    hole_radius, hole_spacing = get_flute_hole_params(args.flute_precision)
    
    print(f"\n>>> STARTING FLUTE: {args.instrument}")
    print(f"    Mouth Peak: {mouth_peak}")
    print(f"    Mouth Max: {mouth_max}")
    print(f"    Precision: {args.flute_precision}")
    print(f"    Invert Blow: {args.flute_invert}")
    print(f"    Invert Angle: {args.flute_angle_invert}")
    print(f"    Follow Sensitivity: {args.flute_follow_sens}")
    
    flute = safe_import_module("src.instruments.flute")
    reload(flute)
    
    flute.start_flute(
        chosen_instrument=args.instrument,
        mouth_peak=mouth_peak,
        mouth_max=mouth_max,
        hole_radius=hole_radius,
        hole_spacing=hole_spacing,
        invert_blow=args.flute_invert,
        invert_angle=args.flute_angle_invert,
        follow_sensitivity=args.flute_follow_sens,
        rec_options=rec_opts,
        resolution_profile=args.resolution,
        show_trackers=args.trackers,
    )


def start_keyboard(args, rec_opts):
    """Start keyboard/piano instrument"""
    defaults = get_defaults()
    
    # Use provided values or defaults
    sustain = args.keyboard_sd if args.keyboard_sd is not None else defaults["keyboard"]["sustain"]
    lift = args.keyboard_lf if args.keyboard_lf is not None else defaults["keyboard"]["lift"]
    tolerance = args.keyboard_ts if args.keyboard_ts is not None else defaults["keyboard"]["tolerance"]
    
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
        resolution_profile=args.resolution,
        show_trackers=args.trackers,
    )


def main():
    """Main CLI entry point"""
    try:
        
        # Verify and install dependencies if needed
        # if not verify_dependencies_before_launch():
        #     print("ERROR: Could not verify all dependencies. Application cannot start.")
        #     sys.exit(1)
        
        args = parse_args()
        
        # Handle --test-fps early and exit
        if args.test_cam:
            print("\n>>> Running FPS test...\n")
            # Load test-fps.py module by spec (handles hyphen in filename)
            test_fps_path = PROJECT_ROOT / "src" / "utils" / "test-fps.py"
            spec = importlib.util.spec_from_file_location("test_fps", test_fps_path)
            test_fps_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(test_fps_module)
            # The module runs the test automatically and prints results
            sys.exit(0)
        
        # Validate settings
        if not settings.INSTRUMENTS:
            print("ERROR: No instruments found in configuration.")
            sys.exit(1)
        
        # Build recording options
        rec_opts = build_recording_options(args)
        
        print(f">>> Recording options:")
        print(f"    .MID: {rec_opts['save_mid']}")
        print(f"    .MP3: {rec_opts['save_mp3']}")
        print(f"    .WAV: {rec_opts['save_wav']}")
        print(f"    Separate folders: {rec_opts['separate_playback']}")

        if args.resolution:
            print(f">>> Resolution profile: {args.resolution['raw']}")
            print(f"    Display: {args.resolution['display_width']}x{args.resolution['display_height']}")
            print(f"    Logical: {args.resolution['logical_width']}x{args.resolution['logical_height']}")
            print(f"    FPS: {args.resolution['fps']}")
        
        # Determine instrument type and start
        instrument_type = get_instrument_type(args.instrument)
        
        if instrument_type == "drums":
            start_drums(args, rec_opts)
        elif instrument_type == "flute":
            start_flute(args, rec_opts)
        else:  # keyboard
            start_keyboard(args, rec_opts)
        
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