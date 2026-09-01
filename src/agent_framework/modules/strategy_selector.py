"""
Module 3 — Strategy Selector
==============================
Chooses which prompting strategy to apply for the current SubTask and state.

Pipeline position: GoalObject + List[SubTask] -> StrategyContext -> PromptGenerator

Strategies:
    static           – Fixed prompt, no context adaptation (baseline)
    dynamic          – Context-aware prompts built from current goal + DOM state
    self_reflective  – Chain-of-thought critique before action output
    failure_recovery – Repair-driven prompting, triggered by VerificationResult failure
"""

from __future__ import annotations

import logging

from ..config import AgentConfig, default_config
from ..models import SubTask, StrategyContext, VerificationResult

logger = logging.getLogger(__name__)

VALID_STRATEGIES = {"static", "dynamic", "self_reflective", "failure_recovery"}

# Maps sub-task type to preferred strategy (overridden by experiment config)
_TASK_TYPE_DEFAULTS: dict[str, str] = {
    "search":   "dynamic",
    "navigate": "dynamic",
    "filter":   "dynamic",
    "extract":  "self_reflective",
    "compare":  "self_reflective",
    "verify":   "dynamic",
}


class StrategySelector:
    """
    Module 3: Selects the prompting strategy for each pipeline step.

    Selection priority:
        1. If VerificationResult.status == "failure" and retries >= threshold → failure_recovery
        2. If configured experiment_strategy is "auto" → use task-type heuristic
        3. Otherwise → use experiment_strategy from config (A/B experiment mode)
    """

    ESCALATION_THRESHOLD = 2  # retries before escalating to failure_recovery

    def __init__(self, config: AgentConfig = default_config):
        self.config = config

    def select(
        self,
        sub_task: SubTask,
        retry_count: int = 0,
        last_verification: VerificationResult | None = None,
        escalation_history: list[str] | None = None,
    ) -> StrategyContext:
        """
        Select the appropriate strategy and return a StrategyContext.

        Args:
            sub_task: Current sub-task being executed.
            retry_count: Number of retries so far for this sub-task.
            last_verification: Most recent verification result (None on first attempt).
            escalation_history: List of previously used strategies this run.

        Returns:
            StrategyContext with selected strategy_id and metadata.
        """
        history = list(escalation_history or [])
        strategy_id = self._resolve_strategy(sub_task, retry_count, last_verification)
        history.append(strategy_id)

        ctx = StrategyContext(
            strategy_id=strategy_id,
            parameters=self._get_parameters(strategy_id, retry_count),
            retry_count=retry_count,
            escalation_history=history,
        )

        logger.info(
            f"[M3] Sub-task={sub_task.type} retry={retry_count} "
            f"→ strategy={strategy_id}"
        )
        return ctx

    # ── Internal ──────────────────────────────────────────────────

    def _resolve_strategy(
        self,
        sub_task: SubTask,
        retry_count: int,
        last_verification: VerificationResult | None,
    ) -> str:
        # Rule 1: Auto-escalate on failure after threshold
        if (
            self.config.auto_escalate_on_retry
            and last_verification is not None
            and last_verification.status == "failure"
            and retry_count >= self.ESCALATION_THRESHOLD
        ):
            return "failure_recovery"

        # Rule 2: Explicit failure on first retry
        if (
            last_verification is not None
            and last_verification.status == "failure"
            and retry_count > 0
        ):
            # Escalate from static/dynamic to self_reflective
            current = self.config.experiment_strategy
            if current in ("static", "dynamic"):
                return "self_reflective"

        # Rule 3: Use experiment_strategy from config (A/B mode)
        configured = self.config.experiment_strategy
        if configured in VALID_STRATEGIES:
            return configured

        # Rule 4: Auto-select by task type
        return _TASK_TYPE_DEFAULTS.get(sub_task.type, "dynamic")

    @staticmethod
    def _get_parameters(strategy_id: str, retry_count: int) -> dict:
        """Strategy-specific runtime parameters."""
        base = {"retry_count": retry_count}
        if strategy_id == "self_reflective":
            base["critique_depth"] = "detailed" if retry_count > 0 else "brief"
        if strategy_id == "failure_recovery":
            base["force_alternative_path"] = retry_count >= 2
        return base
