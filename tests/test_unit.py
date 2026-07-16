from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

# Helpers
# Word threshold for thin content.
_MIN_CONTENT_WORDS = 20

# Above the thin-content threshold.
_RICH_TEXT = " ".join(["word"] * (_MIN_CONTENT_WORDS + 5))

# Below the thin-content threshold.
_THIN_TEXT = " ".join(["word"] * (_MIN_CONTENT_WORDS - 1))

_CARDY_TEXT = "\n\n".join([
    "Real-time observability for AI agents.",
    "Track cost and latency.",
    "Open source browser for agents.",
    "Built for automation teams.",
    "Structured summaries in seconds.",
    "Generate llms.txt for your site.",
    "Label AI outputs faster.",
    "Talk to the lab.",
])

# Minimal HTML pages
_HTML_WITH_TITLE = "<html><head><title>My Page Title</title></head><body><p>Some content here.</p></body></html>"
_HTML_NO_TITLE = "<html><body><p>Some content here.</p></body></html>"


# _scrape_html

class TestScrapeHtml:
    def test_valid_html_extracts_title(self):
        from emb.scrape import _scrape_html

        with patch("emb.scrape.trafilatura.extract", return_value=_RICH_TEXT):
            result = _scrape_html("https://example.com", _HTML_WITH_TITLE)

        assert result.success is True
        assert result.title == "My Page Title"
        assert result.markdown == _RICH_TEXT

    def test_html_without_title_gives_empty_title(self):
        from emb.scrape import _scrape_html

        with patch("emb.scrape.trafilatura.extract", return_value=_RICH_TEXT):
            result = _scrape_html("https://example.com", _HTML_NO_TITLE)

        assert result.success is True
        assert result.title == ""

    def test_trafilatura_returns_none_marks_failure(self):
        from emb.scrape import _scrape_html

        with patch("emb.scrape.trafilatura.extract", return_value=None):
            result = _scrape_html("https://example.com", _HTML_WITH_TITLE)

        assert result.success is False
        assert result.markdown == ""
        assert result.error is not None

    def test_trafilatura_raises_returns_error(self):
        from emb.scrape import _scrape_html

        with patch("emb.scrape.trafilatura.extract", side_effect=RuntimeError("boom")):
            result = _scrape_html("https://example.com", _HTML_WITH_TITLE)

        assert result.success is False
        assert "trafilatura" in result.error.lower() or "boom" in result.error


# _scrape_trafilatura

class TestScrapeTrafilatura:
    def test_http_error_marks_failure(self):
        from unittest.mock import MagicMock
        from emb.scrape import _scrape_trafilatura

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.headers = {}
        mock_resp.content = b""

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _scrape_trafilatura("https://example.com", timeout=10)

        assert result.success is False
        assert result.markdown == ""
        assert "404" in result.error

    def test_network_error_marks_failure(self):
        from emb.scrape import _scrape_trafilatura

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = OSError("network down")
            result = _scrape_trafilatura("https://example.com", timeout=10)

        assert result.success is False
        assert result.markdown == ""
        assert result.error


# _scrape_lightpanda

