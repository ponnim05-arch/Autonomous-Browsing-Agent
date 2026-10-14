# Adaptive Prompt Engineering Framework for Reliable Autonomous Web Agents

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/Frontend-React%2019-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/Language-TypeScript-3178C6.svg)](https://www.typescriptlang.org/)
[![Playwright](https://img.shields.io/badge/Engine-Playwright-45ba4b.svg)](https://playwright.dev/)
[![Electron](https://img.shields.io/badge/Desktop-Electron-47848F.svg)](https://www.electronjs.org/)
[![Tests](https://img.shields.io/badge/Tests-97%20Passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Final Year AIML Research Project**  
> *"Can dynamically generated and self-evaluated prompts improve the reliability of autonomous browser agents, compared to static prompts?"*

---

## 📌 Executive Overview

Traditional browser automation agents rely on fixed, static prompts that frequently break when encountering dynamic web layouts, dynamic Single Page Applications (SPAs), anti-bot challenges, or modal popups. This framework implements an **adaptive micro-pipeline** that dynamically plans, generates, evaluates, and repairs prompts and actions at runtime.

The system combines:
1. **A High-Performance FastAPI Backend**: Houses the core agent framework, browser execution engine, telemetry collectors, and WebSocket streaming.
2. **A Modern React 19 Frontend**: Real-time glassmorphism interface powered by Vite, Tailwind CSS v4, Lucide Icons, and Recharts with live browser screenshot viewport streaming.
3. **An Intelligent Dual-Tier Model Router**: Intelligently routes tasks between ultra-fast vision models (`FAST`), deep reasoning models (`REASONING`), and deterministic zero-token local actions (`NO_LLM`).
4. **Unified Plan-then-Execute Engine**: Pre-plans deterministic action sequences with checkpoints for blazing speed, with automatic fallback to adaptive Observe-Think-Act loops upon uncertainty or DOM drift.
5. **Multi-Platform Delivery**: Runs as a local web app, a standalone packaged Windows desktop application (Electron), or a split cloud deployment (Vercel frontend + Render backend).

---

## ⚡ Key Highlights & Capabilities

- 🔄 **5 Swappable Prompting & Execution Strategies**:
  - `plan_then_execute` (⚡ Ultra Fast single-call planner + deterministic execution)
  - `dynamic` (🟢 Classic adaptive Observe-Think-Act loop)
  - `static` (🔵 Empirical baseline with fixed prompts)
  - `self_reflective` (🟡 Chain-of-thought DOM delta reasoning)
  - `failure_recovery` (🔴 Self-healing diagnostic repairs)
- 🧠 **Multi-Tier Model Routing (`model_router.py`)**:
  - `NO_LLM`: Deterministic actions (navigation, scrolling, waiting, high-confidence verification) execute with zero token latency.
  - `FAST`: Lightweight fast instruction/vision models (e.g., `meta/llama-3.2-11b-vision-instruct`).
  - `REASONING`: Heavy reasoning models for recovery and complex parsing (e.g., `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, `deepseek-ai/deepseek-r1`).
  - Primary provider: **NVIDIA AI Foundations / NIM API** (with separate fast & reasoning keys) plus native fallbacks to **Google Gemini**, **OpenAI**, and **Anthropic**.
- 🌐 **Resilient Browser Execution Engine (`browser_executor.py`)**:
  - Cascading browser resolution: Requested Browser &rarr; Microsoft Edge &rarr; Google Chrome &rarr; Bundled Chromium.
  - Supports **Visible** (headed window), **Headless** (background), and **CDP Mode** (attaches to an existing Chrome instance on port 9222).
  - Anti-bot stealth scripts, dynamic popup auto-dismissal, multi-tab coordination, and intelligent element highlighting.
- 🛒 **Advanced Multi-Cart & Personal Assistant Mode**:
  - Automatically identifies bulk requests (e.g., *"find top 5 mechanical keyboards and add all to cart"*) and reliably iterates product listings, handles variant tabs, and enforces cart verification.
  - Safe guardrails: Configurable URL blocklists prevent unintended checkout or payment submissions.
- 📊 **Telemetry & Analytics Suite**:
  - Dual persistence (Local SQLite `data/experiments.db` + JSONL step-by-step traces `logs/runs/*.jsonl` + optional cloud Supabase sync).
  - Tracks Task Success Rate (TSR), average retries, latency, token usage (input/output), and model tier distribution.
- ⚙️ **In-App Settings Management**:
  - Update API keys (NVIDIA, Gemini, OpenAI, Anthropic, SerpAPI, Google CSE, Bing) directly inside the React UI with instant validation—no manual `.env` file editing required.

---

## 🏗️ System Architecture

```
                                  User NL Goal
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │  Strategy Selector / Model Router │
                     └─────────────────┬─────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌───────────────────────┐                             ┌───────────────────────┐
│ Unified Planner       │                             │ Dynamic Loop Pipeline │
│ (Plan-then-Execute)   │                             │ (Observe-Think-Act)   │
│ 1-Call Action Matrix  │                             │ Intent -> Decompose   │
└───────────┬───────────┘                             └───────────┬───────────┘
            │                                                     │
            └──────────────────────────┬──────────────────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │ Browser Executor (Playwright) │
                       │ Edge / Chrome / Chromium / CDP│
                       └───────────────┬───────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌───────────────────────┐                             ┌───────────────────────┐
│ Page Observer         │                             │ Verifier & Repair     │
│ Pruned Accessibility  │                             │ Multi-check heuristic │
│ Tree & Screenshots    │                             │ + Semantic Evaluation │
└───────────┬───────────┘                             └───────────┬───────────┘
            │                                                     │
            │                  If Failure Detected                │
            │          ┌──────────────────────────────────────────┘
            │          ▼
            │ ┌─────────────────────────────────┐
            │ │ M9: Repair Engine               │
            │ │ Diagnostic & Strategy Escalation│
            │ └────────────────┬────────────────┘
            │                  │
            ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Telemetry & Logger (SQLite + JSONL + Supabase)              │
└──────────────────────────────┬──────────────────────────────┘
                               │ WebSocket (/ws/agent/{run_id})
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ React 19 Frontend / Desktop UI                              │
│ Home • Live Viewport • Dashboard • Run Inspector • Settings │
└─────────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```
Auto/
├── .env.example                     # Environment template (NVIDIA, Gemini, Search, Browser)
├── Launch_App.bat                   # 1-Click launcher for Streamlit Dashboard
├── start_app.bat                    # 1-Click launcher for FastAPI + React UI (Windows cmd)
├── start_app.ps1                    # 1-Click launcher for FastAPI + React UI (PowerShell)
├── render.yaml                      # Render.com Blueprint configuration for FastAPI backend
├── vercel.json                      # Vercel configuration for static React frontend
├── package.json                     # Monorepo root scripts for frontend build
│
├── backend/                         # Core Python Agent Framework & FastAPI Server
│   ├── server.py                    # FastAPI server (REST endpoints, WebSockets, session lifecycle)
│   ├── desktop_entry.py             # Packaging entry point for desktop Electron backend
│   ├── requirements.txt             # Python dependencies (Playwright, FastAPI, LLM SDKs, etc.)
│   ├── requirements-desktop.txt     # PyInstaller dependencies for desktop builds
│   ├── start.sh                     # Cloud startup script for Render / Linux containers
│   │
│   ├── src/agent_framework/         # Micro-pipeline modules
│   │   ├── config.py                # Central configuration & environment loader
│   │   ├── models.py                # Pydantic schemas (ActionObject, PageState, GoalObject)
│   │   ├── llm_client.py            # Unified LLM interface (NVIDIA, Gemini, OpenAI, Claude)
│   │   ├── model_router.py          # Intelligent Model Router (NO_LLM, FAST, REASONING)
│   │   │
│   │   ├── modules/                 # Pipeline stages
│   │   │   ├── unified_planner.py   # Single-call plan-then-execute generator
│   │   │   ├── intent_parser.py     # NL to GoalObject parser
│   │   │   ├── task_decomposer.py   # GoalObject to SubTasks decomposer
│   │   │   ├── strategy_selector.py # Strategy selector & escalation manager
│   │   │   ├── prompt_generator.py  # Stage-specific prompt synthesizer
│   │   │   ├── browser_executor.py  # Playwright browser manager & action dispatcher
│   │   │   ├── page_observer.py     # DOM tree pruner & screenshot capturer
│   │   │   ├── action_selector.py   # Next ActionObject selector
│   │   │   ├── verifier.py          # Multi-check heuristic & semantic verifier
│   │   │   ├── repair_engine.py     # Prompt amendment & self-healing generator
│   │   │   ├── state_manager.py     # Execution state & step tracker
│   │   │   ├── metrics.py           # Per-task execution metrics collector
│   │   │   ├── logger.py            # SQLite, JSONL, and Supabase telemetry logger
│   │   │   └── evaluator.py         # Statistical analysis & TSR calculator
│   │   │
│   │   ├── strategies/              # Swappable prompting strategies
│   │   │   ├── static.py            # Fixed baseline prompt
│   │   │   ├── dynamic.py           # Adaptive Observe-Think-Act
│   │   │   ├── self_reflective.py   # Chain-of-thought DOM delta reasoning
│   │   │   └── failure_recovery.py  # Self-healing diagnostic repairs
│   │   │
│   │   └── utils/                   # Shared utilities
│   │       ├── dom_pruner.py        # Accessibility tree pruning algorithm
│   │       ├── json_extractor.py    # Resilient JSON & markdown code-block parser
│   │       ├── search_client.py     # Free DuckDuckGo / SerpAPI / Google CSE / Bing client
│   │       └── token_counter.py     # Tiktoken & provider token estimator
│   │
│   ├── tests/                       # 97 Automated Pytest test suites
│   └── ui/                          # Legacy/Alternative Streamlit Dashboard
│       └── app.py                   # Streamlit multi-view interface
│
├── frontend/                        # Modern React 19 Frontend
│   ├── src/
│   │   ├── views/
│   │   │   ├── HomeView.tsx         # Goal input, strategy selection, plan pre-generation
│   │   │   ├── AgentView.tsx        # Live screenshot viewport, log stream, extracted results
│   │   │   ├── DashboardView.tsx    # Strategy comparison charts & performance metrics
│   │   │   ├── InspectorView.tsx    # Step-by-step run replay, prompt viewer, diagnostics
│   │   │   └── SettingsView.tsx     # In-app API key manager & provider config
│   │   ├── components/ui/           # Modular UI components (buttons, cards, badges)
│   │   ├── lib/                     # API client, WebSocket manager, theme provider
│   │   ├── App.tsx                  # Root layout & view navigation
│   │   └── index.css                # Tailwind CSS v4 styling & theme tokens
│   ├── package.json                 # Frontend dependencies (React 19, Vite, Lucide, Recharts)
│   └── vite.config.ts               # Vite configuration with API proxy
│
├── desktop/                         # Electron Windows Desktop Wrapper
│   ├── main.cjs                     # Electron main process & backend supervisor
│   └── package.json                 # Desktop packaging scripts & electron-builder config
│
├── scripts/
│   └── build-desktop.ps1            # Automated Windows installer build script
│
├── data/                            # Local SQLite database & screenshot storage
└── logs/runs/                       # JSONL telemetry traces & step logs
```

---

## 🚀 Installation & Setup

### 1. Prerequisites
- **Python**: 3.10 or higher
- **Node.js**: 18.0 or higher with `npm`
- **Browser**: Microsoft Edge or Google Chrome installed locally, or Playwright bundled Chromium.

### 2. Clone & Environment Setup

```bash
git clone https://github.com/your-username/Auto.git
cd Auto

# Create and activate Python virtual environment
python -m venv .venv
.\.venv\Scripts\activate   # Linux/macOS: source .venv/bin/activate

# Install backend dependencies
pip install -r backend/requirements.txt

# (Optional) Install Playwright Chromium if using bundled browser
python -m playwright install chromium

# Install frontend dependencies
cd frontend
npm install
cd ..
```

### 3. Configure API Keys

Copy the sample environment configuration:

```bash
cp .env.example .env
```

Open `.env` and configure your credentials. The framework is optimized for **NVIDIA AI Cloud** by default:

```env
# ── LLM Provider (NVIDIA AI Foundations / NIM) ──────────────────────────
LLM_PROVIDER=nvidia
NVIDIA_API_KEY=nvapi-your-key-here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1

# Dual-Tier Models:
FAST_MODEL=meta/llama-3.2-11b-vision-instruct
REASONING_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning

# (Optional) Distinct keys for fast vs reasoning tiers:
# NVIDIA_FAST_API_KEY=nvapi-...
# NVIDIA_REASONING_API_KEY=nvapi-...

# ── Alternative Fallback Providers ─────────────────────────────────────
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# ── Search API (Optional) ──────────────────────────────────────────────
# If none set, the agent uses FREE DuckDuckGo search automatically (no key needed)
SERPAPI_KEY=
GOOGLE_CSE_KEY=
GOOGLE_CSE_CX=
BING_SEARCH_KEY=

# ── Browser Mode ───────────────────────────────────────────────────────
# BROWSER_MODE: visible (default, opens window) | headless (background) | cdp
BROWSER_MODE=visible
BROWSER_TYPE=msedge
HEADLESS=false
KEEP_BROWSER_OPEN=false

# ── Storage & Origins ──────────────────────────────────────────────────
STORAGE_BACKEND=dual
DB_PATH=data/experiments.db
LOG_DIR=logs/runs
CORS_ORIGINS=*
```

> 💡 **Tip:** You do not need to configure API keys manually in `.env` if you prefer the UI! You can launch the app and configure your keys visually in the **Settings View**.

---

## 💻 Running the Application

### Option A: 1-Click Launchers (Recommended for Windows)

- **FastAPI Backend + React UI**: Double-click `start_app.bat` or run:
  ```powershell
  .\start_app.ps1
  ```
  *This automatically frees port 8000 if occupied, boots the FastAPI backend on `http://127.0.0.1:8000`, starts the React Vite dev server on `http://localhost:5173`, and opens your default browser.*

- **Streamlit Exploration Dashboard**: Double-click `Launch_App.bat` or run:
  ```bash
  .\.venv\Scripts\python -m streamlit run backend/ui/app.py
  ```

---

### Option B: Manual CLI Launch

Run the services in two separate terminals:

```bash
# Terminal 1: Backend
cd backend
python -m uvicorn server:app --port 8000 --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

Visit **`http://localhost:5173`** in your browser.

---

### Option C: Windows Desktop Application (Installer)

To build a standalone Windows `.exe` installer (packaging the React UI, Electron supervisor, bundled Chromium, and FastAPI backend):

```powershell
.\scripts\build-desktop.ps1
```

The resulting installer will be saved to `desktop\release`. On installation, user data, local SQLite storage, screenshots, and logs are persisted under `%APPDATA%\autonomous-browser-agent-desktop`.

---

## 🖥️ User Workflow & Application Views

The React application features 5 primary views accessible via the navigation header:

| View | Purpose & Functionality |
| :--- | :--- |
| **🏠 Home View** | **Mission Control**: Enter your natural-language goal, choose your execution strategy (Plan-then-Execute, Dynamic, Static, Self-Reflective, Failure-Recovery), select the browser visibility mode, and click **Generate Plan** to pre-visualize action steps before launching execution. |
| **🤖 Agent View** | **Live Execution**: Displays real-time browser screenshot streaming, interactive viewport, live step logs, subtask progression bar, extracted data tables with direct purchase/view links, related topic video suggestions, and instant pause/stop buttons. |
| **📊 Dashboard View** | **Comparative Analytics**: Visualizes Task Success Rate (TSR), Average Retries, Task Completion Time (s), Token Consumption, and Model Tier distribution across strategies using interactive Radar, Bar, and Area charts. |
| **🔍 Run Inspector** | **Deep Inspection & Audit**: Browse historical runs, inspect exact raw prompts (system & user prompts), view step-by-step action parameters, inspect verification results, examine self-healing repair amendments, and export traces in JSON/JSONL format. |
| **⚙️ Settings View** | **In-App Key Management**: View and modify API keys for NVIDIA, Gemini, OpenAI, Claude, SerpAPI, Google CSE, and Bing Search with live status verification, obscured fields, and direct saving without backend restarts. |

---

## 🔬 Prompting Strategies Explained

| Strategy | Badge | How it Works | Best Used For |
| :--- | :---: | :--- | :--- |
| **`plan_then_execute`** | ⚡ Ultra Fast | Generates a complete sequence of concrete browser actions with designated checkpoints in a single LLM call. Actions execute deterministically in batch with zero per-step LLM latency. Automatically falls back to recovery if a checkpoint fails. | High-speed tasks, e-commerce searches, multi-item cart additions, well-defined workflows. |
| **`dynamic`** | 🟢 Adaptive | Classical Observe-Think-Act loop. Prunes the accessibility tree and feeds current DOM state back to the LLM after every action to determine the next step. | Sites with complex dynamic state, unknown interactive steps, or unpredictable popups. |
| **`static`** | 🔵 Baseline | Uses pre-determined, fixed prompt templates without runtime dynamic DOM state or repair context. | Experimental baseline for empirical comparison against adaptive strategies. |
| **`self_reflective`** | 🟡 CoT | Implements a Chain-of-Thought (CoT) reflection step evaluating DOM delta changes, verifying if the last action achieved its sub-goal, and assessing confidence before committing the next action. | High-precision workflows, multi-form submissions, and error-sensitive navigation. |
| **`failure_recovery`** | 🔴 Self-Healing | Features aggressive runtime failure diagnostics. When an action or verification fails, the **Repair Engine** analyzes DOM states, repairs faulty selectors, finds alternative paths, or reframes goals with strategy escalation. | Resilient recovery on unstable websites, broken selectors, or dynamic anti-scraping layouts. |

---

## ☁️ Cloud Deployment Architecture

The repository is pre-configured for zero-friction split cloud deployment:

```
                  User
                   │
                   ▼
         ┌──────────────────┐
         │  Vercel Frontend │   React + Vite Static Build (vercel.json / frontend/)
         └─────────┬────────┘
                   │ REST + WebSocket (VITE_API_BASE_URL)
                   ▼
         ┌──────────────────┐
         │  Python Backend  │   FastAPI + Playwright (render.yaml / backend/)
         │  Render / Railwy │
         └─────────┬────────┘
                   │
           ┌───────┴────────┐
           ▼                ▼
     Browser Agent       AI/LLM API
     (headless Chromium) (NVIDIA / Gemini / OpenAI)
```

1. **Frontend (Vercel)**:
   - Connect the repo to Vercel. `vercel.json` automatically selects the Vite framework and builds from `frontend/`.
   - Set the environment variable `VITE_API_BASE_URL` to your live backend URL (e.g., `https://browser-agent-api.onrender.com`).
2. **Backend (Render / Railway / Cloud Run)**:
   - Create a Web Service using the included `render.yaml` blueprint with Root Directory set to `backend`.
   - The startup script `backend/start.sh` automatically installs headless Chromium dependencies (`playwright install chromium --with-deps`) and boots Uvicorn.
   - Configure `NVIDIA_API_KEY` and set `CORS_ORIGINS=https://<your-project>.vercel.app`.

---

## 🧪 Testing & Quality Assurance

The framework includes a comprehensive test suite covering all modules, browser configurations, model routers, and session lifecycles:

```bash
# Run backend test suite
cd backend
pytest -v
```

**Test Results:**
```
============================== 97 passed in 19.87s ===============================
```

**Frontend Production Build Verification:**
```bash
cd frontend
npm run build
```
*Compiles TypeScript without errors and produces optimized production bundles (`dist/index.html`, `dist/assets/`).*

---

## 📊 Scientific Experimentation & Replication

To replicate experimental evaluation comparing the strategies:

1. Configure your default baseline strategy in `.env`:
   ```env
   EXPERIMENT_STRATEGY=static
   ```
2. Execute benchmark tasks via the React UI or programmatic scripts.
3. Repeat identical benchmark tasks with:
   - `EXPERIMENT_STRATEGY=dynamic`
   - `EXPERIMENT_STRATEGY=self_reflective`
   - `EXPERIMENT_STRATEGY=failure_recovery`
   - `EXPERIMENT_STRATEGY=plan_then_execute`
4. Open the **📊 Dashboard View** in the UI to inspect automated comparative metrics across Task Success Rate (TSR), Average Retries, Completion Time, and Token Efficiency.
5. Export execution logs from `data/experiments.db` or `logs/runs/*.jsonl` for offline statistical analysis.

---

## 📜 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

