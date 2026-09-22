"""
utils/search_client.py — Search API Wrapper
============================================
Unified search interface supporting SerpAPI, Google Custom Search Engine,
Bing Search API, and a free DuckDuckGo fallback (no API key required).
Auto-selects provider based on which API key is set.

Priority: SerpAPI > Google CSE > Bing > DuckDuckGo (free) > Mock (for testing)
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import AgentConfig, default_config
from ..models import SearchResult

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0  # seconds

_DDG_BACKENDS = ("html", "lite", "bang")


def _clean_ddg_url(url: str) -> str:
    """Unwrap DuckDuckGo redirect links (//duckduckgo.com/l/?uddg=<encoded>) to real URLs."""
    import re as _re
    from urllib.parse import unquote, parse_qs

    url = url.strip()
    if "duckduckgo.com" in url and "uddg=" in url:
        m = _re.search(r"[?&]uddg=([^&]+)", url)
        if m:
            return unquote(m.group(1))
    # Strip leading protocol-relative '//' and decode HTML entities
    if url.startswith("//"):
        url = "https:" + url
    return url.split("&amp;")[0] if "&amp;" in url else url


def _parse_ddg_html(html: str, num: int) -> list[SearchResult]:
    """Extract organic results from DuckDuckGo's plain-HTML result page."""
    import re

    results: list[SearchResult] = []
    # Each result block: <a rel="nofollow" class="result-link" href="...">Title</a>
    # followed by <a class="result-snippet">Snippet</a>
    for m in re.finditer(
        r'<a[^>]*class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'(?:.*?<a[^>]*class="result-snippet"[^>]*>(.*?)</a>)?',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        if len(results) >= num:
            break
        url = _clean_ddg_url(m.group(1))
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", m.group(3) or "").strip()
        if url and title:
            results.append(SearchResult(title=title, url=url, snippet=snippet))
    return results


def _parse_ddg_lite(html: str, num: int) -> list[SearchResult]:
    """Extract organic results from DuckDuckGo's lite HTML page."""
    import re

    results: list[SearchResult] = []
    # Lite layout: <a rel="nofollow" href="...">Title</a> then <td class="result-snippet">
    for m in re.finditer(
        r'<a[^>]*rel="nofollow"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'(?:.*?<td[^>]*class="result-snippet"[^>]*>(.*?)</td>)?',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        if len(results) >= num:
            break
        url = _clean_ddg_url(m.group(1))
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", m.group(3) or "").strip()
        if url and title:
            results.append(SearchResult(title=title, url=url, snippet=snippet))
    return results


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
                logger.warning(f"[Search] Bing failed: {e}. Trying next.")

        # Free fallback: DuckDuckGo HTML endpoints (no API key / extra module needed)
        try:
            return await self._duckduckgo(query, num)
        except Exception as e:
            logger.warning(f"[Search] DuckDuckGo failed: {e}. Returning mock.")

        logger.warning("[Search] No search provider available. Returning mock results.")
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

    # ── DuckDuckGo (free, no API key) ────────────────────────────

    async def _duckduckgo(self, query: str, num: int) -> list[SearchResult]:
        """
        Free web search via DuckDuckGo's HTML endpoints.
        No API key or extra dependency required — only httpx.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        params = {"q": query, "kl": "us-en"}

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=headers) as client:
            last_err: Exception | None = None
            for backend in _DDG_BACKENDS:
                try:
                    resp = await client.get(f"https://html.duckduckgo.com/{backend}/", params=params)
                    resp.raise_for_status()
                    html = resp.text
                    results = _parse_ddg_html(html, num) or _parse_ddg_lite(html, num)
                    if results:
                        logger.info(f"[Search] DuckDuckGo ({backend}) returned {len(results)} results.")
                        return results
                except Exception as e:
                    last_err = e
                    logger.warning(f"[Search] DDG backend '{backend}' failed: {e}. Trying next.")

        raise SearchClientError(f"DuckDuckGo returned no usable results: {last_err}")

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
