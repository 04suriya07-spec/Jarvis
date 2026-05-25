"""
Bluetooth Skill — bluetoothctl-based (Ubuntu/Linux).

Voice commands:
    "show bluetooth devices"       → list paired devices
    "connect my headphones"        → connect by name or MAC
    "disconnect bluetooth"         → disconnect current device
    "turn Bluetooth on/off"        → toggle adapter power
    "scan for Bluetooth devices"   → discover nearby devices
    "pair my speaker"              → pair new device
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.bluetooth")


async def _run(cmd: str, timeout: int = 15) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "Command timed out"


async def _btctl(commands: list[str], timeout: int = 20) -> str:
    """Feed commands to bluetoothctl interactively via echo pipe."""
    script = "\n".join(commands)
    cmd = f'echo -e "{script}\\nquit" | bluetoothctl'
    _, out, _ = await _run(cmd, timeout=timeout)
    return out


class BluetoothSkill(BaseSkill):
    name = "bluetooth"
    description = "Control Bluetooth: list devices, connect, disconnect, scan, toggle power"

    tool_definition = {
        "name": "bluetooth",
        "description": (
            "Manage Bluetooth on Ubuntu/Linux. "
            "Actions: status, list_devices, connect, disconnect, scan, power_on, power_off, remove."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "list_devices", "connect", "disconnect", "scan", "power_on", "power_off", "remove"],
                },
                "device": {
                    "type": "string",
                    "description": "Device name or MAC address (e.g. 'Sony Headphones' or 'AA:BB:CC:DD:EE:FF')",
                },
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str, device: str = "") -> Any:
        handlers = {
            "status": self._status,
            "list_devices": self._list_devices,
            "connect": self._connect,
            "disconnect": self._disconnect,
            "scan": self._scan,
            "power_on": self._power_on,
            "power_off": self._power_off,
            "remove": self._remove,
        }
        fn = handlers.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}"}
        return await fn(device=device)

    async def _status(self, **_) -> dict:
        rc, out, err = await _run("bluetoothctl show 2>/dev/null | grep -E 'Powered|Discoverable|Pairable'")
        if rc != 0 or not out:
            return {"error": "Bluetooth adapter not found or bluetoothctl unavailable"}

        powered = "yes" in out.lower() and "powered: yes" in out.lower()
        rc2, conn_out, _ = await _run("bluetoothctl devices Connected 2>/dev/null")
        connected_devices = []
        for line in conn_out.splitlines():
            m = re.match(r"Device ([0-9A-F:]+) (.+)", line)
            if m:
                connected_devices.append({"mac": m.group(1), "name": m.group(2)})

        return {
            "powered": powered,
            "connected_devices": connected_devices,
            "raw": out,
        }

    async def _list_devices(self, **_) -> list[dict]:
        rc, out, _ = await _run("bluetoothctl devices 2>/dev/null")
        devices = []
        for line in out.splitlines():
            m = re.match(r"Device ([0-9A-F:]+) (.+)", line)
            if m:
                mac, name = m.group(1), m.group(2)
                # Check if connected
                rc2, info, _ = await _run(f"bluetoothctl info {mac} 2>/dev/null | grep -E 'Connected|Paired|Trusted'")
                connected = "connected: yes" in info.lower()
                paired = "paired: yes" in info.lower()
                devices.append({"mac": mac, "name": name, "connected": connected, "paired": paired})
        return devices if devices else [{"message": "No paired devices found"}]

    def _resolve_mac(self, device: str, paired_output: str) -> str | None:
        """Find MAC from name or return MAC directly."""
        if re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", device):
            return device
        for line in paired_output.splitlines():
            m = re.match(r"Device ([0-9A-F:]+) (.+)", line)
            if m and device.lower() in m.group(2).lower():
                return m.group(1)
        return None

    async def _connect(self, device: str = "", **_) -> dict:
        if not device:
            return {"error": "Device name or MAC required"}

        _, paired_out, _ = await _run("bluetoothctl devices 2>/dev/null")
        mac = self._resolve_mac(device, paired_out)
        if not mac:
            return {"error": f"Device '{device}' not found in paired devices. Scan and pair it first."}

        rc, out, err = await _run(f"bluetoothctl connect {mac}", timeout=20)
        if rc == 0 and "successful" in out.lower():
            return {"success": True, "message": f"Connected to {device} ({mac})"}
        return {"success": False, "error": err or out}

    async def _disconnect(self, device: str = "", **_) -> dict:
        _, paired_out, _ = await _run("bluetoothctl devices Connected 2>/dev/null")

        if device:
            _, all_out, _ = await _run("bluetoothctl devices 2>/dev/null")
            mac = self._resolve_mac(device, all_out)
            if not mac:
                return {"error": f"Device '{device}' not found"}
        else:
            # Disconnect first connected device
            lines = paired_out.splitlines()
            if not lines:
                return {"message": "No devices currently connected"}
            m = re.match(r"Device ([0-9A-F:]+)", lines[0])
            mac = m.group(1) if m else None

        if not mac:
            return {"error": "Could not find a connected device to disconnect"}

        rc, out, err = await _run(f"bluetoothctl disconnect {mac}", timeout=15)
        return {"success": rc == 0, "message": "Disconnected" if rc == 0 else err}

    async def _scan(self, **_) -> list[dict]:
        # Scan for 8 seconds
        rc, out, err = await _run(
            'timeout 8 bluetoothctl scan on 2>/dev/null; bluetoothctl devices 2>/dev/null',
            timeout=15,
        )
        devices = []
        seen = set()
        for line in out.splitlines():
            m = re.match(r"Device ([0-9A-F:]+) (.+)", line)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                devices.append({"mac": m.group(1), "name": m.group(2)})
        return devices if devices else [{"message": "No devices found nearby"}]

    async def _power_on(self, **_) -> dict:
        rc, _, err = await _run("bluetoothctl power on")
        return {"success": rc == 0, "message": "Bluetooth enabled" if rc == 0 else err}

    async def _power_off(self, **_) -> dict:
        rc, _, err = await _run("bluetoothctl power off")
        return {"success": rc == 0, "message": "Bluetooth disabled" if rc == 0 else err}

    async def _remove(self, device: str = "", **_) -> dict:
        if not device:
            return {"error": "Device name or MAC required"}
        _, all_out, _ = await _run("bluetoothctl devices 2>/dev/null")
        mac = self._resolve_mac(device, all_out)
        if not mac:
            return {"error": f"Device '{device}' not found"}
        rc, _, err = await _run(f"bluetoothctl remove {mac}")
        return {"success": rc == 0, "message": f"Removed {device}" if rc == 0 else err}
