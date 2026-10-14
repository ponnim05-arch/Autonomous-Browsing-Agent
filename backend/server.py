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
import hmac
import json
import logging
import math
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# Playwright on Windows requires ProactorEventLoop for subprocess transport
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Compatibility shim for FastAPI when Starlette >= 1.0 or newer
try:
    import starlette.routing
    _orig_router_init = starlette.routing.Router.__init__
    def _patched_router_init(self, *args, **kwargs):
        kwargs.pop("on_startup", None)
        kwargs.pop("on_shutdown", None)
        return _orig_router_init(self, *args, **kwargs)
    starlette.routing.Router.__init__ = _patched_router_init
    if not hasattr(starlette.routing.Router, "add_event_handler"):
        starlette.routing.Router.add_event_handler = lambda self, event_type, func: None
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure src/ is in python path
ROOT_DIR = Path(__file__).parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent_framework.config import AgentConfig, IS_SERVER, default_config
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
# In production the Vercel-hosted frontend calls this API cross-origin, so the
# allowed origins come from CORS_ORIGINS (comma-separated). "*" keeps local dev easy.
_cors_origins_env = os.getenv("CORS_ORIGINS", "*").strip()
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] or ["*"]
_allow_credentials = "*" not in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure runs/screenshots directory exists and is mounted
APP_DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(ROOT_DIR))).resolve()
RUNS_DIR = APP_DATA_DIR / "logs" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
DATA_SCREENSHOTS_DIR = APP_DATA_DIR / "data" / "screenshots"
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
        self.run_sessions: Dict[str, Optional[str]] = {}
        self.active_browsers: Dict[str, Any] = {}
        self.run_plans: Dict[str, Dict[str, Any]] = {}
        self.run_states: Dict[str, Dict[str, Any]] = {}

    async def connect(self, run_id: str, websocket: WebSocket):
        await websocket.accept()
        if run_id not in self.active_connections:
            self.active_connections[run_id] = []
        self.active_connections[run_id].append(websocket)

        # Immediately deliver cached execution plan if already ready
        if run_id in self.run_plans:
            try:
                await websocket.send_text(
                    json.dumps({
                        "type": "plan_ready",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "data": self.run_plans[run_id],
                    })
                )
            except Exception:
                pass

        # Immediately deliver current step state if execution is in progress
        if run_id in self.run_states:
            try:
                await websocket.send_text(
                    json.dumps({
                        "type": "step_start",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "data": self.run_states[run_id],
                    })
                )
            except Exception:
                pass

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


# ── Session Lifecycle ─────────────────────────────────────────────────────────
# Every backend process owns a unique session id. A run started in a previous
# session is never resumable: startup cleanup marks stale RUNNING/PENDING rows
# as CANCELLED, and the frontend always opens with an empty Agent View.

CURRENT_SESSION: Dict[str, Any] = {}


def _new_session_id() -> str:
    return f"session_{uuid.uuid4().hex[:12].upper()}"


def _begin_session() -> str:
    CURRENT_SESSION["id"] = _new_session_id()
    CURRENT_SESSION["started_at"] = time.time()
    logger.info(f"[Session] New backend session: {CURRENT_SESSION['id']}")
    return CURRENT_SESSION["id"]


async def _mark_stale_runs_cancelled() -> int:
    """Mark RUNNING/PENDING runs left over from previous sessions as CANCELLED
    so no restart, reload or reconnect can ever pick them up again."""
    total = 0
    for db_file in _db_file_candidates():
        if not db_file.exists():
            continue
        try:
            import aiosqlite

            async with aiosqlite.connect(db_file) as db:
                cur = await db.execute(
                    "UPDATE experiment_runs SET status='cancelled', completed_at=datetime('now') "
                    "WHERE status IN ('running', 'pending')"
                )
                await db.commit()
                total += max(cur.rowcount or 0, 0)
        except Exception as e:
            logger.warning(f"[Session] Could not cancel stale runs in {db_file}: {e}")
    return total


async def _stop_all_runs(reason: str) -> int:
    """Signal every active run to cancel and mark them cancelled in the DB."""
    stopped = 0
    for rid, evt in list(ws_manager.run_cancel_events.items()):
        evt.set()
        stopped += 1
        await ws_manager.broadcast(rid, "status", {"message": reason})
    if stopped:
        try:
            await _mark_stale_runs_cancelled()
        except Exception as e:
            logger.warning(f"[Session] Could not mark stopped runs cancelled: {e}")
    return stopped


async def _close_browser_sessions() -> None:
    """Terminate any browser automation session owned by this process."""
    try:
        await BrowserExecutor.close_shared_session()
    except Exception as e:
        logger.debug(f"[Session] Shared browser close failed: {e}")


