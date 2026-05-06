@echo off
echo Installing Playwright browsers...
pip install playwright
playwright install chromium
echo Done! Playwright is ready.
pause
