"""Discover all URLs on a website. Reads sitemaps, falls back to link extraction."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from emb._url_validator import validate_url
from emb.types import MapResult

_log = logging.getLogger(__name__)


def map_url(url: str, *, max_links: int = 500, timeout: int = 15) -> MapResult:
    try:
        validate_url(url)
    except ValueError as e:
        return MapResult(url=url, links=[], total=0, error=str(e))

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc
    discovered: set[str] = set()

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        # Check robots.txt and common sitemap paths
        candidates = [
            f"{base}/sitemap.xml",
            f"{base}/sitemap_index.xml",
            f"{base}/sitemap/",
        ]
        try:
            resp = client.get(f"{base}/robots.txt", timeout=timeout)
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

        for sm_url in candidates:
            try:
                resp = client.get(sm_url, timeout=timeout)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "lxml-xml")
                # Sitemap index: recurse into sub-sitemaps (capped at 10)
                sub_count = 0
                for sm in soup.find_all("sitemap"):
                    if sub_count >= 10:
                        break
                    loc = sm.find("loc")
                    if loc and loc.text:
                        try:
                            validate_url(loc.text)
                        except ValueError:
                            _log.debug("Skipping blocked sub-sitemap: %s", loc.text)
                            continue
                        inner = client.get(loc.text, timeout=timeout)
                        if inner.status_code == 200:
                            for tag in BeautifulSoup(inner.text, "lxml-xml").find_all("url"):
                                loc_tag = tag.find("loc")
                                if loc_tag and loc_tag.text:
                                    loc_url = loc_tag.text.strip()
                                    try:
                                        validate_url(loc_url)
                                        discovered.add(loc_url)
                                    except ValueError:
                                        _log.debug("Skipping blocked sitemap URL: %s", loc_url)
                        sub_count += 1
                # Regular sitemap: collect <url><loc> entries only
                for url_tag in soup.find_all("url"):
                    loc = url_tag.find("loc")
                    if loc and loc.text:
                        loc_url = loc.text.strip()
                        try:
                            validate_url(loc_url)
                            discovered.add(loc_url)
                        except ValueError:
                            _log.debug("Skipping blocked sitemap URL: %s", loc_url)
                if len(discovered) >= max_links:
                    break
            except Exception:
                continue

        # Fallback: extract links from homepage
        if not discovered:
            try:
                resp = client.get(base, timeout=timeout)
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
