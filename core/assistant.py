"""
Javris – Core Assistant Orchestrator  (v2 — Personal Intelligence System)
──────────────────────────────────────────────────────────────────────────
Now wires:
  • Personality   → personalised system prompt, tone, priorities
  • Intelligence  → user model injected into every prompt
  • Autonomy      → background loop that proactively acts
  • Life Skills   → files, calendar, tasks, browser
  • Voice         → primary interface mode
  • Memory        → short-term (ring) + long-term (SQLite) + cloud (Firestore)
  • LLMRouter     → UCB1-ranked parallel-hedged provider routing with
                    circuit breakers, LRU+TTL cache, instant fallback
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator

from core.config import get_config
from core.logger import get_logger
from core.memory import MemoryManager, Message
from core.personality import get_personality, PersonalityProfile
from core.intelligence import IntelligenceEngine
from core.autonomy import AutonomyEngine
from core.ambient import get_ambient_watcher, AmbientWatcher
from core.audit import get_audit_log
from core.events import get_event_bus
from core.llm import LLMRouter
from core.models import SkillResult
from core.policy import get_policy_engine
from storage.manager import StorageManager

logger = get_logger("javris.assistant")
cfg = get_config()


class Assistant:
    def __init__(self):
        self.memory = MemoryManager()
        self.personality: PersonalityProfile = get_personality()
        self.intelligence = IntelligenceEngine()
        self.autonomy = AutonomyEngine()
        self.storage = StorageManager()

        self._tools: list[dict] = []
        self._skill_registry: dict = {}
        self._cloud = None
        self._voice = None
        self._autonomy_task: asyncio.Task | None = None
        self._router: LLMRouter | None = None
        self._ambient: AmbientWatcher = get_ambient_watcher()
        self._audit = get_audit_log()
        self._events = get_event_bus()
        self._policy = get_policy_engine()

    # ── Initialisation ───────────────────────────────────────

    async def init(self) -> None:
        # Storage (local + Supabase + Degoo watcher)
        self.storage.init()

        # Memory
        await self.memory.init()

        # Intelligence — load persisted knowledge
        self.intelligence.load()
        self.intelligence.set_assistant(self)

        # Skills
        await self._load_skills()

        # LLM Router — replaces individual _call_* methods
        self._router = LLMRouter(
            tools=self._tools,
            tool_dispatch=self._dispatch_tool,
        )
        self._router.init()

        # Ambient watcher — start passive OS context tracking
        self._ambient.start()

        # Autonomy — wire deps, start background loop
        self.autonomy.set_dependencies(
            assistant=self,
            voice=self._voice,
            intelligence=self.intelligence,
            personality=self.personality,
            cloud=self._cloud,
        )

        logger.info(
            f"Assistant ready | {len(self._skill_registry)} skills | "
            f"owner={self.personality.owner_name}"
        )

    def start_autonomy(self) -> None:
        """Start the background autonomy loop (call after event loop exists)."""
        if self._autonomy_task is None or self._autonomy_task.done():
            self._autonomy_task = asyncio.create_task(self.autonomy.run())
            logger.info("Autonomy engine started")

    async def _load_skills(self) -> None:
        from skills.web_search import WebSearchSkill
        from skills.weather import WeatherSkill
        from skills.news import NewsSkill
        from skills.system_control import SystemControlSkill
        from skills.scheduler import SchedulerSkill
        from skills.code_runner import CodeRunnerSkill
        from skills.notes import NotesSkill
        from skills.life.files import FileSkill
        from skills.life.calendar_skill import CalendarSkill
        from skills.google_calendar import GoogleCalendarSkill
        from skills.life.tasks import TasksSkill
        from skills.life.browser import BrowserSkill
        from skills.finance import FinanceSkill
        from skills.music import MusicSkill
        from skills.documents import DocumentsSkill
        # ── Skills from openclaw integration ─────────────────
        from skills.github import GitHubSkill
        from skills.notion import NotionSkill
        from skills.obsidian import ObsidianSkill
        from skills.email_skill import EmailSkill
        from skills.system.wifi import WiFiSkill
        from skills.system.bluetooth import BluetoothSkill
        from skills.system.audio import AudioSkill
        from skills.system.notify import NotifySkill
        from skills.system.brightness import BrightnessSkill

        skill_classes = [
            WebSearchSkill,
            WeatherSkill,
            NewsSkill,
            SystemControlSkill,
            SchedulerSkill,
            CodeRunnerSkill,
            NotesSkill,
            FileSkill,
            CalendarSkill,
            GoogleCalendarSkill,
            TasksSkill,
            BrowserSkill,
            FinanceSkill,
            MusicSkill,
            DocumentsSkill,
            # openclaw-inspired skills
            GitHubSkill,
            NotionSkill,
            ObsidianSkill,
            EmailSkill,
            # Ubuntu/Linux system skills
            WiFiSkill,
            BluetoothSkill,
            AudioSkill,
            NotifySkill,
            BrightnessSkill,
        ]

        for cls in skill_classes:
            try:
                skill = cls()
                self._skill_registry[skill.name] = skill
                # Register under aliases so old code using "get_weather", etc. still works
                for alias in getattr(skill, "aliases", []):
                    self._skill_registry[alias] = skill
                if skill.tool_definition:
                    self._tools.append(skill.tool_definition)
            except Exception as e:
                logger.warning(f"Skill {cls.__name__} failed to load: {e}")

        logger.debug(f"Skills: {list(self._skill_registry.keys())}")

    # ── System prompt ─────────────────────────────────────────

    def _build_system_prompt(self, voice_mode: bool = False) -> str:
        intel_summary = self.intelligence.build_summary()
        prompt = self.personality.build_system_prompt(intel_summary)
        if voice_mode:
            prompt += (
                "\n\nVOICE MODE: You are speaking aloud. "
                "Keep responses to 1-2 short sentences. "
                "No lists, no markdown, no asterisks. Plain spoken English only."
            )
        return prompt

    # ── Chat (main entry point) ───────────────────────────────

    async def _recall_memory(self, user_input: str) -> str:
        """Semantic-search vector memory and return an injection block."""
        try:
            results = await self.memory.semantic_search(user_input, n=5)
            if not results:
                return ""
            snippets = []
            for r in results:
                score = r.get("score", 0)
                if score < 0.3:          # skip low-relevance hits
                    continue
                text = r.get("text", "").strip()
                role = r.get("metadata", {}).get("role", "")
                if text and role in ("user", "assistant"):
                    snippets.append(f"[{role}] {text[:180]}")
            if not snippets:
                return ""
            joined = "\n".join(snippets[:4])
            return f"\n\n[Relevant memory from past conversations]:\n{joined}"
        except Exception:
            return ""

    def _get_system_prompt(self, voice_mode: bool = False) -> tuple[str, int]:
        """
        Return (system_prompt, max_tokens).

        We use a single medium-length prompt (~70 tokens) for ALL providers:
          • Short enough that Ollama prefills in < 2s (vs 30s for full prompt)
          • Long enough that cloud providers give personalised, in-character replies
          • voice_mode forces 1-sentence replies + 60-token cap
          • chat mode uses 80-token cap (still concise, ~5-8s on CPU Ollama)
        """
        owner   = self.personality.owner_name
        domains = ", ".join(getattr(self.personality, "domains", ["technology", "AI"])[:3])
        tone    = getattr(self.personality, "tone", "concise")

        if voice_mode:
            system = (
                f"You are Javris, {owner}'s AI assistant. "
                f"Be {tone}. Address user as 'Sir'. "
                "Reply in ONE short sentence. No lists, no markdown, no asterisks."
            )
            return system, 60

        ambient_ctx = self._ambient.context_string()
        system = (
            f"You are Javris, {owner}'s personal AI assistant. "
            f"Be {tone}, direct, and proactive. Address user as 'Sir'. "
            f"User interests: {domains}. "
            f"Current context: {ambient_ctx}. "
            "No emojis. Never say 'As an AI'. "
            "Reply in 2-3 sentences unless detail is explicitly requested."
        )
        return system, 80

    async def chat(self, user_input: str) -> str:
        await self.memory.add("user", user_input)

        # Feed to intelligence engine asynchronously (non-blocking)
        asyncio.create_task(
            self.intelligence.analyse(
                [m.to_dict() for m in self.memory.short.get_history(last_n=10)]
            )
        )

        # Semantic memory recall — inject relevant past context
        memory_injection = await self._recall_memory(user_input)

        messages           = self.memory.get_context(last_n=20)
        system, max_tokens = self._get_system_prompt()
        if memory_injection:
            system += memory_injection
        reply              = await self._router.chat(messages, system, max_tokens=max_tokens)

        assistant_msg = await self.memory.add("assistant", reply)

        # Sync both turns to Supabase (fire-and-forget)
        session_id = self.memory.short.session_id
        asyncio.create_task(self._sync_turn(user_input, reply, session_id))

        if self._cloud:
            asyncio.create_task(self._cloud.sync_session(session_id))

        return reply

    async def _sync_turn(self, user_input: str, reply: str, session_id: str) -> None:
        """Push latest user+assistant turn to Supabase."""
        import time as _time
        try:
            await self.storage.sync_message({
                "message_id": f"{session_id}-u-{int(_time.time()*1000)}",
                "session_id": session_id,
                "role": "user",
                "content": user_input,
                "timestamp": _time.time(),
                "metadata": {},
            })
            await self.storage.sync_message({
                "message_id": f"{session_id}-a-{int(_time.time()*1000)}",
                "session_id": session_id,
                "role": "assistant",
                "content": reply,
                "timestamp": _time.time(),
                "metadata": {},
            })
        except Exception:
            pass  # storage sync is best-effort

    async def voice_stream(self, user_input: str) -> AsyncIterator[str]:
        """
        Streaming for voice mode.

        Optimised for low latency on Ollama (CPU):
          • Minimal system prompt — fewer input tokens = faster prefill
          • 150 token output cap — voice answers are 1-2 sentences
          • Only last 6 messages of context (less KV cache pressure)
        """
        await self.memory.add("user", user_input)
        asyncio.create_task(
            self.intelligence.analyse(
                [m.to_dict() for m in self.memory.short.get_history(last_n=6)]
            )
        )
        messages              = self.memory.get_context(last_n=6)
        system, max_tokens    = self._get_system_prompt(voice_mode=True)

        full_reply = ""
        async for chunk in self._router.stream(messages, system, max_tokens=150):
            full_reply += chunk
            yield chunk

        await self.memory.add("assistant", full_reply)

    # ── Streaming ─────────────────────────────────────────────

    async def stream_chat(self, user_input: str) -> AsyncIterator[str]:
        await self.memory.add("user", user_input)
        asyncio.create_task(
            self.intelligence.analyse(
                [m.to_dict() for m in self.memory.short.get_history(last_n=10)]
            )
        )
        memory_injection = await self._recall_memory(user_input)
        messages = self.memory.get_context(last_n=20)
        system, max_tokens = self._get_system_prompt()
        if memory_injection:
            system += memory_injection
        full_reply = ""

        async for chunk in self._router.stream(messages, system, max_tokens=max_tokens):
            full_reply += chunk
            yield chunk

        await self.memory.add("assistant", full_reply)

    # ── Tool dispatch ─────────────────────────────────────────

    async def _dispatch_tool(self, name: str, params: dict) -> str:
        trace_id = str(uuid.uuid4())
        skill = self._skill_registry.get(name)
        if not skill:
            return f"Unknown tool: {name}"

        decision = self._policy.evaluate(name, params)
        if not decision.allowed:
            result = SkillResult(
                ok=False,
                error=decision.reason,
                metadata={
                    "approval_required": decision.requires_approval,
                    "risk": decision.risk.value,
                    "action_hash": decision.action_hash,
                    "tool": name,
                },
            )
            self._audit.write(
                action=f"tool:{name}",
                risk=decision.risk,
                trace_id=trace_id,
                input_data=params,
                result=result,
                decision="blocked",
            )
            await self._events.publish(
                "tool_blocked",
                {"tool": name, "policy": decision.to_dict()},
                trace_id=trace_id,
            )
            await self.autonomy.trigger(
                "approval_required",
                f"{name} requires approval",
                priority="medium",
                data={"tool": name, "policy": decision.to_dict(), "trace_id": trace_id},
            )
            return result.model_dump_json()

        try:
            logger.info(f"Tool: {name}({list(params.keys())})")
            await self._events.publish(
                "tool_started",
                {"tool": name, "params": {k: str(v)[:80] for k, v in params.items()}},
                trace_id=trace_id,
            )
            raw_result = await skill.run(**params)
            result = skill.normalize_result(raw_result) if hasattr(skill, "normalize_result") else SkillResult.from_raw(raw_result)
            result_str = result.model_dump_json()
            self._audit.write(
                action=f"tool:{name}",
                risk=decision.risk,
                trace_id=trace_id,
                input_data=params,
                result=result,
                decision="executed",
            )
            await self._events.publish(
                "tool_finished",
                {"tool": name, "ok": result.ok, "risk": decision.risk.value},
                trace_id=trace_id,
            )

            # Fire a rich tool_used autonomy event for the HUD visualizer
            await self.autonomy.trigger(
                "tool_used",
                f"{name}",
                priority="low",
                data={
                    "tool": name,
                    "params": {k: str(v)[:80] for k, v in params.items()},
                    "result_preview": result_str[:120],
                    "status": "success" if result.ok else "failed",
                    "risk": decision.risk.value,
                    "trace_id": trace_id,
                },
            )
            return result_str
        except Exception as e:
            logger.error(f"Tool {name} error: {e}")
            result = SkillResult(ok=False, error=str(e), metadata={"tool": name})
            self._audit.write(
                action=f"tool:{name}",
                risk=decision.risk,
                trace_id=trace_id,
                input_data=params,
                result=result,
                decision="error",
            )
            await self._events.publish(
                "tool_failed",
                {"tool": name, "error": str(e)[:120], "risk": decision.risk.value},
                trace_id=trace_id,
            )
            await self.autonomy.trigger(
                "tool_used",
                f"{name} failed",
                priority="low",
                data={"tool": name, "params": list(params.keys()), "status": "failed", "error": str(e)[:80]},
            )
            return f"Tool error: {e}"

    # ── Helpers ───────────────────────────────────────────────

    async def remember(self, category: str, content: str) -> None:
        await self.memory.remember_fact(category, content)
        await self.intelligence.analyse([{"role": "user", "content": content, "timestamp": 0}])

    async def search_memory(self, query: str) -> list[dict]:
        return await self.memory.search(query)

    def new_session(self) -> None:
        self.memory.short.clear()
        logger.info(f"New session: {self.memory.short.session_id}")

    def update_personality(self, **kwargs) -> None:
        self.personality.update(**kwargs)
        logger.info(f"Personality updated: {kwargs}")

    async def close(self) -> None:
        if self._autonomy_task:
            self._autonomy_task.cancel()
            try:
                await self._autonomy_task
            except asyncio.CancelledError:
                pass
        self.autonomy.stop()
        self._ambient.stop()
        self.intelligence.save()
        await self.memory.close()
