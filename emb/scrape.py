from __future__ import annotations

import asyncio
import html as _html
import io
import re
import subprocess

import httpx
import pypdf
try:
    import trafilatura
    from trafilatura.settings import use_config
except Exception as exc:
    trafilatura = None
    _TRAFILATURA_IMPORT_ERROR: Exception | None = exc
    _traf_config = None
else:
    _TRAFILATURA_IMPORT_ERROR = None
    _traf_config = use_config()
    _traf_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "15")

from emb._http import safe_get, safe_get_async
from emb._browser import ensure as _ensure_browser
from emb._url_validator import validate_url
from emb.types import ScrapeResult

DEFAULT_TIMEOUT = 30
_MIN_CONTENT_WORDS = 20
_ROOT_FALLBACK_MAX_WORDS = 220
_CARDY_MIN_LINES = 6
_CARDY_MAX_WORDS_PER_LINE = 10

_JS_APP_MARKERS = (
    "__NEXT_DATA__",
    "data-reactroot",
    "window.__NUXT__",
    "window.__INITIAL_STATE__",
    "webpack",
    "astro-island",
    "svelte",
    "hydration",
)


def _word_count(text: str) -> int:
    return len(text.split())


def _fetch_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        text = exc.__class__.__name__
    return f"fetch: {text}"


def _trafilatura_error() -> str | None:
    if _TRAFILATURA_IMPORT_ERROR is None:
        return None
    text = str(_TRAFILATURA_IMPORT_ERROR)
    if "lxml_html_clean" in text or "lxml.html.clean" in text:
        return "Scrape dependencies are incomplete. Install lxml_html_clean or upgrade ember-browser."
    return f"Scrape dependencies are unavailable: {text}"


def _markdown_quality_score(text: str) -> int:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    paragraphs = len([part for part in re.split(r"\n\s*\n", text) if part.strip()])
    headings = len([line for line in lines if line.startswith("#")])
    bullets = len([line for line in lines if re.match(r"^([-*]|\d+\.)\s+", line)])
    links = text.count("](")
    sentences = len(re.findall(r"[.!?](?:\s|$)", text))
    words = _word_count(text)
    short_lines = len([line for line in lines if _word_count(line) <= _CARDY_MAX_WORDS_PER_LINE])

    score = 0
    score += min(words // 40, 6)
    score += min(headings, 3) * 2
    score += min(paragraphs, 4)
    score += 1 if bullets >= 2 else 0
    score += 1 if links >= 2 else 0
    score += min(sentences // 3, 3)
    if lines and len(lines) >= _CARDY_MIN_LINES and short_lines / max(len(lines), 1) >= 0.6 and headings == 0:
        score -= 2
    return score


def _looks_like_card_grid(url: str, text: str) -> bool:
    parsed = httpx.URL(url)
    if parsed.path not in ("", "/"):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < _CARDY_MIN_LINES:
        return False
    if _word_count(text) > _ROOT_FALLBACK_MAX_WORDS:
        return False
    if any(line.startswith("#") for line in lines):
        return False
    short_lines = len([line for line in lines if _word_count(line) <= _CARDY_MAX_WORDS_PER_LINE])
    return short_lines / max(len(lines), 1) >= 0.6


def _looks_js_heavy(html: str) -> bool:
    lower = html.lower()
    marker_hit = any(marker.lower() in lower for marker in _JS_APP_MARKERS)
    script_count = len(re.findall(r"<script\b", html, re.IGNORECASE))
    section_count = len(re.findall(r"<(section|article|main|button)\b", html, re.IGNORECASE))
    return marker_hit or (script_count >= 8 and section_count >= 6)


def _should_try_browser(url: str, result: ScrapeResult, html: str | None = None) -> bool:
    if not result.success:
        return True
    if _word_count(result.markdown) < _MIN_CONTENT_WORDS:
        return True
    if _looks_like_card_grid(url, result.markdown):
        return True
    if html and _looks_js_heavy(html) and _markdown_quality_score(result.markdown) < 8:
        return True
    return False


def _pick_better_result(primary: ScrapeResult, browser: ScrapeResult) -> ScrapeResult:
    if not browser.success:
        return primary
    if not primary.success:
        return browser

    primary_words = _word_count(primary.markdown)
    browser_words = _word_count(browser.markdown)
    primary_score = _markdown_quality_score(primary.markdown)
    browser_score = _markdown_quality_score(browser.markdown)

    if primary_words < _MIN_CONTENT_WORDS and browser_words > primary_words:
        return browser
    if browser_score >= primary_score + 2:
        return browser
    if browser_words >= max(primary_words + 30, int(primary_words * 1.2)):
        return browser
    return primary


# Auto mode tries trafilatura first.
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
    if not _should_try_browser(url, result):
        return result

    try:
        lp = _scrape_lightpanda(url, timeout)
        return _pick_better_result(result, lp)
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


# Run browser fallback in a thread.
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
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await safe_get_async(client, url)
            if resp.status_code != 200:
                status_code = resp.status_code
            else:
                ct = resp.headers.get("content-type", "")
                if "pdf" in ct.lower() or resp.content[:5] == b"%PDF-":
                    pdf_bytes = resp.content
                else:
                    html = resp.text
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=_fetch_error(e))

    if pdf_bytes is not None:
        return _scrape_pdf(url, pdf_bytes)

    if html:
        result = _scrape_html(url, html)
    else:
        result = ScrapeResult(url=url, markdown="", success=False, error=f"HTTP {status_code}")

    if use_browser is False:
        return result

    if _should_try_browser(url, result, html):
        loop = asyncio.get_running_loop()
        lp = await loop.run_in_executor(None, lambda: _scrape_lightpanda(url, timeout))
        return _pick_better_result(result, lp)

    return result


async def scrape_markdown_async(
    url: str,
    *,
    use_browser: bool | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    return (await scrape_url_async(url, use_browser=use_browser, timeout=timeout)).markdown


def _scrape_trafilatura(url: str, timeout: int) -> ScrapeResult:
    dep_error = _trafilatura_error()
    if dep_error:
        return ScrapeResult(url=url, markdown="", success=False, error=dep_error)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = safe_get(client, url)
        if resp.status_code != 200:
            return ScrapeResult(url=url, markdown="", success=False, error=f"HTTP {resp.status_code}")
        ct = resp.headers.get("content-type", "")
        if "pdf" in ct.lower() or resp.content[:5] == b"%PDF-":
            return _scrape_pdf(url, resp.content)
        return _scrape_html(url, resp.text)
    except Exception as e:
        return ScrapeResult(url=url, markdown="", success=False, error=_fetch_error(e))


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
    dep_error = _trafilatura_error()
    if dep_error:
        return ScrapeResult(url=url, markdown="", success=False, error=dep_error)
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
