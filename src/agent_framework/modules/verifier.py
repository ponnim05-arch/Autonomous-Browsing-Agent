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
from ..utils.json_extractor import extract_json_data

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
        action_success: bool = True,
        action_error: Optional[str] = None,
    ) -> tuple[VerificationResult, int]:
        """
        Fast checkpoint validator for batch execution.

        Evaluates if the page is in a healthy, successful state according
        to the expected outcome without unnecessary LLM calls.
        """
        if not action_success:
            return VerificationResult(
                status="failure",
                reason=f"Action failed: {action_error or 'Element not found or interaction failed'}",
                expected_outcome=expected_outcome,
                confidence_score=0.95,
            ), 0

        title_lower = page_state.title.lower()
        if any(sig in title_lower for sig in _ERROR_SIGNALS):
            return VerificationResult(
                status="failure",
                reason=f"Error page detected: '{page_state.title}'",
                expected_outcome=expected_outcome,
                confidence_score=0.95,
            ), 0

        # Check for multi-item cart action
        is_cart_action = any(k in action_desc.lower() for k in ("cart", "buy"))
        if is_cart_action and page_state.extracted_items:
            cart_items = [it for it in page_state.extracted_items if "cart_status" in it]
            if cart_items:
                added = sum(1 for it in cart_items if it.get("cart_status") == "added")
                total = len(cart_items)
                pct = int((added / total) * 100) if total > 0 else 0
                if added == total and total > 0:
                    return VerificationResult(
                        status="success",
                        reason=f"All {total} items successfully added to cart (100% completed)!",
                        expected_outcome=expected_outcome,
                        confidence_score=0.98,
                    ), 0
                elif added > 0:
                    return VerificationResult(
                        status="partial",
                        reason=f"Added {added} of {total} items to cart ({pct}% completed)",
                        expected_outcome=expected_outcome,
                        confidence_score=0.95,
                    ), 0
                else:
                    return VerificationResult(
                        status="failure",
                        reason=f"Failed to add any of the {total} items to cart (0% completed)",
                        expected_outcome=expected_outcome,
                        confidence_score=0.95,
                    ), 0

        # Check for successful product / item extraction
        if not is_cart_action and page_state.extracted_items:
            top_item = page_state.extracted_items[0]
            top_desc = f"{top_item.get('title', '')[:45]} | {top_item.get('price', '')}"
            return VerificationResult(
                status="success",
                reason=f"Extracted {len(page_state.extracted_items)} items. Top: {top_desc}",
                expected_outcome=expected_outcome,
                confidence_score=0.95,
            ), 0

        if not page_state.interactive_elements and not page_state.title:
            return VerificationResult(
                status="partial",
                reason="No content or interactive elements on page — may be loading or blank",
                expected_outcome=expected_outcome,
                confidence_score=0.50,
            ), 0

        return VerificationResult(
            status="success",
            reason=f"Checkpoint verified on '{page_state.title}' ({len(page_state.interactive_elements)} elements)",
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

        # Check 3: Extract — did we get any structured items or content?
        if action.action == "extract":
            if page.extracted_items:
                top_item = page.extracted_items[0]
                return VerificationResult(
                    status="success",
                    reason=f"Extracted {len(page.extracted_items)} items. Direct link: {top_item.get('url')}",
                    expected_outcome="Direct product and price extraction",
                    confidence_score=0.95,
                )
            if action.value and len(action.value.strip()) > 10 and action.value != "[]":
                return VerificationResult(
                    status="success",
                    reason=f"Data extracted ({len(action.value)} chars)",
                    expected_outcome="Non-empty extracted data",
                    confidence_score=0.88,
                )
            return VerificationResult(
                status="partial",
                reason="Extract action completed (waiting for result items)",
                expected_outcome="Non-empty extracted data",
                confidence_score=0.60,
            )

        # Check 4: Multi-item cart action
        if action.action in ("add_all_to_cart", "add_multiple_to_cart") or (
            action.action == "click" and any(k in (action.selector or "").lower() for k in ("add_all_to_cart", "add all", "add_them_to_cart", "add them"))
        ):
            if page.extracted_items:
                cart_items = [it for it in page.extracted_items if "cart_status" in it]
                if cart_items:
                    added = sum(1 for it in cart_items if it.get("cart_status") == "added")
                    total = len(cart_items)
                    pct = int((added / total) * 100) if total > 0 else 0
                    if added == total and total > 0:
                        return VerificationResult(
                            status="success",
                            reason=f"All {total} items successfully added to cart (100% completed)!",
                            expected_outcome=f"All {total} items added to cart",
                            confidence_score=0.98,
                        )
                    elif added > 0:
                        return VerificationResult(
                            status="partial",
                            reason=f"Added {added} of {total} items to cart ({pct}% completed)",
                            expected_outcome=f"All {total} items added to cart",
                            confidence_score=0.95,
                        )
                    else:
                        return VerificationResult(
                            status="failure",
                            reason=f"Failed to add any of the {total} items to cart (0% completed)",
                            expected_outcome=f"Items added to cart",
                            confidence_score=0.95,
                        )
            if action.value:
                m = re.search(r'\((\d{1,3})%\s*completed\)', action.value)
                if m:
                    pct = int(m.group(1))
                    if pct == 100:
                        return VerificationResult(status="success", reason=action.value, expected_outcome="All items added to cart", confidence_score=0.95)
                    elif pct > 0:
                        return VerificationResult(status="partial", reason=action.value, expected_outcome="All items added to cart", confidence_score=0.92)
                    else:
                        return VerificationResult(status="failure", reason=action.value, expected_outcome="All items added to cart", confidence_score=0.90)

        # Check 5: Click on interactive PA targets (cart, buy, book)
        if action.action == "click":
            sel_lower = (action.selector or "").lower()
            pa_targets = ("add_to_cart", "buy_now", "book_now", "cart_button",
                          "proceed", "continue", "next", "login", "sign_in",
                          "close_popup", "dismiss", "reserve")
            if any(t in sel_lower for t in pa_targets):
                # If URL or title changed, it's a success
                if prev_page and (page.url != prev_page.url or page.title != prev_page.title):
                    return VerificationResult(
                        status="success",
                        reason=f"Clicked '{action.selector}' → page changed to '{page.title[:50]}'",
                        expected_outcome=f"Interactive action '{action.selector}' completed",
                        confidence_score=0.92,
                    )
                # Even if page didn't change, action itself succeeded (e.g. cart popup)
                return VerificationResult(
                    status="success",
                    reason=f"Clicked '{action.selector}' on '{page.title[:50]}'",
                    expected_outcome=f"Interactive action '{action.selector}' completed",
                    confidence_score=0.85,
                )

        # Check 5: Fill / Select / Press — success if no error
        if action.action in ("fill", "type", "select", "press", "dismiss_popup"):
            return VerificationResult(
                status="success",
                reason=f"Action '{action.action}' completed on '{page.title[:50]}'",
                expected_outcome=f"{action.action} action executed",
                confidence_score=0.88,
            )

        # Check 6: No elements on page (stuck?)
        if not page.interactive_elements and not page.extracted_items and not page.title:
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
        data = extract_json_data(text)
        if not data or not isinstance(data, dict):
            return VerificationResult(
                status="partial",
                reason="Could not parse LLM verification response",
                confidence_score=0.30,
            )
        try:
            return VerificationResult(**data)
        except (TypeError, ValueError):
            return VerificationResult(
                status="partial",
                reason="Verification response malformed",
                confidence_score=0.30,
            )
