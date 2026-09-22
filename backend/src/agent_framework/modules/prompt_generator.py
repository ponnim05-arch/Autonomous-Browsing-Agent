"""
Module 4 — Dynamic Prompt Generator
=====================================
Generates the actual prompt string for each LLM call during the pipeline.

Pipeline position: StrategyContext + PromptContext -> str (prompt)

Sub-prompts dispatched:
    P1  Search Strategy Prompt         (task type: search)
    P2  Page Understanding Prompt      (after each page load)
    P3  Decision Reasoning Prompt      (task type: compare)
    P4  Action Planning Prompt         (every action cycle)
    P5  Verification Prompt            (after every action)
    P6  Repair Prompt Amendment        (on verification failure)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..models import PromptContext, RepairAmendment

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PromptGenerator:
    """
    Module 4: Dispatches to the correct strategy module and builds
    the final prompt string for each pipeline stage.
    """

    def generate(
        self,
        context: PromptContext,
        repair: RepairAmendment | None = None,
    ) -> str:
        """
        Generate a prompt string for the current pipeline step.

        Args:
            context: Full PromptContext containing goal, sub-task, page state, history.
            repair:  Optional RepairAmendment to inject corrective instructions.

        Returns:
            Final prompt string ready to send to LLM.
        """
        strategy_id = context.strategy.strategy_id
        logger.info(
            f"[M4] Generating prompt: strategy={strategy_id}, "
            f"sub_task_type={context.sub_task.type}"
        )

        # Dispatch to strategy module
        strategy_module = self._load_strategy(strategy_id)
        base_prompt = strategy_module.build_prompt(context)

        # Inject repair amendment if present
        if repair:
            base_prompt = self._inject_repair(base_prompt, repair)

        logger.debug(f"[M4] Prompt length: {len(base_prompt)} chars")
        return base_prompt

    def generate_verification_prompt(self, context: PromptContext) -> str:
        """P5 — Generate the verification prompt for post-action checking."""
        from ..strategies import dynamic as dyn
        return dyn.build_verification_prompt(context)

    # ── Internals ─────────────────────────────────────────────────

    @staticmethod
    def _load_strategy(strategy_id: str):
        """Dynamically import the correct strategy module."""
        if strategy_id == "static":
            from ..strategies import static as mod
        elif strategy_id == "dynamic":
            from ..strategies import dynamic as mod
        elif strategy_id == "self_reflective":
            from ..strategies import self_reflective as mod
        elif strategy_id == "failure_recovery":
            from ..strategies import failure_recovery as mod
        else:
            logger.warning(f"[M4] Unknown strategy '{strategy_id}', falling back to dynamic.")
            from ..strategies import dynamic as mod
        return mod

    @staticmethod
    def _inject_repair(prompt: str, repair: RepairAmendment) -> str:
        """Append repair amendment instructions to an existing prompt."""
        amendment = (
            f"\n\n--- REPAIR INSTRUCTION (Attempt {repair.retry_count}) ---\n"
            f"Amendment type: {repair.amendment_type}\n"
            f"Corrective instruction: {repair.corrective_instruction}\n"
            f"New strategy: {repair.new_strategy}\n"
            f"--- END REPAIR INSTRUCTION ---\n"
        )
        return prompt + amendment
