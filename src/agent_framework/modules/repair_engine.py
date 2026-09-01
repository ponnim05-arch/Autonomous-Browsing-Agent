"""
Module 9 — Prompt Repair Engine
=================================
On verification failure, generates a RepairAmendment — a targeted corrective
instruction injected into the next prompt via PromptGenerator (M4).

Pipeline position: VerificationResult (failure) -> RepairAmendment -> PromptGenerator

Repair strategies (per spec §3/M9):
    selector_repair    – Re-identify target element from updated DOM
    goal_reframing     – Rephrase sub-task in simpler terms
    alternative_path   – Suggest alternative navigation path
    sub_task_skip      – If 3+ repairs fail, mark sub-task failed and continue
"""

from __future__ import annotations

import json
import logging
import re

from ..config import AgentConfig, default_config
from ..llm_client import LLMClient
from ..models import RepairAmendment, RepairInput

logger = logging.getLogger(__name__)

_REPAIR_PROMPT_TEMPLATE = """You are a browser agent repair specialist.

A sub-task has FAILED. Your job is to diagnose the failure and suggest a repair.

FAILURE CONTEXT:
  Original goal: {original_goal}
  Failed action: {failed_action}
  Failure reason: {failure_reason}
  Attempt number: {attempt_number}

CURRENT PAGE STATE SUMMARY:
  URL: {url}
  Title: {title}
  Available elements (first 30):
{elements}

Choose the most appropriate repair strategy:
  - "selector_repair": The element selector was stale or wrong; find a better one.
  - "goal_reframing": The goal wording led to wrong action; reframe it simpler.
  - "alternative_path": The current approach is stuck; suggest a totally different path.
  - "sub_task_skip": It is impossible to complete this step; skip and continue.

Output ONLY valid JSON:
{{
  "amendment_type": "<selector_repair|goal_reframing|alternative_path|sub_task_skip>",
  "corrective_instruction": "<specific correction to apply in the next prompt>",
  "new_strategy": "<static|dynamic|self_reflective|failure_recovery>",
  "retry_count": {attempt_number}
}}
"""


class RepairEngine:
    """
    Module 9: Generates targeted repair amendments on verification failures.

    After max_retries, automatically returns a sub_task_skip amendment.
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self.llm = LLMClient(config)

    async def repair(self, repair_input: RepairInput) -> tuple[RepairAmendment, int]:
        """
        Generate a RepairAmendment for the given failure context.

        Args:
            repair_input: Structured failure context.

        Returns:
            Tuple of (RepairAmendment, tokens_used).
        """
        attempt = repair_input.attempt_number

        # Hard cap: skip sub-task after max_retries
        if attempt >= self.config.max_retries_per_subtask:
            logger.warning(
                f"[M9] Max retries ({self.config.max_retries_per_subtask}) reached. "
                "Marking sub-task as skipped."
            )
            return self._skip_amendment(attempt), 0

        prompt = self._build_repair_prompt(repair_input)
        logger.info(f"[M9] Generating repair for attempt {attempt}: {repair_input.failure_reason[:60]}")

        response_text, tokens = await self.llm.complete(prompt, temperature=0.15)
        amendment = self._parse_amendment(response_text, attempt)

        logger.info(
            f"[M9] Repair → type={amendment.amendment_type}, "
            f"strategy={amendment.new_strategy}"
        )
        return amendment, tokens

    # ── Internals ─────────────────────────────────────────────────

    def _build_repair_prompt(self, ri: RepairInput) -> str:
        page = ri.current_page_state
        elements_text = "\n".join(
            f"  [{el.id}] {el.role}: '{el.label}'"
            for el in page.interactive_elements[:30]
        ) or "  (none visible)"

        return _REPAIR_PROMPT_TEMPLATE.format(
            original_goal=ri.original_goal,
            failed_action=ri.failed_action.model_dump_json(),
            failure_reason=ri.failure_reason,
            attempt_number=ri.attempt_number,
            url=page.url,
            title=page.title,
            elements=elements_text,
        )

    def _parse_amendment(self, text: str, attempt_number: int) -> RepairAmendment:
        json_match = re.search(r"\{[\s\S]*?\}", text)
        if not json_match:
            return self._fallback_amendment(attempt_number)
        try:
            data = json.loads(json_match.group())
            data["retry_count"] = attempt_number
            return RepairAmendment(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return self._fallback_amendment(attempt_number)

    @staticmethod
    def _fallback_amendment(attempt: int) -> RepairAmendment:
        return RepairAmendment(
            amendment_type="goal_reframing",
            corrective_instruction=(
                "The previous approach failed. Try a simpler action — "
                "look for alternative buttons or links that might achieve the same goal."
            ),
            new_strategy="failure_recovery",
            retry_count=attempt,
        )

    @staticmethod
    def _skip_amendment(attempt: int) -> RepairAmendment:
        return RepairAmendment(
            amendment_type="sub_task_skip",
            corrective_instruction=(
                "This sub-task has exceeded the maximum retry limit. "
                "Mark it as failed and proceed to the next sub-task."
            ),
            new_strategy="failure_recovery",
            retry_count=attempt,
        )
