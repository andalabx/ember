"""Unit tests for MCP tool functions in emb.mcp.

Tests run without a real MCP server — each tool is called directly
with all underlying ember functions mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — pre-built return values
# ---------------------------------------------------------------------------

def _ok_scrape(url="https://example.com", markdown="# Page\n\nContent.", title="Page"):
    from emb.types import ScrapeResult
    return ScrapeResult(url=url, markdown=markdown, title=title, success=True)


def _fail_scrape(url="https://example.com", error="timeout"):
    from emb.types import ScrapeResult
    return ScrapeResult(url=url, success=False, error=error)


def _search_results():
    from emb.types import SearchResult
    return [
        SearchResult(url="https://a.com", title="Result A", description="Desc A"),
        SearchResult(url="https://b.com", title="Result B", description="Desc B"),
    ]


def _ok_crawl(url="https://example.com"):
    from emb.types import CrawlResult, CrawlPage
    page = CrawlPage(url=url, markdown="content", title="Home", depth=0)
    return CrawlResult(url=url, pages=[page], total=1, success=True)


def _ok_map(url="https://example.com"):
    from emb.types import MapResult
    return MapResult(url=url, links=["https://example.com/a", "https://example.com/b"], total=2)


def _ok_interact(url="https://example.com"):
    from emb.types import InteractResult
    return InteractResult(url=url, content="Task done.", success=True)


def _fail_interact(url="https://example.com", error="LLM error"):
    from emb.types import InteractResult
    return InteractResult(url=url, success=False, error=error)


# ---------------------------------------------------------------------------
# Access tool functions directly from the module (bypass server machinery)
# ---------------------------------------------------------------------------

def _get_tools() -> dict:
    import importlib
    import sys

    tools: dict = {}

    class _CaptureMCP:
        def tool(self):
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

        def run(self, **kw):
            pass

    # Build a minimal fake fastmcp module and inject it
    fake_fastmcp = MagicMock()
    fake_fastmcp.FastMCP = MagicMock(return_value=_CaptureMCP())

    old = sys.modules.get("fastmcp")
    sys.modules["fastmcp"] = fake_fastmcp

    try:
        # Force a clean reload so the try/except import at the top of mcp.py runs again
        sys.modules.pop("emb.mcp", None)
        mcp_mod = importlib.import_module("emb.mcp")
        mcp_mod.start_mcp()
    finally:
        if old is None:
            sys.modules.pop("fastmcp", None)
        else:
            sys.modules["fastmcp"] = old

    return tools


@pytest.fixture(scope="module")
def tools():
    return _get_tools()


# ===========================================================================
# scrape
# ===========================================================================

class TestMcpScrape:
    def test_returns_markdown(self, tools):
        with patch("emb.scrape.scrape_markdown", return_value="# Heading\nBody."):
            result = tools["scrape"]("https://example.com")
        assert "Heading" in result

    def test_failure_propagates_as_empty_string(self, tools):
        with patch("emb.scrape.scrape_markdown", return_value=""):
            result = tools["scrape"]("https://example.com")
        assert result == ""


# ===========================================================================
# search_web
# ===========================================================================

class TestMcpSearchWeb:
    def test_returns_formatted_results(self, tools):
        with patch("emb.search.search", return_value=_search_results()):
            result = tools["search_web"]("python", limit=2)
        assert "Result A" in result
        assert "https://a.com" in result

    def test_empty_results_returns_no_results(self, tools):
        with patch("emb.search.search", return_value=[]):
            result = tools["search_web"]("nothing")
        assert "No results" in result


# ===========================================================================
# crawl_site
# ===========================================================================

class TestMcpCrawlSite:
    def test_returns_page_count_and_content(self, tools):
        with patch("emb.crawl.crawl", return_value=_ok_crawl()):
            result = tools["crawl_site"]("https://example.com", max_pages=5)
        assert "1" in result   # total pages
        assert "Home" in result

    def test_max_pages_capped_at_500(self, tools):
        with patch("emb.crawl.crawl", return_value=_ok_crawl()) as mock_crawl:
            tools["crawl_site"]("https://example.com", max_pages=9999)
        call_kwargs = mock_crawl.call_args[1]
        assert call_kwargs.get("max_pages") == 500

    def test_max_pages_minimum_1(self, tools):
        with patch("emb.crawl.crawl", return_value=_ok_crawl()) as mock_crawl:
            tools["crawl_site"]("https://example.com", max_pages=0)
        call_kwargs = mock_crawl.call_args[1]
        assert call_kwargs.get("max_pages") >= 1


# ===========================================================================
# map_site
# ===========================================================================

class TestMcpMapSite:
    def test_returns_url_list(self, tools):
        with patch("emb.map.map_url", return_value=_ok_map()):
            result = tools["map_site"]("https://example.com")
        assert "https://example.com/a" in result
        assert "2" in result   # total count


# ===========================================================================
# batch_scrape
# ===========================================================================

class TestMcpBatchScrape:
    def test_empty_input_returns_no_urls(self, tools):
        result = tools["batch_scrape"]("# comment\n\n")
        assert "No URLs" in result

    def test_returns_ok_and_failed_summary(self, tools):
        urls_text = "https://a.com\nhttps://b.com"

        async def _fake(url, **kw):
            return _ok_scrape(url=url) if "a.com" in url else _fail_scrape(url=url)

        with patch("emb.scrape.scrape_url_async", side_effect=_fake):
            result = tools["batch_scrape"](urls_text)

        assert "1 ok" in result
        assert "1 failed" in result

    def test_skips_comment_lines(self, tools):
        urls_text = "# skip\nhttps://a.com"

        async def _fake(url, **kw):
            return _ok_scrape(url=url)

        with patch("emb.scrape.scrape_url_async", side_effect=_fake):
            result = tools["batch_scrape"](urls_text)

        assert "1 ok" in result

    def test_concurrency_capped_at_20(self, tools):
        captured = {}

        async def _fake(url, **kw):
            return _ok_scrape(url=url)

        import asyncio as _asyncio
        original_semaphore = _asyncio.Semaphore

        def _capture_semaphore(n):
            captured["n"] = n
            return original_semaphore(n)

        with patch("emb.scrape.scrape_url_async", side_effect=_fake), \
             patch("asyncio.Semaphore", side_effect=_capture_semaphore):
            tools["batch_scrape"]("https://a.com", concurrency=999)

        assert captured.get("n", 999) <= 20


# ===========================================================================
# interact_page
# ===========================================================================

class TestMcpInteractPage:
    def test_success_returns_content(self, tools):
        with patch("emb.interact.interact", return_value=_ok_interact()):
            result = tools["interact_page"]("https://example.com", prompt="click")
        assert "Task done." in result

    def test_failure_returns_error_string(self, tools):
        with patch("emb.interact.interact", return_value=_fail_interact()):
            result = tools["interact_page"]("https://example.com", prompt="click")
        assert result.startswith("Error:")
        assert "LLM error" in result

    def test_timeout_capped_at_300(self, tools):
        with patch("emb.interact.interact", return_value=_ok_interact()) as mock_interact:
            tools["interact_page"]("https://example.com", timeout=9999)
        call_kwargs = mock_interact.call_args[1]
        assert call_kwargs.get("timeout") <= 300


# ===========================================================================
# extract_data
# ===========================================================================

class TestMcpExtractData:
    def test_success_returns_json(self, tools):
        payload = {"price": "$9.99", "plan": "Pro"}
        with patch("emb.agent.extract", return_value=payload):
            result = tools["extract_data"]("https://example.com")
        data = json.loads(result)
        assert data["price"] == "$9.99"

    def test_error_returns_error_string(self, tools):
        with patch("emb.agent.extract", return_value={"error": "No API key"}):
            result = tools["extract_data"]("https://example.com")
        assert result.startswith("Error:")
        assert "No API key" in result
