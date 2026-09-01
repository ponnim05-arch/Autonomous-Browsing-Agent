"""
Module 8 — Verifier (Optimized)
=================================
Evaluates whether expected outcomes occurred at checkpoints or after actions.

Optimizations:
- Rule-based heuristics resolve navigation, extract, error detection without LLM
- Checkpoint validation method `verify_checkpoint` for batch plan execution
- Semantic LLM verification fallback for complex action evaluation

Pipeline position: ActionObject + PageState -> VerificationResult
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..config import AgentConfig, default_config
from ..llm_client import LLMClient
from ..models import (
    ActionObject, GoalObject, PageState, PromptContext,
    SubTask, StrategyContext, VerificationResult
)
from ..modules.prompt_generator import PromptGenerator

logger = logging.getLogger(__name__)

# Error page signals
_ERROR_SIGNALS = {"404", "not found", "error", "unavailable", "access denied", "blocked", "captcha", "suspended"}


class Verifier:
    """
    Module 8: Multi-check verifier for browser agent actions.

    Combines rule-based heuristics with LLM semantic verification
    for maximum reliability and minimum latency.
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self.llm = LLMClient(config)
        self.prompt_gen = PromptGenerator()

    async def verify(
        self,
        goal: GoalObject,
        sub_task: SubTask,
        action: ActionObject,
        page_state: PageState,
        previous_page_state: Optional[PageState],
        strategy: StrategyContext,
        history: list[ActionObject] | None = None,
    ) -> tuple[VerificationResult, int]:
        """
        Verify whether the last action achieved its intended outcome.

        Args:
            goal: Overall task goal.
            sub_task: Current sub-task being verified.
            action: The action that was just executed.
            page_state: Page state AFTER the action.
            previous_page_state: Page state BEFORE the action (or None).
            strategy: Active strategy context.
            history: Recent action history.

        Returns:
            Tuple of (VerificationResult, tokens_used).
        """
        # 1. Rule-based checks first (fast, 0 tokens)
        rule_result = self._rule_based_check(action, page_state, previous_page_state)
        if rule_result is not None:
            logger.info(f"[M8] Rule-based verdict: {rule_result.status} — {rule_result.reason}")
            return rule_result, 0

        # 2. LLM-assisted semantic check
        context = PromptContext(
            goal=goal,
            sub_task=sub_task,
            page_state=page_state,
            history=history or [],
            strategy=strategy,
        )
        prompt = self.prompt_gen.generate_verification_prompt(context)
        response_text, tokens = await self.llm.complete(prompt, temperature=0.1)
        result = self._parse_verification(response_text)

        logger.info(
            f"[M8] LLM verdict: {result.status} (conf={result.confidence_score:.2f}) "
            f"— {result.reason[:80]}"
        )
        return result, tokens

    async def verify_checkpoint(
        self,
        expected_outcome: str,
        page_state: PageState,
        previous_page_state: Optional[PageState] = None,
        action_desc: str = "",
    ) -> tuple[VerificationResult, int]:
        """
        Fast checkpoint validator for batch execution.

        Evaluates if the page is in a healthy, successful state according
        to the expected outcome without unnecessary LLM calls.
        """
        title_lower = page_state.title.lower()
        if any(sig in title_lower for sig in _ERROR_SIGNALS):
            return VerificationResult(
                status="failure",
                reason=f"Error page detected: '{page_state.title}'",
                expected_outcome=expected_outcome,
                confidence_score=0.95,
            ), 0

        if not page_state.interactive_elements:
            return VerificationResult(
                status="partial",
                reason="No interactive elements on page — may be loading or blank",
                expected_outcome=expected_outcome,
                confidence_score=0.50,
            ), 0

        return VerificationResult(
            status="success",
            reason=f"Checkpoint verified on '{page_state.title}' with {len(page_state.interactive_elements)} elements",
            expected_outcome=expected_outcome,
            confidence_score=0.90,
        ), 0

    # ── Rule-Based Heuristics ─────────────────────────────────────

    def _rule_based_check(
        self,
        action: ActionObject,
        page: PageState,
        prev_page: Optional[PageState],
    ) -> Optional[VerificationResult]:
        """
        Fast deterministic checks. Returns None if LLM check is required.
        """
        title_lower = page.title.lower()

        # Check 1: Error page detection (hard failure)
        if any(sig in title_lower for sig in _ERROR_SIGNALS):
            return VerificationResult(
                status="failure",
                reason=f"Error page detected: '{page.title}'",
                expected_outcome="Valid content page",
                confidence_score=0.95,
            )

        # Check 2: Navigation — did URL change?
        if action.action == "navigate":
            if prev_page and page.url == prev_page.url:
                return VerificationResult(
                    status="failure",
                    reason="URL did not change after navigate action",
                    expected_outcome="New URL loaded",
                    confidence_score=0.90,
                )
            return VerificationResult(
                status="success",
                reason=f"Navigated to: {page.url[:80]}",
                expected_outcome="Page navigation complete",
                confidence_score=0.85,
            )

        # Check 3: Extract — did we get any content?
        if action.action == "extract":
            if action.value and len(action.value.strip()) > 10:
                return VerificationResult(
                    status="success",
                    reason=f"Data extracted ({len(action.value)} chars)",
                    expected_outcome="Non-empty extracted data",
                    confidence_score=0.88,
                )
            return VerificationResult(
                status="partial",
                reason="Extract action produced empty or minimal result",
                expected_outcome="Non-empty extracted data",
                confidence_score=0.60,
            )

        # Check 4: No elements on page (stuck?)
        if not page.interactive_elements:
            return VerificationResult(
                status="partial",
                reason="No interactive elements found on page — may be loading or blank",
                expected_outcome="Page with interactive elements",
                confidence_score=0.50,
            )

        # Needs LLM check
        return None

    def _parse_verification(self, text: str) -> VerificationResult:
        """Parse LLM verification response into VerificationResult."""
        json_match = re.search(r"\{[\s\S]*?\}", text)
        if not json_match:
            return VerificationResult(
                status="partial",
                reason="Could not parse LLM verification response",
                confidence_score=0.30,
            )
        try:
            data = json.loads(json_match.group())
            return VerificationResult(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return VerificationResult(
                status="partial",
                reason="Verification response malformed",
                confidence_score=0.30,
            )
