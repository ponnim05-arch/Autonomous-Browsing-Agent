"""
tests/test_extraction.py — Unit tests for product/link extraction and semantic resolution.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.config import AgentConfig
from agent_framework.models import ActionObject, PageState
from agent_framework.modules.browser_executor import BrowserExecutor
from agent_framework.modules.verifier import Verifier


def _create_mock_playwright():
    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.url = "https://www.amazon.in/s?k=laptops"
    mock_page.title = AsyncMock(return_value="Amazon.in : laptops")
    mock_page.accessibility.snapshot = AsyncMock(return_value={"role": "WebArea", "name": "Amazon"})
    mock_page.screenshot = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.keyboard.press = AsyncMock()
    mock_page.close = AsyncMock()

    return mock_pw, mock_browser, mock_context, mock_page


@pytest.mark.asyncio
async def test_extract_products_and_direct_links():
    config = AgentConfig(browser_type="chromium", headless=True)
    mock_pw, mock_browser, mock_context, mock_page = _create_mock_playwright()

    sample_products = [
        {
            "title": "HP 15s 12th Gen Intel Core i5 Laptop",
            "price": "₹52,990",
            "price_num": 52990.0,
            "url": "https://www.amazon.in/dp/B0CX21C27F",
            "rating": "4.2 out of 5",
        },
        {
            "title": "Lenovo IdeaPad Slim 3 16GB RAM",
            "price": "₹48,490",
            "price_num": 48490.0,
            "url": "https://www.amazon.in/dp/B0B4N7X3Y2",
            "rating": "4.1 out of 5",
        },
    ]

    mock_page.evaluate.return_value = sample_products

    with patch("agent_framework.modules.browser_executor.async_playwright") as mock_pw_fn:
        mock_pw_fn.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserExecutor(config) as executor:
            action = ActionObject(action="extract", selector="cheapest_product", value="cheapest")
            raw_state = await executor.execute(action, run_id="test_extract", step_index=1, screenshot=False)

            assert raw_state["action_success"] is True
            # Sorted by price ascending (48490 < 52990)
            items = raw_state["extracted_items"]
            assert len(items) == 2
            assert items[0]["price_num"] == 48490.0
            assert items[0]["url"] == "https://www.amazon.in/dp/B0B4N7X3Y2"
            assert raw_state["direct_link"] == "https://www.amazon.in/dp/B0B4N7X3Y2"


@pytest.mark.asyncio
async def test_verifier_accepts_extracted_products():
    config = AgentConfig()
    verifier = Verifier(config)

    page_state = PageState(
        url="https://www.amazon.in/s?k=laptops",
        title="Amazon.in : laptops",
        extracted_items=[
            {
                "title": "Lenovo IdeaPad Slim 3 16GB RAM",
                "price": "₹48,490",
                "url": "https://www.amazon.in/dp/B0B4N7X3Y2",
            }
        ],
        direct_link="https://www.amazon.in/dp/B0B4N7X3Y2",
    )

    action = ActionObject(action="extract", selector="cheapest_product")
    result = verifier._rule_based_check(action, page_state, None)

    assert result is not None
    assert result.status == "success"
    assert "https://www.amazon.in/dp/B0B4N7X3Y2" in result.reason
