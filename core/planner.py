"""Planner to convert goals into executable steps."""

from __future__ import annotations

import json
from typing import Any

from core.context_broker import ContextBundle
from core.llm.router import LLMRouter
from core.models import PlanStep, RiskLevel
from core.logger import get_logger

logger = get_logger("javris.planner")

PLANNER_SYSTEM_PROMPT = """You are Javris, an advanced AI planner.
Your job is to break down the user's goal into a list of atomic, sequential executable steps.
You have access to specific tools. If a tool is needed, specify the tool name and arguments.
If a step requires your own reasoning or generation without a tool, omit the tool_name.

Output JSON format exactly:
[
  {
    "goal": "Description of what this step achieves",
    "skill": "tool_name", // Optional, if a specific tool/skill is used
    "args": {"arg1": "value1"}, // Arguments for the tool, if any
    "risk": "read_only" // one of: read_only, write_private, send_external, control_computer, execute_code, delete_or_destructive, financial_or_purchase, credential_access
  }
]
Do not output anything other than the JSON array.
"""

class Planner:
    def __init__(self, router: LLMRouter):
        self.router = router

    async def plan(self, goal: str, context: ContextBundle) -> list[PlanStep]:
        prompt = f"Context:\n{context.to_string()}\n\nUser Goal:\n{goal}\n\nGenerate the JSON plan array."
        
        try:
            response_text = await self.router.chat(
                messages=[{"role": "user", "content": prompt}],
                system=PLANNER_SYSTEM_PROMPT,
                max_tokens=2048,
            )
            
            # Basic json extraction
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:-3]
            elif response_text.startswith("```"):
                response_text = response_text[3:-3]
            
            raw_steps = json.loads(response_text.strip())
            
            steps = []
            for item in raw_steps:
                steps.append(PlanStep(
                    goal=item.get("goal", "Execute step"),
                    skill=item.get("skill"),
                    args=item.get("args", {}),
                    risk=RiskLevel(item.get("risk", "read_only")),
                ))
            return steps
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse plan JSON: {e}\nResponse was: {response_text}")
            # Fallback to a single generic step
            return [PlanStep(goal=goal, skill=None, risk=RiskLevel.READ_ONLY)]
        except Exception as e:
            logger.error(f"Planner error: {e}")
            return [PlanStep(goal=goal, skill=None, risk=RiskLevel.READ_ONLY)]

_planner: Planner | None = None

def get_planner(router: LLMRouter | None = None) -> Planner:
    global _planner
    if _planner is None:
        if router is None:
            raise ValueError("LLMRouter required to initialize Planner")
        _planner = Planner(router)
    return _planner
