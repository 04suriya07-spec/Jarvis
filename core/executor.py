"""Executor to run plan steps autonomously."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from core.models import PlanStep, SkillResult, ExecutionTrace
from core.task_ledger import get_task_ledger
from core.policy import get_policy_engine
from core.verifier import get_verifier
from core.recovery import get_recovery_engine
from core.events import get_event_bus
from core.logger import get_logger

logger = get_logger("javris.executor")

class Executor:
    def __init__(self, assistant_ref: Any):
        # We need a reference to the assistant to dispatch tools
        self.assistant = assistant_ref
        self.ledger = get_task_ledger()
        self.policy = get_policy_engine()
        self.verifier = get_verifier()
        self.recovery = get_recovery_engine()
        self.events = get_event_bus()

    async def execute(self, goal: str, steps: list[PlanStep]) -> ExecutionTrace:
        trace = ExecutionTrace(user_goal=goal, plan=steps)
        
        # 1. Create task in ledger
        highest_risk = max([s.risk.value for s in steps] + ["read_only"])
        task_id = self.ledger.create_task(goal, risk_level=highest_risk)
        
        await self.events.publish("task_started", {"task_id": task_id, "goal": goal}, trace_id=trace.trace_id)
        
        overall_success = True
        final_result = None

        for i, step in enumerate(steps):
            step_id = self.ledger.add_step(
                task_id=task_id, 
                step_index=i, 
                action_type="tool_call" if step.skill else "reasoning", 
                tool_name=step.skill or "", 
                input_data=step.args
            )
            
            await self.events.publish("step_started", {"task_id": task_id, "step_id": step_id, "goal": step.goal}, trace_id=trace.trace_id)
            
            result = None
            if step.skill:
                # Dispatch tool through assistant
                # This already includes policy checking in _dispatch_tool, but we could check here too
                
                try:
                    # Assistant._dispatch_tool returns a json string or str
                    # Wait, we might need a direct way to call the tool to get a SkillResult object back
                    # Let's use the assistant's registry directly, but policy check manually
                    
                    skill = self.assistant._skill_registry.get(step.skill)
                    if not skill:
                        result = SkillResult(ok=False, error=f"Unknown skill: {step.skill}")
                    else:
                        decision = self.policy.evaluate(step.skill, step.args)
                        if not decision.allowed:
                            result = SkillResult(
                                ok=False,
                                error=decision.reason,
                                metadata={
                                    "approval_required": decision.requires_approval,
                                    "risk": decision.risk.value,
                                    "action_hash": decision.action_hash,
                                    "tool": step.skill,
                                }
                            )
                        else:
                            raw = await skill.run(**step.args)
                            result = skill.normalize_result(raw) if hasattr(skill, "normalize_result") else SkillResult.from_raw(raw)
                            
                except Exception as e:
                    logger.error(f"Error executing step {step.goal}: {e}")
                    result = SkillResult(ok=False, error=str(e))
            else:
                # Reasoning step - nothing to execute right now, consider it a success
                result = SkillResult(ok=True, data="Reasoning step completed.")
            
            # Verify
            verified = await self.verifier.verify(step, result)
            
            if not verified or not result.ok:
                # Recovery
                recovered, new_result = await self.recovery.recover(step, result)
                if recovered and new_result:
                    result = new_result
                    verified = await self.verifier.verify(step, result)
                    
            if not verified or not result.ok:
                overall_success = False
                final_result = result
                self.ledger.complete_step(step_id, result.model_dump(), status="failed", error=result.error or "Verification failed")
                await self.events.publish("step_failed", {"task_id": task_id, "step_id": step_id, "error": result.error}, trace_id=trace.trace_id)
                break
                
            self.ledger.complete_step(step_id, result.model_dump(), status="completed")
            await self.events.publish("step_completed", {"task_id": task_id, "step_id": step_id}, trace_id=trace.trace_id)
            final_result = result

        # Update task status
        task_status = "completed" if overall_success else "failed"
        err_str = final_result.error if final_result and not final_result.ok else ""
        res_summary = "Task finished successfully." if overall_success else "Task failed during execution."
        
        self.ledger.update_task_status(task_id, task_status, result_summary=res_summary, error=err_str)
        
        if overall_success:
            await self.events.publish("task_completed", {"task_id": task_id}, trace_id=trace.trace_id)
        else:
            await self.events.publish("task_failed", {"task_id": task_id, "error": err_str}, trace_id=trace.trace_id)
            
        trace.final_result = final_result or SkillResult(ok=overall_success, error=err_str)
        return trace

_executor: Executor | None = None

def get_executor(assistant_ref: Any = None) -> Executor:
    global _executor
    if _executor is None:
        if assistant_ref is None:
            raise ValueError("Assistant reference required to initialize Executor")
        _executor = Executor(assistant_ref)
    return _executor
