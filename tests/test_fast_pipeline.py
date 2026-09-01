"""
Integration test for the full Fast Plan-then-Execute pipeline.
Tests planning, model routing, state management, batch execution, and metrics collection.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
import json

from agent_framework.config import AgentConfig
from agent_framework.model_router import ModelTier, route
from agent_framework.modules.unified_planner import UnifiedPlanner, ExecutionPlan, PlannedStep
from agent_framework.modules.state_manager import StateManager
from agent_framework.modules.metrics import MetricsCollector
from agent_framework.modules.verifier import Verifier
from agent_framework.models import PageState, InteractiveElement, ActionObject


@pytest.mark.asyncio
async def test_fast_plan_then_execute_flow():
    config = AgentConfig(headless=True)
    planner = UnifiedPlanner(config)
    verifier = Verifier(config)
    state_mgr = StateManager()
    metrics = MetricsCollector()
    metrics.start()

    # 1. Mock Planning (Single LLM call generating 4 steps)
    mock_plan_json = {
        "task_type": "product_search",
        "domain": "laptops",
        "success_criteria": "Laptops under 60k listed",
        "steps": [
            {"action": "navigate", "target": "", "value": "https://www.google.com", "checkpoint": False, "description": "Go to Google"},
            {"action": "fill", "target": "searchbox", "value": "laptops under 60000 16gb ram", "checkpoint": False, "description": "Search query"},
            {"action": "click", "target": "search button", "value": "", "checkpoint": True, "description": "Submit search"},
            {"action": "extract", "target": "results", "value": "", "checkpoint": True, "description": "Extract product specs"}
        ]
    }

    with patch.object(planner.llm, "_call_nvidia_model", AsyncMock(return_value=(json.dumps(mock_plan_json), 240))):
        plan, tokens = await planner.plan("Find the cheapest laptop under Rs.60,000 with 16GB RAM")
        metrics.record_llm_call("fast", tokens=tokens, duration_ms=250, phase="plan")

    assert len(plan.steps) == 4
    assert plan.steps[2].checkpoint is True
    assert plan.steps[3].checkpoint is True
    assert tokens == 240
    assert metrics.metrics.total_llm_calls == 1

    # 2. Simulate Fast Deterministic Execution of steps
    state_mgr.set_goal("Find laptops under 60k", len(plan.steps))
    prev_page = None

    for i, step in enumerate(plan.steps):
        action_obj = step.to_action_object()
        assert isinstance(action_obj, ActionObject)

        # Record deterministic browser action (0 LLM calls!)
        metrics.record_browser_action(action_obj.action, success=True, duration_ms=100)

        curr_page = PageState(
            url="https://www.google.com/search?q=laptops" if i >= 2 else "https://www.google.com",
            title="Google Search" if i >= 2 else "Google",
            interactive_elements=[
                InteractiveElement(id="e1", role="link", label="Laptop 16GB at Rs 54990"),
                InteractiveElement(id="e2", role="link", label="Budget Gaming Laptop 16GB RAM"),
                InteractiveElement(id="e3", role="button", label="Next"),
            ],
        )

        state_mgr.update(
            url=curr_page.url,
            title=curr_page.title,
            action=action_obj.action,
            result="executed",
            step_index=i,
        )

        # Checkpoint validation
        if step.checkpoint:
            ver_res, ver_tokens = await verifier.verify_checkpoint(
                expected_outcome=step.description,
                page_state=curr_page,
                previous_page_state=prev_page,
            )
            assert ver_res.status == "success"
            assert ver_tokens == 0  # 0 LLM calls for healthy checkpoint
            metrics.record_checkpoint()
            metrics.record_screenshot()

        prev_page = curr_page
        state_mgr.mark_step_complete(i)

    metrics.stop()

    # Verify target performance:
    # 1 LLM call total, 0 LLM calls during execution, 4 browser actions, 2 checkpoints
    assert metrics.metrics.total_llm_calls == 1
    assert metrics.metrics.fast_model_calls == 1
    assert metrics.metrics.reasoning_model_calls == 0
    assert metrics.metrics.total_tokens == 240
    assert metrics.metrics.total_actions == 4
    assert metrics.metrics.checkpoints_validated == 2
    assert metrics.metrics.screenshots_taken == 2
    assert len(state_mgr.state.completed_steps) == 4
