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
from typing import AsyncIterator

from core.config import get_config
from core.logger import get_logger
from core.memory import MemoryManager, Message
from core.personality import get_personality, PersonalityProfile
from core.intelligence import IntelligenceEngine
from core.autonomy import AutonomyEngine
from core.llm import LLMRouter
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
        from skills.life.tasks import TasksSkill
        from skills.life.browser import BrowserSkill
        from skills.finance import FinanceSkill
        from skills.music import MusicSkill
        # ── Skills from openclaw integration ─────────────────
        from skills.github import GitHubSkill
        from skills.notion import NotionSkill
        from skills.obsidian import ObsidianSkill
        from skills.telegram_notify import TelegramSkill
        from skills.discord_notify import DiscordSkill

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
            TasksSkill,
            BrowserSkill,
            FinanceSkill,
            MusicSkill,
            # openclaw-inspired skills
            GitHubSkill,
            NotionSkill,
            ObsidianSkill,
            TelegramSkill,
            DiscordSkill,
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

        system = (
            f"You are Javris, {owner}'s personal AI assistant. "
            f"Be {tone}, direct, and proactive. Address user as 'Sir'. "
            f"User interests: {domains}. "
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

        messages          = self.memory.get_context(last_n=20)
        system, max_tokens = self._get_system_prompt()
        reply             = await self._router.chat(messages, system, max_tokens=max_tokens)

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
        messages, (system, max_tokens) = (
            self.memory.get_context(last_n=20),
            self._get_system_prompt(),
        )
        full_reply = ""

        async for chunk in self._router.stream(messages, system, max_tokens=max_tokens):
            full_reply += chunk
            yield chunk

        await self.memory.add("assistant", full_reply)

    # ── Tool dispatch ─────────────────────────────────────────

    async def _dispatch_tool(self, name: str, params: dict) -> str:
        skill = self._skill_registry.get(name)
        if not skill:
            return f"Unknown tool: {name}"
        try:
            logger.info(f"Tool: {name}({list(params.keys())})")
            result = await skill.run(**params)

            # Fire an autonomy event for significant tool use
            await self.autonomy.trigger(
                "tool_used",
                f"Used {name}: {str(result)[:60]}",
                priority="low",
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as e:
            logger.error(f"Tool {name} error: {e}")
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
        self.intelligence.save()
        await self.memory.close()
