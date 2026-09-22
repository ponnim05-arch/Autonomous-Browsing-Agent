"""
State Manager — Compact Browser State Tracker
================================================
Maintains a minimal representation of the browser state across the
execution pipeline. Supports state diffing so only changed information
is sent to LLM recovery prompts.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BrowserState:
    """Compact browser state — only the essentials."""

    __slots__ = (
        "url", "title", "page_type", "goal", "completed_steps",
        "current_step", "total_steps", "last_action", "last_result",
        "error", "element_count",
    )

    def __init__(self):
        self.url: str = ""
        self.title: str = ""
        self.page_type: str = "unknown"
        self.goal: str = ""
        self.completed_steps: list[int] = []
        self.current_step: int = 0
        self.total_steps: int = 0
        self.last_action: str = ""
        self.last_result: str = ""
        self.error: Optional[str] = None
        self.element_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "page_type": self.page_type,
            "goal": self.goal,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "last_action": self.last_action,
            "last_result": self.last_result,
            "error": self.error,
            "element_count": self.element_count,
        }

    def to_compact_str(self) -> str:
        """Compact single-line representation for LLM prompts."""
        parts = [
            f"url={self.url[:80]}",
            f"title=\"{self.title[:60]}\"",
            f"step={self.current_step}/{self.total_steps}",
            f"last={self.last_action}→{self.last_result}",
        ]
        if self.error:
            parts.append(f"error={self.error[:80]}")
        return " | ".join(parts)


class StateManager:
    """
    Manages browser state across the execution pipeline.
    Tracks what changed between actions to avoid resending unchanged info.
    """

    def __init__(self):
        self.state = BrowserState()
        self._previous_url: str = ""
        self._previous_title: str = ""

    def update(
        self,
        url: str = "",
        title: str = "",
        action: str = "",
        result: str = "",
        error: Optional[str] = None,
        element_count: int = 0,
        step_index: int = 0,
    ) -> None:
        """Update the browser state after an action."""
        self._previous_url = self.state.url
        self._previous_title = self.state.title

        if url:
            self.state.url = url
        if title:
            self.state.title = title
        if action:
            self.state.last_action = action
        if result:
            self.state.last_result = result
        self.state.error = error
        self.state.element_count = element_count
        self.state.current_step = step_index

        # Detect page type from URL/title
        self.state.page_type = self._detect_page_type(url, title)

    def mark_step_complete(self, step_index: int) -> None:
        """Mark a step as completed."""
        if step_index not in self.state.completed_steps:
            self.state.completed_steps.append(step_index)

    def set_goal(self, goal: str, total_steps: int) -> None:
        """Set the overall task goal and step count."""
        self.state.goal = goal
        self.state.total_steps = total_steps

    @property
    def page_changed(self) -> bool:
        """Check if the page URL or title changed since last update."""
        return (
            self.state.url != self._previous_url
            or self.state.title != self._previous_title
        )

    @property
    def has_error(self) -> bool:
        return self.state.error is not None

    def get_recovery_context(self) -> dict[str, Any]:
        """
        Get minimal context for LLM recovery — only relevant state.
        Much smaller than sending the full page.
        """
        return {
            "goal": self.state.goal,
            "current_step": self.state.current_step,
            "completed": self.state.completed_steps,
            "url": self.state.url[:100],
            "title": self.state.title[:80],
            "last_action": self.state.last_action,
            "error": self.state.error,
        }

    def reset(self) -> None:
        """Reset state for a new task."""
        self.state = BrowserState()
        self._previous_url = ""
        self._previous_title = ""

    @staticmethod
    def _detect_page_type(url: str, title: str) -> str:
        """Heuristic page type detection from URL and title."""
        url_lower = url.lower()
        title_lower = title.lower()

        if any(k in url_lower for k in ("google.com/search", "bing.com/search", "search?")):
            return "search_results"
        if any(k in url_lower for k in ("cart", "basket")):
            return "cart"
        if any(k in url_lower for k in ("checkout", "payment")):
            return "checkout"
        if any(k in url_lower for k in ("login", "signin", "sign-in")):
            return "login"
        if any(k in title_lower for k in ("404", "not found", "error")):
            return "error"
        if any(k in url_lower for k in ("product", "/dp/", "/p/", "/item/")):
            return "product_detail"
        if url_lower in ("", "about:blank"):
            return "blank"

        return "content"
