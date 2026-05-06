"""
Javris Vision Engine
─────────────────────
Gives Javris eyes — it can SEE your screen.

Capabilities:
  • Screenshot full screen or specific window/region
  • Send screenshot to Claude vision API for analysis
  • Describe what's on screen
  • Find UI elements by description (button, field, checkbox)
  • Read text from screen (via Claude vision, no OCR library needed)
  • Track what changed between two screenshots

This is the sensory layer of the Computer-Use Agent.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.vision")
cfg = get_config()

SCREENSHOT_DIR = cfg.base_dir / "data" / "screenshots"


@dataclass
class ScreenState:
    """A captured moment of the screen."""
    image_b64: str           # base64-encoded PNG
    width: int
    height: int
    timestamp: float = field(default_factory=time.time)
    description: str = ""    # Claude's description (filled after analysis)
    file_path: str = ""


@dataclass
class UIElement:
    """A UI element found on screen by vision analysis."""
    description: str         # e.g. "Submit Quiz button"
    element_type: str        # "button" | "input" | "checkbox" | "link" | "text" | "image"
    location: str            # e.g. "center-right", "bottom of page"
    x: int = 0              # approximate pixel coordinates (0 if unknown)
    y: int = 0
    confidence: float = 0.9
    text_content: str = ""   # visible text on/in the element


@dataclass
class VisionAnalysis:
    """Full vision analysis result from Claude."""
    description: str                    # what's on screen
    page_title: str                     # detected page title
    page_type: str                      # "quiz" | "assignment" | "form" | "dashboard" | "other"
    elements: list[UIElement]           # interactive elements found
    questions: list[dict]               # detected quiz questions (if any)
    current_state: str                  # "on question 3/10", "form empty", "submitted", etc.
    suggested_action: str               # what Javris thinks should happen next
    raw_text: str                       # all readable text on screen


class VisionEngine:
    """
    Captures screenshots and analyses them using Claude's vision API.
    """

    def __init__(self):
        self._client = None
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def _get_client(self):
        if self._client:
            return self._client
        if cfg.anthropic_api_key:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)
        return self._client

    # ── Screenshot capture ────────────────────────────────────

    async def screenshot(
        self,
        region: tuple[int, int, int, int] | None = None,
        save: bool = True,
    ) -> ScreenState:
        """
        Capture the screen (or a region) and return a ScreenState.

        Args:
            region: (left, top, right, bottom) pixel coords. None = full screen.
            save: save PNG to disk
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._capture, region, save)

    def _capture(self, region, save: bool) -> ScreenState:
        try:
            import pyautogui
            from PIL import Image

            img: Image.Image = pyautogui.screenshot(region=region)
            w, h = img.size

            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            b64 = base64.b64encode(buf.read()).decode()

            file_path = ""
            if save:
                ts = time.strftime("%Y%m%d_%H%M%S")
                p = SCREENSHOT_DIR / f"screen_{ts}.png"
                img.save(str(p))
                file_path = str(p)

            return ScreenState(image_b64=b64, width=w, height=h, file_path=file_path)
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            raise

    async def screenshot_window(self, window_title: str) -> ScreenState:
        """Try to screenshot a specific window (Windows only)."""
        loop = asyncio.get_event_loop()

        def _do():
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(window_title)
                if not wins:
                    raise ValueError(f"Window '{window_title}' not found")
                w = wins[0]
                region = (w.left, w.top, w.left + w.width, w.top + w.height)
                return self._capture(region, True)
            except Exception:
                return self._capture(None, True)  # fallback to full screen

        return await loop.run_in_executor(None, _do)

    # ── Vision analysis via Claude ────────────────────────────

    async def analyse(
        self,
        state: ScreenState,
        task_context: str = "",
    ) -> VisionAnalysis:
        """
        Send a screenshot to Claude vision and get structured analysis.

        Args:
            state: captured ScreenState
            task_context: what Javris is trying to do (helps Claude focus)
        """
        client = self._get_client()
        if not client:
            return self._empty_analysis("No Claude API key configured")

        prompt = self._build_analysis_prompt(task_context)

        try:
            response = await client.messages.create(
                model=cfg.javris_claude_model,
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": state.image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            raw = response.content[0].text
            return self._parse_analysis(raw)
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return self._empty_analysis(str(e))

    def _build_analysis_prompt(self, task_context: str) -> str:
        ctx = f"\nCurrent task: {task_context}" if task_context else ""
        return f"""Analyse this screenshot carefully.{ctx}

Return a JSON object with this exact structure:
{{
  "description": "one sentence describing what's on screen",
  "page_title": "detected page/tab title",
  "page_type": "quiz|assignment|form|dashboard|login|video|article|other",
  "current_state": "describe current state in detail e.g. 'Question 3 of 10 showing multiple choice'",
  "raw_text": "all readable text visible on screen, comma separated",
  "suggested_action": "what should be done next to complete the task",
  "questions": [
    {{
      "question_text": "full question text",
      "question_type": "multiple_choice|true_false|fill_blank|essay|matching",
      "options": ["option A text", "option B text", "option C text", "option D text"],
      "correct_answer_index": null,
      "answer_text": null
    }}
  ],
  "elements": [
    {{
      "description": "descriptive name",
      "element_type": "button|input|checkbox|radio|link|dropdown|textarea",
      "location": "describe screen position",
      "text_content": "visible text",
      "x_percent": 50,
      "y_percent": 50
    }}
  ]
}}

x_percent and y_percent are 0-100 percentage of screen width/height.
Return ONLY the JSON, nothing else."""

    def _parse_analysis(self, raw: str) -> VisionAnalysis:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not match:
                raise ValueError("No JSON found")
            data = json.loads(match.group())
        except Exception as e:
            logger.warning(f"Analysis parse failed: {e}")
            return self._empty_analysis(raw[:200])

        elements = []
        for e in data.get("elements", []):
            elements.append(UIElement(
                description=e.get("description", ""),
                element_type=e.get("element_type", "unknown"),
                location=e.get("location", ""),
                x=int(e.get("x_percent", 50)),
                y=int(e.get("y_percent", 50)),
                text_content=e.get("text_content", ""),
            ))

        return VisionAnalysis(
            description=data.get("description", ""),
            page_title=data.get("page_title", ""),
            page_type=data.get("page_type", "other"),
            elements=elements,
            questions=data.get("questions", []),
            current_state=data.get("current_state", ""),
            suggested_action=data.get("suggested_action", ""),
            raw_text=data.get("raw_text", ""),
        )

    @staticmethod
    def _empty_analysis(reason: str) -> VisionAnalysis:
        return VisionAnalysis(
            description=reason,
            page_title="",
            page_type="other",
            elements=[],
            questions=[],
            current_state="unknown",
            suggested_action="take screenshot and retry",
            raw_text="",
        )

    # ── Diff detection ────────────────────────────────────────

    async def has_changed(
        self,
        before: ScreenState,
        after: ScreenState,
        threshold: float = 0.02,
    ) -> bool:
        """Returns True if screen changed significantly between two states."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._diff, before, after, threshold)

    @staticmethod
    def _diff(before: ScreenState, after: ScreenState, threshold: float) -> bool:
        try:
            import numpy as np
            from PIL import Image

            def decode(b64: str):
                return Image.open(io.BytesIO(base64.b64decode(b64))).convert("L")

            img1 = np.array(decode(before.image_b64)).astype(float)
            img2 = np.array(decode(after.image_b64)).astype(float)

            if img1.shape != img2.shape:
                return True

            diff = np.abs(img1 - img2).mean() / 255.0
            return diff > threshold
        except Exception:
            return True  # assume changed if we can't tell

    # ── Quick text read ───────────────────────────────────────

    async def read_screen_text(self, region=None) -> str:
        """Quick read — screenshot + ask Claude just for the text."""
        state = await self.screenshot(region=region, save=False)
        client = self._get_client()
        if not client:
            return ""
        try:
            resp = await client.messages.create(
                model=cfg.javris_claude_model,
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": state.image_b64,
                            },
                        },
                        {"type": "text", "text": "Extract all readable text from this screenshot. Return only the text, no commentary."},
                    ],
                }],
            )
            return resp.content[0].text
        except Exception as e:
            logger.warning(f"read_screen_text failed: {e}")
            return ""

    # ── Answer a question using Claude knowledge ──────────────

    async def answer_question(self, question: dict, context: str = "") -> dict:
        """
        Given a parsed question dict from vision analysis, return the answer.

        Args:
            question: {"question_text": ..., "question_type": ..., "options": [...]}
            context: subject/topic context

        Returns:
            {"answer_index": int, "answer_text": str, "explanation": str}
        """
        client = self._get_client()
        if not client:
            return {"answer_index": 0, "answer_text": "", "explanation": "No client"}

        q_type = question.get("question_type", "multiple_choice")
        q_text = question.get("question_text", "")
        options = question.get("options", [])

        if q_type in ("multiple_choice", "true_false") and options:
            opts_str = "\n".join(f"{i}. {o}" for i, o in enumerate(options))
            prompt = f"""Answer this question correctly.
Context: {context}

Question: {q_text}

Options:
{opts_str}

Reply with ONLY a JSON object:
{{"answer_index": <0-based index of correct option>, "answer_text": "<exact option text>", "explanation": "<brief why>"}}"""
        elif q_type == "fill_blank":
            prompt = f"""Complete this correctly.
Context: {context}
Question: {q_text}
Reply: {{"answer_text": "<answer>", "explanation": "<brief why>", "answer_index": -1}}"""
        else:
            prompt = f"""Answer this question with a well-structured response.
Context: {context}
Question: {q_text}
Reply: {{"answer_text": "<detailed answer>", "explanation": "", "answer_index": -1}}"""

        try:
            resp = await client.messages.create(
                model=cfg.javris_claude_model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            import json, re
            text = resp.content[0].text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.warning(f"answer_question failed: {e}")

        return {"answer_index": 0, "answer_text": options[0] if options else "", "explanation": ""}
