"""
Module 7 — Action Selector
============================
Given a PageState + current SubTask, generates the next concrete ActionObject
via an LLM call.

Pipeline position: PageState + SubTask -> ActionObject -> BrowserExecutor
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..config import AgentConfig, default_config
from ..llm_client import LLMClient
from ..models import ActionObject, GoalObject, PageState, PromptContext, SubTask, StrategyContext
from ..modules.prompt_generator import PromptGenerator

logger = logging.getLogger(__name__)

_FALLBACK_EXTRACT = ActionObject(action="extract", selector=None, value=None)
_FALLBACK_WAIT = ActionObject(action="wait", selector=None, value=None)


class ActionSelector:
    """
    Module 7: Generates the next ActionObject for the current pipeline step.

    Uses the PromptGenerator (M4) to build the prompt, then calls the LLM
    and parses the response into a validated ActionObject.
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self.llm = LLMClient(config)
        self.prompt_gen = PromptGenerator()

    async def select(
        self,
        goal: GoalObject,
        sub_task: SubTask,
        page_state: PageState,
        strategy: StrategyContext,
        history: list[ActionObject] | None = None,
        repair_notes: Optional[str] = None,
    ) -> tuple[ActionObject, int]:
        """
        Generate the next ActionObject for the given pipeline step.

        Args:
            goal: Parsed goal object.
            sub_task: Current sub-task.
            page_state: Current pruned page state.
            strategy: Active strategy context.
            history: List of recent ActionObjects (last N kept by config).
            repair_notes: Optional repair instructions from RepairEngine.

        Returns:
            Tuple of (ActionObject, tokens_used).
        """
        history = (history or [])[-(self.config.action_history_window):]

        context = PromptContext(
            goal=goal,
            sub_task=sub_task,
            page_state=page_state,
            history=history,
            repair_notes=repair_notes,
            strategy=strategy,
        )

        prompt = self.prompt_gen.generate(context)
        logger.info(f"[M7] Selecting action for sub-task: {sub_task.goal[:60]}")

        response_text, tokens = await self.llm.complete(prompt)
        action = self._parse_action(response_text)
        logger.info(f"[M7] Action selected: {action.action} selector={action.selector}")
        return action, tokens

    def _parse_action(self, text: str) -> ActionObject:
        """Extract and validate ActionObject JSON from LLM response."""
        json_match = re.search(r"\{[\s\S]*?\}", text)
        if not json_match:
            logger.warning("[M7] No JSON found in action response. Using wait fallback.")
            return _FALLBACK_WAIT

        try:
            data = json.loads(json_match.group())
            return ActionObject(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"[M7] Action parse error: {e}. Retrying with extract fallback.")
            return _FALLBACK_EXTRACT
