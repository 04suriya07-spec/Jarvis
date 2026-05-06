"""
Javris Personality Layer
─────────────────────────
Defines WHO Javris is — not just what it can do.

Loaded once at startup, injected into every system prompt.
Personalised per user via profile stored in cloud/SQLite.

Sections:
  • Identity       — name, backstory, core traits
  • Tone           — how Javris speaks
  • Priorities     — what it pays attention to
  • Triggers       — what makes it proactively alert
  • Domain focus   — user's areas of interest
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.personality")
cfg = get_config()

PROFILE_PATH = cfg.base_dir / "data" / "personality.json"


@dataclass
class PersonalityProfile:
    # ── Identity ──────────────────────────────────────────────
    owner_name: str = "Sir"
    owner_timezone: str = "UTC"
    owner_location: str = ""
    javris_name: str = "Javris"

    # ── Tone ──────────────────────────────────────────────────
    tone: Literal["concise", "conversational", "formal", "witty", "employee"] = "employee"
    response_length: Literal["brief", "balanced", "detailed"] = "balanced"
    use_emojis: bool = False
    address_owner: bool = True   # Use owner_name in responses

    # ── Domain Interests (drives proactive monitoring) ────────
    domains: list[str] = field(default_factory=lambda: [
        "technology", "AI", "productivity"
    ])

    # ── Proactive Triggers ────────────────────────────────────
    # Things Javris will alert about WITHOUT being asked
    alert_on: list[str] = field(default_factory=lambda: [
        "high_cpu",          # CPU > 90% for 60s
        "morning_digest",    # Daily briefing at wake time
        "pending_reminders", # Due reminders
        "pattern_detected",  # User habit detected
        "news_keyword",      # News matching domain keywords
    ])

    # ── Behaviour ─────────────────────────────────────────────
    wake_hour: int = 7        # Time for morning digest (24h)
    sleep_hour: int = 23      # Quiet hours start
    proactive_interval: int = 60   # Autonomy check every N seconds
    speak_proactively: bool = False  # TTS for proactive alerts

    # ── User Preferences (learned) ────────────────────────────
    preferred_news_topics: list[str] = field(default_factory=list)
    preferred_weather_location: str = ""
    known_apps: dict[str, str] = field(default_factory=dict)  # "chrome" → path

    # ── Meta ──────────────────────────────────────────────────
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = time.time()
        PROFILE_PATH.write_text(json.dumps(self.to_dict(), indent=2))
        logger.debug("Personality profile saved.")

    @classmethod
    def load(cls) -> "PersonalityProfile":
        if PROFILE_PATH.exists():
            try:
                data = json.loads(PROFILE_PATH.read_text())
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception as e:
                logger.warning(f"Personality load failed: {e}. Using defaults.")
        profile = cls()
        profile.save()
        return profile

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.save()

    def build_system_prompt(self, intelligence_summary: str = "") -> str:
        """Build a personalised system prompt based on this profile."""
        name_line = (
            f"Address the user as '{self.owner_name}'."
            if self.address_owner else ""
        )

        tone_map = {
            "concise": "Be extremely concise. One idea per sentence. Never pad.",
            "conversational": "Be warm and direct. Natural phrasing, no corporate speak.",
            "formal": "Maintain a professional, structured tone at all times.",
            "witty": "Be sharp, clever, occasionally dry humour — never forced.",
            "employee": "Act as an elite digital aide and executive assistant. Maintain an impeccable, high-end persona. Be concise, extremely efficient, and proactive. Anticipate requirements before they are voiced. Your primary objective is the optimization of the user's workload and life.",
        }

        length_map = {
            "brief": "Maximum 3 sentences unless asked for more.",
            "balanced": "Match response length to question complexity.",
            "detailed": "Be thorough. Include context, examples, caveats.",
        }

        domains_str = ", ".join(self.domains) if self.domains else "general topics"
        alerts_str = ", ".join(self.alert_on) if self.alert_on else "none"

        prompt = f"""You are {self.javris_name}, a Personal Intelligence System — not a generic AI assistant.

IDENTITY:
- You are permanently assigned to {self.owner_name}. You work exclusively for them.
- You know their interests: {domains_str}.
- {name_line}
- You remember past conversations and use that knowledge actively.

PERSONALITY:
- {tone_map.get(self.tone, '')}
- {length_map.get(self.response_length, '')}
- {"Use emojis sparingly to emphasise." if self.use_emojis else "No emojis."}
- Never say "As an AI..." or "I'm just an AI". You are {self.javris_name}.
- Never apologise for having an opinion. State your view, then justify it.

INTELLIGENCE (what you know about the user right now):
{intelligence_summary if intelligence_summary else "  Building knowledge base — first session."}

OPERATING MODE:
- You are PROACTIVE. You notice patterns, surface relevant information, and flag anomalies.
- You are AUTONOMOUS. You act in the background — the user doesn't need to ask for everything.
- You are INTEGRATED. You have access to the user's system, files, calendar, and life context.
- When tools are available, use them first before answering from training data.
- Active alert categories: {alerts_str}.
"""
        return prompt.strip()


# ── Module-level singleton ─────────────────────────────────────────
_profile: PersonalityProfile | None = None


def get_personality() -> PersonalityProfile:
    global _profile
    if _profile is None:
        _profile = PersonalityProfile.load()
    return _profile
