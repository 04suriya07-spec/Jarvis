"""
Javris Gesture — Command Mapper
─────────────────────────────────
Translates a confirmed gesture into a structured command intent.

Architecture: Gesture → Intent → Action → Params

The mapping is loaded from gesture_mappings.json and can be hot-
reloaded at runtime.  Extend by editing the JSON — no code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from gesture.gesture_engine.gesture_smoother import ConfirmedGesture


CONFIG_PATH = Path(__file__).parent.parent / "config" / "gesture_mappings.json"


@dataclass
class CommandIntent:
    """A fully resolved command ready for the system controller."""
    gesture:  str
    intent:   str          # e.g. "media_control"
    action:   str          # e.g. "pause_media"
    params:   Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    is_sequence: bool = False
    confidence: float = 1.0


class GestureMapper:
    """
    Loads gesture → action mappings from JSON and resolves
    ConfirmedGesture objects into CommandIntents.

    Usage::

        mapper = GestureMapper()
        intent = mapper.resolve(confirmed_gesture)
        if intent:
            controller.execute(intent)
    """

    def __init__(self, config_path: Path = CONFIG_PATH):
        self._path = config_path
        self._mappings: Dict[str, dict] = {}
        self._sequences: Dict[str, dict] = {}
        self._settings: dict = {}
        self._app_aliases: Dict[str, str] = {}
        self.load()

    # ── Public API ─────────────────────────────────────────────────

    def load(self) -> None:
        """Load (or reload) mappings from the JSON config file."""
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            self._mappings  = data.get("gesture_mappings", {})
            self._sequences  = data.get("sequences", {})
            self._settings   = data.get("settings", {})
            self._app_aliases = data.get("app_aliases", {})
        except FileNotFoundError:
            pass   # use empty defaults

    def resolve(self, gesture: ConfirmedGesture) -> Optional[CommandIntent]:
        """
        Map a confirmed gesture to a CommandIntent.
        Returns None if the gesture has no mapping.
        """
        if gesture.is_sequence:
            cfg = gesture.metadata  # metadata already holds action cfg
        else:
            cfg = self._mappings.get(gesture.name)

        if not cfg:
            return None

        params = dict(cfg.get("params", {}))

        # Resolve app alias if present
        if "app" in params:
            params["app"] = self._app_aliases.get(params["app"], params["app"])

        return CommandIntent(
            gesture=gesture.name,
            intent=cfg.get("intent", "unknown"),
            action=cfg.get("action", gesture.name),
            params=params,
            description=cfg.get("description", ""),
            is_sequence=gesture.is_sequence,
            confidence=gesture.confidence,
        )

    def get_settings(self) -> dict:
        return dict(self._settings)

    def list_mappings(self) -> list[dict]:
        """Return all configured gesture mappings for display."""
        result = []
        for gesture, cfg in self._mappings.items():
            result.append({
                "gesture": gesture,
                "action": cfg.get("action"),
                "description": cfg.get("description", ""),
            })
        return result

    def add_mapping(self, gesture: str, intent: str, action: str, params: dict = None, description: str = "") -> None:
        """Dynamically add or overwrite a gesture mapping (in-memory only)."""
        self._mappings[gesture] = {
            "intent": intent,
            "action": action,
            "params": params or {},
            "description": description,
        }

    def save(self) -> None:
        """Persist current in-memory mappings back to the JSON file."""
        data = {
            "gesture_mappings": self._mappings,
            "sequences": self._sequences,
            "settings": self._settings,
            "app_aliases": self._app_aliases,
        }
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2)
