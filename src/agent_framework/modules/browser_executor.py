"""
Module 5 — Browser Executor (Optimized & Resilient)
===================================================
Executes browser actions using Playwright (async Chromium/Chrome/Edge/WebKit/Firefox)
or optional Chrome DevTools Protocol (CDP) connection.

Optimizations & Capabilities:
- Explicit, reliable context manager lifecycle (__aenter__ / __aexit__)
- Multi-tier cascading fallback launcher (Requested -> Edge -> Chrome -> Bundled Chromium)
- Optional CDP support (connect to existing browser on --remote-debugging-port)
- In-flight health checks and automatic page/context self-recovery
- Multi-strategy element resolution (cached CSS -> CSS -> aria-label -> placeholder -> text -> role)
- Smart waits (wait_for_load_state / DOMContentLoaded) instead of fixed sleeps
- Safe URL normalization & purchase blocklist enforcement
- Comprehensive runtime diagnostics and actionable error messages

Pipeline position: ActionObject[] -> raw page state (dict)
"""

from __future__ import annotations

import asyncio
import inspect
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


# ── Exceptions ───────────────────────────────────────────────────────────────

class BrowserError(Exception):
    """Base exception for all browser executor errors."""


class BrowserBlockedError(BrowserError):
    """Raised when navigation is blocked by safety guardrails."""


class BrowserNotStartedError(BrowserError):
    """Raised when an operation is attempted on an uninitialized browser."""


class BrowserStartupError(BrowserError):
    """Raised when browser initialization fails with rich diagnostic details."""

    def __init__(
        self,
        message: str,
        diagnostics: dict[str, Any] | None = None,
        suggested_fix: str | None = None,
    ):
        super().__init__(message)
        self.diagnostics = diagnostics or {}
        self.suggested_fix = (
            suggested_fix
            or "Run 'python -m playwright install chromium' or ensure a supported browser is installed."
        )


# ── BrowserExecutor ──────────────────────────────────────────────────────────

