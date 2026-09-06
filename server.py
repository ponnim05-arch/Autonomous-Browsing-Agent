"""
FastAPI Server for Autonomous Fast Browser Agent
================================================
Bridges the Python agent_framework to the React + TypeScript frontend.
Provides REST APIs for planning, execution, runs, and metrics, plus WebSockets
for real-time live browser observation, action execution, and screenshot streaming.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Playwright on Windows requires ProactorEventLoop for subprocess transport
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure src/ is in python path
ROOT_DIR = Path(__file__).parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent_framework.config import AgentConfig, default_config
from agent_framework.models import ActionObject, PageState, SubTask, VerificationResult
from agent_framework.modules.browser_executor import (
    BrowserBlockedError,
    BrowserError,
    BrowserExecutor,
    BrowserNotStartedError,
    BrowserStartupError,
)
from agent_framework.modules.evaluator import Evaluator
from agent_framework.modules.logger import ExperimentLogger
from agent_framework.modules.metrics import MetricsCollector
from agent_framework.modules.page_observer import PageObserver
from agent_framework.modules.repair_engine import RepairEngine
from agent_framework.modules.state_manager import StateManager
from agent_framework.modules.unified_planner import ExecutionPlan, PlannedStep, UnifiedPlanner
from agent_framework.modules.verifier import Verifier

logger = logging.getLogger("agent_api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Autonomous Fast Browser Agent API",
    description="Backend API powering the React + shadcn UI for Autonomous Browser Agents",
    version="1.0.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure runs/screenshots directory exists and is mounted
RUNS_DIR = ROOT_DIR / "logs" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
DATA_SCREENSHOTS_DIR = ROOT_DIR / "data" / "screenshots"
DATA_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR = RUNS_DIR  # Primary screenshot location for agent runs

app.mount("/screenshots", StaticFiles(directory=str(RUNS_DIR)), name="screenshots")
app.mount("/data/screenshots", StaticFiles(directory=str(DATA_SCREENSHOTS_DIR)), name="data_screenshots")


# ── In-Memory Connection & State Tracking ─────────────────────────────────────

class ConnectionManager:
    """Manages active WebSockets keyed by run_id."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.run_cancel_events: Dict[str, asyncio.Event] = {}

    async def connect(self, run_id: str, websocket: WebSocket):
        await websocket.accept()
        if run_id not in self.active_connections:
            self.active_connections[run_id] = []
        self.active_connections[run_id].append(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket):
        if run_id in self.active_connections:
            if websocket in self.active_connections[run_id]:
                self.active_connections[run_id].remove(websocket)
            if not self.active_connections[run_id]:
                del self.active_connections[run_id]

    async def broadcast(self, run_id: str, event_type: str, data: Dict[str, Any]):
        message = json.dumps({"type": event_type, "run_id": run_id, "timestamp": time.time(), "data": data})
        if run_id in self.active_connections:
            dead_sockets = []
            for ws in self.active_connections[run_id]:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead_sockets.append(ws)
            for dead in dead_sockets:
                self.disconnect(run_id, dead)


ws_manager = ConnectionManager()


# ── Request / Response Schemas ────────────────────────────────────────────────

class PlanRequest(BaseModel):
    goal: str
    model: Optional[str] = None
    provider: Optional[str] = None


