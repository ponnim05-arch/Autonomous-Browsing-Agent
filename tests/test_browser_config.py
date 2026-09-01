import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.config import AgentConfig
from agent_framework.modules.browser_executor import BrowserExecutor


def test_browser_executor_launches_msedge():
    config = AgentConfig(browser_type="msedge", headless=True)
    executor = BrowserExecutor(config)

    mock_pw = MagicMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    mock_pw.chromium = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()
    mock_browser.close = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_playwright_fn:
        mock_playwright_fn.return_value.start = AsyncMock(return_value=mock_pw)

        asyncio.run(executor.start())

        mock_pw.chromium.launch.assert_called_once()
        _, kwargs = mock_pw.chromium.launch.call_args
        assert kwargs.get("channel") == "msedge"
        assert kwargs.get("headless") is True
        assert executor._page == mock_page
        assert executor._context == mock_context

        asyncio.run(executor.stop())
