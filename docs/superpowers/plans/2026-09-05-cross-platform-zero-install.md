# Cross-Platform Zero-Install & Default NVIDIA API Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the autonomous browser agent application run directly across Windows and Android devices without requiring users to enter an NVIDIA API key or install any Python modules, while enabling installable PWA functionality.

**Architecture:** Embed a verified fallback default NVIDIA API key in `AgentConfig`, update Streamlit UI to bypass manual API key entry, inject PWA manifest and mobile responsive viewport tags for Android/Windows browser-based installation, and provide a 1-click Windows batch launcher for zero-manual-command local execution.

**Tech Stack:** Python 3.10+, Streamlit, Playwright, Web App Manifest (PWA), Windows Batch.

## Global Constraints

- NVIDIA default key must be active out-of-the-box without requiring `.env` or user UI input.
- User custom API keys (via `.env` or UI input) must still override the default key if provided.
- Zero package installations required for end users accessing the hosted or local app.
- Android and Windows browsers can install the app directly to home screen / desktop with standalone display.
- All existing 28 tests must continue to pass without regression.

---

### Task 1: Built-in Default NVIDIA API Key in `config.py`

**Files:**
- Test: `tests/test_default_nvidia_config.py`
- Modify: `src/agent_framework/config.py:149-160`

**Interfaces:**
- Consumes: `os.getenv("NVIDIA_API_KEY")`
- Produces: `AgentConfig.nvidia_api_key -> str` (never returns None when default key is configured)

- [x] **Step 1: Write the failing test**

Create `tests/test_default_nvidia_config.py`:
```python
import os
from unittest.mock import patch
from agent_framework.config import AgentConfig, DEFAULT_NVIDIA_API_KEY

def test_default_nvidia_api_key_fallback():
    with patch.dict(os.environ, {}, clear=True):
        config = AgentConfig()
        assert config.nvidia_api_key == DEFAULT_NVIDIA_API_KEY
        assert config.nvidia_api_key.startswith("nvapi-")

def test_custom_nvidia_api_key_override():
    custom_key = "nvapi-custom-test-key-12345"
    with patch.dict(os.environ, {"NVIDIA_API_KEY": custom_key}, clear=True):
        config = AgentConfig()
        assert config.nvidia_api_key == custom_key
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_default_nvidia_config.py -v`
Expected: FAIL with "ImportError: cannot import name 'DEFAULT_NVIDIA_API_KEY' from 'agent_framework.config'"

- [x] **Step 3: Implement the minimal code to make test pass**

In `src/agent_framework/config.py`, add:
```python
DEFAULT_NVIDIA_API_KEY = "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"
```
And update `nvidia_api_key` property:
```python
    @property
    def nvidia_api_key(self) -> str:
        _reload_env()
        return os.getenv("NVIDIA_API_KEY") or DEFAULT_NVIDIA_API_KEY
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_default_nvidia_config.py -v`
Expected: PASS (2 passed)

- [x] **Step 5: Commit**

```bash
git add src/agent_framework/config.py tests/test_default_nvidia_config.py
git commit -m "feat: embed default built-in NVIDIA API key with override support"
```

---

### Task 2: Update `ui/app.py` for Zero-Friction Default Key & Streamlined UI

**Files:**
- Modify: `ui/app.py:300-320`, `ui/app.py:410-430`

**Interfaces:**
- Consumes: `AgentConfig.nvidia_api_key`
- Produces: Seamless execution without requiring user API key input

- [x] **Step 1: Update API key UI and validation in `ui/app.py`**

In `ui/app.py`:
1. Move the manual API key input into an optional collapsible expander:
```python
    with st.expander("⚙️ Advanced Settings (Custom API Key & Browser Config)", expanded=False):
        api_key_override = st.text_input(
            "Custom API Key (Optional)",
            type="password",
            placeholder="Using built-in NVIDIA AI Cloud key by default",
            help="Leave blank to use the built-in default NVIDIA API key, or enter your own.",
        )
```
2. Display a confirmation badge above the execution buttons:
```python
    st.caption("🟢 **NVIDIA AI Cloud Active** — Free built-in models ready (no setup required).")
```
3. Update key check validation logic around lines 410-425:
```python
    if provider == "nvidia":
        current_key = api_key_override.strip() or run_config.nvidia_api_key or os.getenv("NVIDIA_API_KEY")
```
And ensure execution is never blocked if `provider == "nvidia"` and `current_key` is present (which it always will be from default).

- [x] **Step 2: Run pytest to ensure no agent framework regressions**

Run: `pytest tests/test_default_nvidia_config.py -v`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add ui/app.py
git commit -m "feat(ui): make NVIDIA key optional with built-in default badge"
```

---

### Task 3: Mobile PWA Manifest & Responsive Viewport Meta Injection

**Files:**
- Create: `ui/static/manifest.json`
- Create: `ui/static/icon.svg`
- Modify: `ui/app.py:1-50`

**Interfaces:**
- Consumes: Web standards for PWA (Web App Manifest, Viewport meta)
- Produces: Add to Home screen / Install App capability on Android and Windows

- [x] **Step 1: Create `ui/static/manifest.json`**

```json
{
  "name": "AutoAgent - Autonomous Web Agent",
  "short_name": "AutoAgent",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0e1117",
  "theme_color": "#0e1117",
  "orientation": "portrait-primary",
  "icons": [
    {
      "src": "/app/static/icon.svg",
      "sizes": "192x192 512x512",
      "type": "image/svg+xml",
      "purpose": "any maskable"
    }
  ]
}
```

- [x] **Step 2: Create `ui/static/icon.svg`**

Create modern SVG robot / autonomous agent icon for home screen launcher.

- [x] **Step 3: Inject PWA meta tags and mobile responsive CSS into `ui/app.py`**

In `ui/app.py`, inject the meta tags into `st.markdown(..., unsafe_allow_html=True)`:
```html
<link rel="manifest" href="/app/static/manifest.json">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0e1117">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
```
Add responsive CSS rules for mobile screens (`@media (max-width: 768px)`):
- Full-width action buttons (min-height 48px).
- Full-width responsive image/viewport container for agent screenshots.
- Touch padding on dropdowns and inputs.

- [x] **Step 4: Commit**

```bash
git add ui/static/manifest.json ui/static/icon.svg ui/app.py
git commit -m "feat: add PWA manifest, app icons, and mobile responsive touch styles"
```

---

### Task 4: Standalone Local Windows Launcher (`Launch_App.bat`)

**Files:**
- Create: `Launch_App.bat`

**Interfaces:**
- Consumes: Local `.venv` directory
- Produces: Double-click launch experience on Windows without manual commands

- [x] **Step 1: Create `Launch_App.bat`**

Write script that:
1. Detects `.venv\Scripts\python.exe` or system Python.
2. Sets host to `0.0.0.0` and port to `8501`.
3. Opens default browser to `http://localhost:8501`.
4. Runs Streamlit seamlessly.

- [x] **Step 2: Verify launcher script syntax**

Run: `cmd.exe /c "Launch_App.bat --test"` or verify syntax.

- [x] **Step 3: Commit**

```bash
git add Launch_App.bat
git commit -m "feat: add 1-click Windows launcher for zero-install local use"
```

---

### Task 5: Comprehensive Verification & Regression Testing

**Files:**
- Tests: `tests/`

- [x] **Step 1: Run complete pytest suite**

Run: `pytest -v`
Expected: 29 passed (all 28 original + 1 new test file).

- [x] **Step 2: Commit any cleanups**

```bash
git status
```
