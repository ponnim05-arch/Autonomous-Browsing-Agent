"""
test_task_decomposer.py — Unit tests for Module 2 (TaskDecomposer)

Validates sub-task list generation, step ordering, verify-step enforcement,
and fallback logic for malformed LLM outputs.
All LLM calls are mocked.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.models import GoalObject, SubTask
from agent_framework.modules.task_decomposer import TaskDecomposer
from agent_framework.config import AgentConfig


@pytest.fixture
def config():
    return AgentConfig(max_subtasks_per_task=6)


@pytest.fixture
def decomposer(config):
    return TaskDecomposer(config)


@pytest.fixture
def sample_goal():
    return GoalObject(
        task_type="product_search",
        domain="laptops",
        constraints={"price_max": 60000, "ram_gb": 16},
        output_format="comparison_table",
        success_criteria="return top 5 results ranked by price",
    )


def test_task_decomposer_successful_decomposition(decomposer, sample_goal):
    """Decomposer should return ordered SubTask objects with verify as final step."""
    mock_subtasks = [
        {"step": 1, "type": "search", "goal": "Search for laptops under 60000 with 16GB RAM"},
        {"step": 2, "type": "navigate", "goal": "Open top result on e-commerce store"},
        {"step": 3, "type": "filter", "goal": "Apply price and RAM filters"},
        {"step": 4, "type": "extract", "goal": "Extract names, prices and specs"},
        {"step": 5, "type": "compare", "goal": "Rank extracted laptops"},
        {"step": 6, "type": "verify", "goal": "Verify data completeness"},
    ]
    with patch.object(
        decomposer.llm,
        "complete",
        AsyncMock(return_value=(json.dumps(mock_subtasks), 150))
    ):
        result = asyncio.run(decomposer.decompose(sample_goal))

    assert len(result) == 6
    assert all(isinstance(st, SubTask) for st in result)
    assert [st.step for st in result] == [1, 2, 3, 4, 5, 6]
    assert result[-1].type == "verify"
    assert result[0].type == "search"


def test_task_decomposer_enforces_verify_last_step(decomposer, sample_goal):
    """If LLM forgets to include 'verify', decomposer appends it automatically."""
    mock_subtasks = [
        {"step": 1, "type": "search", "goal": "Search on Google"},
        {"step": 2, "type": "extract", "goal": "Extract page text"},
    ]
    with patch.object(
        decomposer.llm,
        "complete",
        AsyncMock(return_value=(json.dumps(mock_subtasks), 80))
    ):
        result = asyncio.run(decomposer.decompose(sample_goal))

    assert len(result) == 3
    assert result[-1].type == "verify"
    assert result[-1].step == 3


def test_task_decomposer_fallback_on_non_json(decomposer, sample_goal):
    """Decomposer must fall back to basic 3-step plan when LLM output is malformed."""
    with patch.object(
        decomposer.llm,
        "complete",
        AsyncMock(return_value=("Sorry, I cannot decompose this.", 20))
    ):
        result = asyncio.run(decomposer.decompose(sample_goal))

    assert len(result) == 3
    assert result[0].type == "search"
    assert result[1].type == "extract"
    assert result[2].type == "verify"
    assert result[-1].step == 3
