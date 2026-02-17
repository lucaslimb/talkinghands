#!/usr/bin/env python3
"""
Build script for Talking Hands Linux distribution
Creates a source distribution with installation scripts

Run from project root: python builders/build_linux.py
Or from builders folder: python build_linux.py
"""

import subprocess
import sys
from pathlib import Path
import shutil
import tarfile

def create_linux_distribution(project_root):
    """Create a tar.gz package with source code and installation scripts"""
    
    print("[*] Creating Linux distribution package...")
    
    install_source = project_root / "installers" / "linux" / "install.sh"
    uninstall_source = project_root / "installers" / "linux" / "uninstall.sh"
    run_source = project_root / "installers" / "linux" / "run.sh"
    requirements_source = project_root / "requirements.txt"
    readme_source = project_root / "README.md"
    
    # Create tar.gz package
    tar_name = "TalkingHands-Linux.tar.gz"
    tar_path = project_root / tar_name
    
    try:
        with tarfile.open(tar_path, 'w:gz') as tar:
            # Add source code
            print("    Adding source code...")
            tar.add(project_root / "src", arcname="TalkingHands/src")
            tar.add(project_root / "assets", arcname="TalkingHands/assets")
            
            # Add requirements
            if requirements_source.exists():
                tar.add(requirements_source, arcname="TalkingHands/requirements.txt")
                print("    Added requirements.txt")
            
            # Add installation scripts
            if install_source.exists():
                tar.add(install_source, arcname="TalkingHands/install.sh")
                print("    Added install.sh")
                
            if uninstall_source.exists():
                tar.add(uninstall_source, arcname="TalkingHands/uninstall.sh")
                print("    Added uninstall.sh")
            
            if run_source.exists():
                tar.add(run_source, arcname="TalkingHands/run.sh")
                print("    Added run.sh")
            
            # Add README
            if readme_source.exists():
                tar.add(readme_source, arcname="TalkingHands/README.md")
                print("    Added README.md")
            
            # Add configs documentation
            docs_config = project_root / "docs" / "Configs.md"
            if docs_config.exists():
                tar.add(docs_config, arcname="TalkingHands/docs/Configs.md")
                print("    Added docs/Configs.md")
        
        size_mb = tar_path.stat().st_size / (1024 * 1024)
        print(f"\n[+] Package created: {tar_path.name}")
        print(f"    Size: {size_mb:.1f} MB")
        
        return tar_path
    except Exception as e:
        print(f"[ERROR] Failed to create tar.gz: {e}")
        return None

def main():
    print("\n" + "="*60)
    print("Talking Hands - Linux Distribution Builder")
    print("="*60 + "\n")
    
    # Get project root (parent of builders/ folder)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    
    print(f"Project root: {project_root}\n")
    
    # Verify required files exist
    required_files = ["src", "assets", "requirements.txt", "README.md"]
    missing = [f for f in required_files if not (project_root / f).exists()]
    
    if missing:
        print(f"[ERROR] Missing required files: {', '.join(missing)}")
        sys.exit(1)
    
    print("[+] All source files present\n")
    
    # Create distribution
    tar_path = create_linux_distribution(project_root)
    
    print("\n" + "="*60)
    print("LINUX DISTRIBUTION READY")
    print("="*60 + "\n")
    
    if tar_path:
        print(f"Distribution archive: {tar_path}\n")
        print("To install on Linux:")
        print(f"  1. tar -xzf {tar_path.name}")
        print("  2. cd TalkingHands")
        print("  3. bash install.sh\n")
    else:
        print("[ERROR] Failed to create distribution\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
