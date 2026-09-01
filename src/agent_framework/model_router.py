"""
model_router.py — Intelligent Model Router
=============================================
Routes LLM calls to the appropriate model tier based on task complexity,
browser state, and confidence level.

Tiers:
    NO_LLM     → Execute deterministically, no model call needed
    FAST       → Use lightweight fast model (low latency, low tokens)
    REASONING  → Use strong reasoning model (higher latency, more capable)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    NO_LLM = "no_llm"
    FAST = "fast"
    REASONING = "reasoning"


# Actions that never need LLM involvement
_DETERMINISTIC_ACTIONS = {"navigate", "scroll", "wait"}

# Task types that are inherently simple
_SIMPLE_TASK_TYPES = {"navigation", "simple_search"}

# Sub-task types requiring reasoning
_COMPLEX_SUBTASK_TYPES = {"compare", "extract"}


def route(
    *,
    phase: str,
    task_type: str = "",
    sub_task_type: str = "",
    action_type: str = "",
    retry_count: int = 0,
    confidence: float = 1.0,
    page_changed: bool = True,
    error: Optional[str] = None,
) -> ModelTier:
    """
    Determine which model tier to use for the current operation.

    Args:
        phase: Pipeline phase (plan, execute, verify, recover).
        task_type: Overall task classification.
        sub_task_type: Current sub-task type.
        action_type: Browser action being considered.
        retry_count: Number of retries so far.
        confidence: Confidence score (0.0–1.0).
        page_changed: Whether the page state changed since last check.
        error: Error message if action failed.

    Returns:
        ModelTier indicating which model to use.
    """
    # ── Recovery always uses reasoning ──────────────────────────
    if phase == "recover" or error:
        tier = ModelTier.REASONING
        logger.debug(f"[Router] {phase} with error → REASONING")
        return tier

    # ── Planning phase ─────────────────────────────────────────
    if phase == "plan":
        if task_type in _SIMPLE_TASK_TYPES:
            tier = ModelTier.FAST
        elif retry_count > 0:
            tier = ModelTier.REASONING
        else:
            tier = ModelTier.FAST
        logger.debug(f"[Router] plan task_type={task_type} → {tier.value}")
        return tier

    # ── Execution phase — deterministic actions need no LLM ────
    if phase == "execute":
        if action_type in _DETERMINISTIC_ACTIONS:
            return ModelTier.NO_LLM
        if confidence >= 0.90:
            return ModelTier.NO_LLM
        if confidence >= 0.70:
            return ModelTier.FAST
        return ModelTier.REASONING

    # ── Verification phase ─────────────────────────────────────
    if phase == "verify":
        if not page_changed:
            return ModelTier.NO_LLM
        if confidence >= 0.85:
            return ModelTier.NO_LLM
        if sub_task_type in _COMPLEX_SUBTASK_TYPES:
            return ModelTier.FAST
        return ModelTier.FAST

    # ── Default fallback ───────────────────────────────────────
    logger.debug(f"[Router] unknown phase={phase} → FAST")
    return ModelTier.FAST


def route_for_planning(task_type: str, retry_count: int = 0) -> ModelTier:
    """Convenience: route for the planning phase."""
    return route(phase="plan", task_type=task_type, retry_count=retry_count)


def route_for_verification(
    sub_task_type: str,
    confidence: float,
    page_changed: bool = True,
) -> ModelTier:
    """Convenience: route for the verification phase."""
    return route(
        phase="verify",
        sub_task_type=sub_task_type,
        confidence=confidence,
        page_changed=page_changed,
    )


def route_for_recovery() -> ModelTier:
    """Recovery always uses reasoning model."""
    return ModelTier.REASONING
