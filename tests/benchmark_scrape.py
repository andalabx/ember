# Run with: python tests/benchmark_scrape.py

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table
from rich import box

from emb.scrape import scrape_url

# fmt: off
URLS: list[tuple[str, str]] = [
    # Static HTML / news
    ("https://www.bbc.com/news",                         "news/static"),
    ("https://www.reuters.com",                          "news/static"),
    ("https://apnews.com",                               "news/static"),
    ("https://www.theguardian.com/international",        "news/static"),
    ("https://ycombinator.com",                          "homepage/static"),

    # Wikipedia
    ("https://en.wikipedia.org/wiki/Python_(programming_language)", "wiki"),
    ("https://en.wikipedia.org/wiki/Large_language_model",          "wiki"),

    # Developer docs
    ("https://docs.python.org/3/library/asyncio.html",  "docs/static"),
    ("https://fastapi.tiangolo.com",                    "docs/static"),
    ("https://docs.anthropic.com/en/docs/overview",     "docs/static"),

    # Blogs / articles
    ("https://paulgraham.com/greatwork.html",           "blog/static"),
    ("https://simonwillison.net",                       "blog/static"),
    ("https://overreacted.io",                          "blog/static"),

    # GitHub
    ("https://github.com/anthropics/anthropic-sdk-python", "github"),
    ("https://github.com/encode/httpx",                    "github"),

    # Academic / PDFs
    ("https://arxiv.org/abs/2601.22156",                "academic/html"),
    ("https://arxiv.org/pdf/2601.22156",                "academic/pdf"),
    ("https://arxiv.org/abs/1706.03762",                "academic/html"),

    # Government / institutional
    ("https://www.who.int/news-room/fact-sheets/detail/obesity-and-overweight", "institutional"),
    ("https://www.nasa.gov/missions/artemis",           "institutional"),

    # JS-heavy / SPA (likely to need browser)
    ("https://react.dev/learn",                         "spa/docs"),
    ("https://nextjs.org/docs",                         "spa/docs"),
    ("https://tailwindcss.com/docs/installation",       "spa/docs"),

    # Paywalls (expected fail or thin content)
    ("https://www.nytimes.com",                         "paywall"),
    ("https://www.wsj.com",                             "paywall"),

    # Redirects / edge cases
    ("https://t.co",                                    "redirect"),
    ("https://httpbin.org/html",                        "simple-html"),
    ("https://example.com",                             "simple-html"),
    ("https://en.m.wikipedia.org/wiki/Web_scraping",   "mobile-wiki"),
    ("https://hacker-news.firebaseio.com/v0/item/1.json", "json-api"),
]
# fmt: on


@dataclass
class BenchmarkResult:
    url: str
    category: str
    success: bool
    words: int
    elapsed: float
    error: str


def run() -> None:
    console = Console()
    results: list[BenchmarkResult] = []

    console.print("\n[bold orange1]ember scrape benchmark[/bold orange1]", justify="center")
    console.print(f"[dim]Testing {len(URLS)} URLs — trafilatura path (use_browser=False)[/dim]\n")

    for url, category in URLS:
        short = url[8:50] + ("…" if len(url) > 58 else "")
        console.print(f"[dim]> {short}[/dim]", end="\r")
        t0 = time.perf_counter()
        r = scrape_url(url, use_browser=False, timeout=20)
        elapsed = time.perf_counter() - t0
        words = len(r.markdown.split()) if r.markdown else 0
        results.append(BenchmarkResult(url, category, r.success, words, elapsed, r.error or ""))

    console.print(" " * 70, end="\r")  # clear progress line

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold orange1")
    table.add_column("URL", max_width=48, no_wrap=True)
    table.add_column("Category", max_width=16)
    table.add_column("OK", justify="center", width=4)
    table.add_column("Words", justify="right", width=7)
    table.add_column("Time", justify="right", width=6)
    table.add_column("Error", max_width=30, no_wrap=True)

    for r in results:
        ok_mark = "[green]Y[/green]" if r.success else "[red]N[/red]"
        words_str = str(r.words) if r.success else "[dim]-[/dim]"
        time_str = f"{r.elapsed:.1f}s"
        error_str = f"[dim]{r.error[:40]}[/dim]" if r.error else ""
        short_url = r.url[8:50] + ("…" if len(r.url) > 58 else "")
        table.add_row(short_url, r.category, ok_mark, words_str, time_str, error_str)

    console.print(table)

    passed = sum(1 for r in results if r.success)
    total = len(results)
    pct = passed / total * 100
    color = "green" if pct >= 90 else "yellow" if pct >= 75 else "red"
    avg_words = sum(r.words for r in results if r.success) // max(passed, 1)
    avg_time = sum(r.elapsed for r in results) / total

    console.print(f"[bold {color}]Success rate: {passed}/{total} ({pct:.0f}%)[/bold {color}]")
    console.print(f"[dim]Avg words (passing): {avg_words}  |  Avg time: {avg_time:.1f}s[/dim]\n")

    # Category breakdown
    cats: dict[str, list[bool]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r.success)
    console.print("[bold]By category:[/bold]")
    for cat, outcomes in sorted(cats.items()):
        p = sum(outcomes)
        t = len(outcomes)
        bar = "[green]Y[/green]" * p + "[red]N[/red]" * (t - p)
        console.print(f"  {cat:<20} {bar}  {p}/{t}")
    console.print()


if __name__ == "__main__":
    run()
