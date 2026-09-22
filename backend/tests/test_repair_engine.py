"""
test_repair_engine.py — Unit tests for Module 9 (RepairEngine)

Validates repair strategy suggestions (selector repair, goal reframing,
alternative path), hard max-retry sub-task skipping, and malformed JSON recovery.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.models import (
    ActionObject, InteractiveElement, PageState, RepairAmendment, RepairInput
)
from agent_framework.modules.repair_engine import RepairEngine
from agent_framework.config import AgentConfig


@pytest.fixture
def config():
    return AgentConfig(max_retries_per_subtask=3)


@pytest.fixture
def repair_engine(config):
    return RepairEngine(config)


@pytest.fixture
def sample_page():
    return PageState(
        url="https://store.com/results",
        title="Search Results",
        interactive_elements=[
            InteractiveElement(id="e1", role="button", label="Add to Cart"),
            InteractiveElement(id="e2", role="link", label="Next Page"),
        ],
    )


def test_repair_engine_selector_repair(repair_engine, sample_page):
    """RepairEngine parses LLM selector_repair suggestion correctly."""
    repair_in = RepairInput(
        original_goal="Click Add to Cart button",
        failed_action=ActionObject(action="click", selector="e99"),
        failure_reason="Element e99 not found",
        current_page_state=sample_page,
        attempt_number=1,
    )

    mock_amendment = {
        "amendment_type": "selector_repair",
        "corrective_instruction": "Target element e1 which has label 'Add to Cart'",
        "new_strategy": "failure_recovery",
        "retry_count": 1,
    }
    with patch.object(
        repair_engine.llm,
        "complete",
        AsyncMock(return_value=(json.dumps(mock_amendment), 110))
    ):
        amendment, tokens = asyncio.run(repair_engine.repair(repair_in))

    assert isinstance(amendment, RepairAmendment)
    assert amendment.amendment_type == "selector_repair"
    assert "e1" in amendment.corrective_instruction
    assert amendment.retry_count == 1
    assert tokens == 110


def test_repair_engine_skips_when_max_retries_exceeded(repair_engine, sample_page):
    """When attempt_number >= max_retries_per_subtask, engine returns sub_task_skip without LLM call."""
    repair_in = RepairInput(
        original_goal="Click impossible button",
        failed_action=ActionObject(action="click", selector="e5"),
        failure_reason="Element remains missing after 3 attempts",
        current_page_state=sample_page,
        attempt_number=3,  # matches max_retries_per_subtask=3
    )

    amendment, tokens = asyncio.run(repair_engine.repair(repair_in))

    assert amendment.amendment_type == "sub_task_skip"
    assert "exceeded the maximum retry limit" in amendment.corrective_instruction
    assert tokens == 0


def test_repair_engine_fallback_on_invalid_json(repair_engine, sample_page):
    """If LLM returns unparseable text, repair engine returns fallback goal_reframing amendment."""
    repair_in = RepairInput(
        original_goal="Filter by 16GB",
        failed_action=ActionObject(action="click", selector="e2"),
        failure_reason="Click timed out",
        current_page_state=sample_page,
        attempt_number=1,
    )

    with patch.object(
        repair_engine.llm,
        "complete",
        AsyncMock(return_value=("Invalid non-JSON response from LLM", 20))
    ):
        amendment, tokens = asyncio.run(repair_engine.repair(repair_in))

    assert isinstance(amendment, RepairAmendment)
    assert amendment.amendment_type == "goal_reframing"
    assert amendment.new_strategy == "failure_recovery"
    assert amendment.retry_count == 1
