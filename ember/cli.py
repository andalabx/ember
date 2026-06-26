"""CLI entry point."""

from __future__ import annotations

import json
import sys

import typer

from ember import __version__

app = typer.Typer(
    name="ember",
    help="Open source, lightweight headless browser for AI agents. pip install ember-browser",
    no_args_is_help=True,
)


@app.command(name="url")
def cmd_url(
    url: str = typer.Argument(..., help="URL to scrape"),
):
    """Scrape a URL and return clean content."""
    from ember.scrape import scrape_url
    result = scrape_url(url)
    if not result.success:
        print(f"Error: {result.error}", file=sys.stderr)
        raise typer.Exit(1)
    if result.title:
        print(f"# {result.title}\n")
    print(result.markdown)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
):
    """Search the web."""
    from ember.search import search as _search
    results = _search(query, limit=limit)
    print(f"Search results for: {query}\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.title}")
        print(f"   {r.url}")
        if r.description:
            print(f"   {r.description[:200]}")
        print()


@app.command()
def crawl(
    url: str = typer.Argument(..., help="URL to start from"),
    max_pages: int = typer.Option(50, "--max-pages", "-n", help="Max pages"),
    max_depth: int = typer.Option(3, "--max-depth", "-d", help="Max depth"),
):
    """Crawl a website."""
    from ember.crawl import crawl as _crawl
    result = _crawl(url, max_pages=max_pages, max_depth=max_depth)
    print(f"Crawled {result.total} pages from {url}")
    for p in result.pages:
        prefix = "  " * p.depth + "└── " if p.depth > 0 else "  "
        print(f"{prefix}{p.url} ({len(p.markdown)} chars)")


@app.command()
def map(
    url: str = typer.Argument(..., help="Website URL"),
    max_links: int = typer.Option(500, "--max-links", "-n", help="Max links"),
):
    """Discover all URLs on a website."""
    from ember.map import map_url as _map
    result = _map(url, max_links=max_links)
    print(f"Found {result.total} URLs on {url}")
    for link in result.links:
        print(f"  {link}")


@app.command()
def interact(
    url: str = typer.Argument(..., help="URL to open"),
    prompt: str = typer.Option("", "--prompt", "-p", help="What to do"),
    timeout: int = typer.Option(30, "--timeout", "-t", help="Timeout"),
):
    """Control a browser with natural language."""
    from ember.interact import interact as _interact
    result = _interact(url, prompt=prompt, timeout=timeout)
    if not result.success:
        print(f"Error: {result.error}", file=sys.stderr)
        raise typer.Exit(1)
    print(result.content)


@app.command()
def extract(
    url: str = typer.Argument(..., help="URL to extract from"),
    prompt: str = typer.Option("", "--prompt", "-p", help="What to extract"),
    model: str = typer.Option("gpt-4o-mini", "--model", "-m", help="LLM model"),
):
    """Extract structured data using an LLM."""
    from ember.agent import extract as _extract
    result = _extract(url, prompt=prompt, model=model)
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        raise typer.Exit(1)
    if "content" in result:
        print(result["content"])
    elif "markdown" in result:
        print(result["markdown"])
    else:
        print(json.dumps(result, indent=2))


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind address"),
    port: int = typer.Option(51251, "--port", "-p", help="Port"),
):
    """Start the API server."""
    from ember.api import start_server
    start_server(host=host, port=port)


@app.command()
def mcp():
    """Start the MCP server for agent frameworks."""
    from ember.mcp import start_mcp
    start_mcp()


@app.command()
def version():
    """Show version."""
    print(f"ember v{__version__}")
