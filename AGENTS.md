# AGENTS.md

This file provides instructions for AI coding agents working on the ember project.

## Overview

ember is a lightweight headless browser for AI agents. It gives agents the ability to browse the web, search for information, crawl sites, and interact with pages.

- The Python package lives in `emb/`
- Tests live in `tests/`
- The CLI entry point is `emb.cli:app`

## Build and test

```bash
pip install -e ".[dev]"    # install in development mode with test deps
pytest tests/              # run the full test suite
```

All tests must pass before committing.

## Code conventions

- Use type hints on all function signatures
- Use `from __future__ import annotations` at the top of every module
- Prefer clear code and short `#` comments over docstrings
- Only add a docstring when a public interface truly needs it
- Keep functions small and focused
- Lazy-load heavy dependencies (Lightpanda subprocess, etc.)
- All user-facing errors should be human-readable strings, not raw tracebacks
- Never use raw ANSI escape codes (`\033[36m`) in CLI output — always use Rich markup (`[cyan]`) so Rich can render or strip them correctly depending on the terminal
- Never use Rich `Table` for CLI output — it pads all rows to the widest cell, adding trailing whitespace that looks bad. Use `console.print()` with manual alignment instead

## Comment style

- Keep comments short and simple
- Use `#` comments only
- Comment intent, edge cases, and security decisions
- Do not write long comment blocks, ASCII diagrams, decorative separators, or noisy prose comments

## Product standard

- Write secure code by default. Validate input, keep safe defaults, and avoid risky shortcuts
- Prioritize UX. Make the happy path smooth and make failure paths clear

## Architecture

```
emb/
├── scrape.py           # URL → markdown (trafilatura first, Lightpanda fallback)
├── crawl.py            # BFS website crawler with sitemap support
├── search.py           # Web search via DuckDuckGo (no API key)
├── map.py              # URL discovery via sitemaps + page links
├── interact.py         # Browser interaction via Lightpanda + LLM provider
├── agent.py            # LLM-powered structured extraction
├── cli.py              # Typer CLI + interactive session REPL
├── api.py              # FastAPI REST server
├── mcp.py              # FastMCP server for agent frameworks
├── _browser.py         # Lightpanda auto-download, version pinning, SHA-256 verification
├── _http.py            # Redirect-safe HTTP helpers that revalidate each hop
├── _url_validator.py   # SSRF protection — blocks private/loopback/link-local IPs
└── types.py            # Shared dataclasses (ScrapeResult, SearchResult, etc.)
tests/
├── test_core.py        # Integration tests (scrape, search, crawl, map)
├── test_unit.py        # Unit tests with mocked dependencies
├── test_api.py         # FastAPI endpoint tests via TestClient
└── test_cli.py         # CLI tests via Typer CliRunner
```

### Key helpers in `cli.py`

| Helper | Purpose |
|---|---|
| `_clean_scraped_md(text)` | Strips `\|\|` table artifacts from trafilatura output before panel display |
| `_display_links(links, base_url)` | Groups URLs by first path segment, renders as Rich Tree |
| `_resolve_save(explicit, cmd, ref, ext, session_dir)` | Resolves save path with priority chain |
| `_ses_resolve(flags, cmd, ref, ext, state)` | Session-aware wrapper around `_resolve_save` |
| `_ses_prompt(state)` | Returns Rich markup string for the session prompt |
| `_print_session_home(state)` | Prints the startup quick start and save status |
| `_run_with_steps(fn, steps, interval)` | Rotates progress text while long work runs |
| `_err(msg, hint)` | Prints a human-readable error with optional hint line |

## Key design decisions

- **Lightpanda over Chromium**: 20 MB vs 641 MB. Runs without a display server.
- **trafilatura for tier 1**: handles ~90% of pages with zero browser overhead.
- **Single fetch per page**: `crawl.py` fetches HTML once and reuses it for both content extraction and link discovery.
- **SSRF protection**: `_url_validator.py` blocks RFC 1918, loopback, and link-local ranges before any outbound request in the API layer.
- **Optional REST auth**: `EMBER_API_KEY` enables `X-API-Key` header auth. No auth overhead if the env var is not set.
- **Lazy auto-download**: The Lightpanda binary downloads on first use, verified with SHA-256, then cached. No user action required.
- **Session-first CLI**: `ember` with no arguments launches the interactive REPL (`session()`). One-shot commands still work directly (`ember url ...`). Startup shows a short quick start, and `help` shows the full guide.
- **Persistent save config**: `ember config --save-dir <path>` writes to `~/.config/ember/config.json`. `EMBER_SAVE_DIR` env var overrides it for the current shell. When neither is set, CLI results default to `./ember_results`. All commands use `_resolve_save()` to apply the right path with explicit `-o` taking highest priority.
- **Clean-on-display markdown**: `_clean_scraped_md()` is applied to all scraped content before panel rendering. Trafilatura converts multi-column page layouts to pipe-delimited markdown tables; those scatter visibly in narrow terminals. The cleaner joins cells into readable prose and removes separator rows — the raw `.markdown` field on `ScrapeResult` is never mutated.
- **Tree-grouped URL display**: `_display_links()` groups map results by first path segment and renders them as a Rich `Tree`. A flat dump of 200+ URLs is unusable; grouping makes site structure immediately readable.
- **Windows VT processing**: `cli.py` calls `SetConsoleMode` via `ctypes` at import time on `sys.platform == "win32"`. PowerShell 5.1 does not enable Virtual Terminal Processing for child processes, so ANSI colour codes appear as literal `←[` without this. The call is wrapped in a try/except so it never breaks non-console environments (pipes, CI).

## Port convention

The API server defaults to `127.0.0.1:51251`. Change it with `ember serve --port <n>` or the `EMBER_PORT` environment variable.

## Config file

`~/.config/ember/config.json` — written by `ember config --save-dir <path>`. Currently stores one optional key: `save_dir`. Read at runtime by `_load_config()` in `cli.py`; never imported by library modules. If no config value or env override is set, the CLI falls back to `./ember_results`.

## Environment variables

| Variable | Module | Purpose |
|---|---|---|
| `EMBER_SAVE_DIR` | `cli.py` | Default save directory for all CLI commands. Overrides `config.json`. |
| `EMBER_API_KEY` | `api.py` | Enables `X-API-Key` auth on all REST endpoints. No auth if unset. |
| `EMBER_PORT` | `cli.py` | Default port for `ember serve` (default `51251`). Overridden by `--port` flag. |
| `EMBER_INTERACT_PROVIDER` | `interact.py` | Default LLM provider for `interact` (`openai`, `anthropic`, `gemini`, `mistral`, `ollama`, etc.). |
| `EMBER_LLM_API_KEY` | `agent.py` / `interact.py` | API key for `extract` and the no-browser interact path. |
| `EMBER_LLM_BASE_URL` | `agent.py` / `interact.py` | OpenAI-compatible LLM API base URL (default: OpenAI). |
| `EMBER_LLM_MODEL` | `agent.py` / `interact.py` | Default model for `extract` and the no-browser interact path (default: `gpt-4o-mini`). |
| `EMBER_LIGHTPANDA_PATH` | `_browser.py` | Path to a custom Lightpanda binary. Skips auto-download if set. |
