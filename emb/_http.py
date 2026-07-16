from __future__ import annotations

from urllib.parse import urljoin

import httpx

from emb._url_validator import validate_url

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 10


def _next_redirect_url(response: httpx.Response) -> str | None:
    location = response.headers.get("location", "").strip()
    if response.status_code not in _REDIRECT_STATUS_CODES or not location:
        return None
    return urljoin(str(response.url), location)


def safe_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    timeout: int | float | None = None,
) -> httpx.Response:
    current_url = url
    request_method = getattr(client, method.lower(), None)
    for _ in range(_MAX_REDIRECTS + 1):
        validate_url(current_url)
        if request_method is not None:
            response = request_method(current_url, timeout=timeout, follow_redirects=False)
        else:
            response = client.request(method, current_url, timeout=timeout, follow_redirects=False)
        next_url = _next_redirect_url(response)
        if next_url is None:
            return response
        current_url = next_url
    raise httpx.TooManyRedirects(f"Too many redirects while fetching {url}")


async def safe_request_async(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    timeout: int | float | None = None,
) -> httpx.Response:
    current_url = url
    request_method = getattr(client, method.lower(), None)
    for _ in range(_MAX_REDIRECTS + 1):
        validate_url(current_url)
        if request_method is not None:
            response = await request_method(current_url, timeout=timeout, follow_redirects=False)
        else:
            response = await client.request(method, current_url, timeout=timeout, follow_redirects=False)
        next_url = _next_redirect_url(response)
        if next_url is None:
            return response
        current_url = next_url
    raise httpx.TooManyRedirects(f"Too many redirects while fetching {url}")


def safe_get(
    client: httpx.Client,
    url: str,
    *,
    timeout: int | float | None = None,
) -> httpx.Response:
    return safe_request(client, "GET", url, timeout=timeout)


async def safe_get_async(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: int | float | None = None,
) -> httpx.Response:
    return await safe_request_async(client, "GET", url, timeout=timeout)


def safe_head(
    client: httpx.Client,
    url: str,
    *,
    timeout: int | float | None = None,
) -> httpx.Response:
    return safe_request(client, "HEAD", url, timeout=timeout)
