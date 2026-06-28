"""Scrape URLs to clean markdown. Uses trafilatura first, Lightpanda for JS pages."""

from __future__ import annotations

import asyncio
import html as _html
import io
import re
import subprocess

import httpx
import pypdf
import trafilatura
from trafilatura.settings import use_config

from emb._browser import ensure as _ensure_browser
from emb._url_validator import validate_url
from emb.types import ScrapeResult

DEFAULT_TIMEOUT = 30
_MIN_CONTENT_WORDS = 20
_traf_config = use_config()
_traf_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "15")


# use_browser=None auto-detects: trafilatura first, browser fallback for sparse pages.
def scrape_url(
    url: str,
    *,
    use_browser: bool | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> ScrapeResult:
    try:
        validate_url(url)
    except ValueError as e:
        return ScrapeResult(url=url, success=False, error=str(e))

    if use_browser is False:
        return _scrape_trafilatura(url, timeout)

    if use_browser is True:
        return _scrape_lightpanda(url, timeout)

    result = _scrape_trafilatura(url, timeout)
    if result.success and len(result.markdown.split()) > _MIN_CONTENT_WORDS:
        return result

    try:
        lp = _scrape_lightpanda(url, timeout)
        if lp.success and len(lp.markdown.split()) > len(result.markdown.split()):
            return lp
    except RuntimeError:
        pass

    return result


def scrape_markdown(
    url: str,
    *,
    use_browser: bool | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    return scrape_url(url, use_browser=use_browser, timeout=timeout).markdown


# Browser fallback runs in a thread executor — Lightpanda is a subprocess, not async-native.
async def scrape_url_async(
    url: str,
    *,
    use_browser: bool | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> ScrapeResult:
    try:
        validate_url(url)
    except ValueError as e:
        return ScrapeResult(url=url, success=False, error=str(e))

    if use_browser is True:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: _scrape_lightpanda(url, timeout))

    status_code: int = 0
    html: str | None = None
    pdf_bytes: bytes | None = None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                status_code = resp.status_code
            else:
                ct = resp.headers.get("content-type", "")
                if "pdf" in ct.lower() or resp.content[:5] == b"%PDF-":
                    pdf_bytes = resp.content
                else:
                    html = resp.text
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=f"fetch: {e}")

    if pdf_bytes is not None:
        return _scrape_pdf(url, pdf_bytes)

    if html:
        result = _scrape_html(url, html)
    else:
        result = ScrapeResult(url=url, markdown="", success=False, error=f"HTTP {status_code}")

    if use_browser is False:
        return result

    if not result.success or len(result.markdown.split()) <= _MIN_CONTENT_WORDS:
        loop = asyncio.get_running_loop()
        lp = await loop.run_in_executor(None, lambda: _scrape_lightpanda(url, timeout))
        if lp.success and len(lp.markdown.split()) > len(result.markdown.split()):
            return lp

    return result


async def scrape_markdown_async(
    url: str,
    *,
    use_browser: bool | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    return (await scrape_url_async(url, use_browser=use_browser, timeout=timeout)).markdown


def _scrape_trafilatura(url: str, timeout: int) -> ScrapeResult:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            return ScrapeResult(url=url, markdown="", success=False, error=f"HTTP {resp.status_code}")
        ct = resp.headers.get("content-type", "")
        if "pdf" in ct.lower() or resp.content[:5] == b"%PDF-":
            return _scrape_pdf(url, resp.content)
        return _scrape_html(url, resp.text)
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=f"fetch: {e}")


def _scrape_pdf(url: str, data: bytes) -> ScrapeResult:
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text and text.strip():
                parts.append(text.strip())
        if not parts:
            return ScrapeResult(url=url, markdown="", success=False, error="PDF has no extractable text")
        title = ""
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title)
        return ScrapeResult(url=url, markdown="\n\n".join(parts), title=title)
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=f"PDF extraction: {e}")


def _scrape_html(url: str, html: str) -> ScrapeResult:
    if html.lstrip()[:5] == "%PDF-":
        return ScrapeResult(url=url, markdown="", success=False,
                            error="Received PDF as text — cannot extract")
    try:
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
            title = _html.unescape(m.group(1).strip())
        return ScrapeResult(url=url, markdown=markdown.strip(), title=title)
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=f"trafilatura: {e}")


def _scrape_lightpanda(url: str, timeout: int) -> ScrapeResult:
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
