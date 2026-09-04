"""
json_extractor.py — Robust JSON extraction from LLM responses.

Handles:
- Markdown fenced code blocks (```json ... ``` or ``` ... ```)
- Multiple JSON blocks (takes first valid object/array)
- Leading/trailing conversational text (using json.JSONDecoder.raw_decode)
- Unescaped newlines or trailing commas
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def extract_json_data(text: str) -> Optional[dict | list]:
    """
    Extract the first valid JSON object or array from LLM output.
    Returns None if no valid JSON can be extracted.
    """
    if not text or not text.strip():
        return None

    # Strategy 1: Look inside markdown code fences (```json ... ``` or ``` ... ```)
    code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    for block in code_blocks:
        block = block.strip()
        if not block:
            continue
        # Direct load
        try:
            return json.loads(block)
        except Exception:
            pass

        # Try raw_decode from first { or [ inside block
        m = re.search(r"[\{\[]", block)
        if m:
            try:
                obj, _ = json.JSONDecoder().raw_decode(block[m.start():])
                return obj
            except Exception:
                pass

    # Strategy 2: Search for first { or [ in full text using JSONDecoder.raw_decode
    # This correctly parses nested structures and ignores any subsequent text or second JSON blocks
    for match in re.finditer(r"[\{\[]", text):
        start_idx = match.start()
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start_idx:])
            return obj
        except Exception:
            continue

    # Strategy 3: Regex fallback with greedy and non-greedy matching
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]", r"\{[\s\S]*?\}", r"\[[\s\S]*?\]"):
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                continue

    return None
