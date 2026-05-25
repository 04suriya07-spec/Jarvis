"""Agent Orchestrator for running parallel tasks."""

from __future__ import annotations

import asyncio
from typing import Any

from core.logger import get_logger
from core.reasoning import ReActEngine

logger = get_logger("javris.agents")

class AgentOrchestrator:
    """Spawns parallel ReAct engines for concurrent sub-tasks."""
    
    def __init__(self, router: Any, tools: dict):
        self.router = router
        self.tools = tools

    async def run_parallel(self, goals: list[str], assistant: Any = None) -> dict[str, str]:
        """
        Executes multiple goals simultaneously using separate ReAct engines.
        Returns a map of goal -> final_answer.
        """
        logger.info(f"[Orchestrator] Spawning {len(goals)} parallel agents for goals: {goals}")
        
        async def _run_agent(goal: str) -> tuple[str, str]:
            engine = ReActEngine(self.router)
            try:
                result = await engine.solve(goal, self.tools, assistant)
                return goal, result
            except Exception as e:
                logger.error(f"[Orchestrator] Agent failed for goal '{goal}': {e}")
                return goal, f"Failed: {e}"

        tasks = [_run_agent(g) for g in goals]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_map = {}
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"[Orchestrator] Agent execution exception: {r}")
                continue
            goal, answer = r
            final_map[goal] = answer
            
        return final_map
