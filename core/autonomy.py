"""
Javris Autonomy Layer
──────────────────────
The engine that makes Javris a SYSTEM, not a chatbot.

Runs as a background asyncio loop. Every tick it:
  1. Checks system health (CPU, RAM, disk)
  2. Fires pending reminders
  3. Evaluates proactive suggestions from Intelligence
  4. Monitors news for user-interest keywords
  5. Detects anomalies and alerts
  6. Runs scheduled agents (morning digest, etc.)

Events are pushed to:
  • WebSocket subscribers (live dashboard feed)
  • Voice (TTS) if enabled
  • Notifications (Discord / Telegram) if configured
  • Cloud log

This is the HEARTBEAT of Javris.
"""

from __future__ import annotations

import asyncio
import json
import time
import psutil
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import AsyncIterator, Callable, Optional

from core.config import get_config
from core.logger import get_logger
from core.ambient import get_ambient_watcher, AmbientSnapshot

from core.context_broker import get_context_broker
from core.planner import get_planner
from core.executor import get_executor

logger = get_logger("javris.autonomy")
cfg = get_config()


# ── Event types ───────────────────────────────────────────────────

class EventPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AutonomyEvent:
    """An event generated autonomously by Javris."""
    event_id: str
    event_type: str          # "alert" | "suggestion" | "digest" | "pattern" | "reminder"
    priority: EventPriority
    title: str
    message: str
    action: str = ""         # suggested follow-up action
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)
    spoken: bool = False
    dismissed: bool = False

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "priority": self.priority.value,
            "title": self.title,
            "message": self.message,
            "action": self.action,
            "timestamp": self.timestamp,
            "data": self.data,
            "spoken": self.spoken,
            "dismissed": self.dismissed,
        }


# ── Autonomy Engine ───────────────────────────────────────────────

