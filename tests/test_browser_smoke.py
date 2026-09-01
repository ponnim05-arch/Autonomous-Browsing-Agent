"""
Smoke test for BrowserExecutor with real local browser.
Can be executed when a browser (Chromium, Edge, or Chrome) is installed.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.config import AgentConfig
from agent_framework.models import ActionObject
from agent_framework.modules.browser_executor import BrowserExecutor


@pytest.mark.asyncio
async def test_real_browser_smoke_navigation():
    """Verify that BrowserExecutor can launch a real browser and navigate to about:blank or data url."""
    config = AgentConfig(browser_type="chromium", headless=True)
    async with BrowserExecutor(config) as browser:
        # Navigate to a lightweight local data url
        action = ActionObject(action="navigate", value="about:blank")
        res = await browser.execute(action, run_id="smoke_test", step_index=0, screenshot=False)

        assert res["action_success"] is True
        assert "about:blank" in res["url"]
        assert isinstance(res["accessibility_tree"], dict)
