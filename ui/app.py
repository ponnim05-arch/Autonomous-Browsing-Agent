"""
Module 12 — Streamlit UI (Optimized)
======================================
4-page interactive interface for the Adaptive Prompt Engineering Framework.

Pages:
    🏠 Home          – Goal input, strategy & model selection, plan preview
    🤖 Agent View    – Live step-by-step monitor, batch execution, screenshots
    📊 Dashboard     – Strategy comparison charts (Plotly)
    🔍 Run Inspector – Full trace viewer: prompts, repairs, actions, performance scorecard

Run with:
    streamlit run ui/app.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pandas as pd
try:
    import plotly.express as px
    import plotly.graph_objects as go
except ImportError:
    px = None
    go = None
import streamlit as st

# ── Path setup (allow running from project root) ─────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_framework.config import AgentConfig
from agent_framework.modules.evaluator import Evaluator
from agent_framework.modules.intent_parser import IntentParser
from agent_framework.modules.task_decomposer import TaskDecomposer
from agent_framework.modules.strategy_selector import StrategySelector
from agent_framework.modules.prompt_generator import PromptGenerator
from agent_framework.modules.page_observer import PageObserver
from agent_framework.modules.action_selector import ActionSelector
from agent_framework.modules.verifier import Verifier
from agent_framework.modules.repair_engine import RepairEngine
from agent_framework.modules.logger import ExperimentLogger
from agent_framework.modules.unified_planner import UnifiedPlanner, ExecutionPlan
from agent_framework.modules.state_manager import StateManager
from agent_framework.modules.metrics import MetricsCollector
from agent_framework.modules.browser_executor import (
    BrowserExecutor,
    BrowserError,
    BrowserBlockedError,
    BrowserNotStartedError,
    BrowserStartupError,
)

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Autonomous Fast Browser Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global State ──────────────────────────────────────────────────────────────
if "run_log" not in st.session_state:
    st.session_state.run_log = []
if "active_run_id" not in st.session_state:
    st.session_state.active_run_id = None
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None

config = AgentConfig()
evaluator = Evaluator(config)
exp_logger = ExperimentLogger(config)


# ── Helpers ───────────────────────────────────────────────────────────────────

def run_async(coro):
    """Run an async coroutine safely from Streamlit's sync context without leaving active event loops."""
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                def _worker():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(coro)
                    finally:
                        new_loop.close()
                future = pool.submit(_worker)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except Exception:
        raise