@app.on_event("startup")
async def _session_startup_cleanup():
    """Startup safety check: fresh session, stale runs cancelled, no orphan browsers."""
    _begin_session()
    cancelled = await _mark_stale_runs_cancelled()
    if cancelled:
        logger.info(f"[Session] Marked {cancelled} stale run(s) as cancelled from previous sessions.")
    try:
        BrowserExecutor._kill_zombie_playwright_browsers()
    except Exception as e:
        logger.debug(f"[Session] Zombie browser cleanup skipped: {e}")
    await _close_browser_sessions()


@app.on_event("shutdown")
async def _session_shutdown_cleanup():
    """Process shutdown: cancel all runs, close browsers, end the session."""
    logger.info(f"[Session] Shutting down session {CURRENT_SESSION.get('id')}")
    await _stop_all_runs("Backend session ended — agent stopped.")
    await _close_browser_sessions()
    CURRENT_SESSION["id"] = None


@app.get("/api/session")
async def get_session():
    """Current backend session info — the frontend uses this to detect restarts."""
    return {
        "session_id": CURRENT_SESSION.get("id"),
        "started_at": CURRENT_SESSION.get("started_at"),
        "active_runs": list(ws_manager.run_cancel_events.keys()),
    }


@app.post("/api/shutdown")
async def client_shutdown_beacon():
    """The frontend sends this beacon when the app window closes/reloads:
    stop all agents, cancel active tasks and close browser sessions.
    Idempotent — safe to receive multiple times."""
    stopped = await _stop_all_runs("Application closed — agent stopped.")
    await _close_browser_sessions()
    return {"status": "ok", "stopped_runs": stopped}


# ── Request / Response Schemas ────────────────────────────────────────────────

class PlanRequest(BaseModel):
    goal: str
    model: Optional[str] = None
    provider: Optional[str] = None
    strategy: str = "plan_then_execute"


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

def _provider_for_model(model: str) -> str:
    normalized = model.lower()
    if normalized.startswith(("meta/", "mistralai/", "nvidia/", "openai/gpt-oss")):
        return "nvidia"
    if normalized.startswith(("gpt-", "o1", "o3")) or normalized == "gpt-4o":
        return "openai"
    if normalized.startswith("claude"):
        return "anthropic"
    if normalized.startswith("gemini"):
        return "gemini"
    raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}


@app.post("/api/desktop/shutdown")
async def desktop_shutdown(request: Request):
    token = os.getenv("DESKTOP_CONTROL_TOKEN", "")
    supplied = request.headers.get("x-desktop-control-token", "")
    if not token or not hmac.compare_digest(token, supplied):
        raise HTTPException(status_code=403, detail="Desktop shutdown is not authorized")

    server = getattr(app.state, "desktop_uvicorn_server", None)
    if server is None:
        raise HTTPException(status_code=503, detail="Desktop server controller is unavailable")
    server.should_exit = True
    return {"status": "shutting_down"}


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
        "browser_is_remote": IS_SERVER,
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


class ApiKeysUpdate(BaseModel):
    """Schema for updating API keys via the settings page."""
    nvidia_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    serpapi_key: Optional[str] = None
    google_cse_key: Optional[str] = None
    google_cse_cx: Optional[str] = None
    bing_search_key: Optional[str] = None


def _mask_key(value: str | None) -> str:
    """Mask an API key, showing only the first 8 and last 4 characters."""
    if not value:
        return ""
    v = value.strip()
    if len(v) <= 12:
        return "*" * len(v) if v else ""
    return v[:8] + "*" * (len(v) - 12) + v[-4:]


