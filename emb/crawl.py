"""Crawl a website. BFS with sitemap support."""

from __future__ import annotations

import logging
import time
from collections import deque
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from emb._url_validator import validate_url
from emb.scrape import _MIN_CONTENT_WORDS, _scrape_html, _scrape_lightpanda
from emb.types import CrawlPage, CrawlResult

_log = logging.getLogger(__name__)


def _sitemap_urls(
    url: str,
    client: httpx.Client,
    *,
    _visited: set[str] | None = None,
    _depth: int = 0,
) -> list[str]:
    if _visited is None:
        _visited = set()
    if _depth > 3 or url in _visited or len(_visited) > 50:
        return []
    _visited.add(url)
    try:
        resp = client.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml-xml")
        urls = []
        # Sitemap index: recurse into sub-sitemaps
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            if loc and loc.text:
                try:
                    validate_url(loc.text)
                except ValueError:
                    _log.debug("Skipping blocked sub-sitemap: %s", loc.text)
                    continue
                urls.extend(_sitemap_urls(loc.text, client, _visited=_visited, _depth=_depth + 1))
        # Regular sitemap: collect <url><loc> entries only
        for url_tag in soup.find_all("url"):
            loc = url_tag.find("loc")
            if loc and loc.text:
                loc_url = loc.text.strip()
                try:
                    validate_url(loc_url)
                    urls.append(loc_url)
                except ValueError:
                    _log.debug("Skipping blocked sitemap URL: %s", loc_url)
        return urls
    except Exception:
        return []


def _find_sitemaps(url: str, client: httpx.Client) -> list[str]:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
        f"{base}/sitemap/",
    ]
    try:
        resp = client.get(f"{base}/robots.txt", timeout=10)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:") and len(candidates) < 10:
                    candidate = line.split(":", 1)[1].strip()
                    try:
                        validate_url(candidate)
                        candidates.insert(0, candidate)
                    except ValueError:
                        _log.debug("Skipping blocked robots.txt sitemap: %s", candidate)
    except Exception:
        pass
    found = []
    for sm in candidates:
        try:
            if client.head(sm, timeout=5).status_code == 200:
                found.append(sm)
        except Exception:
            continue
    return found


# BFS. Sitemap pages seeded first, then links. One fetch per page covers
# both content extraction and link discovery.
def crawl(
    url: str,
    *,
    max_pages: int = 50,
    max_depth: int = 3,
    same_domain: bool = True,
    use_sitemap: bool = True,
    timeout: int = 30,
    delay: float = 0.0,
) -> CrawlResult:
    try:
        validate_url(url)
    except ValueError as e:
        return CrawlResult(url=url, success=False, error=str(e))

    parsed = urlparse(url)
    domain = parsed.netloc
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    pages: list[CrawlPage] = []

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        if use_sitemap:
            for sm in _find_sitemaps(url, client):
                for u in _sitemap_urls(sm, client):
                    if u not in visited:
                        queue.append((u, 0))
                        visited.add(u)

        if url not in visited:
            queue.appendleft((url, 0))
            visited.add(url)

        while queue and len(pages) < max_pages:
            page_url, depth = queue.popleft()
            if depth > max_depth:
                continue

            try:
                resp = client.get(page_url, timeout=timeout)
                if resp.status_code != 200:
                    _log.debug("Skipping %s: HTTP %d", page_url, resp.status_code)
                    continue
                html = resp.text
            except Exception as exc:
                _log.debug("Skipping %s: %s", page_url, exc)
                continue

            result = _scrape_html(page_url, html)
            if not result.success or len(result.markdown.split()) <= _MIN_CONTENT_WORDS:
                lp = _scrape_lightpanda(page_url, timeout)
                if lp.success:
                    result = lp
                elif not result.success:
                    continue

            links: list[str] = []
            if depth < max_depth:
                soup = BeautifulSoup(html, "lxml")
                for a in soup.find_all("a", href=True):
                    link = urljoin(page_url, a["href"])
                    p = urlparse(link)
                    if p.scheme not in ("http", "https"):
                        continue
                    if same_domain and p.netloc != domain:
                        continue
                    clean = link.split("#")[0]
                    # Use len(visited) as cap to account for failed pages
                    if clean and clean not in visited and len(visited) < max_pages * 4:
                        visited.add(clean)
                        queue.append((clean, depth + 1))
                        links.append(clean)

            pages.append(CrawlPage(url=page_url, markdown=result.markdown, title=result.title,
                                   links=links, depth=depth))

            if delay:
                time.sleep(delay)

    return CrawlResult(url=url, pages=pages, total=len(pages))
