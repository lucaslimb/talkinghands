"""Teste manual do LED: azul, verde, vermelho e desligamento."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Permite executar diretamente `python scripts\test_lighting.py` a partir da raiz.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engines.lighting_controller import LightingController


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="Porta serial do Arduino, por exemplo COM3")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    colors = (
        ("azul", (0, 0, 255)),
        ("verde", (0, 255, 0)),
        ("vermelho", (255, 0, 0)),
    )
    controller = None
    try:
        controller = LightingController(args.port)
        for name, (red, green, blue) in colors:
            print(f"Acendendo {name}...")
            controller.set_color(red, green, blue)
            time.sleep(args.interval)
    finally:
        if controller is not None:
            print("Apagando LED e encerrando.")
            try:
                if controller.is_connected:
                    controller.off()
            finally:
                controller.close()


if __name__ == "__main__":
    main()
