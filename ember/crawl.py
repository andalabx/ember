"""Crawl a website. BFS with sitemap support."""

from __future__ import annotations

from collections import deque
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ember.scrape import scrape_url
from ember.types import CrawlPage, CrawlResult


def _sitemap_urls(url: str, client: httpx.Client) -> list[str]:
    """Extract URLs from a sitemap. Handles sitemap index files."""
    try:
        resp = client.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml-xml")
        urls = []
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            if loc and loc.text:
                urls.extend(_sitemap_urls(loc.text, client))
        for loc in soup.find_all("loc"):
            if loc.text:
                urls.append(loc.text.strip())
        return urls
    except Exception:
        return []


def _find_sitemaps(url: str, client: httpx.Client) -> list[str]:
    """Discover sitemaps from robots.txt and common paths."""
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
                if line.lower().startswith("sitemap:"):
                    candidates.insert(0, line.split(":", 1)[1].strip())
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


def crawl(
    url: str,
    *,
    max_pages: int = 50,
    max_depth: int = 3,
    same_domain: bool = True,
    use_sitemap: bool = True,
    timeout: int = 30,
) -> CrawlResult:
    """Crawl a website starting from URL.

    BFS crawl. Sitemap pages discovered first, then links.
    Each page scraped with the same smart backend (trafilatura → browser).
    """
    parsed = urlparse(url)
    domain = parsed.netloc
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    pages: list[CrawlPage] = []

    if use_sitemap:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            for sm in _find_sitemaps(url, client):
                for u in _sitemap_urls(sm, client):
                    if u not in visited and len(pages) < max_pages:
                        queue.append((u, 0))
                        visited.add(u)

    if url not in visited:
        queue.appendleft((url, 0))
        visited.add(url)

    while queue and len(pages) < max_pages:
        page_url, depth = queue.popleft()
        if depth > max_depth:
            continue
        result = scrape_url(page_url, timeout=timeout)
        if not result.success:
            continue

        links: list[str] = []
        if depth < max_depth:
            try:
                resp = httpx.get(page_url, timeout=10, follow_redirects=True)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    for a in soup.find_all("a", href=True):
                        link = urljoin(page_url, a["href"])
                        p = urlparse(link)
                        if p.scheme not in ("http", "https"):
                            continue
                        if same_domain and p.netloc != domain:
                            continue
                        clean = link.split("#")[0]
                        if clean and clean not in visited:
                            visited.add(clean)
                            if len(pages) + len(queue) < max_pages:
                                queue.append((clean, depth + 1))
                                links.append(clean)
            except Exception:
                pass

        pages.append(CrawlPage(url=page_url, markdown=result.markdown, title=result.title,
                               links=links, depth=depth))

    return CrawlResult(url=url, pages=pages, total=len(pages))