@app.get("/api/settings/keys")
async def get_api_keys():
    """Return current API keys in masked form, plus links to obtain them."""
    cfg = AgentConfig()
    return {
        "keys": {
            "nvidia_api_key": _mask_key(cfg.nvidia_api_key),
            "gemini_api_key": _mask_key(cfg.gemini_api_key),
            "openai_api_key": _mask_key(cfg.openai_api_key),
            "anthropic_api_key": _mask_key(cfg.anthropic_api_key),
            "serpapi_key": _mask_key(cfg.serpapi_key),
            "google_cse_key": _mask_key(cfg.google_cse_key),
            "google_cse_cx": _mask_key(cfg.google_cse_cx),
            "bing_search_key": _mask_key(cfg.bing_search_key),
        },
        "providers": [
            {
                "id": "nvidia_api_key",
                "name": "NVIDIA NIM",
                "description": "Access Llama, Nemotron, and other models via NVIDIA AI Foundation",
                "link": "https://build.nvidia.com/explore/discover",
                "link_label": "Get NVIDIA API Key",
                "env_var": "NVIDIA_API_KEY",
                "category": "llm",
            },
            {
                "id": "gemini_api_key",
                "name": "Google Gemini",
                "description": "Access Gemini 2.5 Flash and Pro models from Google AI Studio",
                "link": "https://aistudio.google.com/apikey",
                "link_label": "Get Gemini API Key",
                "env_var": "GEMINI_API_KEY",
                "category": "llm",
            },
            {
                "id": "openai_api_key",
                "name": "OpenAI",
                "description": "Access GPT-4o and other OpenAI models",
                "link": "https://platform.openai.com/api-keys",
                "link_label": "Get OpenAI API Key",
                "env_var": "OPENAI_API_KEY",
                "category": "llm",
            },
            {
                "id": "anthropic_api_key",
                "name": "Anthropic Claude",
                "description": "Access Claude 3.7 Sonnet and other Anthropic models",
                "link": "https://console.anthropic.com/settings/keys",
                "link_label": "Get Anthropic API Key",
                "env_var": "ANTHROPIC_API_KEY",
                "category": "llm",
            },
            {
                "id": "serpapi_key",
                "name": "SerpAPI",
                "description": "Google search results API (optional, falls back to DuckDuckGo)",
                "link": "https://serpapi.com/manage-api-key",
                "link_label": "Get SerpAPI Key",
                "env_var": "SERPAPI_KEY",
                "category": "search",
            },
            {
                "id": "google_cse_key",
                "name": "Google Custom Search",
                "description": "Google Programmable Search Engine API key",
                "link": "https://programmablesearchengine.google.com/controlpanel/all",
                "link_label": "Get Google CSE Key",
                "env_var": "GOOGLE_CSE_KEY",
                "category": "search",
            },
            {
                "id": "google_cse_cx",
                "name": "Google CSE ID",
                "description": "Your Custom Search Engine ID (cx parameter)",
                "link": "https://programmablesearchengine.google.com/controlpanel/all",
                "link_label": "Get Search Engine ID",
                "env_var": "GOOGLE_CSE_CX",
                "category": "search",
            },
            {
                "id": "bing_search_key",
                "name": "Bing Search",
                "description": "Microsoft Bing Search API key",
                "link": "https://www.microsoft.com/en-us/bing/apis/bing-web-search-api",
                "link_label": "Get Bing Search Key",
                "env_var": "BING_SEARCH_KEY",
                "category": "search",
            },
        ],
    }


@app.put("/api/settings/keys")
async def update_api_keys(body: ApiKeysUpdate):
    """Save updated API keys to the .env file and reload them in-process."""
    from agent_framework.config import ENV_PATH_ROOT, ENV_PATH_BACKEND, _reload_env

    env_path = ENV_PATH_ROOT if ENV_PATH_ROOT.exists() else ENV_PATH_BACKEND
    if not env_path.exists():
        env_path = ENV_PATH_ROOT
        env_path.write_text("# Auto-generated by settings UI\n")

    content = env_path.read_text(encoding="utf-8")
    updates = body.dict(exclude_none=True)
    if not updates:
        return {"status": "no_changes"}

    env_var_map = {
        "nvidia_api_key": "NVIDIA_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "serpapi_key": "SERPAPI_KEY",
        "google_cse_key": "GOOGLE_CSE_KEY",
        "google_cse_cx": "GOOGLE_CSE_CX",
        "bing_search_key": "BING_SEARCH_KEY",
    }

    lines = content.splitlines()
    for field_name, value in updates.items():
        # Skip masked values (user didn't change them)
        if "*" in value:
            continue
        env_key = env_var_map.get(field_name)
        if not env_key:
            continue
        # Update in-process environment
        os.environ[env_key] = value
        # Update .env file
        found = False
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(f"{env_key}=") or stripped.startswith(f"# {env_key}="):
                lines[i] = f"{env_key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{env_key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _reload_env()
    return {"status": "saved", "updated": list(updates.keys())}


@app.post("/api/plan")
async def generate_plan(req: PlanRequest):
    if not req.goal.strip():
        raise HTTPException(status_code=400, detail="Goal cannot be empty")
    cfg = AgentConfig()
    if req.model:
        cfg.fast_model = req.model
        cfg.llm_model = req.model
        cfg.llm_provider = _provider_for_model(req.model)
    cfg.experiment_strategy = req.strategy

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
    cfg = AgentConfig(
        browser_mode=req.browser_mode,
        headless=req.browser_mode == "headless",
        browser_type=req.browser_type,
        browser_connection_mode="cdp" if req.browser_mode == "cdp" else "playwright",
        cdp_endpoint=req.cdp_endpoint or "http://127.0.0.1:9222",
        reuse_browser=req.keep_browser_open,
        keep_browser_open=req.keep_browser_open,
    )
    cfg.experiment_strategy = req.strategy

    # Determine provider from model
    clean_model = req.model
    cfg.llm_provider = _provider_for_model(clean_model)

    cfg.llm_model = clean_model
    cfg.fast_model = clean_model

    exp_logger = ExperimentLogger(cfg)
    run_id = await exp_logger.start_run(req.goal, req.strategy)

    # Initialize cancel event and bind run to the current session
    cancel_event = asyncio.Event()
    ws_manager.run_cancel_events[run_id] = cancel_event
    ws_manager.run_sessions[run_id] = CURRENT_SESSION.get("id")

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


