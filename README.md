# Adaptive Prompt Engineering Framework for Reliable Autonomous Web Agents

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Playwright](https://img.shields.io/badge/tested%20with-Playwright-45ba4b.svg)](https://playwright.dev/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Final Year AIML Research Project**  
> *"Can dynamically generated and self-evaluated prompts improve the reliability of autonomous browser agents, compared to static prompts?"*

---

## 📌 Overview

Traditional browser automation agents rely on fixed, static prompts that easily break when a website layout changes or an unexpected popup appears. This framework implements a **modular micro-pipeline** that dynamically generates, evaluates, and repairs prompts at runtime.

### Key Capabilities
- 🔄 **4 Swappable Prompting Strategies** (`static`, `dynamic`, `self_reflective`, `failure_recovery`) for empirical A/B evaluation.
- 🛠️ **Autonomous Prompt Repair Engine** that diagnoses failures and injects targeted corrective amendments.
- 🌐 **Async Browser Automation** powered by Playwright with accessibility tree pruning and stealth user settings.
- 📊 **Telemetry & Comparison Dashboard** with SQLite persistence, per-step JSONL tracing, and interactive Plotly metrics in Streamlit.

---

## 🏗️ Architecture & Module Map

```
User Goal (NL)
  │
  ▼
[M1: Intent Parser]        ── Parse NL goal into structured GoalObject
  │
  ▼
[M2: Task Decomposer]      ── Decompose GoalObject into sequential SubTasks
  │
  ▼
[M3: Strategy Selector]    ── Select strategy (static, dynamic, self_reflective, failure_recovery)
  │
  ├──► Loop per SubTask:
  │      [M4: Prompt Generator]    ── Build stage-specific prompt with context & repairs
  │      [M5: Browser Executor]    ── Playwright async execution (Chromium)
  │      [M6: Page Observer]       ── Prune accessibility tree into compact PageState
  │      [M7: Action Selector]     ── Generate next ActionObject via LLM
  │      [M8: Verifier]            ── Multi-check verification (heuristics + semantic)
  │      └── If Failure:
  │            [M9: Repair Engine] ── Generate RepairAmendment & escalate strategy
  │      [M10: Logger]             ── Async SQLite + JSONL step-by-step telemetry
  ▼
[M11: Evaluator]           ── Compute Task Success Rate, Retries, Time & Token Usage
  │
  ▼
[M12: Streamlit UI]        ── Interactive web interface & experimentation dashboard
```

---

## 🚀 Getting Started

### 1. Installation

Clone repository and install dependencies:

```bash
git clone https://github.com/your-username/Auto.git
cd Auto

# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate  # On Linux/macOS: source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and provide your API keys:

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Choose ONE LLM Provider
GEMINI_API_KEY=your_gemini_api_key_here
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash

# Optional: Search API
SERPAPI_KEY=your_serpapi_key_here

# Browser Settings
# Type: chromium | msedge | chrome | firefox | webkit
BROWSER_TYPE=chromium
HEADLESS=false

# Connection Mode: playwright (dedicated clean browser) | cdp (existing Chrome via remote debugging)
BROWSER_CONNECTION_MODE=playwright
CDP_ENDPOINT=http://127.0.0.1:9222
```

### Browser Execution Modes
- **Dedicated Playwright Mode (Default):** Launches a separate, clean browser instance with resilient fallback cascading (Requested Browser -> Microsoft Edge -> Google Chrome -> Bundled Chromium).
- **Chrome DevTools Protocol (CDP) Mode:** Connects to an existing Chrome instance started with `--remote-debugging-port=9222`:
  ```bash
  # Start Chrome with remote debugging enabled
  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome_dev_profile"
  ```

---

## 💻 Running the Application

### Launch the Streamlit Dashboard (Recommended)

```bash
streamlit run ui/app.py
```

The app provides 4 views:
1. **🏠 Home** — Submit natural-language goals, configure strategies, review planned subtasks, and inspect past runs.
2. **🤖 Agent View** — Watch the agent execute actions live with real-time DOM states, verifications, and screenshots.
3. **📊 Dashboard** — Compare prompting strategies across Task Success Rate (TSR), Average Retries, Completion Time, and Token Usage.
4. **🔍 Run Inspector** — Drill down into any historical run to inspect exact prompts, repair amendments, action logs, and per-step duration.

---

## 🧪 Running the Test Suite

Run all unit tests across all modules (100% mocked, no API keys needed):

```bash
pytest
```

Output:
```
============================= 28 passed in 0.19s ==============================
```

---

## 🔬 Experiment Design & Replication

To replicate experimental results comparing the 4 strategies:

1. Open `.env` and set `EXPERIMENT_STRATEGY=static`
2. Run benchmark tasks via the Streamlit UI or programmatic script.
3. Repeat with `EXPERIMENT_STRATEGY=dynamic`, `self_reflective`, and `failure_recovery`.
4. Open the **📊 Dashboard** page in Streamlit to view automated Plotly comparison charts and statistical summaries.

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.
