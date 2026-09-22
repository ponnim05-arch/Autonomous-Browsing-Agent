import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.config import AgentConfig
from agent_framework.models import ActionObject, PageState, RepairAmendment, VerificationResult
from agent_framework.modules.logger import ExperimentLogger


def test_logger_jsonl_lifecycle(tmp_path):
    db_path = str(tmp_path / "test.db")
    log_dir = str(tmp_path / "runs")
    config = AgentConfig(db_path=db_path, log_dir=log_dir, storage_backend="sqlite")
    logger = ExperimentLogger(config)

    run_id = asyncio.run(logger.start_run("Find laptops under 60k", "dynamic"))
    assert run_id is not None
    assert len(run_id) == 8

    # Log step
    action = ActionObject(action="navigate", value="https://google.com")
    page_state = PageState(url="https://google.com", title="Google", interactive_elements=[])
    verification = VerificationResult(status="pass", reason="Loaded")

    asyncio.run(logger.log_step(
        run_id=run_id,
        step_index=1,
        sub_task_type="navigate",
        prompt_used="Go to google",
        action=action,
        page_state=page_state,
        verification=verification,
        tokens_used=150,
        duration_ms=500,
    ))

    # Log repair
    amendment = RepairAmendment(
        amendment_type="selector_repair",
        corrective_instruction="Use #search instead",
        new_strategy="dynamic",
        retry_count=1,
    )
    asyncio.run(logger.log_repair(
        run_id=run_id,
        step_index=1,
        failure_reason="Selector failed",
        original_prompt="Click button",
        amendment=amendment,
        repaired_prompt="Click #search",
    ))

    # End run
    asyncio.run(logger.end_run(
        run_id=run_id,
        status="success",
        total_actions=1,
        total_retries=0,
        total_tokens=150,
        completion_time_sec=1.5,
    ))

    trace_file = Path(log_dir) / run_id / "trace.jsonl"
    assert trace_file.exists()


def test_logger_supabase_sync(tmp_path):
    db_path = str(tmp_path / "test.db")
    log_dir = str(tmp_path / "runs")
    config = AgentConfig(
        db_path=db_path,
        log_dir=log_dir,
        storage_backend="supabase",
    )
    logger = ExperimentLogger(config)

    # Mock supabase client
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[])

    logger._supabase_client = mock_supabase

    run_id = asyncio.run(logger.start_run("Test Supabase Goal", "dynamic"))
    assert mock_supabase.table.called
    assert mock_supabase.table.call_args[0][0] == "experiment_runs"

    action = ActionObject(action="click", selector="#btn")
    asyncio.run(logger.log_step(
        run_id=run_id,
        step_index=1,
        sub_task_type="action",
        prompt_used="Click",
        action=action,
    ))
    assert mock_supabase.table.call_args[0][0] == "action_steps"

    asyncio.run(logger.end_run(run_id=run_id, status="success"))
    assert mock_supabase.table.call_args[0][0] == "experiment_runs"
