# Cross-Platform Zero-Install & Default Built-in NVIDIA API Key Design

## Overview
This design makes the Autonomous Browser Agent accessible directly as a normal application across both **Windows** and **Android** devices without requiring users to install any Python packages, modules, or dependencies. It also establishes a built-in default **NVIDIA AI Cloud** API key so end users can execute tasks immediately without entering credentials.

---

## 1. Built-in Default NVIDIA API Key

### Current State
- `AgentConfig` in `src/agent_framework/config.py` loads `NVIDIA_API_KEY` from `.env`.
- In `ui/app.py`, if no key is entered in the UI and no key is found in the environment, task execution is blocked with an error.

### Proposed Architecture
1. **Fallback Key in `config.py`**:
   - Introduce `DEFAULT_NVIDIA_API_KEY = "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"`.
   - Update `nvidia_api_key` property:
     ```python
     @property
     def nvidia_api_key(self) -> str:
         _reload_env()
         return os.getenv("NVIDIA_API_KEY") or DEFAULT_NVIDIA_API_KEY
     ```
   - If a user provides their own key via `.env` or the UI, that key takes priority. Otherwise, the verified default key is always used.
2. **UI Simplification in `ui/app.py`**:
   - Set the default provider to `nvidia` (using Meta Llama 3.2 11B Vision & Nemotron reasoning).
   - Display a status badge: `🟢 NVIDIA AI Cloud (Default Key Active — Ready to Run)`.
   - Move the API key input into an optional collapsible expander (`⚙️ Advanced Settings (Custom API Key)`).
   - Remove validation blockers for the default NVIDIA provider so execution starts immediately when clicking "Plan & Execute".

---

## 2. Cross-Platform Zero-Install Architecture (Hosted + PWA)

Because the application is hosted via Streamlit (Streamlit Community Cloud / Hosted Server), users do not need to install Python, Node.js, Playwright binaries, or virtual environments on their devices.

```
                  ┌──────────────────────────────────────────────┐
                  │           Hosted Streamlit Server            │
                  │   - Streamlit UI + Agent Framework Engine    │
                  │   - Playwright Chromium Headless/Visible     │
                  │   - Default NVIDIA AI Cloud Connection       │
                  └───────────────┬──────────────┬───────────────┘
                                  │              │
                    HTTPS Web/PWA │              │ HTTPS Web/PWA
                                  ▼              ▼
     ┌──────────────────────────────┐          ┌──────────────────────────────┐
     │        Windows Desktop       │          │       Android Smartphone     │
     │ - Any browser (Edge/Chrome)  │          │ - Chrome / Edge on Android   │
     │ - Install as Desktop PWA app │          │ - Tap "Add to Home screen"   │
     │ - Zero packages needed       │          │ - Fullscreen native app view │
     │ - 1-click execution          │          │ - Touch-friendly controls    │
     └──────────────────────────────┘          └──────────────────────────────┘
```

### Android Native App Experience (PWA)
1. **Web App Manifest (`manifest.json`)**:
   - `name`: "AutoAgent - Autonomous Web Agent"
   - `short_name`: "AutoAgent"
   - `display`: "standalone" (removes browser URL bar, providing a native app container)
   - `start_url`: "/"
   - `theme_color`: "#0e1117"
   - `background_color`: "#0e1117"
   - `icons`: Scalable Web app icons (192x192, 512x512)
2. **Meta Header Injection**:
   - Mobile viewport: `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">`.
   - Apple mobile web app capable tags for iOS compatibility as well.
   - PWA installation script / install prompt banner so Android users get an automatic one-tap "Install App" button.

### Mobile & Responsive UI Styling
1. **Adaptive Viewport for Agent Execution**:
   - Viewport containers for the live browser screenshots, DOM elements, and execution logs will automatically scale to 100% of mobile screen width.
   - Action buttons ("🚀 Plan & Execute in Browser Now", "🛑 Stop", "📋 Plan Only") sized and padded for touch targets (min-height 48px).
   - Multi-column controls in desktop view collapse to single-column swipe-friendly stacks on mobile viewports.

---

## 3. Local Windows Standalone Launcher (`Launch_App.bat`)

For users who also want to run or test the application locally on Windows without installing packages:
- `Launch_App.bat`:
  - Automatically identifies the local bundled virtual environment (`.venv\Scripts\python.exe`).
  - Launches Streamlit with `streamlit run ui/app.py --server.address=0.0.0.0 --server.port=8501`.
  - Automatically opens default browser to `http://localhost:8501`.
  - No manual command line, pip, or python commands required by the user.

---

## 4. Verification & Validation Plan
1. **Unit & Integration Tests**:
   - Test that `AgentConfig().nvidia_api_key` returns the fallback key even when `NVIDIA_API_KEY` is wiped from environment variables.
   - Run `pytest` across all 28 existing test suites to ensure zero regressions.
2. **UI & Flow Validation**:
   - Launch Streamlit in headless test mode, verify that the home page renders without errors.
   - Verify that the API key input is optional and default key is loaded.
   - Verify PWA manifest and viewport meta tags are served.