class TestScrapeLightpanda:
    def test_ensure_browser_raises_returns_error(self):
        from emb.scrape import _scrape_lightpanda

        with patch("emb.scrape._ensure_browser", side_effect=RuntimeError("no binary")):
            result = _scrape_lightpanda("https://example.com", timeout=10)

        assert result.success is False
        assert "no binary" in result.error

    def test_non_zero_exit_code_returns_error(self):
        from emb.scrape import _scrape_lightpanda

        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stderr = "something went wrong"
        fake_proc.stdout = ""

        with patch("emb.scrape._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.scrape.subprocess.run", return_value=fake_proc):
            result = _scrape_lightpanda("https://example.com", timeout=10)

        assert result.success is False
        assert "1" in result.error  # exit code 1 appears in message

    def test_empty_stdout_returns_error(self):
        from emb.scrape import _scrape_lightpanda

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "   "  # whitespace-only → stripped to empty
        fake_proc.stderr = ""

        with patch("emb.scrape._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.scrape.subprocess.run", return_value=fake_proc):
            result = _scrape_lightpanda("https://example.com", timeout=10)

        assert result.success is False
        assert "empty" in result.error.lower()

    def test_timeout_expired_returns_error(self):
        from emb.scrape import _scrape_lightpanda

        with patch("emb.scrape._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.scrape.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="lightpanda", timeout=10)):
            result = _scrape_lightpanda("https://example.com", timeout=10)

        assert result.success is False
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()

    def test_success_returns_markdown(self):
        from emb.scrape import _scrape_lightpanda

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "# Heading\n\nSome content."
        fake_proc.stderr = ""

        with patch("emb.scrape._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.scrape.subprocess.run", return_value=fake_proc):
            result = _scrape_lightpanda("https://example.com", timeout=10)

        assert result.success is True
        assert result.markdown == "# Heading\n\nSome content."


# scrape_url auto-detect

class TestScrapeUrlAutoDetect:
    def test_thin_trafilatura_falls_back_to_lightpanda(self):
        from emb.scrape import scrape_url
        from emb.types import ScrapeResult

        thin_result = ScrapeResult(url="https://example.com", markdown=_THIN_TEXT, success=True)
        rich_lp_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        with patch("emb.scrape.validate_url"), \
             patch("emb.scrape._scrape_trafilatura", return_value=thin_result) as mock_traf, \
             patch("emb.scrape._scrape_lightpanda", return_value=rich_lp_result) as mock_lp:
            result = scrape_url("https://example.com")

        mock_traf.assert_called_once()
        mock_lp.assert_called_once()
        # Lightpanda result chosen because it has more words
        assert result.markdown == _RICH_TEXT

    def test_lightpanda_also_fails_returns_trafilatura_result(self):
        from emb.scrape import scrape_url
        from emb.types import ScrapeResult

        thin_result = ScrapeResult(url="https://example.com", markdown=_THIN_TEXT, success=True)

        with patch("emb.scrape.validate_url"), \
             patch("emb.scrape._scrape_trafilatura", return_value=thin_result), \
             patch("emb.scrape._scrape_lightpanda", side_effect=RuntimeError("unavailable")):
            result = scrape_url("https://example.com")

        # RuntimeError is caught; trafilatura thin result is returned
        assert result.markdown == _THIN_TEXT
        assert result.success is True

    def test_rich_trafilatura_skips_lightpanda(self):
        from emb.scrape import scrape_url
        from emb.types import ScrapeResult

        rich_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        with patch("emb.scrape.validate_url"), \
             patch("emb.scrape._scrape_trafilatura", return_value=rich_result), \
             patch("emb.scrape._scrape_lightpanda") as mock_lp:
            result = scrape_url("https://example.com")

        mock_lp.assert_not_called()
        assert result.markdown == _RICH_TEXT

    def test_cardy_homepage_trafilatura_falls_back_to_lightpanda(self):
        from emb.scrape import scrape_url
        from emb.types import ScrapeResult

        cardy_result = ScrapeResult(url="https://example.com", markdown=_CARDY_TEXT, success=True)
        rich_lp_result = ScrapeResult(
            url="https://example.com",
            markdown="# Example\n\n" + " ".join(["word"] * 80),
            success=True,
        )

        with patch("emb.scrape.validate_url"), \
             patch("emb.scrape._scrape_trafilatura", return_value=cardy_result), \
             patch("emb.scrape._scrape_lightpanda", return_value=rich_lp_result) as mock_lp:
            result = scrape_url("https://example.com")

        mock_lp.assert_called_once()
        assert result.markdown == rich_lp_result.markdown

    def test_use_browser_true_calls_lightpanda_directly(self):
        from emb.scrape import scrape_url
        from emb.types import ScrapeResult

        lp_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        with patch("emb.scrape.validate_url"), \
             patch("emb.scrape._scrape_trafilatura") as mock_traf, \
             patch("emb.scrape._scrape_lightpanda", return_value=lp_result) as mock_lp:
            result = scrape_url("https://example.com", use_browser=True)

        mock_traf.assert_not_called()
        mock_lp.assert_called_once()
        assert result.markdown == _RICH_TEXT

    def test_ssrf_blocked_url_returns_failure(self):
        from emb.scrape import scrape_url

        with patch("emb.scrape.validate_url", side_effect=ValueError("blocked")), \
             patch("emb.scrape._scrape_trafilatura") as mock_traf:
            result = scrape_url("https://10.0.0.1/")

        mock_traf.assert_not_called()
        assert result.success is False
        assert "blocked" in result.error


# scrape_url_async

class TestScrapeUrlAsync:
    def test_non_200_status_returns_failure(self):
        import asyncio
        from emb.scrape import scrape_url_async

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = ""

        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        mock_client.__aexit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_resp)

        # Use AsyncMock for the async context manager
        async def run():
            with patch("emb.scrape.validate_url"), \
                 patch("emb.scrape.httpx.AsyncClient") as MockClient:
                instance = MagicMock()
                async def fake_get(*a, **kw):
                    return mock_resp
                instance.get = fake_get
                async def fake_aenter(*a, **kw):
                    return instance
                async def fake_aexit(*a, **kw):
                    return False
                instance.__aenter__ = fake_aenter
                instance.__aexit__ = fake_aexit
                MockClient.return_value = instance
                return await scrape_url_async("https://example.com", use_browser=False)

        result = asyncio.run(run())
        assert result.success is False
        assert "404" in result.error

    def test_httpx_raises_returns_failure(self):
        import asyncio
        from emb.scrape import scrape_url_async

        async def run():
            with patch("emb.scrape.validate_url"), \
                 patch("emb.scrape.httpx.AsyncClient") as MockClient:
                instance = MagicMock()
                async def fake_get(*a, **kw):
                    raise OSError("connection refused")
                instance.get = fake_get
                async def fake_aenter(*a, **kw):
                    return instance
                async def fake_aexit(*a, **kw):
                    return False
                instance.__aenter__ = fake_aenter
                instance.__aexit__ = fake_aexit
                MockClient.return_value = instance
                return await scrape_url_async("https://example.com", use_browser=False)

        result = asyncio.run(run())
        assert result.success is False
        assert result.error.startswith("fetch:")

    def test_use_browser_false_skips_lightpanda(self):
        import asyncio
        from emb.scrape import scrape_url_async
        from emb.types import ScrapeResult

        # Thin content so auto-detect would normally fall back to Lightpanda
        thin_html = "<html><head><title>T</title></head><body><p>Short.</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = thin_html

        async def run():
            with patch("emb.scrape.validate_url"), \
                 patch("emb.scrape.httpx.AsyncClient") as MockClient, \
                 patch("emb.scrape._scrape_lightpanda") as mock_lp:
                instance = MagicMock()
                async def fake_get(*a, **kw):
                    return mock_resp
                instance.get = fake_get
                async def fake_aenter(*a, **kw):
                    return instance
                async def fake_aexit(*a, **kw):
                    return False
                instance.__aenter__ = fake_aenter
                instance.__aexit__ = fake_aexit
                MockClient.return_value = instance
                with patch("emb.scrape._scrape_html",
                           return_value=ScrapeResult(url="https://example.com",
                                                     markdown=_THIN_TEXT, success=True)):
                    result = await scrape_url_async("https://example.com", use_browser=False)
                mock_lp.assert_not_called()
                return result

        result = asyncio.run(run())
        assert result.success is True

    def test_ssrf_blocked_url_returns_failure(self):
        import asyncio
        from emb.scrape import scrape_url_async

        async def run():
            with patch("emb.scrape.validate_url", side_effect=ValueError("blocked")):
                return await scrape_url_async("https://10.0.0.1/")

        result = asyncio.run(run())
        assert result.success is False
        assert "blocked" in result.error

    def test_use_browser_true_runs_in_executor(self):
        import asyncio
        from emb.scrape import scrape_url_async
        from emb.types import ScrapeResult

        lp_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        async def run():
            with patch("emb.scrape.validate_url"), \
                 patch("emb.scrape._scrape_lightpanda", return_value=lp_result) as mock_lp:
                result = await scrape_url_async("https://example.com", use_browser=True)
                mock_lp.assert_called_once()
                return result

        result = asyncio.run(run())
        assert result.success is True
        assert result.markdown == _RICH_TEXT

    def test_auto_detect_thin_content_falls_back_to_lightpanda(self):
        import asyncio
        from emb.scrape import scrape_url_async
        from emb.types import ScrapeResult

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>Short.</p></body></html>"

        lp_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        async def run():
            with patch("emb.scrape.validate_url"), \
                 patch("emb.scrape.httpx.AsyncClient") as MockClient, \
                 patch("emb.scrape._scrape_html",
                       return_value=ScrapeResult(url="https://example.com",
                                                 markdown=_THIN_TEXT, success=True)), \
                 patch("emb.scrape._scrape_lightpanda", return_value=lp_result) as mock_lp:
                instance = MagicMock()
                async def fake_get(*a, **kw):
                    return mock_resp
                instance.get = fake_get
                async def fake_aenter(*a, **kw):
                    return instance
                async def fake_aexit(*a, **kw):
                    return False
                instance.__aenter__ = fake_aenter
                instance.__aexit__ = fake_aexit
                MockClient.return_value = instance
                result = await scrape_url_async("https://example.com")
                mock_lp.assert_called_once()
                return result

        result = asyncio.run(run())
        assert result.success is True
        assert result.markdown == _RICH_TEXT

    def test_auto_detect_cardy_homepage_falls_back_to_lightpanda(self):
        import asyncio
        from emb.scrape import scrape_url_async
        from emb.types import ScrapeResult

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><main>cards</main></body></html>"

        cardy_result = ScrapeResult(url="https://example.com", markdown=_CARDY_TEXT, success=True)
        rich_lp_result = ScrapeResult(
            url="https://example.com",
            markdown="# Example\n\n" + " ".join(["word"] * 80),
            success=True,
        )

        async def run():
            with patch("emb.scrape.validate_url"), \
                 patch("emb.scrape.httpx.AsyncClient") as MockClient, \
                 patch("emb.scrape._scrape_html", return_value=cardy_result), \
                 patch("emb.scrape._scrape_lightpanda", return_value=rich_lp_result) as mock_lp:
                instance = MagicMock()

                async def fake_get(*a, **kw):
                    return mock_resp

                instance.get = fake_get

                async def fake_aenter(*a, **kw):
                    return instance

                async def fake_aexit(*a, **kw):
                    return False

                instance.__aenter__ = fake_aenter
                instance.__aexit__ = fake_aexit
                MockClient.return_value = instance
                result = await scrape_url_async("https://example.com")
                mock_lp.assert_called_once()
                return result

        result = asyncio.run(run())
        assert result.success is True
        assert result.markdown == rich_lp_result.markdown


