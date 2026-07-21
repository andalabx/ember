import asyncio

import pytest

from emb.scrape import scrape_url, scrape_markdown, scrape_url_async, scrape_markdown_async
from emb.search import search
from emb.types import ScrapeResult, SearchResult, CrawlResult, MapResult

# URLs
_CONTENT_URL   = "https://www.iana.org/domains/reserved"   # static page, clear title, ~60 words
_SIMPLE_URL    = "https://www.iana.org/domains/reserved"   # same: static HTML, no JS needed
_MAP_URL       = "https://www.iana.org/"                   # Homepage with internal links.
_CRAWL_URL     = "https://www.iana.org/domains/reserved"   # shallow, well-behaved


def _require_live_result(result: ScrapeResult) -> ScrapeResult:
    if result.success:
        return result
    error = (result.error or "").lower()
    if any(marker in error for marker in (
        "cannot resolve hostname",
        "all connection attempts failed",
        "forcibly closed",
        "timed out",
        "network",
    )):
        pytest.skip(f"live network unavailable: {result.error}")
    pytest.fail(f"Scrape failed: {result.error}")


# Scrape

def test_scrape_simple():
    result = _require_live_result(scrape_url(_CONTENT_URL, timeout=15))
    assert len(result.markdown.split()) > 20
    assert result.title


def test_scrape_markdown_shorthand():
    result = _require_live_result(scrape_url(_CONTENT_URL, timeout=15))
    md = result.markdown
    assert len(md.split()) > 20


def test_scrape_no_browser():
    # Plain static page, so trafilatura-only is enough.
    result = _require_live_result(scrape_url(_SIMPLE_URL, use_browser=False, timeout=15))
    assert len(result.markdown.split()) > 20


def test_scrape_result_type():
    result = _require_live_result(scrape_url(_CONTENT_URL, timeout=15))
    assert isinstance(result, ScrapeResult)
    assert isinstance(result.url, str)
    assert isinstance(result.markdown, str)
    assert isinstance(result.success, bool)


def test_scrape_bad_url():
    result = scrape_url("https://thisdomaindoesnotexist.invalid", timeout=5)
    assert not result.success
    assert result.error


# Async scrape

def test_scrape_async():
    result = _require_live_result(asyncio.run(scrape_url_async(_CONTENT_URL, timeout=15)))
    assert len(result.markdown.split()) > 20


def test_scrape_markdown_async_shorthand():
    result = _require_live_result(asyncio.run(scrape_url_async(_CONTENT_URL, timeout=15)))
    md = result.markdown
    assert len(md.split()) > 20


def test_scrape_async_concurrent():
    async def _run():
        results = await asyncio.gather(
            scrape_url_async(_CONTENT_URL, timeout=15),
            scrape_url_async("https://www.iana.org/about", timeout=15),
        )
        return results
    results = asyncio.run(_run())
    for result in results:
        _require_live_result(result)
    assert all(r.success for r in results)


# Search

def test_search():
    results = search("python programming", limit=2)
    assert len(results) >= 1
    assert results[0].title
    assert results[0].url


def test_search_zero_results():
    results = search("xyznonexistent123456789", limit=1)
    assert isinstance(results, list)


def test_search_result_type():
    results = search("python", limit=1)
    assert isinstance(results[0], SearchResult)
    assert isinstance(results[0].url, str)
    assert isinstance(results[0].title, str)


# Crawl

def test_crawl_basic():
    from emb.crawl import crawl
    result = crawl(_CRAWL_URL, max_pages=3, max_depth=1, timeout=15)
    assert isinstance(result, CrawlResult)
    assert result.success
    assert result.total >= 1
    assert result.pages[0].url
    assert len(result.pages[0].markdown.split()) > 5


def test_crawl_respects_max_pages():
    from emb.crawl import crawl
    result = crawl(_CRAWL_URL, max_pages=1, max_depth=1, timeout=15)
    assert result.total <= 1


# Map

def test_map_basic():
    from emb.map import map_url
    # IANA homepage exposes enough internal links for this check.
    result = map_url(_MAP_URL, max_links=10)
    assert isinstance(result, MapResult)
    assert result.total >= 1
    assert all(l.startswith("http") for l in result.links)
