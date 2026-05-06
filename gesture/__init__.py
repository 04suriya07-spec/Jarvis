"""
Javris Gesture Control System
──────────────────────────────
Real-time touchless OS control via hand gestures.

Quick start::

    from gesture import GestureController

    ctrl = GestureController(show_preview=True)
    await ctrl.run_async()
"""

from gesture.gesture_controller import GestureController
from gesture.gesture_engine.gesture_smoother import ConfirmedGesture
from gesture.command_mapper.mapper import CommandIntent, GestureMapper
from gesture.system_controller.actions import SystemController, ACTION_REGISTRY
from gesture.integration_layer.javris_bridge import JavrisBridge, GestureEvent

__all__ = [
    "GestureController",
    "ConfirmedGesture",
    "CommandIntent",
    "GestureMapper",
    "SystemController",
    "ACTION_REGISTRY",
    "JavrisBridge",
    "GestureEvent",
]