# ── Run Deletion / Clearing Helpers ───────────────────────────────────────────

def _db_file_candidates() -> List[Path]:
    """Possible locations of the SQLite experiments DB (CWD-relative or backend-relative)."""
    rel = default_config.db_path
    candidates = [Path(rel), ROOT_DIR / rel]
    seen, unique = set(), []
    for c in candidates:
        rp = c.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(c)
    return unique


def _run_artifact_dirs() -> List[Path]:
    """Possible base dirs holding per-run artifacts (trace.jsonl, CSVs, screenshots)."""
    rel = default_config.log_dir
    candidates = [Path(rel), ROOT_DIR / rel, RUNS_DIR]
    seen, unique = set(), []
    for c in candidates:
        rp = c.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(c)
    return unique


def _delete_run_artifacts(run_id: str) -> bool:
    """Remove on-disk artifacts (screenshots, JSONL traces, CSV exports) for a run."""
    removed = False
    for base in _run_artifact_dirs():
        run_dir = base / run_id
        if run_dir.is_dir():
            shutil.rmtree(run_dir, ignore_errors=True)
            removed = True
    return removed


async def _delete_run_rows(db_file: Path, run_id: str) -> int:
    """Delete all DB rows for a run. Returns the number of rows removed."""
    deleted = 0
    try:
        import aiosqlite

        async with aiosqlite.connect(db_file) as db:
            for table in ("action_steps", "prompt_repairs", "experiment_runs"):
                cur = await db.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
                deleted += max(cur.rowcount or 0, 0)
            await db.commit()
    except ImportError:
        import sqlite3

        def _sync() -> int:
            n = 0
            with sqlite3.connect(db_file) as conn:
                for table in ("action_steps", "prompt_repairs", "experiment_runs"):
                    cur = conn.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
                    n += max(cur.rowcount or 0, 0)
                conn.commit()
            return n

        deleted = await asyncio.to_thread(_sync)
    return deleted


async def _delete_run_everything(run_id: str) -> Dict[str, Any]:
    """Delete a run from every DB candidate location plus its on-disk artifacts."""
    rows_deleted = 0
    for db_file in _db_file_candidates():
        if db_file.exists():
            try:
                rows_deleted += await _delete_run_rows(db_file, run_id)
            except Exception as e:
                logger.warning(f"DB delete failed for {db_file}: {e}")
    artifacts_deleted = _delete_run_artifacts(run_id)
    return {"rows_deleted": rows_deleted, "artifacts_deleted": artifacts_deleted}


@app.post("/api/runs/{run_id}/clear")
async def clear_run(run_id: str):
    """Clear a running task: cancels execution, marks the record 'cancelled',
    and notifies all listeners to reset their live view."""
    was_running = run_id in ws_manager.run_cancel_events
    if was_running:
        ws_manager.run_cancel_events[run_id].set()
        await ws_manager.broadcast(run_id, "status", {"message": "Run cleared by user."})
    # Finalize any lingering 'running'/'pending' row (live or stale) so it can
    # never be treated as active after a restart.
    for db_file in _db_file_candidates():
        if not db_file.exists():
            continue
        try:
            import aiosqlite

            async with aiosqlite.connect(db_file) as db:
                await db.execute(
                    "UPDATE experiment_runs SET status='cancelled', completed_at=datetime('now') "
                    "WHERE run_id=? AND status IN ('running', 'pending')",
                    (run_id,),
                )
                await db.commit()
        except Exception as e:
            logger.warning(f"Could not mark run {run_id} cancelled: {e}")
    await ws_manager.broadcast(run_id, "run_cleared", {"run_id": run_id})
    return {"status": "cleared", "was_running": was_running}