class BrowserExecutor:
    """
    Module 5: Manages Playwright browser lifecycle and executes ActionObjects.

    Usage (async context manager):
        async with BrowserExecutor(config) as browser:
            raw_state = await browser.execute(action, run_id, step_index)
            # Or batch execute:
            results = await browser.execute_batch(actions, run_id, start_step)
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._is_started = False
        self._is_cdp = False
        # Selector cache: description → CSS selector
        self._selector_cache: dict[str, str] = {}
        self._last_extracted_items: list[dict[str, Any]] = []

    # ── Diagnostics ───────────────────────────────────────────────────────────

    @classmethod
    def get_diagnostics(cls, config: AgentConfig | None = None) -> dict[str, Any]:
        """
        Inspect the execution environment, module import origins, and Playwright status.
        Helpful for troubleshooting stale packages, wrong venvs, or missing binaries.
        """
        cfg = config or default_config
        try:
            framework_path = inspect.getfile(cls)
        except Exception:
            framework_path = __file__

        is_local_src = "site-packages" not in framework_path.replace("\\", "/")

        pw_available = async_playwright is not None
        pw_version = None
        pw_module_path = None
        if pw_available:
            try:
                import importlib.metadata
                pw_version = importlib.metadata.version("playwright")
            except Exception:
                pw_version = "installed"
            try:
                import playwright
                pw_module_path = inspect.getfile(playwright)
            except Exception:
                pw_module_path = "unknown"

        return {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "agent_framework_path": framework_path,
            "is_local_src": is_local_src,
            "playwright_available": pw_available,
            "playwright_version": pw_version,
            "playwright_module_path": pw_module_path,
            "browser_type": cfg.browser_type,
            "browser_connection_mode": getattr(cfg, "browser_connection_mode", "playwright"),
            "headless": cfg.headless,
            "cdp_endpoint": getattr(cfg, "cdp_endpoint", "http://127.0.0.1:9222"),
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "BrowserExecutor":
        try:
            await self.start()
            return self
        except Exception:
            await self.stop()
            raise

    async def __aexit__(self, *_) -> None:
        await self.stop()

    async def start(self) -> None:
        """
        Initialize Playwright -> Browser -> Context -> Page (or connect via CDP).
        Guarantees that all required browser resources are initialized or raises BrowserStartupError.
        """
        if self._is_started and self._page and not self._page.is_closed():
            logger.debug("[M5] BrowserExecutor already running and healthy.")
            return

        if async_playwright is None:
            diag = self.get_diagnostics(self.config)
            raise BrowserStartupError(
                "Playwright is not installed in the active Python environment.",
                diagnostics=diag,
                suggested_fix="Install Playwright with: pip install playwright && python -m playwright install chromium",
            )

        connection_mode = (
            getattr(self.config, "browser_connection_mode", "playwright") or "playwright"
        ).lower()

        try:
            self._playwright = await async_playwright().start()

            if connection_mode == "cdp":
                await self._start_cdp()
            else:
                await self._start_playwright()

            self._is_started = True
            logger.info(
                f"[M5] BrowserExecutor ready (mode={connection_mode}, type={self.config.browser_type}, headless={self.config.headless})"
            )
        except BrowserStartupError:
            await self.stop()
            raise
        except Exception as exc:
            await self.stop()
            diag = self.get_diagnostics(self.config)
            diag["startup_error"] = str(exc)
            raise BrowserStartupError(
                f"Failed to start browser session: {exc}",
                diagnostics=diag,
                suggested_fix="Ensure browser binaries are installed via 'python -m playwright install chromium' or verify CDP endpoint.",
            ) from exc

    async def _start_cdp(self) -> None:
        """Connect to an existing Chrome/Chromium instance via Chrome DevTools Protocol."""
        endpoint = getattr(self.config, "cdp_endpoint", "http://127.0.0.1:9222")
        logger.info(f"[M5] Connecting to browser over CDP endpoint: {endpoint}")
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
            self._is_cdp = True

            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
            else:
                self._context = await self._browser.new_context(
                    viewport={"width": 1366, "height": 768},
                    locale="en-IN",
                )

            pages = self._context.pages
            if pages:
                self._page = pages[0]
            else:
                self._page = await self._context.new_page()

            logger.info(f"[M5] Successfully connected to CDP browser ({endpoint})")
        except Exception as exc:
            diag = self.get_diagnostics(self.config)
            diag["cdp_endpoint"] = endpoint
            raise BrowserStartupError(
                f"Could not connect to browser over CDP at {endpoint}. Ensure Chrome is running with '--remote-debugging-port=9222'.",
                diagnostics=diag,
                suggested_fix="Launch Chrome with: chrome.exe --remote-debugging-port=9222 --user-data-dir=\"<temp_dir>\"",
            ) from exc

    async def _start_playwright(self) -> None:
        """Launch a dedicated Playwright browser instance with cascading fallbacks."""
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

        self._is_cdp = False
        self._browser = await self._launch_browser_resiliently(b_type, launch_kwargs)
        self._context = await self._browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )
        self._page = await self._context.new_page()

    async def _launch_browser_resiliently(self, b_type: str, launch_kwargs: dict):
        """
        Resilient browser launcher with clean fallback cascade:
        1. Requested browser / channel
        2. System Edge (channel='msedge')
        3. System Chrome (channel='chrome')
        4. Playwright bundled Chromium
        """
        launch_attempts = []

        if b_type in ("msedge", "edge"):
            launch_attempts.append(
                ("System Edge (channel='msedge')", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs))
            )
            launch_attempts.append(
                ("Bundled Chromium", lambda: self._playwright.chromium.launch(**launch_kwargs))
            )
            launch_attempts.append(
                ("System Chrome (channel='chrome')", lambda: self._playwright.chromium.launch(channel="chrome", **launch_kwargs))
            )
        elif b_type in ("chrome", "google-chrome"):
            launch_attempts.append(
                ("System Chrome (channel='chrome')", lambda: self._playwright.chromium.launch(channel="chrome", **launch_kwargs))
            )
            launch_attempts.append(
                ("System Edge (channel='msedge')", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs))
            )
            launch_attempts.append(
                ("Bundled Chromium", lambda: self._playwright.chromium.launch(**launch_kwargs))
            )
        elif b_type in ("firefox", "webkit"):
            launcher = getattr(self._playwright, b_type, None)
            if launcher:
                launch_attempts.append(
                    (f"{b_type.capitalize()} (bundled)", lambda: launcher.launch(**launch_kwargs))
                )
            launch_attempts.append(
                ("System Edge (channel='msedge')", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs))
            )
            launch_attempts.append(
                ("Bundled Chromium", lambda: self._playwright.chromium.launch(**launch_kwargs))
            )
        else:
            # Default: chromium
            launch_attempts.append(
                ("Bundled Chromium", lambda: self._playwright.chromium.launch(**launch_kwargs))
            )
            launch_attempts.append(
                ("System Edge (channel='msedge')", lambda: self._playwright.chromium.launch(channel="msedge", **launch_kwargs))
            )
            launch_attempts.append(
                ("System Chrome (channel='chrome')", lambda: self._playwright.chromium.launch(channel="chrome", **launch_kwargs))
            )

        last_error = None
        attempted_names = []

        for name, launcher_fn in launch_attempts:
            attempted_names.append(name)
            try:
                browser = await launcher_fn()
                logger.info(f"[M5] Browser successfully launched using {name}")
                return browser
            except Exception as exc:
                last_error = exc
                logger.warning(f"[M5] Launch attempt with {name} failed: {exc}. Trying fallback...")

        # If all launch attempts failed, construct informative diagnostic exception
        diag = self.get_diagnostics(self.config)
        diag["attempted_launchers"] = attempted_names
        diag["last_error"] = str(last_error)

        raise BrowserStartupError(
            f"Failed to launch browser '{b_type}' after trying: {', '.join(attempted_names)}. "
            f"Original error: {last_error}",
            diagnostics=diag,
            suggested_fix="Install missing browser binaries using: python -m playwright install chromium",
        )

    async def stop(self) -> None:
        """Close browser, context, page, and Playwright cleanly without leaving dangling processes."""
        try:
            if self._page:
                if not self._page.is_closed():
                    await self._page.close()
        except Exception as e:
            logger.debug(f"[M5] Error closing page: {e}")
        finally:
            self._page = None

        try:
            if self._context:
                await self._context.close()
        except Exception as e:
            logger.debug(f"[M5] Error closing context: {e}")
        finally:
            self._context = None

        try:
            if self._browser:
                # In CDP mode, disconnecting is preferred over closing the external browser
                if not self._is_cdp and self._browser.is_connected():
                    await self._browser.close()
                elif self._is_cdp and self._browser.is_connected():
                    await self._browser.close()
        except Exception as e:
            logger.debug(f"[M5] Error closing browser: {e}")
        finally:
            self._browser = None

        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug(f"[M5] Error stopping playwright: {e}")
        finally:
            self._playwright = None
            self._is_started = False
            self._selector_cache.clear()

        logger.info("[M5] Browser stopped and resources released.")

    # ── Health Check & Recovery ───────────────────────────────────────────────

    async def _ensure_healthy(self) -> None:
        """
        Verify that browser, context, and page are alive and operational.
        Performs controlled recovery if context or page has closed unexpectedly.
        """
        if not self._is_started or not self._playwright or not self._browser:
            raise BrowserNotStartedError(
                "BrowserExecutor not started. Use 'async with BrowserExecutor(config) as browser:'"
            )

        # 1. Verify browser connection
        if not self._browser.is_connected():
            logger.warning("[M5] Browser connection lost. Re-establishing browser session...")
            await self.start()
            return

        # 2. Verify context
        if not self._context:
            logger.warning("[M5] Browser context missing. Recreating context...")
            self._context = await self._browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
            )

        # 3. Verify page & auto-select latest active tab
        if self._context and self._context.pages:
            # Switch to most recent non-closed tab
            valid_pages = [p for p in self._context.pages if not p.is_closed()]
            if valid_pages:
                self._page = valid_pages[-1]
            else:
                self._page = await self._context.new_page()
        elif not self._page or self._page.is_closed():
            logger.warning("[M5] Browser page was closed or missing. Creating a new page to recover session...")
            self._page = await self._context.new_page()

    # ── Single Action Execution ───────────────────────────────────────────────

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
            dict with keys: url, title, accessibility_tree, screenshot_path, duration_ms, action_success
        """
        await self._ensure_healthy()

        # Safety check: normalize and block forbidden purchase URLs
        if action.action == "navigate" and action.value:
            self._check_blocklist(action.value)

        # Micro-delay for event loop yield
        await asyncio.sleep(0.02)

        start_ms = int(time.time() * 1000)
        timeout = action.timeout_ms or self.config.action_timeout_ms
        success = True
        error_msg = None

        try:
            await self._dispatch(action, timeout)
            # Smart wait: wait for DOM ready instead of fixed sleep
            await self._smart_wait(action)
        except BrowserBlockedError:
            raise
        except Exception as e:
            logger.warning(f"[M5] Action execution failed: {action.action} (target={action.selector}) → {e}")
            success = False
            error_msg = str(e)

        duration_ms = int(time.time() * 1000) - start_ms

        # Capture page state safely
        raw_state = await self._capture_state(run_id, step_index, screenshot)
        raw_state["duration_ms"] = duration_ms
        raw_state["action_success"] = success
        if error_msg:
            raw_state["action_error"] = error_msg
        return raw_state

    # ── Batch Execution (Plan-then-Execute) ────────────────────────────────────

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
        await self._ensure_healthy()

        checkpoints = set(checkpoint_indices or [])
        results = []

        for i, action in enumerate(actions):
            step_idx = start_step + i
            is_checkpoint = i in checkpoints

            take_screenshot = is_checkpoint and self.config.screenshots_at_checkpoints_only
            if is_checkpoint:
                take_screenshot = True

            result = await self.execute(
                action,
                run_id=run_id,
                step_index=step_idx,
                screenshot=take_screenshot,
            )
            results.append(result)

            # If action failed at a checkpoint, halt batch to prevent cascading failures
            if not result.get("action_success", True) and is_checkpoint:
                logger.warning(f"[M5] Batch halted at step {step_idx}: action failed at checkpoint")
                break

        return results

    # ── Action Dispatch ───────────────────────────────────────────────────────

    async def _dispatch(self, action: ActionObject, timeout: int) -> None:
        """Route action to the correct Playwright method."""
        page = self._page
        act = (action.action or "").lower().strip()
        sel_lower = (action.selector or "").lower().strip()

        if act == "click":
            el = await self._resolve_element(action.selector, timeout)
            if el:
                await el.click(timeout=timeout)
            else:
                # Fallback specifically for search submit buttons if not found
                if any(k in sel_lower for k in ("search_button", "search_btn", "search submit", "submit search", "search-button")):
                    try:
                        logger.info("[M5] Search button not directly clickable, pressing Enter on active search input...")
                        await page.keyboard.press("Enter")
                        return
                    except Exception:
                        pass
                raise RuntimeError(
                    f"Target element for click not found matching selector/text '{action.selector}'"
                )

        elif act in ("type", "fill"):
            el = await self._resolve_element(action.selector, timeout)
            if el:
                await el.fill(action.value or "", timeout=timeout)
                # Auto-press Enter on search fields / queries to trigger instant website search
                if act == "type" or any(k in sel_lower for k in ("search", "query", "box", "input", "find")):
                    try:
                        await el.press("Enter")
                    except Exception:
                        pass
            else:
                raise RuntimeError(
                    f"Target element for {act} not found matching selector/text '{action.selector}'"
                )

        elif act == "navigate":
            url = (action.value or "").strip()
            if not url:
                raise ValueError("Navigate action requires a valid URL value.")
            if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
                url = "https://" + url
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_load_timeout_ms)
            except Exception as goto_err:
                logger.warning(f"[M5] Fast goto with domcontentloaded failed: {goto_err}. Retrying standard goto...")
                await page.goto(url, timeout=self.config.page_load_timeout_ms)

        elif act == "scroll":
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")

        elif act == "extract":
            # Live in-page structured product and link extraction
            extracted = await self._extract_page_products_or_items(action.selector, action.value)
            self._last_extracted_items = extracted
            action.value = str(extracted)

        elif act == "wait":
            wait_time = 1.0
            if action.value:
                try:
                    wait_time = float(action.value)
                except ValueError:
                    wait_time = 1.0
            await asyncio.sleep(min(wait_time, 5.0))

        elif act == "select":
            el = await self._resolve_element(action.selector, timeout)
            if el:
                try:
                    await el.select_option(label=action.value or "", timeout=timeout)
                except Exception:
                    # Fallback: try by value
                    try:
                        await el.select_option(value=action.value or "", timeout=timeout)
                    except Exception as e2:
                        logger.warning(f"[M5] Select option failed: {e2}")
            else:
                raise RuntimeError(
                    f"Target element for select not found: '{action.selector}'"
                )

        elif act == "press":
            key = (action.value or "Enter").strip()
            await page.keyboard.press(key)

        elif act == "dismiss_popup":
            await self._dismiss_popups()

        else:
            raise ValueError(f"Unknown action type: '{act}'")

    async def _smart_wait(self, action: ActionObject) -> None:
        """Use browser-native waits instead of fixed sleeps."""
        try:
            if not self._page or self._page.is_closed():
                return
            if action.action == "navigate":
                # Heavy pages (Amazon, Flipkart, MakeMyTrip) need networkidle
                try:
                    await self._page.wait_for_load_state(
                        "networkidle",
                        timeout=min(self.config.page_load_timeout_ms, 12000),
                    )
                except Exception:
                    # Fallback to domcontentloaded if networkidle times out
                    try:
                        await self._page.wait_for_load_state(
                            "domcontentloaded",
                            timeout=3000,
                        )
                    except Exception:
                        pass
                # Auto-dismiss popups after navigation
                await self._dismiss_popups()
            elif action.action == "click":
                # Check if clicking opened a new tab/window (e.g. Amazon target="_blank" product links)
                if self._context and len(self._context.pages) > 1:
                    latest = self._context.pages[-1]
                    if latest != self._page and not latest.is_closed():
                        logger.info(f"[M5] New tab opened after click: '{latest.url}'. Switching active page.")
                        self._page = latest
                # After clicking products/cart/buy, wait for new page to settle
                try:
                    await self._page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=min(self.config.page_load_timeout_ms, 5000),
                    )
                except Exception:
                    pass
            elif action.action in ("type", "fill"):
                await asyncio.sleep(0.5)
            elif action.action == "extract":
                await asyncio.sleep(0.3)
            elif action.action == "dismiss_popup":
                await asyncio.sleep(0.3)
        except Exception:
            pass  # Page might already be settled

    async def _dismiss_popups(self) -> None:
        """
        Auto-close cookie banners, notification prompts, login popups, and overlays.
        Runs silently — if no popups found, does nothing.
        """
        if not self._page or self._page.is_closed():
            return

        # Common popup/overlay close selectors across major sites
        popup_selectors = [
            # Cookie consent
            "button:has-text('Accept')",
            "button:has-text('Accept All')",
            "button:has-text('Accept Cookies')",
            "button:has-text('Got it')",
            "button:has-text('I agree')",
            "button:has-text('OK')",
            "button:has-text('Agree')",
            "[aria-label='Accept cookies']",
            "#cookie-accept",
            # Generic close buttons
            "button[aria-label='Close']",
            "button[aria-label='Dismiss']",
            "button:has-text('✕')",
            "button:has-text('×')",
            "button:has-text('Close')",
            ".close-button",
            ".modal-close",
            "[data-dismiss='modal']",
            "[data-testid='close-button']",
            # Login/notification dismiss
            "button:has-text('Not Now')",
            "button:has-text('Skip')",
            "button:has-text('No Thanks')",
            "button:has-text('Maybe Later')",
            "button:has-text('Remind me later')",
            # Amazon-specific
            "#sp-cc-accept",
            "input[data-action-type='DISMISS']",
            # Flipkart-specific
            "button._2KpZ6l._2doB4z",
            "button:has-text('✕'):near(.login)",
        ]

        for sel in popup_selectors:
            try:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=600):
                    await el.click(timeout=1500)
                    logger.info(f"[M5] Dismissed popup via: {sel}")
                    await asyncio.sleep(0.3)
                    break  # One popup dismissed per call
            except Exception:
                continue

    # ── Element Resolution (Multi-strategy with caching & semantic mapping) ───

    async def _resolve_element(self, selector: str | None, timeout: int):
        """
        Resolve an element using multiple strategies with caching.

        Priority:
        1. Cached CSS selector (from previous successful resolution)
        2. Semantic intent matches (search buttons, search inputs, product links, cart)
        3. Direct CSS locator
        4. aria-label match
        5. Placeholder match
        6. Text content match
        7. Role + name via get_by_role
        """
        if not selector:
            return None
        page = self._page
        if not page or page.is_closed():
            return None

        # 1. Check cache first
        if selector in self._selector_cache:
            cached = self._selector_cache[selector]
            try:
                el = page.locator(cached).first
                await el.wait_for(state="visible", timeout=min(timeout, 2000))
                return el
            except Exception:
                # Cache miss / DOM mutated — remove invalid entry
                del self._selector_cache[selector]

        sel_lower = selector.lower().strip()

        # 2. Semantic mapping for Search Buttons / Submit Buttons
        if any(k in sel_lower for k in ("search_button", "search_btn", "search button", "search-submit", "submit search", "submit_button")):
            search_btn_selectors = [
                "#nav-search-submit-button",
                "input[id*='search-submit']",
                "button[type='submit']",
                "input[type='submit']",
                "[aria-label*='search' i]",
                "[title*='search' i]",
                "button:has-text('Search')",
                "button:has-text('Go')",
                ".nav-search-submit input",
            ]
            for s in search_btn_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 1500))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 3. Semantic mapping for Search Query / Inputs
        if any(k in sel_lower for k in ("search_query", "search_box", "search_input", "search query", "searchbox", "search bar", "search_field")):
            search_input_selectors = [
                "#twotabsearchtextbox",
                "input[name='field-keywords']",
                "input[name='q']",
                "input[type='search']",
                "input[placeholder*='search' i]",
                "input[aria-label*='search' i]",
                "input[type='text']",
                "textarea[name='q']",
            ]
            for s in search_input_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 1500))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 4. Semantic mapping for Products / Cheapest Item / First Item Links
        if any(k in sel_lower for k in ("cheapest_product", "first_product", "product_link", "product", "item_link", "first item", "cheapest item", "product_card")):
            product_selectors = [
                "[data-component-type='s-search-result'] h2 a",
                "[data-component-type='s-search-result'] a.a-link-normal[href*='/dp/']",
                "div[data-id] a",
                ".product-card a",
                "article a[href]",
                "a:has(h2)",
                "a:has(h3)",
            ]
            for s in product_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 2000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 5. Semantic mapping for Add to Cart / Cart Button
        if any(k in sel_lower for k in ("add_to_cart", "add to cart", "cart_button", "add_cart", "addtocart")):
            cart_selectors = [
                "#add-to-cart-button",
                "input#add-to-cart-button",
                "#add-to-cart-button-ubb",
                "button:has-text('Add to Cart')",
                "button:has-text('Add to cart')",
                "input[value*='Add to Cart' i]",
                "button:has-text('ADD TO CART')",
                "[data-action='add-to-cart']",
                "button.add-to-cart",
                ".add-to-cart-button",
                "button:has-text('Add to Basket')",
                # Flipkart
                "button:has-text('Add to Cart')",
                "button._2KpZ6l",
                "button.QqFHMw",
            ]
            for s in cart_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 3000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 6. Semantic mapping for Buy Now
        if any(k in sel_lower for k in ("buy_now", "buy now", "buy_button", "buynow")):
            buy_selectors = [
                "#buy-now-button",
                "input#buy-now-button",
                "button:has-text('Buy Now')",
                "button:has-text('BUY NOW')",
                "input[value*='Buy Now' i]",
                ".buy-now-button",
                "button._2KpZ6l._1FqOHf",
                "button:has-text('Buy Now')",
            ]
            for s in buy_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 3000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 7. Semantic mapping for Book Now / Reserve
        if any(k in sel_lower for k in ("book_now", "book now", "book_button", "reserve_button", "reserve", "book_ticket")):
            book_selectors = [
                "button:has-text('Book Now')",
                "button:has-text('Book')",
                "button:has-text('Reserve')",
                "a:has-text('Book Now')",
                "a:has-text('Book')",
                "button:has-text('BOOK NOW')",
                ".book-btn",
                ".book-now",
                "button:has-text('Search')",  # travel sites use "Search" for booking
            ]
            for s in book_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 3000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 8. Semantic mapping for Login / Sign In
        if any(k in sel_lower for k in ("login_button", "login", "sign_in", "signin", "log_in")):
            login_selectors = [
                "button:has-text('Sign In')",
                "button:has-text('Log In')",
                "button:has-text('Login')",
                "a:has-text('Sign In')",
                "a:has-text('Log In')",
                "a:has-text('Login')",
                "#signInSubmit",
                "input[type='submit'][value*='Sign' i]",
                "button[type='submit']",
            ]
            for s in login_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 2000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 9. Semantic mapping for Proceed / Continue / Next
        if any(k in sel_lower for k in ("proceed_button", "proceed", "continue_button", "continue", "next_button", "next")):
            proceed_selectors = [
                "button:has-text('Proceed')",
                "button:has-text('Continue')",
                "button:has-text('Next')",
                "a:has-text('Proceed')",
                "a:has-text('Continue')",
                "a:has-text('Next')",
                "input[type='submit'][value*='Proceed' i]",
                "input[type='submit'][value*='Continue' i]",
                ".proceed-btn",
                ".continue-btn",
            ]
            for s in proceed_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 2000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 10. Semantic mapping for Date Input / Picker
        if any(k in sel_lower for k in ("date_input", "date_picker", "date", "check_in", "check_out", "departure", "arrival")):
            date_selectors = [
                "input[type='date']",
                "input[placeholder*='date' i]",
                "input[placeholder*='check' i]",
                "input[name*='date' i]",
                "input[aria-label*='date' i]",
                "[data-testid*='date']",
                "input[id*='date' i]",
            ]
            for s in date_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 2000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 11. Semantic mapping for Quantity / Passengers
        if any(k in sel_lower for k in ("quantity_input", "quantity", "qty", "passenger_input", "passengers", "travellers", "adults")):
            qty_selectors = [
                "#quantity",
                "select[name*='quantity' i]",
                "input[name*='qty' i]",
                "input[name*='quantity' i]",
                "select[name*='passenger' i]",
                "select[name*='adult' i]",
                "input[name*='passenger' i]",
            ]
            for s in qty_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 2000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 12. Semantic mapping for Close Popup / Dismiss
        if any(k in sel_lower for k in ("close_popup", "dismiss", "close_modal", "close_overlay", "close_banner")):
            popup_selectors = [
                "button[aria-label='Close']",
                "button[aria-label='Dismiss']",
                "button:has-text('✕')",
                "button:has-text('×')",
                "button:has-text('Close')",
                ".close-button",
                ".modal-close",
                "[data-dismiss='modal']",
                "button:has-text('Not Now')",
                "button:has-text('Skip')",
                "#sp-cc-accept",
            ]
            for s in popup_selectors:
                try:
                    el = page.locator(s).first
                    if await el.is_visible(timeout=800):
                        self._selector_cache[selector] = s
                        return el
                except Exception:
                    continue
            # No popup found — not an error
            return None

        # 5. Try as direct CSS selector
        try:
            el = page.locator(selector).first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            self._selector_cache[selector] = selector
            return el
        except Exception:
            pass

        # 6. Try aria-label
        try:
            el = page.locator(f'[aria-label*="{selector}" i]').first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            self._selector_cache[selector] = f'[aria-label*="{selector}" i]'
            return el
        except Exception:
            pass

        # 7. Try placeholder
        try:
            el = page.locator(f'[placeholder*="{selector}" i]').first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            self._selector_cache[selector] = f'[placeholder*="{selector}" i]'
            return el
        except Exception:
            pass

        # 8. Try text match
        try:
            el = page.get_by_text(selector, exact=False).first
            await el.wait_for(state="visible", timeout=min(timeout, 2000))
            return el
        except Exception:
            pass

        # 9. Try role-based matching for common interactive roles
        for role in ("button", "link", "textbox", "searchbox", "combobox"):
            try:
                el = page.get_by_role(role, name=selector).first
                await el.wait_for(state="visible", timeout=min(timeout, 1500))
                return el
            except Exception:
                continue

        # 13. Cross-tab search fallback: if element not on current page, check other open tabs
        if self._context and len(self._context.pages) > 1:
            for other_page in reversed(self._context.pages):
                if other_page != page and not other_page.is_closed():
                    try:
                        el = other_page.locator(selector).first
                        if await el.is_visible(timeout=1000):
                            logger.info(f"[M5] Element '{selector}' found on another tab ({other_page.url}). Switching active page.")
                            self._page = other_page
                            return el
                    except Exception:
                        pass

        logger.warning(f"[M5] Element not found after all strategies: {selector}")
        return None

    # ── In-Page Product & Direct Link Extraction ──────────────────────────────

    async def _extract_page_products_or_items(
        self, selector: str | None = None, value: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract structured items, titles, prices, ratings, and direct links from the page.
        """
        if not self._page or self._page.is_closed():
            return []

        js_extractor = """
        () => {
            const results = [];
            const seenUrls = new Set();

            // 1. Amazon selectors
            const amazonItems = document.querySelectorAll('div[data-component-type="s-search-result"], div.s-result-item[data-asin]');
            if (amazonItems.length > 0) {
                amazonItems.forEach(item => {
                    const titleEl = item.querySelector('h2 a span, h2 a, h2 span, span.a-text-normal');
                    const linkEl = item.querySelector('h2 a, a.a-link-normal[href*="/dp/"], a[href*="/dp/"]');
                    const priceEl = item.querySelector('.a-price .a-offscreen, .a-price-whole');
                    const ratingEl = item.querySelector('i.a-icon-star-small span, span.a-icon-alt');
                    
                    if (titleEl && linkEl) {
                        const title = titleEl.textContent.trim();
                        let href = linkEl.getAttribute('href') || '';
                        if (href.startsWith('/')) href = window.location.origin + href;
                        
                        let priceText = priceEl ? priceEl.textContent.trim() : '';
                        let priceNum = 0;
                        if (priceText) {
                            const cleanNum = priceText.replace(/[^0-9.]/g, '');
                            priceNum = parseFloat(cleanNum) || 0;
                        }
                        
                        if (title && href && !seenUrls.has(href)) {
                            seenUrls.add(href);
                            results.push({
                                title: title,
                                price: priceText || 'N/A',
                                price_num: priceNum,
                                url: href,
                                rating: ratingEl ? ratingEl.textContent.trim() : ''
                            });
                        }
                    }
                });
            }

            // 2. Flipkart selectors
            if (results.length === 0) {
                const flipkartItems = document.querySelectorAll('div[data-id], div._1AtVbE, div._75nlfW');
                flipkartItems.forEach(item => {
                    const titleEl = item.querySelector('div.KzDlHZ, div._4rR01T, a.wByJw6, a.s1Q9rs, div[class*="title"]');
                    const linkEl = item.querySelector('a[href*="/p/"], a._1fQZEK, a.VJA3rP, a[class*="link"]');
                    const priceEl = item.querySelector('div.Nx9bqj, div._30jeq3, div[class*="price"]');
                    
                    if (titleEl) {
                        const title = titleEl.textContent.trim();
                        let href = linkEl ? linkEl.getAttribute('href') || '' : '';
                        if (href.startsWith('/')) href = window.location.origin + href;
                        let priceText = priceEl ? priceEl.textContent.trim() : '';
                        let priceNum = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                        
                        if (title && (!href || !seenUrls.has(href))) {
                            if (href) seenUrls.add(href);
                            results.push({
                                title: title,
                                price: priceText || 'N/A',
                                price_num: priceNum,
                                url: href || window.location.href,
                                rating: ''
                            });
                        }
                    }
                });
            }

            // 3. Generic Product / Article / Search results (Google, Shopify, general stores)
            if (results.length === 0) {
                const cards = document.querySelectorAll('article, .product-card, .product-item, .product, div.card, div.g');
                cards.forEach(card => {
                    const heading = card.querySelector('h1, h2, h3, h4, .title, a');
                    const link = card.querySelector('a[href]');
                    const price = card.querySelector('.price, [class*="price"], [id*="price"]');
                    
                    if (heading && link) {
                        const title = heading.textContent.trim();
                        let href = link.getAttribute('href') || '';
                        if (href.startsWith('/')) href = window.location.origin + href;
                        let priceText = price ? price.textContent.trim() : '';
                        let priceNum = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                        
                        if (title && href && href.startsWith('http') && !seenUrls.has(href)) {
                            seenUrls.add(href);
                            results.push({
                                title: title,
                                price: priceText || 'N/A',
                                price_num: priceNum,
                                url: href,
                                rating: ''
                            });
                        }
                    }
                });
            }

            // 4. Fallback: all links with significant headings/text
            if (results.length === 0) {
                const links = document.querySelectorAll('h2 a[href], h3 a[href], a[href]:has(h2), a[href]:has(h3)');
                links.forEach(l => {
                    let href = l.getAttribute('href') || '';
                    if (href.startsWith('/')) href = window.location.origin + href;
                    const text = l.textContent.trim();
                    if (text.length > 10 && href.startsWith('http') && !seenUrls.has(href)) {
                        seenUrls.add(href);
                        results.push({
                            title: text,
                            price: 'N/A',
                            price_num: 0,
                            url: href,
                            rating: ''
                        });
                    }
                });
            }

            return results.slice(0, 15);
        }
        """

        try:
            items = await self._page.evaluate(js_extractor) or []
            # If user asked for cheapest product, sort by price_num ascending
            sel_query = f"{selector or ''} {value or ''}".lower()
            if any(k in sel_query for k in ("cheap", "lowest", "least", "min")):
                valid_priced = [it for it in items if it.get("price_num", 0) > 0]
                unpriced = [it for it in items if it.get("price_num", 0) == 0]
                valid_priced.sort(key=lambda x: x["price_num"])
                items = valid_priced + unpriced

            logger.info(f"[M5] Extracted {len(items)} items from page '{self._page.url}'")
            return items
        except Exception as exc:
            logger.warning(f"[M5] In-page extraction failed: {exc}")
            return []

    # ── State Capture ─────────────────────────────────────────────────────────

    async def _capture_state(
        self, run_id: str, step_index: int, take_screenshot: bool
    ) -> dict[str, Any]:
        """Defensively capture current page URL, title, accessibility tree, extracted items, and optional screenshot."""
        page = self._page

        url = ""
        title = ""
        if page and not page.is_closed():
            try:
                url = page.url or ""
                title = await page.title()
            except Exception:
                url = getattr(page, "url", "") or ""
                title = "Unknown Page"

        # Accessibility tree snapshot
        acc_tree = {}
        if page and not page.is_closed():
            try:
                acc_tree = await page.accessibility.snapshot() or {}
            except Exception as acc_err:
                logger.debug(f"[M5] Accessibility snapshot failed: {acc_err}")
                acc_tree = {}

        # Automated product/link extraction on result pages
        extracted_items = []
        direct_link = None
        if self._last_extracted_items:
            extracted_items = list(self._last_extracted_items)
            direct_link = extracted_items[0].get("url")
            self._last_extracted_items = []
        elif page and not page.is_closed() and any(k in (url or "").lower() for k in ("search", "s?", "/p/", "/dp/", "results", "query")):
            try:
                extracted_items = await self._extract_page_products_or_items()
                if extracted_items:
                    direct_link = extracted_items[0].get("url")
            except Exception:
                extracted_items = []

        # Optional Screenshot
        screenshot_path = None
        if take_screenshot and page and not page.is_closed():
            try:
                screenshot_path = await self._save_screenshot(run_id, step_index)
            except Exception as sc_err:
                logger.warning(f"[M5] Failed to capture screenshot: {sc_err}")

        return {
            "url": url,
            "title": title,
            "accessibility_tree": acc_tree,
            "screenshot_path": screenshot_path,
            "extracted_items": extracted_items,
            "direct_link": direct_link,
        }

    async def _save_screenshot(self, run_id: str, step_index: int) -> str | None:
        """Save a screenshot to logs/runs/{run_id}/step_{n}.png."""
        if not self._page or self._page.is_closed():
            return None
        run_dir = Path(self.config.log_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = str(run_dir / f"step_{step_index:03d}.png")
        await self._page.screenshot(path=path, full_page=False)
        logger.debug(f"[M5] Screenshot saved: {path}")
        return path

    def _check_blocklist(self, url: str) -> None:
        """Raise BrowserBlockedError if URL matches any blocklist pattern."""
        url_lower = (url or "").lower()
        for pattern in self.config.block_purchase_urls:
            if pattern.lower() in url_lower:
                raise BrowserBlockedError(
                    f"Navigation blocked: URL '{url}' matches blocked pattern '{pattern}'"
                )

    def clear_selector_cache(self) -> None:
        """Clear the selector cache (e.g. when navigating to a new site)."""
        self._selector_cache.clear()
