"""
Javris Computer-Use Agent
──────────────────────────
The autonomous loop that lets Javris SEE and ACT on your screen.

Architecture:
  1. OBSERVE  — screenshot → Claude vision → structured understanding
  2. THINK    — Claude decides the next action based on the task goal
  3. ACT      — execute the action (click, type, scroll, navigate…)
  4. VERIFY   — screenshot again → did it work?
  5. REPEAT   → until task is complete or max_steps reached

Designed for:
  • Completing web forms and quizzes
  • Navigating edutech platforms
  • Filling assignments
  • Any repetitive browser task

The user can watch it work in real-time on their screen.
Progress is streamed to the dashboard via a callback.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Callable, Optional

from core.config import get_config
from core.logger import get_logger
from core.vision import VisionEngine, VisionAnalysis, ScreenState
from skills.computer.browser_agent import BrowserAgent, ActionResult

logger = get_logger("javris.computer_agent")
cfg = get_config()


# ── Data structures ───────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class AgentStep:
    step_num: int
    action_type: str         # "navigate" | "click" | "type" | "scroll" | "wait" | "read" | "answer"
    description: str
    result: str
    screenshot_b64: str = ""
    timestamp: float = field(default_factory=time.time)
    success: bool = True


@dataclass
class ComputerTask:
    task_id: str
    goal: str                # natural language description of what to accomplish
    url: str = ""            # starting URL (optional)
    status: TaskStatus = TaskStatus.PENDING
    steps: list[AgentStep] = field(default_factory=list)
    max_steps: int = 50
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0
    result_summary: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "url": self.url,
            "status": self.status.value,
            "steps_taken": len(self.steps),
            "max_steps": self.max_steps,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "result_summary": self.result_summary,
            "error": self.error,
            "recent_steps": [
                {
                    "step": s.step_num,
                    "action": s.action_type,
                    "description": s.description,
                    "result": s.result,
                    "success": s.success,
                }
                for s in self.steps[-5:]
            ],
        }


# ── Computer-Use Agent ────────────────────────────────────────────

class ComputerAgent:
    """
    Autonomous agent that controls the browser to complete tasks.

    Usage:
        agent = ComputerAgent()
        await agent.init(use_live_chrome=True)
        task = await agent.run_task(
            goal="Complete the quiz on this page",
            url="https://myedutech.com/quiz/123",
            on_step=lambda s: print(s.description),
        )
    """

    def __init__(self):
        self.browser = BrowserAgent()
        self.vision = VisionEngine()
        self._client = None
        self._tasks: dict[str, ComputerTask] = {}
        self._running_task: ComputerTask | None = None
        self._stop_requested = False
        self._pause_requested = False

    # ── Init ─────────────────────────────────────────────────

    async def init(self, use_live_chrome: bool = True) -> bool:
        """Connect to browser. Returns True if ready."""
        if cfg.anthropic_api_key:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)

        if use_live_chrome:
            ok = await self.browser.connect_to_live_chrome()
            if not ok:
                logger.info("Live Chrome not available, launching new browser")
                ok = await self.browser.launch_browser(headless=False)
        else:
            ok = await self.browser.launch_browser(headless=False)

        logger.info(f"ComputerAgent ready | browser={'connected' if ok else 'failed'}")
        return ok

    # ── Main task runner ──────────────────────────────────────

    async def run_task(
        self,
        goal: str,
        url: str = "",
        task_id: str = "",
        max_steps: int = 50,
        on_step: Callable[[AgentStep], None] | None = None,
        on_complete: Callable[[ComputerTask], None] | None = None,
    ) -> ComputerTask:
        """
        Execute a natural-language task autonomously.

        Args:
            goal: what to accomplish, e.g. "Complete the quiz and submit it"
            url: navigate here first (optional)
            task_id: unique ID (auto-generated if empty)
            max_steps: safety limit
            on_step: callback after each step (for live progress streaming)
            on_complete: callback when task finishes
        """
        import uuid
        task_id = task_id or str(uuid.uuid4())[:8]

        task = ComputerTask(
            task_id=task_id,
            goal=goal,
            url=url,
            max_steps=max_steps,
            status=TaskStatus.RUNNING,
        )
        self._tasks[task_id] = task
        self._running_task = task
        self._stop_requested = False
        self._pause_requested = False

        logger.info(f"Task started: [{task_id}] {goal}")

        try:
            # Navigate to starting URL if provided
            if url:
                result = await self.browser.goto(url)
                step = AgentStep(
                    step_num=0,
                    action_type="navigate",
                    description=f"Navigated to {url}",
                    result="success" if result.success else result.error,
                    success=result.success,
                )
                task.steps.append(step)
                if on_step:
                    on_step(step)
                await asyncio.sleep(2)

            # Main autonomous loop
            for i in range(1, max_steps + 1):
                if self._stop_requested:
                    task.status = TaskStatus.STOPPED
                    task.result_summary = "Stopped by user"
                    break

                while self._pause_requested:
                    await asyncio.sleep(0.5)

                step = await self._agent_step(task, i)
                task.steps.append(step)

                if on_step:
                    on_step(step)

                logger.info(f"  Step {i}/{max_steps}: [{step.action_type}] {step.description[:80]}")

                # Check completion
                if step.action_type == "complete":
                    task.status = TaskStatus.COMPLETED
                    task.result_summary = step.description
                    task.completed_at = time.time()
                    break

                # Check failure
                if step.action_type == "failed":
                    task.status = TaskStatus.FAILED
                    task.error = step.description
                    break

                # Small delay between steps (human-like pacing)
                await asyncio.sleep(1.5)

            else:
                task.status = TaskStatus.FAILED
                task.error = f"Reached max steps ({max_steps}) without completing"

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"Task error: {e}")

        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.COMPLETED

        self._running_task = None
        if on_complete:
            on_complete(task)

        logger.info(f"Task {task_id} ended: {task.status.value} | steps={len(task.steps)}")
        return task

    # ── Single agent step ─────────────────────────────────────

    async def _agent_step(self, task: ComputerTask, step_num: int) -> AgentStep:
        """
        One observe→think→act cycle.
        Returns the step taken.
        """
        # 1. OBSERVE — take screenshot from browser page
        try:
            page_b64 = await self.browser.page_screenshot()
            page_text = await self.browser.get_page_text()
            page_title = await self.browser.get_page_title()
            current_url = self.browser.current_url
        except Exception as e:
            return AgentStep(step_num, "error", f"Could not capture page: {e}", str(e), success=False)

        # 2. THINK — ask Claude what to do next
        action_plan = await self._think(
            task=task,
            step_num=step_num,
            page_text=page_text[:3000],
            page_title=page_title,
            current_url=current_url,
            page_b64=page_b64,
        )

        if not action_plan:
            return AgentStep(step_num, "error", "Could not determine action", "", success=False)

        action_type = action_plan.get("action", "wait")
        description = action_plan.get("description", "")

        # 3. ACT — execute the planned action
        result = await self._execute_action(action_plan)

        return AgentStep(
            step_num=step_num,
            action_type=action_type,
            description=description,
            result=result.detail if result.success else result.error,
            screenshot_b64=page_b64,
            success=result.success,
        )

    async def _think(
        self,
        task: ComputerTask,
        step_num: int,
        page_text: str,
        page_title: str,
        current_url: str,
        page_b64: str,
    ) -> dict | None:
        """Ask Claude to decide the next action given current page state."""
        if not self._client:
            return {"action": "failed", "description": "No AI client available"}

        recent_steps = "\n".join(
            f"  {s.step_num}. [{s.action_type}] {s.description} → {s.result[:60]}"
            for s in task.steps[-6:]
        )

        system = """You are a browser automation agent. You control a web browser to complete tasks for the user.