# interact

class TestInteract:
    def test_no_prompt_propagates_scrape_failure(self):
        from emb.interact import interact
        from emb.types import ScrapeResult

        failed = ScrapeResult(url="https://example.com", success=False, error="network error")

        with patch("emb.interact.validate_url"), \
             patch("emb.scrape.scrape_url", return_value=failed), \
             patch("emb.scrape.scrape_markdown", side_effect=AssertionError("should use scrape_url")):
            result = interact("https://example.com", prompt="", use_browser=True)

        assert result.success is False
        assert result.error == "network error"

    def test_no_prompt_returns_scraped_content(self):
        from emb.interact import interact
        from emb.types import ScrapeResult

        with patch("emb.interact.validate_url"), \
             patch(
                 "emb.scrape.scrape_url",
                 return_value=ScrapeResult(url="https://example.com", markdown="Page content", success=True),
             ) as mock_scrape:
            result = interact("https://example.com", prompt="", use_browser=True)

        mock_scrape.assert_called_once_with("https://example.com", use_browser=True, timeout=60)
        assert result.success is True
        assert result.content == "Page content"

    def test_unknown_provider_returns_error(self):
        from emb.interact import interact

        with patch("emb.interact.validate_url"):
            result = interact("https://example.com", prompt="do something",
                              provider="unknownai", use_browser=True)

        assert result.success is False
        assert "unknownai" in result.error.lower() or "unknown" in result.error.lower()

    def test_missing_api_key_for_keyed_provider(self):
        from emb.interact import interact

        # Ensure the env var is absent so there's no fallback key
        with patch("emb.interact.validate_url"), \
             patch.dict("os.environ", {}, clear=False):
            import os
            env_backup = os.environ.pop("OPENAI_API_KEY", None)
            env_backup2 = os.environ.pop("EMBER_LLM_API_KEY", None)
            try:
                result = interact("https://example.com", prompt="do something",
                                  provider="openai", api_key="")
            finally:
                if env_backup is not None:
                    os.environ["OPENAI_API_KEY"] = env_backup
                if env_backup2 is not None:
                    os.environ["EMBER_LLM_API_KEY"] = env_backup2

        assert result.success is False
        assert "api" in result.error.lower() or "key" in result.error.lower()

    def test_ollama_no_key_needed(self):
        from emb.interact import interact

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "Task completed."
        fake_proc.stderr = ""

        with patch("emb.interact.validate_url"), \
             patch("emb.interact._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.interact.subprocess.run", return_value=fake_proc):
            result = interact("https://example.com", prompt="click OK",
                              provider="ollama", api_key="", use_browser=True)

        assert result.success is True
        assert result.content == "Task completed."

    def test_llama_cpp_no_key_needed(self):
        from emb.interact import interact

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "Done."
        fake_proc.stderr = ""

        with patch("emb.interact.validate_url"), \
             patch("emb.interact._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.interact.subprocess.run", return_value=fake_proc):
            result = interact("https://example.com", prompt="fill form",
                              provider="llama_cpp", api_key="", use_browser=True)

        assert result.success is True

    def test_ensure_browser_raises_returns_error(self):
        from emb.interact import interact

        with patch("emb.interact.validate_url"), \
             patch("emb.interact._ensure_browser", side_effect=RuntimeError("no binary")):
            result = interact("https://example.com", prompt="do thing",
                              provider="ollama", api_key="", use_browser=True)

        assert result.success is False
        assert "no binary" in result.error

    def test_subprocess_timeout_returns_error(self):
        from emb.interact import interact

        with patch("emb.interact.validate_url"), \
             patch("emb.interact._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.interact.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="lightpanda", timeout=60)):
            result = interact("https://example.com", prompt="click",
                              provider="ollama", api_key="", timeout=60, use_browser=True)

        assert result.success is False
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()

    def test_non_zero_returncode_always_fails(self):
        from emb.interact import interact

        fake_proc = MagicMock()
        fake_proc.returncode = 2
        fake_proc.stdout = "partial output"
        fake_proc.stderr = "critical failure"

        with patch("emb.interact.validate_url"), \
             patch("emb.interact._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.interact.subprocess.run", return_value=fake_proc):
            result = interact("https://example.com", prompt="click",
                              provider="ollama", api_key="", use_browser=True)

        assert result.success is False
        assert "2" in result.error  # exit code appears in error message

    def test_model_param_forwarded_to_cmd(self):
        from emb.interact import interact

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "done"
        fake_proc.stderr = ""

        with patch("emb.interact.validate_url"), \
             patch("emb.interact._ensure_browser", return_value="/usr/bin/lightpanda"), \
             patch("emb.interact.subprocess.run", return_value=fake_proc) as mock_run:
            interact("https://example.com", prompt="navigate",
                     provider="ollama", api_key="", model="llama3:latest", use_browser=True)

        called_cmd = mock_run.call_args[0][0]  # positional first arg (the list)
        assert "--model" in called_cmd
        assert "llama3:latest" in called_cmd

    def test_ssrf_blocked_url_returns_failure(self):
        from emb.interact import interact

        with patch("emb.interact.validate_url", side_effect=ValueError("blocked")):
            result = interact("https://10.0.0.1/", prompt="click")

        assert result.success is False
        assert "blocked" in result.error

    def test_invalid_model_too_long_returns_error(self):
        from emb.interact import interact

        with patch("emb.interact.validate_url"):
            result = interact("https://example.com", prompt="click",
                              provider="ollama", api_key="", model="x" * 129, use_browser=True)

        assert result.success is False
        assert "model" in result.error.lower() or "invalid" in result.error.lower()

    def test_invalid_model_starts_with_dash_returns_error(self):
        from emb.interact import interact

        with patch("emb.interact.validate_url"):
            result = interact("https://example.com", prompt="click",
                              provider="ollama", api_key="", model="-bad-flag", use_browser=True)

        assert result.success is False
        assert "model" in result.error.lower() or "invalid" in result.error.lower()

    def test_no_browser_prompt_uses_passed_model(self):
        from emb.interact import interact
        from emb.types import ScrapeResult

        scraped = ScrapeResult(url="https://example.com", markdown="Page body", title="Page", success=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Answer"}}]
        }

        with patch("emb.interact.validate_url"), \
             patch("emb.scrape.scrape_url", return_value=scraped), \
             patch("httpx.post", return_value=mock_resp) as mock_post:
            result = interact(
                "https://example.com",
                prompt="summarize",
                api_key="sk-test",
                model="custom-model",
                use_browser=False,
            )

        assert result.success is True
        assert mock_post.call_args.kwargs["json"]["model"] == "custom-model"

    def test_no_browser_non_openai_provider_returns_clear_error(self):
        from emb.interact import interact

        with patch("emb.interact.validate_url"):
            result = interact(
                "https://example.com",
                prompt="summarize",
                provider="anthropic",
                api_key="sk-test",
                use_browser=False,
            )

        assert result.success is False
        assert "openai-compatible" in result.error.lower()


# extract (agent.py)

class TestExtract:
    def test_scrape_failure_returns_error_dict(self):
        from emb.agent import extract
        from emb.types import ScrapeResult

        failed = ScrapeResult(url="https://x.com", success=False, error="network error")

        with patch("emb.agent.scrape_url", return_value=failed):
            result = extract("https://x.com")

        assert "error" in result

    def test_no_api_key_returns_error_dict(self):
        from emb.agent import extract
        from emb.types import ScrapeResult

        scraped = ScrapeResult(url="https://x.com", markdown="# Hello", title="Hello", success=True)

        with patch("emb.agent.scrape_url", return_value=scraped), \
             patch("emb.agent.httpx.post") as mock_post:
            result = extract("https://x.com", api_key="")

        mock_post.assert_not_called()
        assert "error" in result
        assert "api key" in result["error"].lower() or "ember_llm_api_key" in result["error"].lower()

    def test_llm_returns_valid_json(self):
        import json
        from emb.agent import extract
        from emb.types import ScrapeResult

        scraped = ScrapeResult(url="https://x.com", markdown="content", title="T", success=True)
        llm_payload = json.dumps({"price": "$9.99", "plan": "Basic"})

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": llm_payload}}]
        }

        with patch("emb.agent.scrape_url", return_value=scraped), \
             patch("emb.agent.httpx.post", return_value=mock_resp):
            result = extract("https://x.com", api_key="sk-test")

        assert result == {"price": "$9.99", "plan": "Basic"}

    def test_llm_returns_non_json_text(self):
        from emb.agent import extract
        from emb.types import ScrapeResult

        scraped = ScrapeResult(url="https://x.com", markdown="content", title="T", success=True)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Here is what I found: lots of text."}}]
        }

        with patch("emb.agent.scrape_url", return_value=scraped), \
             patch("emb.agent.httpx.post", return_value=mock_resp):
            result = extract("https://x.com", api_key="sk-test")

        assert "content" in result
        assert result["sources"] == ["https://x.com"]

    def test_httpx_raises_returns_error_dict(self):
        from emb.agent import extract
        from emb.types import ScrapeResult

        scraped = ScrapeResult(url="https://x.com", markdown="content", title="T", success=True)

        with patch("emb.agent.scrape_url", return_value=scraped), \
             patch("emb.agent.httpx.post", side_effect=OSError("connection timeout")):
            result = extract("https://x.com", api_key="sk-test")

        assert "error" in result
        assert "llm" in result["error"].lower() or "failed" in result["error"].lower()


