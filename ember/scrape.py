"""Scrape URLs to clean markdown. Uses trafilatura first, Lightpanda for JS pages."""

from __future__ import annotations

import re
import subprocess
from typing import Optional

import trafilatura
from trafilatura.settings import use_config

from ember._browser import ensure as _ensure_browser
from ember.types import ScrapeResult

DEFAULT_TIMEOUT = 30
_traf_config = use_config()
_traf_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "15")


def scrape_url(
    url: str,
    *,
    use_browser: Optional[bool] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> ScrapeResult:
    """Extract clean markdown from a URL.

    Args:
        url: The page to scrape.
        use_browser: True forces browser rendering.
                     False skips the browser.
                     None auto-detects (trafilatura first, browser fallback).
        timeout: Request timeout in seconds.
    """
    if use_browser is False:
        return _scrape_trafilatura(url, timeout)

    if use_browser is True:
        return _scrape_lightpanda(url, timeout)

    result = _scrape_trafilatura(url, timeout)
    if result.success and len(result.markdown.strip()) > 50:
        return result

    try:
        lp = _scrape_lightpanda(url, timeout)
        if lp.success and len(lp.markdown.strip()) > len(result.markdown.strip()):
            return lp
    except RuntimeError:
        pass

    return result


def scrape_markdown(
    url: str,
    *,
    use_browser: Optional[bool] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Shorthand: return markdown string only."""
    return scrape_url(url, use_browser=use_browser, timeout=timeout).markdown


def _scrape_trafilatura(url: str, timeout: int) -> ScrapeResult:
    """Fast text extraction. No browser overhead."""
    try:
        html = trafilatura.fetch_url(url)
        if not html:
            return ScrapeResult(url=url, markdown="", success=False, error="Could not fetch URL")
        markdown = trafilatura.extract(
            html,
            config=_traf_config,
            include_formatting=True,
            include_links=True,
            include_images=False,
            output_format="markdown",
        )
        if not markdown:
            return ScrapeResult(url=url, markdown="", success=False, error="Could not extract content")
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()
        return ScrapeResult(url=url, markdown=markdown.strip(), title=title)
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=f"trafilatura: {e}")


def _scrape_lightpanda(url: str, timeout: int) -> ScrapeResult:
    """Browser-based extraction for JS pages. Auto-downloads Lightpanda if needed."""
    try:
        lp = _ensure_browser()
    except RuntimeError as e:
        return ScrapeResult(url=url, markdown="", success=False, error=str(e))

    try:
        r = subprocess.run(
            [lp, "fetch", "--dump", "markdown", "--obey-robots",
             "--wait-until", "networkidle", "--terminate-ms", str(timeout * 1000), url],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        if r.returncode != 0:
            return ScrapeResult(url=url, markdown="", success=False,
                                error=f"Lightpanda exit {r.returncode}: {r.stderr[:200]}")
        output = r.stdout.strip()
        if not output:
            return ScrapeResult(url=url, markdown="", success=False, error="Lightpanda returned empty")
        return ScrapeResult(url=url, markdown=output)
    except subprocess.TimeoutExpired:
        return ScrapeResult(url=url, markdown="", success=False, error=f"Lightpanda timed out ({timeout}s)")
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=f"Lightpanda: {e}")
