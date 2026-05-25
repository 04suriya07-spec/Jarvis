"""
WiFi Skill — nmcli-based network management (Ubuntu/Linux).

Voice commands:
    "show WiFi networks"          → list available SSIDs
    "connect to Home WiFi"        → connect to saved network
    "disconnect WiFi"             → disconnect current connection
    "turn WiFi on/off"            → enable or disable radio
    "what's my IP address"        → show current IP
    "WiFi status"                 → connection status + signal
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.wifi")


async def _run(cmd: str, timeout: int = 15) -> tuple[int, str, str]:
    """Run a shell command, return (returncode, stdout, stderr)."""
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


class WiFiSkill(BaseSkill):
    name = "wifi"
    description = "Control WiFi: list networks, connect, disconnect, toggle radio, get IP"

    tool_definition = {
        "name": "wifi",
        "description": (
            "Manage WiFi on Ubuntu/Linux. "
            "Actions: status, list_networks, connect, disconnect, enable, disable, get_ip."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "list_networks", "connect", "disconnect", "enable", "disable", "get_ip"],
                },
                "ssid": {
                    "type": "string",
                    "description": "Network name (SSID) to connect to",
                },
                "password": {
                    "type": "string",
                    "description": "WiFi password for new networks",
                },
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str, ssid: str = "", password: str = "") -> Any:
        handlers = {
            "status": self._status,
            "list_networks": self._list_networks,
            "connect": self._connect,
            "disconnect": self._disconnect,
            "enable": self._enable,
            "disable": self._disable,
            "get_ip": self._get_ip,
        }
        fn = handlers.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}"}
        return await fn(ssid=ssid, password=password)

    async def _status(self, **_) -> dict:
        rc, out, err = await _run("nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status")
        if rc != 0:
            return {"error": err or "nmcli not available. Install: sudo apt install network-manager"}

        lines = [l for l in out.splitlines() if "wifi" in l.lower()]
        if not lines:
            return {"connected": False, "message": "No WiFi device found"}

        parts = lines[0].split(":")
        state = parts[2] if len(parts) > 2 else "unknown"
        connection = parts[3] if len(parts) > 3 else ""

        # Get signal strength
        signal_info = {}
        rc2, out2, _ = await _run("nmcli -t -f IN-USE,SSID,SIGNAL,BARS dev wifi list")
        for line in out2.splitlines():
            if line.startswith("*:"):
                p = line.split(":")
                if len(p) >= 4:
                    signal_info = {"ssid": p[1], "signal": p[2], "bars": p[3]}
                break

        return {
            "connected": state == "connected",
            "state": state,
            "network": connection or signal_info.get("ssid", ""),
            "signal_percent": signal_info.get("signal", ""),
            "bars": signal_info.get("bars", ""),
        }

    async def _list_networks(self, **_) -> list[dict]:
        rc, out, err = await _run("nmcli -t -f IN-USE,SSID,SIGNAL,BARS,SECURITY dev wifi list")
        if rc != 0:
            return [{"error": err or "nmcli failed"}]

        networks = []
        seen = set()
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) < 5:
                continue
            in_use, ssid, signal, bars, security = parts[0], parts[1], parts[2], parts[3], parts[4]
            if ssid and ssid not in seen:
                seen.add(ssid)
                networks.append({
                    "ssid": ssid,
                    "signal_percent": signal,
                    "bars": bars,
                    "security": security or "Open",
                    "connected": in_use == "*",
                })

        networks.sort(key=lambda x: int(x["signal_percent"] or 0), reverse=True)
        return networks[:20]

    async def _connect(self, ssid: str = "", password: str = "", **_) -> dict:
        if not ssid:
            return {"error": "SSID required to connect"}

        # Try saved connection first
        rc, out, _ = await _run(f'nmcli con up "{ssid}"', timeout=20)
        if rc == 0:
            return {"success": True, "message": f"Connected to {ssid} (saved profile)"}

        # New network — password required
        if not password:
            return {"error": f"No saved profile for '{ssid}'. Provide a password to connect."}

        rc2, out2, err2 = await _run(
            f'nmcli dev wifi connect "{ssid}" password "{password}"',
            timeout=30,
        )
        if rc2 == 0:
            return {"success": True, "message": f"Connected to {ssid}"}
        return {"success": False, "error": err2 or out2}

    async def _disconnect(self, **_) -> dict:
        rc, out, err = await _run("nmcli dev disconnect $(nmcli -t -f DEVICE,TYPE dev | grep wifi | cut -d: -f1)")
        if rc == 0:
            return {"success": True, "message": "WiFi disconnected"}
        # Simpler fallback
        rc2, out2, err2 = await _run("nmcli radio wifi off && nmcli radio wifi on")
        return {"success": rc2 == 0, "message": "WiFi disconnected" if rc2 == 0 else err2}

    async def _enable(self, **_) -> dict:
        rc, _, err = await _run("nmcli radio wifi on")
        return {"success": rc == 0, "message": "WiFi enabled" if rc == 0 else err}

    async def _disable(self, **_) -> dict:
        rc, _, err = await _run("nmcli radio wifi off")
        return {"success": rc == 0, "message": "WiFi disabled" if rc == 0 else err}

    async def _get_ip(self, **_) -> dict:
        rc, out, _ = await _run("ip route get 8.8.8.8 2>/dev/null | grep -oP 'src \\K\\S+'")
        local_ip = out.strip() if rc == 0 and out else "unknown"

        rc2, pub, _ = await _run("curl -s --max-time 5 https://api.ipify.org")
        public_ip = pub.strip() if rc2 == 0 and pub else "unavailable"

        return {"local_ip": local_ip, "public_ip": public_ip}
