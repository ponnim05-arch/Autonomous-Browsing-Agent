"""
Module 2 — Task Decomposer
===========================
Decomposes a GoalObject into an ordered, executable list of SubTask objects.

Pipeline position: GoalObject -> List[SubTask] -> StrategySelector
"""

from __future__ import annotations

import json
import logging
import re

from ..config import AgentConfig, default_config
from ..llm_client import LLMClient
from ..models import GoalObject, SubTask
from ..utils.json_extractor import extract_json_data

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a task decomposition agent for an autonomous browser agent.

Given a structured goal, break it into an ordered list of atomic sub-tasks.
Each sub-task must have a unique step number, a type, and a specific goal.

Valid sub-task types: search | navigate | filter | extract | compare | verify

Output ONLY a valid JSON array like this:
[
  {"step": 1, "type": "search",   "goal": "..."},
  {"step": 2, "type": "navigate", "goal": "..."},
  ...
]

Rules:
- The last sub-task MUST always be type "verify".
- Maximum {max_subtasks} sub-tasks.
- Each goal must be concise and actionable (one sentence).
- Order must be logically sequential.
"""


class TaskDecomposer:
    """Module 2: Converts GoalObject → List[SubTask]."""

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self.llm = LLMClient(config)

    async def decompose(self, goal: GoalObject) -> list[SubTask]:
        """
        Decompose a GoalObject into ordered sub-tasks.

        Args:
            goal: Structured goal from IntentParser (Module 1).

        Returns:
            List of SubTask objects, ordered by step number.
        """
        system = _SYSTEM_PROMPT.replace("{max_subtasks}", str(self.config.max_subtasks_per_task))
        goal_json = goal.model_dump_json(indent=2)
        prompt = f"{system}\n\nGoal Object:\n{goal_json}\n\nSub-tasks:"

        logger.info(f"[M2] Decomposing goal: {goal.task_type} / {goal.domain}")
        response_text, tokens = await self.llm.complete(prompt, temperature=0.1)
        logger.debug(f"[M2] LLM response ({tokens} tokens): {response_text[:300]}")

        subtasks = self._parse_subtasks(response_text, goal)
        logger.info(f"[M2] Decomposed into {len(subtasks)} sub-tasks.")
        return subtasks

    def _parse_subtasks(self, text: str, goal: GoalObject) -> list[SubTask]:
        """Extract and validate sub-task JSON array from LLM response."""
        raw = extract_json_data(text)
        if isinstance(raw, dict) and "subtasks" in raw:
            raw = raw["subtasks"]

        if not raw or not isinstance(raw, list):
            logger.warning("[M2] No JSON array found, using fallback decomposition.")
            return self._fallback_subtasks(goal)

        try:
            subtasks = [SubTask(**item) for item in raw]

            # Enforce ordering and limits
            subtasks.sort(key=lambda t: t.step)
            subtasks = subtasks[: self.config.max_subtasks_per_task]

            # Ensure last step is verify
            if subtasks and subtasks[-1].type != "verify":
                subtasks.append(
                    SubTask(
                        step=subtasks[-1].step + 1,
                        type="verify",
                        goal="Verify that the extracted results are complete and coherent",
                    )
                )
            return subtasks
        except (TypeError, ValueError) as e:
            logger.warning(f"[M2] Parse error: {e}. Using fallback.")
            return self._fallback_subtasks(goal)

    @staticmethod
    def _fallback_subtasks(goal: GoalObject) -> list[SubTask]:
        """Minimal 3-step plan when decomposition fails."""
        return [
            SubTask(step=1, type="search",  goal=f"Search for: {goal.domain}"),
            SubTask(step=2, type="extract", goal="Extract relevant information from the page"),
            SubTask(step=3, type="verify",  goal="Verify that the extracted data is complete"),
        ]
