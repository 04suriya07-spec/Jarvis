"""
Morning Digest Agent
─────────────────────
Produces a personalised daily briefing:
  • Top news headlines
  • Weather for user's location
  • Calendar / reminders for the day
  • Fun fact or motivational quote
  • Reads it aloud via TTS

Schedule with APScheduler or run on demand.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.agent.morning_digest")
cfg = get_config()

MOTIVATIONAL_QUOTES = [
    "The secret of getting ahead is getting started. — Mark Twain",
    "It does not matter how slowly you go as long as you do not stop. — Confucius",
    "Everything you've ever wanted is on the other side of fear. — George Addair",
    "Success is not final, failure is not fatal: it is the courage to continue that counts. — Churchill",
    "Believe you can and you're halfway there. — Theodore Roosevelt",
    "You miss 100% of the shots you don't take. — Wayne Gretzky",
]


class MorningDigestAgent:
    """Generates and optionally reads the morning digest."""

    def __init__(self, assistant=None, voice=None):
        self._assistant = assistant
        self._voice = voice
        self._location = "London"   # Will be personalised from user facts

    async def run(
        self,
        location: str = "",
        speak: bool = True,
    ) -> dict:
        """Generate and optionally speak the morning digest."""
        loc = location or self._location
        today = date.today().strftime("%A, %B %d, %Y")

        logger.info(f"Generating morning digest for {loc} on {today}")

        # Gather all info in parallel
        weather_task = self._get_weather(loc)
        news_task = self._get_news()
        reminders_task = self._get_todays_reminders()
        quote_task = self._get_quote()

        weather, news, reminders, quote = await asyncio.gather(
            weather_task, news_task, reminders_task, quote_task
        )

        # Build digest text
        digest = self._build_digest(today, weather, news, reminders, quote)

        if speak and self._voice:
            # Speak a shorter version
            spoken = self._build_spoken_version(today, weather, news, quote)
            asyncio.create_task(self._voice.speak(spoken))

        return {
            "date": today,
            "weather": weather,
            "news": news,
            "reminders": reminders,
            "quote": quote,
            "digest_text": digest,
        }

    async def _get_weather(self, location: str) -> dict:
        if self._assistant:
            skill = self._assistant._skill_registry.get("get_weather")
            if skill:
                try:
                    return await skill.run(location=location, forecast_days=1)
                except Exception as e:
                    logger.warning(f"Weather fetch failed: {e}")
        return {}

    async def _get_news(self) -> list[dict]:
        if self._assistant:
            skill = self._assistant._skill_registry.get("get_news")
            if skill:
                try:
                    return await skill.run(count=5)
                except Exception as e:
                    logger.warning(f"News fetch failed: {e}")
        return []

    async def _get_todays_reminders(self) -> list[dict]:
        if self._assistant:
            skill = self._assistant._skill_registry.get("scheduler")
            if skill:
                try:
                    all_reminders = await skill.run(action="list")
                    today_str = date.today().isoformat()
                    return [
                        r for r in all_reminders
                        if r.get("when", "").startswith(today_str)
                        and r.get("status") == "pending"
                    ]
                except Exception:
                    pass
        return []

    async def _get_quote(self) -> str:
        import random
        return random.choice(MOTIVATIONAL_QUOTES)

    def _build_digest(
        self,
        today: str,
        weather: dict,
        news: list[dict],
        reminders: list[dict],
        quote: str,
    ) -> str:
        lines = [f"# Good morning! — {today}\n"]

        # Weather
        if weather.get("current"):
            w = weather["current"]
            lines.append(f"## Weather — {w.get('location', '')}")
            lines.append(
                f"{w.get('description', '')} | {w.get('temp', '')} "
                f"(feels like {w.get('feels_like', '')})"
            )
            lines.append(f"Humidity: {w.get('humidity', '')} | Wind: {w.get('wind_speed', '')}\n")

        # News
        if news:
            lines.append("## Top Headlines")
            for article in news[:5]:
                lines.append(f"- **{article.get('title', '')}** ({article.get('source', '')})")
            lines.append("")

        # Reminders
        if reminders:
            lines.append("## Today's Reminders")
            for r in reminders:
                lines.append(f"- {r['title']} at {r['when']}")
            lines.append("")

        # Quote
        lines.append(f"## Quote of the Day\n> {quote}")

        return "\n".join(lines)

    def _build_spoken_version(
        self, today: str, weather: dict, news: list[dict], quote: str
    ) -> str:
        parts = [f"Good morning! Today is {today}."]

        if weather.get("current"):
            w = weather["current"]
            parts.append(
                f"The weather in {w.get('location', 'your area')} is {w.get('description', '')} "
                f"with a temperature of {w.get('temp', '')}."
            )

        if news:
            parts.append("Here are today's top headlines.")
            for i, article in enumerate(news[:3], 1):
                parts.append(f"{i}. {article.get('title', '')}")

        parts.append(f"And your quote for the day: {quote}")
        return " ".join(parts)
