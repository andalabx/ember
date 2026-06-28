"""Tests for the FastAPI endpoints in emb.api.

Uses fastapi.testclient.TestClient — no real HTTP connections, no subprocesses.
All underlying ember functions are mocked at the call site (emb.api.*).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers — build a fresh TestClient so env-var changes (API key) are visible
# ---------------------------------------------------------------------------

def _make_client(monkeypatch=None, api_key: str = "") -> TestClient:
    import emb.api as api_mod

    if api_key:
        if monkeypatch:
            monkeypatch.setenv("EMBER_API_KEY", api_key)
        # Patch the module-level variable the middleware reads
        with patch.object(api_mod, "_API_KEY", api_key):
            client = TestClient(api_mod.app, raise_server_exceptions=False)
            # Return already-patched client — tests re-patch inside their body
    else:
        if monkeypatch:
            monkeypatch.delenv("EMBER_API_KEY", raising=False)

    # For simplicity, always return a client against the already-imported app.
    # Auth-specific tests patch _API_KEY themselves.
    return TestClient(api_mod.app, raise_server_exceptions=False)


# Convenience: a single shared client with no API key set (most tests don't use auth)
@pytest.fixture()
def client():
    import emb.api as api_mod
    with patch.object(api_mod, "_API_KEY", ""):
        yield TestClient(api_mod.app, raise_server_exceptions=False)


@pytest.fixture()
def authed_client():
    import emb.api as api_mod
    with patch.object(api_mod, "_API_KEY", "secret"):
        yield TestClient(api_mod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers for mocking scrape / crawl results
# ---------------------------------------------------------------------------

def _ok_scrape(url="https://example.com", markdown="# Hello", title="Hello"):
    from emb.types import ScrapeResult
    return ScrapeResult(url=url, markdown=markdown, title=title, success=True)


def _fail_scrape(url="https://example.com", error="network error"):
    from emb.types import ScrapeResult
    return ScrapeResult(url=url, success=False, error=error)


def _ok_crawl(url="https://example.com"):
    from emb.types import CrawlResult, CrawlPage
    page = CrawlPage(url=url, markdown="content", title="Title", depth=0)
    return CrawlResult(url=url, pages=[page], total=1, success=True)


def _ok_interact(url="https://example.com"):
    from emb.types import InteractResult
    return InteractResult(url=url, content="clicked!", success=True)


def _ok_map(url="https://example.com"):
    from emb.types import MapResult
    return MapResult(url=url, links=["https://example.com/page"], total=1)


def _ok_search():
    from emb.types import SearchResult
    return [SearchResult(url="https://a.com", title="A", description="desc")]


# ===========================================================================
# Root and health
# ===========================================================================

class TestRootAndHealth:
    def test_root_returns_endpoint_map(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "ember"
        endpoints = data["endpoints"]
        expected_keys = {
            "POST /scrape",
            "POST /crawl",
            "POST /search",
            "POST /map",
            "POST /interact",
            "POST /extract",
            "POST /agent",
            "GET /health",
        }
        assert expected_keys == set(endpoints.keys())

    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# POST /scrape
# ===========================================================================

class TestApiScrape:
    def test_scrape_success_200(self, client):
        with patch("emb.api.validate_url"), \
             patch("emb.api.scrape_url", return_value=_ok_scrape()):
            resp = client.post("/scrape", json={"url": "https://example.com"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["url"] == "https://example.com"
        assert body["title"] == "Hello"
        assert body["markdown"] == "# Hello"

    def test_scrape_failure_returns_502(self, client):
        with patch("emb.api.validate_url"), \
             patch("emb.api.scrape_url", return_value=_fail_scrape()):
            resp = client.post("/scrape", json={"url": "https://example.com"})

        assert resp.status_code == 502

    def test_scrape_private_ip_returns_400(self, client):
        # 10.0.0.1 is RFC-1918 private — validate_url blocks it
        # We must NOT patch validate_url here; the real check should fire.
        # But socket.gethostbyname may not resolve "10.0.0.1" as a hostname;
        # supply a literal IP URL that validate_url will reject.
        resp = client.post("/scrape", json={"url": "https://10.0.0.1/"})
        assert resp.status_code == 400

    def test_scrape_file_scheme_returns_400(self, client):
        resp = client.post("/scrape", json={"url": "file:///etc/passwd"})
        assert resp.status_code == 400

    def test_scrape_timeout_too_low_returns_422(self, client):
        resp = client.post("/scrape", json={"url": "https://example.com", "timeout": 0})
        assert resp.status_code == 422

    def test_scrape_timeout_too_high_returns_422(self, client):
        resp = client.post("/scrape", json={"url": "https://example.com", "timeout": 121})
        assert resp.status_code == 422


# ===========================================================================
# POST /crawl
# ===========================================================================

class TestApiCrawl:
    def test_crawl_success(self, client):
        with patch("emb.api.do_crawl", return_value=_ok_crawl()), \
             patch("emb.api.validate_url"):
            resp = client.post("/crawl", json={"url": "https://example.com"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["pages"]) == 1
        assert body["pages"][0]["url"] == "https://example.com"

    def test_crawl_failure_returns_502(self, client):
        from emb.types import CrawlResult
        failed = CrawlResult(url="https://example.com", success=False, error="timeout")
        with patch("emb.api.do_crawl", return_value=failed), \
             patch("emb.api.validate_url"):
            resp = client.post("/crawl", json={"url": "https://example.com"})

        assert resp.status_code == 502

    def test_crawl_private_ip_returns_400(self, client):
        resp = client.post("/crawl", json={"url": "https://10.0.0.1/"})
        assert resp.status_code == 400


# ===========================================================================
# POST /search
# ===========================================================================

class TestApiSearch:
    def test_search_success(self, client):
        with patch("emb.api.search", return_value=_ok_search()):
            resp = client.post("/search", json={"query": "python"})  # search has no URL/SSRF

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "python"
        assert len(body["results"]) == 1
        assert body["results"][0]["url"] == "https://a.com"

    def test_search_runtime_error_returns_502(self, client):
        with patch("emb.api.search", side_effect=RuntimeError("DDGS failed")):
            resp = client.post("/search", json={"query": "python"})

        assert resp.status_code == 502


# ===========================================================================
# POST /map
# ===========================================================================

class TestApiMap:
    def test_map_success(self, client):
        with patch("emb.api.validate_url"), \
             patch("emb.api.map_url", return_value=_ok_map()):
            resp = client.post("/map", json={"url": "https://example.com"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert "https://example.com/page" in body["links"]

    def test_map_private_ip_returns_400(self, client):
        resp = client.post("/map", json={"url": "https://10.0.0.1/"})
        assert resp.status_code == 400


# ===========================================================================
# POST /interact
# ===========================================================================

class TestApiInteract:
    def test_interact_success(self, client):
        with patch("emb.api.validate_url"), \
             patch("emb.api.do_interact", return_value=_ok_interact()):
            resp = client.post("/interact",
                               json={"url": "https://example.com", "prompt": "click OK"})

        assert resp.status_code == 200
        assert resp.json()["content"] == "clicked!"

    def test_interact_failure_returns_502(self, client):
        from emb.types import InteractResult
        failed = InteractResult(url="https://example.com", success=False, error="LLM error")
        with patch("emb.api.validate_url"), \
             patch("emb.api.do_interact", return_value=failed):
            resp = client.post("/interact",
                               json={"url": "https://example.com", "prompt": "click"})

        assert resp.status_code == 502

    def test_interact_private_ip_returns_400(self, client):
        resp = client.post("/interact", json={"url": "https://10.0.0.1/", "prompt": "click"})
        assert resp.status_code == 400


# ===========================================================================
# POST /extract and POST /agent
# ===========================================================================

class TestApiExtract:
    def test_extract_success(self, client):
        extracted = {"price": "$9.99", "plan": "Basic"}
        with patch("emb.api.validate_url"), \
             patch("emb.api.agent_extract", return_value=extracted):
            resp = client.post("/extract",
                               json={"url": "https://example.com", "prompt": "pricing"})

        assert resp.status_code == 200
        assert resp.json()["price"] == "$9.99"

    def test_agent_alias_success(self, client):
        extracted = {"data": "value"}
        with patch("emb.api.validate_url"), \
             patch("emb.api.agent_extract", return_value=extracted):
            resp = client.post("/agent",
                               json={"url": "https://example.com"})

        assert resp.status_code == 200
        assert resp.json()["data"] == "value"

    def test_extract_error_dict_returns_502(self, client):
        with patch("emb.api.validate_url"), \
             patch("emb.api.agent_extract", return_value={"error": "scrape failed"}):
            resp = client.post("/extract",
                               json={"url": "https://example.com"})

        assert resp.status_code == 502


# ===========================================================================
# Auth middleware
# ===========================================================================

class TestAuthMiddleware:
    def test_request_without_key_returns_401(self, authed_client):
        resp = authed_client.post("/scrape", json={"url": "https://example.com"})
        assert resp.status_code == 401

    def test_request_with_correct_key_passes(self, authed_client):
        with patch("emb.api.validate_url"), \
             patch("emb.api.scrape_url", return_value=_ok_scrape()):
            resp = authed_client.post(
                "/scrape",
                json={"url": "https://example.com"},
                headers={"X-API-Key": "secret"},
            )
        # Should be 200 (or at worst something other than 401)
        assert resp.status_code != 401

    def test_request_with_wrong_key_returns_401(self, authed_client):
        resp = authed_client.post(
            "/scrape",
            json={"url": "https://example.com"},
            headers={"X-API-Key": "wrongkey"},
        )
        assert resp.status_code == 401

    def test_root_bypasses_auth(self, authed_client):
        resp = authed_client.get("/")
        assert resp.status_code == 200

    def test_health_bypasses_auth(self, authed_client):
        resp = authed_client.get("/health")
        assert resp.status_code == 200
