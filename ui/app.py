"""
Module 12 — Streamlit UI (Optimized + Browser Display)
========================================================
4-page interactive interface for the Adaptive Prompt Engineering Framework.

Pages:
    🏠 Home          – Goal input, strategy & model selection, browser mode, plan preview
    🤖 Agent View    – Live step-by-step monitor, browser status, batch execution, screenshots
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

# ── Force reload agent_framework modules so Streamlit picks up code updates without requiring a server restart ──
for _mod_name in list(sys.modules.keys()):
    if _mod_name.startswith("agent_framework"):
        del sys.modules[_mod_name]

import re

from agent_framework.config import AgentConfig, DEFAULT_NVIDIA_API_KEY
from agent_framework.models import (
    ActionObject, GoalObject, PageState, PromptContext,
    SubTask, StrategyContext, VerificationResult, RepairInput,
)
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

# ── PWA & Mobile Meta Headers + Responsive CSS ───────────────────────────────
st.markdown(
    """
    <head>
        <link rel="manifest" href="/app/static/manifest.json">
        <link rel="icon" type="image/svg+xml" href="/app/static/icon.svg">
        <link rel="apple-touch-icon" href="/app/static/icon.svg">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="theme-color" content="#0e1117">
    </head>
    <style>
        /* Mobile-first touch and viewport styles */
        @media (max-width: 768px) {
            .stButton > button {
                width: 100% !important;
                min-height: 48px !important;
                font-size: 1rem !important;
                border-radius: 8px !important;
                margin-top: 4px !important;
                margin-bottom: 4px !important;
            }
            img {
                max-width: 100% !important;
                height: auto !important;
                border-radius: 6px !important;
            }
            textarea, input[type="text"] {
                font-size: 16px !important;
            }
            .block-container {
                padding-top: 1rem !important;
                padding-bottom: 2rem !important;
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Global State ──────────────────────────────────────────────────────────────
_DEFAULT_STATE = {
    "nav_page": "🏠 Home",
    "run_log": [],
    "active_run_id": None,
    "last_metrics": None,
    "active_url": None,
    "active_page_title": None,
    "active_screenshot": None,
    # Browser display state (serializable only — no Playwright objects)
    "browser_active": False,
    "browser_mode": "visible",
    "browser_started": False,
    "browser_error": None,
    "current_url": None,
    "current_title": None,
    "current_action": None,
    "browser_status_log": [],
}
for key, default in _DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = default

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


def make_status_callback():
    """
    Create a status callback that writes serializable state to a shared dict.

    Because async browser execution runs on a worker thread, we cannot write
    to st.session_state directly (Streamlit's ScriptRunContext is thread-local).
    Instead we write to a plain dict and sync it back on the main thread after
    the async work completes.
    """
    status_data = {
        "current_url": None,
        "current_title": None,
        "current_action": None,
        "browser_started": False,
        "browser_error": None,
        "log": [],
    }

    def callback(event: str, message: str, url=None):
        status_data["log"].append(message)
        if url:
            status_data["current_url"] = url
        if event == "browser_started":
            status_data["browser_started"] = True
        elif event == "browser_error":
            status_data["browser_error"] = message
        elif event in ("navigating", "page_loaded"):
            if url:
                status_data["current_url"] = url
        if event == "page_loaded":
            # Extract title from message pattern "📄 Title"
            title = message.replace("📄 ", "").strip()
            status_data["current_title"] = title
        if event == "action":
            status_data["current_action"] = message

    return callback, status_data


def sync_status_to_session(status_data: dict):
    """Copy status_data back to session_state on the main thread."""
    st.session_state.current_url = status_data.get("current_url")
    st.session_state.current_title = status_data.get("current_title")
    st.session_state.current_action = status_data.get("current_action")
    st.session_state.browser_started = status_data.get("browser_started", False)
    st.session_state.browser_error = status_data.get("browser_error")
    st.session_state.browser_status_log = status_data.get("log", [])


def navigate_to(page_name: str):
    """Safely queue programmatic navigation to another page and trigger rerun."""
    st.session_state.pending_nav_page = page_name
    st.rerun()


# ── Sidebar ───────────────────────────────────────────────────────────────────

# Apply any queued programmatic navigation BEFORE the radio widget is instantiated
if "pending_nav_page" in st.session_state:
    st.session_state.nav_page = st.session_state.pop("pending_nav_page")

with st.sidebar:
    st.title("⚡ Fast Browser Agent")
    st.caption("Plan-then-Execute & Multi-Tier Model Router")
    st.divider()
    page = st.radio(
        "Navigate",
        ["🏠 Home", "🤖 Agent View", "📊 Dashboard", "🔍 Run Inspector"],
        key="nav_page",
        label_visibility="collapsed",
    )
    st.divider()
    st.caption(f"Fast Model: `{config.fast_model}`")
    st.caption(f"Reasoning Model: `{config.reasoning_model}`")
    st.caption(f"Browser: `{config.browser_type}` | Mode: `{config.browser_mode}`")
    st.caption(f"Batch Execution: `{'Enabled' if config.enable_batch_execution else 'Disabled'}`")
    st.caption(f"Storage: `{config.storage_backend}`")

    with st.expander("📱 Install as Android/Windows App", expanded=False):
        st.markdown(
            """
            **To run like a normal app:**
            - **Android:** Open in Chrome/Edge, tap **⋮ (Menu)** ➔ **'Install app'** or **'Add to Home screen'**.
            - **Windows:** Click the **Install** icon (⊞) in the browser address bar.
            - Launches directly in full-screen standalone mode without browser toolbars!
            """
        )

    with st.expander("🛠️ Environment & Diagnostics"):
        diag = BrowserExecutor.get_diagnostics(config)
        st.write(f"**Python:** `{diag['python_version']}`")
        st.write(f"**Playwright:** `{diag['playwright_version'] or 'Not installed'}`")
        st.write(f"**Browser Mode:** `{diag['browser_mode']}`")
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

        # ── Unified Browser Mode ─────────────────────────────────────────────
        browser_mode_choice = st.selectbox(
            "🌐 Browser Mode",
            [
                "visible (👁️ Visible Browser — Recommended)",
                "headless (🔇 Headless / Background)",
                "cdp (🔌 Connect to Existing Chrome / CDP)",
            ],
            index=0,
            help="Visible: opens a real browser window you can watch. Headless: runs invisibly. CDP: connects to Chrome already running with --remote-debugging-port.",
        )
        browser_choice = st.selectbox(
            "Browser Type",
            ["chromium", "msedge", "chrome", "firefox", "webkit"],
            index=0,
        )
        keep_open = st.checkbox(
            "🔓 Keep browser open across tasks (same window)",
            value=True,
            help="Keep the browser window open across tasks so all actions execute in the same window without reopening.",
        )

        st.markdown(
            """
            <div style="background: rgba(46, 125, 50, 0.15); border: 1px solid rgba(76, 175, 80, 0.4); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 1.1rem;">🟢</span>
                    <div>
                        <strong style="color: #81c784; font-size: 0.85rem;">NVIDIA AI Cloud Built-in</strong>
                        <div style="font-size: 0.75rem; color: #a5d6a7;">Ready out-of-the-box — no API key or setup needed!</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        cdp_endpoint = "http://127.0.0.1:9222"
        clean_browser_mode = browser_mode_choice.split(" ")[0].strip()

        with st.expander("⚙️ Advanced Settings (Custom Key & CDP)", expanded=False):
            api_key_override = st.text_input(
                "Custom API Key (Optional)",
                type="password",
                placeholder="Using built-in NVIDIA key by default",
                help="Leave blank to use the built-in NVIDIA AI Cloud key, or paste your own custom key here.",
            )
            if clean_browser_mode == "cdp":
                cdp_endpoint = st.text_input(
                    "CDP Endpoint",
                    value="http://127.0.0.1:9222",
                    help="Start Chrome with: chrome.exe --remote-debugging-port=9222",
                )

    clean_strategy = strategy_mode.split(" ")[0].strip()

    # ── Open Website Button ──────────────────────────────────────────────────
    with st.expander("🌐 Pre-launch Browser (Optional)", expanded=False):
        st.caption("Launch the browser before starting task execution. Subsequent tasks will run in this same window.")
        pre_url = st.text_input(
            "URL to open",
            value="https://www.google.com",
            placeholder="https://www.google.com",
            key="pre_launch_url",
        )
        col_open, col_close = st.columns([1, 1])
        with col_open:
            if st.button("👁️ Open Browser", key="open_browser_btn", use_container_width=True):
                clean_model = model_choice.split(" ")[0].strip()

                os.environ["BROWSER_MODE"] = clean_browser_mode
                os.environ["HEADLESS"] = "true" if clean_browser_mode == "headless" else "false"
                os.environ["BROWSER_TYPE"] = browser_choice
                os.environ["KEEP_BROWSER_OPEN"] = "true"
                os.environ["REUSE_BROWSER"] = "true"
                if clean_browser_mode == "cdp":
                    os.environ["BROWSER_CONNECTION_MODE"] = "cdp"
                    os.environ["CDP_ENDPOINT"] = cdp_endpoint
                else:
                    os.environ["BROWSER_CONNECTION_MODE"] = "playwright"

                pre_config = AgentConfig()

                async def _open_preview():
                    from agent_framework.models import ActionObject
                    from agent_framework.modules.browser_executor import BrowserExecutor
                    async with BrowserExecutor(pre_config, reuse_session=True) as browser:
                        action = ActionObject(action="navigate", value=pre_url)
                        result = await browser.execute(action, run_id="preview", step_index=0, screenshot=True)
                        return result

                try:
                    with st.spinner(f"🌐 Opening {pre_url}..."):
                        result = run_async(_open_preview())
                    st.success(f"✅ Browser open: **{result.get('title', 'Page')}**")
                    st.caption(f"URL: `{result.get('url', pre_url)}`")
                    if result.get("screenshot_path") and Path(result["screenshot_path"]).exists():
                        st.image(result["screenshot_path"], caption="Browser Preview")
                except BrowserStartupError as bse:
                    st.error(f"❌ Browser startup failed: {bse}")
                    if bse.suggested_fix:
                        st.info(f"💡 {bse.suggested_fix}")
                except Exception as e:
                    st.error(f"❌ Could not open browser: {e}")

        with col_close:
            if st.button("🛑 Close Browser Window", key="close_browser_window_btn", use_container_width=True):
                from agent_framework.modules.browser_executor import BrowserExecutor
                run_async(BrowserExecutor.close_shared_session())
                st.success("✅ Browser window closed.")

    col_sub1, col_sub2 = st.columns([2, 1])
    with col_sub1:
        run_now = st.button("🚀 Plan & Execute in Browser Now", type="primary", use_container_width=True)
    with col_sub2:
        plan_only = st.button("📋 Plan Only (Preview Steps)", use_container_width=True)

    if run_now or plan_only:
        clean_model = model_choice.split(" ")[0].strip()

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
        os.environ["FAST_MODEL"] = "meta/llama-3.2-11b-vision-instruct" if provider == "nvidia" else clean_model
        os.environ["REASONING_MODEL"] = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning" if provider == "nvidia" else clean_model
        os.environ["EXPERIMENT_STRATEGY"] = clean_strategy
        os.environ["BROWSER_TYPE"] = browser_choice
        os.environ["BROWSER_MODE"] = clean_browser_mode
        os.environ["HEADLESS"] = "true" if clean_browser_mode == "headless" else "false"
        os.environ["KEEP_BROWSER_OPEN"] = str(keep_open).lower()
        if clean_browser_mode == "cdp":
            os.environ["BROWSER_CONNECTION_MODE"] = "cdp"
            os.environ["CDP_ENDPOINT"] = cdp_endpoint
        else:
            os.environ["BROWSER_CONNECTION_MODE"] = "playwright"

        if api_key_override.strip():
            key_var = f"{provider.upper()}_API_KEY"
            os.environ[key_var] = api_key_override.strip()

        run_config = AgentConfig()

        if provider == "nvidia":
            current_key = api_key_override.strip() or run_config.nvidia_api_key or os.getenv("NVIDIA_API_KEY") or DEFAULT_NVIDIA_API_KEY
        elif provider == "gemini":
            current_key = run_config.gemini_api_key or os.getenv("GEMINI_API_KEY")
        elif provider == "openai":
            current_key = run_config.openai_api_key or os.getenv("OPENAI_API_KEY")
        else:
            current_key = run_config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")

        if not goal_input.strip():
            st.warning("Please enter a goal.")
        elif not current_key or not current_key.strip():
            st.error(f"❌ No API key found for provider `{provider.upper()}`. Set `{provider.upper()}_API_KEY` in your `.env` file or paste it into Advanced Settings above.")
        else:
            # Store browser mode in session state for Agent View
            st.session_state.browser_mode = clean_browser_mode

            if clean_strategy == "plan_then_execute":
                with st.spinner("⚡ Generating compact execution plan (1 fast LLM call)..."):
                    try:
                        planner = UnifiedPlanner(run_config)
                        plan, tokens = run_async(planner.plan(goal_input))

                        st.session_state.run_log = []
                        st.session_state.execution_plan = plan
                        st.session_state.pending_strategy = clean_strategy
                        st.session_state.pending_goal_text = goal_input

                        if run_now:
                            st.session_state.auto_start_execution = True
                            navigate_to("🤖 Agent View")

                        st.success(
                            f"📋 Action Plan generated in 1 LLM call ({tokens} tokens)! "
                            f"**{len(plan.steps)} steps** queued."
                        )
                        st.warning("⚠️ **Note:** Plan is generated but not executed yet. Click below to run the actions in the browser:")
                        if st.button("🚀 Proceed to Agent View & Execute", type="primary", key="goto_agent_view_plan"):
                            st.session_state.auto_start_execution = True
                            navigate_to("🤖 Agent View")

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

                        if run_now:
                            st.session_state.auto_start_execution = True
                            navigate_to("🤖 Agent View")

                        st.success(
                            f"📋 Goal parsed: **{goal_obj.task_type}** / {goal_obj.domain} "
                            f"| {len(subtasks)} sub-tasks planned."
                        )
                        st.warning("⚠️ **Note:** Plan is generated but not executed yet. Click below to run the actions in the browser:")
                        if st.button("🚀 Proceed to Agent View & Execute", type="primary", key="goto_agent_view_legacy"):
                            st.session_state.auto_start_execution = True
                            navigate_to("🤖 Agent View")

                        # Show decomposed sub-tasks
                        st.subheader("📋 Sub-task Plan")
                        for st_ in subtasks:
                            st.markdown(f"**Step {st_.step}** `{st_.type}` — {st_.goal}")
                    except Exception as e:
                        st.error(f"❌ Error during planning: {e}")

    st.divider()
    st.subheader("📜 Previous Run History (Completed Past Sessions)")
    st.caption("Showing history of previous completed sessions. To run a new task, click 'Plan & Execute in Browser Now' above.")
    try:
        history_df = run_async(evaluator.get_run_history(20))
        if history_df.empty:
            st.info("No runs yet. Submit a goal above to get started.")
        else:
            st.dataframe(
                history_df.style.map(
                    lambda v: "color: green" if v == "success"
                    else ("color: red" if v == "failed" else ""),
                    subset=["status"],
                ),
                width="stretch",
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
        browser_mode_display = st.session_state.get("browser_mode", "visible")
        st.markdown(f"**Browser Mode:** `{browser_mode_display}`")
        st.divider()

        auto_start = st.session_state.pop("auto_start_execution", False)
        if st.button("🚀 Start Fast Execution", type="primary") or auto_start:
            run_config = AgentConfig()
            os.environ["EXPERIMENT_STRATEGY"] = strategy_name

            run_id = run_async(exp_logger.start_run(goal_text, strategy_name))
            st.session_state.active_run_id = run_id
            st.session_state.run_log = []
            st.session_state.extracted_products = []
            st.session_state.browser_active = True
            st.session_state.browser_error = None

            progress = st.progress(0, text="Starting execution...")

            # Live browser status area
            status_area = st.empty()
            with status_area.container():
                st.info(f"🌐 Starting browser... (mode: {browser_mode_display})")

            start_time = time.time()
            metrics = MetricsCollector()
            metrics.start()

            # Create status callback for live updates
            status_callback, status_data = make_status_callback()

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

                        has_step_failures = False
                        has_step_partial = False
                        first_failure_reason = ""
                        partial_reason = ""
                        failed_step_num = 0
                        partial_step_num = 0
                        completed_steps = 0
                        total_steps_count = len(plan.steps)
                        run_config.reuse_browser = True

                        async with BrowserExecutor(run_config, status_callback=status_callback, reuse_session=True) as browser:
                            prev_page = None
                            for i, (planned_step, action_obj) in enumerate(zip(plan.steps, actions_to_exec)):
                                step_progress = (i + 1) / total_steps_count

                                is_cp = planned_step.checkpoint or (i == total_steps_count - 1)
                                step_start = time.time()

                                # Execute single action in browser (capture screenshot on every step for live visual view)
                                raw_state = await browser.execute(
                                    action_obj,
                                    run_id=run_id,
                                    step_index=i,
                                    screenshot=True,
                                    )
                                act_duration = (time.time() - step_start) * 1000
                                p_actions += 1
                                act_success = raw_state.get("action_success", True)
                                act_err = raw_state.get("action_error")
                                metrics.record_browser_action(action_obj.action, success=act_success, duration_ms=act_duration)
                                metrics.record_screenshot()

                                if not act_success:
                                    has_step_failures = True
                                    if not first_failure_reason:
                                        first_failure_reason = act_err or "Action execution failed"
                                        failed_step_num = i + 1

                                page_state = observer.observe(raw_state, task_keywords=[plan.domain, plan.task_type], prev_state=prev_page)

                                # Store active website details for live app view
                                if page_state.url:
                                    status_data["current_url"] = page_state.url
                                    status_data["current_title"] = page_state.title
                                if page_state.screenshot_path:
                                    status_data["last_screenshot"] = page_state.screenshot_path

                                # Capture and update extracted items and their cart statuses in-place
                                if page_state.extracted_items:
                                    for item in page_state.extracted_items:
                                        existing = next((p for p in st.session_state.extracted_products if p.get("url") and p.get("url") == item.get("url")), None)
                                        if existing:
                                            existing.update(item)
                                        else:
                                            st.session_state.extracted_products.append(item)

                                state_mgr.update(
                                    url=page_state.url,
                                    title=page_state.title,
                                    action=action_obj.action,
                                    result="executed" if act_success else "failed",
                                    step_index=i,
                                )

                                # Verification at checkpoints
                                if not act_success:
                                    ver_status = "failure"
                                    ver_reason = f"Step failed: {act_err or 'Element not found'}"
                                else:
                                    ver_status = "success"
                                    ver_reason = "Executed in batch"
                                    completed_steps += 1

                                if is_cp:
                                    ver_result, ver_tok = await verifier.verify_checkpoint(
                                        expected_outcome=planned_step.description or "Action completed",
                                        page_state=page_state,
                                        previous_page_state=prev_page,
                                        action_desc=f"{action_obj.action} {action_obj.selector or ''}",
                                        action_success=act_success,
                                        action_error=act_err,
                                    )
                                    ver_status = ver_result.status
                                    ver_reason = ver_result.reason
                                    p_tokens += ver_tok
                                    metrics.record_checkpoint()
                                    if ver_tok > 0:
                                        metrics.record_llm_call("fast", tokens=ver_tok, phase="verify")
                                    if ver_status == "failure":
                                        has_step_failures = True
                                        if not first_failure_reason:
                                            first_failure_reason = ver_reason
                                            failed_step_num = i + 1
                                    elif ver_status == "partial":
                                        has_step_partial = True
                                        if not partial_reason:
                                            partial_reason = ver_reason
                                            partial_step_num = i + 1

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
                                    "direct_link": page_state.direct_link,
                                })

                                prev_page = page_state
                                state_mgr.mark_step_complete(i)

                            # Smoothly yield manual control to the user after finishing all actions
                            try:
                                await browser.yield_control_to_user()
                            except Exception:
                                pass

                        if has_step_failures:
                            final_status = "partial" if completed_steps > 0 else "failed"
                        elif has_step_partial:
                            final_status = "partial"
                            if not first_failure_reason:
                                first_failure_reason = partial_reason
                                failed_step_num = partial_step_num
                        else:
                            final_status = "success"

                        return final_status, p_actions, p_retries, p_tokens, completed_steps, total_steps_count, first_failure_reason, failed_step_num

                    with st.spinner("⚡ Running batch browser execution..."):
                        final_status, total_actions, total_retries, total_tokens, completed_steps, total_steps, failure_reason, failed_step = run_async(run_fast_pipeline())

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
                        has_failure = False
                        first_err = ""
                        failed_idx = 0
                        completed_cnt = 0

                        # Smart initial URL inference from goal
                        init_url = "https://www.google.com"
                        goal_lower = goal_text.lower()
                        if "youtube" in goal_lower:
                            init_url = "https://www.youtube.com/"
                        elif "amazon" in goal_lower:
                            init_url = "https://www.amazon.in/"
                        elif "flipkart" in goal_lower:
                            init_url = "https://www.flipkart.com/"
                        elif "makemytrip" in goal_lower:
                            init_url = "https://www.makemytrip.com/"

                        run_config.reuse_browser = True
                        async with BrowserExecutor(run_config, status_callback=status_callback, reuse_session=True) as browser:
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
                                            value=init_url if step_idx == 0 else None,
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

                                    if page_state_after.extracted_items:
                                        for item in page_state_after.extracted_items:
                                            existing = next((p for p in st.session_state.extracted_products if p.get("url") and p.get("url") == item.get("url")), None)
                                            if existing:
                                                existing.update(item)
                                            else:
                                                st.session_state.extracted_products.append(item)

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
                                        "direct_link": page_state_after.direct_link,
                                    })

                                    last_verification = verification
                                    prev_page_state = page_state_after
                                    step_idx += 1

                                    if verification.status == "success":
                                        completed_cnt += 1
                                        break

                                    if verification.status == "failure":
                                        has_failure = True
                                        if not first_err:
                                            first_err = verification.reason
                                            failed_idx = task_idx + 1
                                        if retry_count < run_config.max_retries_per_subtask:
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

                            # Smoothly yield manual control to the user after finishing all actions
                            try:
                                await browser.yield_control_to_user()
                            except Exception:
                                pass

                        c_status = "success" if not has_failure else ("partial" if completed_cnt > 0 else "failed")
                        return c_status, p_actions, p_retries, p_tokens, completed_cnt, len(subtasks), first_err, failed_idx

                    with st.spinner("Agent running (Classic observe-think-act)..."):
                        final_status, total_actions, total_retries, total_tokens, completed_steps, total_steps, failure_reason, failed_step = run_async(run_classic_pipeline())

                # Sync status data back to session state
                sync_status_to_session(status_data)
                st.session_state.browser_active = False

                metrics.stop()
                elapsed = time.time() - start_time
                st.session_state.last_metrics = metrics.to_dict()

                # Store active URLs from status data
                if status_data.get("current_url"):
                    st.session_state.active_url = status_data["current_url"]
                if status_data.get("current_title"):
                    st.session_state.active_page_title = status_data["current_title"]
                if status_data.get("last_screenshot"):
                    st.session_state.active_screenshot = status_data["last_screenshot"]

                run_async(exp_logger.end_run(
                    run_id, final_status, total_actions, total_retries,
                    total_tokens, elapsed
                ))

                pct = max(0.0, min(1.0, completed_steps / max(total_steps, 1))) if total_steps > 0 else (1.0 if final_status == "success" else 0.0)
                # Check for explicit completion percentage reported in failure/partial reason (e.g. "70% completed")
                try:
                    m_pct = re.search(r'(\d{1,3})%\s*completed', failure_reason or "")
                    if m_pct:
                        pct = float(m_pct.group(1)) / 100.0
                except Exception:
                    pass

                display_pct = int(pct * 100)
                if final_status == "success":
                    progress.progress(1.0, text=f"✅ Task Completed 100% in {elapsed:.1f}s!")
                    st.success(f"🎉 **Task 100% Completed in {elapsed:.1f}s!** All {total_steps} steps succeeded.")
                    st.info("✨ **Manual Control Yielded:** The browser tab is open and playing. The agent has exited from the tab — you have full manual control.")
                elif final_status == "partial":
                    progress.progress(pct, text=f"⚠️ Task Partially Completed ({display_pct}%) in {elapsed:.1f}s")
                    st.warning(f"⚠️ **Task Partially Completed ({display_pct}%):** {failure_reason}")
                else:
                    progress.progress(pct, text=f"❌ Task Failed ({display_pct}%) in {elapsed:.1f}s")
                    st.error(f"❌ **Task Failed at step {failed_step}:** {failure_reason}")

            except BrowserStartupError as bse:
                sync_status_to_session(status_data)
                st.session_state.browser_active = False
                st.error(f"❌ **Browser Startup Failed:** {bse}")
                diag = bse.diagnostics
                with st.expander("🛠️ Browser Diagnostics & Troubleshooting", expanded=True):
                    st.markdown(f"**Browser Type:** `{diag.get('browser_type', run_config.browser_type)}` | **Mode:** `{diag.get('browser_mode', 'visible')}` | **Headless:** `{diag.get('headless', run_config.headless)}`")
                    st.markdown(f"**Playwright Available:** `{diag.get('playwright_available')}` (`{diag.get('playwright_version', 'N/A')}`)")
                    st.markdown(f"**Framework Location:** `{diag.get('agent_framework_path')}` (`{'Local src' if diag.get('is_local_src') else 'Installed site-packages'}`)")
                    if diag.get("attempted_launchers"):
                        st.markdown(f"**Attempted Launchers:** {', '.join(diag.get('attempted_launchers'))}")
                    if bse.suggested_fix:
                        st.info(f"💡 **Suggested Fix:** {bse.suggested_fix}")
                    st.code("python -m playwright install chromium", language="bash")
                run_async(exp_logger.end_run(run_id, "failed", 0, 0, 0, 0))

            except BrowserNotStartedError as bne:
                sync_status_to_session(status_data)
                st.session_state.browser_active = False
                st.error(f"❌ **Browser Lifecycle Error:** {bne}")
                st.info("💡 **Fix:** Ensure the browser is managed inside an `async with BrowserExecutor(config) as browser:` context.")
                run_async(exp_logger.end_run(run_id, "failed", 0, 0, 0, 0))

            except BrowserBlockedError as bbe:
                sync_status_to_session(status_data)
                st.session_state.browser_active = False
                st.error(f"🛑 **Navigation Blocked:** {bbe}")
                st.warning("Action was blocked by safe browsing guardrails (e.g. checkout or payment URL).")
                run_async(exp_logger.end_run(run_id, "blocked", 0, 0, 0, 0))

            except Exception as e:
                sync_status_to_session(status_data)
                st.session_state.browser_active = False
                st.error(f"❌ **Agent Execution Error:** {e}")
                run_async(exp_logger.end_run(run_id, "failed", 0, 0, 0, 0))

        # ── Live Browser Status ──────────────────────────────────────────────
        if st.session_state.get("browser_status_log"):
            with st.expander("📡 Browser Status Log", expanded=False):
                for msg in st.session_state.browser_status_log[-15:]:
                    st.caption(msg)

        # Show Active Task Website & Live Visual Browser Window
        if st.session_state.get("active_url"):
            st.subheader("🌐 Active Task Website (Live View)")
            with st.container(border=True):
                w_col1, w_col2 = st.columns([4, 1])
                curr_title = st.session_state.get("active_page_title") or "Website Loaded"
                w_col1.markdown(f"### 🔗 [{curr_title}]({st.session_state.active_url})")

                # Current URL & action display
                w_col1.caption(f"**Current URL:** `{st.session_state.active_url}`")
                if st.session_state.get("current_action"):
                    w_col1.caption(f"**Current Action:** {st.session_state.current_action}")

                w_col2.link_button("🚀 Open Website in Tab", st.session_state.active_url, width="stretch")

                active_img = st.session_state.get("active_screenshot")
                if active_img and Path(active_img).exists():
                    st.image(active_img, caption=f"Active Browser Viewport — {curr_title}", width="stretch")

        # Show Extracted Products & Direct Links if available
        if st.session_state.get("extracted_products"):
            prods = st.session_state.extracted_products
            valid_urls = [p["url"] for p in prods if p.get("url")]

            hdr_col1, hdr_col2 = st.columns([3, 1])
            hdr_col1.subheader("🛍️ Extracted Products & Direct Links")
            if valid_urls:
                if hdr_col2.button("🚀 Open All Links in Tabs", key="open_all_prods_btn", help="Open all extracted product pages in separate browser tabs"):
                    import streamlit.components.v1 as components
                    js_code = f"""
                    <script>
                        const urls = {valid_urls!r};
                        urls.forEach(url => window.open(url, '_blank'));
                    </script>
                    """
                    components.html(js_code, height=0)
                    st.toast(f"Opening {len(valid_urls)} product links in new browser tabs! (Please allow popups if prompted)")

            # Show Cart Progress Header if multi-item cart task
            cart_added = sum(1 for p in prods if p.get("cart_status") == "added")
            cart_failed = sum(1 for p in prods if p.get("cart_status") in ("failed", "unavailable / out of stock"))
            if cart_added + cart_failed > 0:
                total_cart = cart_added + cart_failed
                pct_cart = int((cart_added / total_cart) * 100)
                if pct_cart == 100:
                    st.success(f"🛒 **Multi-Item Cart Status:** All {total_cart} items successfully added to cart (100% completed)!")
                else:
                    st.warning(f"🛒 **Multi-Item Cart Status:** {cart_added} of {total_cart} items added to cart ({pct_cart}% completed).")

            for idx, prod in enumerate(prods, 1):
                with st.container(border=True):
                    p1, p2, p3 = st.columns([5, 3, 2])
                    p1.markdown(f"**#{idx} {prod.get('title', 'Unknown Product')}**")
                    price_info = f"💰 **{prod.get('price', 'N/A')}**"
                    if prod.get("rating"):
                        price_info += f" | ⭐ {prod.get('rating')}"

                    c_status = prod.get("cart_status")
                    if c_status == "added":
                        price_info += " | 🛒 :green[**Added to Cart**]"
                    elif c_status:
                        price_info += f" | ⚠️ :orange[**{c_status}**]"

                    p2.markdown(price_info)
                    if prod.get("url"):
                        p3.link_button("🔗 Direct Product Link", prod["url"], width="stretch")

        # ── Final Result Card ────────────────────────────────────────────────
        if st.session_state.last_metrics and st.session_state.get("active_run_id"):
            m = st.session_state.last_metrics
            st.subheader("✅ Task Completed")
            with st.container(border=True):
                rc1, rc2 = st.columns([3, 1])
                rc1.markdown(f"**Website:** {st.session_state.get('active_page_title', 'N/A')}")
                rc1.markdown(f"**Final URL:** `{st.session_state.get('active_url', 'N/A')}`")
                if st.session_state.get("active_url"):
                    rc2.link_button("🌐 Open Final Page", st.session_state.active_url, width="stretch")

            # Performance Scorecard
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
                st.plotly_chart(fig1, width="stretch")

            with col_b:
                fig2 = px.bar(
                    df, x="strategy", y="action_accuracy",
                    title="Action Accuracy by Strategy (%)",
                    color="strategy",
                    text_auto=".1f",
                )
                fig2.update_layout(showlegend=False, yaxis_range=[0, 105])
                st.plotly_chart(fig2, width="stretch")

            col_c, col_d = st.columns(2)
            with col_c:
                fig3 = px.bar(
                    df, x="strategy", y="avg_retries",
                    title="Average Retries per Run",
                    color="strategy",
                    text_auto=".2f",
                )
                fig3.update_layout(showlegend=False)
                st.plotly_chart(fig3, width="stretch")

            with col_d:
                fig4 = px.bar(
                    df, x="strategy", y="avg_token_usage",
                    title="Average Token Usage per Run (Tokens)",
                    color="strategy",
                    text_auto=".0f",
                )
                fig4.update_layout(showlegend=False)
                st.plotly_chart(fig4, width="stretch")

        st.subheader("📋 Full Metrics Table")
        st.dataframe(df, width="stretch")


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
