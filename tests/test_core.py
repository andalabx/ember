"""Tests for ember core functionality."""
from ember.scrape import scrape_url, scrape_markdown
from ember.search import search
from ember.types import ScrapeResult, SearchResult


def test_scrape_simple():
    result = scrape_url("https://example.com", timeout=10)
    assert result.success, f"Scrape failed: {result.error}"
    assert len(result.markdown) > 20
    assert result.title and "Example" in result.title


def test_scrape_markdown_shorthand():
    md = scrape_markdown("https://example.com", timeout=10)
    assert len(md) > 20


def test_scrape_no_browser():
    result = scrape_url("https://example.com", use_browser=False, timeout=10)
    assert result.success


def test_search():
    results = search("python programming", limit=2)
    assert len(results) >= 1
    assert results[0].title
    assert results[0].url


def test_search_zero_results():
    results = search("xyznonexistent123456789", limit=1)
    assert isinstance(results, list)


def test_scrape_result_type():
    result = scrape_url("https://example.com", timeout=10)
    assert isinstance(result, ScrapeResult)
    assert isinstance(result.url, str)
    assert isinstance(result.markdown, str)


def test_search_result_type():
    results = search("python", limit=1)
    assert isinstance(results[0], SearchResult)
