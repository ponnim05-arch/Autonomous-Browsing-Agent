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
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

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

    # Class-level persistent session for reusing the same browser window across tasks
    _shared_playwright: Any = None
    _shared_browser: Any = None
    _shared_context: Any = None
    _shared_page: Any = None

    def __init__(
        self,
        config: AgentConfig = default_config,
        status_callback: Optional[Callable[[str, str, Optional[str]], None]] = None,
        reuse_session: Optional[bool] = None,
        **kwargs: Any,
    ):
        self.config = config
        self._status_callback = status_callback
        if reuse_session is None and "reuse_session" in kwargs:
            reuse_session = kwargs["reuse_session"]
        self.reuse_session = (
            reuse_session
            if reuse_session is not None
            else getattr(config, "reuse_browser", False)
        )
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._is_started = False
        self._is_cdp = False
        self._reused_shared_session = False
        # Selector cache: description → CSS selector
        self._selector_cache: dict[str, str] = {}
        self._last_extracted_items: list[dict[str, Any]] = []

    # ── Status Callback ────────────────────────────────────────────────────────

    def _emit_status(self, event: str, message: str, url: Optional[str] = None) -> None:
        """Fire the status callback if one is registered."""
        if self._status_callback:
            try:
                self._status_callback(event, message, url)
            except Exception:
                pass  # Never let callback errors disrupt execution
        logger.info(f"[M5] Status: [{event}] {message}" + (f" ({url})" if url else ""))

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def is_alive(self) -> bool:
        """Check if the full Playwright → Browser → Context → Page chain is healthy."""
        if not self._is_started or not self._playwright or not self._browser:
            return False
        if not self._browser.is_connected():
            return False
        if not self._context:
            return False
        if not self._page or self._page.is_closed():
            return False
        return True

    @property
    def current_url(self) -> str:
        """Return the current page URL, or empty string if unavailable."""
        if self._page and not self._page.is_closed():
            return self._page.url or ""
        return ""

    @property
    def current_title(self) -> str:
        """Return a cached title hint. For async title, use await page.title()."""
        # Playwright title() is async; this provides a sync best-effort hint.
        if self._page and not self._page.is_closed():
            return getattr(self._page, '_last_title', '') or ''
        return ""

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
            "browser_mode": getattr(cfg, "browser_mode", "visible"),
            "browser_connection_mode": getattr(cfg, "browser_connection_mode", "playwright"),
            "headless": cfg.headless,
            "keep_browser_open": getattr(cfg, "keep_browser_open", False),
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

        browser_mode = getattr(self.config, "browser_mode", "visible")

        # ── Reuse shared session if active and healthy ─────────────────────
        if self.reuse_session and BrowserExecutor._shared_browser:
            shared_b = BrowserExecutor._shared_browser
            shared_ctx = BrowserExecutor._shared_context
            try:
                if shared_b.is_connected() and shared_ctx:
                    self._playwright = BrowserExecutor._shared_playwright
                    self._browser = shared_b
                    self._context = shared_ctx

                    # Ensure we have an active, open page
                    page = BrowserExecutor._shared_page
                    if not page or page.is_closed():
                        pages = self._context.pages
                        if pages and not pages[-1].is_closed():
                            page = pages[-1]
                        else:
                            page = await self._context.new_page()

                    self._page = page
                    BrowserExecutor._shared_page = page
                    try:
                        await self._page.bring_to_front()
                    except Exception:
                        pass

                    self._is_started = True
                    self._reused_shared_session = True
                    self._emit_status("browser_started", f"✅ Reused existing browser window (mode={browser_mode})")
                    logger.info("[M5] Successfully attached to existing browser window session.")
                    return
            except Exception as e:
                logger.warning(f"[M5] Could not attach to shared browser: {e}. Launching fresh instance...")
                await BrowserExecutor.close_shared_session()

        self._emit_status("browser_starting", f"🌐 Starting browser (mode={browser_mode}, type={self.config.browser_type})...")

        try:
            self._playwright = await async_playwright().start()

            if connection_mode == "cdp":
                await self._start_cdp()
            else:
                await self._start_playwright()

            if self.reuse_session:
                BrowserExecutor._shared_playwright = self._playwright
                BrowserExecutor._shared_browser = self._browser
                BrowserExecutor._shared_context = self._context
                BrowserExecutor._shared_page = self._page

            self._is_started = True
            self._emit_status("browser_started", f"✅ Browser started (mode={browser_mode}, type={self.config.browser_type}, headless={self.config.headless})")
            logger.info(
                f"[M5] BrowserExecutor ready (mode={connection_mode}, browser_mode={browser_mode}, type={self.config.browser_type}, headless={self.config.headless})"
            )
        except BrowserStartupError:
            self._emit_status("browser_error", "❌ Browser startup failed")
            await self.stop()
            raise
        except Exception as exc:
            self._emit_status("browser_error", f"❌ Could not start browser: {exc}")
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
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=CalculateNativeWinOcclusion",
            "--disable-ipc-flooding-protection",
        ]
        # In visible mode, start maximized for better UX
        if not self.config.headless:
            browser_args.append("--start-maximized")

        launch_kwargs = {
            "headless": self.config.headless,
            "args": browser_args,
        }

        self._is_cdp = False
        self._browser = await self._launch_browser_resiliently(b_type, launch_kwargs)

        # For visible mode with --start-maximized, use no_viewport so the
        # page fills the maximized window instead of being constrained.
        ctx_kwargs = {
            "user_agent": _USER_AGENT,
            "locale": "en-IN",
        }
        if not self.config.headless:
            ctx_kwargs["no_viewport"] = True
        else:
            ctx_kwargs["viewport"] = {"width": 1366, "height": 768}

        self._context = await self._browser.new_context(**ctx_kwargs)

        # Force links to open in the same window/tab instead of opening separate windows
        try:
            await self._context.add_init_script("""
                // Prevent target="_blank" from opening new windows/tabs
                document.addEventListener('DOMContentLoaded', () => {
                    document.querySelectorAll('a[target="_blank"]').forEach(a => a.removeAttribute('target'));
                });
                document.addEventListener('click', (e) => {
                    const a = e.target && e.target.closest ? e.target.closest('a') : null;
                    if (a && a.getAttribute('target') === '_blank') {
                        a.removeAttribute('target');
                    }
                }, true);
            """)
        except Exception as e:
            logger.debug(f"[M5] Could not add link init script: {e}")

        # Auto-track and focus any new tabs that are opened
        def _handle_new_tab(new_p):
            logger.info(f"[M5] New tab opened: {new_p.url}. Keeping active page updated.")
            self._page = new_p
            BrowserExecutor._shared_page = new_p

        try:
            res = self._context.on("page", _handle_new_tab)
            if inspect.isawaitable(res):
                await res
        except Exception:
            pass

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

    async def stop(self, force_close: bool = False) -> None:
        """Close browser, context, page, and Playwright cleanly without leaving dangling processes.

        If reuse_session is True and not force_close, the browser window stays open
        for subsequent tasks to execute in the same window.
        """
        keep_open = getattr(self.config, "keep_browser_open", False)

        if self.reuse_session and not force_close:
            logger.info("[M5] reuse_session=True — browser window kept alive for subsequent tasks.")
            self._emit_status("browser_kept_open", "🌐 Browser window kept open for subsequent tasks")
            self._is_started = False
            self._selector_cache.clear()
            return

        if not self.reuse_session and keep_open and self._browser and not self._is_cdp:
            # Leave the browser window open — only release Python handles
            logger.info("[M5] keep_browser_open=True — browser window stays open.")
            self._emit_status("browser_kept_open", "🌐 Browser window left open for review")
            self._page = None
            self._context = None
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
            return

        self._emit_status("browser_stopping", "🔄 Closing browser...")

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

        # If this instance was using the shared session, clear the shared pointers
        if self.reuse_session or force_close:
            BrowserExecutor._shared_page = None
            BrowserExecutor._shared_context = None
            BrowserExecutor._shared_browser = None
            BrowserExecutor._shared_playwright = None

        self._emit_status("browser_stopped", "✅ Browser closed")
        logger.info("[M5] Browser stopped and resources released.")

    @classmethod
    async def close_shared_session(cls) -> None:
        """Explicitly shut down any persistent shared browser window."""
        try:
            if cls._shared_page and not cls._shared_page.is_closed():
                await cls._shared_page.close()
        except Exception:
            pass
        finally:
            cls._shared_page = None

        try:
            if cls._shared_context:
                await cls._shared_context.close()
        except Exception:
            pass
        finally:
            cls._shared_context = None

        try:
            if cls._shared_browser and cls._shared_browser.is_connected():
                await cls._shared_browser.close()
        except Exception:
            pass
        finally:
            cls._shared_browser = None

        try:
            if cls._shared_playwright:
                await cls._shared_playwright.stop()
        except Exception:
            pass
        finally:
            cls._shared_playwright = None

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
                BrowserExecutor._shared_page = self._page
                try:
                    await self._page.bring_to_front()
                except Exception:
                    pass
            else:
                self._page = await self._context.new_page()
                BrowserExecutor._shared_page = self._page
        elif not self._page or self._page.is_closed():
            logger.warning("[M5] Browser page was closed or missing. Creating a new page to recover session...")
            self._page = await self._context.new_page()
            BrowserExecutor._shared_page = self._page

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

        # Emit status before action execution
        act_desc = action.action
        if action.action == "navigate":
            self._emit_status("navigating", f"🔗 Navigating to {action.value}", action.value)
        elif action.action in ("type", "fill"):
            self._emit_status("action", f"⌨️ Typing into {action.selector or 'input'}...")
        elif action.action == "click":
            self._emit_status("action", f"🖱️ Clicking {action.selector or 'element'}...")
        elif action.action == "extract":
            self._emit_status("action", f"🔍 Extracting data...")
        elif action.action == "scroll":
            self._emit_status("action", f"📜 Scrolling page...")
        else:
            self._emit_status("action", f"🤖 Executing: {act_desc}")

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

        # Emit post-action status with current page info
        if success:
            self._emit_status("page_loaded", f"📄 {raw_state.get('title', 'Page')}", raw_state.get("url"))
        else:
            self._emit_status("action_failed", f"⚠️ Action failed: {error_msg}")
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

    async def _click_resiliently(self, el: Any, timeout: int = 4000, force: bool = False) -> None:
        """
        Robustly click an element using a 4-tier fallback:
        Tier 1: Scroll into view so button is positioned in the viewport
        Tier 2: Standard Playwright click (simulates genuine user interaction)
        Tier 3: Forced Playwright click (force=True, bypasses actionability & occlusion checks)
        Tier 4: JavaScript DOM click (el.evaluate("e => e.click()")) - 100% reliable for small buttons,
                elements with inner spans/SVGs, and transparent wrappers.
        """
        # Tier 1: Scroll into view
        try:
            await el.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        # Tier 2: Standard click
        if not force:
            try:
                await el.click(timeout=min(timeout, 3000))
                return
            except Exception as e1:
                logger.debug(f"[M5] Standard click intercepted or timed out ({e1}). Retrying with force click...")

        # Tier 3: Force click
        try:
            await el.click(force=True, timeout=2000)
            return
        except Exception as e2:
            logger.debug(f"[M5] Force click failed ({e2}). Falling back to native DOM click...")

        # Tier 4: Direct DOM JavaScript click dispatch
        try:
            await el.evaluate("""e => {
                const target = e.closest('button, a, input[type="submit"], input[type="button"], [role="button"]') || e;
                target.scrollIntoView({ block: 'center', inline: 'center' });
                target.click();
            }""")
            return
        except Exception as e3:
            logger.warning(f"[M5] Native DOM click failed: {e3}")
            raise e3

    # ── Action Dispatch ───────────────────────────────────────────────────────

    async def _dispatch(self, action: ActionObject, timeout: int) -> None:
        """Route action to the correct Playwright method."""
        page = self._page
        act = (action.action or "").lower().strip()
        sel_lower = (action.selector or "").lower().strip()

        # Multi-item cart execution
        if act in ("add_all_to_cart", "add_multiple_to_cart") or (
            act == "click" and any(k in sel_lower for k in ("add_all_to_cart", "add_them_to_cart", "add all to cart", "add_all", "add them to cart", "add all"))
        ):
            await self._add_all_to_cart(action, timeout)
            return

        if act == "click":
            is_volume = any(k in sel_lower for k in ("volume", "sound", "unmute", "max_volume", "volume_max"))
            is_play = any(k in sel_lower for k in ("play", "video_player", "play_button"))

            # Volume & Sound handling: directly maximize volume via HTML5 video element
            if is_volume:
                try:
                    await page.evaluate("""
                        () => {
                            const v = document.querySelector('video');
                            if (v) {
                                v.muted = false;
                                v.volume = 1.0;
                            }
                        }
                    """)
                except Exception:
                    pass

            # Video play handling: play HTML5 video element
            if is_play:
                try:
                    await page.evaluate("""
                        () => {
                            const v = document.querySelector('video');
                            if (v && v.paused) {
                                v.play();
                            }
                        }
                    """)
                except Exception:
                    pass

            # Smart check: If item is ALREADY added to cart and we are on cart confirmation/wagon page
            curr_url = (page.url or "").lower()
            try:
                curr_title = (await page.title() or "").lower()
            except Exception:
                curr_title = ""

            is_cart_page = any(k in curr_url for k in ("/cart", "/smart-wagon", "/gp/cart", "/viewcart")) or any(k in curr_title for k in ("shopping cart", "cart", "added to cart"))

            if is_cart_page and any(k in sel_lower for k in ("add_to_cart", "add to cart", "add_cart", "addtocart")):
                logger.info(f"[M5] Product is already added to cart on {curr_url} ('{curr_title}'). Step fulfilled.")
                return

            el = await self._resolve_element(action.selector, timeout)
            if el:
                try:
                    await self._click_resiliently(el, timeout=timeout, force=(is_volume or is_play))
                except Exception as click_err:
                    if is_volume or is_play:
                        logger.info(f"[M5] Click on {action.selector} bypassed due to overlay ({click_err}), action fulfilled via video JS")
                        return
                    raise click_err

                # If we clicked a video or play button, ensure playback started
                if any(k in sel_lower for k in ("video", "play")):
                    try:
                        await page.evaluate("() => { const v = document.querySelector('video'); if (v && v.paused) v.play(); }")
                    except Exception:
                        pass
                return
            else:
                # If on cart page and asking for cart_button, but cart button was not resolved as element
                if is_cart_page and any(k in sel_lower for k in ("cart_button", "view_cart", "cart", "open_cart", "go_to_cart")):
                    logger.info(f"[M5] Already on cart page ({curr_url}). Cart view fulfilled.")
                    return
                # If volume action, we already set volume in JS, so consider it accomplished
                if is_volume:
                    logger.info("[M5] Volume/sound set directly via HTML5 video element")
                    return
                # If play button, we already attempted play in JS
                if is_play:
                    logger.info("[M5] Video play triggered directly via HTML5 video element")
                    return
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
                await page.goto(url, wait_until="domcontentloaded", timeout=min(self.config.page_load_timeout_ms, 20000))
            except Exception as goto_err:
                logger.warning(f"[M5] Fast goto with domcontentloaded failed: {goto_err}. Retrying standard goto...")
                try:
                    await page.goto(url, timeout=self.config.page_load_timeout_ms)
                except Exception as e2:
                    curr = page.url or ""
                    target_host = url.split("://")[-1].split("/")[0].replace("www.", "")
                    if target_host and target_host in curr:
                        logger.info(f"[M5] Target host '{target_host}' reached despite timeout warning.")
                    else:
                        raise e2

        elif act == "scroll":
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")

        elif act == "extract":
            # Live in-page structured product and link extraction
            limit = 20
            if action.value:
                try:
                    limit_match = re.search(r'\b(\d{1,2})\b', str(action.value))
                    if limit_match:
                        limit = int(limit_match.group(1))
                except Exception:
                    limit = 20
            extracted = await self._extract_page_products_or_items(action.selector, action.value, limit=limit)
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
            if any(k in key.lower() for k in ("volumemax", "volumeup", "volume_up", "sound", "max")):
                try:
                    await page.evaluate("""
                        () => {
                            const v = document.querySelector('video');
                            if (v) {
                                v.muted = false;
                                v.volume = 1.0;
                            }
                        }
                    """)
                except Exception:
                    pass
            else:
                try:
                    await page.keyboard.press(key)
                except Exception as e:
                    logger.warning(f"[M5] Keyboard press '{key}' failed: {e}")

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
                        BrowserExecutor._shared_page = latest
                        try:
                            await latest.bring_to_front()
                        except Exception:
                            pass
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
            # YouTube-specific ad dismiss
            "button.ytp-ad-skip-button",
            "button.ytp-ad-skip-button-modern",
            ".ytp-ad-skip-button-container button",
            "button:has-text('Skip Ads')",
            "button:has-text('Skip Ad')",
            "button:has-text('Skip')",
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
                "input[name='search_query']",
                "input#search",
                "ytd-searchbox input",
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

        # 5. Semantic mapping for Add to Cart
        if any(k in sel_lower for k in ("add_to_cart", "add to cart", "add_cart", "addtocart", "add_to_bag", "add to bag", "add_to_basket")):
            cart_selectors = [
                # Amazon Desktop & Mobile (visible buybox first)
                "#desktop_qualifiedBuyBox #add-to-cart-button",
                "#buybox #add-to-cart-button",
                "#desktop_qualifiedBuyBox input[name='submit.add-to-cart']",
                "#add-to-cart-button",
                "input#add-to-cart-button",
                "span.a-button:has(#add-to-cart-button)",
                "span.a-button-primary:has(#add-to-cart-button)",
                "#add-to-cart-button-ubb",
                "input[name='submit.add-to-cart']",
                "#exportsUndeliverable-cart-announce",
                "#bundle-add-to-cart-button",
                "#addToCart",
                "span[id*='submit.add-to-cart'] input",
                "button[name='submit.addToCart']",
                "input[name='submit.addToCart']",
                "[data-action='add-to-cart']",
                # Flipkart Modern & Classic
                "button:has-text('Add to Cart')",
                "button:has-text('ADD TO CART')",
                "button:has-text('Add to cart')",
                "button._2KpZ6l._2U9uOA._3v1-ww",
                "button.QqFHMw",
                "button[class*='QqFHMw']",
                "li button:has-text('Add to Cart')",
                "ul.row li button",
                # Generic E-Commerce
                "button:has-text('Add to Bag')",
                "button:has-text('ADD TO BAG')",
                "button:has-text('Add to Basket')",
                "button[name*='add-to-cart' i]",
                "[data-testid*='add-to-cart' i]",
                "button.add-to-cart",
                ".add-to-cart-button",
                "input[value*='Add to Cart' i]",
                "a:has-text('Add to Cart')",
            ]
            # Prioritize the first visible button to avoid hidden trade-in/secondary forms
            for s in cart_selectors:
                try:
                    loc = page.locator(s)
                    cnt = await loc.count()
                    for idx in range(cnt):
                        cand = loc.nth(idx)
                        if await cand.is_visible():
                            self._selector_cache[selector] = s
                            return cand
                except Exception:
                    continue
            # Fallback to direct locator if none visible yet
            try:
                el = page.locator(", ".join(cart_selectors)).first
                await el.wait_for(state="attached", timeout=min(timeout, 2000))
                return el
            except Exception:
                pass

        # 6. Semantic mapping for Cart Button / View Cart / Go to Cart
        if any(k in sel_lower for k in ("cart_button", "view_cart", "go_to_cart", "open_cart", "my_cart", "shopping_cart", "view cart", "cart")):
            view_cart_selectors = [
                # Amazon Cart Navigation & Smart Wagon
                "#nav-cart",
                "#nav-cart-count-container",
                "#sw-gtc a",
                ".sw-gtc a",
                "a:has-text('Go to Cart')",
                "a:has-text('View Cart')",
                "#attach-sidesheet-view-cart-button",
                "#attach-sidesheet-view-cart-button a",
                "a[href*='/cart']",
                "a[href*='/gp/cart']",
                # Flipkart Cart Navigation
                "a[href*='/viewcart']",
                "a:has-text('Cart')",
                "a._3SkBxJ",
                # Generic Cart Links
                "a[href*='cart' i]",
                "button[aria-label*='cart' i]",
                "a[aria-label*='cart' i]",
                "button:has-text('Cart')",
                "a:has-text('Bag')",
                "a:has-text('Basket')",
            ]
            combined = ", ".join(view_cart_selectors)
            try:
                el = page.locator(combined).first
                await el.wait_for(state="attached", timeout=min(timeout, 2500))
                self._selector_cache[selector] = combined
                return el
            except Exception:
                pass
            for s in view_cart_selectors:
                try:
                    el = page.locator(s).first
                    if await el.is_visible(timeout=200):
                        self._selector_cache[selector] = s
                        return el
                except Exception:
                    continue

        # 7. Semantic mapping for Buy Now
        if any(k in sel_lower for k in ("buy_now", "buy now", "buy_button", "buynow", "buy")):
            buy_selectors = [
                # Amazon
                "#buy-now-button",
                "input#buy-now-button",
                "span.a-button:has(#buy-now-button)",
                "span.a-button-oneclick:has(#buy-now-button)",
                "input[name='submit.buy-now']",
                "#buyNow_feature_div input",
                "span[id*='submit.buy-now'] input",
                "[data-action='buy-now']",
                "input[value*='Buy Now' i]",
                # Flipkart
                "button:has-text('Buy Now')",
                "button:has-text('BUY NOW')",
                "button._2KpZ6l._1FqOHf",
                "button.QqFHMw._2qbW8n",
                "li button:has-text('Buy Now')",
                # Generic
                "button:has-text('Buy Now')",
                "button[name*='buy-now' i]",
                "[data-testid*='buy-now' i]",
                ".buy-now-button",
                "a:has-text('Buy Now')",
            ]
            combined = ", ".join(buy_selectors)
            try:
                el = page.locator(combined).first
                await el.wait_for(state="attached", timeout=min(timeout, 2500))
                self._selector_cache[selector] = combined
                return el
            except Exception:
                pass
            for s in buy_selectors:
                try:
                    el = page.locator(s).first
                    if await el.is_visible(timeout=200):
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

        # 13. Semantic mapping for Videos / YouTube
        if any(k in sel_lower for k in ("first_video", "video_link", "video_title", "first video", "video_item", "video")):
            video_selectors = [
                "ytd-video-renderer a#video-title",
                "ytd-video-renderer #video-title",
                "a#video-title",
                "ytd-video-renderer a#thumbnail",
                "#contents ytd-video-renderer a#thumbnail",
                "ytd-rich-item-renderer a#video-title",
                "a[href*='/watch']",
                "video",
            ]
            for s in video_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 3000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 14. Semantic mapping for Video Play / Pause Button
        if any(k in sel_lower for k in ("play_button", "play button", "play_video", "pause_button", "video_player")):
            play_selectors = [
                "button.ytp-play-button",
                ".ytp-play-button",
                "button[aria-label*='Play' i]",
                "button[aria-label*='Pause' i]",
                ".video-stream",
                "video",
            ]
            for s in play_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 2500))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 15. Semantic mapping for Volume / Sound / Unmute
        if any(k in sel_lower for k in ("volume_max", "volume", "sound", "unmute", "volume_button", "mute_button", "max_volume")):
            volume_selectors = [
                "button.ytp-mute-button",
                ".ytp-mute-button",
                ".ytp-volume-panel",
                "button[aria-label*='Mute' i]",
                "button[aria-label*='volume' i]",
                "button[aria-label*='Unmute' i]",
                "video",
            ]
            for s in volume_selectors:
                try:
                    el = page.locator(s).first
                    await el.wait_for(state="visible", timeout=min(timeout, 2000))
                    self._selector_cache[selector] = s
                    return el
                except Exception:
                    continue

        # 16. Try as direct CSS selector
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
        self, selector: str | None = None, value: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """
        Extract structured items, titles, prices, ratings, and direct links from the page.
        """
        if not self._page or self._page.is_closed():
            return []

        js_extractor = """
        (maxCount) => {
            const results = [];
            const seenUrls = new Set();
            const cap = maxCount || 20;

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

            return results.slice(0, cap);
        }
        """

        try:
            items = await self._page.evaluate(js_extractor, limit) or []
            # If user asked for cheapest product, sort by price_num ascending
            sel_query = f"{selector or ''} {value or ''}".lower()
            if any(k in sel_query for k in ("cheap", "lowest", "least", "min")):
                valid_priced = [it for it in items if it.get("price_num", 0) > 0]
                unpriced = [it for it in items if it.get("price_num", 0) == 0]
                valid_priced.sort(key=lambda x: x["price_num"])
                items = valid_priced + unpriced

            logger.info(f"[M5] Extracted {len(items)} items from page '{self._page.url}' (requested limit={limit})")
            return items
        except Exception as exc:
            logger.warning(f"[M5] In-page extraction failed: {exc}")
            return []

    # ── Multi-Item Cart Execution ─────────────────────────────────────────────

    async def _add_all_to_cart(self, action: ActionObject, timeout: int) -> None:
        """
        Sequentially visit each extracted product in the SAME browser tab,
        click Add to Cart, record real-time status per item, and navigate
        to the cart page at the end.
        """
        page = self._page
        if not page or page.is_closed():
            raise RuntimeError("Browser page not available for add_all_to_cart")

        # Parse target item count
        target_count = 10
        raw_val = str(action.value or "")
        count_match = re.search(r'\b(\d{1,2})\b', raw_val)
        if count_match:
            try:
                target_count = int(count_match.group(1))
            except Exception:
                pass
        target_count = max(1, min(target_count, 25))

        # Retrieve candidate items
        items = [dict(it) for it in self._last_extracted_items if it.get("url")]
        if len(items) < target_count:
            # Try in-page extraction to fill up to target_count
            extracted = await self._extract_page_products_or_items(limit=target_count)
            seen_urls = {it.get("url") for it in items}
            for it in extracted:
                if it.get("url") and it.get("url") not in seen_urls:
                    items.append(dict(it))
                    seen_urls.add(it.get("url"))

        # Fallback: if items list is still empty, scrape any product links on the current search page
        if not items:
            raw_links = await page.evaluate("""
                () => {
                    const links = [];
                    const seen = new Set();
                    document.querySelectorAll('a[href*="/dp/"], a[href*="/p/"]').forEach(a => {
                        let h = a.getAttribute('href') || '';
                        if (h.startsWith('/')) h = window.location.origin + h;
                        const t = a.textContent.trim();
                        if (h.startsWith('http') && !seen.has(h) && t.length > 5) {
                            seen.add(h);
                            links.push({ title: t, price: 'N/A', price_num: 0, url: h, rating: '' });
                        }
                    });
                    return links.slice(0, 25);
                }
            """)
            if raw_links:
                items = raw_links

        target_items = items[:target_count]
        actual_total = len(target_items)
        if actual_total == 0:
            raise RuntimeError("No product links found on the page to add to cart.")

        logger.info(f"[M5] Beginning multi-item cart flow for {actual_total} items (target={target_count})")
        self._emit_status("action", f"🛒 Beginning multi-item cart flow for {actual_total} products...")

        add_cart_selectors = [
            "#desktop_qualifiedBuyBox #add-to-cart-button",
            "#buybox #add-to-cart-button",
            "#desktop_qualifiedBuyBox input[name='submit.add-to-cart']",
            "#add-to-cart-button",
            "input#add-to-cart-button",
            "#add-to-cart-button-ubb",
            "button#add-to-cart-button",
            "[name='submit.add-to-cart']",
            "button:has-text('Add to Cart')",
            "button:has-text('Add to cart')",
            "button:has-text('ADD TO CART')",
            "a:has-text('Add to Cart')",
            "a:has-text('ADD TO CART')",
            "._2KpZ6l._2U9uOA._3v1-ww",
            "button[class*='_2KpZ6l']",
            "[data-action='add-to-cart']",
        ]

        added_count = 0
        for idx, item in enumerate(target_items, 1):
            url = item.get("url")
            title_snippet = item.get("title", f"Product #{idx}")[:40]
            if not url:
                item["cart_status"] = "unavailable / out of stock"
                continue

            self._emit_status("action", f"🛒 [{idx}/{actual_total}] Opening '{title_snippet}...' in same tab", url)
            logger.info(f"[M5] [{idx}/{actual_total}] Navigating to: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as nav_err:
                logger.warning(f"[M5] Navigation to product {idx} had warning: {nav_err}")

            await asyncio.sleep(1.0)
            await self._dismiss_popups()

            # Record pre-click cart count
            prev_cart_count = 0
            try:
                c_str = await page.evaluate("() => document.querySelector('#nav-cart-count')?.innerText || ''")
                if c_str:
                    prev_cart_count = int(re.sub(r'\D', '', c_str))
            except Exception:
                prev_cart_count = added_count

            # Find the first VISIBLE Add to Cart button (avoids hidden trade-in inputs on Amazon)
            chosen_btn = None
            for s in add_cart_selectors:
                try:
                    loc = page.locator(s)
                    cnt = await loc.count()
                    for b_idx in range(cnt):
                        btn_cand = loc.nth(b_idx)
                        if await btn_cand.is_visible():
                            chosen_btn = btn_cand
                            break
                    if chosen_btn:
                        break
                except Exception:
                    continue

            if chosen_btn:
                try:
                    await self._click_resiliently(chosen_btn, timeout=4000)
                    await asyncio.sleep(1.5)
                except Exception as click_err:
                    logger.warning(f"[M5] Failed clicking add to cart for item {idx}: {click_err}")

            # Dismiss warranty / protection plan side sheets or modals (common on laptops)
            upsell_dismiss_selectors = [
                "#attachSiNoCoverage",
                "input[aria-labelledby='attachSiNoCoverage-announce']",
                "#attach-close_sideSheet-link",
                "#attach-sidesheet-close-button",
                "#attach-warranty-pane input[data-action='close']",
                "#attachSiNoCoverage-announce",
                "[aria-label='Close']",
            ]
            for u_sel in upsell_dismiss_selectors:
                try:
                    u_btn = page.locator(u_sel).first
                    if await u_btn.count() > 0 and await u_btn.is_visible():
                        await u_btn.click(timeout=1500)
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    pass

            # Verify addition via cart count increase or confirmation banner
            item_added = False

            # Check 1: Did #nav-cart-count increase?
            try:
                new_cart_str = await page.evaluate("() => document.querySelector('#nav-cart-count')?.innerText || ''")
                if new_cart_str:
                    new_count = int(re.sub(r'\D', '', new_cart_str))
                    if new_count > prev_cart_count:
                        item_added = True
                        logger.info(f"[M5] Item {idx}: Cart count increased from {prev_cart_count} to {new_count}")
            except Exception:
                pass

            # Check 2: Confirmation banner/message (ensuring it is not empty cart / sign-in screen)
            if not item_added:
                try:
                    has_confirm = await page.evaluate("""
                        () => {
                            const conf = document.querySelector('#NATC_SMART_WAGON_CONF_MSG_SUCCESS, #sw-atc-confirmation, .sw-atc-message, .a-size-medium-plus.a-color-base.sw-atc-text, #attach-added-to-cart-message');
                            if (conf && conf.offsetParent !== null) return true;
                            const bodyText = document.body ? document.body.innerText : '';
                            return (bodyText.includes('Added to Cart') || bodyText.includes('Added to Basket')) && !bodyText.includes('Your Amazon Cart is empty') && !bodyText.includes('Sign in to your account');
                        }
                    """)
                    if has_confirm:
                        item_added = True
                except Exception:
                    pass

            # Check 3: Smart wagon page if not empty
            if not item_added:
                curr_url = page.url or ""
                if ("smart-wagon" in curr_url or "sw-atc" in curr_url) and "gp/cart/view.html" not in curr_url:
                    item_added = True

            if item_added:
                item["cart_status"] = "added"
                added_count += 1
                self._emit_status("action", f"✅ [{idx}/{actual_total}] Added to cart: {title_snippet}")
                logger.info(f"[M5] [{idx}/{actual_total}] Successfully added to cart: {title_snippet}")
            else:
                item["cart_status"] = "unavailable / out of stock"
                self._emit_status("action", f"⚠️ [{idx}/{actual_total}] Out of stock or buy box missing")
                logger.warning(f"[M5] [{idx}/{actual_total}] Could not add to cart (out of stock/missing buy box)")

        # Navigate to the platform's cart page in the SAME tab so user sees all items
        try:
            curr_url = page.url or ""
            if "amazon" in curr_url.lower():
                await page.goto("https://www.amazon.in/gp/cart/view.html", wait_until="domcontentloaded", timeout=15000)
            elif "flipkart" in curr_url.lower():
                await page.goto("https://www.flipkart.com/viewcart", wait_until="domcontentloaded", timeout=15000)
            else:
                cart_btn = page.locator("#nav-cart, a[href*='/cart'], button[class*='cart']").first
                if await cart_btn.count() > 0:
                    await self._click_resiliently(cart_btn, timeout=3000)
        except Exception as cart_nav_err:
            logger.warning(f"[M5] Navigating to cart page after completion: {cart_nav_err}")

        # Cross-verify with final cart count if available
        try:
            final_count_str = await page.evaluate("() => document.querySelector('#nav-cart-count')?.innerText || ''")
            if final_count_str:
                final_count = int(re.sub(r'\D', '', final_count_str))
                if final_count > 0:
                    added_count = max(added_count, min(final_count, actual_total))
        except Exception:
            pass

        # Update cache so UI has full item status list
        self._last_extracted_items = target_items

        # Calculate exact percentage
        completion_pct = int((added_count / actual_total) * 100) if actual_total > 0 else 0
        summary_msg = f"Added {added_count} of {actual_total} items to cart ({completion_pct}% completed)"
        action.value = summary_msg

        logger.info(f"[M5] Multi-item cart flow finished: {summary_msg}")
        if added_count == actual_total:
            self._emit_status("action_completed", f"🎉 All {actual_total} items added to cart (100% completed)!")
        elif added_count > 0:
            self._emit_status("action_partial", f"⚠️ Added {added_count} of {actual_total} items to cart ({completion_pct}% completed)")
        else:
            raise RuntimeError(f"Could not add any of the {actual_total} items to cart (items may be out of stock).")

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
            # Preserve self._last_extracted_items so downstream steps and UI retain the items
        elif page and not page.is_closed() and any(k in (url or "").lower() for k in ("search", "s?", "/p/", "/dp/", "results", "query")):
            try:
                extracted_items = await self._extract_page_products_or_items()
                if extracted_items:
                    direct_link = extracted_items[0].get("url")
                    self._last_extracted_items = extracted_items
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
