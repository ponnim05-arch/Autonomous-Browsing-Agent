"""
test_intent_parser.py — Unit tests for Module 1 (IntentParser)

Tests 10 diverse natural-language goals across different task types.
All LLM calls are mocked — no real API key or external pytest plugins required.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.models import GoalObject
from agent_framework.modules.intent_parser import IntentParser
from agent_framework.config import AgentConfig


@pytest.fixture
def config():
    return AgentConfig()


@pytest.fixture
def parser(config):
    return IntentParser(config)


def _mock_llm(json_data: dict):
    return AsyncMock(return_value=(json.dumps(json_data), 120))


GOALS = [
    (
        "Find the cheapest laptop under Rs.60,000 with 16GB RAM",
        {"task_type": "product_search", "domain": "laptops",
         "constraints": {"price_max": 60000, "ram_gb": 16, "currency": "INR"},
         "output_format": "comparison_table",
         "success_criteria": "top 5 results by price"},
    ),
    (
        "Compare iPhone 15 Pro price on Amazon and Flipkart",
        {"task_type": "price_comparison", "domain": "smartphones",
         "constraints": {"model": "iPhone 15 Pro"},
         "output_format": "comparison_table",
         "success_criteria": "price from both sites"},
    ),
    (
        "Find Python asyncio documentation",
        {"task_type": "documentation_search", "domain": "python_programming",
         "constraints": {"topic": "asyncio"},
         "output_format": "summary_with_link",
         "success_criteria": "return docs URL"},
    ),
    (
        "Search for mechanical keyboards under $150",
        {"task_type": "product_search", "domain": "keyboards",
         "constraints": {"price_max": 150, "currency": "USD"},
         "output_format": "list",
         "success_criteria": "list keyboards under $150"},
    ),
    (
        "Navigate to React documentation for hooks",
        {"task_type": "navigation", "domain": "web_development",
         "constraints": {"topic": "hooks", "framework": "React"},
         "output_format": "summary_with_link",
         "success_criteria": "reach hooks documentation page"},
    ),
    (
        "Find top 3 news articles about AI in 2025",
        {"task_type": "data_extraction", "domain": "news",
         "constraints": {"topic": "AI", "year": 2025, "count": 3},
         "output_format": "list",
         "success_criteria": "3 recent AI news articles"},
    ),
    (
        "What is the current price of gold per gram in India?",
        {"task_type": "data_extraction", "domain": "commodity_prices",
         "constraints": {"commodity": "gold", "unit": "gram", "country": "India"},
         "output_format": "text",
         "success_criteria": "return current gold price per gram"},
    ),
    (
        "Book a flight from Delhi to Mumbai next Friday",
        {"task_type": "other", "domain": "travel",
         "constraints": {"from": "Delhi", "to": "Mumbai", "day": "Friday"},
         "output_format": "text",
         "success_criteria": "find available flights"},
    ),
    (
        "Extract product specs from Samsung S24 Ultra page",
        {"task_type": "data_extraction", "domain": "smartphones",
         "constraints": {"model": "Samsung S24 Ultra"},
         "output_format": "raw_data",
         "success_criteria": "full spec sheet extracted"},
    ),
    (
        "Find internship opportunities for ML engineers in Bangalore",
        {"task_type": "product_search", "domain": "jobs",
         "constraints": {"role": "ML engineer", "type": "internship", "location": "Bangalore"},
         "output_format": "list",
         "success_criteria": "list relevant internship postings"},
    ),
]


@pytest.mark.parametrize("raw_goal,expected_json", GOALS)
def test_intent_parser_produces_valid_goal_object(parser, raw_goal, expected_json):
    """Parsed output must be a valid GoalObject with correct task_type and domain."""
    with patch.object(parser.llm, "complete", _mock_llm(expected_json)):
        result = asyncio.run(parser.parse(raw_goal))

    assert isinstance(result, GoalObject), "Result must be a GoalObject"
    assert result.task_type == expected_json["task_type"]
    assert result.domain == expected_json["domain"]
    assert isinstance(result.constraints, dict)
    assert isinstance(result.output_format, str)
    assert isinstance(result.success_criteria, str)


def test_intent_parser_fallback_on_invalid_json(parser):
    """Parser must return a fallback GoalObject when LLM returns non-JSON."""
    with patch.object(parser.llm, "complete", AsyncMock(return_value=("not valid json at all", 10))):
        result = asyncio.run(parser.parse("some goal"))

    assert isinstance(result, GoalObject)
    assert result.task_type == "other"
    assert result.domain == "general"


def test_intent_parser_fallback_on_empty_response(parser):
    """Parser must not raise on empty LLM response."""
    with patch.object(parser.llm, "complete", AsyncMock(return_value=("", 0))):
        result = asyncio.run(parser.parse("any goal"))
    assert isinstance(result, GoalObject)


def test_intent_parser_extracts_constraints(parser):
    """Constraints dict must be populated from the LLM response."""
    mock_data = {
        "task_type": "product_search",
        "domain": "laptops",
        "constraints": {"price_max": 60000, "ram_gb": 16},
        "output_format": "comparison_table",
        "success_criteria": "top results",
    }
    with patch.object(parser.llm, "complete", _mock_llm(mock_data)):
        result = asyncio.run(parser.parse("Find laptops"))
    assert result.constraints.get("price_max") == 60000
    assert result.constraints.get("ram_gb") == 16
