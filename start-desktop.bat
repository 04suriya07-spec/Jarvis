@echo off
echo ========================================
echo   JAVRIS OS - SYSTEM INITIALIZATION
echo ========================================

echo [1/4] Force-cleaning system ports...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM electron.exe /T >nul 2>&1
timeout /t 2 > nul

echo [2/4] Starting Javris Backend...
start "Javris Backend" cmd /k "python main.py serve --voice --host 127.0.0.1"

echo [3/4] Starting Voice Ears...
start "Javris Ears" cmd /c "python ui/wake_daemon.py"

echo [4/4] Starting Self-Healing Machine...
start "Javris Healer" /min cmd /c "python core/self_healing.py"

echo [!] Launching Transparent HUD...
echo [!] The HUD will auto-retry until the backend is ready.
cd desktop_app
start "Javris HUD" cmd /c "npx electron ."

echo ========================================
echo   JAVRIS OS IS INITIALIZING
echo ========================================
echo [TIP] AI Models are loading in the background.
exit
