"""
utils/search_client.py — Search API Wrapper
============================================
Unified search interface supporting SerpAPI, Google Custom Search Engine,
and Bing Search API. Auto-selects provider based on which API key is set.

Priority: SerpAPI > Google CSE > Bing > Mock (for testing)
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import AgentConfig, default_config
from ..models import SearchResult

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0  # seconds


class SearchClientError(Exception):
    """Raised when all search providers fail."""


class SearchClient:
    """
    Async search client with automatic provider fallback.

    Usage:
        client = SearchClient(config)
        results = await client.search("laptops under 60000 16GB RAM", num=5)
    """

    def __init__(self, config: AgentConfig = default_config):
        self.config = config

    async def search(self, query: str, num: int = 5) -> list[SearchResult]:
        """
        Run a web search and return top results.

        Args:
            query: Search query string.
            num: Number of results to return.

        Returns:
            List of SearchResult objects.
        """
        # Try providers in priority order
        if self.config.serpapi_key:
            try:
                return await self._serpapi(query, num)
            except Exception as e:
                logger.warning(f"[Search] SerpAPI failed: {e}. Trying next.")

        if self.config.google_cse_key and self.config.google_cse_cx:
            try:
                return await self._google_cse(query, num)
            except Exception as e:
                logger.warning(f"[Search] Google CSE failed: {e}. Trying next.")

        if self.config.bing_search_key:
            try:
                return await self._bing(query, num)
            except Exception as e:
                logger.warning(f"[Search] Bing failed: {e}. Returning mock.")

        logger.warning("[Search] No search API key configured. Returning mock results.")
        return self._mock_results(query, num)

    # ── SerpAPI ───────────────────────────────────────────────────

    async def _serpapi(self, query: str, num: int) -> list[SearchResult]:
        params = {
            "q": query,
            "api_key": self.config.serpapi_key,
            "num": num,
            "engine": "google",
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("organic_results", [])[:num]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            ))
        return results

    # ── Google CSE ────────────────────────────────────────────────

    async def _google_cse(self, query: str, num: int) -> list[SearchResult]:
        params = {
            "q": query,
            "key": self.config.google_cse_key,
            "cx": self.config.google_cse_cx,
            "num": min(num, 10),
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1", params=params
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("items", [])[:num]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            ))
        return results

    # ── Bing ──────────────────────────────────────────────────────

    async def _bing(self, query: str, num: int) -> list[SearchResult]:
        headers = {"Ocp-Apim-Subscription-Key": self.config.bing_search_key}
        params = {"q": query, "count": num, "mkt": "en-IN"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("webPages", {}).get("value", [])[:num]:
            results.append(SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
            ))
        return results

    # ── Mock (no API key) ─────────────────────────────────────────

    @staticmethod
    def _mock_results(query: str, num: int) -> list[SearchResult]:
        """Return placeholder results when no API key is configured."""
        return [
            SearchResult(
                title=f"Mock Result {i + 1} for: {query}",
                url=f"https://example.com/result-{i + 1}",
                snippet=f"This is a mock search result #{i + 1}. Configure a search API key in .env.",
            )
            for i in range(num)
        ]