class AutonomyEngine:
    """
    The background brain of Javris.

    Usage:
        engine = AutonomyEngine()
        engine.set_dependencies(assistant, voice, intelligence, personality)
        asyncio.create_task(engine.run())
    """

    def __init__(self):
        self._assistant = None
        self._voice = None
        self._intelligence = None
        self._personality = None
        self._cloud = None

        self._running = False
        self._event_queue: asyncio.Queue[AutonomyEvent] = asyncio.Queue()
        self._subscribers: list[asyncio.Queue] = []   # WebSocket event feeds
        self._event_log: list[AutonomyEvent] = []     # in-memory log (last 200)

        # State trackers
        self._last_digest_date: str = ""
        self._cpu_high_since: float = 0
        self._last_news_check: float = 0
        self._last_suggestion_times: dict[str, float] = {}
        self._dismissed_events: set[str] = set()

        # Ambient context integration
        self._ambient = get_ambient_watcher()
        self._last_window_context: str = ""
        self._last_app_category: str = ""
        self._break_reminded_at: float = 0
        self._session_start: float = time.time()
        self._loop: asyncio.AbstractEventLoop | None = None

        import uuid
        self._make_id = lambda: str(uuid.uuid4())[:8]

    def set_dependencies(self, assistant, voice, intelligence, personality, cloud=None):
        self._assistant = assistant
        self._voice = voice
        self._intelligence = intelligence
        self._personality = personality
        self._cloud = cloud

    # ── Subscriber management (WebSocket fans) ────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except (ValueError, AttributeError):
            pass

    async def _broadcast(self, event: AutonomyEvent) -> None:
        """Push event to all WebSocket subscribers."""
        payload = event.to_dict()
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    # ── Main loop ─────────────────────────────────────────────

    async def run(self) -> None:
        """Entry point — run as a background task."""
        self._running = True
        self._loop = asyncio.get_running_loop()
        # Start ambient watcher (background OS thread)
        self._ambient.start()
        self._ambient.on_window_change = self._on_window_change

        # Fast ambient tick every 30s, slow external checks every 10 min
        fast_interval = 30
        slow_every_n  = 20          # slow checks every 20 fast ticks = 10 min
        tick_count    = 0

        logger.info(f"Autonomy engine started (fast={fast_interval}s, slow every {slow_every_n} ticks)")

        while self._running:
            try:
                await self._fast_tick()
                if tick_count % slow_every_n == 0:
                    await self._slow_tick()
                tick_count += 1
            except Exception as e:
                logger.error(f"Autonomy tick error: {e}")
            await asyncio.sleep(fast_interval)

    def stop(self) -> None:
        self._running = False
        self._ambient.stop()

    def _on_window_change(self, title: str, exe: str, category: str) -> None:
        """Called from ambient thread when active window changes."""
        if not self._loop or not self._running:
            return
        # Schedule async context-aware suggestion
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(
                self._suggest_from_context(title, exe, category)
            )
        )

    async def _fast_tick(self) -> None:
        """Quick checks — ambient context, breaks, system health."""
        checks = [
            self._check_system_health(),
            self._check_break_reminder(),
            self._check_ambient_context(),
        ]
        results = await asyncio.gather(*checks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.debug(f"Fast tick error: {r}")

    async def _slow_tick(self) -> None:
        """Heavier checks — news, digest, suggestions (every ~10 min)."""
        checks = [
            self._check_morning_digest(),
            self._check_proactive_suggestions(),
            self._check_news_alerts(),
        ]
        results = await asyncio.gather(*checks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.debug(f"Slow tick error: {r}")

    async def _check_break_reminder(self) -> None:
        """Remind user to take a break after 90 min of continuous activity."""
        snap = self._ambient.snapshot
        # Only if user has been actively using computer (idle < 5 min)
        if snap.idle_seconds > 300:
            self._session_start = time.time()   # reset session on idle
            return

        session_minutes = (time.time() - self._session_start) / 60
        if session_minutes >= 90:
            time_since_reminder = time.time() - self._break_reminded_at
            if time_since_reminder > 5400:   # remind max once per 90 min
                self._break_reminded_at = time.time()
                self._session_start = time.time()
                owner = self._personality.owner_name if self._personality else "Sir"
                await self._emit(AutonomyEvent(
                    event_id=self._make_id(),
                    event_type="wellness",
                    priority=EventPriority.MEDIUM,
                    title="Break Reminder",
                    message=f"You've been working for {int(session_minutes)} minutes, {owner}. Consider a short break.",
                    action="none",
                ))

    async def _check_ambient_context(self) -> None:
        """Surface context-aware suggestions based on active app/window."""
        snap = self._ambient.snapshot
        if snap.app_category == self._last_app_category:
            return   # no change
        self._last_app_category = snap.app_category
        # Emit ambient context update to WebSocket dashboard
        await self._broadcast(AutonomyEvent(
            event_id=self._make_id(),
            event_type="ambient_context",
            priority=EventPriority.LOW,
            title="Context Update",
            message=snap.to_context_string(),
            data=snap.to_dict(),
        ))

    async def _suggest_from_context(self, title: str, exe: str, category: str) -> None:
        """Proactively suggest actions based on what the user just opened."""
        if not self._personality:
            return

        # Only emit once per unique window, with 5 min cooldown
        key = f"window_{category}_{exe[:20]}"
        await self._emit_throttled(key, 300, AutonomyEvent(
            event_id=self._make_id(),
            event_type="context_suggestion",
            priority=EventPriority.LOW,
            title=f"Context: {category.title()}",
            message=self._context_message(title, exe, category),
            action="none",
            data={"window": title, "exe": exe, "category": category},
        ))

    def _context_message(self, title: str, exe: str, category: str) -> str:
        name = self._personality.owner_name if self._personality else "Sir"
        messages = {
            "coding": f"Switched to coding, {name}. Want me to pull up recent commits or run tests?",
            "browsing": f"Browser is active, {name}. Shall I search or summarize something?",
            "communication": f"Communication app is open, {name}. Any messages I should draft?",
            "terminal": f"Terminal opened, {name}. Running a deployment or task?",
            "documents": f"Working on documents, {name}. Want me to summarize or proofread?",
            "media": f"Enjoying some media, {name}. I'll stay quiet unless you need me.",
        }
        return messages.get(category, f"Switched to {title[:40]}, {name}.")

    # Keep original single-tick name as alias for backward compat
    async def _tick(self) -> None:
        await self._fast_tick()

    # ── Checks ────────────────────────────────────────────────

    async def _check_system_health(self) -> None:
        """Alert on high CPU / low disk / memory pressure."""
        try:
            loop = asyncio.get_running_loop()
            
            # Run blocking psutil calls in executor
            cpu = await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=1))
            mem = await loop.run_in_executor(None, psutil.virtual_memory)
            disk = await loop.run_in_executor(None, lambda: psutil.disk_usage("/"))

            # CPU spike
            if cpu > 90:
                if self._cpu_high_since == 0:
                    self._cpu_high_since = time.time()
                elif time.time() - self._cpu_high_since > 60:
                    await self._emit(AutonomyEvent(
                        event_id=self._make_id(),
                        event_type="alert",
                        priority=EventPriority.HIGH,
                        title="High CPU Usage",
                        message=f"CPU has been at {cpu:.0f}% for over a minute. Check running processes.",
                        action="system_processes",
                        data={"cpu": cpu, "mem": mem.percent},
                    ))
                    self._cpu_high_since = 0
            else:
                self._cpu_high_since = 0

            # Low disk
            if disk.percent > 90:
                await self._emit_throttled("low_disk", 3600, AutonomyEvent(
                    event_id=self._make_id(),
                    event_type="alert",
                    priority=EventPriority.MEDIUM,
                    title="Low Disk Space",
                    message=f"Disk is {disk.percent:.0f}% full ({disk.free // 1e9:.1f} GB free).",
                    action="system_disk",
                    data={"disk_percent": disk.percent},
                ))

            # Memory pressure
            if mem.percent > 85:
                await self._emit_throttled("high_mem", 1800, AutonomyEvent(
                    event_id=self._make_id(),
                    event_type="alert",
                    priority=EventPriority.MEDIUM,
                    title="High Memory Usage",
                    message=f"RAM at {mem.percent:.0f}%. {mem.available // 1e6:.0f} MB free.",
                    action="system_memory",
                    data={"mem_percent": mem.percent},
                ))
        except Exception as e:
            logger.debug(f"System health check failed: {e}")

    async def _check_morning_digest(self) -> None:
        """Fire morning digest once per day at user's wake hour."""
        if not self._personality:
            return

        now = datetime.now()
        today = date.today().isoformat()

        if (
            now.hour == self._personality.wake_hour
            and self._last_digest_date != today
            and "morning_digest" in (self._personality.alert_on or [])
        ):
            self._last_digest_date = today
            logger.info("Generating autonomous morning digest...")
            
            briefing = f"Morning briefing ready for {self._personality.owner_name}."
            # Note: We keep the morning digest LLM call because it's a high-value daily event
            if self._assistant:
                try:
                    prompt = (
                        "PROACTIVE TRIGGER: It is morning. Summarize my daily goals and weather concisely as an employee briefing."
                    )
                    briefing = await self._assistant._call_llm([{"role": "user", "content": prompt}])
                except Exception as e:
                    logger.error(f"LLM Digest generation failed: {e}")

            await self._emit(AutonomyEvent(
                event_id=self._make_id(),
                event_type="digest",
                priority=EventPriority.HIGH,
                title="Morning Executive Briefing",
                message=briefing,
                action="none",
            ))

    async def _check_proactive_suggestions(self) -> None:
        """Surface suggestions from the intelligence engine."""
        if not self._intelligence:
            return

        suggestions = self._intelligence.get_proactive_suggestions()
        for s in suggestions:
            action = s.get("action", "")
            priority_str = s.get("priority", "low")
            priority = EventPriority(priority_str) if priority_str in EventPriority._value2member_map_ else EventPriority.LOW

            await self._emit_throttled(
                f"suggestion_{action}",
                1800,
                AutonomyEvent(
                    event_id=self._make_id(),
                    event_type="suggestion",
                    priority=priority,
                    title="Suggestion",
                    message=s.get("message", ""),
                    action=action,
                ),
            )

    async def _check_news_alerts(self) -> None:
        """Check news for topics matching user interests (every 30 min)."""
        if time.time() - self._last_news_check < 1800:
            return
        if not self._intelligence or not self._personality:
            return

        domains = self._personality.domains
        if not domains:
            return

        self._last_news_check = time.time()

        try:
            if self._assistant:
                skill = self._assistant._skill_registry.get("get_news")
                if skill:
                    topic = domains[0]
                    articles = await skill.run(topic=topic, count=1)
                    if articles:
                        a = articles[0]
                        # SKIP LLM re-write to save quota for voice!
                        message = f"{a.get('title', '')}"
                        if a.get('summary'):
                            message += f"\n\n{a.get('summary')[:150]}..."

                        await self._emit_throttled(
                            f"news_{topic}",
                            3600,
                            AutonomyEvent(
                                event_id=self._make_id(),
                                event_type="news_alert",
                                priority=EventPriority.LOW,
                                title=f"Proactive Alert: {topic.capitalize()}",
                                message=message,
                                action="get_news",
                                data={"article": a, "topic": topic},
                            ),
                        )
        except Exception as e:
            logger.debug(f"News alert check failed: {e}")

    # ── Emit helpers ──────────────────────────────────────────

    async def _emit(self, event: AutonomyEvent) -> None:
        """Emit an event to all sinks."""
        if event.event_id in self._dismissed_events:
            return

        self._event_log.append(event)
        if len(self._event_log) > 200:
            self._event_log = self._event_log[-200:]

        await self._broadcast(event)

        if self._cloud and self._cloud.available:
            try:
                self._cloud.log_activity(event.event_type, event.message)
            except Exception:
                pass

        if (
            self._voice
            and self._personality
            and self._personality.speak_proactively
            and event.priority in (EventPriority.HIGH, EventPriority.CRITICAL)
        ):
            asyncio.create_task(self._voice.speak(event.message))

        logger.info(f"[AUTONOMY] {event.priority.value.upper()} | {event.title}: {event.message[:80]}")

    async def _emit_throttled(self, key: str, min_interval: float, event: AutonomyEvent) -> None:
        last = self._last_suggestion_times.get(key, 0)
        if time.time() - last < min_interval:
            return
        self._last_suggestion_times[key] = time.time()
        await self._emit(event)

    async def trigger(self, event_type: str, message: str, priority: str = "medium", data: dict | None = None) -> None:
        p = EventPriority(priority) if priority in EventPriority._value2member_map_ else EventPriority.MEDIUM
        await self._emit(AutonomyEvent(
            event_id=self._make_id(),
            event_type=event_type,
            priority=p,
            title=event_type.replace("_", " ").title(),
            message=message,
            data=data or {},
        ))

    def dismiss(self, event_id: str) -> None:
        self._dismissed_events.add(event_id)

    def get_recent_events(self, limit: int = 50, event_type: str = "") -> list[dict]:
        events = self._event_log[-limit:]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.to_dict() for e in reversed(events)]

    def get_stats(self) -> dict:
        counts: dict[str, int] = {}
        for e in self._event_log:
            counts[e.event_type] = counts.get(e.event_type, 0) + 1
        return {
            "total_events": len(self._event_log),
            "by_type": counts,
            "running": self._running,
            "subscribers": len(self._subscribers),
        }

    async def execute_autonomous_task(self, goal: str) -> None:
        """
        Takes a complex user goal, uses the Planner to break it down,
        and uses the Executor to run the steps. Runs in background.
        """
        if not self._assistant:
            logger.error("Cannot execute autonomous task: Assistant dependency not set")
            return

        logger.info(f"Starting autonomous task for goal: {goal}")
        await self.trigger("task_started", f"Starting autonomous task: {goal}", priority="high")

        try:
            # 1. Build context
            broker = get_context_broker(self._assistant.memory)
            context = await broker.build_context(goal)

            # 2. Extract tools
            tools = self._assistant._skill_registry

            # 3. Use Parallel Agents (Orchestrator) if the goal explicitly contains " and "
            if " and " in goal.lower() and len(goal.split(" and ")) > 1:
                goals = [g.strip() for g in goal.split(" and ") if g.strip()]
                from core.agents import AgentOrchestrator
                orchestrator = AgentOrchestrator(self._assistant._router, tools)
                results = await orchestrator.run_parallel(goals, assistant=self._assistant)
                trace = {"status": "success", "results": results}
            else:
                from core.reasoning import ReActEngine
                engine = ReActEngine(self._assistant._router)
                result = await engine.solve(goal, tools, assistant=self._assistant)
                trace = {"status": "success", "result": result}

            # 4. Notify completion
            if trace.get("status") == "success":
                await self.trigger("task_completed", f"Autonomous task completed: {goal}", priority="high", data=trace)
            else:
                err = trace.get("error", "Unknown error")
                await self.trigger("task_failed", f"Autonomous task failed: {err}", priority="high", data=trace)
                
        except Exception as e:
            logger.error(f"Error executing autonomous task '{goal}': {e}")
            await self.trigger("task_failed", f"Error: {str(e)}", priority="high")
