@echo off
REM ============================================================
REM  Launch Chrome with Remote Debugging enabled
REM  This lets Javris connect to YOUR existing Chrome session
REM  (preserves all your cookies, logins, and tabs)
REM ============================================================

echo Starting Chrome with remote debugging on port 9222...
echo Javris can now connect to this browser.
echo.

REM Try common Chrome locations
set CHROME1="C:\Program Files\Google\Chrome\Application\chrome.exe"
set CHROME2="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
set CHROME3="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if exist %CHROME1% (
    start "" %CHROME1% --remote-debugging-port=9222 --no-first-run
    goto done
)
if exist %CHROME2% (
    start "" %CHROME2% --remote-debugging-port=9222 --no-first-run
    goto done
)
if exist %CHROME3% (
    start "" %CHROME3% --remote-debugging-port=9222 --no-first-run
    goto done
)

echo Chrome not found in standard locations.
echo Edit this script with your Chrome path.

:done
echo Chrome launched! Now click "Connect Live Chrome" in the Javris dashboard.
timeout /t 3
