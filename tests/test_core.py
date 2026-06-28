"""Integration tests for ember core functionality — hit real URLs."""
import asyncio

from emb.scrape import scrape_url, scrape_markdown, scrape_url_async, scrape_markdown_async
from emb.search import search
from emb.types import ScrapeResult, SearchResult, CrawlResult, MapResult

# ── URLs chosen to match what each test actually exercises ──────────
_CONTENT_URL   = "https://www.iana.org/domains/reserved"   # static page, clear title, ~60 words
_SIMPLE_URL    = "https://www.iana.org/domains/reserved"   # same: static HTML, no JS needed
_MAP_URL       = "https://www.iana.org/"                   # IANA homepage — has internal links
_CRAWL_URL     = "https://www.iana.org/domains/reserved"   # shallow, well-behaved


# ── Scrape ──────────────────────────────────────────────────────────

def test_scrape_simple():
    result = scrape_url(_CONTENT_URL, timeout=15)
    assert result.success, f"Scrape failed: {result.error}"
    assert len(result.markdown.split()) > 20
    assert result.title


def test_scrape_markdown_shorthand():
    md = scrape_markdown(_CONTENT_URL, timeout=15)
    assert len(md.split()) > 20


def test_scrape_no_browser():
    # use_browser=False means trafilatura only — suits a plain static HTML page
    result = scrape_url(_SIMPLE_URL, use_browser=False, timeout=15)
    assert result.success
    assert len(result.markdown.split()) > 20


def test_scrape_result_type():
    result = scrape_url(_CONTENT_URL, timeout=15)
    assert isinstance(result, ScrapeResult)
    assert isinstance(result.url, str)
    assert isinstance(result.markdown, str)
    assert isinstance(result.success, bool)


def test_scrape_bad_url():
    result = scrape_url("https://thisdomaindoesnotexist.invalid", timeout=5)
    assert not result.success
    assert result.error


# ── Async scrape ────────────────────────────────────────────────────

def test_scrape_async():
    result = asyncio.run(scrape_url_async(_CONTENT_URL, timeout=15))
    assert result.success, f"Async scrape failed: {result.error}"
    assert len(result.markdown.split()) > 20


def test_scrape_markdown_async_shorthand():
    md = asyncio.run(scrape_markdown_async(_CONTENT_URL, timeout=15))
    assert len(md.split()) > 20


def test_scrape_async_concurrent():
    async def _run():
        results = await asyncio.gather(
            scrape_url_async(_CONTENT_URL, timeout=15),
            scrape_url_async("https://www.iana.org/about", timeout=15),
        )
        return results
    results = asyncio.run(_run())
    assert all(r.success for r in results)


# ── Search ──────────────────────────────────────────────────────────

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


# ── Crawl ───────────────────────────────────────────────────────────

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


# ── Map ─────────────────────────────────────────────────────────────

def test_map_basic():
    from emb.map import map_url
    # IANA homepage has many internal links in its navigation
    result = map_url(_MAP_URL, max_links=10)
    assert isinstance(result, MapResult)
    assert result.total >= 1
    assert all(l.startswith("http") for l in result.links)
