"""
test_verifier.py — Unit tests for Module 8 (Verifier)

Validates multi-check verification: error page detection, URL change checks,
extract content non-emptiness, empty element heuristic, and LLM semantic fallbacks.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.models import (
    ActionObject, GoalObject, InteractiveElement, PageState,
    StrategyContext, SubTask, VerificationResult
)
from agent_framework.modules.verifier import Verifier
from agent_framework.config import AgentConfig


@pytest.fixture
def config():
    return AgentConfig()


@pytest.fixture
def verifier(config):
    return Verifier(config)


@pytest.fixture
def sample_goal():
    return GoalObject(
        task_type="product_search",
        domain="laptops",
        constraints={"price_max": 60000},
        output_format="comparison_table",
        success_criteria="find laptops",
    )


@pytest.fixture
def sample_subtask():
    return SubTask(step=1, type="navigate", goal="Navigate to Flipkart")


@pytest.fixture
def sample_strategy():
    return StrategyContext(strategy_id="dynamic")


def test_verifier_detects_error_page_as_failure(verifier, sample_goal, sample_subtask, sample_strategy):
    """Verifier must flag 404/Error titles as hard failure via rule check without LLM call."""
    action = ActionObject(action="navigate", value="https://example.com/missing")
    page = PageState(
        url="https://example.com/missing",
        title="404 Not Found - Error Page",
        interactive_elements=[],
    )

    result, tokens = asyncio.run(verifier.verify(
        sample_goal, sample_subtask, action, page, None, sample_strategy
    ))

    assert result.status == "failure"
    assert "404" in result.reason or "Error" in result.reason
    assert result.confidence_score >= 0.9
    assert tokens == 0


def test_verifier_detects_failed_navigation_when_url_unchanged(
    verifier, sample_goal, sample_subtask, sample_strategy
):
    """When a navigate action leaves URL unchanged, rule check flags failure."""
    prev_page = PageState(url="https://store.com/home", title="Home", interactive_elements=[])
    curr_page = PageState(url="https://store.com/home", title="Home", interactive_elements=[])
    action = ActionObject(action="navigate", value="https://store.com/laptops")

    result, tokens = asyncio.run(verifier.verify(
        sample_goal, sample_subtask, action, curr_page, prev_page, sample_strategy
    ))

    assert result.status == "failure"
    assert "URL did not change" in result.reason
    assert tokens == 0


def test_verifier_detects_successful_extract(
    verifier, sample_goal, sample_strategy
):
    """Extract action with populated text content returns success."""
    subtask = SubTask(step=4, type="extract", goal="Extract laptop specifications")
    action = ActionObject(
        action="extract",
        value='{"item": "Asus Vivobook 15", "price": 49990, "ram": "16GB"}'
    )
    page = PageState(
        url="https://store.com/p/123",
        title="Asus Vivobook 15 Specs",
        interactive_elements=[InteractiveElement(id="e1", role="button", label="Buy Now")],
    )

    result, tokens = asyncio.run(verifier.verify(
        sample_goal, subtask, action, page, None, sample_strategy
    ))

    assert result.status == "success"
    assert "Data extracted" in result.reason
    assert tokens == 0


def test_verifier_llm_semantic_fallback(
    verifier, sample_goal, sample_strategy
):
    """When rules pass to LLM, verifier calls LLM and parses JSON VerificationResult."""
    subtask = SubTask(step=2, type="filter", goal="Apply 16GB RAM filter")
    action = ActionObject(action="click", selector="e2")
    prev_page = PageState(url="https://store.com/laptops", title="Laptops", interactive_elements=[])
    curr_page = PageState(
        url="https://store.com/laptops?ram=16gb",
        title="Laptops with 16GB RAM",
        interactive_elements=[InteractiveElement(id="e1", role="button", label="Next")],
    )

    mock_llm_ver = {
        "status": "success",
        "reason": "16GB RAM filter checkbox is checked and listings updated",
        "expected_outcome": "16GB filter applied",
        "confidence_score": 0.92,
    }
    with patch.object(
        verifier.llm,
        "complete",
        AsyncMock(return_value=(json.dumps(mock_llm_ver), 95))
    ):
        result, tokens = asyncio.run(verifier.verify(
            sample_goal, subtask, action, curr_page, prev_page, sample_strategy
        ))

    assert result.status == "success"
    assert result.confidence_score == 0.92
    assert tokens == 95
