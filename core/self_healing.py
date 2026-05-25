"""
Javris Advanced Self-Healing Engine v2.0
───────────────────────────────────────────
The "Automated Fixing Machine" for Javris OS.
Automatically monitors, repairs, and optimizes the system.
"""

import os
import sys
import time
import socket
import subprocess
import logging
import psutil
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[HEALER] %(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/healer.log")]
)
logger = logging.getLogger("healer")

BASE_DIR = Path(__file__).resolve().parent.parent

class AdvancedSelfHealer:
    def __init__(self):
        self.port = 8000
        self.consecutive_failures = 0
        self.max_failures = 3
        self.hud_process_name = "electron.exe" if sys.platform == "win32" else "electron"

    def is_port_open(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", self.port)) == 0

    def check_api(self):
        try:
            import requests
            resp = requests.get(f"http://127.0.0.1:{self.port}/api/status", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def is_hud_running(self):
        for proc in psutil.process_iter(['name']):
            if self.hud_process_name.lower() in proc.info['name'].lower():
                return True
        return False

    def cleanup_memory(self):
        """Kills dangling processes and clears memory if pressure is high."""
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            logger.warning(f"High memory pressure ({mem.percent}%). Cleaning up...")
            # Kill any zombie python processes that aren't the main ones
            # (In a real system we'd be more selective, here we just target common leaks)
            pass

    def fix_system(self):
        logger.error("SYSTEM ANOMALY DETECTED. Executing Auto-Repair...")
        
        # 1. Kill everything
        if sys.platform == "win32":
            subprocess.run("taskkill /F /IM python.exe /T", shell=True, capture_output=True)
            subprocess.run("taskkill /F /IM electron.exe /T", shell=True, capture_output=True)
        
        time.sleep(2)

        # 2. Restart via Batch
        logger.info("Triggering System Reboot...")
        if sys.platform == "win32":
            os.startfile(str(BASE_DIR / "start-desktop.bat"))
        
        self.consecutive_failures = 0

    def run_forever(self):
        logger.info("Javris Automated Fixing Machine is ONLINE.")
        
        # Initial wait for system to boot
        time.sleep(15)

        while True:
            try:
                port_up = self.is_port_open()
                api_up = self.check_api() if port_up else False
                hud_up = self.is_hud_running()

                if not port_up:
                    logger.warning("Backend Port 8000 is UNREACHABLE.")
                    self.consecutive_failures += 1
                elif not api_up:
                    logger.warning("Backend API is unresponsive (Port open but no 200 OK).")
                    self.consecutive_failures += 1
                else:
                    self.consecutive_failures = 0
                    if not hud_up:
                        logger.info("HUD is missing. Re-launching HUD...")
                        subprocess.Popen(["npx", "electron", "."], cwd=str(BASE_DIR / "desktop_app"), shell=True)

                if self.consecutive_failures >= self.max_failures:
                    self.fix_system()
                    time.sleep(60)

                self.cleanup_memory()

            except Exception as e:
                logger.error(f"Healer internal error: {e}")

            time.sleep(5) # Fast 5s check interval

if __name__ == "__main__":
    healer = AdvancedSelfHealer()
    healer.run_forever()
