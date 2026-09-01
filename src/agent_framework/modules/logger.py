"""
Module 10 — Logger & Experiment Tracker
========================================
Records every step of every task run with full traceability.

Storage:
    - Supabase Cloud (PostgreSQL): experiment_runs, action_steps, prompt_repairs tables
    - SQLite (async via aiosqlite): local experiment_runs, action_steps, prompt_repairs tables
    - JSONL trace files: logs/runs/{run_id}/trace.jsonl (one record per step)
    - CSV export on task completion

Pipeline position: All modules -> Logger (fire-and-forget)
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

from ..config import AgentConfig, default_config
from ..models import ActionObject, PageState, RepairAmendment, VerificationResult

logger = logging.getLogger(__name__)

# ── SQL Schemas ───────────────────────────────────────────────────────────────

_CREATE_EXPERIMENT_RUNS = """
CREATE TABLE IF NOT EXISTS experiment_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    UNIQUE NOT NULL,
    task_goal       TEXT    NOT NULL,
    strategy        TEXT    NOT NULL,
    started_at      DATETIME NOT NULL,
    completed_at    DATETIME,
    status          TEXT    DEFAULT 'running',
    total_actions   INTEGER DEFAULT 0,
    total_retries   INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    completion_time_sec REAL
);
"""

_CREATE_ACTION_STEPS = """
CREATE TABLE IF NOT EXISTS action_steps (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT    NOT NULL,
    step_index            INTEGER NOT NULL,
    sub_task_type         TEXT,
    prompt_used           TEXT,
    action_taken          TEXT,
    page_state_snapshot   TEXT,
    verification_status   TEXT,
    verification_reason   TEXT,
    tokens_used           INTEGER DEFAULT 0,
    duration_ms           INTEGER DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES experiment_runs(run_id)
);
"""

_CREATE_PROMPT_REPAIRS = """
CREATE TABLE IF NOT EXISTS prompt_repairs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT    NOT NULL,
    step_index       INTEGER NOT NULL,
    failure_reason   TEXT,
    original_prompt  TEXT,
    repair_amendment TEXT,
    repaired_prompt  TEXT,
    repair_strategy  TEXT,
    FOREIGN KEY (run_id) REFERENCES experiment_runs(run_id)
);
"""


class ExperimentLogger:
    """
    Module 10: Dual Supabase + SQLite + JSONL experiment tracker.

    Usage:
        logger = ExperimentLogger(config)
        run_id = await logger.start_run("Find laptops under 60k", "dynamic")
        await logger.log_step(run_id, step_index, ...)
        await logger.end_run(run_id, status="success")
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self._db_path = config.db_path
        self._log_dir = Path(config.log_dir)
        self._initialized = False
        self._supabase_client: Any = None

    def _get_supabase(self) -> Any:
        """Lazily initialize Supabase client if configured."""
        if self._supabase_client is not None:
            return self._supabase_client

        if self.config.storage_backend in ("supabase", "dual"):
            url = self.config.supabase_url
            key = self.config.supabase_key
            if url and key and not url.startswith("https://your-project"):
                try:
                    from supabase import create_client
                    self._supabase_client = create_client(url, key)
                    logger.info(f"[M10] Supabase client initialized for {url}")
                except Exception as e:
                    logger.warning(f"[M10] Supabase init failed: {e}")
        return self._supabase_client

    async def _ensure_init(self) -> None:
        """Create local DB and tables on first use."""
        if self._initialized:
            return
        if aiosqlite and self.config.storage_backend in ("sqlite", "dual"):
            try:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(_CREATE_EXPERIMENT_RUNS)
                    await db.execute(_CREATE_ACTION_STEPS)
                    await db.execute(_CREATE_PROMPT_REPAIRS)
                    await db.commit()
                logger.info(f"[M10] SQLite initialized at {self._db_path}")
            except Exception as e:
                logger.warning(f"[M10] SQLite init failed: {e}")
        self._initialized = True

    # ── Run Lifecycle ─────────────────────────────────────────────

    async def start_run(self, task_goal: str, strategy: str) -> str:
        """
        Create a new experiment run record.

        Returns:
            run_id (UUID string).
        """
        await self._ensure_init()
        run_id = str(uuid.uuid4())[:8]  # short 8-char ID
        now = datetime.utcnow().isoformat()

        # Local SQLite
        if aiosqlite and self.config.storage_backend in ("sqlite", "dual"):
            try:
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(
                        """INSERT INTO experiment_runs
                           (run_id, task_goal, strategy, started_at, status)
                           VALUES (?, ?, ?, ?, 'running')""",
                        (run_id, task_goal, strategy, now),
                    )
                    await db.commit()
            except Exception as e:
                logger.warning(f"[M10] SQLite start_run error: {e}")

        # Supabase Cloud
        supabase = self._get_supabase()
        if supabase:
            try:
                payload = {
                    "run_id": run_id,
                    "task_goal": task_goal,
                    "strategy": strategy,
                    "started_at": now,
                    "status": "running",
                }
                await asyncio.to_thread(
                    lambda: supabase.table("experiment_runs").insert(payload).execute()
                )
            except Exception as e:
                logger.warning(f"[M10] Supabase start_run sync error: {e}")

        # Create JSONL trace file
        run_dir = self._log_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[M10] Run started: {run_id} | strategy={strategy}")
        return run_id

    async def end_run(
        self,
        run_id: str,
        status: str,
        total_actions: int = 0,
        total_retries: int = 0,
        total_tokens: int = 0,
        completion_time_sec: float = 0.0,
    ) -> None:
        """Finalize a run record."""
        await self._ensure_init()
        now = datetime.utcnow().isoformat()

        # Local SQLite
        if aiosqlite and self.config.storage_backend in ("sqlite", "dual"):
            try:
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(
                        """UPDATE experiment_runs SET
                           completed_at=?, status=?, total_actions=?,
                           total_retries=?, total_tokens=?, completion_time_sec=?
                           WHERE run_id=?""",
                        (now, status, total_actions, total_retries,
                         total_tokens, completion_time_sec, run_id),
                    )
                    await db.commit()
            except Exception as e:
                logger.warning(f"[M10] SQLite end_run error: {e}")

        # Supabase Cloud
        supabase = self._get_supabase()
        if supabase:
            try:
                update_payload = {
                    "completed_at": now,
                    "status": status,
                    "total_actions": total_actions,
                    "total_retries": total_retries,
                    "total_tokens": total_tokens,
                    "completion_time_sec": completion_time_sec,
                }
                await asyncio.to_thread(
                    lambda: supabase.table("experiment_runs")
                    .update(update_payload)
                    .eq("run_id", run_id)
                    .execute()
                )
            except Exception as e:
                logger.warning(f"[M10] Supabase end_run sync error: {e}")

        if self.config.export_csv_on_complete:
            await self._export_csv(run_id)

        logger.info(f"[M10] Run {run_id} ended: {status} | {total_actions} actions | {total_tokens} tokens")

    # ── Step Logging ──────────────────────────────────────────────

    async def log_step(
        self,
        run_id: str,
        step_index: int,
        sub_task_type: str,
        prompt_used: str,
        action: Optional[ActionObject] = None,
        page_state: Optional[PageState] = None,
        verification: Optional[VerificationResult] = None,
        tokens_used: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Log a single pipeline step to SQLite, Supabase, and JSONL."""
        await self._ensure_init()

        action_json = action.model_dump_json() if action else None
        page_json = page_state.model_dump_json() if page_state else None
        v_status = verification.status if verification else None
        v_reason = verification.reason if verification else None

        # Local SQLite
        if aiosqlite and self.config.storage_backend in ("sqlite", "dual"):
            try:
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(
                        """INSERT INTO action_steps
                           (run_id, step_index, sub_task_type, prompt_used, action_taken,
                            page_state_snapshot, verification_status, verification_reason,
                            tokens_used, duration_ms)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, step_index, sub_task_type, prompt_used[:5000],
                         action_json, page_json, v_status, v_reason, tokens_used, duration_ms),
                    )
                    await db.commit()
            except Exception as e:
                logger.warning(f"[M10] SQLite log_step error: {e}")

        # Supabase Cloud
        supabase = self._get_supabase()
        if supabase:
            try:
                step_payload = {
                    "run_id": run_id,
                    "step_index": step_index,
                    "sub_task_type": sub_task_type,
                    "prompt_used": prompt_used[:5000],
                    "action_taken": action.model_dump() if action else None,
                    "page_state_snapshot": page_state.model_dump() if page_state else None,
                    "verification_status": v_status,
                    "verification_reason": v_reason,
                    "tokens_used": tokens_used,
                    "duration_ms": duration_ms,
                }
                await asyncio.to_thread(
                    lambda: supabase.table("action_steps").insert(step_payload).execute()
                )
            except Exception as e:
                logger.warning(f"[M10] Supabase log_step sync error: {e}")

        # JSONL trace
        await self._append_jsonl(run_id, {
            "step": step_index,
            "sub_task_type": sub_task_type,
            "action": action.model_dump() if action else None,
            "verification": {"status": v_status, "reason": v_reason},
            "tokens_used": tokens_used,
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def log_repair(
        self,
        run_id: str,
        step_index: int,
        failure_reason: str,
        original_prompt: str,
        amendment: RepairAmendment,
        repaired_prompt: str,
    ) -> None:
        """Log a prompt repair event to SQLite, Supabase, and JSONL."""
        await self._ensure_init()

        # Local SQLite
        if aiosqlite and self.config.storage_backend in ("sqlite", "dual"):
            try:
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(
                        """INSERT INTO prompt_repairs
                           (run_id, step_index, failure_reason, original_prompt,
                            repair_amendment, repaired_prompt, repair_strategy)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, step_index, failure_reason, original_prompt[:5000],
                         amendment.model_dump_json(), repaired_prompt[:5000],
                         amendment.amendment_type),
                    )
                    await db.commit()
            except Exception as e:
                logger.warning(f"[M10] SQLite log_repair error: {e}")

        # Supabase Cloud
        supabase = self._get_supabase()
        if supabase:
            try:
                repair_payload = {
                    "run_id": run_id,
                    "step_index": step_index,
                    "failure_reason": failure_reason,
                    "original_prompt": original_prompt[:5000],
                    "repair_amendment": amendment.model_dump(),
                    "repaired_prompt": repaired_prompt[:5000],
                    "repair_strategy": amendment.amendment_type,
                }
                await asyncio.to_thread(
                    lambda: supabase.table("prompt_repairs").insert(repair_payload).execute()
                )
            except Exception as e:
                logger.warning(f"[M10] Supabase log_repair sync error: {e}")

    # ── Helpers ───────────────────────────────────────────────────

    async def _append_jsonl(self, run_id: str, record: dict) -> None:
        trace_path = self._log_dir / run_id / "trace.jsonl"
        try:
            async with asyncio.Lock():
                with open(trace_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"[M10] JSONL write failed: {e}")

    async def _export_csv(self, run_id: str) -> None:
        """Export action_steps for this run to a CSV file."""
        if not aiosqlite:
            return
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM action_steps WHERE run_id=?", (run_id,)
                ) as cursor:
                    rows = await cursor.fetchall()

            if not rows:
                return

            csv_path = self._log_dir / run_id / "steps.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows([dict(r) for r in rows])

            logger.info(f"[M10] CSV exported: {csv_path}")
        except Exception as e:
            logger.warning(f"[M10] CSV export failed: {e}")