# _browser.ensure

class TestBrowserEnsure:
    def test_env_path_real_file_returned(self, tmp_path):
        from emb._browser import ensure

        fake_binary = tmp_path / "lightpanda"
        fake_binary.write_bytes(b"ELF")

        with patch.dict("os.environ", {"EMBER_LIGHTPANDA_PATH": str(fake_binary)}):
            result = ensure()

        assert result == str(fake_binary)

    def test_env_path_bare_name_resolved_via_path(self):
        from emb._browser import ensure

        fake_run = MagicMock()
        fake_run.returncode = 0

        with patch.dict("os.environ", {"EMBER_LIGHTPANDA_PATH": "lightpanda-custom"}), \
             patch("emb._browser.subprocess.run", return_value=fake_run):
            result = ensure()

        assert result == "lightpanda-custom"

    def test_env_path_with_separator_nonexistent_raises(self):
        from emb._browser import ensure
        import os

        # Force a path that has a separator but does not exist
        fake_path = "/nonexistent/path/to/lightpanda"
        with patch.dict("os.environ", {"EMBER_LIGHTPANDA_PATH": fake_path}):
            with pytest.raises(RuntimeError, match="binary not found"):
                ensure()

    def test_windows_platform_raises_wsl_message(self):
        from emb import _browser

        # Ensure EMBER_LIGHTPANDA_PATH is unset so we reach platform detection
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("EMBER_LIGHTPANDA_PATH", None)

            with patch("emb._browser.platform.system", return_value="Windows"), \
                 patch("emb._browser.subprocess.run",
                       side_effect=FileNotFoundError("not found")), \
                 patch("emb._browser.BINARY_PATH") as mock_bp:
                mock_bp.exists.return_value = False
                # _platform_url must return None for Windows
                with patch("emb._browser._platform_url", return_value=None):
                    with pytest.raises(RuntimeError, match="WSL"):
                        _browser.ensure()

    def test_unsupported_platform_raises(self):
        from emb import _browser

        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("EMBER_LIGHTPANDA_PATH", None)

            with patch("emb._browser.platform.system", return_value="Linux"), \
                 patch("emb._browser.platform.machine", return_value="mips"), \
                 patch("emb._browser.subprocess.run",
                       side_effect=FileNotFoundError("not found")), \
                 patch("emb._browser.BINARY_PATH") as mock_bp:
                mock_bp.exists.return_value = False
                with patch("emb._browser._platform_url", return_value=None):
                    with pytest.raises(RuntimeError) as exc_info:
                        _browser.ensure()

            # WSL should not appear on non-Windows platforms.
            assert "wsl" not in str(exc_info.value).lower()