You see screenshots of the current page and decide the next action.
Be methodical, patient, and human-like in your interactions.
Never rush — wait for pages to load, scroll to find content, read carefully before acting."""

        prompt = f"""TASK: {task.goal}
STEP: {step_num}/{task.max_steps}
CURRENT URL: {current_url}
PAGE TITLE: {page_title}

RECENT ACTIONS:
{recent_steps if recent_steps else "  (first step)"}

PAGE CONTENT (first 3000 chars):
{page_text}

Based on the screenshot and page content, decide the SINGLE BEST next action.

Return ONLY a JSON object with this structure:
{{
  "action": "<one of: click|type|select_option|check_radio|scroll|navigate|wait|read|submit|press_key|complete|failed>",
  "description": "what you are doing and why",
  "selector": "<CSS selector if applicable, else empty>",
  "text": "<text to type or button text to click, if applicable>",
  "value": "<option value for selects, key name for press_key>",
  "url": "<URL to navigate to, if action=navigate>",
  "x_percent": <0-100, x click position as % of page width, if no selector>,
  "y_percent": <0-100, y click position as % of page height, if no selector>,
  "scroll_direction": "down|up",
  "reason": "why this action moves toward completing the task"
}}

Use action="complete" ONLY when the task is fully done.
Use action="failed" ONLY when the task cannot be completed.
Use action="wait" if the page is still loading or you need to pause.
"""

        try:
            content = [{"type": "text", "text": prompt}]
            if page_b64:
                content = [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": page_b64},
                    },
                    {"type": "text", "text": prompt},
                ]

            resp = await self._client.messages.create(
                model=cfg.javris_claude_model,
                max_tokens=600,
                system=system,
                messages=[{"role": "user", "content": content}],
            )
            raw = resp.content[0].text
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            logger.warning(f"Could not parse action JSON: {raw[:200]}")
            return None
        except Exception as e:
            logger.error(f"Think step failed: {e}")
            return None

    async def _execute_action(self, plan: dict) -> ActionResult:
        """Execute the action decided by the think step."""
        action = plan.get("action", "wait")
        selector = plan.get("selector", "")
        text = plan.get("text", "")
        value = plan.get("value", "")
        url = plan.get("url", "")
        x = float(plan.get("x_percent", 0))
        y = float(plan.get("y_percent", 0))
        scroll_dir = plan.get("scroll_direction", "down")
        description = plan.get("description", action)

        try:
            if action == "click":
                return await self.browser.click(selector=selector, text=text, x_percent=x, y_percent=y)

            elif action == "type":
                return await self.browser.type_text(selector=selector, text=text)

            elif action == "select_option":
                return await self.browser.select_option(selector=selector, value=value, label=text)

            elif action == "check_radio":
                if text:
                    return await self.browser.click_radio_by_text(text)
                return await self.browser.check(selector, True)

            elif action == "scroll":
                return await self.browser.scroll(scroll_dir, 400)

            elif action == "navigate":
                return await self.browser.goto(url)

            elif action == "wait":
                await asyncio.sleep(2)
                return ActionResult(True, "wait", "Waited 2 seconds")

            elif action == "press_key":
                return await self.browser.press_key(value or text or "Enter")

            elif action == "submit":
                return await self.browser.submit_form(selector)

            elif action in ("complete", "failed"):
                return ActionResult(True, action, description)

            else:
                await asyncio.sleep(1)
                return ActionResult(True, "unknown", f"Unknown action: {action}")

        except Exception as e:
            return ActionResult(False, action, error=str(e))

    # ── Control ───────────────────────────────────────────────

    def stop(self) -> None:
        """Stop the running task."""
        self._stop_requested = True
        logger.info("Stop requested")

    def pause(self) -> None:
        self._pause_requested = True
        logger.info("Pause requested")

    def resume(self) -> None:
        self._pause_requested = False
        logger.info("Resumed")

    # ── Queries ───────────────────────────────────────────────

    def get_task(self, task_id: str) -> ComputerTask | None:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[dict]:
        return [t.to_dict() for t in self._tasks.values()]

    def get_running_task(self) -> ComputerTask | None:
        return self._running_task

    def get_status(self) -> dict:
        rt = self._running_task
        return {
            "browser": self.browser.get_status(),
            "running_task": rt.to_dict() if rt else None,
            "total_tasks": len(self._tasks),
            "completed": sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED),
        }

    # ── Specialised task runners ──────────────────────────────

    async def complete_quiz(
        self,
        url: str,
        subject_context: str = "",
        on_step=None,
    ) -> ComputerTask:
        """
        Specialised runner for quiz completion.
        Reads each question, answers with Claude's knowledge, submits.
        """
        goal = (
            f"Complete the quiz on this page. "
            f"{'Subject: ' + subject_context + '. ' if subject_context else ''}"
            "Read each question carefully, select or type the correct answer, "
            "then move to the next question. Submit when all questions are answered."
        )
        return await self.run_task(goal=goal, url=url, max_steps=80, on_step=on_step)

    async def fill_assignment(
        self,
        url: str,
        instructions: str = "",
        on_step=None,
    ) -> ComputerTask:
        """Specialised runner for written assignments."""
        goal = (
            f"Fill in the assignment on this page. "
            f"{'Additional instructions: ' + instructions if instructions else ''} "
            "Read the requirements, write appropriate answers in all text fields, "
            "and submit the assignment when complete."
        )
        return await self.run_task(goal=goal, url=url, max_steps=60, on_step=on_step)

    async def navigate_and_read(self, url: str, on_step=None) -> ComputerTask:
        """Navigate to a page and summarise its content."""
        goal = (
            "Navigate to this page, scroll through all the content, "
            "read everything on the page, and when done report a complete summary."
        )
        return await self.run_task(goal=goal, url=url, max_steps=20, on_step=on_step)

    async def close(self) -> None:
        await self.browser.disconnect()
