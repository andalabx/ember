from __future__ import annotations

import re
from typing import Sequence

from ddgs import DDGS

from emb.types import SearchResult

# General web engines, tried in this order.
# ddgs "auto" runs wikipedia and grokipedia first, and the wikipedia engine builds its host
# from the region ("wt-wt" -> wt.wikipedia.org, which does not exist). They stay opt-in.
DEFAULT_BACKENDS: tuple[str, ...] = ("duckduckgo", "brave", "startpage", "yahoo", "mojeek")

_ERR_MAX_CHARS = 90


def available_backends() -> list[str]:
    # Ask ddgs which text engines it registered; engines change between ddgs versions.
    try:
        from ddgs.engines import ENGINES

        return sorted(ENGINES["text"])
    except Exception:
        return sorted(DEFAULT_BACKENDS)


def _resolve_backends(backend: str | Sequence[str] | None) -> list[str]:
    available = available_backends()
    if backend is None:
        # Skip defaults this ddgs version no longer ships instead of failing on them.
        return [b for b in DEFAULT_BACKENDS if b in available] or ["auto"]

    raw = backend.split(",") if isinstance(backend, str) else list(backend)
    names: list[str] = []
    for item in raw:
        name = item.strip().lower()
        if name and name not in names:
            names.append(name)
    if not names:
        raise ValueError("backend is empty. Pass an engine name such as 'duckduckgo'.")

    # ddgs treats an unknown backend as "auto" without saying so, so reject it here.
    unknown = [n for n in names if n != "auto" and n not in available]
    if unknown:
        raise ValueError(
            f"Unknown search backend {', '.join(map(repr, unknown))}. "
            f"Available: {', '.join(available)}, auto."
        )
    return names


def _short_error(exc: Exception) -> str:
    text = re.sub(r"\s+", " ", str(exc) or exc.__class__.__name__).strip()
    if "no results found" in text.lower():
        return "no results (blocked or rate-limited)"
    if "dns" in text.lower():
        return "DNS lookup failed"
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "timed out"
    if "connecterror" in text.lower() or "error sending request" in text.lower():
        return "connection failed"
    # Square brackets would be read as Rich markup when the CLI prints this.
    text = text.replace("[", "(").replace("]", ")")
    return text if len(text) <= _ERR_MAX_CHARS else text[: _ERR_MAX_CHARS - 1] + "…"


def _search_one(query: str, backend: str, *, limit: int, region: str, timeout: int) -> list[SearchResult]:
    # The wikipedia engine reads the language from the region, so "wt-wt" has no valid host.
    if backend == "wikipedia" and region == "wt-wt":
        region = "us-en"
    with DDGS(timeout=timeout) as ddgs:
        raw = list(ddgs.text(query, region=region, max_results=limit, backend=backend))
    return [
        SearchResult(url=r.get("href", ""), title=r.get("title", ""), description=r.get("body", ""))
        for r in raw
        if r.get("href")
    ]


def search(
    query: str,
    *,
    limit: int = 5,
    region: str = "wt-wt",
    timeout: int = 15,
    backend: str | Sequence[str] | None = None,
) -> list[SearchResult]:
    backends = _resolve_backends(backend)

    # One engine at a time, so a dead engine cannot hide a working one.
    failures: list[str] = []
    for name in backends:
        try:
            results = _search_one(query, name, limit=limit, region=region, timeout=timeout)
        except Exception as e:
            failures.append(f"{name}: {_short_error(e)}")
            continue
        if results:
            return results
        failures.append(f"{name}: no results")

    raise RuntimeError(f"Search failed on all engines - {'; '.join(failures)}")
