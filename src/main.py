#!/usr/bin/env python3
"""
Talking Hands CLI Launcher
Command-line interface for Talking Hands computer vision instruments platform.
"""
import argparse
import sys
import os
from importlib import import_module, reload
from pathlib import Path

# Setup imports
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.config import settings

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

def get_instrument_type(instrument_name):
    """Determine instrument type from name"""
    catalog = get_available_instruments()
    
    if instrument_name in catalog["drums"]:
        return "drums"
    elif instrument_name in catalog["flute"]:
        return "flute"
    else:
        return "keyboard"

def create_argparse():
    """Create and configure the argument parser"""
    parser = argparse.ArgumentParser(
        prog="Talking Hands",
        description="Virtual instrument platform using computer vision",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Examples:
    python main.py -i "Perfect Drums 1" -tf
    python main.py -i "Grand Piano" --piano-sd 0.5 --piano-lf 0.025
    python main.py -i "Recorder" --flute-max 0.06 --flute-p medium
    python main.py -i "Quality Flute" --flute-invert
        """
    )
    
    # Global arguments
    parser.add_argument(
        "-i", "--instrument",
        type=validate_instrument,
        required=True,
        help="Instrument name to start (e.g., 'Perfect Drums 1', 'Grand Piano', 'Recorder')"
    )
    
    parser.add_argument(
        "-s", "--sound",
        type=str,
        help="Alias for --instrument"
    )
    
    parser.add_argument(
        "-t", "--trackers",
        action="store_true",
        help="Show hand/face trackers on screen (default: off)"
    )
    
    parser.add_argument(
        "-f", "--separate-folders",
        action="store_true",
        help="Keep playback and recordings in different folders (default: all in recordings)"
    )
    
    # Recording format options
    rec_group = parser.add_argument_group("Recording Formats")
    rec_group.add_argument(
        "--mid",
        action="store_true",
        default=True,
        help="Save .MID files (default: enabled)"
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
        help="Save .MP3 files (default: disabled)"
    )
    rec_group.add_argument(
        "--wav",
        action="store_true",
        help="Save .WAV files (default: disabled)"
    )
    
    # Keyboard arguments
    kbd_group = parser.add_argument_group("Keyboard Options")
    kbd_group.add_argument(
        "--keyboard-lf",
        type=float,
        default=None,
        metavar="LIFT_THRESHOLD",
        help="Lift threshold in normalized units (default: 0.02). Quanto maior o valor, mais alto é preciso levantar o dedo para tocar uma nota."
    )
    kbd_group.add_argument(
        "--keyboard-sd",
        type=float,
        default=None,
        metavar="SUSTAIN_DECAY",
        help="Sustain decay in seconds (default: 0.8). Tempo de sustentação da nota após ser tocada. Valores menores resultam em notas mais curtas, enquanto valores maiores permitem que as notas soem por mais tempo."
    )
    kbd_group.add_argument(
        "--keyboard-ts",
        type=float,
        default=None,
        metavar="TOUCH_TOLERANCE",
        help="Touch sensitivity/tolerance in normalized units (default: 0.005). Quanto maior o valor, mais permissivo é o sistema para reconhecer um toque, quanto menor, mais preciso e exigente será o reconhecimento do toque."
    )
    
    # Drums arguments
    drums_group = parser.add_argument_group("Drums Options")
    drums_group.add_argument(
        "--drums-tt",
        type=float,
        default=None,
        metavar="TOUCH_TOLERANCE",
        help="Touch tolerance as normalized value (default: 0.01). Quanto maior a porcentagem, maior será a área de contato com os tambores, pratos, bumbo."
    )
    drums_group.add_argument(
        "--drums-tv",
        type=float,
        default=None,
        metavar="TOUCH_VELOCITY",
        help="Touch velocity threshold (default: 0.012). Quanto maior, mais rápido você precisa mover a mão para gerar um som mais alto."
    )
    
    # Flute arguments
    flute_group = parser.add_argument_group("Flute Options")
    flute_group.add_argument(
        "--flute-inv",
        action="store_true",
        dest="flute_invert",
        help="Invert blow logic (higher mouth opening = louder) (default: lower mouth opening = louder)"
    )

    flute_group.add_argument(
        "--flute-max",
        type=float,
        default=None,
        metavar="MOUTH_MAX",
        help="Maximum mouth opening threshold (default: 0.05)"
    )
    flute_group.add_argument(
        "--flute-min",
        type=float,
        default=None,
        metavar="MOUTH_MIN",
        help="Minimum mouth opening threshold / peak (default: 0.01)"
    )
    flute_group.add_argument(
        "--flute-p",
        "--flute-precision",
        choices=["small", "medium", "large"],
        default="medium",
        dest="flute_precision",
        help="Hole size and spacing (default: medium)"
    )
    
    return parser


def parse_args():
    """Parse command line arguments"""
    parser = create_argparse()
    args = parser.parse_args()
    
    # Handle --sound as alias for --instrument
    if args.sound and not args.instrument:
        args.instrument = validate_instrument(args.sound)
    
    return args


def get_defaults():
    """Load default values from settings"""
    defaults = {
        "keyboard": {
            "sustain": float(getattr(settings, 'SUSTAIN_DECAY', 0.8)),
            "lift": float(getattr(settings, 'LIFT_THRESHOLD', 0.02)),
            "tolerance": float(getattr(settings, 'TOUCH_TOLERANCE', 0.005)),
        },
        "drums": {
            "tolerance": float(getattr(settings, 'TOUCH_TOLERANCE', 0.01)),
            "touch_velocity": float(getattr(settings, 'TOUCH_VELOCITY', 0.012)),
        },
        "flute": {
            "mouth_peak": float(getattr(settings, 'MOUTH_PEAK_OPEN', 0.01)),
            "mouth_max": float(getattr(settings, 'MOUTH_MAX_OPEN', 0.05)),
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
        "medium": (0.019, 0.068),
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
    print(f"    Tolerance: {tolerance}")
    print(f"    Touch Velocity: {touch_velocity}")
    
    drums = import_module("src.instruments.drums")
    drums.start_drums(
        chosen_instrument=args.instrument,
        user_tolerance=tolerance,
        rec_options=rec_opts,
        touch_velocity=touch_velocity,
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
    
    flute = import_module("src.instruments.flute")
    reload(flute)
    
    flute.start_flute(
        chosen_instrument=args.instrument,
        mouth_peak=mouth_peak,
        mouth_max=mouth_max,
        hole_radius=hole_radius,
        hole_spacing=hole_spacing,
        invert_blow=args.flute_invert,
        rec_options=rec_opts
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
    
    keyboard = import_module("src.instruments.keyboard")
    keyboard.start_piano(
        chosen_instrument=args.instrument,
        user_sustain=sustain,
        lift_threshold=lift,
        touch_tolerance=tolerance,
        rec_options=rec_opts
    )


def main():
    """Main CLI entry point"""
    try:
        args = parse_args()
        
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