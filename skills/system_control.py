"""System Control skill – open apps, screenshots, clipboard, processes."""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.system")

SYSTEM = platform.system()  # Windows | Darwin | Linux


class SystemControlSkill(BaseSkill):
    name = "system_control"
    description = "Control the operating system: open apps, take screenshots, manage files"

    tool_definition = {
        "name": "system_control",
        "description": (
            "Control the operating system. Supported actions: "
            "open_app, take_screenshot, get_clipboard, set_clipboard, "
            "list_processes, get_system_info, run_command."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "open_app",
                        "take_screenshot",
                        "get_clipboard",
                        "set_clipboard",
                        "list_processes",
                        "get_system_info",
                        "run_command",
                    ],
                },
                "target": {
                    "type": "string",
                    "description": "App name, command, or clipboard text depending on action",
                },
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str, target: str = "") -> Any:
        handlers = {
            "open_app": self._open_app,
            "take_screenshot": self._screenshot,
            "get_clipboard": self._get_clipboard,
            "set_clipboard": self._set_clipboard,
            "list_processes": self._list_processes,
            "get_system_info": self._system_info,
            "run_command": self._run_command,
        }
        handler = handlers.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(target)

    async def _open_app(self, app_name: str) -> dict:
        loop = asyncio.get_event_loop()

        def _open():
            try:
                if SYSTEM == "Windows":
                    os.startfile(app_name)
                elif SYSTEM == "Darwin":
                    subprocess.Popen(["open", "-a", app_name])
                else:
                    # Linux: try as command, then as desktop app via gtk-launch
                    try:
                        subprocess.Popen([app_name], start_new_session=True)
                    except FileNotFoundError:
                        subprocess.Popen(
                            ["gtk-launch", app_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                return {"success": True, "app": app_name}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return await loop.run_in_executor(None, _open)

    async def _screenshot(self, _: str = "") -> dict:
        loop = asyncio.get_event_loop()

        def _take():
            try:
                import pyautogui
                from PIL import Image

                screenshot_dir = Path("data/screenshots")
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                from datetime import datetime
                fname = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                path = screenshot_dir / fname
                img = pyautogui.screenshot()
                img.save(str(path))
                return {"success": True, "path": str(path)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return await loop.run_in_executor(None, _take)

    async def _get_clipboard(self, _: str = "") -> dict:
        loop = asyncio.get_event_loop()

        def _get():
            try:
                import pyautogui
                import subprocess
                if SYSTEM == "Windows":
                    import subprocess
                    result = subprocess.run(
                        ["powershell", "-command", "Get-Clipboard"],
                        capture_output=True, text=True
                    )
                    return {"content": result.stdout.strip()}
                else:
                    import pyperclip
                    return {"content": pyperclip.paste()}
            except Exception as e:
                return {"error": str(e)}

        return await loop.run_in_executor(None, _get)

    async def _set_clipboard(self, text: str) -> dict:
        loop = asyncio.get_event_loop()

        def _set():
            try:
                if SYSTEM == "Windows":
                    subprocess.run(
                        ["powershell", "-command", f"Set-Clipboard -Value '{text}'"],
                        capture_output=True,
                    )
                else:
                    import pyperclip
                    pyperclip.copy(text)
                return {"success": True}
            except Exception as e:
                return {"error": str(e)}

        return await loop.run_in_executor(None, _set)

    async def _list_processes(self, _: str = "") -> list[dict]:
        loop = asyncio.get_event_loop()

        def _list():
            try:
                import psutil
                procs = []
                for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                    try:
                        procs.append(p.info)
                    except psutil.NoSuchProcess:
                        pass
                # Top 20 by CPU
                procs.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
                return procs[:20]
            except Exception as e:
                return [{"error": str(e)}]

        return await loop.run_in_executor(None, _list)

    async def _system_info(self, _: str = "") -> dict:
        loop = asyncio.get_event_loop()

        def _info():
            try:
                import psutil
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage("/")
                return {
                    "platform": platform.platform(),
                    "cpu_percent": cpu,
                    "cpu_cores": psutil.cpu_count(),
                    "ram_total_gb": round(mem.total / 1e9, 1),
                    "ram_used_gb": round(mem.used / 1e9, 1),
                    "ram_percent": mem.percent,
                    "disk_total_gb": round(disk.total / 1e9, 1),
                    "disk_used_gb": round(disk.used / 1e9, 1),
                    "disk_percent": disk.percent,
                    "python": sys.version.split()[0],
                }
            except Exception as e:
                return {"error": str(e)}

        return await loop.run_in_executor(None, _info)

    async def _run_command(self, command: str) -> dict:
        """Run a shell command and return output (sandboxed)."""
        BLOCKED = ["rm -rf", "del /f", "format", "shutdown", "reboot", ":(){"]
        lower = command.lower()
        for dangerous in BLOCKED:
            if dangerous in lower:
                return {"error": "Command blocked for safety reasons."}

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode(errors="replace")[:4000],
                "stderr": stderr.decode(errors="replace")[:1000],
            }
        except asyncio.TimeoutError:
            return {"error": "Command timed out (30s)"}
        except Exception as e:
            return {"error": str(e)}
