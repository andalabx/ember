from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScrapeResult:
    url: str
    markdown: str = ""
    title: str = ""
    description: str = ""
    screenshot: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


@dataclass
class CrawlPage:
    url: str
    markdown: str
    title: str = ""
    links: list[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class CrawlResult:
    url: str
    pages: list[CrawlPage] = field(default_factory=list)
    total: int = 0
    success: bool = True
    error: str | None = None


@dataclass
class SearchResult:
    url: str
    title: str
    description: str = ""


@dataclass
class MapResult:
    url: str
    links: list[str] = field(default_factory=list)
    total: int = 0
    error: str | None = None


@dataclass
class InteractResult:
    url: str
    content: str = ""
    screenshot: str | None = None
    success: bool = True
    error: str | None = None
