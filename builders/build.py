#!/usr/bin/env python3
"""
Build script for Talking Hands executable (Windows)
Creates a standalone .exe file without Python dependencies
Generates a distribution package with installer scripts

Run from project root: python builders/build.py
Or from builders folder: python build.py
"""

import subprocess
import sys
from pathlib import Path
import shutil
import zipfile

def run_command(cmd, description, use_shell=False):
    """Run a command and handle errors"""
    print(f"[*] {description}...")
    result = subprocess.run(cmd, shell=use_shell)
    if result.returncode != 0:
        print(f"[ERROR] {description} failed")
        sys.exit(1)
    print(f"[+] {description} complete")

def create_distribution_package(project_root, exe_path):
    """Create a zip file with exe and installer scripts in separate folders"""
    
    print("\n[*] Creating distribution package...")
    
    install_source = project_root / "installers" / "windows" / "install.bat"
    uninstall_source = project_root / "installers" / "windows" / "uninstall.bat"
    
    # Create zip package
    zip_name = "TalkingHands.zip"
    zip_path = project_root / zip_name
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add executable to root of zip
            if exe_path.exists():
                zipf.write(exe_path, arcname=exe_path.name)
                print(f"    Added {exe_path.name}")
            
            # Add installer scripts to 'installer' folder in zip
            if install_source.exists():
                zipf.write(install_source, arcname=f"installer/{install_source.name}")
                print(f"    Added installer/install.bat")
            
            if uninstall_source.exists():
                zipf.write(uninstall_source, arcname=f"installer/{uninstall_source.name}")
                print(f"    Added installer/uninstall.bat")
            
            # Add README to root
            readme_path = project_root / "README.md"
            if readme_path.exists():
                zipf.write(readme_path, arcname="README.md")
                print(f"    Added README.md")
        
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"\n[+] Package created: {zip_path.name}")
        print(f"    Size: {size_mb:.1f} MB")
        
        return zip_path
    except Exception as e:
        print(f"[ERROR] Failed to create zip: {e}")
        return None

def main():
    print("\n" + "="*60)
    print("Talking Hands - Build Executable (Windows)")
    print("="*60 + "\n")
    
    # Get project root (parent of builders/ folder)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    
    print(f"Project root: {project_root}\n")
    
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
    for folder in ["dist", "build/.exe_build", "__pycache__"]:
        folder_path = project_root / folder if not folder.startswith("build/") else script_dir / folder.replace("build/", "")
        if folder_path.exists():
            shutil.rmtree(folder_path)
            print(f"    Removed {folder}")
    print("[+] Cleanup complete\n")
    
    # Change to project root for PyInstaller
    import os
    original_cwd = os.getcwd()
    os.chdir(project_root)
    
    try:
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
        
        print("\n" + "="*60)
        print("[+] Build Successful!")
        print("="*60 + "\n")
        
        exe_path = project_root / "dist" / "THEngine.exe"
        
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"Executable: {exe_path}")
            print(f"Size: {size_mb:.1f} MB\n")
            
            # Create distribution package
            zip_path = create_distribution_package(project_root, exe_path)
            
            print("\n" + "="*60)
            print("DISTRIBUTION PACKAGE READY")
            print("="*60 + "\n")
            
            if zip_path:
                print(f"Distribution ZIP: {zip_path}\n")
            
        else:
            print(f"[ERROR] Executable not found at {exe_path}\n")
    
    finally:
        os.chdir(original_cwd)

if __name__ == "__main__":
    main()
