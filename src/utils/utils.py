import sys
import os
from pathlib import Path

def get_asset_path(relative_path):
    """
    Retorna o caminho absoluto para um recurso dentro da pasta 'assets'.
    Lida com o ambiente de desenvolvimento e PyInstaller.
    Exemplo de uso: get_asset_path("fonts/minha_fonte.ttf")
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = Path(__file__).resolve().parent.parent.parent

    # Retorna o caminho completo
    return os.path.join(base_path, "assets", relative_path)