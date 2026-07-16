from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from emb.scrape import scrape_url

_log = logging.getLogger(__name__)

_DEFAULT_API_KEY = os.environ.get("EMBER_LLM_API_KEY", "")
_DEFAULT_BASE_URL = os.environ.get("EMBER_LLM_BASE_URL", "https://api.openai.com/v1")
_DEFAULT_MODEL = os.environ.get("EMBER_LLM_MODEL", "gpt-4o-mini")
_MAX_CONTENT_CHARS = 15_000


# Extract needs an LLM.
def extract(
    url: str,
    *,
    prompt: str = "",
    model: str = _DEFAULT_MODEL,
    api_key: str = _DEFAULT_API_KEY,
    base_url: str = _DEFAULT_BASE_URL,
    timeout: int = 60,
    use_browser: bool | None = None,
) -> dict[str, Any]:
    scraped = scrape_url(url, use_browser=use_browser, timeout=timeout)
    if not scraped.success:
        return {"error": scraped.error or "Failed to scrape URL"}

    if not api_key:
        return {
            "error": (
                "extract() requires EMBER_LLM_API_KEY. "
                "Use ember url or scrape_url() when you want raw page markdown."
            )
        }

    user_prompt = f"Page: {url}\nTitle: {scraped.title}\n\n{scraped.markdown[:_MAX_CONTENT_CHARS]}\n\n"
    if prompt:
        user_prompt += f"Task: {prompt}"
    else:
        user_prompt += "Extract the main structured information."

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Extract the requested information from the page content."},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {"content": content, "sources": [url]}
    except Exception as e:
        _log.debug("LLM request error: %s", e)
        return {"error": "LLM request failed"}
