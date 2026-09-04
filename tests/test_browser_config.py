"""
Comprehensive tests for BrowserExecutor lifecycle, fallbacks, recovery, CDP mode,
browser modes (visible/headless/cdp), status callbacks, keep_browser_open,
is_alive property, and error diagnostics.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.config import AgentConfig
from agent_framework.models import ActionObject
from agent_framework.modules.browser_executor import (
    BrowserExecutor,
    BrowserError,
    BrowserBlockedError,
    BrowserNotStartedError,
    BrowserStartupError,
)


def _create_mock_playwright():
    """Helper to create a fully wired mock Playwright hierarchy."""
    mock_pw = MagicMock()
    mock_browser = AsyncMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.url = "https://example.com"
    mock_page.title = AsyncMock(return_value="Example Domain")
    mock_page.accessibility = MagicMock()
    mock_page.accessibility.snapshot = AsyncMock(return_value={"role": "WebArea", "name": "Example Domain"})
    mock_page.screenshot = AsyncMock()

    mock_pw.chromium = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()
    mock_browser.close = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    mock_page.close = AsyncMock()

    return mock_pw, mock_browser, mock_context, mock_page


# 1. Initialization and Diagnostics
def test_browser_executor_diagnostics():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    diag = BrowserExecutor.get_diagnostics(config)

    assert "python_executable" in diag
    assert "agent_framework_path" in diag
    assert "playwright_available" in diag
    assert diag["browser_type"] == "chromium"
    assert diag["headless"] is True
    assert diag["browser_connection_mode"] == "playwright"
    assert diag["browser_mode"] == "headless"
    assert "keep_browser_open" in diag


# 2. Context manager starts and stops cleanly
@pytest.mark.asyncio
async def test_browser_executor_context_manager_lifecycle():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            assert executor._is_started is True
            assert executor._page == mock_page
            assert executor._context == mock_context
            assert executor._browser == mock_browser

        # After exiting context manager, all resources must be released
        assert executor._is_started is False
        assert executor._page is None
        assert executor._context is None
        assert executor._browser is None
        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()


# 3. Execution works after startup
@pytest.mark.asyncio
async def test_browser_executor_execute_action_success():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    mock_element = AsyncMock()
    mock_element.wait_for = AsyncMock()
    mock_element.click = AsyncMock()
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_element))

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            action = ActionObject(action="click", selector="#submit-button")
            result = await executor.execute(action, run_id="test_run", step_index=0, screenshot=False)

            assert result["action_success"] is True
            assert result["url"] == "https://example.com"
            assert result["title"] == "Example Domain"
            mock_element.click.assert_called_once()


# 4. execute() raises BrowserNotStartedError when called outside context manager
@pytest.mark.asyncio
async def test_browser_executor_execute_without_start_raises_error():
    config = AgentConfig()
    executor = BrowserExecutor(config)

    with pytest.raises(BrowserNotStartedError, match="BrowserExecutor not started"):
        await executor.execute(ActionObject(action="navigate", value="https://example.com"))


# 5. execute() sets action_success=False on element not found or unknown action
@pytest.mark.asyncio
async def test_browser_executor_handles_missing_element_gracefully():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    # Locator throws timeout on wait_for
    mock_el = MagicMock()
    mock_el.wait_for = AsyncMock(side_effect=Exception("Element timed out"))
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_el))
    mock_page.get_by_text = MagicMock(return_value=MagicMock(first=mock_el))
    mock_page.get_by_role = MagicMock(return_value=MagicMock(first=mock_el))

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            action = ActionObject(action="click", selector="non_existent_btn")
            result = await executor.execute(action, run_id="test_run", step_index=1, screenshot=False)

            assert result["action_success"] is False
            assert "action_error" in result


# 6. Fallback order for Edge and Chrome
@pytest.mark.asyncio
async def test_browser_executor_fallback_to_edge_and_chrome():
    config = AgentConfig(browser_type="msedge", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    # Edge launch succeeds directly
    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            mock_pw.chromium.launch.assert_called_once()
            _, kwargs = mock_pw.chromium.launch.call_args
            assert kwargs.get("channel") == "msedge"


# 7. Fallback when primary launch fails
@pytest.mark.asyncio
async def test_browser_executor_cascading_fallback():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    # First attempt (Bundled) fails, second attempt (Edge) succeeds
    mock_pw.chromium.launch = AsyncMock(
        side_effect=[Exception("Bundled chromium not found"), mock_browser]
    )

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            assert executor._is_started is True
            assert mock_pw.chromium.launch.call_count == 2


# 8. BrowserStartupError raised when all launchers fail
@pytest.mark.asyncio
async def test_browser_executor_all_launchers_fail_raises_startup_error():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    # All launch attempts fail
    mock_pw.chromium.launch = AsyncMock(side_effect=Exception("Browser binary missing"))

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        with pytest.raises(BrowserStartupError) as exc_info:
            async with BrowserExecutor(config):
                pass

        assert "Failed to launch browser" in str(exc_info.value)
        assert exc_info.value.diagnostics["browser_type"] == "chromium"


# 9. Page closed recovery
@pytest.mark.asyncio
async def test_browser_executor_page_closed_recovery():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    new_mock_page = AsyncMock()
    new_mock_page.is_closed = MagicMock(return_value=False)
    new_mock_page.url = "https://recovered.com"
    new_mock_page.title = AsyncMock(return_value="Recovered Page")
    new_mock_page.accessibility = MagicMock()
    new_mock_page.accessibility.snapshot = AsyncMock(return_value={})
    mock_context.new_page = AsyncMock(return_value=new_mock_page)

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            # Simulate page being closed by user
            executor._page.is_closed = MagicMock(return_value=True)

            action = ActionObject(action="wait", value="0.1")
            result = await executor.execute(action, run_id="test_run", step_index=2, screenshot=False)

            assert result["action_success"] is True
            assert executor._page == new_mock_page


# 10. CDP Connection Mode
@pytest.mark.asyncio
async def test_browser_executor_cdp_mode():
    config = AgentConfig(browser_connection_mode="cdp", cdp_endpoint="http://127.0.0.1:9222", browser_mode="cdp")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()
    mock_browser.contexts = [mock_context]
    mock_context.pages = [mock_page]

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            assert executor._is_cdp is True
            mock_pw.chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:9222")


# 11. Safety Blocklist
@pytest.mark.asyncio
async def test_browser_executor_safety_blocklist():
    config = AgentConfig(block_purchase_urls=["checkout", "payment"])
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            with pytest.raises(BrowserBlockedError, match="matches blocked pattern 'checkout'"):
                await executor.execute(
                    ActionObject(action="navigate", value="https://store.com/checkout/confirm"),
                    run_id="test_run",
                )


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS — Browser Display Feature
# ══════════════════════════════════════════════════════════════════════════════

# 12. Visible browser mode sets headless=False
def test_visible_mode_sets_headless_false():
    config = AgentConfig(browser_mode="visible")
    assert config.headless is False
    assert config.browser_connection_mode == "playwright"


# 13. Headless browser mode sets headless=True
def test_headless_mode_sets_headless_true():
    config = AgentConfig(browser_mode="headless")
    assert config.headless is True
    assert config.browser_connection_mode == "playwright"


# 14. CDP mode sets browser_connection_mode=cdp
def test_cdp_mode_sets_connection_mode():
    config = AgentConfig(browser_mode="cdp")
    assert config.browser_connection_mode == "cdp"
    assert config.headless is False


# 15. Status callback fires during lifecycle
@pytest.mark.asyncio
async def test_status_callback_fires_during_lifecycle():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    events = []

    def capture_callback(event, message, url=None):
        events.append((event, message, url))

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config, status_callback=capture_callback) as executor:
            assert any(e[0] == "browser_starting" for e in events), "browser_starting event not fired"
            assert any(e[0] == "browser_started" for e in events), "browser_started event not fired"

    # After exit, browser_stopping / browser_stopped should fire
    assert any(e[0] == "browser_stopping" for e in events), "browser_stopping event not fired"
    assert any(e[0] == "browser_stopped" for e in events), "browser_stopped event not fired"


# 16. Status callback fires on action execution
@pytest.mark.asyncio
async def test_status_callback_fires_on_actions():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=None)
    mock_context.pages = []

    events = []

    def capture_callback(event, message, url=None):
        events.append((event, message, url))

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config, status_callback=capture_callback) as executor:
            action = ActionObject(action="navigate", value="https://example.com")
            await executor.execute(action, run_id="test_run", step_index=0, screenshot=False)

    # Should have navigating event
    nav_events = [e for e in events if e[0] == "navigating"]
    assert len(nav_events) >= 1, "navigating event not fired"
    assert "example.com" in nav_events[0][1]


# 17. keep_browser_open prevents browser close
@pytest.mark.asyncio
async def test_keep_browser_open_prevents_close():
    config = AgentConfig(
        browser_type="chromium", headless=True,
        browser_mode="headless", keep_browser_open=True
    )
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            assert executor._is_started is True

        # Browser.close() should NOT have been called
        mock_browser.close.assert_not_called()
        # Page.close() should NOT have been called
        mock_page.close.assert_not_called()
        # But playwright.stop() should still be called to release Python resources
        mock_pw.stop.assert_called_once()


# 18. is_alive property works correctly
@pytest.mark.asyncio
async def test_is_alive_property():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        executor = BrowserExecutor(config)

        # Before start, is_alive should be False
        assert executor.is_alive is False

        async with executor:
            # After start, is_alive should be True
            assert executor.is_alive is True

            # Simulate page close
            mock_page.is_closed = MagicMock(return_value=True)
            assert executor.is_alive is False

            # Simulate browser disconnect
            mock_page.is_closed = MagicMock(return_value=False)
            mock_browser.is_connected = MagicMock(return_value=False)
            assert executor.is_alive is False


# 19. current_url property
@pytest.mark.asyncio
async def test_current_url_property():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        executor = BrowserExecutor(config)
        assert executor.current_url == ""

        async with executor:
            assert executor.current_url == "https://example.com"


# 20. Duplicate browser prevention (start() is idempotent)
@pytest.mark.asyncio
async def test_duplicate_browser_prevention():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            assert executor._is_started is True
            # Calling start() again should not create a new browser
            await executor.start()
            # launch should only have been called once
            assert mock_pw.chromium.launch.call_count == 1


# 21. Missing Chromium gives useful error with suggested fix
@pytest.mark.asyncio
async def test_missing_chromium_useful_error():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, _, _, _ = _create_mock_playwright()

    # All launch attempts fail with "executable doesn't exist"
    mock_pw.chromium.launch = AsyncMock(
        side_effect=Exception("Executable doesn't exist at /path/chromium")
    )

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        with pytest.raises(BrowserStartupError) as exc_info:
            async with BrowserExecutor(config):
                pass

        assert "playwright install" in exc_info.value.suggested_fix.lower()
        assert exc_info.value.diagnostics["browser_type"] == "chromium"


# 22. CDP failure gives useful error
@pytest.mark.asyncio
async def test_cdp_failure_useful_error():
    config = AgentConfig(browser_mode="cdp", cdp_endpoint="http://127.0.0.1:9222")
    mock_pw, _, _, _ = _create_mock_playwright()

    mock_pw.chromium.connect_over_cdp = AsyncMock(
        side_effect=Exception("Connection refused")
    )

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        with pytest.raises(BrowserStartupError) as exc_info:
            async with BrowserExecutor(config):
                pass

        assert "CDP" in str(exc_info.value) or "cdp" in str(exc_info.value).lower()
        assert "9222" in str(exc_info.value)


# 23. Browser mode appears in diagnostics
def test_browser_mode_in_diagnostics():
    config = AgentConfig(browser_mode="visible")
    diag = BrowserExecutor.get_diagnostics(config)
    assert diag["browser_mode"] == "visible"
    assert diag["headless"] is False


# 24. Status callback error doesn't crash execution
@pytest.mark.asyncio
async def test_status_callback_error_doesnt_crash():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    def crashing_callback(event, message, url=None):
        raise RuntimeError("Callback crashed!")

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        # Should not raise despite callback crashing
        async with BrowserExecutor(config, status_callback=crashing_callback) as executor:
            assert executor._is_started is True


# 25. Visible mode uses --start-maximized and no_viewport
@pytest.mark.asyncio
async def test_visible_mode_maximized_window():
    config = AgentConfig(browser_type="chromium", browser_mode="visible")
    assert config.headless is False

    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            # Check that launch was called with --start-maximized
            launch_call = mock_pw.chromium.launch.call_args
            args_list = launch_call.kwargs.get("args", [])
            assert "--start-maximized" in args_list

            # Check that new_context was called with no_viewport=True
            ctx_call = mock_browser.new_context.call_args
            assert ctx_call.kwargs.get("no_viewport") is True


# 26. Headless mode uses fixed viewport
@pytest.mark.asyncio
async def test_headless_mode_fixed_viewport():
    config = AgentConfig(browser_type="chromium", browser_mode="headless")
    assert config.headless is True

    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            # Check that launch was called WITHOUT --start-maximized
            launch_call = mock_pw.chromium.launch.call_args
            args_list = launch_call.kwargs.get("args", [])
            assert "--start-maximized" not in args_list

            # Check that new_context was called with viewport
            ctx_call = mock_browser.new_context.call_args
            assert ctx_call.kwargs.get("viewport") == {"width": 1366, "height": 768}


# 27. Page navigation works correctly
@pytest.mark.asyncio
async def test_page_navigation_works():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_context.pages = []

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            action = ActionObject(action="navigate", value="https://www.google.com")
            result = await executor.execute(action, run_id="test_run", step_index=0, screenshot=False)

            assert result["action_success"] is True
            mock_page.goto.assert_called()
            # Verify the URL was passed correctly
            call_args = mock_page.goto.call_args
            assert "google.com" in call_args[0][0]


# 28. Final URL correctly reported
@pytest.mark.asyncio
async def test_final_url_correctly_reported():
    config = AgentConfig(browser_type="chromium", headless=True, browser_mode="headless")
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    mock_page.url = "https://www.google.com/search?q=python"

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            action = ActionObject(action="wait", value="0.01")
            result = await executor.execute(action, run_id="test_run", step_index=0, screenshot=False)

            assert result["url"] == "https://www.google.com/search?q=python"
            assert executor.current_url == "https://www.google.com/search?q=python"