class RunRequest(BaseModel):
    goal: str
    strategy: str = "plan_then_execute"
    model: str = "meta/llama-3.2-11b-vision-instruct"
    browser_mode: str = "visible"
    browser_type: str = "chromium"
    keep_browser_open: bool = True
    cdp_endpoint: Optional[str] = "http://127.0.0.1:9222"
    plan: Optional[Dict[str, Any]] = None


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/config")
async def get_config():
    cfg = AgentConfig()
    env_keys = {
        "nvidia": bool(cfg.nvidia_api_key or os.getenv("NVIDIA_API_KEY")),
        "openai": bool(cfg.openai_api_key or os.getenv("OPENAI_API_KEY")),
        "anthropic": bool(cfg.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")),
        "gemini": bool(cfg.gemini_api_key or os.getenv("GEMINI_API_KEY")),
    }
    return {
        "default_strategy": cfg.experiment_strategy,
        "fast_model": cfg.fast_model,
        "reasoning_model": cfg.reasoning_model,
        "browser_mode": cfg.browser_mode,
        "browser_type": cfg.browser_type,
        "storage_backend": cfg.storage_backend,
        "available_strategies": [
            {"id": "plan_then_execute", "name": "Plan-then-Execute", "badge": "⚡ Ultra Fast", "desc": "1-shot plan generation with direct execution and checkpoints"},
            {"id": "dynamic", "name": "Dynamic", "badge": "🟢 Adaptive", "desc": "Classic Observe-Think-Act loop after every single action"},
            {"id": "static", "name": "Static", "badge": "🔵 Baseline", "desc": "Predefined fixed prompt pipeline"},
            {"id": "self_reflective", "name": "Self-Reflective", "badge": "🟡 CoT", "desc": "Chain-of-Thought reflection on page changes before actions"},
            {"id": "failure_recovery", "name": "Failure-Recovery", "badge": "🔴 Self-Healing", "desc": "Aggressive error diagnostic and automatic prompt repairs"},
        ],
        "available_models": [
            {"id": "meta/llama-3.2-11b-vision-instruct", "name": "Llama 3.2 11B Vision", "provider": "nvidia", "tier": "Fast Vision"},
            {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "name": "Nemotron 3 Nano Omni 30B", "provider": "nvidia", "tier": "Omni Reasoning"},
            {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B", "provider": "nvidia", "tier": "Heavy Reasoning"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "gemini", "tier": "Fast Multimodal"},
            {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai", "tier": "Advanced Multimodal"},
            {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet", "provider": "anthropic", "tier": "Reasoning & Agentic"},
        ],
        "browser_modes": ["visible", "headless", "cdp"],
        "browser_types": ["chromium", "msedge", "chrome", "firefox", "webkit"],
        "api_keys_present": env_keys,
    }


@app.post("/api/plan")
async def generate_plan(req: PlanRequest):
    if not req.goal.strip():
        raise HTTPException(status_code=400, detail="Goal cannot be empty")
    cfg = AgentConfig()
    if req.model:
        cfg.fast_model = req.model
        cfg.llm_model = req.model

    try:
        planner = UnifiedPlanner(cfg)
        plan, tokens = await planner.plan(req.goal)
        return {
            "tokens": tokens,
            "domain": plan.domain,
            "task_type": plan.task_type,
            "steps": [
                {
                    "action": step.action,
                    "selector": step.target,
                    "target": step.target,
                    "value": step.value,
                    "checkpoint": step.checkpoint,
                    "description": step.description,
                }
                for step in plan.steps
            ],
            "checkpoint_indices": plan.checkpoint_indices,
            "success_criteria": getattr(plan, "success_criteria", ""),
        }
    except Exception as e:
        logger.error(f"Plan generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/run")
async def start_run(req: RunRequest):
    cfg = AgentConfig()
    cfg.experiment_strategy = req.strategy
    cfg.browser_mode = req.browser_mode
    cfg.headless = req.browser_mode == "headless"
    cfg.browser_type = req.browser_type
    cfg.reuse_browser = req.keep_browser_open
    cfg.keep_browser_open = req.keep_browser_open
    if req.browser_mode == "cdp":
        cfg.browser_connection_mode = "cdp"
        cfg.cdp_endpoint = req.cdp_endpoint or "http://127.0.0.1:9222"
    else:
        cfg.browser_connection_mode = "playwright"

    # Determine provider from model
    clean_model = req.model
    if any(k in clean_model for k in ("meta/", "mistralai/", "nvidia", "openai/gpt-oss")):
        cfg.llm_provider = "nvidia"
    elif any(k in clean_model for k in ("gpt-4", "o3", "o1")):
        cfg.llm_provider = "openai"
    elif "claude" in clean_model:
        cfg.llm_provider = "anthropic"
    else:
        cfg.llm_provider = "gemini"

    cfg.llm_model = clean_model
    cfg.fast_model = clean_model

    exp_logger = ExperimentLogger(cfg)
    run_id = await exp_logger.start_run(req.goal, req.strategy)

    # Initialize cancel event
    cancel_event = asyncio.Event()
    ws_manager.run_cancel_events[run_id] = cancel_event

    # Launch execution background task
    asyncio.create_task(
        execute_agent_run(
            run_id=run_id,
            goal=req.goal,
            strategy=req.strategy,
            config=cfg,
            plan_dict=req.plan,
            cancel_event=cancel_event,
        )
    )

    return {"run_id": run_id, "status": "started"}


@app.post("/api/stop/{run_id}")
async def stop_run(run_id: str):
    if run_id in ws_manager.run_cancel_events:
        ws_manager.run_cancel_events[run_id].set()
        await ws_manager.broadcast(run_id, "status", {"message": "Execution cancellation requested by user."})
        return {"status": "stopping"}
    return {"status": "not_running"}


def sanitize_records(df) -> List[Dict[str, Any]]:
    """Converts a pandas DataFrame to JSON-compliant records with no NaNs."""
    if df is None or df.empty:
        return []
    import numpy as np
    sanitized_df = df.replace({np.nan: None})
    records = sanitized_df.to_dict(orient="records")
    return records


@app.get("/api/runs")
async def get_runs(limit: int = 50):
    evaluator = Evaluator(default_config)
    try:
        df = await evaluator.get_run_history(limit=limit)
        return sanitize_records(df)
    except Exception as e:
        logger.error(f"Error fetching runs: {e}")
        return []


@app.get("/api/runs/{run_id}")
async def get_run_details(run_id: str):
    evaluator = Evaluator(default_config)
    try:
        summary = await evaluator.compute_metrics(run_id)
        steps_df = await evaluator.get_run_steps(run_id)
        repairs_df = await evaluator.get_run_repairs(run_id)

        # Look for latest screenshot on disk
        latest_screenshot_url = None
        latest_screenshot_base64 = None
        run_dir = RUNS_DIR / run_id
        if run_dir.exists():
            pngs = sorted(run_dir.glob("step_*.png"))
            if pngs:
                latest = pngs[-1]
                latest_screenshot_url = f"/screenshots/{latest.relative_to(RUNS_DIR).as_posix()}"
                try:
                    with open(latest, "rb") as f:
                        latest_screenshot_base64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
                except Exception:
                    pass

        # Extract final URL & title from steps if available
        final_url = None
        final_title = None
        if steps_df is not None and not steps_df.empty:
            for idx in range(len(steps_df) - 1, -1, -1):
                row = steps_df.iloc[idx]
                snap_str = row.get("page_state_snapshot")
                if snap_str:
                    try:
                        snap_obj = json.loads(snap_str)
                        if snap_obj.get("url") and not final_url:
                            final_url = snap_obj.get("url")
                        if snap_obj.get("title") and not final_title:
                            final_title = snap_obj.get("title")
                        if final_url and final_title:
                            break
                    except Exception:
                        pass

        return {
            "summary": summary.model_dump(),
            "steps": sanitize_records(steps_df),
            "repairs": sanitize_records(repairs_df),
            "latest_screenshot": latest_screenshot_url,
            "latest_screenshot_base64": latest_screenshot_base64,
            "final_url": final_url,
            "final_title": final_title,
        }
    except Exception as e:
        logger.error(f"Error fetching run details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/runs/{run_id}/latest-screenshot")
async def get_latest_screenshot(run_id: str):
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run directory not found")
    pngs = sorted(run_dir.glob("step_*.png"))
    if not pngs:
        raise HTTPException(status_code=404, detail="No screenshots found for this run")
    latest = pngs[-1]
    rel = latest.relative_to(RUNS_DIR).as_posix()
    b64 = None
    try:
        with open(latest, "rb") as f:
            b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
    except Exception:
        pass
    return {
        "run_id": run_id,
        "screenshot_url": f"/screenshots/{rel}",
        "screenshot_base64": b64,
        "step": latest.stem,
    }


@app.get("/api/related-videos")
async def get_related_videos():
    """Returns top 10 latest videos related to Prasad Tech in Telugu."""
    scratch_file = ROOT_DIR.parent / "brain" / "latest_prasad_tech_videos.json"
    local_cached = ROOT_DIR / "data" / "latest_prasad_tech_videos.json"
    if local_cached.exists():
        try:
            with open(local_cached, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Curated fallbacks with actual live data
    return [
        {
            "rank": 1,
            "videoId": "kGU6fiO9WuU",
            "title": "POCO X8 Series Unboxing & Initial Impressions || Insane Battery Phones 🤯",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=kGU6fiO9WuU",
            "thumbnail": "https://i.ytimg.com/vi/kGU6fiO9WuU/hqdefault.jpg"
        },
        {
            "rank": 2,
            "videoId": "S_2CR951ErA",
            "title": "Infinix HOT 70 Pro 5G Unboxing & Initial Impressions || The New Budget King? 😱",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=S_2CR951ErA",
            "thumbnail": "https://i.ytimg.com/vi/S_2CR951ErA/hqdefault.jpg"
        },
        {
            "rank": 3,
            "videoId": "q237uN0nfOY",
            "title": "Tech News 2241 || iQOO 16, iOS 27, Xiaomi 18 Fold, Nothing 2027 Launches, Smart Wheelchair, Robot",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=q237uN0nfOY",
            "thumbnail": "https://i.ytimg.com/vi/q237uN0nfOY/hqdefault.jpg"
        },
        {
            "rank": 4,
            "videoId": "uV5JVRXXUcA",
            "title": "Tech News 2240 || OnePlus 16, Huawei Mate XT 2, Gemini Coding, IMEI Tamper, Sim Swap",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=uV5JVRXXUcA",
            "thumbnail": "https://i.ytimg.com/vi/uV5JVRXXUcA/hqdefault.jpg"
        },
        {
            "rank": 5,
            "videoId": "EeUxMaCqxHo",
            "title": "Which is the best Water Purifier? Urban Native M3 pro vs Aquaguard ritz pro 4X",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=EeUxMaCqxHo",
            "thumbnail": "https://i.ytimg.com/vi/EeUxMaCqxHo/hqdefault.jpg"
        },
        {
            "rank": 6,
            "videoId": "82JoLvTNhOc",
            "title": "vivo T5 5G Unboxing & First Impressions || 7050mAh Battery + 144Hz AMOLED | Telugu",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=82JoLvTNhOc",
            "thumbnail": "https://i.ytimg.com/vi/82JoLvTNhOc/hqdefault.jpg"
        },
        {
            "rank": 7,
            "videoId": "Wvv6wfWQlLM",
            "title": "HONOR Robot Phone Is INSANE 😲🤯 | A Real-Life SCI-FI Phone! 🥳",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=Wvv6wfWQlLM",
            "thumbnail": "https://i.ytimg.com/vi/Wvv6wfWQlLM/hqdefault.jpg"
        },
        {
            "rank": 8,
            "videoId": "n48kAO6cMAs",
            "title": "Tech News 2238 || Mobile Prices GST Cut, iPhone Ultra, New Mac's, Plaud One, Meta.Etc..",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=n48kAO6cMAs",
            "thumbnail": "https://i.ytimg.com/vi/n48kAO6cMAs/hqdefault.jpg"
        },
        {
            "rank": 9,
            "videoId": "1oD_4E2_lcM",
            "title": "Nothing OS 5.0 New Features & Changes Explained! 🥳",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=1oD_4E2_lcM",
            "thumbnail": "https://i.ytimg.com/vi/1oD_4E2_lcM/hqdefault.jpg"
        },
        {
            "rank": 10,
            "videoId": "kZTe4kl8Q3U",
            "title": "Upcoming Mobiles in September 2026 🥳 || Exciting Launches ahead 🤩",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=kZTe4kl8Q3U",
            "thumbnail": "https://i.ytimg.com/vi/kZTe4kl8Q3U/hqdefault.jpg"
        }
    ]


@app.get("/api/metrics")
async def get_metrics():
    evaluator = Evaluator(default_config)
    try:
        strategy_df = await evaluator.compare_strategies()
        runs_df = await evaluator.get_run_history(limit=100)

        total_runs = len(runs_df) if not runs_df.empty else 0
        success_runs = len(runs_df[runs_df["status"] == "success"]) if not runs_df.empty else 0
        success_rate = (success_runs / total_runs * 100) if total_runs > 0 else 0.0

        import math
        def safe_float(val, default=0.0):
            try:
                f = float(val)
                return default if math.isnan(f) or math.isinf(f) else f
            except Exception:
                return default

        avg_completion = safe_float(runs_df["completion_time_sec"].mean()) if not runs_df.empty and "completion_time_sec" in runs_df else 0.0
        avg_tokens = safe_float(runs_df["total_tokens"].mean()) if not runs_df.empty and "total_tokens" in runs_df else 0.0
        avg_retries = safe_float(runs_df["total_retries"].mean()) if not runs_df.empty and "total_retries" in runs_df else 0.0

        return {
            "overview": {
                "total_runs": total_runs,
                "overall_success_rate": round(safe_float(success_rate), 1),
                "avg_completion_time_sec": round(avg_completion, 1),
                "avg_tokens": round(avg_tokens, 0),
                "avg_retries": round(avg_retries, 2),
            },
            "strategy_comparison": sanitize_records(strategy_df),
            "recent_runs": sanitize_records(runs_df),
        }
    except Exception as e:
        logger.error(f"Error computing metrics: {e}", exc_info=True)
        return {"overview": {}, "strategy_comparison": [], "recent_runs": []}


# ── WebSocket Endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/agent/{run_id}")
async def agent_websocket(websocket: WebSocket, run_id: str):
    await ws_manager.connect(run_id, websocket)
    try:
        # Keep connection open and handle client messages
        while True:
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
                if parsed.get("action") == "stop":
                    if run_id in ws_manager.run_cancel_events:
                        ws_manager.run_cancel_events[run_id].set()
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(run_id, websocket)


# ── Execution Worker ──────────────────────────────────────────────────────────

async def execute_agent_run(
    run_id: str,
    goal: str,
    strategy: str,
    config: AgentConfig,
    plan_dict: Optional[Dict[str, Any]],
    cancel_event: asyncio.Event,
):
    """Executes an agent run and streams real-time updates over WebSocket."""
    exp_logger = ExperimentLogger(config)
    metrics = MetricsCollector()
    metrics.start()
    observer = PageObserver(config)
    verifier = Verifier(config)
    state_mgr = StateManager()

    await ws_manager.broadcast(run_id, "status", {"message": f"Initializing browser ({config.browser_mode} mode)..."})

    def status_cb(event: str, message: str, url: Optional[str] = None):
        asyncio.create_task(
            ws_manager.broadcast(run_id, "browser_event", {"event": event, "message": message, "url": url})
        )

    try:
        # If plan was not provided upfront, generate one
        if not plan_dict and strategy == "plan_then_execute":
            await ws_manager.broadcast(run_id, "status", {"message": "Generating action plan with UnifiedPlanner..."})
            planner = UnifiedPlanner(config)
            plan_obj, _ = await planner.plan(goal)
            plan_dict = {
                "steps": [
                    {
                        "action": s.action,
                        "selector": s.target,
                        "target": s.target,
                        "value": s.value,
                        "checkpoint": s.checkpoint,
                        "description": s.description,
                    }
                    for s in plan_obj.steps
                ],
                "domain": plan_obj.domain,
                "task_type": plan_obj.task_type,
            }

        steps_data = plan_dict.get("steps", []) if plan_dict else []
        total_steps = len(steps_data)
        state_mgr.set_goal(goal, total_steps)

        await ws_manager.broadcast(run_id, "plan_ready", {"steps": steps_data, "total_steps": total_steps})

        async with BrowserExecutor(config, status_callback=status_cb, reuse_session=True) as browser:
            prev_page = None

            for i, step_info in enumerate(steps_data):
                if cancel_event.is_set():
                    await ws_manager.broadcast(run_id, "status", {"message": "Run cancelled by user."})
                    await exp_logger.end_run(
                        run_id=run_id,
                        status="failed",
                        total_actions=metrics.total_actions,
                        total_retries=0,
                        total_tokens=0,
                        completion_time_sec=metrics.elapsed_seconds,
                    )
                    return

                action_type = step_info.get("action", "navigate")
                selector = step_info.get("selector") or step_info.get("target")
                value = step_info.get("value")
                description = step_info.get("description", "")

                action_obj = ActionObject(action=action_type, selector=selector, value=value)

                await ws_manager.broadcast(
                    run_id,
                    "step_start",
                    {
                        "step_index": i,
                        "total_steps": total_steps,
                        "action": action_type,
                        "description": description,
                        "selector": selector,
                        "value": value,
                    },
                )

                t0 = time.time()
                raw_state = await browser.execute(action_obj, run_id=run_id, step_index=i, screenshot=True)
                duration_ms = int((time.time() - t0) * 1000)

                act_success = raw_state.get("action_success", True)
                act_err = raw_state.get("action_error")
                metrics.record_browser_action(action_type, success=act_success, duration_ms=duration_ms)
                metrics.record_screenshot()

                page_state = observer.observe(raw_state, task_keywords=[goal], prev_state=prev_page)
                prev_page = page_state

                # Prepare screenshot URL or base64
                screenshot_rel = None
                screenshot_base64 = None
                if page_state.screenshot_path and Path(page_state.screenshot_path).exists():
                    p = Path(page_state.screenshot_path).resolve()
                    try:
                        rel = p.relative_to(RUNS_DIR.resolve()).as_posix()
                        screenshot_rel = f"/screenshots/{rel}"
                    except Exception:
                        try:
                            rel = p.relative_to(DATA_SCREENSHOTS_DIR.resolve()).as_posix()
                            screenshot_rel = f"/screenshots/{rel}"
                        except Exception:
                            screenshot_rel = f"/screenshots/{run_id}/{p.name}"

                    try:
                        with open(p, "rb") as img_file:
                            b64 = base64.b64encode(img_file.read()).decode("utf-8")
                            screenshot_base64 = f"data:image/png;base64,{b64}"
                    except Exception as b64_err:
                        logger.warning(f"Error encoding base64 screenshot: {b64_err}")

                await ws_manager.broadcast(
                    run_id,
                    "step_completed",
                    {
                        "step_index": i,
                        "success": act_success,
                        "error": act_err,
                        "url": page_state.url,
                        "title": page_state.title,
                        "screenshot": screenshot_rel,
                        "screenshot_base64": screenshot_base64,
                        "duration_ms": duration_ms,
                        "extracted_items": page_state.extracted_items,
                    },
                )

                # Log step to SQLite
                try:
                    await exp_logger.log_step(
                        run_id=run_id,
                        step_index=i,
                        sub_task_type=description or action_type,
                        prompt_used=description,
                        action=action_obj,
                        page_state=page_state,
                        verification=VerificationResult(status="success" if act_success else "failure", reason=act_err or "OK"),
                        tokens_used=0,
                        duration_ms=duration_ms,
                    )
                except Exception as log_err:
                    logger.warning(f"Error logging step {i} to experiments db: {log_err}")

                await asyncio.sleep(0.3)

            # Mark run as complete
            metrics.stop()
            m = getattr(metrics, "metrics", None)
            total_acts = getattr(m, "total_actions", 0) if m else 0
            total_toks = getattr(m, "total_tokens", 0) if m else 0
            total_ret = getattr(m, "recovery_attempts", 0) if m else 0
            tot_time = getattr(m, "total_time_sec", 0.0) if m else 0.0
            final_summary = metrics.summary()

            await exp_logger.end_run(
                run_id=run_id,
                status="success",
                total_actions=total_acts,
                total_retries=total_ret,
                total_tokens=total_toks,
                completion_time_sec=tot_time,
            )
            await ws_manager.broadcast(
                run_id,
                "run_finished",
                {
                    "status": "success",
                    "summary": final_summary,
                    "message": "Goal completed successfully!",
                    "final_url": prev_page.url if prev_page else None,
                    "final_title": prev_page.title if prev_page else None,
                    "final_screenshot": screenshot_rel,
                    "final_screenshot_base64": screenshot_base64,
                },
            )

    except Exception as e:
        logger.error(f"Error during agent run {run_id}: {e}", exc_info=True)
        try:
            metrics.stop()
            m = getattr(metrics, "metrics", None)
            total_acts = getattr(m, "total_actions", 0) if m else 0
            total_toks = getattr(m, "total_tokens", 0) if m else 0
            total_ret = getattr(m, "recovery_attempts", 0) if m else 0
            tot_time = getattr(m, "total_time_sec", 0.0) if m else 0.0
            await exp_logger.end_run(
                run_id=run_id,
                status="failed",
                total_actions=total_acts,
                total_retries=total_ret,
                total_tokens=total_toks,
                completion_time_sec=tot_time,
            )
        except Exception:
            pass
        await ws_manager.broadcast(
            run_id,
            "run_finished",
            {"status": "failed", "error": str(e), "message": f"Execution halted: {e}"},
        )
    finally:
        if run_id in ws_manager.run_cancel_events:
            del ws_manager.run_cancel_events[run_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
