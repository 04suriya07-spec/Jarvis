"""
Javris Voice Command Router
────────────────────────────
Maps spoken phrases to instant system actions.

TWO tiers:
  TIER 1 — Browser-side (Web Speech API, <50ms)
    UI commands: "open chat", "scroll down", "stop agent"
    These never hit the server.

  TIER 2 — Server-side (this file, ~200ms)
    Smart commands: "complete the quiz", "search for X", "remind me at 3pm"
    These route to the right skill/agent automatically.

This file handles Tier 2 routing and returns a structured action.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class VoiceCommand:
    intent: str          # what the user wants
    action: str          # which function/endpoint to call
    params: dict         # extracted parameters
    confidence: float    # 0.0–1.0
    raw_text: str        # original spoken text
    is_ui_command: bool = False   # handled client-side


# ── Intent patterns ───────────────────────────────────────────────
# Each entry: (regex pattern, intent, action, param extractor fn)

COMMAND_PATTERNS: list[tuple] = [
    # Mode switching — must be first so it catches "switch to X mode" before navigation
    (r"(switch to|activate|enable|go to|use)\s+(.+?)\s*(mode)?$", "switch_mode", "switch_mode",
        lambda m: {"mode": m.group(2).strip().lower()}),

    # Navigation
    (r"(go to|open|navigate to|visit)\s+(.+)", "navigate", "browser_navigate",
        lambda m: {"url": m.group(2).strip()}),

    # Quiz/Assignment
    (r"(complete|finish|do|start)\s+(the\s+)?quiz", "start_quiz", "computer_quiz",
        lambda m: {}),
    (r"(fill|complete|do|start)\s+(the\s+)?assignment", "start_assignment", "computer_assignment",
        lambda m: {}),
    (r"(stop|cancel|abort|halt)\s+(the\s+)?(agent|task|quiz|browser)", "stop_agent", "computer_stop",
        lambda m: {}),

    # Weather
    (r"(what'?s?(\s+is)?|get|show|how'?s?(\s+the)?)\s+(the\s+)?weather(\s+in\s+(.+))?", "weather", "get_weather",
        lambda m: {"location": (m.group(6) or "").strip() or "current location"}),
    (r"weather(\s+in\s+(.+))?", "weather", "get_weather",
        lambda m: {"location": (m.group(2) or "").strip() or "current location"}),

    # News
    (r"(what'?s?(\s+is)?|get|show|any)\s+(the\s+)?(latest\s+)?news(\s+(about|on)\s+(.+))?", "news", "get_news",
        lambda m: {"topic": (m.group(7) or "").strip()}),

    # Reminders
    (r"(remind me|set a reminder|alert me)(.+)(at|in)\s+(.+)", "reminder", "set_reminder",
        lambda m: {"message": m.group(2).strip(), "when": m.group(4).strip()}),

    # Tasks
    (r"(add|create|new)\s+(a\s+)?task[:\s]+(.+)", "create_task", "tasks_create",
        lambda m: {"title": m.group(3).strip()}),
    (r"(show|list|what are)\s+(my\s+)?(tasks?|todos?)", "list_tasks", "tasks_list",
        lambda m: {}),

    # Notes
    (r"(note|write down|remember)[:\s]+(.+)", "create_note", "notes_create",
        lambda m: {"content": m.group(2).strip()}),

    # Search
    (r"(search|look up|find|google)\s+(for\s+)?(.+)", "web_search", "web_search",
        lambda m: {"query": m.group(3).strip()}),

    # System
    (r"(take a?\s+)?screenshot", "screenshot", "screenshot",
        lambda m: {}),
    (r"(show|what'?s?)\s+(my\s+)?(system|cpu|ram|memory|disk)\s*(info|status|usage)?", "system_info", "system_info",
        lambda m: {}),

    # Research
    (r"(research|investigate|deep dive)\s+(into\s+)?(.+)", "research", "research",
        lambda m: {"topic": m.group(3).strip()}),

    # Morning digest
    (r"(morning (briefing|digest|report)|good morning|daily briefing)", "digest", "morning_digest",
        lambda m: {}),

    # Scroll (browser control)
    (r"scroll (down|up)(\s+\d+)?", "scroll", "browser_scroll",
        lambda m: {"direction": m.group(1), "amount": int((m.group(2) or " 300").strip())}),

    # Click
    (r"click\s+(.+)", "click", "browser_click",
        lambda m: {"text": m.group(1).strip()}),

    # Type
    (r"type\s+(.+)", "type_text", "browser_type",
        lambda m: {"text": m.group(1).strip()}),

    # Voice mode
    (r"(pause|stop)\s+listening", "pause_voice", "voice_pause",
        lambda m: {}),
    (r"(start|resume)\s+listening", "resume_voice", "voice_resume",
        lambda m: {}),

    # New session
    (r"new (conversation|session|chat)", "new_session", "new_session",
        lambda m: {}),

    # Read page
    (r"(read|summarise?|summarize)\s+(this\s+)?(page|website|article)", "read_page", "browser_read",
        lambda m: {}),
]

# UI-only commands (handled browser-side, returned as is_ui_command=True)
UI_COMMANDS = {
    r"open (chat|assistant)": {"panel": "chat"},
    r"open computer|show browser|computer (view|panel)": {"panel": "computer"},
    r"open tasks?|show tasks?": {"panel": "tasks"},
    r"open intelligence|show intelligence": {"panel": "intelligence"},
    r"open personality|show settings": {"panel": "personality"},
    r"open notifications?|show notifications?": {"panel": "notifications"},
    r"open weather|show weather (panel)?": {"panel": "weather"},
    r"open news|show news (panel)?": {"panel": "news"},
    r"(minimize|hide|close) (all\s+)?(panels?|windows?)": {"action": "minimize_all"},
    r"(maximize|fullscreen|expand) (.+)": {"action": "maximize_panel"},
    r"(arrange|tile|layout) panels?": {"action": "tile_panels"},
}


def parse_command(text: str) -> VoiceCommand:
    """
    Parse a spoken command and return a VoiceCommand.
    Returns an AI-chat fallback if no pattern matches.
    """
    lower = text.lower().strip()

    # Check UI commands first (no server round-trip)
    for pattern, action in UI_COMMANDS.items():
        if re.search(pattern, lower):
            return VoiceCommand(
                intent="ui_command",
                action="ui",
                params=action,
                confidence=0.95,
                raw_text=text,
                is_ui_command=True,
            )

    # Match against skill commands
    for pattern, intent, action, extractor in COMMAND_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            try:
                params = extractor(m)
            except Exception:
                params = {}
            return VoiceCommand(
                intent=intent,
                action=action,
                params={**params, "_raw": text},
                confidence=0.9,
                raw_text=text,
                is_ui_command=False,
            )

    # Default: send to AI chat
    return VoiceCommand(
        intent="chat",
        action="chat",
        params={"message": text},
        confidence=0.7,
        raw_text=text,
        is_ui_command=False,
    )


# ── Server-side command executor ──────────────────────────────────

async def execute_command(cmd: VoiceCommand, assistant, autonomy=None) -> dict:
    """
    Execute a parsed voice command.
    Returns {"response": str, "action_taken": str, "data": dict}
    """
    action = cmd.action

    try:
        if action == "switch_mode":
            mode_text = cmd.params.get("mode", "")
            try:
                from core.modes import ModeManager
                mgr = ModeManager(autonomy=autonomy)
                mode_id = mgr.match_from_voice(mode_text) or mode_text
                result = await mgr.switch(mode_id)
                if "error" in result:
                    return {"response": f"I don't know that mode. Available: work, trading, dev, focus, night, research.", "action_taken": "error", "data": {}}
                return {
                    "response": f"Switching to {result['name']}. Opening {', '.join(result['panels'][:3])} panels.",
                    "action_taken": "mode_switched",
                    "data": result,
                    "is_ui_command": True,
                    "ui_params": {"action": "switch_mode", **result},
                }
            except Exception as e:
                pass

        elif action == "chat":
            reply = await assistant.chat(cmd.params.get("message", cmd.raw_text))
            return {"response": reply, "action_taken": "chat", "data": {}}

        elif action == "get_weather":
            skill = assistant._skill_registry.get("get_weather")
            if skill:
                loc = cmd.params.get("location", "").strip()
                if not loc or loc == "current location":
                    loc = (
                        getattr(getattr(assistant, "personality", None), "preferred_weather_location", None)
                        or "London"
                    )
                data = await skill.run(location=loc)
                curr = data.get("current", {})
                if not curr:
                    return {"response": f"Sorry, I couldn't get weather data for {loc}.", "action_taken": "weather", "data": data}
                reply = (f"{curr.get('description','')}, {curr.get('temp','')} "
                         f"in {curr.get('location', loc)}. "
                         f"Feels like {curr.get('feels_like','')}.")
                return {"response": reply, "action_taken": "weather", "data": data}

        elif action == "get_news":
            skill = assistant._skill_registry.get("get_news")
            if skill:
                topic = cmd.params.get("topic", "")
                articles = await skill.run(topic=topic, count=3)
                titles = ". ".join(a.get("title","") for a in articles[:3])
                return {"response": f"Here are the top stories: {titles}", "action_taken": "news", "data": {"articles": articles}}

        elif action == "set_reminder":
            skill = assistant._skill_registry.get("scheduler")
            if skill:
                result = await skill.run(action="create", title=cmd.params.get("message",""), when=cmd.params.get("when",""))
                return {"response": f"Reminder set for {result.get('scheduled_for','')}", "action_taken": "reminder", "data": result}

        elif action == "tasks_create":
            skill = assistant._skill_registry.get("tasks")
            if skill:
                result = await skill.run(action="create", title=cmd.params.get("title",""))
                return {"response": f"Task created: {cmd.params.get('title','')}", "action_taken": "task_created", "data": result}

        elif action == "tasks_list":
            skill = assistant._skill_registry.get("tasks")
            if skill:
                tasks = await skill.run(action="list")
                count = len(tasks) if isinstance(tasks, list) else 0
                titles = ". ".join(t.get("title","") for t in (tasks[:3] if isinstance(tasks, list) else []))
                return {"response": f"You have {count} pending tasks. First: {titles}", "action_taken": "tasks_listed", "data": {"tasks": tasks}}

        elif action == "web_search":
            skill = assistant._skill_registry.get("web_search")
            if skill:
                results = await skill.run(query=cmd.params.get("query",""))
                top = results[0] if results else {}
                reply = f"Top result: {top.get('title','')} — {top.get('snippet','')[:150]}"
                return {"response": reply, "action_taken": "searched", "data": {"results": results}}

        elif action == "research":
            return {"response": f"Starting research on: {cmd.params.get('topic','')}. Check the Research panel.", "action_taken": "research_started", "data": cmd.params}

        elif action == "morning_digest":
            asyncio.create_task(assistant.autonomy.trigger("morning_digest", "Voice request", priority="high"))
            return {"response": "Generating your morning briefing...", "action_taken": "digest", "data": {}}

        elif action == "screenshot":
            skill = assistant._skill_registry.get("system_control")
            if skill:
                result = await skill.run(action="take_screenshot")
                return {"response": "Screenshot taken.", "action_taken": "screenshot", "data": result}

        elif action == "system_info":
            skill = assistant._skill_registry.get("system_control")
            if skill:
                info = await skill.run(action="get_system_info")
                reply = (f"CPU: {info.get('cpu_percent','?')}%, "
                         f"RAM: {info.get('ram_percent','?')}%, "
                         f"Disk: {info.get('disk_percent','?')}%")
                return {"response": reply, "action_taken": "system_info", "data": info}

        elif action == "notes_create":
            skill = assistant._skill_registry.get("notes")
            if skill:
                content = cmd.params.get("content", "")
                result = await skill.run(action="create", title=content[:40], content=content)
                return {"response": f"Note saved: {content[:60]}", "action_taken": "note_created", "data": result}

        elif action in ("computer_quiz", "computer_assignment", "computer_stop", "browser_navigate",
                        "browser_scroll", "browser_click", "browser_type", "browser_read",
                        "new_session", "voice_pause", "voice_resume"):
            return {"response": f"Executing: {action}", "action_taken": action, "data": cmd.params}

    except Exception as e:
        from core.logger import get_logger
        get_logger("javris.voice_commands").error(f"execute_command error: {e}", exc_info=True)
        return {"response": f"Sorry, I hit an error: {e}", "action_taken": "error", "data": {}}

    # Fallback to chat
    reply = await assistant.chat(cmd.raw_text)
    return {"response": reply, "action_taken": "chat", "data": {}}
