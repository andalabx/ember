"""LLM-powered structured extraction from scraped pages."""

from __future__ import annotations

import json
import os
from typing import Any

from ember.scrape import scrape_url

_DEFAULT_API_KEY = os.environ.get("EMBER_LLM_API_KEY", "")
_DEFAULT_BASE_URL = os.environ.get("EMBER_LLM_BASE_URL", "https://api.openai.com/v1")
_DEFAULT_MODEL = os.environ.get("EMBER_LLM_MODEL", "gpt-4o-mini")


def extract(
    url: str,
    *,
    prompt: str = "",
    model: str = _DEFAULT_MODEL,
    api_key: str = _DEFAULT_API_KEY,
    base_url: str = _DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Extract structured data from a URL using an LLM.

    Scrapes the page to markdown, then sends it to the LLM with
    the extraction prompt. Requires EMBER_LLM_API_KEY to be set.

    Args:
        url: Page to extract from.
        prompt: What to extract (e.g. "list all pricing plans").
        model: LLM model name.
        api_key: API key for the LLM provider.
        base_url: Base URL for the LLM API.

    Returns:
        Dictionary with extracted content.
    """
    scraped = scrape_url(url)
    if not scraped.success:
        return {"error": scraped.error or "Failed to scrape URL"}

    if not api_key:
        return {"markdown": scraped.markdown, "title": scraped.title}

    user_prompt = f"Page: {url}\nTitle: {scraped.title}\n\n{scraped.markdown[:15000]}\n\n"
    if prompt:
        user_prompt += f"Task: {prompt}"
    else:
        user_prompt += "Extract the main structured information."

    try:
        import httpx
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
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {"content": content, "sources": [url]}
    except Exception as e:
        return {"error": f"LLM extraction failed: {e}"}
