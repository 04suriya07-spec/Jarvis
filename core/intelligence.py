"""
Javris Memory Intelligence
───────────────────────────
Transforms raw stored messages into KNOWLEDGE.

What it does:
  • Extracts facts from conversations automatically
  • Detects behavioural patterns (what user does at what time)
  • Tracks topics of interest and their frequency
  • Identifies recurring questions → proactive answers
  • Maintains a live "user model" that improves over time
  • Generates context summaries for system prompts

This is the difference between a filing cabinet and a brain.
"""

from __future__ import annotations

import asyncio
import json
import time
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.intelligence")
cfg = get_config()

INTEL_PATH = cfg.base_dir / "data" / "intelligence.json"


# ── Data structures ───────────────────────────────────────────────

@dataclass
class Pattern:
    """A detected behavioural pattern."""
    pattern_id: str
    description: str
    confidence: float          # 0.0–1.0
    occurrences: int
    first_seen: float
    last_seen: float
    time_of_day: str = ""      # "morning" | "afternoon" | "evening" | "night"
    days_of_week: list = field(default_factory=list)
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class UserFact:
    """A fact learned about the user from conversations."""
    fact_id: str
    category: str              # "preference" | "habit" | "personal" | "work" | "interest"
    statement: str             # e.g. "User prefers morning news briefings"
    evidence: str              # what triggered this fact
    confidence: float
    created_at: float
    updated_at: float
    reinforced: int = 1        # times this has been confirmed

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Intelligence Engine ───────────────────────────────────────────

