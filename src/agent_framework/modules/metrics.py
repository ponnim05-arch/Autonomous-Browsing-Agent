"""
Performance Metrics — Task Execution Instrumentation
======================================================
Tracks every performance-relevant metric during task execution:
LLM calls, tokens, screenshots, browser time, recovery attempts, etc.

Produces a summary report at the end of each task.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskMetrics:
    """Performance metrics for a single task execution."""

    # Timing
    start_time: float = 0.0
    end_time: float = 0.0
    browser_time_ms: float = 0.0
    llm_time_ms: float = 0.0

    # LLM calls
    total_llm_calls: int = 0
    fast_model_calls: int = 0
    reasoning_model_calls: int = 0
    planning_calls: int = 0
    verification_calls: int = 0
    recovery_calls: int = 0

    # Tokens
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0

    # Browser
    total_actions: int = 0
    successful_actions: int = 0
    failed_actions: int = 0
    screenshots_taken: int = 0
    dom_extractions: int = 0

    # Recovery
    recovery_attempts: int = 0
    steps_skipped: int = 0

    # Plan
    planned_steps: int = 0
    executed_steps: int = 0
    checkpoints_validated: int = 0

    @property
    def total_time_sec(self) -> float:
        if self.end_time and self.start_time:
            return round(self.end_time - self.start_time, 2)
        return 0.0

    @property
    def browser_time_sec(self) -> float:
        return round(self.browser_time_ms / 1000, 2)

    @property
    def llm_time_sec(self) -> float:
        return round(self.llm_time_ms / 1000, 2)


class MetricsCollector:
    """
    Collects and reports performance metrics for task execution.

    Usage:
        mc = MetricsCollector()
        mc.start()
        mc.record_llm_call("fast", tokens=150, duration_ms=320)
        mc.record_browser_action("click", success=True, duration_ms=450)
        mc.stop()
        print(mc.summary())
    """

    def __init__(self):
        self.metrics = TaskMetrics()
        self._llm_timer: Optional[float] = None

    def start(self) -> None:
        """Start timing the task."""
        self.metrics = TaskMetrics()
        self.metrics.start_time = time.time()

    def stop(self) -> None:
        """Stop timing the task."""
        self.metrics.end_time = time.time()

    def record_llm_call(
        self, tier: str, tokens: int = 0,
        duration_ms: float = 0, phase: str = "",
    ) -> None:
        """Record an LLM call."""
        self.metrics.total_llm_calls += 1
        self.metrics.total_tokens += tokens
        self.metrics.llm_time_ms += duration_ms

        if tier == "fast":
            self.metrics.fast_model_calls += 1
        elif tier == "reasoning":
            self.metrics.reasoning_model_calls += 1

        if phase == "plan":
            self.metrics.planning_calls += 1
        elif phase == "verify":
            self.metrics.verification_calls += 1
        elif phase == "recover":
            self.metrics.recovery_calls += 1

    def record_browser_action(
        self, action: str, success: bool = True,
        duration_ms: float = 0,
    ) -> None:
        """Record a browser action execution."""
        self.metrics.total_actions += 1
        self.metrics.browser_time_ms += duration_ms
        if success:
            self.metrics.successful_actions += 1
        else:
            self.metrics.failed_actions += 1

    def record_screenshot(self) -> None:
        self.metrics.screenshots_taken += 1

    def record_dom_extraction(self) -> None:
        self.metrics.dom_extractions += 1

    def record_recovery(self) -> None:
        self.metrics.recovery_attempts += 1

    def record_checkpoint(self) -> None:
        self.metrics.checkpoints_validated += 1

    def set_plan_info(self, planned_steps: int) -> None:
        self.metrics.planned_steps = planned_steps

    def summary(self) -> str:
        """Generate a formatted performance summary."""
        m = self.metrics
        lines = [
            "",
            "╔══════════════════════════════════════╗",
            "║       TASK PERFORMANCE REPORT        ║",
            "╠══════════════════════════════════════╣",
            f"║ Total time:        {m.total_time_sec:>8.1f}s        ║",
            f"║ Browser time:      {m.browser_time_sec:>8.1f}s        ║",
            f"║ LLM time:          {m.llm_time_sec:>8.1f}s        ║",
            "╠══════════════════════════════════════╣",
            f"║ LLM calls:         {m.total_llm_calls:>8d}         ║",
            f"║   Fast calls:      {m.fast_model_calls:>8d}         ║",
            f"║   Reasoning calls: {m.reasoning_model_calls:>8d}         ║",
            f"║   Planning:        {m.planning_calls:>8d}         ║",
            f"║   Verification:    {m.verification_calls:>8d}         ║",
            f"║   Recovery:        {m.recovery_calls:>8d}         ║",
            "╠══════════════════════════════════════╣",
            f"║ Total tokens:      {m.total_tokens:>8d}         ║",
            "╠══════════════════════════════════════╣",
            f"║ Browser actions:   {m.total_actions:>8d}         ║",
            f"║   Successful:      {m.successful_actions:>8d}         ║",
            f"║   Failed:          {m.failed_actions:>8d}         ║",
            f"║ Screenshots:       {m.screenshots_taken:>8d}         ║",
            f"║ DOM extractions:   {m.dom_extractions:>8d}         ║",
            "╠══════════════════════════════════════╣",
            f"║ Planned steps:     {m.planned_steps:>8d}         ║",
            f"║ Executed steps:    {m.executed_steps:>8d}         ║",
            f"║ Checkpoints:       {m.checkpoints_validated:>8d}         ║",
            f"║ Recovery attempts: {m.recovery_attempts:>8d}         ║",
            "╚══════════════════════════════════════╝",
            "",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return metrics as a dictionary for logging/UI."""
        m = self.metrics
        return {
            "total_time_sec": m.total_time_sec,
            "browser_time_sec": m.browser_time_sec,
            "llm_time_sec": m.llm_time_sec,
            "total_llm_calls": m.total_llm_calls,
            "fast_model_calls": m.fast_model_calls,
            "reasoning_model_calls": m.reasoning_model_calls,
            "total_tokens": m.total_tokens,
            "total_actions": m.total_actions,
            "successful_actions": m.successful_actions,
            "failed_actions": m.failed_actions,
            "screenshots": m.screenshots_taken,
            "dom_extractions": m.dom_extractions,
            "recovery_attempts": m.recovery_attempts,
            "planned_steps": m.planned_steps,
            "executed_steps": m.executed_steps,
            "checkpoints_validated": m.checkpoints_validated,
        }
