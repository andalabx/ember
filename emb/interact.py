"""Browser interaction via Lightpanda agent. Auto-installs on first use."""

from __future__ import annotations

import os
import platform
import subprocess

from emb._browser import ensure as _ensure_browser
from emb._url_validator import validate_url
from emb.types import InteractResult

_DEFAULT_PROVIDER = os.environ.get("EMBER_INTERACT_PROVIDER", "openai")
_DEFAULT_API_KEY = os.environ.get("EMBER_LLM_API_KEY", "")
_DEFAULT_MODEL = os.environ.get("EMBER_LLM_MODEL", "")

# Maps provider name → env var that Lightpanda reads for its API key.
# None means no key needed (local providers).
_PROVIDER_ENV_VARS: dict[str, str | None] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "huggingface": "HF_TOKEN",
    "vercel": "AI_GATEWAY_API_KEY",
    "ollama": None,
    "llama_cpp": None,
}


# Without a prompt, returns page markdown directly (no LLM needed).
# use_browser=False (or auto on Windows) falls back to trafilatura; prompt is answered via direct LLM call.
def interact(
    url: str,
    *,
    prompt: str = "",
    provider: str = _DEFAULT_PROVIDER,
    api_key: str = _DEFAULT_API_KEY,
    model: str = _DEFAULT_MODEL,
    timeout: int = 60,
    use_browser: bool = platform.system() != "Windows",
) -> InteractResult:
    try:
        validate_url(url)
    except ValueError as e:
        return InteractResult(url=url, success=False, error=str(e))

    if not prompt:
        from emb.scrape import scrape_markdown
        content = scrape_markdown(url, use_browser=True if use_browser else False)
        return InteractResult(url=url, content=content)

    # No-browser path: scrape with trafilatura then answer via direct LLM call
    if not use_browser:
        return _interact_no_browser(url, prompt=prompt, api_key=api_key, timeout=timeout)

    if provider not in _PROVIDER_ENV_VARS:
        return InteractResult(
            url=url, content="", success=False,
            error=f"Unknown provider {provider!r}. Valid providers: {sorted(_PROVIDER_ENV_VARS)}",
        )

    # Sanitize model: reject values that look like extra CLI flags
    model = model.strip()
    if model and (model.startswith("-") or len(model) > 128):
        return InteractResult(
            url=url, content="", success=False,
            error=f"Invalid model name: {model!r}",
        )

    env_var = _PROVIDER_ENV_VARS.get(provider)
    effective_key = ""
    if env_var is not None:
        effective_key = api_key or os.environ.get(env_var, "")
        if not effective_key:
            return InteractResult(
                url=url, content="", success=False,
                error=(
                    f"interact() with a prompt requires an LLM. "
                    f"Set EMBER_LLM_API_KEY or {env_var}, "
                    f"or pass provider='ollama' to use a local model."
                ),
            )

    try:
        lp = _ensure_browser()
    except RuntimeError as e:
        return InteractResult(url=url, content="", success=False, error=str(e))

    # Pass the API key via the env var Lightpanda reads for the chosen provider
    env = os.environ.copy()
    if env_var and effective_key:
        env[env_var] = effective_key

    # Lightpanda agent navigates based on task text; embed the URL there
    task = f"Navigate to {url}. {prompt}"
    cmd = [lp, "agent", "--task", task, "--provider", provider]
    if model:
        cmd += ["--model", model]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        content = (proc.stdout or proc.stderr or "").strip()
        if proc.returncode != 0:
            return InteractResult(
                url=url, content="", success=False,
                error=f"Lightpanda agent exit {proc.returncode}: {(proc.stderr or proc.stdout or '')[:200]}",
            )
        return InteractResult(url=url, content=content)
    except subprocess.TimeoutExpired:
        return InteractResult(url=url, content="", success=False, error=f"Timed out ({timeout}s)")
    except Exception as e:
        return InteractResult(url=url, content="", success=False, error=str(e))


def _interact_no_browser(url: str, *, prompt: str, api_key: str, timeout: int) -> InteractResult:
    from emb.scrape import scrape_url
    import httpx
    import json

    scraped = scrape_url(url, use_browser=False, timeout=timeout)
    if not scraped.success:
        return InteractResult(url=url, content="", success=False, error=scraped.error)

    if not api_key:
        return InteractResult(
            url=url, content="", success=False,
            error="interact() with a prompt requires EMBER_LLM_API_KEY (no browser path uses OpenAI-compatible API).",
        )

    base_url = os.environ.get("EMBER_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("EMBER_LLM_MODEL", "gpt-4o-mini")
    content_snippet = scraped.markdown[:15_000]
    user_msg = f"Page: {url}\nTitle: {scraped.title}\n\n{content_snippet}\n\nTask: {prompt}"

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Answer the task using the page content provided."},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
        return InteractResult(url=url, content=answer)
    except Exception as e:
        return InteractResult(url=url, content="", success=False, error=f"LLM request failed: {e}")
