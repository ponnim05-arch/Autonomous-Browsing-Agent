"""
models.py — Pydantic schemas for all inter-module data objects.

Each model corresponds to a handoff point in the pipeline data-flow:
    GoalObject      : M1 -> M2
    SubTask         : M2 -> M3
    StrategyContext : M3 -> M4
    PromptContext   : M4 (internal)
    ActionObject    : M4/M7 -> M5
    InteractiveEl   : used inside PageState
    PageState       : M6 -> M7/M8
    VerificationResult : M8 -> M9
    RepairInput     : M9 (internal input)
    RepairAmendment : M9 -> M4
    RunStep         : All -> M10
    MetricsSummary  : M11 output
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── M1 Output ─────────────────────────────────────────────────────────────────

class GoalObject(BaseModel):
    task_type: str                          # e.g. "product_search"
    domain: str                             # e.g. "laptops"
    constraints: dict[str, Any] = Field(default_factory=dict)
    output_format: str = "text"             # e.g. "comparison_table"
    success_criteria: str = ""


# ── M2 Output ─────────────────────────────────────────────────────────────────

class SubTask(BaseModel):
    step: int
    type: str   # search | navigate | filter | extract | compare | verify
    goal: str


# ── M3 Output ─────────────────────────────────────────────────────────────────

class StrategyContext(BaseModel):
    strategy_id: str                        # static | dynamic | self_reflective | failure_recovery
    parameters: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    escalation_history: list[str] = Field(default_factory=list)


# ── M4 Internal ───────────────────────────────────────────────────────────────

class PromptContext(BaseModel):
    goal: GoalObject
    sub_task: SubTask
    page_state: Optional["PageState"] = None
    history: list["ActionObject"] = Field(default_factory=list)
    repair_notes: Optional[str] = None
    strategy: StrategyContext


# ── M5 Input / M7 Output ──────────────────────────────────────────────────────

class ActionObject(BaseModel):
    action: str     # click | type | navigate | scroll | extract | wait
    selector: Optional[str] = None
    value: Optional[str] = None
    timeout_ms: int = 5000


# ── M6 Output ─────────────────────────────────────────────────────────────────

class InteractiveElement(BaseModel):
    id: str                                 # e.g. "e1"
    role: str                               # button | link | textbox | ...
    label: str
    visible: bool = True
    aria_label: Optional[str] = None
    has_bounding_box: bool = True


class PageState(BaseModel):
    url: str
    title: str
    interactive_elements: list[InteractiveElement] = Field(default_factory=list)
    summary_text: str = ""
    screenshot_path: Optional[str] = None
    raw_html_length: int = 0


# ── M8 Output ─────────────────────────────────────────────────────────────────

class VerificationResult(BaseModel):
    status: str                             # success | failure | partial
    reason: str
    expected_outcome: str = ""
    confidence_score: float = 0.0


# ── M9 Input / Output ─────────────────────────────────────────────────────────

class RepairInput(BaseModel):
    original_goal: str
    failed_action: ActionObject
    failure_reason: str
    current_page_state: PageState
    attempt_number: int


class RepairAmendment(BaseModel):
    amendment_type: str     # selector_repair | goal_reframing | alternative_path | sub_task_skip
    corrective_instruction: str
    new_strategy: str
    retry_count: int


# ── M10 Log Record ────────────────────────────────────────────────────────────

class RunStep(BaseModel):
    run_id: str
    step_index: int
    sub_task_type: str
    prompt_used: str
    action_taken: Optional[ActionObject] = None
    page_state_snapshot: Optional[PageState] = None
    verification_status: Optional[str] = None
    verification_reason: Optional[str] = None
    tokens_used: int = 0
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── M11 Output ────────────────────────────────────────────────────────────────

class MetricsSummary(BaseModel):
    run_id: Optional[str] = None           # None → aggregate across all runs
    strategy: Optional[str] = None
    task_success_rate: float = 0.0         # %
    avg_retries: float = 0.0
    avg_completion_time_sec: float = 0.0
    avg_token_usage: float = 0.0
    action_accuracy: float = 0.0           # %
    total_runs: int = 0


# ── Search ────────────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


# Allow forward references to resolve
PromptContext.model_rebuild()