class IntelligenceEngine:
    """
    The brain behind Javris's self-improving knowledge of its owner.

    Call `analyse()` periodically to process new messages.
    Call `build_summary()` to get a context string for the system prompt.
    """

    def __init__(self):
        self.patterns: dict[str, Pattern] = {}
        self.user_facts: dict[str, UserFact] = {}
        self.topic_frequency: Counter = Counter()
        self.hourly_activity: dict[int, int] = defaultdict(int)  # hour → msg count
        self.daily_activity: dict[str, int] = defaultdict(int)   # weekday → count
        self.query_history: list[dict] = []
        self._last_analysis: float = 0
        self._assistant = None   # injected after init

    def set_assistant(self, assistant) -> None:
        self._assistant = assistant

    # ── Persistence ───────────────────────────────────────────

    def save(self) -> None:
        INTEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "patterns": {k: v.to_dict() for k, v in self.patterns.items()},
            "user_facts": {k: v.to_dict() for k, v in self.user_facts.items()},
            "topic_frequency": dict(self.topic_frequency),
            "hourly_activity": dict(self.hourly_activity),
            "daily_activity": dict(self.daily_activity),
            "last_analysis": self._last_analysis,
        }
        INTEL_PATH.write_text(json.dumps(state, indent=2))

    def load(self) -> None:
        if not INTEL_PATH.exists():
            return
        try:
            content = INTEL_PATH.read_text().strip()
            if not content:
                logger.info("Intelligence file is empty. Initializing fresh.")
                return
            state = json.loads(content)
            for pid, pd in state.get("patterns", {}).items():
                self.patterns[pid] = Pattern(**pd)
            for fid, fd in state.get("user_facts", {}).items():
                self.user_facts[fid] = UserFact(**fd)
            self.topic_frequency = Counter(state.get("topic_frequency", {}))
            self.hourly_activity = defaultdict(int, {int(k): v for k, v in state.get("hourly_activity", {}).items()})
            self.daily_activity = defaultdict(int, state.get("daily_activity", {}))
            self._last_analysis = state.get("last_analysis", 0)
            logger.info(
                f"Intelligence loaded: {len(self.patterns)} patterns, "
                f"{len(self.user_facts)} facts"
            )
        except Exception as e:
            logger.warning(f"Intelligence load failed: {e}")

    # ── Core analysis ─────────────────────────────────────────

    async def analyse(self, messages: list[dict]) -> None:
        """
        Process a batch of messages and update the user model.
        Call this after every conversation turn or periodically.
        """
        if not messages:
            return

        for msg in messages:
            ts = msg.get("timestamp", time.time())
            content = msg.get("content", "")
            role = msg.get("role", "")

            if role != "user" or not content:
                continue

            # Track time patterns
            dt = datetime.fromtimestamp(ts)
            self.hourly_activity[dt.hour] += 1
            self.daily_activity[dt.strftime("%A")] += 1

            # Extract topics
            self._extract_topics(content)

            # Store for pattern analysis
            self.query_history.append({
                "content": content,
                "hour": dt.hour,
                "weekday": dt.strftime("%A"),
                "timestamp": ts,
            })

        # Detect patterns every 10 messages
        if len(self.query_history) % 10 == 0:
            await self._detect_patterns()

        # Extract facts via LLM (throttled)
        if time.time() - self._last_analysis > 300:  # every 5 min
            await self._extract_facts_llm(messages[-20:])
            self._last_analysis = time.time()

        self.save()

    def _extract_topics(self, text: str) -> None:
        """Simple keyword-based topic extraction."""
        TOPIC_KEYWORDS = {
            "weather": ["weather", "temperature", "rain", "forecast", "sunny", "humid"],
            "news": ["news", "headline", "article", "today", "happening", "current"],
            "code": ["code", "python", "function", "bug", "error", "script", "program"],
            "finance": ["stock", "market", "price", "gold", "crypto", "bitcoin", "invest"],
            "productivity": ["todo", "task", "reminder", "schedule", "calendar", "meeting"],
            "research": ["research", "explain", "how does", "what is", "why", "understand"],
            "system": ["open", "launch", "screenshot", "process", "cpu", "memory", "disk"],
        }
        lower = text.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                self.topic_frequency[topic] += 1

    async def _detect_patterns(self) -> None:
        """Detect recurring behavioural patterns from query history."""
        if len(self.query_history) < 5:
            return

        # Pattern 1: Active hours
        if self.hourly_activity:
            peak_hour = max(self.hourly_activity, key=self.hourly_activity.get)
            total = sum(self.hourly_activity.values())
            confidence = self.hourly_activity[peak_hour] / total if total else 0

            if confidence > 0.2:
                tod = self._hour_to_tod(peak_hour)
                pid = "peak_activity_time"
                self.patterns[pid] = Pattern(
                    pattern_id=pid,
                    description=f"Most active at {peak_hour:02d}:00 ({tod})",
                    confidence=min(confidence * 2, 1.0),
                    occurrences=self.hourly_activity[peak_hour],
                    first_seen=self.query_history[0]["timestamp"],
                    last_seen=self.query_history[-1]["timestamp"],
                    time_of_day=tod,
                )

        # Pattern 2: Top topics
        if self.topic_frequency:
            top_topics = self.topic_frequency.most_common(3)
            for topic, count in top_topics:
                if count >= 3:
                    pid = f"frequent_topic_{topic}"
                    total = sum(self.topic_frequency.values())
                    self.patterns[pid] = Pattern(
                        pattern_id=pid,
                        description=f"Frequently asks about {topic} ({count} times)",
                        confidence=min(count / total * 3, 1.0),
                        occurrences=count,
                        first_seen=time.time() - 86400,
                        last_seen=time.time(),
                        tags=[topic],
                    )

        # Pattern 3: Preferred day
        if self.daily_activity:
            peak_day = max(self.daily_activity, key=self.daily_activity.get)
            self.patterns["peak_day"] = Pattern(
                pattern_id="peak_day",
                description=f"Most active on {peak_day}s",
                confidence=0.6,
                occurrences=self.daily_activity[peak_day],
                first_seen=time.time() - 86400 * 7,
                last_seen=time.time(),
                days_of_week=[peak_day],
            )

    async def _extract_facts_llm(self, messages: list[dict]) -> None:
        """Use the LLM router to extract user facts from recent conversation.

        Only runs when a cloud provider (OpenAI / Gemini / Claude) is available
        and not rate-limited — we don't want background analysis competing with
        the main chat response on the local Ollama model.
        """
        router = getattr(self._assistant, "_router", None) if self._assistant else None
        if not router:
            return
        if not messages:
            return

        # Skip if only Ollama is available — don't compete with main chat
        cloud_available = any(
            s.name != "ollama" and s.available
            for s in router._slots
        )
        if not cloud_available:
            return

        conversation = "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}"
            for m in messages
            if m.get("role") in ("user", "assistant")
        )

        prompt = f"""Analyse this conversation and extract facts about the USER only.

CONVERSATION:
{conversation}

Output a JSON array of facts. Each fact:
{{
  "category": "preference|habit|personal|work|interest",
  "statement": "one clear sentence about the user",
  "confidence": 0.0-1.0
}}

Rules:
- Only include facts with confidence ≥ 0.6
- Focus on WHO they are and HOW they work, not what they asked
- Maximum 5 facts
- Return [] if nothing meaningful found
- Return ONLY the JSON array, no explanation"""

        try:
            text = await self._assistant._router.chat(
                [{"role": "user", "content": prompt}],
                system="You are a JSON fact extractor. Return only valid JSON arrays.",
                max_tokens=512,
            )
            # Extract JSON from response
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if not match:
                return
            facts = json.loads(match.group())

            for fact in facts:
                if fact.get("confidence", 0) < 0.6:
                    continue
                import uuid
                fid = str(uuid.uuid4())[:8]
                self.user_facts[fid] = UserFact(
                    fact_id=fid,
                    category=fact.get("category", "general"),
                    statement=fact.get("statement", ""),
                    evidence="llm_extraction",
                    confidence=fact.get("confidence", 0.7),
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            if facts:
                logger.info(f"Extracted {len(facts)} facts from conversation")
        except Exception as e:
            logger.debug(f"Fact extraction failed: {e}")

    # ── Proactive suggestions ─────────────────────────────────

    def get_proactive_suggestions(self) -> list[dict]:
        """
        Return suggestions Javris should make RIGHT NOW based on
        patterns, time of day, and user model.
        """
        suggestions = []
        now = datetime.now()
        hour = now.hour

        # Check if it's near a peak activity time
        if self.hourly_activity:
            peak = max(self.hourly_activity, key=self.hourly_activity.get)
            if abs(peak - hour) <= 1:
                top_topic = self.topic_frequency.most_common(1)
                if top_topic:
                    topic = top_topic[0][0]
                    suggestions.append({
                        "type": "pattern_match",
                        "message": f"You usually check {topic} around this time. Want an update?",
                        "action": f"get_{topic}",
                        "priority": "medium",
                    })

        # Morning briefing
        if 6 <= hour <= 9:
            suggestions.append({
                "type": "morning",
                "message": "Good morning. Ready for your daily briefing?",
                "action": "morning_digest",
                "priority": "high",
            })

        # Evening summary
        if 20 <= hour <= 22:
            suggestions.append({
                "type": "evening",
                "message": "End of day. Want a summary of what was discussed today?",
                "action": "daily_summary",
                "priority": "low",
            })

        return suggestions

    def should_suggest_topic(self, topic: str) -> bool:
        """True if the user frequently engages with this topic."""
        total = sum(self.topic_frequency.values())
        if total == 0:
            return False
        return self.topic_frequency.get(topic, 0) / total > 0.15

    # ── Summary for system prompt ─────────────────────────────

    def build_summary(self) -> str:
        """
        Returns a compact summary injected into every system prompt
        so Claude always knows who it's talking to.
        """
        lines = []

        # Facts
        high_conf_facts = [
            f for f in self.user_facts.values()
            if f.confidence >= 0.7
        ][:6]
        if high_conf_facts:
            lines.append("Known about user:")
            for f in high_conf_facts:
                lines.append(f"  • {f.statement}")

        # Patterns
        strong_patterns = [
            p for p in self.patterns.values()
            if p.confidence >= 0.5
        ][:3]
        if strong_patterns:
            lines.append("Detected patterns:")
            for p in strong_patterns:
                lines.append(f"  • {p.description}")

        # Top interests
        if self.topic_frequency:
            top = [t for t, _ in self.topic_frequency.most_common(4)]
            lines.append(f"Top interests: {', '.join(top)}")

        # Activity time
        if self.hourly_activity:
            peak = max(self.hourly_activity, key=self.hourly_activity.get)
            lines.append(f"Most active around: {peak:02d}:00")

        return "\n".join(lines) if lines else "Still learning about user."

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _hour_to_tod(hour: int) -> str:
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        return "night"

    def get_all_facts(self) -> list[dict]:
        return [f.to_dict() for f in sorted(
            self.user_facts.values(), key=lambda x: x.confidence, reverse=True
        )]

    def get_all_patterns(self) -> list[dict]:
        return [p.to_dict() for p in sorted(
            self.patterns.values(), key=lambda x: x.confidence, reverse=True
        )]

    def get_stats(self) -> dict:
        return {
            "total_facts": len(self.user_facts),
            "total_patterns": len(self.patterns),
            "top_topics": dict(self.topic_frequency.most_common(5)),
            "peak_hour": max(self.hourly_activity, key=self.hourly_activity.get)
                         if self.hourly_activity else None,
            "peak_day": max(self.daily_activity, key=self.daily_activity.get)
                        if self.daily_activity else None,
            "total_queries_analysed": len(self.query_history),
        }
