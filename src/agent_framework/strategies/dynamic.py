"""
strategies/dynamic.py — Dynamic Contextual Prompting Strategy (Optimized)
========================================================================
Token-efficient, stage-specific prompts built from current goal, sub-task type,
compact DOM state, and recent history.
"""

from __future__ import annotations

from ..models import PromptContext
from ..utils.dom_pruner import elements_to_compact


# ── P1: Search Strategy Prompt ────────────────────────────────────────────────

_SEARCH_TEMPLATE = """You are a web search agent.
GOAL: {overall_goal}
TASK: {sub_task_goal}
DOMAIN: {domain}
CONSTRAINTS: {constraints}
PAGE: {url} - "{title}"

ELEMENTS:
{elements}

Output ONLY valid JSON:
{{
  "action": "<click|type|navigate>",
  "selector": "<element id or target>",
  "value": "<query or url or null>",
  "timeout_ms": 5000
}}
"""

# ── P2: Page Understanding Prompt ─────────────────────────────────────────────

_EXTRACT_TEMPLATE = """You are a data extraction agent.
GOAL: {overall_goal}
TASK: {sub_task_goal}
PAGE: {url} - "{title}"
SUMMARY: {page_summary}

ELEMENTS:
{elements}

Output ONLY valid JSON:
{{
  "action": "extract",
  "selector": null,
  "value": "<extracted data as JSON string>",
  "timeout_ms": 5000
}}
"""

# ── P3: Decision / Comparison Prompt ──────────────────────────────────────────

_COMPARE_TEMPLATE = """You are a ranking and comparison agent.
GOAL: {overall_goal}
TASK: {sub_task_goal}
CRITERIA: {success_criteria}
DATA:
{history}

Output ONLY valid JSON:
{{
  "action": "extract",
  "selector": null,
  "value": "<ranked results as JSON string>",
  "timeout_ms": 5000
}}
"""

# ── P4: Generic Action Planning Prompt ────────────────────────────────────────

_ACTION_TEMPLATE = """You are a browser automation agent.
GOAL: {overall_goal}
STEP: {sub_task_goal}
PAGE: {url} - "{title}"
SUMMARY: {page_summary}

ELEMENTS:
{elements}

HISTORY:
{history}

Output ONLY valid JSON:
{{
  "action": "<click|type|navigate|scroll|extract|wait>",
  "selector": "<element id or selector or null>",
  "value": "<text/URL/null>",
  "timeout_ms": 5000
}}
"""

# ── P5: Verification Prompt ───────────────────────────────────────────────────

_VERIFICATION_TEMPLATE = """Verify if browser action succeeded.
TASK: {sub_task_goal}
EXPECTED: {expected_outcome}
ACTION: {action}
PAGE: {url} - "{title}"
SUMMARY: {page_summary}

Output ONLY valid JSON:
{{
  "status": "<success|failure|partial>",
  "reason": "<short reason>",
  "expected_outcome": "{expected_outcome}",
  "confidence_score": <float 0.0 to 1.0>
}}
"""


def build_prompt(context: PromptContext) -> str:
    """Route to the correct dynamic sub-prompt based on sub-task type."""
    task_type = context.sub_task.type

    if task_type == "search":
        return _build_search(context)
    elif task_type == "extract":
        return _build_extract(context)
    elif task_type == "compare":
        return _build_compare(context)
    else:
        return _build_action(context)


def build_verification_prompt(context: PromptContext) -> str:
    """P5 — Build a context-aware verification prompt."""
    last_action = context.history[-1] if context.history else None
    action_str = last_action.model_dump_json() if last_action else "None"
    page = context.page_state
    expected = _infer_expected_outcome(context)

    return _VERIFICATION_TEMPLATE.format(
        sub_task_goal=context.sub_task.goal,
        expected_outcome=expected,
        action=action_str,
        url=page.url if page else "unknown",
        title=page.title if page else "unknown",
        page_summary=page.summary_text if page else "",
    )


# ── Sub-builders ──────────────────────────────────────────────────────────────

def _build_search(context: PromptContext) -> str:
    return _SEARCH_TEMPLATE.format(
        overall_goal=context.goal.success_criteria,
        sub_task_goal=context.sub_task.goal,
        domain=context.goal.domain,
        constraints=context.goal.constraints,
        url=_url(context),
        title=_title(context),
        elements=_format_elements(context),
    )


def _build_extract(context: PromptContext) -> str:
    return _EXTRACT_TEMPLATE.format(
        overall_goal=context.goal.success_criteria,
        sub_task_goal=context.sub_task.goal,
        url=_url(context),
        title=_title(context),
        page_summary=_summary(context),
        elements=_format_elements(context),
    )


def _build_compare(context: PromptContext) -> str:
    return _COMPARE_TEMPLATE.format(
        overall_goal=context.goal.success_criteria,
        sub_task_goal=context.sub_task.goal,
        success_criteria=context.goal.success_criteria,
        history=_format_history(context),
    )


def _build_action(context: PromptContext) -> str:
    return _ACTION_TEMPLATE.format(
        overall_goal=context.goal.success_criteria,
        sub_task_goal=context.sub_task.goal,
        url=_url(context),
        title=_title(context),
        page_summary=_summary(context),
        elements=_format_elements(context),
        history=_format_history(context),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _url(ctx: PromptContext) -> str:
    return ctx.page_state.url if ctx.page_state else "unknown"


def _title(ctx: PromptContext) -> str:
    return ctx.page_state.title if ctx.page_state else "unknown"


def _summary(ctx: PromptContext) -> str:
    return ctx.page_state.summary_text if ctx.page_state else ""


def _format_elements(ctx: PromptContext, limit: int = 30) -> str:
    if not ctx.page_state or not ctx.page_state.interactive_elements:
        return "(none)"
    return elements_to_compact(ctx.page_state.interactive_elements[:limit])


def _format_history(ctx: PromptContext) -> str:
    if not ctx.history:
        return "(none)"
    lines = []
    for i, action in enumerate(ctx.history[-3:], 1):  # last 3 actions
        lines.append(f"{i}. {action.action} {action.selector or ''} {action.value or ''}".strip())
    return "\n".join(lines)


def _infer_expected_outcome(ctx: PromptContext) -> str:
    type_map = {
        "search":   "Search results page loaded",
        "navigate": "Target page loaded",
        "filter":   "Filtered results visible",
        "extract":  "Target data extracted",
        "compare":  "Ranked comparison generated",
        "verify":   "Results verified",
    }
    return type_map.get(ctx.sub_task.type, "Action completed")
