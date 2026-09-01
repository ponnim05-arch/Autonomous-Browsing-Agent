"""
utils/token_counter.py — Token Counting Utility
================================================
Counts tokens in a text string for supported models.

Uses tiktoken for OpenAI-compatible models.
Falls back to character-based estimate for Gemini / Anthropic.
Rule of thumb: ~4 chars per token for English text.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4  # conservative estimate

# tiktoken encoding cache
_ENC_CACHE: dict[str, object] = {}


def count_tokens(text: str, model: str = "gemini-2.0-flash") -> int:
    """
    Estimate the number of tokens in a text string.

    Args:
        text: Input text.
        model: Model name (used to select the encoding).

    Returns:
        Estimated token count (int).
    """
    model_lower = model.lower()

    # Use tiktoken for OpenAI models
    if any(prefix in model_lower for prefix in ("gpt-", "text-embedding", "o1", "o3")):
        return _tiktoken_count(text, model)

    # Character-estimate for Gemini / Claude / other
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _tiktoken_count(text: str, model: str) -> int:
    try:
        import tiktoken  # optional dep

        if model not in _ENC_CACHE:
            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")
            _ENC_CACHE[model] = enc

        enc = _ENC_CACHE[model]
        return len(enc.encode(text))
    except ImportError:
        logger.debug("tiktoken not installed; using char estimate.")
        return max(1, len(text) // _CHARS_PER_TOKEN)
    except Exception as e:
        logger.warning(f"tiktoken error: {e}; using char estimate.")
        return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_cost_usd(tokens: int, model: str = "gemini-2.0-flash") -> float:
    """
    Rough cost estimate in USD based on public pricing (as of mid-2025).
    Update these rates as pricing changes.
    """
    # Rates in USD per 1M tokens (input+output blended)
    rates = {
        "gemini-2.0-flash": 0.15,
        "gemini-1.5-pro": 3.50,
        "gpt-4o": 7.50,
        "gpt-4o-mini": 0.30,
        "claude-3-5-sonnet": 9.00,
        "claude-3-haiku": 0.50,
    }
    for key, rate in rates.items():
        if key in model.lower():
            return round(tokens / 1_000_000 * rate, 6)
    return round(tokens / 1_000_000 * 1.0, 6)  # $1/M fallback
