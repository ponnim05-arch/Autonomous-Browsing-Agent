"""
Module 1 — Intent Parser
========================
Parses a raw natural-language user goal into a structured GoalObject.

Pipeline position: User input -> GoalObject -> TaskDecomposer
"""

from __future__ import annotations

import json
import logging
import re

from ..config import AgentConfig, default_config
from ..llm_client import LLMClient
from ..models import GoalObject
from ..utils.json_extractor import extract_json_data

logger = logging.getLogger(__name__)

_FEW_SHOT_EXAMPLES = """
Example 1:
Input: "Find the cheapest laptop under Rs.60,000 with 16GB RAM"
Output:
{
  "task_type": "product_search",
  "domain": "laptops",
  "constraints": {"price_max": 60000, "currency": "INR", "ram_gb": 16},
  "output_format": "comparison_table",
  "success_criteria": "return top 5 ranked results by price with specs"
}

Example 2:
Input: "Compare prices of iPhone 15 Pro across Amazon, Flipkart, and Croma"
Output:
{
  "task_type": "price_comparison",
  "domain": "smartphones",
  "constraints": {"model": "iPhone 15 Pro", "sites": ["amazon", "flipkart", "croma"]},
  "output_format": "comparison_table",
  "success_criteria": "list price from each site side by side"
}

Example 3:
Input: "Find Python documentation for asyncio event loop"
Output:
{
  "task_type": "documentation_search",
  "domain": "python_programming",
  "constraints": {"topic": "asyncio event loop", "source": "docs.python.org"},
  "output_format": "summary_with_link",
  "success_criteria": "return the relevant docs page URL and a brief summary"
}
""".strip()

_SYSTEM_PROMPT = f"""You are a goal parsing agent. Your job is to convert a natural-language user 
goal into a structured JSON object.

Output ONLY valid JSON matching this exact schema:
{{
  "task_type": "<string: product_search | price_comparison | documentation_search | navigation | data_extraction | other>",
  "domain": "<string: topic/category>",
  "constraints": {{<key-value pairs extracted from the goal>}},
  "output_format": "<string: comparison_table | list | summary_with_link | text | raw_data>",
  "success_criteria": "<string: what the final output should contain>"
}}

Here are few-shot examples:
{_FEW_SHOT_EXAMPLES}

Now parse the user's goal.
"""


class IntentParser:
    """Module 1: Converts raw NL goal string → validated GoalObject."""

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self.llm = LLMClient(config)

    async def parse(self, raw_goal: str) -> GoalObject:
        """
        Parse a natural-language goal string into a GoalObject.

        Args:
            raw_goal: e.g. "Find the cheapest laptop under Rs.60,000 with 16GB RAM"

        Returns:
            GoalObject with structured fields.

        Raises:
            ValueError: If LLM output cannot be parsed into a valid GoalObject.
        """
        prompt = f"{_SYSTEM_PROMPT}\n\nUser Goal: {raw_goal}\n\nOutput:"
        logger.info(f"[M1] Parsing goal: {raw_goal[:80]}...")

        response_text, tokens = await self.llm.complete(prompt, temperature=0.1)
        logger.debug(f"[M1] LLM response ({tokens} tokens): {response_text[:200]}")

        goal = self._parse_response(response_text, raw_goal)
        logger.info(f"[M1] Parsed → task_type={goal.task_type}, domain={goal.domain}")
        return goal

    def _parse_response(self, text: str, fallback_goal: str) -> GoalObject:
        """Extract and validate JSON from LLM response."""
        data = extract_json_data(text)
        if not data or not isinstance(data, dict):
            logger.warning("[M1] No valid JSON found in LLM response, using fallback.")
            return self._fallback_goal(fallback_goal)

        try:
            return GoalObject(**data)
        except (TypeError, ValueError) as e:
            logger.warning(f"[M1] JSON parse error: {e}. Using fallback.")
            return self._fallback_goal(fallback_goal)

    @staticmethod
    def _fallback_goal(raw_goal: str) -> GoalObject:
        """Create a minimal GoalObject when parsing fails."""
        return GoalObject(
            task_type="other",
            domain="general",
            constraints={"raw_goal": raw_goal},
            output_format="text",
            success_criteria="Complete the user's stated goal",
        )
