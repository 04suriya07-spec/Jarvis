"""
Javris Browser Agent
─────────────────────
Full browser automation powered by Playwright.

TWO modes:
  1. LIVE MODE   — connect to YOUR existing Chrome via CDP
                   (user sees everything, cookies/logins preserved)
  2. HIDDEN MODE — launch a new headless browser for background tasks

Capabilities:
  • Navigate to URLs
  • Click any element (by selector, text, or vision coordinates)
  • Type text into fields
  • Select dropdown options
  • Check/uncheck checkboxes and radio buttons
  • Submit forms
  • Scroll pages
  • Wait for content to load
  • Extract page text and HTML
  • Take screenshots of page or specific elements
  • Handle popups and modals
  • Execute custom JavaScript

To connect to your live Chrome:
  Launch Chrome with: --remote-debugging-port=9222
  Or use the setup script to add this flag automatically.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.logger import get_logger
from core.config import get_config

logger = get_logger("javris.browser_agent")
cfg = get_config()

CDP_URL = "http://localhost:9222"   # default Chrome debug port


@dataclass
class ActionResult:
    success: bool
    action: str
    detail: str = ""
    screenshot_b64: str = ""
    page_text: str = ""
    error: str = ""


class BrowserAgent:
    """
    Playwright-based browser controller.
    Connects to your live Chrome or launches a new one.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None
        self._connected = False
        self._mode = "none"   # "live" | "hidden" | "none"
        self._action_log: list[dict] = []

    # ── Connection ────────────────────────────────────────────

    async def connect_to_live_chrome(self, cdp_url: str = CDP_URL) -> bool:
        """
        Connect to the user's already-running Chrome browser.
        Chrome must be started with --remote-debugging-port=9222.
        """
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
            contexts = self._browser.contexts
            if not contexts:
                raise RuntimeError("No browser contexts found")
            pages = contexts[0].pages
            self._page = pages[0] if pages else await contexts[0].new_page()
            self._connected = True
            self._mode = "live"
            logger.info(f"Connected to live Chrome | URL: {self._page.url}")
            return True
        except Exception as e:
            logger.warning(f"Live Chrome connect failed: {e}")
            return False

    async def launch_browser(self, headless: bool = False) -> bool:
        """Launch a new browser window (visible or hidden)."""
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--start-maximized",
                ],
            )
            context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self._page = await context.new_page()
            self._connected = True
            self._mode = "hidden" if headless else "visible"
            logger.info(f"Browser launched | mode={'headless' if headless else 'visible'}")
            return True
        except Exception as e:
            logger.error(f"Browser launch failed: {e}")
            return False

    async def disconnect(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._connected = False
        self._mode = "none"

    @property
    def connected(self) -> bool:
        return self._connected and self._page is not None

    @property
    def current_url(self) -> str:
        try:
            return self._page.url if self._page else ""
        except Exception:
            return ""

    # ── Navigation ────────────────────────────────────────────

    async def goto(self, url: str, wait_until: str = "networkidle") -> ActionResult:
        try:
            await self._page.goto(url, wait_until=wait_until, timeout=30000)
            await asyncio.sleep(1)
            return ActionResult(success=True, action="goto", detail=f"Navigated to {url}")
        except Exception as e:
            return ActionResult(success=False, action="goto", error=str(e))

    async def go_back(self) -> ActionResult:
        try:
            await self._page.go_back(wait_until="networkidle", timeout=15000)
            return ActionResult(success=True, action="go_back")
        except Exception as e:
            return ActionResult(success=False, action="go_back", error=str(e))

    async def reload(self) -> ActionResult:
        try:
            await self._page.reload(wait_until="networkidle", timeout=15000)
            return ActionResult(success=True, action="reload")
        except Exception as e:
            return ActionResult(success=False, action="reload", error=str(e))

    # ── Interaction ───────────────────────────────────────────

    async def click(
        self,
        selector: str = "",
        text: str = "",
        x_percent: float = 0,
        y_percent: float = 0,
        delay_ms: int = 50,
    ) -> ActionResult:
        """Click an element by CSS selector, text content, or screen coordinates."""
        try:
            if selector:
                await self._page.click(selector, delay=delay_ms, timeout=10000)
                detail = f"Clicked [{selector}]"
            elif text:
                # Try text selector
                el = self._page.get_by_text(text, exact=False).first
                await el.click(delay=delay_ms, timeout=10000)
                detail = f"Clicked text '{text}'"
            elif x_percent or y_percent:
                vp = self._page.viewport_size or {"width": 1280, "height": 800}
                x = int(x_percent / 100 * vp["width"])
                y = int(y_percent / 100 * vp["height"])
                await self._page.mouse.click(x, y, delay=delay_ms)
                detail = f"Clicked at ({x}, {y})"
            else:
                return ActionResult(success=False, action="click", error="No target specified")

            await asyncio.sleep(0.3)
            self._log("click", detail)
            return ActionResult(success=True, action="click", detail=detail)
        except Exception as e:
            return ActionResult(success=False, action="click", error=str(e))

    async def type_text(
        self,
        selector: str = "",
        text: str = "",
        clear_first: bool = True,
        delay_ms: int = 30,
    ) -> ActionResult:
        """Type text into an input field."""
        try:
            if selector:
                el = self._page.locator(selector).first
            else:
                el = self._page.locator("input:visible, textarea:visible").first

            if clear_first:
                await el.triple_click()
                await el.press("Control+a")
                await el.press("Delete")

            await el.type(text, delay=delay_ms)
            detail = f"Typed '{text[:40]}{'…' if len(text) > 40 else ''}' into {selector or 'focused field'}"
            self._log("type", detail)
            return ActionResult(success=True, action="type", detail=detail)
        except Exception as e:
            return ActionResult(success=False, action="type", error=str(e))

    async def select_option(self, selector: str, value: str = "", label: str = "") -> ActionResult:
        """Select a dropdown option."""
        try:
            if label:
                await self._page.select_option(selector, label=label)
            else:
                await self._page.select_option(selector, value=value)
            detail = f"Selected '{label or value}' in {selector}"
            self._log("select", detail)
            return ActionResult(success=True, action="select", detail=detail)
        except Exception as e:
            return ActionResult(success=False, action="select", error=str(e))

    async def check(self, selector: str, state: bool = True) -> ActionResult:
        """Check or uncheck a checkbox/radio button."""
        try:
            if state:
                await self._page.check(selector, timeout=5000)
            else:
                await self._page.uncheck(selector, timeout=5000)
            detail = f"{'Checked' if state else 'Unchecked'} {selector}"
            self._log("check", detail)
            return ActionResult(success=True, action="check", detail=detail)
        except Exception as e:
            return ActionResult(success=False, action="check", error=str(e))

    async def press_key(self, key: str) -> ActionResult:
        """Press a keyboard key (Enter, Tab, Escape, ArrowDown, etc.)."""
        try:
            await self._page.keyboard.press(key)
            return ActionResult(success=True, action="key", detail=f"Pressed {key}")
        except Exception as e:
            return ActionResult(success=False, action="key", error=str(e))

    async def scroll(self, direction: str = "down", amount: int = 300) -> ActionResult:
        """Scroll the page."""
        try:
            delta = amount if direction == "down" else -amount
            await self._page.mouse.wheel(0, delta)
            await asyncio.sleep(0.2)
            return ActionResult(success=True, action="scroll", detail=f"Scrolled {direction} {amount}px")
        except Exception as e:
            return ActionResult(success=False, action="scroll", error=str(e))

    async def hover(self, selector: str) -> ActionResult:
        try:
            await self._page.hover(selector, timeout=5000)
            return ActionResult(success=True, action="hover", detail=f"Hovered {selector}")
        except Exception as e:
            return ActionResult(success=False, action="hover", error=str(e))

    async def submit_form(self, selector: str = "") -> ActionResult:
        """Submit a form (optionally specify the form selector)."""
        try:
            if selector:
                await self._page.eval_on_selector(selector, "el => el.submit()")
            else:
                await self._page.keyboard.press("Enter")
            await asyncio.sleep(1)
            return ActionResult(success=True, action="submit", detail="Form submitted")
        except Exception as e:
            return ActionResult(success=False, action="submit", error=str(e))

    # ── Waiting ───────────────────────────────────────────────

    async def wait_for_text(self, text: str, timeout: int = 10000) -> bool:
        try:
            await self._page.wait_for_selector(f"text={text}", timeout=timeout)
            return True
        except Exception:
            return False

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> bool:
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def wait_for_load(self, timeout: int = 10000) -> None:
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            await asyncio.sleep(2)

    async def wait_seconds(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    # ── Reading / Extraction ──────────────────────────────────

    async def get_page_text(self) -> str:
        try:
            return await self._page.inner_text("body")
        except Exception:
            return ""

    async def get_page_title(self) -> str:
        try:
            return await self._page.title()
        except Exception:
            return ""

    async def get_element_text(self, selector: str) -> str:
        try:
            return await self._page.inner_text(selector)
        except Exception:
            return ""

    async def find_elements(self, selector: str) -> list[dict]:
        """Find all matching elements and return their text + attributes."""
        try:
            els = await self._page.query_selector_all(selector)
            results = []
            for el in els[:20]:
                text = await el.inner_text()
                tag = await el.evaluate("e => e.tagName")
                results.append({"text": text.strip(), "tag": tag.lower()})
            return results
        except Exception:
            return []

    async def execute_js(self, script: str) -> Any:
        """Execute arbitrary JavaScript on the page."""
        try:
            return await self._page.evaluate(script)
        except Exception as e:
            return {"error": str(e)}

    # ── Screenshot ────────────────────────────────────────────

    async def page_screenshot(self) -> str:
        """Take a screenshot of the current page. Returns base64 PNG."""
        try:
            import base64
            buf = await self._page.screenshot(type="png", full_page=False)
            return base64.b64encode(buf).decode()
        except Exception as e:
            logger.warning(f"Page screenshot failed: {e}")
            return ""

    # ── Smart element finders ─────────────────────────────────

    async def find_button(self, text: str) -> str | None:
        """Return selector for a button containing the given text."""
        candidates = [
            f"button:has-text('{text}')",
            f"input[type='submit'][value='{text}']",
            f"a:has-text('{text}')",
            f"[role='button']:has-text('{text}')",
        ]
        for sel in candidates:
            try:
                el = self._page.locator(sel).first
                if await el.is_visible():
                    return sel
            except Exception:
                continue
        return None

    async def find_radio_for_option(self, option_text: str) -> str | None:
        """Find the radio button associated with a given answer text."""
        try:
            # Try finding label containing the text, then get its radio
            label = self._page.get_by_text(option_text, exact=False).first
            if await label.is_visible():
                # Click the label directly (usually works for radio buttons)
                return None  # Caller should click by text
        except Exception:
            pass
        return None

    async def click_radio_by_text(self, option_text: str) -> ActionResult:
        """Click a radio button by its associated label text."""
        try:
            # Strategy 1: click the label text
            el = self._page.get_by_text(option_text, exact=False).first
            await el.click()
            return ActionResult(success=True, action="click_radio", detail=f"Selected '{option_text}'")
        except Exception:
            pass

        try:
            # Strategy 2: find input near the text
            el = self._page.locator(f"label:has-text('{option_text}') input[type='radio']").first
            await el.check()
            return ActionResult(success=True, action="click_radio", detail=f"Checked radio '{option_text}'")
        except Exception as e:
            return ActionResult(success=False, action="click_radio", error=str(e))

    # ── Logging ───────────────────────────────────────────────

    def _log(self, action: str, detail: str) -> None:
        self._action_log.append({
            "action": action,
            "detail": detail,
            "url": self.current_url,
            "timestamp": time.time(),
        })
        if len(self._action_log) > 200:
            self._action_log = self._action_log[-200:]

    def get_action_log(self) -> list[dict]:
        return list(self._action_log)

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "connected": self.connected,
            "mode": self._mode,
            "url": self.current_url,
            "actions_taken": len(self._action_log),
        }
