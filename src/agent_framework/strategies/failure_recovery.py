"""
strategies/failure_recovery.py — Failure-Recovery Prompting Strategy
======================================================================
Triggered after repeated verification failures. Injects the RepairAmendment
corrective instruction and forces alternative-path reasoning.
"""

from __future__ import annotations

from ..models import PromptContext
from . import dynamic


_RECOVERY_PREFIX = """⚠️  RECOVERY MODE — Previous action attempts FAILED.

You are a recovery-mode browser automation agent. Your previous attempts did not
achieve the sub-task goal. You must think differently this time.

FAILURE CONTEXT:
  - Sub-task goal: {sub_task_goal}
  - Retry attempt: {retry_count}
  - Force alternative path: {force_alt}

RECOVERY INSTRUCTIONS:
  1. Do NOT repeat the same action type + selector combination that already failed.
  2. Look for ALTERNATIVE selectors or element IDs that might achieve the same goal.
  3. If navigation is stuck, try navigating directly to a search engine.
  4. If an element is not found, look for related labels (e.g., 'Buy Now' instead of 'Add to Cart').
  5. If the page hasn't changed, consider a 'scroll' action to reveal more elements.

"""

_RECOVERY_SUFFIX = """
IMPORTANT: Output ONLY valid JSON. Do not repeat selectors from recent failed history.
"""


def build_prompt(context: PromptContext) -> str:
    """
    Build a failure-recovery prompt with alternative path instructions.
    Wraps the dynamic prompt with recovery-mode framing.
    """
    retry_count = context.strategy.retry_count
    force_alt = context.strategy.parameters.get("force_alternative_path", False)

    prefix = _RECOVERY_PREFIX.format(
        sub_task_goal=context.sub_task.goal,
        retry_count=retry_count,
        force_alt="YES — you must try a completely different approach" if force_alt else "NO",
    )

    # Get base dynamic prompt for current context
    base = dynamic.build_prompt(context)

    # Append failed selector warning if we can extract it from history
    failed_selectors = _extract_failed_selectors(context)
    if failed_selectors:
        base += f"\n\nAVOID these selectors (previously failed): {failed_selectors}"

    return prefix + base + _RECOVERY_SUFFIX


def build_verification_prompt(context: PromptContext) -> str:
    """Delegate verification to dynamic strategy."""
    return dynamic.build_verification_prompt(context)


def _extract_failed_selectors(context: PromptContext) -> str:
    """Extract selector IDs from recent action history for exclusion."""
    if not context.history:
        return ""
    selectors = [
        a.selector for a in context.history[-3:]  # last 3 attempts
        if a.selector and a.selector.startswith("e")
    ]
    return ", ".join(set(selectors)) if selectors else ""
