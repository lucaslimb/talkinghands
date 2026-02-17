#!/usr/bin/env python3
"""
Build script for Talking Hands executable
Creates a standalone .exe file without Python dependencies
Run: python build.py
"""

import subprocess
import sys
from pathlib import Path
import shutil

version = "1.0.0"

def run_command(cmd, description, use_shell=False):
    """Run a command and handle errors"""
    print(f"[*] {description}...")
    result = subprocess.run(cmd, shell=use_shell)
    if result.returncode != 0:
        print(f"[ERROR] {description} failed")
        sys.exit(1)
    print(f"[+] {description} complete")

def main():
    print("\n" + "="*50)
    print("Talking Hands - Build Executable")
    print("="*50 + "\n")
    
    # Get project root
    project_root = Path(__file__).resolve().parent
    
    # Check PyInstaller
    print("[*] Checking PyInstaller...")
    result = subprocess.run([sys.executable, "-m", "pip", "show", "pyinstaller"], 
                          capture_output=True)
    if result.returncode != 0:
        print("[!] PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                      check=True)
    print("[+] PyInstaller is ready\n")
    
    # Clean previous builds
    print("[*] Cleaning previous builds...")
    for folder in ["dist", "build", "__pycache__"]:
        folder_path = project_root / folder
        if folder_path.exists():
            shutil.rmtree(folder_path)
            print(f"    Removed {folder}")
    print("[+] Cleanup complete\n")
    
    # Build with PyInstaller
    print("[*] Building executable (this may take 5-10 minutes)...")
    print("    This bundles Python, all dependencies, and assets...\n")
    
    # Get mediapipe path for data collection
    mediapipe_path = Path(sys.prefix) / "Lib" / "site-packages" / "mediapipe"
    
    # Use list format to avoid shell parsing issues with spaces in paths
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "THEngine",
        "--console",  # Show console for CLI output
        "--icon=assets/icon.ico",
        "--add-data", "assets/soundfonts:assets/soundfonts",
        "--add-data", "assets/fonts:assets/fonts",
        "--add-data", "src/config/:src/config",
        "--add-data", "src/instruments/:src/instruments",
        "--add-data", "src/engines/:src/engines",
        "--add-data", "src/utils/:src/utils",
        # MediaPipe data files (critical for hand/face tracking)
        "--add-data", f"{mediapipe_path}:mediapipe",
        # Standard library modules
        "--hidden-import=wave",
        "--hidden-import=struct",
        "--hidden-import=shutil",
        "--hidden-import=subprocess",
        "--hidden-import=queue",
        "--hidden-import=ctypes",
        "--hidden-import=math",
        "--hidden-import=argparse",
        "--hidden-import=threading",
        # Third-party packages
        "--hidden-import=cv2",
        "--hidden-import=mediapipe",
        "--hidden-import=fluidsynth",
        "--hidden-import=pyfluidsynth",
        "--hidden-import=pygame",
        "--hidden-import=customtkinter",
        "--hidden-import=mido",
        "--hidden-import=sounddevice",
        "--hidden-import=numpy",
        # MediaPipe submodules
        "--collect-submodules", "mediapipe",
        "src/main.py"
    ]
    
    run_command(cmd, "Building executable")
    
    print("\n" + "="*50)
    print("[+] Build Successful!")
    print("="*50 + "\n")
    
    exe_path = project_root / "dist" / "THEngine.exe"
    print(f"Executable location: {exe_path}\n")

if __name__ == "__main__":
    main()
