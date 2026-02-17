@echo off
REM Talking Hands - Uninstallation Batch Script
REM Completely removes Talking Hands and FluidSynth from the system

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo Talking Hands - Uninstallation Setup
echo ============================================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] This uninstaller requires Administrator privileges
    echo     Right-click and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

set INSTALL_DIR=%ProgramFiles%\Talking Hands
set FLUIDSYNTH_DIR=%ProgramFiles%\FluidSynth
set DESKTOP=%USERPROFILE%\Desktop
set START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Talking Hands

echo [*] This will remove:
echo     - Talking Hands executable
echo     - FluidSynth audio engine
echo     - All shortcuts
echo     - System PATH entries
echo.

set /p CONFIRM="Are you sure you want to uninstall? (yes/no): "
if /i not "%CONFIRM%"=="yes" (
    echo [!] Uninstallation cancelled
    pause
    exit /b 0
)

echo.
echo [*] Starting uninstallation...
echo.

REM Remove Talking Hands installation
echo [*] Removing Talking Hands...
if exist "%INSTALL_DIR%" (
    rmdir /s /q "%INSTALL_DIR%" >nul 2>&1
    if %errorLevel% equ 0 (
        echo [+] Removed Talking Hands directory
    ) else (
        echo [!] Some Talking Hands files could not be removed (may be in use)
    )
)

REM Remove FluidSynth
echo [*] Removing FluidSynth audio engine...
if exist "%FLUIDSYNTH_DIR%" (
    rmdir /s /q "%FLUIDSYNTH_DIR%" >nul 2>&1
    if %errorLevel% equ 0 (
        echo [+] Removed FluidSynth directory
    ) else (
        echo [!] Some FluidSynth files could not be removed
    )
)

REM Remove from PATH environment variable
echo [*] Cleaning system PATH...
for /f "tokens=2*" %%a in ('reg query HKCU\Environment /v PATH 2^>nul') do (
    set OLD_PATH=%%b
)

if defined OLD_PATH (
    setlocal enabledelayedexpansion
    set NEW_PATH=!OLD_PATH:%FLUIDSYNTH_DIR%\bin;=!
    set NEW_PATH=!NEW_PATH:;%FLUIDSYNTH_DIR%\bin=!
    
    if not "!NEW_PATH!"=="!OLD_PATH!" (
        reg add HKCU\Environment /v PATH /d "!NEW_PATH!" /f >nul 2>&1
        echo [+] Removed FluidSynth from system PATH
    ) else (
        echo [+] PATH already clean
    )
    endlocal
)

REM Remove registry entries
echo [*] Removing registry entries...
reg delete HKCU\Software\Talking Hands /f >nul 2>&1
echo [+] Removed registry entries

echo.
echo ============================================================
echo [+] Uninstallation Complete!
echo ============================================================
echo.
echo Talking Hands has been completely removed from your system.
echo.
pause
