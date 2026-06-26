"""Web search via DuckDuckGo. Free. No API key needed."""

from __future__ import annotations

from ddgs import DDGS

from ember.types import SearchResult


def search(
    query: str,
    *,
    limit: int = 5,
    region: str = "wt-wt",
    timeout: int = 15,
) -> list[SearchResult]:
    """Search the web.

    Uses DuckDuckGo. No API key, no account needed.

    Args:
        query: Search string.
        limit: Max results (default 5).
        region: Region code (default 'wt-wt' is worldwide).
        timeout: Max seconds to wait for results.
    """
    try:
        with DDGS(timeout=timeout) as ddgs:
            raw = list(ddgs.text(query, region=region, max_results=limit))
    except Exception as e:
        raise RuntimeError(f"Search failed: {e}") from e

    return [
        SearchResult(url=r.get("href", ""), title=r.get("title", ""), description=r.get("body", ""))
        for r in raw
    ]