# _browser.is_available

class TestBrowserIsAvailable:
    def test_binary_exists_returns_true(self, tmp_path):
        from emb import _browser

        fake = tmp_path / "lightpanda"
        fake.write_bytes(b"ELF")

        with patch.object(_browser, "BINARY_PATH", fake):
            result = _browser.is_available()

        assert result is True

    def test_binary_not_found_returns_false(self, tmp_path):
        from emb import _browser

        missing = tmp_path / "nope"  # does not exist

        with patch.object(_browser, "BINARY_PATH", missing), \
             patch("emb._browser.subprocess.run",
                   side_effect=FileNotFoundError("not found")):
            result = _browser.is_available()

        assert result is False


# validate_url

class TestValidateUrl:
    def test_valid_public_url_passes(self):
        import socket
        from emb._url_validator import validate_url

        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        with patch("emb._url_validator.socket.getaddrinfo", return_value=fake_infos):
            validate_url("https://example.com/path")  # must not raise

    def test_private_ip_10x_blocked(self):
        import socket
        from emb._url_validator import validate_url

        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]
        with patch("emb._url_validator.socket.getaddrinfo", return_value=fake_infos):
            with pytest.raises(ValueError, match="blocked"):
                validate_url("https://internal.corp/")

    def test_private_ip_192168x_blocked(self):
        import socket
        from emb._url_validator import validate_url

        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 0))]
        with patch("emb._url_validator.socket.getaddrinfo", return_value=fake_infos):
            with pytest.raises(ValueError, match="blocked"):
                validate_url("https://router.local/")

    def test_loopback_127x_blocked(self):
        from emb._url_validator import validate_url

        with pytest.raises(ValueError, match="blocked"):
            validate_url("https://localhost/")  # localhost resolves to loopback

    def test_link_local_169254x_blocked(self):
        import socket
        from emb._url_validator import validate_url

        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]
        with patch("emb._url_validator.socket.getaddrinfo", return_value=fake_infos):
            with pytest.raises(ValueError, match="blocked"):
                validate_url("https://metadata.google.internal/")

    def test_file_scheme_blocked(self):
        from emb._url_validator import validate_url

        with pytest.raises(ValueError, match="scheme"):
            validate_url("file:///etc/passwd")

    def test_no_hostname_blocked(self):
        from emb._url_validator import validate_url

        with pytest.raises(ValueError):
            validate_url("https:///path")

    def test_private_ip_172_16x_blocked(self):
        import socket
        from emb._url_validator import validate_url

        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.16.0.1", 0))]
        with patch("emb._url_validator.socket.getaddrinfo", return_value=fake_infos):
            with pytest.raises(ValueError, match="blocked"):
                validate_url("https://internal.corp/")

    def test_ipv6_loopback_blocked(self):
        import socket
        from emb._url_validator import validate_url

        fake_infos = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))]
        with patch("emb._url_validator.socket.getaddrinfo", return_value=fake_infos):
            with pytest.raises(ValueError, match="blocked"):
                validate_url("https://ip6-localhost/")

    def test_ipv6_mapped_ipv4_blocked(self):
        import socket
        from emb._url_validator import validate_url

        fake_infos = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:10.0.0.1", 0, 0, 0))]
        with patch("emb._url_validator.socket.getaddrinfo", return_value=fake_infos):
            with pytest.raises(ValueError, match="blocked"):
                validate_url("https://internal.corp/")

    def test_unresolvable_hostname_raises(self):
        import socket
        from emb._url_validator import validate_url

        with patch("emb._url_validator.socket.getaddrinfo",
                   side_effect=socket.gaierror("Name or service not known")):
            with pytest.raises(ValueError, match="Cannot resolve"):
                validate_url("https://thisdomaindoesnotexist.invalid/")

    def test_redirect_target_is_revalidated(self):
        from emb.scrape import scrape_url

        def fake_validate(url: str) -> None:
            if "127.0.0.1" in url:
                raise ValueError("URL resolves to a blocked address (127.0.0.1)")

        redirect_resp = MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"location": "http://127.0.0.1/admin"}
        redirect_resp.url = "https://example.com/start"

        with patch("emb.scrape.validate_url", side_effect=fake_validate), \
             patch("emb.scrape.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.return_value = redirect_resp
            MockClient.return_value.__enter__.return_value = mock_client
            MockClient.return_value.__exit__.return_value = False
            result = scrape_url("https://example.com", use_browser=False)

        assert result.success is False
        assert "blocked address" in (result.error or "")


# Types

class TestTypeDefaults:
    def test_scrape_result_defaults(self):
        from emb.types import ScrapeResult

        r = ScrapeResult(url="https://x.com")

        assert r.markdown == ""
        assert r.title == ""
        assert r.description == ""
        assert r.screenshot is None
        assert r.metadata == {}
        assert r.success is True
        assert r.error is None

    def test_interact_result_defaults(self):
        from emb.types import InteractResult

        r = InteractResult(url="https://x.com")

        assert r.content == ""
        assert r.screenshot is None
        assert r.success is True
        assert r.error is None


# _sitemap_urls

class TestSitemapUrlsRecursion:
    def test_stops_at_depth_3(self):
        from emb.crawl import _sitemap_urls

        # Build a sitemap XML that references the next level
        def make_sitemap_index(child_url: str) -> str:
            return (
                '<?xml version="1.0"?>'
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<sitemap><loc>{child_url}</loc></sitemap>"
                "</sitemapindex>"
            )

        leaf_sitemap = (
            '<?xml version="1.0"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.com/leaf</loc></url>"
            "</urlset>"
        )

        call_count = {"n": 0}
        level_urls = [
            "https://example.com/sitemap0.xml",
            "https://example.com/sitemap1.xml",
            "https://example.com/sitemap2.xml",
            "https://example.com/sitemap3.xml",
            "https://example.com/sitemap4.xml",
        ]

        def fake_get(url, timeout=15):
            call_count["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            idx = level_urls.index(url) if url in level_urls else -1
            if idx == len(level_urls) - 1 or idx == -1:
                resp.text = leaf_sitemap
            else:
                resp.text = make_sitemap_index(level_urls[idx + 1])
            return resp

        mock_client = MagicMock()
        mock_client.get.side_effect = fake_get

        urls = _sitemap_urls(level_urls[0], mock_client)

        # The guard stops recursion at _depth > 3, so we should not see calls
        # for depth 4 and 5 (level_urls[4]). The leaf may or may not be reached
        # depending on which level hits depth > 3, but critically the function
        # terminates and we don't recurse infinitely.
        assert call_count["n"] <= 4  # depth 0, 1, 2, 3 → at most 4 GET requests


# _find_sitemaps

class TestFindSitemapsCap:
    def test_robots_txt_cap_at_10_candidates(self):
        from emb.crawl import _find_sitemaps

        # Build robots.txt with 20 Sitemap: directives
        robots_lines = "\n".join(
            f"Sitemap: https://example.com/sitemap_{i}.xml" for i in range(20)
        )

        robots_resp = MagicMock()
        robots_resp.status_code = 200
        robots_resp.text = robots_lines

        # Every HEAD returns 404, so only the candidate cap matters here.
        head_resp = MagicMock()
        head_resp.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = robots_resp
        mock_client.head.return_value = head_resp

        _find_sitemaps("https://example.com/", mock_client)

        # HEAD calls should stay at or below the cap.
        head_call_count = mock_client.head.call_count
        # The candidate list is capped at 10, so we should never HEAD more than 10 URLs
        assert head_call_count <= 10


# crawl

class TestCrawl:
    def test_ssrf_blocked_url_returns_failure(self):
        from emb.crawl import crawl

        with patch("emb.crawl.validate_url", side_effect=ValueError("blocked")):
            result = crawl("https://10.0.0.1/")

        assert result.success is False
        assert "blocked" in result.error

    def test_delay_sleeps_between_pages(self):
        from emb.crawl import crawl
        from emb.types import ScrapeResult

        scrape_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>no links here</body></html>"

        with patch("emb.crawl.validate_url"), \
             patch("emb.crawl._find_sitemaps", return_value=[]), \
             patch("emb.crawl._scrape_html", return_value=scrape_result), \
             patch("emb.crawl.time.sleep") as mock_sleep, \
             patch("emb.crawl.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value = MagicMock(get=MagicMock(return_value=mock_resp))
            MockClient.return_value.__exit__.return_value = False
            crawl("https://example.com", max_pages=1, use_sitemap=False, delay=0.5)

        mock_sleep.assert_called_once_with(0.5)

    def test_use_sitemap_false_skips_sitemap_discovery(self):
        from emb.crawl import crawl
        from emb.types import ScrapeResult

        scrape_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>no links</body></html>"

        with patch("emb.crawl.validate_url"), \
             patch("emb.crawl._find_sitemaps") as mock_find, \
             patch("emb.crawl._scrape_html", return_value=scrape_result), \
             patch("emb.crawl.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value = MagicMock(get=MagicMock(return_value=mock_resp))
            MockClient.return_value.__exit__.return_value = False
            crawl("https://example.com", max_pages=1, use_sitemap=False)

        mock_find.assert_not_called()

    def test_same_domain_false_allows_external_links(self):
        from emb.crawl import crawl
        from emb.types import ScrapeResult

        external = "https://other.com/page"
        html_with_link = (
            '<html><head><title>Home</title></head><body>'
            + ("word " * 25)
            + f'<a href="{external}">External</a>'
            + "</body></html>"
        )
        html_simple = "<html><head><title>Ext</title></head><body>" + ("word " * 25) + "</body></html>"

        scrape_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)

        call_urls = []
        def fake_get(url, **kwargs):
            call_urls.append(url)
            r = MagicMock()
            r.status_code = 200
            r.text = html_simple if url == external else html_with_link
            return r

        with patch("emb.crawl.validate_url"), \
             patch("emb.crawl._find_sitemaps", return_value=[]), \
             patch("emb.crawl._scrape_html", return_value=scrape_result), \
             patch("emb.crawl.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = fake_get
            MockClient.return_value.__enter__.return_value = mock_client
            MockClient.return_value.__exit__.return_value = False
            crawl("https://example.com", max_pages=5, max_depth=1,
                  same_domain=False, use_sitemap=False)

        assert external in call_urls

    def test_same_domain_true_filters_sitemap_urls_from_other_domains(self):
        from emb.crawl import crawl
        from emb.types import ScrapeResult

        scrape_result = ScrapeResult(url="https://example.com", markdown=_RICH_TEXT, success=True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>no links</body></html>"

        with patch("emb.crawl.validate_url"), \
             patch("emb.crawl._find_sitemaps", return_value=["https://example.com/sitemap.xml"]), \
             patch("emb.crawl._sitemap_urls", return_value=["https://other.com/offsite"]), \
             patch("emb.crawl._scrape_html", return_value=scrape_result), \
             patch("emb.crawl.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            MockClient.return_value.__enter__.return_value = mock_client
            MockClient.return_value.__exit__.return_value = False
            result = crawl("https://example.com", max_pages=5, max_depth=1, same_domain=True)

        assert all("example.com" in page.url for page in result.pages)


# map_url

class TestMapUrl:
    def test_ssrf_blocked_url_returns_error(self):
        from emb.map import map_url

        with patch("emb.map.validate_url", side_effect=ValueError("blocked")):
            result = map_url("https://10.0.0.1/")

        assert result.total == 0
        assert result.error is not None
        assert "blocked" in result.error

    def test_link_fallback_when_no_sitemap(self):
        from emb.map import map_url

        home_html = (
            "<html><body>"
            '<a href="/page1">p1</a><a href="/page2">p2</a>'
            "</body></html>"
        )

        def fake_get(url, **kwargs):
            r = MagicMock()
            if "/sitemap" in url or "robots.txt" in url:
                r.status_code = 404
                r.text = ""
            else:
                r.status_code = 200
                r.text = home_html
            return r

        with patch("emb.map.validate_url"), \
             patch("emb.map.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = fake_get
            MockClient.return_value.__enter__.return_value = mock_client
            MockClient.return_value.__exit__.return_value = False
            result = map_url("https://example.com/")

        assert result.total >= 1
        assert any("example.com" in link for link in result.links)

    def test_sitemap_urls_stay_on_requested_domain(self):
        from emb.map import map_url

        sitemap_xml = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://other.com/offsite</loc></url>"
            "<url><loc>https://example.com/on-site</loc></url>"
            "</urlset>"
        )

        def fake_get(url, **kwargs):
            r = MagicMock()
            if "robots.txt" in url:
                r.status_code = 404
                r.text = ""
            elif "/sitemap" in url:
                r.status_code = 200
                r.text = sitemap_xml
            else:
                r.status_code = 200
                r.text = "<html><body></body></html>"
            return r

        with patch("emb.map.validate_url"), \
             patch("emb.map.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = fake_get
            MockClient.return_value.__enter__.return_value = mock_client
            MockClient.return_value.__exit__.return_value = False
            result = map_url("https://example.com/")

        assert "https://example.com/on-site" in result.links
        assert "https://other.com/offsite" not in result.links
