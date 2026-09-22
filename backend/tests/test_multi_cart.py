"""
Unit tests for multi-item cart task detection, planning, verification, and execution.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_framework.modules.unified_planner import (
    UnifiedPlanner,
    is_multi_cart_task,
    extract_clean_search_query,
)
from agent_framework.modules.verifier import Verifier
from agent_framework.config import AgentConfig
from agent_framework.models import ActionObject, PageState


def test_is_multi_cart_task_detection():
    # Multi-item cart query with 10 laptops
    is_multi, count = is_multi_cart_task(
        "search 10 best laptops under 75k gaming laptops with ryzen 7 processor in amazon and add them to cart"
    )
    assert is_multi is True
    assert count == 10

    # Multi-item cart query with top 5 keyboards
    is_multi, count = is_multi_cart_task(
        "find top 5 mechanical keyboards and add all to cart"
    )
    assert is_multi is True
    assert count == 5

    # Multi-item cart query with 3 books
    is_multi, count = is_multi_cart_task(
        "search 3 books on python in flipkart and add them to cart"
    )
    assert is_multi is True
    assert count == 3

    # Single item add to cart
    is_multi, count = is_multi_cart_task(
        "search cheapest laptop on amazon and add to cart"
    )
    assert is_multi is False
    assert count == 1

    # Search only without cart
    is_multi, count = is_multi_cart_task(
        "search 10 laptops under 60000"
    )
    assert is_multi is False
    assert count == 1


def test_extract_clean_search_query():
    raw_task = "search 10 best laptops under 75k gaming laptops with ryzen 7 processor in amazon and add them to cart"
    clean = extract_clean_search_query(raw_task)
    assert "add them to cart" not in clean.lower()
    assert "in amazon" not in clean.lower()
    assert "10 best" not in clean.lower()
    assert "gaming laptops" in clean.lower() or "ryzen 7" in clean.lower()


def test_planner_multi_item_fallback_plan():
    task = "search 10 best laptops under 75k gaming laptops with ryzen 7 processor in amazon and add them to cart"
    plan = UnifiedPlanner._fallback_plan(task)

    actions = [s.action for s in plan.steps]
    assert "extract" in actions
    assert "add_all_to_cart" in actions

    add_all_step = next(s for s in plan.steps if s.action == "add_all_to_cart")
    assert add_all_step.value == "10"
    assert add_all_step.checkpoint is True


def test_planner_parse_plan_enforces_multi_item_cart():
    planner = UnifiedPlanner(AgentConfig())
    task = "search 10 best laptops under 75k gaming laptops with ryzen 7 processor in amazon and add them to cart"

    # Suppose LLM naively returned a single-item plan
    single_item_llm_json = """
    {
        "task_type": "purchase",
        "domain": "amazon.in",
        "steps": [
            {"action": "navigate", "value": "https://www.amazon.in/", "checkpoint": false},
            {"action": "dismiss_popup", "target": "close_popup", "checkpoint": false},
            {"action": "fill", "target": "search_input", "value": "laptops", "checkpoint": false},
            {"action": "click", "target": "cheapest_product", "checkpoint": false},
            {"action": "click", "target": "add_to_cart", "checkpoint": true}
        ]
    }
    """
    plan = planner._parse_plan(single_item_llm_json, task)
    actions = [s.action for s in plan.steps]

    # Enforced to use extract + add_all_to_cart
    assert "add_all_to_cart" in actions
    add_all_step = next(s for s in plan.steps if s.action == "add_all_to_cart")
    assert add_all_step.value == "10"
    assert add_all_step.checkpoint is True


@pytest.mark.asyncio
async def test_verifier_multi_item_cart_100_percent():
    verifier = Verifier(AgentConfig())

    # 10 items all added to cart
    items = [{"title": f"Laptop {i}", "price": "70000", "url": f"https://amazon.in/dp/{i}", "cart_status": "added"} for i in range(10)]
    page_state = PageState(
        url="https://www.amazon.in/gp/cart/view.html",
        title="Shopping Cart",
        interactive_elements=[],
        extracted_items=items,
    )

    action = ActionObject(action="add_all_to_cart", selector="extracted_products", value="10")
    res, tok = await verifier.verify_checkpoint(
        expected_outcome="Add all 10 items to cart",
        page_state=page_state,
        action_desc="add_all_to_cart extracted_products",
        action_success=True,
    )
    assert res.status == "success"
    assert "100%" in res.reason or "All 10" in res.reason


@pytest.mark.asyncio
async def test_verifier_multi_item_cart_partial_percent():
    verifier = Verifier(AgentConfig())

    # 7 items added, 3 out of stock
    items = [{"title": f"Laptop {i}", "price": "70000", "url": f"https://amazon.in/dp/{i}", "cart_status": "added"} for i in range(7)]
    items += [{"title": f"Laptop {i}", "price": "70000", "url": f"https://amazon.in/dp/{i}", "cart_status": "unavailable / out of stock"} for i in range(7, 10)]

    page_state = PageState(
        url="https://www.amazon.in/gp/cart/view.html",
        title="Shopping Cart",
        interactive_elements=[],
        extracted_items=items,
    )

    action = ActionObject(action="add_all_to_cart", selector="extracted_products", value="10")
    res, tok = await verifier.verify_checkpoint(
        expected_outcome="Add all 10 items to cart",
        page_state=page_state,
        action_desc="add_all_to_cart extracted_products",
        action_success=True,
    )
    assert res.status == "partial"
    assert "70%" in res.reason
    assert "7 of 10" in res.reason


@pytest.mark.asyncio
async def test_verifier_multi_item_cart_zero_percent_failure():
    verifier = Verifier(AgentConfig())

    # 0 items added
    items = [{"title": f"Laptop {i}", "price": "70000", "url": f"https://amazon.in/dp/{i}", "cart_status": "unavailable / out of stock"} for i in range(5)]

    page_state = PageState(
        url="https://www.amazon.in/gp/cart/view.html",
        title="Shopping Cart",
        interactive_elements=[],
        extracted_items=items,
    )

    action = ActionObject(action="add_all_to_cart", selector="extracted_products", value="5")
    res, tok = await verifier.verify_checkpoint(
        expected_outcome="Add all 5 items to cart",
        page_state=page_state,
        action_desc="add_all_to_cart extracted_products",
        action_success=True,
    )
    assert res.status == "failure"
    assert "0%" in res.reason
