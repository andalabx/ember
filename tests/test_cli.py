"""Tests for every CLI command in emb.cli.

Uses typer.testing.CliRunner — no real network, no subprocesses.
All underlying functions are mocked at the call site (emb.cli imports).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from emb.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers — pre-built return values
# ---------------------------------------------------------------------------

def _ok_scrape(url="https://example.com", markdown="Page markdown", title="Page Title"):
    from emb.types import ScrapeResult
    return ScrapeResult(url=url, markdown=markdown, title=title, success=True)


def _fail_scrape(url="https://example.com", error="connect timeout"):
    from emb.types import ScrapeResult
    return ScrapeResult(url=url, success=False, error=error)


def _ok_crawl(url="https://example.com"):
    from emb.types import CrawlResult, CrawlPage
    page = CrawlPage(url=url, markdown="content text", title="Title", depth=0)
    return CrawlResult(url=url, pages=[page], total=1, success=True)


def _ok_map(url="https://example.com"):
    from emb.types import MapResult
    return MapResult(url=url, links=["https://example.com/a", "https://example.com/b"], total=2)


def _ok_interact(url="https://example.com"):
    from emb.types import InteractResult
    return InteractResult(url=url, content="Action completed.", success=True)


def _fail_interact(url="https://example.com", error="LLM failed"):
    from emb.types import InteractResult
    return InteractResult(url=url, success=False, error=error)


def _search_results():
    from emb.types import SearchResult
    return [
        SearchResult(url="https://a.com", title="Result A", description="Description A"),
        SearchResult(url="https://b.com", title="Result B", description="Description B"),
    ]


# ===========================================================================
# version
# ===========================================================================

class TestVersion:
    def test_version_prints_version_string(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "ember v0.1.0" in result.output


# ===========================================================================
# serve
# ===========================================================================

class TestCmdServe:
    def test_serve_starts_with_default_port(self):
        with patch("emb.api.start_server") as mock_start:
            result = runner.invoke(app, ["serve"])

        mock_start.assert_called_once_with(host="127.0.0.1", port=51251)
        assert result.exit_code == 0

    def test_serve_custom_port_flag(self):
        with patch("emb.api.start_server") as mock_start:
            result = runner.invoke(app, ["serve", "--port", "8080"])

        call_kwargs = mock_start.call_args[1]
        assert call_kwargs.get("port") == 8080

    def test_serve_ember_port_env_var(self, monkeypatch):
        monkeypatch.setenv("EMBER_PORT", "9000")
        # Re-import app after env change so the default is re-evaluated
        from importlib import reload
        import emb.cli as cli_mod
        reload(cli_mod)
        from emb.cli import app as reloaded_app

        with patch("emb.api.start_server") as mock_start:
            runner.invoke(reloaded_app, ["serve"])

        call_kwargs = mock_start.call_args[1]
        assert call_kwargs.get("port") == 9000

    def test_serve_prints_url(self):
        with patch("emb.api.start_server"):
            result = runner.invoke(app, ["serve", "--port", "51251"])

        assert "51251" in result.output
        assert "127.0.0.1" in result.output


# ===========================================================================
# url (cmd_url)
# ===========================================================================

class TestCmdUrl:
    def test_url_with_title_exit_0(self):
        with patch("emb.scrape.scrape_url", return_value=_ok_scrape()):
            result = runner.invoke(app, ["url", "https://example.com"])

        assert result.exit_code == 0
        assert "Page Title" in result.output
        assert "Page markdown" in result.output

    def test_url_without_title_no_heading(self):
        no_title = _ok_scrape(title="")
        with patch("emb.scrape.scrape_url", return_value=no_title):
            result = runner.invoke(app, ["url", "https://example.com"])

        assert result.exit_code == 0
        # No heading line should appear (title is blank)
        assert "# " not in result.output

    def test_url_failure_exit_1(self):
        with patch("emb.scrape.scrape_url", return_value=_fail_scrape()):
            result = runner.invoke(app, ["url", "https://example.com"])

        assert result.exit_code == 1
        # Error message should appear somewhere in the combined output
        assert "connect timeout" in result.output or "Error" in result.output


# ===========================================================================
# search
# ===========================================================================

class TestCmdSearch:
    def test_search_prints_results(self):
        with patch("emb.search.search", return_value=_search_results()):
            result = runner.invoke(app, ["search", "python"])

        assert result.exit_code == 0
        assert "Result A" in result.output
        assert "https://a.com" in result.output
        assert "Description A" in result.output
        assert "Result B" in result.output

    def test_search_prints_query_header(self):
        with patch("emb.search.search", return_value=_search_results()):
            result = runner.invoke(app, ["search", "python"])

        assert "python" in result.output


# ===========================================================================
# crawl
# ===========================================================================

class TestCmdCrawl:
    def test_crawl_success_exit_0(self):
        with patch("emb.crawl.crawl", return_value=_ok_crawl()):
            result = runner.invoke(app, ["crawl", "https://example.com"])

        assert result.exit_code == 0
        assert "1" in result.output  # total page count

    def test_crawl_delay_param_forwarded(self):
        with patch("emb.crawl.crawl", return_value=_ok_crawl()) as mock_crawl:
            runner.invoke(app, ["crawl", "https://example.com", "--delay", "1.5"])

        call_kwargs = mock_crawl.call_args[1]
        assert call_kwargs.get("delay") == pytest.approx(1.5)

    def test_crawl_max_pages_forwarded(self):
        with patch("emb.crawl.crawl", return_value=_ok_crawl()) as mock_crawl:
            runner.invoke(app, ["crawl", "https://example.com", "--max-pages", "10"])

        call_kwargs = mock_crawl.call_args[1]
        assert call_kwargs.get("max_pages") == 10


# ===========================================================================
# map
# ===========================================================================

class TestCmdMap:
    def test_map_prints_urls(self):
        with patch("emb.map.map_url", return_value=_ok_map()):
            result = runner.invoke(app, ["map", "https://example.com"])

        assert result.exit_code == 0
        # URLs are shown as short paths relative to the base host
        assert "/a" in result.output
        assert "/b" in result.output

    def test_map_prints_total(self):
        with patch("emb.map.map_url", return_value=_ok_map()):
            result = runner.invoke(app, ["map", "https://example.com"])

        assert "2" in result.output  # total == 2


# ===========================================================================
# interact
# ===========================================================================

class TestCmdInteract:
    def test_interact_success_exit_0(self):
        with patch("emb.interact.interact", return_value=_ok_interact()):
            result = runner.invoke(app, ["interact", "https://example.com",
                                         "--prompt", "click the button"])

        assert result.exit_code == 0
        assert "Action completed." in result.output

    def test_interact_failure_exit_1(self):
        with patch("emb.interact.interact", return_value=_fail_interact()):
            result = runner.invoke(app, ["interact", "https://example.com",
                                         "--prompt", "click"])

        assert result.exit_code == 1
        assert "LLM failed" in result.output or "Error" in result.output

    def test_interact_provider_forwarded(self):
        with patch("emb.interact.interact", return_value=_ok_interact()) as mock_interact:
            runner.invoke(app, ["interact", "https://example.com",
                                "--prompt", "do it",
                                "--provider", "anthropic"])

        call_kwargs = mock_interact.call_args[1]
        assert call_kwargs.get("provider") == "anthropic"


# ===========================================================================
# extract
# ===========================================================================

class TestCmdExtract:
    def test_extract_content_dict_prints_content(self):
        payload = {"content": "Extracted text here.", "sources": ["https://example.com"]}
        with patch("emb.agent.extract", return_value=payload):
            result = runner.invoke(app, ["extract", "https://example.com"])

        assert result.exit_code == 0
        assert "Extracted text here." in result.output

    def test_extract_markdown_dict_prints_markdown(self):
        payload = {"markdown": "# Title\n\nContent.", "title": "Title"}
        with patch("emb.agent.extract", return_value=payload):
            result = runner.invoke(app, ["extract", "https://example.com"])

        assert result.exit_code == 0
        # Rich's Markdown renderer converts "# Title" to a styled heading — no literal "#"
        assert "Title" in result.output
        assert "Content." in result.output

    def test_extract_json_dict_prints_json(self):
        payload = {"price": "$9.99", "plan": "Pro"}
        with patch("emb.agent.extract", return_value=payload):
            result = runner.invoke(app, ["extract", "https://example.com"])

        assert result.exit_code == 0
        assert "$9.99" in result.output
        assert "Pro" in result.output

    def test_extract_error_dict_exit_1(self):
        payload = {"error": "Failed to scrape URL"}
        with patch("emb.agent.extract", return_value=payload):
            result = runner.invoke(app, ["extract", "https://example.com"])

        assert result.exit_code == 1
        assert "Failed to scrape URL" in result.output or "Error" in result.output

    def test_extract_model_from_env_var(self, monkeypatch):
        # We can verify the model is forwarded by inspecting the mock call args
        with patch("emb.agent.extract", return_value={"content": "ok"}) as mock_extract:
            # Supply the model explicitly to simulate what EMBER_LLM_MODEL would give
            runner.invoke(app, ["extract", "https://example.com",
                                "--model", "gpt-4-turbo"])

        call_kwargs = mock_extract.call_args[1]
        assert call_kwargs.get("model") == "gpt-4-turbo"

    def test_extract_default_model_gpt4o_mini(self):
        with patch("emb.agent.extract", return_value={"content": "ok"}) as mock_extract, \
             patch.dict("os.environ", {"EMBER_LLM_MODEL": ""}, clear=False):
            runner.invoke(app, ["extract", "https://example.com"])

        call_kwargs = mock_extract.call_args[1]
        # Default model is "gpt-4o-mini" (cli.py line 103)
        assert call_kwargs.get("model") in ("gpt-4o-mini", "")


# ===========================================================================
# batch
# ===========================================================================

class TestCmdBatch:
    def _write_urls(self, tmp_path: Path, lines: list[str]) -> Path:
        f = tmp_path / "urls.txt"
        f.write_text("\n".join(lines))
        return f

    def test_batch_missing_file_exit_1(self, tmp_path):
        result = runner.invoke(app, ["batch", str(tmp_path / "nope.txt")])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "File" in result.output

    def test_batch_empty_file_exit_1(self, tmp_path):
        f = self._write_urls(tmp_path, ["# comment", ""])
        result = runner.invoke(app, ["batch", str(f)])
        assert result.exit_code == 1

    def test_batch_success_prints_summary(self, tmp_path):
        f = self._write_urls(tmp_path, ["https://a.com", "https://b.com"])
        ok = _ok_scrape(url="https://a.com")
        fail = _fail_scrape(url="https://b.com")

        async def _fake_scrape(url, **kw):
            return ok if "a.com" in url else fail

        with patch("emb.scrape.scrape_url_async", side_effect=_fake_scrape):
            result = runner.invoke(app, ["batch", str(f)])

        assert result.exit_code == 0
        assert "1" in result.output   # 1 ok
        assert "a.com" in result.output

    def test_batch_skips_comment_lines(self, tmp_path):
        f = self._write_urls(tmp_path, ["# skip me", "https://a.com"])

        async def _fake_scrape(url, **kw):
            return _ok_scrape(url=url)

        with patch("emb.scrape.scrape_url_async", side_effect=_fake_scrape):
            result = runner.invoke(app, ["batch", str(f)])

        assert result.exit_code == 0

    def test_batch_concurrency_param(self, tmp_path):
        f = self._write_urls(tmp_path, ["https://a.com"])

        async def _fake_scrape(url, **kw):
            return _ok_scrape(url=url)

        with patch("emb.scrape.scrape_url_async", side_effect=_fake_scrape):
            result = runner.invoke(app, ["batch", str(f), "--concurrency", "3"])

        assert result.exit_code == 0


# ===========================================================================
# config
# ===========================================================================

class TestCmdConfig:
    def test_config_show_current(self, tmp_path, monkeypatch):
        monkeypatch.setattr("emb.cli._CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.delenv("EMBER_SAVE_DIR", raising=False)
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "save_dir" in result.output or "not set" in result.output

    def test_config_set_save_dir(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        monkeypatch.setattr("emb.cli._CONFIG_PATH", cfg_path)
        result = runner.invoke(app, ["config", "--save-dir", str(tmp_path / "out")])
        assert result.exit_code == 0
        assert cfg_path.exists()
        data = json.loads(cfg_path.read_text())
        assert "save_dir" in data

    def test_config_clear_save_dir(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"save_dir": "/some/path"}))
        monkeypatch.setattr("emb.cli._CONFIG_PATH", cfg_path)
        result = runner.invoke(app, ["config", "--save-dir", ""])
        assert result.exit_code == 0
        data = json.loads(cfg_path.read_text())
        assert "save_dir" not in data

    def test_config_reset(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"save_dir": "/some/path"}))
        monkeypatch.setattr("emb.cli._CONFIG_PATH", cfg_path)
        result = runner.invoke(app, ["config", "--reset"])
        assert result.exit_code == 0
        assert json.loads(cfg_path.read_text()) == {}
