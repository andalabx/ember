"""Web search via DuckDuckGo. Free. No API key needed."""

from __future__ import annotations

from ddgs import DDGS

from emb.types import SearchResult


def search(
    query: str,
    *,
    limit: int = 5,
    region: str = "wt-wt",
    timeout: int = 15,
) -> list[SearchResult]:
    try:
        with DDGS(timeout=timeout) as ddgs:
            raw = list(ddgs.text(query, region=region, max_results=limit))
    except Exception as e:
        raise RuntimeError(f"Search failed: {e}") from e

    return [
        SearchResult(url=r.get("href", ""), title=r.get("title", ""), description=r.get("body", ""))
        for r in raw
        if r.get("href")
    ]
