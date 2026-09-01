"""
config.py — Central configuration for the agent framework.

All settings are read from environment variables (via .env) with sensible
defaults. Instantiate AgentConfig() anywhere in the codebase; it is a
frozen dataclass so it stays immutable after construction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _reload_env() -> None:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=True)
    else:
        load_dotenv(override=True)


_reload_env()


def _env_list(key: str, default: str) -> list[str]:
    """Parse a comma-separated env var into a list."""
    _reload_env()
    raw = os.getenv(key, default)
    return [v.strip() for v in raw.split(",") if v.strip()]


@dataclass
class AgentConfig:
    # ── LLM ────────────────────────────────────────────────────────
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "nvidia")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "meta/llama-3.2-11b-vision-instruct")
    )
    llm_temperature: float = 0.2
    llm_thinking: bool = field(
        default_factory=lambda: os.getenv("LLM_THINKING", "false").lower() == "true"
    )
    llm_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("LLM_REASONING_EFFORT", "low")
    )
    max_tokens_per_call: int = 4096
    token_budget_per_task: int = 100_000

    # ── Model Routing ──────────────────────────────────────────────
    fast_model: str = field(
        default_factory=lambda: os.getenv("FAST_MODEL", "meta/llama-3.2-11b-vision-instruct")
    )
    reasoning_model: str = field(
        default_factory=lambda: os.getenv("REASONING_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    )

    fast_model_max_tokens: int = 512
    reasoning_model_max_tokens: int = 4096

    # ── Performance ────────────────────────────────────────────────
    enable_batch_execution: bool = field(
        default_factory=lambda: os.getenv("ENABLE_BATCH_EXECUTION", "true").lower() == "true"
    )
    screenshots_at_checkpoints_only: bool = field(
        default_factory=lambda: os.getenv("SCREENSHOTS_AT_CHECKPOINTS", "true").lower() == "true"
    )

    # ── Experiment ─────────────────────────────────────────────────
    experiment_strategy: str = field(
        default_factory=lambda: os.getenv("EXPERIMENT_STRATEGY", "dynamic")
    )
    auto_escalate_on_retry: bool = True

    # ── Browser ────────────────────────────────────────────────────
    headless: bool = field(
        default_factory=lambda: os.getenv("HEADLESS", "false").lower() == "true"
    )
    browser_type: str = field(
        default_factory=lambda: os.getenv("BROWSER_TYPE", "chromium")
    )
    browser_connection_mode: str = field(
        default_factory=lambda: os.getenv("BROWSER_CONNECTION_MODE", "playwright").lower()
    )
    cdp_endpoint: str = field(
        default_factory=lambda: os.getenv("CDP_ENDPOINT", "http://127.0.0.1:9222")
    )
    action_timeout_ms: int = 10_000
    page_load_timeout_ms: int = 30_000

    # ── Safety ─────────────────────────────────────────────────────
    # PA mode: allow cart/checkout — only block final payment submission
    block_purchase_urls: list[str] = field(
        default_factory=lambda: _env_list(
            "BLOCK_PURCHASE_URLS", "payment/process,order/confirm,pay/submit,payment/complete"
        )
    )

    # ── Pipeline Limits ────────────────────────────────────────────
    max_retries_per_subtask: int = 3
    max_subtasks_per_task: int = 10
    action_history_window: int = 5       # last N actions included in prompt
    max_interactive_elements: int = 50   # DOM pruning limit (reduced from 200 for token efficiency)

    # ── Storage ────────────────────────────────────────────────────
    storage_backend: str = field(
        default_factory=lambda: os.getenv("STORAGE_BACKEND", "dual")
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("DB_PATH", "data/experiments.db")
    )
    log_dir: str = field(
        default_factory=lambda: os.getenv("LOG_DIR", "logs/runs")
    )
    export_csv_on_complete: bool = True

    # ── API Keys (read-only references) ───────────────────────────
    @property
    def nvidia_api_key(self) -> str | None:
        _reload_env()
        return os.getenv("NVIDIA_API_KEY")

    @property
    def nvidia_base_url(self) -> str:
        _reload_env()
        return os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

    @property
    def gemini_api_key(self) -> str | None:
        _reload_env()
        return os.getenv("GEMINI_API_KEY")

    @property
    def openai_api_key(self) -> str | None:
        _reload_env()
        return os.getenv("OPENAI_API_KEY")

    @property
    def anthropic_api_key(self) -> str | None:
        _reload_env()
        return os.getenv("ANTHROPIC_API_KEY")

    @property
    def supabase_url(self) -> str | None:
        _reload_env()
        return os.getenv("SUPABASE_URL")

    @property
    def supabase_key(self) -> str | None:
        _reload_env()
        return os.getenv("SUPABASE_KEY")

    @property
    def serpapi_key(self) -> str | None:
        _reload_env()
        return os.getenv("SERPAPI_KEY")

    @property
    def google_cse_key(self) -> str | None:
        _reload_env()
        return os.getenv("GOOGLE_CSE_KEY")

    @property
    def google_cse_cx(self) -> str | None:
        _reload_env()
        return os.getenv("GOOGLE_CSE_CX")

    @property
    def bing_search_key(self) -> str | None:
        _reload_env()
        return os.getenv("BING_SEARCH_KEY")


# Singleton instance used throughout the package
default_config = AgentConfig()
