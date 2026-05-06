"""
Javris Modes System
────────────────────
Defines workspace modes (Work / Trading / Dev / Night / Focus)
Each mode declares which panels are visible and in what layout.

Usage:
  from core.modes import ModeManager
  mgr = ModeManager()
  mgr.switch("trading")  # → broadcasts MODE_CHANGE event via autonomy

Voice commands wired in voice_commands.py:
  "switch to work mode"
  "activate trading mode"
  "night mode"
  "focus mode"
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.logger import get_logger

logger = get_logger("javris.modes")

DATA_PATH = Path(__file__).parent.parent / "data" / "modes.json"


# ── Mode definitions ──────────────────────────────────────────────

@dataclass
class Mode:
    id: str
    name: str
    icon: str
    description: str
    panels: list[str]          # which panels to open
    layout: str = "cascade"    # cascade | tile | stack
    color_accent: str = "#00d4ff"
    bg_effect: str = "default"
    shortcuts: dict = field(default_factory=dict)  # extra hotkeys for this mode
    voice_aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "description": self.description,
            "panels": self.panels,
            "layout": self.layout,
            "color_accent": self.color_accent,
            "bg_effect": self.bg_effect,
            "shortcuts": self.shortcuts,
        }


BUILT_IN_MODES: list[Mode] = [
    Mode(
        id="work",
        name="Work Mode",
        icon="💼",
        description="Productivity focused — chat, tasks, calendar, notes",
        panels=["chat", "tasks", "notifications"],
        layout="cascade",
        color_accent="#00d4ff",
        voice_aliases=["work mode", "work", "productivity mode"],
    ),
    Mode(
        id="trading",
        name="Trading Mode",
        icon="📈",
        description="Market focus — news, research, system monitor",
        panels=["news", "research", "intelligence", "notifications"],
        layout="tile",
        color_accent="#10b981",
        bg_effect="scanlines",
        voice_aliases=["trading mode", "trade mode", "trading", "market mode"],
    ),
    Mode(
        id="dev",
        name="Dev Mode",
        icon="⌨️",
        description="Development — chat, computer, intelligence",
        panels=["chat", "computer", "intelligence"],
        layout="tile",
        color_accent="#7c3aed",
        voice_aliases=["dev mode", "developer mode", "coding mode", "dev"],
    ),
    Mode(
        id="focus",
        name="Focus Mode",
        icon="🎯",
        description="Minimal distraction — chat only, no notifications",
        panels=["chat"],
        layout="stack",
        color_accent="#f59e0b",
        voice_aliases=["focus mode", "focus", "deep work", "do not disturb"],
    ),
    Mode(
        id="night",
        name="Night Mode",
        icon="🌙",
        description="Minimal, dimmed — weather and notifications only",
        panels=["notifications", "weather"],
        layout="cascade",
        color_accent="#4f46e5",
        bg_effect="dim",
        voice_aliases=["night mode", "night", "sleep mode", "dim mode"],
    ),
    Mode(
        id="research",
        name="Research Mode",
        icon="🔬",
        description="Deep research — research panel + chat + intelligence",
        panels=["research", "chat", "intelligence"],
        layout="tile",
        color_accent="#ec4899",
        voice_aliases=["research mode", "research", "study mode"],
    ),
]


# ── Manager ───────────────────────────────────────────────────────

class ModeManager:
    def __init__(self, autonomy=None):
        self._modes: dict[str, Mode] = {m.id: m for m in BUILT_IN_MODES}
        self._current: str = "work"
        self._autonomy = autonomy
        self._load()

    def _load(self):
        if DATA_PATH.exists():
            try:
                d = json.loads(DATA_PATH.read_text())
                self._current = d.get("current", "work")
            except Exception:
                pass

    def _save(self):
        DATA_PATH.parent.mkdir(exist_ok=True)
        DATA_PATH.write_text(json.dumps({"current": self._current}))

    @property
    def current(self) -> Mode:
        return self._modes.get(self._current, self._modes["work"])

    @property
    def current_id(self) -> str:
        return self._current

    def list_modes(self) -> list[dict]:
        return [m.to_dict() for m in self._modes.values()]

    def get_mode(self, mode_id: str) -> Optional[Mode]:
        return self._modes.get(mode_id)

    async def switch(self, mode_id: str) -> dict:
        """Switch to a mode by ID. Broadcasts event to dashboard."""
        if mode_id not in self._modes:
            # Try alias matching
            for m in self._modes.values():
                for alias in m.voice_aliases:
                    if alias in mode_id.lower():
                        mode_id = m.id
                        break

        if mode_id not in self._modes:
            return {"error": f"Unknown mode: {mode_id}", "available": list(self._modes.keys())}

        prev = self._current
        self._current = mode_id
        self._save()

        mode = self._modes[mode_id]
        logger.info(f"Mode switched: {prev} → {mode_id}")

        # Broadcast to dashboard via autonomy
        if self._autonomy:
            await self._autonomy.trigger(
                event_type="mode_change",
                message=f"Switched to {mode.name}",
                priority="medium",
                data={
                    "mode_id": mode_id,
                    "mode_name": mode.name,
                    "icon": mode.icon,
                    "panels": mode.panels,
                    "layout": mode.layout,
                    "color_accent": mode.color_accent,
                    "bg_effect": mode.bg_effect,
                },
            )

        return {
            "switched_to": mode_id,
            "name": mode.name,
            "panels": mode.panels,
            "layout": mode.layout,
        }

    def match_from_voice(self, text: str) -> Optional[str]:
        """Find mode ID from spoken text. Returns None if no match."""
        lower = text.lower()
        for mode in self._modes.values():
            for alias in mode.voice_aliases:
                if alias in lower:
                    return mode.id
        # Direct ID match
        for mode_id in self._modes:
            if mode_id in lower:
                return mode_id
        return None
