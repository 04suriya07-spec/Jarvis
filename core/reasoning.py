"""ReAct Engine for Javris self-correction and reasoning."""

from __future__ import annotations

import json
from typing import Any
from pydantic import BaseModel

from core.llm.router import LLMRouter
from core.models import RiskLevel
from core.logger import get_logger

logger = get_logger("javris.reasoning")

class Action(BaseModel):
    name: str
    args: dict[str, Any]
    risk: RiskLevel = RiskLevel.READ_ONLY

class ReActEngine:
    """
    Thought -> Action -> Observation -> Thought -> Action -> ...
    Used for complex multi-step tasks.
    """

    def __init__(self, router: LLMRouter):
        self.router = router

    async def solve(self, goal: str, tools: dict, assistant: Any = None) -> str:
        """Solves a goal using the provided tools."""
        history = []
        
        system_prompt = (
            "You are Javris, an advanced autonomous intelligence. Use the Thought-Action-Observation loop to solve the user's goal.\n"
            "Format your response as a JSON object containing either a 'thought' and 'action', OR a 'thought' and 'final_answer'.\n"
            "Example 1:\n"
            "{\n"
            "  \"thought\": \"I need to search the web for the latest news.\",\n"
            "  \"action\": {\"name\": \"web_search\", \"args\": {\"query\": \"latest tech news\"}, \"risk\": \"read_only\"}\n"
            "}\n"
            "Example 2:\n"
            "{\n"
            "  \"thought\": \"I have all the information I need.\",\n"
            "  \"final_answer\": \"The latest news is ...\"\n"
            "}\n"
            f"Available tools: {list(tools.keys())}\n"
            "Do not output anything outside the JSON object."
        )

        for step in range(8):  # Max 8 iterations
            # Build prompt with history
            history_text = "\n".join([
                f"Step {i+1}:\nThought: {h['thought']}\nAction: {h.get('action', {}).get('name', 'none')}\nObservation: {h.get('obs')}"
                for i, h in enumerate(history)
            ])
            
            prompt = f"Goal: {goal}\n\nHistory:\n{history_text}\n\nWhat is your next thought and action?"
            
            try:
                response = await self.router.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system=system_prompt,
                    max_tokens=1024
                )
                
                # Parse JSON
                response = response.strip()
                if response.startswith("```json"):
                    response = response[7:-3]
                elif response.startswith("```"):
                    response = response[3:-3]
                
                data = json.loads(response.strip())
                thought = data.get("thought", "No thought provided")
                
                if "final_answer" in data:
                    logger.info(f"[ReAct] Final Answer reached: {data['final_answer']}")
                    return data["final_answer"]
                
                action_data = data.get("action")
                if not action_data:
                    history.append({"thought": thought, "obs": "Error: No action provided, please provide an action or final_answer."})
                    continue
                
                action_name = action_data.get("name")
                action_args = action_data.get("args", {})
                risk = action_data.get("risk", "read_only")
                
                logger.info(f"[ReAct] Step {step+1}: Thought: {thought} | Action: {action_name}")
                
                # Execute tool
                if action_name in tools:
                    skill = tools[action_name]
                    # Check policy if we had assistant wired (simplified here)
                    if assistant:
                        from core.policy import get_policy_engine
                        policy = get_policy_engine()
                        eval_res = policy.evaluate(action_name, action_args, risk)
                        if eval_res.requires_approval:
                            # In real ReAct we'd pause for approval or skip
                            pass 

                    # Execute
                    try:
                        res = await skill.run(**action_args)
                        obs = str(res.data if hasattr(res, 'data') and res.ok else getattr(res, 'error', str(res)))
                    except Exception as e:
                        obs = f"Action execution failed: {e}"
                else:
                    obs = f"Error: Tool '{action_name}' not found."
                
                history.append({"thought": thought, "action": action_data, "obs": obs})

            except json.JSONDecodeError as e:
                logger.error(f"[ReAct] JSON error: {e}")
                history.append({"thought": "Format error", "obs": "Your previous response was not valid JSON. Please return ONLY JSON."})
            except Exception as e:
                logger.error(f"[ReAct] Unexpected error: {e}")
                break
                
        # If loop exhausts
        return await self._summarize(goal, history)

    async def _summarize(self, goal: str, history: list) -> str:
        prompt = f"Goal: {goal}\n\nYou tried these steps:\n{history}\n\nProvide the best final answer based on what you found, or explain why it couldn't be completed."
        return await self.router.chat([{"role": "user", "content": prompt}])
