@echo off
REM Talking Hands - Installation Batch Script
REM Automatically downloads and installs FluidSynth, then sets up Talking Hands

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo Talking Hands - Installation Setup
echo ============================================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] This installer requires Administrator privileges
    echo     Right-click and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

REM FluidSynth installation directory
set FLUIDSYNTH_DIR=%ProgramFiles%\FluidSynth
set FLUIDSYNTH_BIN=%FLUIDSYNTH_DIR%\bin
set FLUIDSYNTH_ZIP=%TEMP%\fluidsynth.zip

REM FluidSynth release URL (v2.5.1 Windows binary - glib version for best compatibility)
set FLUIDSYNTH_URL=https://github.com/FluidSynth/fluidsynth/releases/download/v2.5.1/fluidsynth-v2.5.1-win10-x64-glib.zip

echo [*] Checking for FluidSynth installation...

if exist "%FLUIDSYNTH_BIN%" (
    echo [+] FluidSynth already installed at %FLUIDSYNTH_DIR%
    goto SKIP_FLUIDSYNTH
)

echo [!] FluidSynth not found. Downloading automatically...
echo.

REM Download FluidSynth
echo [*] Downloading FluidSynth 2.5.1 from GitHub...
powershell -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri '%FLUIDSYNTH_URL%' -OutFile '%FLUIDSYNTH_ZIP%' } catch { exit 1 }"

if %errorLevel% neq 0 (
    echo [ERROR] Failed to download FluidSynth
    echo.
    echo You can download manually from:
    echo   https://github.com/FluidSynth/fluidsynth/releases/tag/v2.5.1
    echo   (Choose: fluidsynth-v2.5.1-win10-x64-glib.zip)
    echo.
    echo Extract to: %FLUIDSYNTH_DIR%
    echo.
    pause
    exit /b 1
)

echo [+] Downloaded successfully

REM Extract FluidSynth
echo [*] Extracting FluidSynth...
if not exist "%FLUIDSYNTH_DIR%" mkdir "%FLUIDSYNTH_DIR%"

powershell -Command "Expand-Archive -Path '%FLUIDSYNTH_ZIP%' -DestinationPath '%FLUIDSYNTH_DIR%' -Force"

if %errorLevel% neq 0 (
    echo [ERROR] Failed to extract FluidSynth
    pause
    exit /b 1
)

REM Clean up ZIP file
del "%FLUIDSYNTH_ZIP%" >nul 2>&1

echo [+] FluidSynth installed successfully

:SKIP_FLUIDSYNTH

echo [*] Adding FluidSynth to PATH...

setx PATH "%FLUIDSYNTH_BIN%;%%PATH%%" >nul 2>&1
if %errorLevel% equ 0 (
    echo [+] Updated system PATH
) else (
    echo [!] Could not update PATH. You may need to do this manually.
)

REM Create installation directory
set INSTALL_DIR=%ProgramFiles%\Talking Hands
echo [*] Creating installation directory: %INSTALL_DIR%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM Copy executable if available
if exist "..\..\dist\THEngine.exe" (
    echo [*] Copying executable...
    copy /Y "..\..\dist\THEngine.exe" "%INSTALL_DIR%\THEngine.exe" >nul
    if !errorLevel! equ 0 (
        echo [+] Installed to %INSTALL_DIR%\THEngine.exe
    ) else (
        echo [ERROR] Failed to copy executable
        pause
        exit /b 1
    )
    
    REM Copy uninstaller
    echo [*] Copying uninstaller...
    copy /Y "uninstall.bat" "%INSTALL_DIR%\uninstall.bat" >nul 2>&1
    echo [+] Uninstaller available in installation directory
) else (
    echo [ERROR] dist\THEngine.exe not found
    echo Please build the executable first with: python build/build.py
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [+] Installation Complete!
echo ============================================================
echo.
echo You can now launch Talking Hands from:
echo   - Command: THEngine.exe -i "Piano"
echo.
echo To uninstall completely:
echo   - Run: %INSTALL_DIR%\uninstall.bat
echo   - Or: uninstall.bat in the installation directory
echo.
pause
