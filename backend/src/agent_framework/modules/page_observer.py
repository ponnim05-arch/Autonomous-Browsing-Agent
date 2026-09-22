"""
Module 6 — Page State Observer
================================
Converts raw browser page state into a compact, LLM-consumable PageState.

Pipeline position: raw page state (dict) -> PageState -> ActionSelector/Verifier
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import AgentConfig, default_config
from ..models import PageState
from ..utils.dom_pruner import prune_accessibility_tree, elements_to_text, filter_for_task

logger = logging.getLogger(__name__)


class PageObserver:
    """
    Module 6: Transforms raw Playwright state into a structured PageState.

    Pruning pipeline:
        raw accessibility_tree
        → filter interactive roles
        → assign stable e{n} IDs
        → filter for task relevance (if keywords provided)
        → truncate to max_interactive_elements
        → build concise summary_text
        → return PageState
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config

    def observe(
        self,
        raw_state: dict[str, Any],
        task_keywords: list[str] | None = None,
        prev_state: PageState | None = None,
    ) -> PageState:
        """
        Convert a raw browser state dict into a structured PageState.

        Args:
            raw_state: Output from BrowserExecutor.execute() containing
                       keys: url, title, accessibility_tree, screenshot_path
            task_keywords: Optional keywords to prioritize task-relevant elements.
            prev_state: Optional previous page state for comparison.

        Returns:
            PageState with pruned interactive elements and summary text.
        """
        url = raw_state.get("url", "")
        title = raw_state.get("title", "")
        tree = raw_state.get("accessibility_tree", {})
        screenshot_path = raw_state.get("screenshot_path")

        # Prune accessibility tree
        elements = prune_accessibility_tree(
            tree,
            max_elements=self.config.max_interactive_elements,
        )

        # Filter by task relevance if keywords are provided
        if task_keywords:
            elements = filter_for_task(
                elements,
                task_keywords,
                max_elements=min(self.config.max_interactive_elements, 30),
            )

        # Generate summary text
        extracted_items = raw_state.get("extracted_items", [])
        direct_link = raw_state.get("direct_link")
        summary = self._generate_summary(url, title, elements, prev_state, extracted_items)

        page_state = PageState(
            url=url,
            title=title,
            interactive_elements=elements,
            summary_text=summary,
            screenshot_path=screenshot_path,
            raw_html_length=len(str(tree)),
            extracted_items=extracted_items,
            direct_link=direct_link,
        )

        logger.info(
            f"[M6] Observed page: '{title[:60]}' | "
            f"{len(elements)} interactive elements | {len(extracted_items)} items extracted | url={url[:80]}"
        )
        return page_state

    @staticmethod
    def _generate_summary(
        url: str,
        title: str,
        elements,
        prev_state: PageState | None = None,
        extracted_items: list[dict[str, Any]] | None = None,
    ) -> str:
        """Generate a brief natural-language summary of the page state."""
        roles = {}
        for el in elements:
            roles[el.role] = roles.get(el.role, 0) + 1

        role_summary = ", ".join(f"{count} {role}(s)" for role, count in roles.items())
        is_error = any(
            kw in title.lower()
            for kw in ["404", "not found", "error", "unavailable", "blocked", "access denied"]
        )
        error_note = " ⚠️ Error page detected." if is_error else ""

        changed_note = ""
        if prev_state and prev_state.url != url:
            changed_note = f" (Navigated from {prev_state.url[:40]})"

        return (
            f"Page: '{title}' at {url}.{changed_note} "
            f"Interactive elements: {role_summary or 'none'}.{error_note}"
        )

