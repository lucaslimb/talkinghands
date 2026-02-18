#!/usr/bin/env python3
"""
FluidSynth 2.5.1 Setup for Talking Hands
Downloads and extracts FluidSynth binaries for bundling with the executable.
"""

import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


def setup_fluidsynth():
    """Download and set up FluidSynth 2.5.1 for bundling"""
    
    print("\n" + "="*60)
    print("FluidSynth 2.5.1 Setup for Building")
    print("="*60 + "\n")
    
    # Get project root
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    fluidsynth_dir = project_root / "assets" / "fluidsynth-v2.5.1"
    
    # Check if already exists
    if (fluidsynth_dir / "bin").exists():
        print(f"[+] FluidSynth already set up at {fluidsynth_dir}\n")
        return True
    
    print("[*] Downloading FluidSynth 2.5.1 from GitHub...")
    print("    URL: https://github.com/FluidSynth/fluidsynth/releases/download/v2.5.1/fluidsynth-v2.5.1-win10-x64-glib.zip\n")
    
    try:
        url = "https://github.com/FluidSynth/fluidsynth/releases/download/v2.5.1/fluidsynth-v2.5.1-win10-x64-glib.zip"
        zip_path = project_root / "fluidsynth-v2.5.1-win10-x64-glib.zip"
        
        # Download with progress
        def download_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(downloaded * 100 / total_size, 100)
            print(f"    Progress: {percent:.1f}%", end='\r')
        
        urllib.request.urlretrieve(url, str(zip_path), download_progress)
        print("\n[+] Download complete\n")
        
        # Extract
        print("[*] Extracting to assets/fluidsynth-v2.5.1/...")
        fluidsynth_dir.parent.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Get the root folder name from the zip
            names = zip_ref.namelist()
            root_folder = names[0].split('/')[0] if names else None
            
            # Extract all
            zip_ref.extractall(str(fluidsynth_dir.parent))
            
            # Rename if needed
            if root_folder and root_folder != "fluidsynth-v2.5.1":
                extracted_path = fluidsynth_dir.parent / root_folder
                if extracted_path.exists() and extracted_path != fluidsynth_dir:
                    extracted_path.rename(fluidsynth_dir)
        
        print("[+] Extraction complete\n")
        
        # Verify essential files
        essential_files = ["bin/fluidsynth.exe", "bin/libfluidsynth-3.dll"]
        missing = []
        
        for file in essential_files:
            if not (fluidsynth_dir / file).exists():
                missing.append(file)
        
        if missing:
            print("[ERROR] Missing essential files:")
            for file in missing:
                print(f"    {file}")
            return False
        
        print("[+] All essential FluidSynth files verified\n")
        
        # Clean up zip
        zip_path.unlink(missing_ok=True)
        
        print("[+] FluidSynth 2.5.1 is ready for bundling\n")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Failed to set up FluidSynth: {e}\n")
        print("Manual setup:")
        print("  1. Download: https://github.com/FluidSynth/fluidsynth/releases/tag/v2.5.1")
        print("  2. Choose: fluidsynth-v2.5.1-win10-x64-glib.zip")
        print("  3. Extract to: assets/fluidsynth-v2.5.1/")
        print()
        return False


if __name__ == "__main__":
    success = setup_fluidsynth()
    sys.exit(0 if success else 1)
