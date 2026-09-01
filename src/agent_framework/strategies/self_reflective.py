"""
strategies/self_reflective.py — Self-Reflective Prompting Strategy
====================================================================
Wraps dynamic prompts with a "think step-by-step and critique your plan"
instruction chain. Forces the model to reason before committing to an action.
"""

from __future__ import annotations

from ..models import PromptContext
from . import dynamic


_REFLECTION_PREFIX = """You are a self-critical browser automation agent.

Before choosing any action, you MUST follow this reasoning chain:

STEP 1 - SITUATION ANALYSIS:
  - What is the current page showing?
  - What elements are available?
  - What is the most recent action history telling me?

STEP 2 - PLAN GENERATION:
  - What are 2-3 possible next actions?
  - Which is most likely to achieve: {sub_task_goal}

STEP 3 - CRITIQUE:
  - What could go wrong with my chosen action?
  - Is there a simpler alternative?
  - Am I repeating a failed pattern?

STEP 4 - FINAL DECISION:
  - My chosen action (output ONLY this as JSON):

"""

_REFLECTION_SUFFIX = """
Remember: Output ONLY valid JSON for the chosen action. Do not include your reasoning in the output.
"""


def build_prompt(context: PromptContext) -> str:
    """
    Build a self-reflective prompt by wrapping the dynamic prompt
    with chain-of-thought critique instructions.
    """
    base = dynamic.build_prompt(context)

    critique_depth = context.strategy.parameters.get("critique_depth", "brief")
    prefix = _REFLECTION_PREFIX.format(sub_task_goal=context.sub_task.goal)

    if critique_depth == "detailed":
        prefix += (
            "\nNote: Previous attempts failed. Be especially critical of selector choices "
            "and consider whether the page structure may have changed.\n"
        )

    return prefix + base + _REFLECTION_SUFFIX


def build_verification_prompt(context: PromptContext) -> str:
    """Delegate verification to dynamic strategy (no self-reflection needed here)."""
    return dynamic.build_verification_prompt(context)
