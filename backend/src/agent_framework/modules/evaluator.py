"""
Module 11 — Evaluator & Dashboard Data Provider
=================================================
Computes experiment metrics from SQLite and provides DataFrames
for the Streamlit dashboard.

Metrics (per spec §3/M11):
    Task Success Rate (%)      – % of runs with status 'success'
    Average Retries            – mean repair cycles per run
    Average Completion Time(s) – wall-clock mean
    Average Token Usage        – total tokens per run
    Action Accuracy (%)        – % steps with verification_status='success'
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    import aiosqlite
except ImportError:
    aiosqlite = None
import pandas as pd

from ..config import AgentConfig, default_config
from ..models import MetricsSummary

logger = logging.getLogger(__name__)


class Evaluator:
    """
    Module 11: Async metrics engine. Queries SQLite and returns
    MetricsSummary objects or DataFrames for charting.
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config

    # ── Single Run Metrics ────────────────────────────────────────

    async def compute_metrics(self, run_id: str) -> MetricsSummary:
        """
        Compute metrics for a single completed run.

        Args:
            run_id: The 8-char run identifier.

        Returns:
            MetricsSummary for that run.
        """
        async with aiosqlite.connect(self.config.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Run-level stats
            async with db.execute(
                "SELECT * FROM experiment_runs WHERE run_id=?", (run_id,)
            ) as cur:
                run = await cur.fetchone()

            if not run:
                return MetricsSummary(run_id=run_id)

            # Action accuracy
            async with db.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN verification_status='success' THEN 1 ELSE 0 END) as successes
                   FROM action_steps WHERE run_id=?""",
                (run_id,),
            ) as cur:
                acc_row = await cur.fetchone()

        total_actions = acc_row["total"] or 0
        successes = acc_row["successes"] or 0
        action_accuracy = (successes / total_actions * 100) if total_actions > 0 else 0.0

        is_success = 1 if run["status"] == "success" else 0

        return MetricsSummary(
            run_id=run_id,
            strategy=run["strategy"],
            task_success_rate=float(is_success * 100),
            avg_retries=float(run["total_retries"] or 0),
            avg_completion_time_sec=float(run["completion_time_sec"] or 0),
            avg_token_usage=float(run["total_tokens"] or 0),
            action_accuracy=round(action_accuracy, 2),
            total_runs=1,
        )

    # ── Strategy Comparison ───────────────────────────────────────

    async def compare_strategies(self) -> pd.DataFrame:
        """
        Aggregate metrics across all completed runs, grouped by strategy.

        Returns:
            DataFrame with columns:
            strategy | task_success_rate | avg_retries | avg_completion_time_sec
            | avg_token_usage | action_accuracy | total_runs
        """
        async with aiosqlite.connect(self.config.db_path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute(
                """SELECT
                    r.strategy,
                    COUNT(*) as total_runs,
                    AVG(CASE WHEN r.status='success' THEN 1.0 ELSE 0.0 END) * 100 as task_success_rate,
                    AVG(r.total_retries) as avg_retries,
                    AVG(r.completion_time_sec) as avg_completion_time_sec,
                    AVG(r.total_tokens) as avg_token_usage
                   FROM experiment_runs r
                   WHERE r.status IN ('success', 'failed', 'partial')
                   GROUP BY r.strategy
                   ORDER BY task_success_rate DESC"""
            ) as cur:
                rows = await cur.fetchall()

            # Action accuracy per strategy
            async with db.execute(
                """SELECT
                    r.strategy,
                    CAST(SUM(CASE WHEN s.verification_status='success' THEN 1 ELSE 0 END) AS REAL)
                    / NULLIF(COUNT(s.id), 0) * 100 as action_accuracy
                   FROM action_steps s
                   JOIN experiment_runs r ON s.run_id = r.run_id
                   GROUP BY r.strategy"""
            ) as cur:
                acc_rows = await cur.fetchall()

        acc_map = {r["strategy"]: round(r["action_accuracy"] or 0, 2) for r in acc_rows}

        data = []
        for row in rows:
            strat = row["strategy"]
            data.append({
                "strategy": strat,
                "total_runs": row["total_runs"],
                "task_success_rate": round(row["task_success_rate"] or 0, 2),
                "avg_retries": round(row["avg_retries"] or 0, 2),
                "avg_completion_time_sec": round(row["avg_completion_time_sec"] or 0, 2),
                "avg_token_usage": round(row["avg_token_usage"] or 0, 0),
                "action_accuracy": acc_map.get(strat, 0.0),
            })

        if not data:
            return pd.DataFrame(columns=[
                "strategy", "total_runs", "task_success_rate", "avg_retries",
                "avg_completion_time_sec", "avg_token_usage", "action_accuracy",
            ])

        return pd.DataFrame(data)

    # ── Run History ───────────────────────────────────────────────

    async def get_run_history(self, limit: int = 50) -> pd.DataFrame:
        """Return the most recent N runs as a DataFrame."""
        async with aiosqlite.connect(self.config.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT run_id, task_goal, strategy, status, started_at,
                          total_actions, total_retries, total_tokens, completion_time_sec
                   FROM experiment_runs
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    async def get_run_steps(self, run_id: str) -> pd.DataFrame:
        """Return all action steps for a specific run."""
        async with aiosqlite.connect(self.config.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM action_steps WHERE run_id=? ORDER BY step_index",
                (run_id,),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    async def get_run_repairs(self, run_id: str) -> pd.DataFrame:
        """Return all repair events for a specific run."""
        async with aiosqlite.connect(self.config.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM prompt_repairs WHERE run_id=? ORDER BY step_index",
                (run_id,),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])
