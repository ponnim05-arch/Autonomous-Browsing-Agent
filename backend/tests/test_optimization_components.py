"""
Unit tests for the performance optimization modules:
- Model Router
- Unified Planner
- State Manager
- Metrics Collector
"""

import pytest
from agent_framework.model_router import ModelTier, route, route_for_planning, route_for_verification, route_for_recovery
from agent_framework.modules.state_manager import StateManager
from agent_framework.modules.metrics import MetricsCollector
from agent_framework.modules.unified_planner import PlannedStep, ExecutionPlan, UnifiedPlanner


def test_model_router_decisions():
    # Recovery always uses reasoning
    assert route(phase="recover") == ModelTier.REASONING
    assert route(phase="plan", error="some error") == ModelTier.REASONING

    # Deterministic execution actions use NO_LLM
    assert route(phase="execute", action_type="navigate") == ModelTier.NO_LLM
    assert route(phase="execute", action_type="scroll") == ModelTier.NO_LLM

    # High confidence execution uses NO_LLM
    assert route(phase="execute", action_type="click", confidence=0.95) == ModelTier.NO_LLM

    # Normal planning uses FAST tier
    assert route_for_planning("product_search") == ModelTier.FAST

    # Repeated failure planning escalates to REASONING
    assert route_for_planning("product_search", retry_count=1) == ModelTier.REASONING


def test_state_manager_tracking():
    sm = StateManager()
    sm.set_goal("Find laptops", 4)
    assert sm.state.total_steps == 4

    sm.update(
        url="https://www.google.com",
        title="Google",
        action="navigate",
        result="success",
        element_count=12,
        step_index=0,
    )
    assert sm.state.url == "https://www.google.com"
    assert sm.state.page_type == "content"
    assert sm.page_changed is True

    sm.mark_step_complete(0)
    assert 0 in sm.state.completed_steps

    ctx = sm.get_recovery_context()
    assert ctx["goal"] == "Find laptops"
    assert ctx["current_step"] == 0


def test_metrics_collector():
    mc = MetricsCollector()
    mc.start()
    mc.record_llm_call("fast", tokens=120, duration_ms=250, phase="plan")
    mc.record_browser_action("navigate", success=True, duration_ms=600)
    mc.record_browser_action("click", success=True, duration_ms=300)
    mc.record_screenshot()
    mc.record_checkpoint()
    mc.stop()

    summary_text = mc.summary()
    assert "TASK PERFORMANCE REPORT" in summary_text
    assert mc.metrics.fast_model_calls == 1
    assert mc.metrics.total_actions == 2
    assert mc.metrics.screenshots_taken == 1
    assert mc.metrics.checkpoints_validated == 1

    d = mc.to_dict()
    assert d["total_tokens"] == 120
    assert d["successful_actions"] == 2


def test_planned_step_conversion():
    step = PlannedStep(
        action="fill",
        target="search box",
        value="laptop 16gb",
        checkpoint=True,
        description="Type laptop search",
    )
    action_obj = step.to_action_object()
    assert action_obj.action == "fill"
    assert action_obj.selector == "search box"
    assert action_obj.value == "laptop 16gb"


def test_unified_planner_fallback():
    planner = UnifiedPlanner()
    fallback = planner._fallback_plan("search headphones")
    assert len(fallback.steps) >= 3
    assert fallback.steps[-1].checkpoint is True