@app.delete("/api/runs")
async def clear_all_runs():
    """Delete ALL recorded runs: DB rows, JSONL traces, screenshots, CSV exports."""
    # Cancel anything still executing so nothing writes new rows mid-deletion.
    running_ids = list(ws_manager.run_cancel_events.keys())
    for rid in running_ids:
        ws_manager.run_cancel_events[rid].set()
        await ws_manager.broadcast(rid, "status", {"message": "Run cleared by user."})

    all_run_ids: set = set(running_ids)
    for db_file in _db_file_candidates():
        if not db_file.exists():
            continue
        try:
            import aiosqlite

            async with aiosqlite.connect(db_file) as db:
                async with db.execute("SELECT run_id FROM experiment_runs") as cur:
                    all_run_ids.update(row[0] for row in await cur.fetchall())
                await db.execute("DELETE FROM action_steps")
                await db.execute("DELETE FROM prompt_repairs")
                await db.execute("DELETE FROM experiment_runs")
                await db.commit()
        except Exception as e:
            logger.warning(f"Could not clear DB {db_file}: {e}")

    # Wipe every artifact directory.
    for base in _run_artifact_dirs():
        if base.is_dir():
            for child in base.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink()
                except Exception:
                    pass

    for rid in running_ids:
        await ws_manager.broadcast(rid, "run_cleared", {"run_id": rid})

    return {"status": "cleared", "deleted_runs": len(all_run_ids)}


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a single recorded run with all of its steps, repairs and artifacts."""
    if run_id in ws_manager.run_cancel_events:
        raise HTTPException(status_code=409, detail="Run is still executing — stop or clear it first.")
    result = await _delete_run_everything(run_id)
    if result["rows_deleted"] == 0 and not result["artifacts_deleted"]:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "deleted", "run_id": run_id, **result}


@app.get("/api/related-videos")
async def get_related_videos(query: str = ""):
    """
    Returns top 10 YouTube videos related to the given search query.
    When query is empty, falls back to the curated Prasad Tech list or local cache.
    """
    import re as _re

    # ── Helper: parse YouTube search HTML for video cards ────────────────────
    async def _fetch_youtube_search(search_query: str) -> list:
        """Scrape YouTube search results using httpx (no API key needed)."""
        search_url = "https://www.youtube.com/results"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        params = {"search_query": search_query, "sp": "CAI%253D"}  # sort by upload date
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(search_url, params=params, headers=headers)
                resp.raise_for_status()
                html = resp.text

            # YouTube embeds its data as JSON in ytInitialData
            match = _re.search(r"var ytInitialData\s*=\s*(\{.+?\});\s*</script>", html, _re.DOTALL)
            if not match:
                return []
            raw_json = match.group(1)
            data = json.loads(raw_json)

            contents = (
                data.get("contents", {})
                    .get("twoColumnSearchResultsRenderer", {})
                    .get("primaryContents", {})
                    .get("sectionListRenderer", {})
                    .get("contents", [])
            )

            videos = []
            rank = 1
            for section in contents:
                items = (
                    section.get("itemSectionRenderer", {}).get("contents", [])
                )
                for item in items:
                    vr = item.get("videoRenderer")
                    if not vr:
                        continue
                    video_id = vr.get("videoId", "")
                    if not video_id:
                        continue

                    title = (
                        vr.get("title", {})
                          .get("runs", [{}])[0]
                          .get("text", "")
                    )
                    author = (
                        vr.get("ownerText", {})
                          .get("runs", [{}])[0]
                          .get("text", "")
                    )
                    thumbnails = vr.get("thumbnail", {}).get("thumbnails", [])
                    thumbnail = (
                        thumbnails[-1]["url"] if thumbnails
                        else f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                    )
                    # Duration
                    duration = (
                        vr.get("lengthText", {}).get("simpleText", "")
                    )
                    # View count
                    views = (
                        vr.get("viewCountText", {}).get("simpleText", "")
                        or vr.get("viewCountText", {})
                              .get("runs", [{}])[0]
                              .get("text", "")
                    )
                    # Published time
                    time_ago = (
                        vr.get("publishedTimeText", {}).get("simpleText", "")
                    )

                    videos.append({
                        "rank": rank,
                        "videoId": video_id,
                        "title": title,
                        "author": author,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "thumbnail": thumbnail,
                        "duration": duration,
                        "views": views,
                        "timeAgo": time_ago,
                    })
                    rank += 1
                    if rank > 10:
                        break
                if rank > 10:
                    break
            return videos
        except Exception as exc:
            logger.warning(f"[related-videos] YouTube scrape failed for '{search_query}': {exc}")
            return []

    # ── If a query was provided, do a live YouTube search ────────────────────
    if query.strip():
        results = await _fetch_youtube_search(query.strip())
        if results:
            return results
        # If live search failed, still return empty so the frontend can show a message
        return []

    # ── No query: try local cache first ──────────────────────────────────────
    local_cached = ROOT_DIR / "data" / "latest_prasad_tech_videos.json"
    if local_cached.exists():
        try:
            with open(local_cached, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # ── Final curated fallback (Prasad Tech in Telugu) ───────────────────────
    return [
        {
            "rank": 1,
            "videoId": "kGU6fiO9WuU",
            "title": "POCO X8 Series Unboxing & Initial Impressions || Insane Battery Phones 🤯",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=kGU6fiO9WuU",
            "thumbnail": "https://i.ytimg.com/vi/kGU6fiO9WuU/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 2,
            "videoId": "S_2CR951ErA",
            "title": "Infinix HOT 70 Pro 5G Unboxing & Initial Impressions || The New Budget King? 😱",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=S_2CR951ErA",
            "thumbnail": "https://i.ytimg.com/vi/S_2CR951ErA/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 3,
            "videoId": "q237uN0nfOY",
            "title": "Tech News 2241 || iQOO 16, iOS 27, Xiaomi 18 Fold, Nothing 2027 Launches, Smart Wheelchair, Robot",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=q237uN0nfOY",
            "thumbnail": "https://i.ytimg.com/vi/q237uN0nfOY/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 4,
            "videoId": "uV5JVRXXUcA",
            "title": "Tech News 2240 || OnePlus 16, Huawei Mate XT 2, Gemini Coding, IMEI Tamper, Sim Swap",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=uV5JVRXXUcA",
            "thumbnail": "https://i.ytimg.com/vi/uV5JVRXXUcA/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 5,
            "videoId": "EeUxMaCqxHo",
            "title": "Which is the best Water Purifier? Urban Native M3 pro vs Aquaguard ritz pro 4X",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=EeUxMaCqxHo",
            "thumbnail": "https://i.ytimg.com/vi/EeUxMaCqxHo/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 6,
            "videoId": "82JoLvTNhOc",
            "title": "vivo T5 5G Unboxing & First Impressions || 7050mAh Battery + 144Hz AMOLED | Telugu",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=82JoLvTNhOc",
            "thumbnail": "https://i.ytimg.com/vi/82JoLvTNhOc/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 7,
            "videoId": "Wvv6wfWQlLM",
            "title": "HONOR Robot Phone Is INSANE 😲🤯 | A Real-Life SCI-FI Phone! 🥳",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=Wvv6wfWQlLM",
            "thumbnail": "https://i.ytimg.com/vi/Wvv6wfWQlLM/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 8,
            "videoId": "n48kAO6cMAs",
            "title": "Tech News 2238 || Mobile Prices GST Cut, iPhone Ultra, New Mac's, Plaud One, Meta.Etc..",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=n48kAO6cMAs",
            "thumbnail": "https://i.ytimg.com/vi/n48kAO6cMAs/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 9,
            "videoId": "1oD_4E2_lcM",
            "title": "Nothing OS 5.0 New Features & Changes Explained! 🥳",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=1oD_4E2_lcM",
            "thumbnail": "https://i.ytimg.com/vi/1oD_4E2_lcM/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
        },
        {
            "rank": 10,
            "videoId": "kZTe4kl8Q3U",
            "title": "Upcoming Mobiles in September 2026 🥳 || Exciting Launches ahead 🤩",
            "author": "Prasadtechintelugu",
            "url": "https://www.youtube.com/watch?v=kZTe4kl8Q3U",
            "thumbnail": "https://i.ytimg.com/vi/kZTe4kl8Q3U/hqdefault.jpg",
            "duration": "", "views": "", "timeAgo": "",
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
    # Orphan guard: if no run is executing for this id (e.g. backend restarted,
    # or the client reconnected to an old run), tell the client to reset its
    # Agent View instead of waiting forever. Never resumes an old task.
    if run_id not in ws_manager.run_cancel_events:
        await ws_manager.broadcast(run_id, "run_cleared", {"run_id": run_id})
    try:
        # Keep connection open and handle client messages
        while True:
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
                act = parsed.get("action")
                if act == "stop":
                    if run_id in ws_manager.run_cancel_events:
                        ws_manager.run_cancel_events[run_id].set()
                elif act == "interact":
                    browser = ws_manager.active_browsers.get(run_id)
                    if browser:
                        interaction_type = parsed.get("type", "")
                        await browser.handle_interaction(interaction_type, parsed)
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(run_id, websocket)


# ── Execution Worker ──────────────────────────────────────────────────────────

async def _encode_screenshot(page_state, run_id: str) -> tuple:
    """Encode a screenshot from page state into (relative_url, base64_data)."""
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
    return screenshot_rel, screenshot_base64


def _verify_goal_heuristic(goal: str, final_url: str | None, final_title: str | None, steps_succeeded: int, total_steps: int, failed_steps: list) -> tuple:
    """Rule-based goal verification. Returns (is_verified: bool, message: str).

    Checks whether the final browser state plausibly matches the user's goal
    instead of blindly reporting success after all steps have been attempted.
    """
    goal_lower = goal.lower()
    url_lower = (final_url or "").lower()
    title_lower = (final_title or "").lower()

    # If the majority of steps failed, don't claim success
    if failed_steps and len(failed_steps) > total_steps * 0.4:
        return False, f"{len(failed_steps)} of {total_steps} actions failed. Goal may not be fully achieved."

    # Check if the final page matches expected keywords from the goal
    goal_keywords = [w for w in goal_lower.split() if len(w) > 3 and w not in (
        "open", "from", "this", "that", "with", "what", "find", "search", "google", "using", "want", "please",
        "could", "would", "should", "make", "into", "submit", "enter", "type", "click", "navigate",
    )]

    if not final_url or final_url in ("", "about:blank"):
        return False, "Browser did not navigate to any page."

    # Check for common target sites mentioned in the goal
    site_checks = {
        "chatgpt": ("chatgpt" in url_lower or "chat.openai" in url_lower),
        "google": ("google" in url_lower),
        "amazon": ("amazon" in url_lower),
        "youtube": ("youtube" in url_lower or "youtu.be" in url_lower),
        "flipkart": ("flipkart" in url_lower),
    }
    for site_name, is_on_site in site_checks.items():
        if site_name in goal_lower and not is_on_site:
            return False, f"Goal mentions '{site_name}' but final page is on {final_url}"

    # If all steps succeeded, check for obvious failure signals
    error_signals = ["404", "not found", "error", "access denied", "blocked", "captcha"]
    if any(sig in title_lower for sig in error_signals):
        return False, f"Final page appears to be an error page: '{final_title}'"

    if steps_succeeded == total_steps:
        return True, f"All {total_steps} actions completed successfully. Final page: {final_title or final_url}"

    if steps_succeeded > 0:
        return True, f"{steps_succeeded} of {total_steps} actions completed. Some steps had issues but goal may be partially achieved."

    return False, "No actions completed successfully."


MAX_ACTION_RETRIES = 2


async def execute_agent_run(
    run_id: str,
    goal: str,
    strategy: str,
    config: AgentConfig,
    plan_dict: Optional[Dict[str, Any]],
    cancel_event: asyncio.Event,
):
    """Executes an agent run and streams real-time updates over WebSocket.

    Improvements over the original:
    - Action retry: failed actions are retried up to MAX_ACTION_RETRIES times
    - Halt on prerequisite failure: terminal failures stop dependent actions
    - Goal verification: success is verified against the final page state
    - Continuous screenshot streaming for responsive viewport updates
    """
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

    screenshot_rel = None
    screenshot_base64 = None

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

        plan_payload = {"steps": steps_data, "total_steps": total_steps}
        ws_manager.run_plans[run_id] = plan_payload
        await ws_manager.broadcast(run_id, "plan_ready", plan_payload)

        def frame_cb(frame_data: dict[str, Any]):
            asyncio.create_task(
                ws_manager.broadcast(run_id, "viewport_frame", frame_data)
            )

        async with BrowserExecutor(config, status_callback=status_cb, frame_callback=frame_cb, reuse_session=True) as browser:
            ws_manager.active_browsers[run_id] = browser
            prev_page = None
            steps_succeeded = 0
            failed_steps: list[dict] = []
            halted = False

            for i, step_info in enumerate(steps_data):
                if cancel_event.is_set():
                    await ws_manager.broadcast(run_id, "status", {"message": "Run cancelled by user."})
                    await exp_logger.end_run(
                        run_id=run_id,
                        status="cancelled",
                        total_actions=metrics.total_actions,
                        total_retries=0,
                        total_tokens=0,
                        completion_time_sec=metrics.elapsed_seconds,
                    )
                    return

                if halted:
                    await ws_manager.broadcast(run_id, "step_start", {
                        "step_index": i, "total_steps": total_steps,
                        "action": step_info.get("action", ""), "description": "Skipped — prerequisite failed",
                        "selector": step_info.get("selector"), "value": step_info.get("value"),
                    })
                    await ws_manager.broadcast(run_id, "step_completed", {
                        "step_index": i, "success": False,
                        "error": "Skipped due to earlier prerequisite failure",
                        "url": prev_page.url if prev_page else None,
                        "title": prev_page.title if prev_page else None,
                        "screenshot": screenshot_rel,
                        "screenshot_base64": screenshot_base64,
                        "duration_ms": 0,
                        "extracted_items": [],
                    })
                    continue

                action_type = step_info.get("action", "navigate")
                selector = step_info.get("selector") or step_info.get("target")
                value = step_info.get("value")
                description = step_info.get("description", "")

                action_obj = ActionObject(action=action_type, selector=selector, value=value)

                step_start_payload = {
                    "step_index": i,
                    "total_steps": total_steps,
                    "action": action_type,
                    "description": description,
                    "selector": selector,
                    "value": value,
                }
                ws_manager.run_states[run_id] = step_start_payload
                await ws_manager.broadcast(run_id, "step_start", step_start_payload)

                # ── Action execution with retry ──────────────────────────
                act_success = False
                act_err = None
                raw_state = {}
                duration_ms = 0

                for attempt in range(1, MAX_ACTION_RETRIES + 2):  # 1 try + MAX_ACTION_RETRIES retries
                    if cancel_event.is_set():
                        break

                    t0 = time.time()
                    try:
                        raw_state = await browser.execute(action_obj, run_id=run_id, step_index=i, screenshot=True)
                        duration_ms = int((time.time() - t0) * 1000)
                        act_success = raw_state.get("action_success", True)
                        act_err = raw_state.get("action_error")

                        if act_success:
                            break  # Success — no retry needed

                        # Action reported failure — determine if retryable
                        if attempt <= MAX_ACTION_RETRIES:
                            await ws_manager.broadcast(run_id, "status", {
                                "message": f"⚠️ Step {i+1} failed (attempt {attempt}/{MAX_ACTION_RETRIES+1}): {act_err}. Retrying..."
                            })
                            await asyncio.sleep(0.5 * attempt)  # Exponential backoff
                        # else: final attempt also failed — will be handled below

                    except BrowserBlockedError:
                        raise  # Safety block — never retry
                    except Exception as exec_err:
                        duration_ms = int((time.time() - t0) * 1000)
                        act_success = False
                        act_err = str(exec_err)
                        raw_state = {"url": "", "title": "", "action_success": False, "action_error": act_err}

                        if attempt <= MAX_ACTION_RETRIES:
                            await ws_manager.broadcast(run_id, "status", {
                                "message": f"⚠️ Step {i+1} error (attempt {attempt}/{MAX_ACTION_RETRIES+1}): {act_err}. Retrying..."
                            })
                            await asyncio.sleep(0.5 * attempt)

                metrics.record_browser_action(action_type, success=act_success, duration_ms=duration_ms)
                metrics.record_screenshot()

                page_state = observer.observe(raw_state, task_keywords=[goal], prev_state=prev_page)
                prev_page = page_state

                screenshot_rel, screenshot_base64 = await _encode_screenshot(page_state, run_id)

                if act_success:
                    steps_succeeded += 1
                else:
                    failed_steps.append({"step_index": i, "action": action_type, "error": act_err})
                    is_checkpoint = step_info.get("checkpoint", False)
                    # Halt on prerequisite failure: navigate and checkpoint failures are terminal
                    if action_type == "navigate" or is_checkpoint:
                        halted = True
                        await ws_manager.broadcast(run_id, "status", {
                            "message": f"❌ Step {i+1} failed after {MAX_ACTION_RETRIES+1} attempts: {act_err}. Halting dependent steps."
                        })

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

                await asyncio.sleep(0.15)  # Reduced from 0.3 for better responsiveness

            # ── Goal Verification ────────────────────────────────────────
            final_url = prev_page.url if prev_page else None
            final_title = prev_page.title if prev_page else None

            goal_verified, verification_message = _verify_goal_heuristic(
                goal, final_url, final_title, steps_succeeded, total_steps, failed_steps
            )

            metrics.stop()
            m = getattr(metrics, "metrics", None)
            total_acts = getattr(m, "total_actions", 0) if m else 0
            total_toks = getattr(m, "total_tokens", 0) if m else 0
            total_ret = getattr(m, "recovery_attempts", 0) if m else 0
            tot_time = getattr(m, "total_time_sec", 0.0) if m else 0.0
            final_summary = metrics.summary()

            if goal_verified:
                run_status = "success"
                run_message = f"🎉 {verification_message}"
            elif steps_succeeded > 0 and not halted:
                run_status = "success"
                run_message = f"⚠️ {verification_message}"
            else:
                run_status = "failed"
                run_message = f"❌ {verification_message}"
                if failed_steps:
                    last_fail = failed_steps[-1]
                    run_message += f" Last failure at step {last_fail['step_index']+1}: {last_fail['error']}"

            await exp_logger.end_run(
                run_id=run_id,
                status=run_status,
                total_actions=total_acts,
                total_retries=total_ret,
                total_tokens=total_toks,
                completion_time_sec=tot_time,
            )
            await ws_manager.broadcast(
                run_id,
                "run_finished",
                {
                    "status": run_status,
                    "summary": final_summary,
                    "message": run_message,
                    "final_url": final_url,
                    "final_title": final_title,
                    "final_screenshot": screenshot_rel,
                    "final_screenshot_base64": screenshot_base64,
                    "steps_succeeded": steps_succeeded,
                    "steps_failed": len(failed_steps),
                    "total_steps": total_steps,
                    "steps": steps_data,
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
        ws_manager.run_sessions.pop(run_id, None)
        ws_manager.active_browsers.pop(run_id, None)


_frontend_dist_dir = Path(
    os.getenv("APP_FRONTEND_DIST", str(ROOT_DIR / "frontend_dist"))
).resolve()
if _frontend_dist_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist_dir), html=True), name="desktop_frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
