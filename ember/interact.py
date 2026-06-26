"""Browser interaction via Lightpanda CDP. Auto-installs on first use."""

from __future__ import annotations

import subprocess
import time
from typing import Optional

from ember._browser import ensure as _ensure_browser
from ember.types import InteractResult

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222


def interact(
    url: str,
    prompt: str = "",
    *,
    timeout: int = 30,
) -> InteractResult:
    """Open a URL and perform browser actions.

    Lightpanda downloads automatically on first call.
    With a prompt, uses natural language to drive the browser.
    Without a prompt, returns the page content as markdown.

    Args:
        url: Page to open.
        prompt: Natural language action (e.g. "click the login button").
        timeout: Max seconds for the operation.
    """
    if not prompt:
        from ember.scrape import scrape_markdown
        content = scrape_markdown(url, use_browser=True)
        return InteractResult(url=url, content=content)

    try:
        lp = _ensure_browser()
    except RuntimeError as e:
        return InteractResult(url=url, content="", success=False, error=str(e))

    try:
        proc = subprocess.run(
            [lp, "agent", "--task", prompt, "--no-llm"],
            capture_output=True, text=True, timeout=timeout,
        )
        content = (proc.stdout or proc.stderr or "").strip()
        return InteractResult(url=url, content=content)
    except subprocess.TimeoutExpired:
        return InteractResult(url=url, content="", success=False, error=f"Timed out ({timeout}s)")
    except Exception as e:
        return InteractResult(url=url, content="", success=False, error=str(e))
