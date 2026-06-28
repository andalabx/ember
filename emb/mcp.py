"""MCP server. Connects ember to any MCP-compatible agent framework."""

from __future__ import annotations

import asyncio
import json

try:
    from fastmcp import FastMCP
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False


# Runs over stdio — compatible with Claude Code, Cursor, and any MCP client.
def start_mcp():
    if not _HAS_MCP:
        import sys
        print("MCP support requires: pip install ember-browser[mcp]", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("ember")

    @mcp.tool()
    def scrape(url: str) -> str:
        """Scrape a URL and return clean markdown."""
        from emb.scrape import scrape_markdown
        return scrape_markdown(url)

    @mcp.tool()
    def search_web(query: str, limit: int = 5) -> str:
        """Search the web and return results as markdown."""
        from emb.search import search
        results = search(query, limit=limit)
        return "\n".join(
            f"# {r.title}\n{r.url}\n{r.description}\n" for r in results
        ) or "No results."

    @mcp.tool()
    def crawl_site(url: str, max_pages: int = 20) -> str:
        """Crawl a website and return page content."""
        from emb.crawl import crawl
        max_pages = min(max(1, max_pages), 500)
        result = crawl(url, max_pages=max_pages)
        out = [f"Crawled {result.total} pages from {url}"]
        for p in result.pages:
            snippet = p.markdown[:500] + ("..." if len(p.markdown) > 500 else "")
            out.append(f"\n## {p.title or p.url}\n{snippet}")
        return "\n".join(out)

    @mcp.tool()
    def map_site(url: str) -> str:
        """Discover all URLs on a website."""
        from emb.map import map_url
        result = map_url(url)
        return f"Found {result.total} URLs:\n" + "\n".join(
            f"  {link}" for link in result.links[:50]
        )

    @mcp.tool()
    def batch_scrape(urls: str, concurrency: int = 5) -> str:
        """Scrape multiple URLs concurrently and return combined markdown.

        Pass urls as a newline-separated list (one URL per line, # = comment).
        concurrency controls how many fetches run in parallel (max 20).
        """
        from emb.scrape import scrape_url_async

        url_list = [
            u.strip() for u in urls.splitlines()
            if u.strip() and not u.startswith("#")
        ]
        if not url_list:
            return "No URLs provided."

        concurrency = min(max(1, concurrency), 20)

        async def _run() -> list:
            sem = asyncio.Semaphore(concurrency)
            async def _one(u: str):
                async with sem:
                    return await scrape_url_async(u)
            return list(await asyncio.gather(*[_one(u) for u in url_list]))

        results = asyncio.run(_run())

        ok = [r for r in results if r.success]
        fail = [r for r in results if not r.success]
        out = [f"Scraped {len(results)} URLs — {len(ok)} ok, {len(fail)} failed\n"]
        for r in ok:
            snippet = r.markdown[:500] + ("..." if len(r.markdown) > 500 else "")
            out.append(f"## {r.title or r.url}\nURL: {r.url}\n\n{snippet}\n")
        for r in fail:
            out.append(f"## ERROR: {r.url}\n{r.error}\n")
        return "\n".join(out)

    @mcp.tool()
    def interact_page(
        url: str,
        prompt: str = "",
        provider: str = "openai",
        model: str = "",
        timeout: int = 60,
    ) -> str:
        """Open a URL and perform browser actions using natural language.

        Requires an LLM provider when prompt is given.
        Without a prompt, returns page markdown.
        """
        timeout = min(max(1, timeout), 300)
        from emb.interact import interact
        result = interact(url, prompt=prompt, provider=provider, model=model, timeout=timeout)
        if not result.success:
            return f"Error: {result.error}"
        return result.content

    @mcp.tool()
    def extract_data(url: str, prompt: str = "") -> str:
        """Extract structured data from a URL using an LLM."""
        from emb.agent import extract
        result = extract(url, prompt=prompt)
        if "error" in result:
            return f"Error: {result['error']}"
        return json.dumps(result, indent=2)

    mcp.run(transport="stdio")
