"""
strategies/static.py — Static Baseline Prompting Strategy
===========================================================
Uses a single fixed prompt template regardless of context or failures.
This is the A/B control condition for the experiment.
"""

from __future__ import annotations

from ..models import PromptContext


_ACTION_TEMPLATE = """You are a browser automation agent. Your task is:
{sub_task_goal}

Current page URL: {url}
Page title: {title}

Interactive elements on the page:
{elements}

Choose ONE action to perform. Output ONLY valid JSON:
{{
  "action": "<click|type|navigate|scroll|extract|wait>",
  "selector": "<element id like e1, or null>",
  "value": "<text to type, or URL to navigate to, or null>",
  "timeout_ms": 5000
}}
"""

_VERIFICATION_TEMPLATE = """Did the last action succeed?

Sub-task goal: {sub_task_goal}
Action taken: {action}
Current page URL: {url}
Page title: {title}

Output ONLY valid JSON:
{{
  "status": "<success|failure|partial>",
  "reason": "<brief explanation>",
  "expected_outcome": "<what was expected>",
  "confidence_score": <float 0.0 to 1.0>
}}
"""


def build_prompt(context: PromptContext) -> str:
    """Build a static action-planning prompt (P4)."""
    elements_text = _format_elements(context)
    page = context.page_state

    return _ACTION_TEMPLATE.format(
        sub_task_goal=context.sub_task.goal,
        url=page.url if page else "unknown",
        title=page.title if page else "unknown",
        elements=elements_text,
    )


def build_verification_prompt(context: PromptContext) -> str:
    """Build a static verification prompt (P5)."""
    last_action = context.history[-1] if context.history else None
    action_str = last_action.model_dump_json() if last_action else "None"
    page = context.page_state

    return _VERIFICATION_TEMPLATE.format(
        sub_task_goal=context.sub_task.goal,
        action=action_str,
        url=page.url if page else "unknown",
        title=page.title if page else "unknown",
    )


def _format_elements(context: PromptContext) -> str:
    if not context.page_state or not context.page_state.interactive_elements:
        return "(no interactive elements detected)"
    lines = []
    for el in context.page_state.interactive_elements[:50]:  # static: tighter limit
        lines.append(f"  [{el.id}] {el.role}: {el.label}")
    return "\n".join(lines)
