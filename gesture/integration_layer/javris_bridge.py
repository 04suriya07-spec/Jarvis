"""
Javris Gesture — Integration Layer: Javris Bridge
───────────────────────────────────────────────────
Exposes gesture events to the Javris assistant core so gestures can:
  • Trigger assistant commands directly
  • Combine with voice input as multi-modal shortcuts
  • Activate voice-listen mode via specific gestures

The bridge runs as an async consumer on the event queue produced
by GestureController.  It can also emit autonomy events.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Coroutine, Dict, Optional

from gesture.gesture_engine.gesture_smoother import ConfirmedGesture
from gesture.command_mapper.mapper import CommandIntent

logger = logging.getLogger("javris.gesture.bridge")


# ── Event types ───────────────────────────────────────────────────

GESTURE_VOICE_TRIGGER  = "activate_voice"
GESTURE_ASSISTANT_CMD  = "assistant_command"
GESTURE_CHAT_TRIGGER   = "trigger_assistant_chat"


class GestureEvent:
    """Wrapped gesture event for the assistant event bus."""
    def __init__(self, intent: CommandIntent, gesture: ConfirmedGesture):
        self.intent   = intent
        self.gesture  = gesture
        self.action   = intent.action
        self.params   = intent.params

    def __repr__(self):
        return f"GestureEvent({self.gesture.name} → {self.action})"


# ── Bridge ────────────────────────────────────────────────────────

class JavrisBridge:
    """
    Consumes gesture events and routes them into the Javris assistant.

    Hooks
    ─────
    Register custom async callbacks via `on_event(action_name, coro_fn)`.
    The callback receives a GestureEvent.

    Voice Activation
    ────────────────
    When a gesture maps to `activate_voice`, the bridge calls
    `voice_trigger_fn` if one is registered.
    """

    def __init__(self):
        self._hooks: Dict[str, Callable] = {}
        self._assistant = None
        self._voice_engine = None
        self._autonomy_engine = None
        self._running = False

    # ── Dependency injection ──────────────────────────────────────

    def set_assistant(self, assistant) -> None:
        self._assistant = assistant

    def set_voice_engine(self, voice_engine) -> None:
        self._voice_engine = voice_engine

    def set_autonomy(self, autonomy) -> None:
        self._autonomy_engine = autonomy

    # ── Hook registration ─────────────────────────────────────────

    def on_event(self, action: str, fn: Callable) -> None:
        """Register an async callback for a specific action name."""
        self._hooks[action] = fn

    # ── Main processing ───────────────────────────────────────────

    async def handle(self, event: GestureEvent) -> None:
        """Process a single gesture event."""
        action = event.action
        logger.info(f"Gesture event: {event.gesture.name} → {action} {event.params}")

        # Check registered hooks first
        hook = self._hooks.get(action)
        if hook:
            try:
                await hook(event)
            except Exception as e:
                logger.error(f"Hook for {action} raised: {e}")
            return

        # Built-in routing
        if action == GESTURE_VOICE_TRIGGER:
            await self._activate_voice(event)
        elif action == GESTURE_CHAT_TRIGGER:
            await self._trigger_chat(event)
        elif action == "assistant_command":
            await self._send_to_assistant(event.params.get("command", ""), event)
        else:
            # Fire autonomy event so the dashboard reflects gesture activity
            await self._fire_autonomy_event(event)

    async def consume_queue(self, queue: asyncio.Queue) -> None:
        """Consume events from the gesture controller's asyncio Queue."""
        self._running = True
        while self._running:
            try:
                event: GestureEvent = await asyncio.wait_for(queue.get(), timeout=1.0)
                await self.handle(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bridge queue error: {e}")

    def stop(self) -> None:
        self._running = False

    # ── Internal actions ──────────────────────────────────────────

    async def _activate_voice(self, event: GestureEvent) -> None:
        """Trigger one-shot voice listen mode."""
        if self._voice_engine:
            try:
                logger.info("Voice activated via gesture")
                # Signal the voice engine to listen for one utterance
                if hasattr(self._voice_engine, "listen_once"):
                    text = await self._voice_engine.listen_once()
                    if text and self._assistant:
                        reply = await self._assistant.chat(text)
                        await self._voice_engine.speak(reply)
            except Exception as e:
                logger.error(f"Voice activation failed: {e}")
        else:
            logger.warning("Voice engine not connected to bridge")

    async def _send_to_assistant(self, command: str, event: GestureEvent) -> None:
        """Send a text command directly to the assistant."""
        if self._assistant and command:
            try:
                reply = await self._assistant.chat(command)
                if self._voice_engine:
                    await self._voice_engine.speak(reply)
            except Exception as e:
                logger.error(f"Assistant command failed: {e}")

    async def _trigger_chat(self, event: GestureEvent) -> None:
        """Signal to open Javris chat (fires an autonomy event the frontend picks up)."""
        if self._autonomy_engine:
            try:
                await self._autonomy_engine.trigger(
                    "gesture_open_chat",
                    "Call-me gesture: open Javris chat",
                    priority="normal",
                )
            except Exception:
                pass
        if self._voice_engine:
            try:
                await self._voice_engine.speak("Opening chat. How can I help you?")
            except Exception:
                pass

    async def _fire_autonomy_event(self, event: GestureEvent) -> None:
        """Fire a low-priority autonomy event for gesture tracking."""
        if self._autonomy_engine:
            try:
                await self._autonomy_engine.trigger(
                    "gesture_executed",
                    f"Gesture: {event.gesture.name} → {event.action}",
                    priority="low",
                )
            except Exception:
                pass
