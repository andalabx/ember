"""MCP server. Connects ember to any MCP-compatible agent framework."""

from __future__ import annotations

import json

try:
    from mcp.server import FastMCP
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False


def start_mcp():
    """Start the MCP server over stdio.

    Compatible with Claude Code, OpenClaw, and any MCP client.
    Each ember feature becomes a tool the agent can call.
    """
    if not _HAS_MCP:
        print("MCP support requires: pip install mcp")
        return

    mcp = FastMCP("ember")

    @mcp.tool()
    def scrape_url(url: str) -> str:
        """Scrape a URL and return clean markdown."""
        from ember.scrape import scrape_markdown
        return scrape_markdown(url)

    @mcp.tool()
    def search_web(query: str, limit: int = 5) -> str:
        """Search the web and return results."""
        from ember.search import search
        results = search(query, limit=limit)
        return "\n".join(
            f"# {r.title}\n{r.url}\n{r.description}\n" for r in results
        ) or "No results."

    @mcp.tool()
    def crawl_site(url: str, max_pages: int = 20) -> str:
        """Crawl a website and return page content."""
        from ember.crawl import crawl
        result = crawl(url, max_pages=max_pages)
        out = [f"Crawled {result.total} pages from {url}"]
        for p in result.pages[:10]:
            out.append(f"\n## {p.title or p.url}\n{p.markdown[:500]}...")
        return "\n".join(out)

    @mcp.tool()
    def map_site(url: str) -> str:
        """Discover all URLs on a website."""
        from ember.map import map_url
        result = map_url(url)
        return f"Found {result.total} URLs:\n" + "\n".join(f"  {l}" for l in result.links[:50])

    @mcp.tool()
    def extract_data(url: str, prompt: str = "") -> str:
        """Extract structured data from a URL using an LLM."""
        from ember.agent import extract
        result = extract(url, prompt=prompt)
        if "error" in result:
            return f"Error: {result['error']}"
        return json.dumps(result, indent=2)

    mcp.run(transport="stdio")
