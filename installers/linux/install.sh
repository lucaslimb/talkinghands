#!/bin/bash
# Talking Hands - Linux Installation Script
# Installs all dependencies and sets up the application

set -e

INSTALL_DIR="$HOME/.local/share/TalkingHands"
APP_NAME="Talking Hands"
PYTHON_MIN_VERSION="3.9"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[+]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on supported Linux distribution
check_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        log_info "Detected OS: $PRETTY_NAME"
        return 0
    else
        log_error "Unable to detect Linux distribution"
        return 1
    fi
}

# Check Python version
check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        return 1
    fi
    
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    log_info "Python $PYTHON_VERSION found"
    
    if [ "$(printf '%s\n' "$PYTHON_MIN_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$PYTHON_MIN_VERSION" ]; then
        log_error "Python $PYTHON_MIN_VERSION or higher required (found $PYTHON_VERSION)"
        return 1
    fi
    return 0
}

# Install system dependencies based on distribution
install_system_deps() {
    log_info "Installing system dependencies..."
    
    case "$OS" in
        ubuntu|debian)
            sudo apt-get update
            sudo apt-get install -y \
                python3-dev \
                python3-venv \
                python3-pip \
                libopencv-dev \
                python3-opencv \
                libfluidsynth3 \
                libfluidsynth-dev \
                fluidsynth \
                libsndfile1 \
                libsndfile1-dev \
                libportaudio2 \
                libportaudio-dev \
                xdotool \
                libx11-dev
            ;;
        fedora|rhel|centos)
            sudo dnf install -y \
                python3-devel \
                python3-pip \
                opencv-devel \
                opencv-python \
                fluidsynth-devel \
                libsndfile-devel \
                portaudio-devel \
                xdotool-devel \
                libX11-devel
            ;;
        arch|manjaro)
            sudo pacman -Syu --noconfirm \
                python-pip \
                opencv \
                fluidsynth \
                libsndfile \
                portaudio \
                xdotool \
                libx11
            ;;
        opensuse*)
            sudo zypper install -y \
                python3-devel \
                python3-pip \
                opencv-devel \
                fluidsynth-devel \
                libsndfile-devel \
                portaudio-devel \
                xdotool-devel \
                libX11-devel
            ;;
        *)
            log_warn "Unsupported distribution: $OS"
            log_warn "Please manually install: python3-dev opencv4 fluidsynth libsndfile1-dev portaudio19-dev"
            ;;
    esac
}

# Create virtual environment and install Python packages
setup_venv() {
    log_info "Setting up Python virtual environment..."
    
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    
    if [ -d venv ]; then
        log_info "Existing virtual environment found, updating packages..."
    else
        python3 -m venv venv
        log_info "Virtual environment created"
    fi
    
    source venv/bin/activate
    
    log_info "Installing Python packages..."
    pip install --upgrade pip setuptools wheel
    
    # Get the source directory (where install.sh is located)
    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    if [ -f "$SOURCE_DIR/requirements.txt" ]; then
        pip install -r "$SOURCE_DIR/requirements.txt"
        log_info "Python packages installed"
    else
        log_warn "requirements.txt not found in $(dirname "$SOURCE_DIR")"
        log_info "Installing core packages manually..."
        pip install opencv-python mediapipe pygame customtkinter mido pyaudio sounddevice pyfluidsynth
    fi
    
    deactivate
}

# Create desktop entry
create_desktop_entry() {
    log_info "Creating desktop entry..."
    
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    
    cat > "$DESKTOP_DIR/talkinghandsengine.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=Talking Hands
Comment=Virtual instrument platform using hand gestures
Exec=bash -c "TALKING_HANDS_HOME=$HOME/.local/share/TalkingHands; cd $TALKING_HANDS_HOME; source venv/bin/activate; python src/main.py"
Icon=multimedia-player
Categories=Audio;Music;
Terminal=true
StartupNotify=true
EOF
    
    chmod +x "$DESKTOP_DIR/talkinghandsengine.desktop"
    log_info "Desktop entry created"
}

# Create launcher script
create_launcher() {
    log_info "Creating launcher script..."
    
    LOCAL_BIN="$HOME/.local/bin"
    mkdir -p "$LOCAL_BIN"
    
    cat > "$LOCAL_BIN/talkinghandsengine" << 'EOF'
#!/bin/bash
# Talking Hands Launcher Script

export TALKING_HANDS_HOME="$HOME/.local/share/TalkingHands"
cd "$TALKING_HANDS_HOME"
source venv/bin/activate
python src/main.py "$@"
EOF
    
    chmod +x "$LOCAL_BIN/talkinghandsengine"
    
    # Check if ~/.local/bin is in PATH
    if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
        log_warn "~/.local/bin not in PATH"
        log_info "Run: export PATH=\"\$HOME/.local/bin:\$PATH\"" 
        log_info "Or add to ~/.bashrc or ~/.zshrc for permanent setup"
    fi
    
    log_info "Launcher created: talkinghandsengine"
}

# Copy source code if not already there
copy_source() {
    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    log_info "Copying application files..."
    
    if [ -d "$SOURCE_DIR/src" ]; then
        cp -r "$SOURCE_DIR/src" "$INSTALL_DIR/"
        cp -r "$SOURCE_DIR/assets" "$INSTALL_DIR/"
        cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/" 2>/dev/null || true
        log_info "Application files copied"
    else
        log_error "Source files not found in $SOURCE_DIR"
        return 1
    fi
}

# Main installation routine
main() {
    echo -e "\n${GREEN}========================================${NC}"
    echo -e "${GREEN}Talking Hands - Linux Installation${NC}"
    echo -e "${GREEN}========================================${NC}\n"
    
    check_distro || exit 1
    check_python || exit 1
    install_system_deps || exit 1
    copy_source || exit 1
    setup_venv || exit 1
    create_launcher || exit 1
    create_desktop_entry || exit 1
    
    echo -e "\n${GREEN}========================================${NC}"
    echo -e "${GREEN}Installation Complete!${NC}"
    echo -e "${GREEN}========================================${NC}\n"
    
    log_info "Installation directory: $INSTALL_DIR"
    log_info "To run: talkinghandsengine"
    log_info "Or see the application in your app menu"
    
    echo ""
}

# Run installation
main "$@"
