"""Discover all URLs on a website. Reads sitemaps, falls back to link extraction."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ember.types import MapResult


def map_url(url: str, *, max_links: int = 500) -> MapResult:
    """List all discoverable URLs on a website.

    Tries sitemaps first. Falls back to extracting links from the homepage.

    Args:
        url: Website URL to map.
        max_links: Maximum links to return.
    """
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc
    discovered: set[str] = set()

    with httpx.Client(timeout=10, follow_redirects=True) as client:
        # Check robots.txt and common sitemap paths
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

        for sm_url in candidates:
            try:
                resp = client.get(sm_url, timeout=10)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "lxml-xml")
                for sm in soup.find_all("sitemap"):
                    loc = sm.find("loc")
                    if loc and loc.text:
                        inner = client.get(loc.text, timeout=10)
                        if inner.status_code == 200:
                            for tag in BeautifulSoup(inner.text, "lxml-xml").find_all("loc"):
                                if tag.text:
                                    discovered.add(tag.text.strip())
                for loc in soup.find_all("loc"):
                    if loc.text:
                        discovered.add(loc.text.strip())
                if len(discovered) >= max_links:
                    break
            except Exception:
                continue

    # Fallback: extract links from homepage
    if not discovered:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            try:
                resp = client.get(base, timeout=15)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    for a in soup.find_all("a", href=True):
                        link = urljoin(base, a["href"])
                        p = urlparse(link)
                        if p.scheme in ("http", "https") and p.netloc == domain:
                            discovered.add(link.split("#")[0])
            except Exception:
                pass

    links = sorted(discovered)[:max_links]
    return MapResult(url=url, links=links, total=len(links))
