from __future__ import annotations

__version__ = "0.1.3"

# Lazy imports keep package startup light.

__all__ = [
    "__version__",
    "scrape_url",
    "scrape_url_async",
    "scrape_markdown",
    "scrape_markdown_async",
    "map_url",
]

_LAZY: dict[str, str] = {
    "scrape_url":            "emb.scrape",
    "scrape_url_async":      "emb.scrape",
    "scrape_markdown":       "emb.scrape",
    "scrape_markdown_async": "emb.scrape",
    "map_url":               "emb.map",
}


def __getattr__(name: str):
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module 'emb' has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, name)
