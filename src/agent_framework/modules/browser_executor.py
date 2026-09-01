"""
Module 5 — Browser Executor (Optimized)
=========================================
Executes browser actions using Playwright (async Chromium).

Optimizations over original:
- Batch execution: execute multiple actions without LLM between them
- Selector caching: memoize successful CSS selectors
- Smart waits: use wait_for_selector / wait_for_load_state instead of sleep
- Checkpoint-only screenshots: only capture at validation points
- Multi-strategy element resolution with priority fallback

Pipeline position: ActionObject[] -> raw page state (dict)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

from ..config import AgentConfig, default_config
from ..models import ActionObject

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class BrowserBlockedError(Exception):
    """Raised when navigation is blocked by safety guardrails."""


class BrowserExecutor:
    """
    Module 5: Manages Playwright browser lifecycle and executes ActionObjects.

    Usage (async context manager):
        async with BrowserExecutor(config) as executor:
            raw_state = await executor.execute(action, run_id, step_index)
            # Or batch execute:
            results = await executor.execute_batch(actions, run_id, start_step)
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        # Selector cache: description → CSS selector
        self._selector_cache: dict[str, str] = {}

    # ── Lifecycle ─────────────────────────────────────────────────

    async def __aenter__(self) -> "BrowserExecutor":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()

    async def start(self) -> None:
        """Launch Playwright browser and create a stealth context with background execution flags."""
        self._playwright = await async_playwright().start()
        b_type = (self.config.browser_type or "chromium").lower()
        launch_kwargs = {
            "headless": self.config.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=CalculateNativeWinOcclusion",
                "--disable-ipc-flooding-protection",
            ],
        }

        self._browser = await self._launch_browser_resiliently(b_type, launch_kwargs)
        self._context = await self._browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )
        self._page = await self._context.new_page()
        logger.info(f"[M5] Browser started ({b_type}, headless={self.config.headless})")

    async def _launch_browser_resiliently(self, b_type: str, launch_kwargs: dict):
        """
        Resilient browser launcher with cascading fallbacks:
        1. Requested browser / channel
        2. System Edge (channel='msedge')
        3. System Chrome (channel='chrome')
        4. Playwright bundled Chromium
        5. Programmatic auto-install of Chromium if all missing
        """
        # Strategy sequence
        launch_attempts = []

        if b_type in ("msedge", "edge"):
            launch_attempts.append(("chromium (msedge)", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs)))
            launch_attempts.append(("chromium (bundled)", lambda: self._playwright.chromium.launch(**launch_kwargs)))
            launch_attempts.append(("chromium (chrome)", lambda: self._playwright.chromium.launch(channel="chrome", **launch_kwargs)))
        elif b_type in ("chrome", "google-chrome"):
            launch_attempts.append(("chromium (chrome)", lambda: self._playwright.chromium.launch(channel="chrome", **launch_kwargs)))
            launch_attempts.append(("chromium (msedge)", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs)))
            launch_attempts.append(("chromium (bundled)", lambda: self._playwright.chromium.launch(**launch_kwargs)))
        elif b_type in ("firefox", "webkit"):
            launcher = getattr(self._playwright, b_type)
            launch_attempts.append((b_type, lambda: launcher.launch(**launch_kwargs)))
            launch_attempts.append(("chromium (msedge)", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs)))
            launch_attempts.append(("chromium (bundled)", lambda: self._playwright.chromium.launch(**launch_kwargs)))
        else:
            # Default chromium
            launch_attempts.append(("chromium (bundled)", lambda: self._playwright.chromium.launch(**launch_kwargs)))
            launch_attempts.append(("chromium (msedge)", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs)))
            launch_attempts.append(("chromium (chrome)", lambda: self._playwright.chromium.launch(channel="chrome", **launch_kwargs)))

        last_error = None
        for name, launcher_fn in launch_attempts:
            try:
                browser = await launcher_fn()
                logger.info(f"[M5] Browser successfully launched using {name}")
                return browser
            except Exception as exc:
                last_error = exc
                logger.warning(f"[M5] Launch attempt with {name} failed: {exc}. Trying fallback...")

        # If all failed, attempt auto-install and retry
        logger.info("[M5] Missing browser binaries detected. Auto-installing Playwright Chromium...")
        try:
            import subprocess
            proc = await asyncio.to_thread(
                lambda: subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            )
            logger.info(f"[M5] Playwright auto-install finished (code {proc.returncode}). Retrying launch...")
            return await self._playwright.chromium.launch(**launch_kwargs)
        except Exception as install_err:
            raise RuntimeError(
                f"Failed to launch any browser. Auto-install failed: {install_err}. "
                f"Original error: {last_error}"
            ) from last_error

    async def stop(self) -> None:
        """Close browser and Playwright cleanly."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("[M5] Browser stopped.")

    # ── Single Action Execution ───────────────────────────────────

    async def execute(
        self,
        action: ActionObject,
        run_id: str = "dev",
        step_index: int = 0,
        screenshot: bool = True,
    ) -> dict[str, Any]:
        """
        Execute a single ActionObject and return raw page state.

        Args:
            action: The action to perform.
            run_id: Current run ID (for screenshot paths).
            step_index: Step number (for screenshot naming).
            screenshot: Whether to capture a screenshot after action.

        Returns:
            dict with keys: url, title, accessibility_tree, screenshot_path, duration_ms
        """
        if not self._page:
            raise RuntimeError("BrowserExecutor not started. Use async context manager.")

        # Safety check
        if action.action == "navigate" and action.value:
            self._check_blocklist(action.value)

        # Micro-delay for event loop yield
        await asyncio.sleep(0.02)

        start_ms = int(time.time() * 1000)
        timeout = action.timeout_ms or self.config.action_timeout_ms
        success = True

        try:
            await self._dispatch(action, timeout)
            # Smart wait: wait for DOM ready instead of fixed sleep
            await self._smart_wait(action)
        except Exception as e:
            logger.warning(f"[M5] Action failed: {action.action} → {e}")
            success = False

        duration_ms = int(time.time() * 1000) - start_ms

        # Capture page state
        raw_state = await self._capture_state(run_id, step_index, screenshot)
        raw_state["duration_ms"] = duration_ms
        raw_state["action_success"] = success
        return raw_state

    # ── Batch Execution (Plan-then-Execute) ───────────────────────

    async def execute_batch(
        self,
        actions: list[ActionObject],
        run_id: str = "dev",
        start_step: int = 0,
        checkpoint_indices: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute multiple actions in batch without LLM between them.

        Only captures full state at checkpoint indices.
        Returns a list of result dicts for each action.

        Args:
            actions: List of ActionObjects to execute sequentially.
            run_id: Current run ID.
            start_step: Starting step index for naming.
            checkpoint_indices: Step indices where full state capture is needed.

        Returns:
            List of raw state dicts, one per action.
        """
        if not self._page:
            raise RuntimeError("BrowserExecutor not started.")

        checkpoints = set(checkpoint_indices or [])
        results = []

        for i, action in enumerate(actions):
            step_idx = start_step + i
            is_checkpoint = i in checkpoints

            # Only take screenshot at checkpoints
            take_screenshot = is_checkpoint and not self.config.screenshots_at_checkpoints_only
            if is_checkpoint:
                take_screenshot = True

            result = await self.execute(
                action,
                run_id=run_id,
                step_index=step_idx,
                screenshot=take_screenshot if is_checkpoint else False,
            )
            results.append(result)

            # If action failed at a checkpoint, stop batch
            if not result.get("action_success", True) and is_checkpoint:
                logger.warning(f"[M5] Batch stopped at step {step_idx}: action failed at checkpoint")
                break

        return results

    # ── Action Dispatch ───────────────────────────────────────────

    async def _dispatch(self, action: ActionObject, timeout: int) -> None:
        """Route action to the correct Playwright method."""
        page = self._page
        act = action.action.lower()

        if act == "click":
            el = await self._resolve_element(action.selector, timeout)
            if el:
                await el.click(timeout=timeout)
            else:
                logger.warning(f"[M5] Click target not found: {action.selector}")

        elif act in ("type", "fill"):
            el = await self._resolve_element(action.selector, timeout)
            if el:
                await el.fill(action.value or "", timeout=timeout)
                # Don't auto-press Enter for fill actions
                if act == "type":
                    await el.press("Enter")
            else:
                logger.warning(f"[M5] Type target not found: {action.selector}")

        elif act == "navigate":
            url = action.value or ""
            if not url.startswith("http"):
                url = "https://" + url
            await page.goto(url, timeout=self.config.page_load_timeout_ms)

        elif act == "scroll":
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")

        elif act == "extract":
            # Extract is a logical action; no browser interaction needed
            pass

        elif act == "wait":
            await asyncio.sleep(1.0)

        else:
            logger.warning(f"[M5] Unknown action type: {act}")

    async def _smart_wait(self, action: ActionObject) -> None:
        """Use browser-native waits instead of fixed sleeps."""
        try:
            if action.action in ("navigate", "click"):
                await self._page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=min(self.config.page_load_timeout_ms, 3000),
                )
            elif action.action in ("type", "fill"):
                # Brief wait for any AJAX response
                await asyncio.sleep(0.3)
        except Exception:
            pass  # Timeout is acceptable, page may already be ready

    # ── Element Resolution (Multi-strategy with caching) ──────────

    async def _resolve_element(self, selector: str | None, timeout: int):
        """
        Resolve an element using multiple strategies with caching.

        Priority:
        1. Cached CSS selector (from previous successful resolution)
        2. Direct CSS selector
        3. aria-label match
        4. Text content match
        5. Placeholder match
        6. Role + name via get_by_role
        """
        if not selector:
            return None
        page = self._page

        # 1. Check cache first
        if selector in self._selector_cache:
            cached = self._selector_cache[selector]
            try:
                el = page.locator(cached).first
                await el.wait_for(state="visible", timeout=min(timeout, 2000))
                return el
            except Exception:
                # Cache miss — selector changed, remove it
                del self._selector_cache[selector]

        # 2. Try as direct CSS selector
        try:
            el = page.locator(selector).first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            self._selector_cache[selector] = selector
            return el
        except Exception:
            pass

        # 3. Try aria-label
        try:
            el = page.locator(f'[aria-label*="{selector}" i]').first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            self._selector_cache[selector] = f'[aria-label*="{selector}" i]'
            return el
        except Exception:
            pass

        # 4. Try placeholder
        try:
            el = page.locator(f'[placeholder*="{selector}" i]').first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            self._selector_cache[selector] = f'[placeholder*="{selector}" i]'
            return el
        except Exception:
            pass

        # 5. Try text match
        try:
            el = page.get_by_text(selector, exact=False).first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            return el
        except Exception:
            pass

        # 6. Try role-based matching for common roles
        for role in ("button", "link", "textbox", "searchbox", "combobox"):
            try:
                el = page.get_by_role(role, name=selector).first
                await el.wait_for(state="visible", timeout=min(timeout, 1500))
                return el
            except Exception:
                continue

        logger.warning(f"[M5] Element not found after all strategies: {selector}")
        return None

    # ── State Capture ─────────────────────────────────────────────

    async def _capture_state(
        self, run_id: str, step_index: int, take_screenshot: bool
    ) -> dict[str, Any]:
        """Capture current page accessibility tree and optional screenshot."""
        page = self._page

        url = page.url
        title = await page.title()

        # Accessibility tree
        try:
            acc_tree = await page.accessibility.snapshot()
        except Exception:
            acc_tree = {}

        # Screenshot
        screenshot_path = None
        if take_screenshot:
            screenshot_path = await self._save_screenshot(run_id, step_index)

        return {
            "url": url,
            "title": title,
            "accessibility_tree": acc_tree or {},
            "screenshot_path": screenshot_path,
        }

    async def _save_screenshot(self, run_id: str, step_index: int) -> str:
        """Save a screenshot to logs/runs/{run_id}/step_{n}.png."""
        run_dir = Path(self.config.log_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = str(run_dir / f"step_{step_index:03d}.png")
        await self._page.screenshot(path=path, full_page=False)
        logger.debug(f"[M5] Screenshot saved: {path}")
        return path

    def _check_blocklist(self, url: str) -> None:
        """Raise BrowserBlockedError if URL matches any blocklist pattern."""
        url_lower = url.lower()
        for pattern in self.config.block_purchase_urls:
            if pattern.lower() in url_lower:
                raise BrowserBlockedError(
                    f"Navigation blocked: URL '{url}' matches blocked pattern '{pattern}'"
                )

    def clear_selector_cache(self) -> None:
        """Clear the selector cache (e.g., when navigating to a new site)."""
        self._selector_cache.clear()
