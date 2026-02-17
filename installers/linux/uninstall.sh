#!/bin/bash
# Talking Hands - Linux Uninstallation Script
# Removes the application and all related files

INSTALL_DIR="$HOME/.local/share/TalkingHands"
DESKTOP_FILE="$HOME/.local/share/applications/talkinghandsengine.desktop"
LAUNCHER="$HOME/.local/bin/talkinghandsengine"

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

main() {
    echo -e "\n${GREEN}========================================${NC}"
    echo -e "${GREEN}Talking Hands - Linux Uninstall${NC}"
    echo -e "${GREEN}========================================${NC}\n"
    
    log_warn "This will remove Talking Hands from your system"
    echo ""
    read -p "Continue? (y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Uninstallation cancelled"
        exit 0
    fi
    
    # Remove application directory
    if [ -d "$INSTALL_DIR" ]; then
        log_info "Removing application directory..."
        rm -rf "$INSTALL_DIR"
        log_info "Directory removed"
    else
        log_warn "Application directory not found: $INSTALL_DIR"
    fi
    
    # Remove launcher script
    if [ -f "$LAUNCHER" ]; then
        log_info "Removing launcher script..."
        rm -f "$LAUNCHER"
        log_info "Launcher removed"
    fi
    
    # Remove desktop entry
    if [ -f "$DESKTOP_FILE" ]; then
        log_info "Removing desktop entry..."
        rm -f "$DESKTOP_FILE"
        
        # Update desktop database if available
        if command -v update-desktop-database &> /dev/null; then
            update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
        fi
        
        log_info "Desktop entry removed"
    fi
    
    echo -e "\n${GREEN}========================================${NC}"
    echo -e "${GREEN}Uninstallation Complete!${NC}"
    echo -e "${GREEN}========================================${NC}\n"
    
    log_info "Talking Hands has been removed"
    echo ""
}

main "$@"
