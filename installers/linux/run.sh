#!/bin/bash
# Talking Hands - Direct Run Script
# Run the application without full installation
# Useful for development or quick testing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[+]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check Python
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed"
    exit 1
fi

log_info "Python $(python3 --version | cut -d' ' -f2) found"

# Create or update virtual environment
if [ ! -d "$VENV_DIR" ]; then
    log_info "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    log_info "Virtual environment found"
fi

# Activate venv
log_info "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Install/update dependencies
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    log_info "Installing/updating dependencies..."
    pip install --upgrade pip setuptools wheel
    pip install -r "$SCRIPT_DIR/requirements.txt"
else
    log_warn "requirements.txt not found"
    log_info "Installing core dependencies..."
    pip install --upgrade pip
    pip install opencv-python mediapipe pygame customtkinter mido pyaudio sounddevice pyfluidsynth
fi

log_info "Starting Talking Hands..."
echo ""

# Set environment variable for settings
export TALKING_HANDS_HOME="$SCRIPT_DIR"

# Run the application
python "$SCRIPT_DIR/src/main.py" "$@"
