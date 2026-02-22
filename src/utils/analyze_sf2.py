#!/usr/bin/env python3
"""
Analyze SoundFont (.sf2) files and list presets/instruments.

Usage examples:
  python src/utils/analyze_sf2.py --sf2 assets/soundfonts/drums/Drums.sf2
  python src/utils/analyze_sf2.py --all
  python src/utils/analyze_sf2.py --sf2 assets/soundfonts/drums/Drums.sf2 --json

Notes:
- This script uses sf2utils for direct SF2 parsing.
- If sf2utils is not installed, the script prints install guidance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _decode_name(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").replace("\x00", "").strip()
    return str(value).replace("\x00", "").strip()


def _get_attr(obj: Any, candidates: list[str], default: Any = None) -> Any:
    for attr in candidates:
        if hasattr(obj, attr):
            return getattr(obj, attr)
    return default


def _is_sentinel_instrument(inst: Any) -> bool:
    attr = _get_attr(inst, ["is_sentinel"], False)
    try:
        return bool(attr()) if callable(attr) else bool(attr)
    except Exception:
        return False


def _extract_presets(sf2_obj: Any) -> list[dict[str, Any]]:
    presets = []
    for preset in getattr(sf2_obj, "presets", []):
        name = _decode_name(_get_attr(preset, ["name", "preset_name"]))
        bank = _get_attr(preset, ["bank", "bank_id"], None)
        program = _get_attr(preset, ["preset", "program", "preset_id"], None)

        if not name or name.upper() == "EOP" or bank is None or program is None:
            continue

        presets.append(
            {
                "name": name,
                "bank": bank,
                "program": program,
            }
        )
    presets.sort(key=lambda p: ((p["bank"] if p["bank"] is not None else 9999), (p["program"] if p["program"] is not None else 9999), p["name"]))
    return presets


def _extract_instruments(sf2_obj: Any) -> list[str]:
    names = []
    for inst in getattr(sf2_obj, "instruments", []):
        if _is_sentinel_instrument(inst):
            continue
        name = _decode_name(_get_attr(inst, ["name", "instrument_name"]))
        if name and name.upper() != "EOI":
            names.append(name)
    return sorted(set(names))


def _collect_instrument_details(sf2_obj: Any) -> list[dict[str, Any]]:
    details = []
    for inst in getattr(sf2_obj, "instruments", []):
        if _is_sentinel_instrument(inst):
            continue

        name = _decode_name(_get_attr(inst, ["name", "instrument_name"]))
        if not name or name.upper() == "EOI":
            continue

        samples = []
        for s in _get_attr(inst, ["samples"], []) or []:
            s_name = _decode_name(_get_attr(s, ["name"]))
            if s_name:
                samples.append(s_name)

        details.append(
            {
                "name": name,
                "sample_count": len(samples),
                "samples": sorted(set(samples)),
            }
        )

    details.sort(key=lambda x: x["name"])
    return details


def _group_preset_key_layers(preset_obj: Any) -> list[dict[str, Any]]:
    keys = list(getattr(preset_obj, "key_range", []))
    if not keys:
        return []

    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for key in keys:
        inst_names = []
        sample_names = []

        try:
            for inst in preset_obj.key_instruments(key) or []:
                n = _decode_name(_get_attr(inst, ["name", "instrument_name"]))
                if n and n.upper() != "EOI":
                    inst_names.append(n)
        except Exception:
            pass

        try:
            for sample in preset_obj.key_samples(key) or []:
                n = _decode_name(_get_attr(sample, ["name"]))
                if n:
                    sample_names.append(n)
        except Exception:
            pass

        inst_names = sorted(set(inst_names))
        sample_names = sorted(set(sample_names))
        signature = (tuple(inst_names), tuple(sample_names))

        if current is None:
            current = {
                "key_from": key,
                "key_to": key,
                "instruments": inst_names,
                "samples": sample_names,
                "_sig": signature,
            }
            continue

        if key == current["key_to"] + 1 and signature == current["_sig"]:
            current["key_to"] = key
        else:
            current.pop("_sig", None)
            groups.append(current)
            current = {
                "key_from": key,
                "key_to": key,
                "instruments": inst_names,
                "samples": sample_names,
                "_sig": signature,
            }

    if current is not None:
        current.pop("_sig", None)
        groups.append(current)

    return groups


def _collect_preset_details(sf2_obj: Any) -> list[dict[str, Any]]:
    details = []
    for preset in getattr(sf2_obj, "presets", []):
        name = _decode_name(_get_attr(preset, ["name", "preset_name"]))
        bank = _get_attr(preset, ["bank", "bank_id"], None)
        program = _get_attr(preset, ["preset", "program", "preset_id"], None)
        if not name or name.upper() == "EOP" or bank is None or program is None:
            continue

        layers = _group_preset_key_layers(preset)
        details.append(
            {
                "name": name,
                "bank": bank,
                "program": program,
                "layer_group_count": len(layers),
                "layers": layers,
            }
        )

    details.sort(key=lambda p: (p["bank"], p["program"], p["name"]))
    return details


def analyze_sf2_file(sf2_path: Path, deep: bool = False) -> dict[str, Any]:
    try:
        from sf2utils.sf2parse import Sf2File
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency 'sf2utils'. Install with: pip install sf2utils"
        ) from exc

    with sf2_path.open("rb") as handle:
        sf2_obj = Sf2File(handle)

    presets = _extract_presets(sf2_obj)
    instruments = _extract_instruments(sf2_obj)

    preset_details = _collect_preset_details(sf2_obj) if deep else []
    instrument_details = _collect_instrument_details(sf2_obj) if deep else []

    result = {
        "file": str(sf2_path),
        "preset_count": len(presets),
        "instrument_count": len(instruments),
        "presets": presets,
        "instruments": instruments,
    }

    if deep:
        result["preset_details"] = preset_details
        result["instrument_details"] = instrument_details

    return result


def _collect_sf2_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []

    if args.sf2:
        for raw in args.sf2:
            path = Path(raw)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            paths.append(path.resolve())

    if args.all:
        try:
            from src.config import settings

            for sf2_file in settings.SF2_PATHS.values():
                p = Path(sf2_file)
                if p.exists():
                    paths.append(p.resolve())
        except Exception:
            pass

        assets_soundfonts = PROJECT_ROOT / "assets" / "soundfonts"
        if assets_soundfonts.exists():
            for p in assets_soundfonts.rglob("*.sf2"):
                paths.append(p.resolve())

    unique = []
    seen = set()
    for p in paths:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique


def _print_human(result: dict[str, Any]) -> None:
    print(f"\n=== {result['file']} ===")
    print(f"Presets: {result['preset_count']}")
    print(f"Instruments: {result['instrument_count']}")

    print("\n[Presets]")
    if result["presets"]:
        for p in result["presets"]:
            bank = "?" if p["bank"] is None else p["bank"]
            program = "?" if p["program"] is None else p["program"]
            print(f"  - B:{bank} P:{program} | {p['name']}")
    else:
        print("  (none)")

    print("\n[Instruments]")
    if result["instruments"]:
        for name in result["instruments"]:
            print(f"  - {name}")
    else:
        print("  (none)")

    if "preset_details" in result:
        print("\n[Preset Layers]")
        for preset in result["preset_details"]:
            print(f"  * {preset['name']} (B:{preset['bank']} P:{preset['program']})")
            for layer in preset["layers"]:
                kf = layer["key_from"]
                kt = layer["key_to"]
                kr = f"{kf}" if kf == kt else f"{kf}-{kt}"
                inst_txt = ", ".join(layer["instruments"]) if layer["instruments"] else "(none)"
                smp_txt = ", ".join(layer["samples"]) if layer["samples"] else "(none)"
                print(f"    - Keys {kr} | Inst: {inst_txt}")
                print(f"      Samples: {smp_txt}")

    if "instrument_details" in result:
        print("\n[Instrument Sample Lists]")
        for inst in result["instrument_details"]:
            print(f"  * {inst['name']} ({inst['sample_count']} samples)")
            for s in inst["samples"]:
                print(f"    - {s}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze .sf2 files and list presets/instruments"
    )
    parser.add_argument(
        "--sf2",
        nargs="+",
        help="One or more .sf2 file paths (relative to project root or absolute)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze all known SF2 files from settings/assets",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Include deep details: preset key layers and per-instrument sample lists",
    )

    args = parser.parse_args()

    if not args.sf2 and not args.all:
        parser.error("Use --sf2 <path> or --all")

    sf2_paths = _collect_sf2_paths(args)
    if not sf2_paths:
        print("No .sf2 files found for the requested input.")
        return 1

    results: list[dict[str, Any]] = []
    for sf2_path in sf2_paths:
        if not sf2_path.exists():
            print(f"[!] File not found: {sf2_path}")
            continue

        try:
            results.append(analyze_sf2_file(sf2_path, deep=args.deep))
        except RuntimeError as err:
            print(f"[!] {err}")
            return 2
        except Exception as err:
            print(f"[!] Failed to analyze {sf2_path}: {err}")

    if not results:
        return 1

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for result in results:
            _print_human(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
