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
            # Use the news skill if assistant is ready
            if self._assistant:
                skill = self._assistant._skill_registry.get("get_news")
                if skill:
                    topic = domains[0]  # Top domain
                    articles = await skill.run(topic=topic, count=1)
                    if articles:
                        a = articles[0]
                        # SKIP LLM re-write to save quota for voice!
                        # We just use the raw headline for autonomy events
                        message = a.get('title', "")[:200]
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