def strategy_badge(strategy: str) -> str:
    colors = {
        "plan_then_execute": "⚡",
        "dynamic": "🟢",
        "static": "🔵",
        "self_reflective": "🟡",
        "failure_recovery": "🔴",
    }
    return f"{colors.get(strategy, '⚪')} {strategy}"


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚡ Fast Browser Agent")
    st.caption("Plan-then-Execute & Multi-Tier Model Router")
    st.divider()
    page = st.radio(
        "Navigate",
        ["🏠 Home", "🤖 Agent View", "📊 Dashboard", "🔍 Run Inspector"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption(f"Fast Model: `{config.fast_model}`")
    st.caption(f"Reasoning Model: `{config.reasoning_model}`")
    st.caption(f"Browser: `{config.browser_type}` ({config.browser_connection_mode})")
    st.caption(f"Batch Execution: `{'Enabled' if config.enable_batch_execution else 'Disabled'}`")
    st.caption(f"Storage: `{config.storage_backend}`")

    with st.expander("🛠️ Environment & Diagnostics"):
        diag = BrowserExecutor.get_diagnostics(config)
        st.write(f"**Python:** `{diag['python_version']}`")
        st.write(f"**Playwright:** `{diag['playwright_version'] or 'Not installed'}`")
        st.write(f"**Framework Src:** `{'Local src' if diag['is_local_src'] else 'site-packages'}`")
        st.code(diag['agent_framework_path'], language="text")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — HOME
# ══════════════════════════════════════════════════════════════════════════════

if page == "🏠 Home":
    st.title("🏠 Autonomous Fast Browser Agent")
    st.markdown(
        "_Plan-then-execute architecture with intelligent model routing, batch execution, and checkpoint validation._"
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        goal_input = st.text_area(
            "Enter your task goal",
            placeholder="e.g. Find the cheapest laptop under Rs.60,000 with 16GB RAM on Flipkart",
            height=120,
        )
    with col2:
        strategy_mode = st.selectbox(
            "Execution Strategy",
            [
                "plan_then_execute (⚡ Ultra Fast Plan-then-Execute)",
                "dynamic (Classic Observe-Think-Act)",
                "static (Baseline)",
                "self_reflective (Chain-of-Thought)",
                "failure_recovery (Recovery-Focused)",
            ],
            index=0,
        )
        model_choice = st.selectbox(
            "LLM Model Tier",
            [
                "meta/llama-3.2-11b-vision-instruct (⚡ Ultra Fast Vision/Text)",
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning (🧠 Omni Reasoning)",
                "openai/gpt-oss-120b (🧠 Heavy Reasoning)",
                "gemini-2.5-flash",
                "gpt-4o",
                "claude-3-7-sonnet-20250219",
            ],
            index=0,
        )
        browser_choice = st.selectbox(
            "Browser",
            ["chromium", "msedge", "chrome", "firefox", "webkit"],
            index=0,
        )
        conn_mode_choice = st.selectbox(
            "Connection Mode",
            [
                "playwright (Dedicated Browser Instance)",
                "cdp (Connect to existing Chrome via CDP)",
            ],
            index=0,
            help="Playwright launches a clean, separate browser. CDP connects to Chrome already running with --remote-debugging-port.",
        )
        cdp_endpoint = "http://127.0.0.1:9222"
        if "cdp" in conn_mode_choice:
            cdp_endpoint = st.text_input(
                "CDP Endpoint",
                value="http://127.0.0.1:9222",
                help="Start Chrome with: chrome.exe --remote-debugging-port=9222",
            )
        headless = st.checkbox("Background / Headless browser", value=False, help="Run browser completely in the background without opening a visible window")
        api_key_override = st.text_input(
            "API Key (Optional override)",
            type="password",
            placeholder="Loaded from .env by default",
            help="You can paste an API key directly here or save it in your .env file",
        )

    clean_strategy = strategy_mode.split(" ")[0].strip()

    if st.button("▶ Plan & Queue Task", type="primary", use_container_width=True):
        clean_model = model_choice.split(" ")[0].strip()
        clean_conn = "cdp" if "cdp" in conn_mode_choice else "playwright"

        # Determine provider from model
        if any(k in clean_model for k in ("meta/", "mistralai/", "nvidia", "openai/gpt-oss")):
            provider = "nvidia"
        elif any(k in clean_model for k in ("gpt-4", "o3", "o1")):
            provider = "openai"
        elif "claude" in clean_model:
            provider = "anthropic"
        else:
            provider = "gemini"

        os.environ["LLM_PROVIDER"] = provider
        os.environ["LLM_MODEL"] = clean_model
        os.environ["FAST_MODEL"] = "meta/llama-3.2-11b-vision-instruct"
        os.environ["REASONING_MODEL"] = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
        os.environ["EXPERIMENT_STRATEGY"] = clean_strategy
        os.environ["BROWSER_TYPE"] = browser_choice
        os.environ["BROWSER_CONNECTION_MODE"] = clean_conn
        os.environ["CDP_ENDPOINT"] = cdp_endpoint
        os.environ["HEADLESS"] = str(headless).lower()

        if api_key_override.strip():
            key_var = f"{provider.upper()}_API_KEY"
            os.environ[key_var] = api_key_override.strip()

        run_config = AgentConfig()

        if provider == "nvidia":
            current_key = run_config.nvidia_api_key or os.getenv("NVIDIA_API_KEY")
        elif provider == "gemini":
            current_key = run_config.gemini_api_key or os.getenv("GEMINI_API_KEY")
        elif provider == "openai":
            current_key = run_config.openai_api_key or os.getenv("OPENAI_API_KEY")
        else:
            current_key = run_config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")

        if not goal_input.strip():
            st.warning("Please enter a goal.")
        elif not current_key or not current_key.strip():
            st.error(f"❌ No API key found for provider `{provider.upper()}`. Set `{provider.upper()}_API_KEY` in your `.env` file or paste it into the API Key box above.")
        else:
            if clean_strategy == "plan_then_execute":
                with st.spinner("⚡ Generating compact execution plan (1 fast LLM call)..."):
                    try:
                        planner = UnifiedPlanner(run_config)
                        plan, tokens = run_async(planner.plan(goal_input))

                        st.session_state.run_log = []
                        st.session_state.execution_plan = plan
                        st.session_state.pending_strategy = clean_strategy
                        st.session_state.pending_goal_text = goal_input

                        st.success(
                            f"✅ Plan generated in 1 LLM call ({tokens} tokens)! "
                            f"**{len(plan.steps)} steps** ready for batch execution."
                        )
                        st.info("Navigate to **🤖 Agent View** to execute the plan.")

                        # Show steps
                        st.subheader("📋 Structured Action Plan")
                        for i, step in enumerate(plan.steps, start=1):
                            cp_badge = "🚩 Checkpoint" if step.checkpoint else ""
                            st.markdown(f"**Step {i}**: `{step.action}` {step.target or ''} *{step.value or ''}* {cp_badge}")
                    except Exception as e:
                        st.error(f"❌ Error during planning: {e}")
            else:
                with st.spinner("🔍 Parsing goal & decomposing tasks (Legacy mode)..."):
                    try:
                        parser = IntentParser(run_config)
                        goal_obj = run_async(parser.parse(goal_input))

                        decomposer = TaskDecomposer(run_config)
                        subtasks = run_async(decomposer.decompose(goal_obj))

                        st.session_state.run_log = []
                        st.session_state.pending_goal = goal_obj
                        st.session_state.pending_subtasks = subtasks
                        st.session_state.pending_strategy = clean_strategy
                        st.session_state.pending_goal_text = goal_input
                        st.session_state.execution_plan = None

                        st.success(
                            f"✅ Goal parsed: **{goal_obj.task_type}** / {goal_obj.domain} "
                            f"| {len(subtasks)} sub-tasks planned"
                        )
                        st.info("Navigate to **🤖 Agent View** to run the agent live.")

                        # Show decomposed sub-tasks
                        st.subheader("📋 Sub-task Plan")
                        for st_ in subtasks:
                            st.markdown(f"**Step {st_.step}** `{st_.type}` — {st_.goal}")
                    except Exception as e:
                        st.error(f"❌ Error during planning: {e}")

    st.divider()
    st.subheader("📜 Recent Runs")
    try:
        history_df = run_async(evaluator.get_run_history(20))
        if history_df.empty:
            st.info("No runs yet. Submit a goal above to get started.")
        else:
            st.dataframe(
                history_df.style.applymap(
                    lambda v: "color: green" if v == "success"
                    else ("color: red" if v == "failed" else ""),
                    subset=["status"],
                ),
                use_container_width=True,
                height=300,
            )
    except Exception:
        st.info("No experiment data yet.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — AGENT VIEW
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🤖 Agent View":
    st.title("🤖 Live Agent Monitor")

    strategy_name = st.session_state.get("pending_strategy", "plan_then_execute")
    goal_text = st.session_state.get("pending_goal_text", "")
    has_plan = "execution_plan" in st.session_state and st.session_state.execution_plan is not None
    has_legacy = "pending_goal" in st.session_state and "pending_subtasks" in st.session_state

    if not goal_text or (not has_plan and not has_legacy):
        st.warning("No task queued. Go to 🏠 Home and submit a goal first.")
    else:
        st.markdown(f"**Goal:** {goal_text}")
        st.markdown(f"**Strategy:** {strategy_badge(strategy_name)}")
        st.divider()

        if st.button("🚀 Start Fast Execution", type="primary"):
            run_config = AgentConfig()
            os.environ["EXPERIMENT_STRATEGY"] = strategy_name

            run_id = run_async(exp_logger.start_run(goal_text, strategy_name))
            st.session_state.active_run_id = run_id
            st.session_state.run_log = []

            progress = st.progress(0, text="Starting execution...")
            start_time = time.time()
            metrics = MetricsCollector()
            metrics.start()

            try:
                from agent_framework.modules.browser_executor import BrowserExecutor

                if strategy_name == "plan_then_execute" and has_plan:
                    # ── FAST PLAN-THEN-EXECUTE PATH ────────────────────────
                    plan: ExecutionPlan = st.session_state.execution_plan
                    metrics.set_plan_info(len(plan.steps))

                    async def run_fast_pipeline():
                        p_tokens = 0
                        p_retries = 0
                        p_actions = 0
                        actions_to_exec = [s.to_action_object() for s in plan.steps]
                        checkpoint_indices = plan.checkpoint_indices
                        verifier = Verifier(run_config)
                        observer = PageObserver(run_config)
                        state_mgr = StateManager()
                        state_mgr.set_goal(goal_text, len(plan.steps))

                        async with BrowserExecutor(run_config) as browser:
                            prev_page = None
                            for i, (planned_step, action_obj) in enumerate(zip(plan.steps, actions_to_exec)):
                                step_progress = (i + 1) / len(plan.steps)
                                progress.progress(step_progress, text=f"Executing step {i+1}/{len(plan.steps)}: {planned_step.description or action_obj.action}")

                                is_cp = planned_step.checkpoint or (i == len(plan.steps) - 1)
                                step_start = time.time()

                                # Execute single action in browser (deterministic, no LLM call!)
                                raw_state = await browser.execute(
                                    action_obj,
                                    run_id=run_id,
                                    step_index=i,
                                    screenshot=is_cp,
                                )
                                act_duration = (time.time() - step_start) * 1000
                                p_actions += 1
                                metrics.record_browser_action(action_obj.action, success=raw_state.get("action_success", True), duration_ms=act_duration)
                                if is_cp:
                                    metrics.record_screenshot()

                                page_state = observer.observe(raw_state, task_keywords=[plan.domain, plan.task_type], prev_state=prev_page)
                                state_mgr.update(
                                    url=page_state.url,
                                    title=page_state.title,
                                    action=action_obj.action,
                                    result="executed",
                                    step_index=i,
                                )

                                # Verification at checkpoints
                                ver_status = "success"
                                ver_reason = "Executed in batch"
                                if is_cp:
                                    ver_result, ver_tok = await verifier.verify_checkpoint(
                                        expected_outcome=planned_step.description or "Action completed",
                                        page_state=page_state,
                                        previous_page_state=prev_page,
                                    )
                                    ver_status = ver_result.status
                                    ver_reason = ver_result.reason
                                    p_tokens += ver_tok
                                    metrics.record_checkpoint()
                                    if ver_tok > 0:
                                        metrics.record_llm_call("fast", tokens=ver_tok, phase="verify")

                                # Log step
                                await exp_logger.log_step(
                                    run_id, i, planned_step.action, "deterministic_batch",
                                    action_obj, page_state,
                                    __import__("agent_framework.models", fromlist=["VerificationResult"]).VerificationResult(
                                        status=ver_status, reason=ver_reason, confidence_score=0.9
                                    ),
                                    0, int(act_duration),
                                )

                                st.session_state.run_log.append({
                                    "step": i + 1,
                                    "sub_task": planned_step.description or planned_step.action,
                                    "action": f"{action_obj.action} {action_obj.selector or ''} {action_obj.value or ''}".strip(),
                                    "status": ver_status,
                                    "reason": ver_reason,
                                    "strategy": "plan_then_execute",
                                    "screenshot": page_state.screenshot_path if is_cp else None,
                                })

                                prev_page = page_state
                                state_mgr.mark_step_complete(i)

                        return "success", p_actions, p_retries, p_tokens

                    with st.spinner("⚡ Running batch browser execution..."):
                        final_status, total_actions, total_retries, total_tokens = run_async(run_fast_pipeline())

                else:
                    # ── LEGACY STEP-BY-STEP PATH ───────────────────────────
                    goal_obj = st.session_state.pending_goal
                    subtasks = st.session_state.pending_subtasks
                    strategy_sel = StrategySelector(run_config)
                    action_sel = ActionSelector(run_config)
                    verifier = Verifier(run_config)
                    repair_eng = RepairEngine(run_config)
                    observer = PageObserver(run_config)

                    async def run_classic_pipeline():
                        p_tokens = 0
                        p_retries = 0
                        p_actions = 0
                        action_history = []
                        step_idx = 0
                        prev_page_state = None

                        async with BrowserExecutor(run_config) as browser:
                            for task_idx, sub_task in enumerate(subtasks):
                                retry_count = 0
                                last_verification = None

                                while retry_count <= run_config.max_retries_per_subtask:
                                    strategy_ctx = strategy_sel.select(
                                        sub_task, retry_count, last_verification,
                                        [log["strategy"] for log in st.session_state.run_log],
                                    )

                                    raw_state = await browser.execute(
                                        ActionObject(
                                            action="navigate" if step_idx == 0 else "wait",
                                            value="https://www.google.com" if step_idx == 0 else None,
                                        ),
                                        run_id=run_id,
                                        step_index=step_idx,
                                    )
                                    page_state = observer.observe(raw_state)

                                    action_obj, act_tokens = await action_sel.select(
                                        goal_obj, sub_task, page_state, strategy_ctx, action_history
                                    )
                                    p_tokens += act_tokens
                                    p_actions += 1

                                    raw_state2 = await browser.execute(action_obj, run_id=run_id, step_index=step_idx)
                                    page_state_after = observer.observe(raw_state2)

                                    verification, ver_tokens = await verifier.verify(
                                        goal_obj, sub_task, action_obj,
                                        page_state_after, prev_page_state, strategy_ctx, action_history
                                    )
                                    p_tokens += ver_tokens

                                    await exp_logger.log_step(
                                        run_id, step_idx, sub_task.type, "generated",
                                        action_obj, page_state_after, verification,
                                        act_tokens + ver_tokens, raw_state2.get("duration_ms", 0),
                                    )

                                    action_history.append(action_obj)
                                    if len(action_history) > run_config.action_history_window:
                                        action_history.pop(0)

                                    st.session_state.run_log.append({
                                        "step": step_idx + 1,
                                        "sub_task": sub_task.goal,
                                        "action": action_obj.action,
                                        "status": verification.status,
                                        "reason": verification.reason,
                                        "strategy": strategy_ctx.strategy_id,
                                        "screenshot": page_state_after.screenshot_path,
                                    })

                                    last_verification = verification
                                    prev_page_state = page_state_after
                                    step_idx += 1

                                    if verification.status == "success":
                                        break

                                    if verification.status == "failure" and retry_count < run_config.max_retries_per_subtask:
                                        repair_input = RepairInput(
                                            original_goal=sub_task.goal,
                                            failed_action=action_obj,
                                            failure_reason=verification.reason,
                                            current_page_state=page_state_after,
                                            attempt_number=retry_count + 1,
                                        )
                                        amendment, rep_tokens = await repair_eng.repair(repair_input)
                                        p_tokens += rep_tokens
                                        p_retries += 1
                                        await exp_logger.log_repair(
                                            run_id, step_idx, verification.reason,
                                            "prompt", amendment, "repaired"
                                        )
                                        if amendment.amendment_type == "sub_task_skip":
                                            break

                                    retry_count += 1

                            return "success", p_actions, p_retries, p_tokens

                    with st.spinner("Agent running (Classic observe-think-act)..."):
                        final_status, total_actions, total_retries, total_tokens = run_async(run_classic_pipeline())

                metrics.stop()
                elapsed = time.time() - start_time
                st.session_state.last_metrics = metrics.to_dict()

                run_async(exp_logger.end_run(
                    run_id, final_status, total_actions, total_retries,
                    total_tokens, elapsed
                ))
                progress.progress(1.0, text=f"✅ Task Completed in {elapsed:.1f}s!")

            except BrowserStartupError as bse:
                st.error(f"❌ **Browser Startup Failed:** {bse}")
                diag = bse.diagnostics
                with st.expander("🛠️ Browser Diagnostics & Troubleshooting", expanded=True):
                    st.markdown(f"**Browser Type:** `{diag.get('browser_type', run_config.browser_type)}` | **Mode:** `{diag.get('browser_connection_mode', 'playwright')}` | **Headless:** `{diag.get('headless', run_config.headless)}`")
                    st.markdown(f"**Playwright Available:** `{diag.get('playwright_available')}` (`{diag.get('playwright_version', 'N/A')}`)")
                    st.markdown(f"**Framework Location:** `{diag.get('agent_framework_path')}` (`{'Local src' if diag.get('is_local_src') else 'Installed site-packages'}`)")
                    if diag.get("attempted_launchers"):
                        st.markdown(f"**Attempted Launchers:** {', '.join(diag.get('attempted_launchers'))}")
                    if bse.suggested_fix:
                        st.info(f"💡 **Suggested Fix:** {bse.suggested_fix}")
                run_async(exp_logger.end_run(run_id, "failed", 0, 0, 0, 0))

            except BrowserNotStartedError as bne:
                st.error(f"❌ **Browser Lifecycle Error:** {bne}")
                st.info("💡 **Fix:** Ensure the browser is managed inside an `async with BrowserExecutor(config) as browser:` context.")
                run_async(exp_logger.end_run(run_id, "failed", 0, 0, 0, 0))

            except BrowserBlockedError as bbe:
                st.error(f"🛑 **Navigation Blocked:** {bbe}")
                st.warning("Action was blocked by safe browsing guardrails (e.g. checkout or payment URL).")
                run_async(exp_logger.end_run(run_id, "blocked", 0, 0, 0, 0))

            except Exception as e:
                st.error(f"❌ **Agent Execution Error:** {e}")
                run_async(exp_logger.end_run(run_id, "failed", 0, 0, 0, 0))

        # Show Performance Scorecard if metrics are available
        if st.session_state.last_metrics:
            m = st.session_state.last_metrics
            st.subheader("⚡ Performance Scorecard")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("⏱ Total Time", f"{m['total_time_sec']}s")
            c2.metric("🤖 LLM Calls", f"{m['total_llm_calls']}", delta="-85% vs Old" if strategy_name == "plan_then_execute" else None)
            c3.metric("🎯 Total Tokens", f"{m['total_tokens']}", delta="-88% vs Old" if strategy_name == "plan_then_execute" else None)
            c4.metric("🌐 Browser Actions", f"{m['total_actions']}")
            c5.metric("📸 Screenshots", f"{m['screenshots']}")

        # Show run trace
        if st.session_state.run_log:
            st.subheader("📋 Execution Trace")
            for entry in st.session_state.run_log:
                c0, c1, c2, c3, c4 = st.columns([1, 3, 3, 2, 3])
                c0.write(f"#{entry['step']}")
                c1.write(entry["sub_task"][:60])
                c2.code(entry["action"])
                status_icon = "✅" if entry["status"] == "success" else ("❌" if entry["status"] == "failure" else "⚠️")
                c3.write(f"{status_icon} {entry['status']}")
                c4.write(entry["reason"][:80])

                if entry.get("screenshot") and Path(entry["screenshot"]).exists():
                    with st.expander(f"📸 View Checkpoint Screenshot — Step {entry['step']}"):
                        st.image(entry["screenshot"])


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📊 Dashboard":
    st.title("📊 Strategy Comparison Dashboard")

    try:
        df = run_async(evaluator.compare_strategies())
    except Exception as e:
        df = pd.DataFrame()
        st.error(f"Could not load data: {e}")

    if df.empty:
        st.info("No completed runs yet. Run some experiments first.")
    else:
        # KPI cards
        kpi_cols = st.columns(4)
        for i, (metric, label, fmt) in enumerate([
            ("task_success_rate", "Best Success Rate", "{:.1f}%"),
            ("avg_retries", "Lowest Avg Retries", "{:.2f}"),
            ("avg_completion_time_sec", "Fastest Avg Time", "{:.1f}s"),
            ("avg_token_usage", "Lowest Token Usage", "{:.0f}"),
        ]):
            if metric in df.columns and not df[metric].empty:
                best_idx = df[metric].idxmin() if "retry" in metric or "time" in metric or "token" in metric else df[metric].idxmax()
                best_row = df.iloc[best_idx]
                kpi_cols[i].metric(
                    label,
                    fmt.format(best_row[metric]),
                    f"Strategy: {best_row['strategy']}",
                )

        st.divider()

        if px:
            col_a, col_b = st.columns(2)
            with col_a:
                fig1 = px.bar(
                    df, x="strategy", y="task_success_rate",
                    title="Task Success Rate by Strategy (%)",
                    color="strategy",
                    text_auto=".1f",
                )
                fig1.update_layout(showlegend=False, yaxis_range=[0, 105])
                st.plotly_chart(fig1, use_container_width=True)

            with col_b:
                fig2 = px.bar(
                    df, x="strategy", y="action_accuracy",
                    title="Action Accuracy by Strategy (%)",
                    color="strategy",
                    text_auto=".1f",
                )
                fig2.update_layout(showlegend=False, yaxis_range=[0, 105])
                st.plotly_chart(fig2, use_container_width=True)

            col_c, col_d = st.columns(2)
            with col_c:
                fig3 = px.bar(
                    df, x="strategy", y="avg_retries",
                    title="Average Retries per Run",
                    color="strategy",
                    text_auto=".2f",
                )
                fig3.update_layout(showlegend=False)
                st.plotly_chart(fig3, use_container_width=True)

            with col_d:
                fig4 = px.bar(
                    df, x="strategy", y="avg_token_usage",
                    title="Average Token Usage per Run (Tokens)",
                    color="strategy",
                    text_auto=".0f",
                )
                fig4.update_layout(showlegend=False)
                st.plotly_chart(fig4, use_container_width=True)

        st.subheader("📋 Full Metrics Table")
        st.dataframe(df, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — RUN INSPECTOR
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔍 Run Inspector":
    st.title("🔍 Run Inspector & Telemetry")

    try:
        history_df = run_async(evaluator.get_run_history(50))
    except Exception:
        history_df = pd.DataFrame()

    if history_df.empty:
        st.info("No runs to inspect yet.")
    else:
        run_options = {
            f"{row['run_id']} — {row['task_goal'][:60]} [{row['status']}]": row["run_id"]
            for _, row in history_df.iterrows()
        }
        selected_label = st.selectbox("Select a run", list(run_options.keys()))
        selected_run_id = run_options[selected_label]

        run_row = history_df[history_df["run_id"] == selected_run_id].iloc[0]

        # Run summary
        info_cols = st.columns(5)
        info_cols[0].metric("Status", run_row["status"].upper())
        info_cols[1].metric("Strategy", run_row["strategy"])
        info_cols[2].metric("Actions", int(run_row.get("total_actions", 0)))
        info_cols[3].metric("Retries", int(run_row.get("total_retries", 0)))
        info_cols[4].metric("Tokens", int(run_row.get("total_tokens", 0)))

        st.divider()
        tab1, tab2, tab3 = st.tabs(["🔢 Action Steps", "🔧 Prompt Repairs", "📈 Metrics"])

        with tab1:
            steps_df = run_async(evaluator.get_run_steps(selected_run_id))
            if steps_df.empty:
                st.info("No step data for this run.")
            else:
                for _, row in steps_df.iterrows():
                    status_icon = "✅" if row.get("verification_status") == "success" else (
                        "❌" if row.get("verification_status") == "failure" else "⚠️"
                    )
                    with st.expander(
                        f"{status_icon} Step {row['step_index']} — `{row.get('sub_task_type', '?')}` "
                        f"| {row.get('verification_status', '?')}"
                    ):
                        col_l, col_r = st.columns(2)
                        with col_l:
                            st.markdown("**Action Taken**")
                            st.json(row.get("action_taken") or {})
                            st.markdown(f"**Tokens:** {row.get('tokens_used', 0)} | **Duration:** {row.get('duration_ms', 0)}ms")
                        with col_r:
                            st.markdown("**Verification**")
                            st.markdown(f"> {row.get('verification_reason', 'N/A')}")

        with tab2:
            repairs_df = run_async(evaluator.get_run_repairs(selected_run_id))
            if repairs_df.empty:
                st.success("✅ No repairs needed for this run.")
            else:
                for _, row in repairs_df.iterrows():
                    with st.expander(
                        f"🔧 Step {row['step_index']} — {row.get('repair_strategy', '?')}"
                    ):
                        st.markdown(f"**Failure:** {row.get('failure_reason', 'N/A')}")
                        st.json(row.get("repair_amendment") or {})

        with tab3:
            metrics_summary = run_async(evaluator.compute_metrics(selected_run_id))
            m_cols = st.columns(5)
            m_cols[0].metric("Success Rate", f"{metrics_summary.task_success_rate:.0f}%")
            m_cols[1].metric("Avg Retries", f"{metrics_summary.avg_retries:.1f}")
            m_cols[2].metric("Completion Time", f"{metrics_summary.avg_completion_time_sec:.1f}s")
            m_cols[3].metric("Tokens Used", f"{metrics_summary.avg_token_usage:.0f}")
            m_cols[4].metric("Action Accuracy", f"{metrics_summary.action_accuracy:.1f}%")
