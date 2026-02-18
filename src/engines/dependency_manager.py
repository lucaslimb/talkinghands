#!/usr/bin/env python3
"""
Dependency Manager for Talking Hands
Handles verification of bundled libraries and Python packages.
"""

import subprocess
import sys
import os
from pathlib import Path
import importlib.util


class DependencyManager:
    """Manages bundled dependencies and Python packages"""

    def __init__(self):
        # Detect if running from PyInstaller bundle
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            self.project_root = Path(sys._MEIPASS)
        else:
            # Running as normal Python script
            current_file = Path(__file__).resolve()
            self.project_root = current_file.parent.parent.parent
        
        self.fluidsynth_dir = self.project_root / "assets" / "fluidsynth-v2.5.1"
    
    def print_status(self, message, status="info"):
        """Print status messages with consistent formatting"""
        prefix = {
            "info": "[*]",
            "success": "[+]",
            "warning": "[!]",
            "error": "[ERROR]"
        }.get(status, "[*]")
        print(f"{prefix} {message}")
    
    # ==================== FluidSynth Bundled Library ====================
    
    def setup_bundled_fluidsynth(self):
        """
        Configure bundled FluidSynth by:
        1. Adding its bin directory to PATH
        2. Setting FLUIDSYNTH_PATH environment variable
        3. Ensuring DLL directory is accessible to pyfluidsynth
        """
        bin_dir = self.fluidsynth_dir / "bin"
        
        if not bin_dir.exists():
            self.print_status("Bundled FluidSynth not found", "warning")
            return False
        
        try:
            bin_str = str(bin_dir)
            
            # 1. Add to PATH at the beginning (highest priority)
            current_path = os.environ.get("PATH", "")
            if bin_str not in current_path:
                os.environ["PATH"] = f"{bin_str};{current_path}"
            
            # 2. Set FLUIDSYNTH_PATH explicitly for pyfluidsynth
            # This helps pyfluidsynth locate the library
            os.environ["FLUIDSYNTH_PATH"] = bin_str
            
            # 3. Can also set specific DLL paths if needed
            os.environ["FLUIDSYNTH_DLL"] = str(bin_dir / "libfluidsynth-3.dll")
            
            self.print_status(f"FluidSynth 2.5.1 bundled library configured", "success")
            return True
        except Exception as e:
            self.print_status(f"Error setting up FluidSynth: {e}", "error")
            return False
    
    def get_fluidsynth_bin_path(self):
        """
        Get the absolute path to FluidSynth bin directory.
        Useful for code that needs to explicitly know where FluidSynth is.
        """
        bin_dir = self.fluidsynth_dir / "bin"
        if bin_dir.exists():
            return str(bin_dir)
        return None
    
    # ==================== Python Package Management ====================
    
    def check_python_packages(self):
        """Check which required packages are not installed"""
        required_packages = {
            "cv2": "opencv-python",
            "mediapipe": "mediapipe",
            "fluidsynth": "pyfluidsynth",
            "pygame": "pygame",
            "customtkinter": "customtkinter",
            "mido": "mido",
            "sounddevice": "sounddevice",
            "numpy": "numpy",
        }
        
        missing = {}
        
        self.print_status("Checking Python packages...", "info")
        
        for module_name, package_name in required_packages.items():
            spec = importlib.util.find_spec(module_name)
            if spec is None:
                missing[module_name] = package_name
                self.print_status(f"Missing: {package_name}", "warning")
            else:
                self.print_status(f"Found: {package_name}", "success")
        
        return missing
    
    def run_command(self, cmd, description="", silent=False):
        """Run a shell command and return success status"""
        try:
            if not silent:
                self.print_status(f"{description}...", "info")
            
            result = subprocess.run(
                cmd,
                capture_output=silent,
                text=True
            )
            
            if result.returncode == 0:
                if not silent:
                    self.print_status(f"{description} successful", "success")
                return True
            else:
                if not silent and result.stderr:
                    self.print_status(f"Command failed: {result.stderr}", "warning")
                return False
        except Exception as e:
            if not silent:
                self.print_status(f"Error executing command: {e}", "error")
            return False
    
    def install_python_packages(self, missing_packages):
        """Install missing Python packages"""
        if not missing_packages:
            self.print_status("All Python packages already installed", "success")
            return True
        
        self.print_status(f"Installing {len(missing_packages)} missing packages...", "info")
        
        try:
            # Try upgrading pip first
            self.run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], "Upgrading pip")
            
            # Install packages one by one for better error reporting
            for module_name, package_name in missing_packages.items():
                success = self.run_command(
                    [sys.executable, "-m", "pip", "install", package_name],
                    f"Installing {package_name}"
                )
                if not success:
                    self.print_status(f"Failed to install {package_name}", "error")
                    return False
            
            self.print_status("All packages installed successfully", "success")
            return True
        except Exception as e:
            self.print_status(f"Error installing packages: {e}", "error")
            return False
    
    # ==================== Main Verification Workflow ====================
    
    def verify_and_install_dependencies(self):
        """
        Main verification workflow. Checks bundled libraries and Python packages.
        Returns True if all dependencies are available or successfully installed.
        """
        print("\n" + "="*60)
        print("DEPENDENCY VERIFICATION")
        print("="*60 + "\n")
        
        # Step 1: Configure bundled FluidSynth
        self.print_status("Checking bundled FluidSynth 2.5.1...", "info")
        fluidsynth_ok = self.setup_bundled_fluidsynth()
        
        if not fluidsynth_ok:
            self.print_status("FluidSynth bundled library not found", "error")
            self.print_status("The application may not work correctly", "error")
        
        # Step 2: Check Python packages
        print()
        missing_packages = self.check_python_packages()
        
        if missing_packages:
            print()
            packages_ok = self.install_python_packages(missing_packages)
            if not packages_ok:
                self.print_status("Some packages could not be installed", "error")
                return False
        else:
            self.print_status("All Python packages installed", "success")
        
        print("\n" + "="*60)
        if fluidsynth_ok:
            self.print_status("All dependencies verified successfully!", "success")
            print("="*60 + "\n")
            return True
        else:
            self.print_status("Warning: FluidSynth not properly configured", "warning")
            print("="*60 + "\n")
            return fluidsynth_ok


def verify_dependencies_before_launch():
    """
    Public function to verify dependencies before application launch.
    Automatically installs missing Python packages if possible.
    FluidSynth is bundled and configured automatically.
    """
    manager = DependencyManager()
    return manager.verify_and_install_dependencies()


if __name__ == "__main__":
    # Standalone testing
    manager = DependencyManager()
    success = manager.verify_and_install_dependencies()
    sys.exit(0 if success else 1)

