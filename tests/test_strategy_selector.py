"""
test_strategy_selector.py — Unit tests for Module 3 (StrategySelector)

Validates strategy selection, A/B strategy overrides, auto-escalation
on retry threshold, and failure recovery triggering.
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.models import SubTask, VerificationResult, StrategyContext
from agent_framework.modules.strategy_selector import StrategySelector
from agent_framework.config import AgentConfig


@pytest.fixture
def base_config():
    return AgentConfig(experiment_strategy="dynamic", auto_escalate_on_retry=True)


@pytest.fixture
def selector(base_config):
    return StrategySelector(base_config)


@pytest.fixture
def sub_task():
    return SubTask(step=1, type="search", goal="Search for laptops")


def test_select_default_experiment_strategy(selector, sub_task):
    """When no retries or failures, selector returns configured strategy."""
    ctx = selector.select(sub_task, retry_count=0)
    assert isinstance(ctx, StrategyContext)
    assert ctx.strategy_id == "dynamic"
    assert ctx.retry_count == 0
    assert "dynamic" in ctx.escalation_history


def test_select_static_strategy_when_configured(sub_task):
    """When static strategy is configured, it is selected."""
    cfg = AgentConfig(experiment_strategy="static")
    sel = StrategySelector(cfg)
    ctx = sel.select(sub_task, retry_count=0)
    assert ctx.strategy_id == "static"


def test_escalates_to_self_reflective_on_first_failure(selector, sub_task):
    """On first retry with failure verification, escalates from dynamic to self_reflective."""
    failed_ver = VerificationResult(
        status="failure",
        reason="Element not found",
        confidence_score=0.9,
    )
    ctx = selector.select(sub_task, retry_count=1, last_verification=failed_ver)
    assert ctx.strategy_id == "self_reflective"
    assert ctx.retry_count == 1


def test_escalates_to_failure_recovery_after_threshold(selector, sub_task):
    """After ESCALATION_THRESHOLD (2) retries on failure, escalates to failure_recovery."""
    failed_ver = VerificationResult(
        status="failure",
        reason="Stale element reference twice",
        confidence_score=0.95,
    )
    ctx = selector.select(sub_task, retry_count=2, last_verification=failed_ver)
    assert ctx.strategy_id == "failure_recovery"
    assert ctx.retry_count == 2
    assert ctx.parameters.get("force_alternative_path") is True


def test_maintains_escalation_history(selector, sub_task):
    """Escalation history tracks previously used strategies."""
    history = ["dynamic", "self_reflective"]
    failed_ver = VerificationResult(status="failure", reason="Failed again", confidence_score=0.9)
    ctx = selector.select(
        sub_task,
        retry_count=2,
        last_verification=failed_ver,
        escalation_history=history,
    )
    assert ctx.escalation_history == ["dynamic", "self_reflective", "failure_recovery"]
