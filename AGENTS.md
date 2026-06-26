# AGENTS.md

This file provides instructions for AI coding agents working on the ember project.

## Overview

ember is a lightweight headless browser for AI agents. It gives agents the ability to browse the web, search for information, and interact with pages.

- The Python package lives in `ember/`
- Tests live in `tests/`
- The CLI entry point is `ember.cli:app`

## Build and test

```bash
cd /home/mimi/ember
pip install -e ".[dev]"    # Install in development mode with test deps
pytest tests/              # Run the test suite
```

All tests must pass before committing. Also read CONTRIBUTING.md for contribution guidelines.

## Code conventions

- Use type hints on all function signatures
- Use `from __future__ import annotations` at the top of every module
- Docstrings should explain why, not what (the code says what)
- Keep functions small and focused
- Lazy load heavy dependencies (Lightpanda, Playwright, etc.)
- All errors should be user-friendly messages, not raw exceptions

## Architecture

```
ember/         # Installed package
├── scrape.py  # URL to markdown (trafilatura first, Lightpanda fallback)
├── crawl.py   # BFS website crawler with sitemap support
├── search.py  # Web search via DuckDuckGo (free, no API key)
├── map.py     # URL discovery via sitemaps + links
├── interact.py # Browser interaction via Lightpanda CDP
├── agent.py   # LLM-powered structured extraction
├── cli.py     # Typer CLI (9 commands)
├── api.py     # FastAPI server
├── mcp.py     # MCP server for agent frameworks
├── _browser.py # Lightpanda auto-download and management
└── types.py   # Shared data models
tests/         # Pytest test suite
```

## Key design decisions

- Lightpanda instead of Chromium (20 MB vs 641 MB)
- trafilatura for 90% of pages (zero memory overhead)
- Browser is lazy loaded, only when needed
- Browser auto-downloads on first use
- No Docker, no separate services, no API keys for basic features
- DuckDuckGo for built-in search (free, no key required)

## Port convention

The API server defaults to port 51251. This can be changed with `ember serve --port <number>` or the EMBER_PORT environment variable.
