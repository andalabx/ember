"""Shared types used across ember modules."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScrapeResult:
    url: str
    markdown: str
    title: str = ""
    description: str = ""
    screenshot: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


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
    error: Optional[str] = None


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


@dataclass
class InteractResult:
    url: str
    content: str
    screenshot: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
