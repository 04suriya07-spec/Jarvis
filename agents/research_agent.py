"""
Deep Research Agent
────────────────────
Multi-hop web research with citation tracking.
Given a topic, it:
  1. Breaks it into sub-questions
  2. Searches each independently
  3. Synthesises a structured report with sources
"""

from __future__ import annotations

import asyncio
from typing import Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.agent.research")
cfg = get_config()


class ResearchAgent:
    """Autonomous research agent that produces cited reports."""

    def __init__(self, assistant=None):
        self._assistant = assistant

    async def research(
        self,
        topic: str,
        depth: int = 3,
        on_progress=None,
    ) -> dict:
        """
        Conduct deep research on a topic.

        Args:
            topic: Research question or topic
            depth: Number of sub-questions to explore (1-5)
            on_progress: Optional async callback(step: str) for streaming progress

        Returns:
            {"topic", "summary", "sections", "sources", "sub_questions"}
        """
        logger.info(f"Research started: {topic!r} depth={depth}")

        async def progress(msg: str):
            logger.info(f"Research: {msg}")
            if on_progress:
                await on_progress(msg)

        # Step 1: Generate sub-questions
        await progress("Generating research plan...")
        sub_questions = await self._generate_sub_questions(topic, depth)

        # Step 2: Search each sub-question in parallel
        await progress(f"Searching {len(sub_questions)} sub-topics...")
        search_tasks = [self._search_topic(q) for q in sub_questions]
        search_results = await asyncio.gather(*search_tasks)

        # Step 3: Compile sources
        all_sources = []
        sections_data = []
        for q, results in zip(sub_questions, search_results):
            sources = [r for r in results if r.get("url")]
            all_sources.extend(sources)
            sections_data.append({"question": q, "sources": sources})

        # Step 4: Synthesise report
        await progress("Synthesising report...")
        report = await self._synthesise(topic, sections_data)

        return {
            "success": True,
            "topic": topic,
            "summary": report.get("summary", ""),
            "full_report": report.get("full_report", report.get("summary", "")),
            "sections": report.get("sections", []),
            "sub_questions": sub_questions,
            "sources": all_sources[:20],
            "source_count": len(all_sources),
        }

    async def _generate_sub_questions(self, topic: str, n: int) -> list[str]:
        """Ask the LLM to decompose a topic into sub-questions."""
        if not self._assistant:
            return [topic]

        prompt = (
            f"Break this research topic into {n} specific sub-questions that together "
            f"would give a comprehensive understanding.\n\nTopic: {topic}\n\n"
            f"Reply ONLY with a numbered list of sub-questions. No preamble."
        )
        try:
            if self._assistant and self._assistant._router:
                text = await self._assistant._router.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are an expert research planner.",
                    max_tokens=512
                )
            else:
                logger.warning("No LLM router available for sub-question generation")
                return [topic]
            lines = [
                l.lstrip("0123456789.-) ").strip()
                for l in text.strip().splitlines()
                if l.strip()
            ]
            return lines[:n] if lines else [topic]
        except Exception as e:
            logger.warning(f"Sub-question generation failed: {e}")
            return [topic]

    async def _search_topic(self, query: str) -> list[dict]:
        """Search the web for a specific sub-question."""
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=4))

            results = await loop.run_in_executor(None, _search)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "query": query,
                }
                for r in results
            ]
        except Exception as e:
            logger.warning(f"Search failed for {query!r}: {e}")
            return []

    async def _synthesise(self, topic: str, sections_data: list[dict]) -> dict:
        """Use the LLM to write a structured report."""
        if not self._assistant:
            return {"summary": "No assistant available", "sections": []}

        # Build context from search snippets
        context_parts = []
        for s in sections_data:
            context_parts.append(f"\n### {s['question']}")
            for src in s["sources"][:3]:
                context_parts.append(
                    f"- [{src['title']}]({src['url']}): {src['snippet'][:300]}"
                )

        context = "\n".join(context_parts)

        prompt = f"""You are writing a comprehensive research report.

Topic: {topic}

Source material:
{context}

Write a structured Markdown report with:
1. An executive summary (2-3 sentences)
2. Key findings (bulleted)
3. One section per sub-topic with analysis
4. A conclusion

Cite sources inline as [Source Title](url). Be analytical, not just summarizing."""

        try:
            if self._assistant and self._assistant._router:
                report_text = await self._assistant._router.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are an expert research analyst.",
                    max_tokens=3000
                )
            else:
                return {"summary": "No LLM router available for synthesis", "sections": []}
            # Extract summary: text before the first ## heading (or first paragraph)
            lines = report_text.splitlines()
            summary_lines = []
            body_lines = []
            in_body = False
            for line in lines:
                if line.startswith("##") or in_body:
                    in_body = True
                    body_lines.append(line)
                else:
                    summary_lines.append(line)

            summary = "\n".join(summary_lines).strip()
            # If LLM started with ## immediately, use first non-empty paragraph as summary
            if not summary:
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        summary = stripped
                        break
            if not summary:
                summary = report_text[:400].strip()

            return {
                "summary": summary,
                "sections": [{"content": "\n".join(body_lines)}],
                "full_report": report_text,
            }
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return {"summary": str(e), "sections": []}
