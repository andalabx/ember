<div align="center">

<pre>
  ███████╗███╗   ███╗██████╗ ███████╗██████╗ 
  ██╔════╝████╗ ████║██╔══██╗██╔════╝██╔══██╗
  █████╗  ██╔████╔██║██████╔╝█████╗  ██████╔╝
  ██╔══╝  ██║╚██╔╝██║██╔══██╗██╔══╝  ██╔══██╗
  ███████╗██║ ╚═╝ ██║██████╔╝███████╗██║  ██║
  ╚══════╝╚═╝     ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝
</pre>

**Open source, lightweight headless browser for AI agents.**

[![PyPI](https://img.shields.io/pypi/v/ember-browser)](https://pypi.org/project/ember-browser/)
[![Python](https://img.shields.io/pypi/pyversions/ember-browser)](https://pypi.org/project/ember-browser/)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

```bash
pip install ember-browser
```

*No Docker. No API key to start.*

</div>

---

## Why ember

Most web tools for agents ship with Chromium (641 MB) or require Docker just to get started. We needed something an agent could use on a VPS, a laptop, or a Raspberry Pi without thinking about it.

ember runs at ~17 MB idle. It decides whether a page needs a browser — you just pass it a URL.

|                     | ember              | Crawl4AI           |
|---------------------|--------------------|--------------------|
| Import footprint    | ~54 MB             | 171.8 MB           |
| Browser binary      | 20 MB (Lightpanda) | 641 MB (Chromium)  |
| Scrape success rate | ~85% (trafilatura) / ~95%+ (+ Lightpanda) | 90% |
| Docker required     | No                 | No                 |
| API key required    | No                 | No                 |

---

## Quick start

```bash
pip install ember-browser

ember                          # start the interactive session
ember url https://example.com  # or run a one-shot command
ember serve                    # start the REST API
```

---

## CLI

### Interactive session

`ember` with no arguments opens a persistent session. Commands and a save guide are shown on startup — no need to type `help` first.

```
  ███████╗███╗   ███╗██████╗ ███████╗██████╗
  ...
  ╚══════╝╚═╝     ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝

  v0.1.0  lightweight headless browser for AI agents

  url        <url>              scrape a page to markdown
  search     <query>            web search
  crawl      <url>              crawl a whole website
  map        <url>              discover all URLs on a site
  interact   <url>              control a browser with natural language
  extract    <url>              pull structured data with an LLM
  batch      <urls.txt>         scrape many URLs concurrently

  ─── saving results ───────────────────────────────────────────
  one result   url example.com -o page.md
  everything   output ./research/  then all results auto-save
  last result  save page.md        after any command

ember › url andausman.com
ember › save page.md

ember › output ./research/       # auto-save everything from here
ember/research › search "python asyncio" -n 10
ember/research › crawl docs.example.com
ember/research › output clear    # stop auto-saving
ember › quit
```

### One-shot commands

Every command works standalone too:

```bash
ember url https://example.com                         # scrape a page
ember search "AI agents python" -n 10                 # web search
ember crawl https://docs.example.com --max-pages 20   # crawl a site
ember map https://example.com                         # discover all URLs
ember interact https://amazon.com \
  --prompt "find a mechanical keyboard under $100"
ember extract https://example.com/pricing \
  --prompt "list all plans and prices as JSON"
```

### Saving results

All commands accept `-o` to save that run:

```bash
ember url https://example.com -o page.md
ember search "python" -o results.json
ember crawl https://docs.example.com -o ./pages/   # one .md per page
ember map https://example.com -o urls.txt
ember extract https://example.com -o data.json
```

Set a default save directory so you never need `-o`:

```bash
ember config --save-dir ./research/    # persists across sessions
ember config                           # show current settings
ember config --save-dir ""             # clear it
```

Or use an environment variable for the current shell:

```bash
EMBER_SAVE_DIR=./out ember url https://example.com
```

In a session, the three ways to save:

```
ember › url example.com -o page.md     # save just this run
ember › save page.md                   # save the last result
ember › output ./research/             # auto-save all results from now on
```

### Async batch scraping

```bash
# urls.txt — one URL per line, # = comment
ember batch urls.txt                      # 5 concurrent by default
ember batch urls.txt -c 20 -o ./pages/   # 20 parallel, save to dir
```

---

## Python API

```python
from emb.scrape import scrape_url, scrape_markdown
from emb.search import search
from emb.crawl import crawl
from emb.map import map_url

# Scrape a page → ScrapeResult
result = scrape_url("https://example.com")
print(result.markdown)   # full page content as markdown
print(result.title)      # page title
print(result.success)    # True / False

# Just the markdown text
md = scrape_markdown("https://example.com")

# Crawl a site
result = crawl("https://docs.example.com", max_pages=20, max_depth=3)
for page in result.pages:
    print(page.url, len(page.markdown))

# Discover URLs
result = map_url("https://example.com", max_links=100)
print(result.links)   # list[str]

# Search the web
results = search("python asyncio tutorial", limit=5)
for r in results:
    print(r.title, r.url)

# Browser interaction with natural language
from emb.interact import interact

result = interact("https://example.com", prompt="click the login button")
print(result.content)   # what the agent did / saw

# LLM-powered structured extraction
from emb.agent import extract

data = extract("https://example.com/pricing", prompt="list all plans and prices")
print(data)   # dict
```

### Async

```python
import asyncio
from emb.scrape import scrape_url_async

async def main():
    results = await asyncio.gather(
        scrape_url_async("https://example.com"),
        scrape_url_async("https://httpbin.org/get"),
    )
    for r in results:
        print(r.url, r.success)

asyncio.run(main())
```

---

## REST API

```bash
ember serve               # http://127.0.0.1:51251
ember serve --port 8080   # custom port

EMBER_API_KEY=your-secret ember serve   # require auth
```

```bash
curl -X POST http://localhost:51251/scrape \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret" \
  -d '{"url": "https://example.com"}'

curl -X POST http://localhost:51251/search \
  -H "Content-Type: application/json" \
  -d '{"query": "AI agents", "limit": 5}'

curl -X POST http://localhost:51251/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com", "max_pages": 10}'
```

Endpoints: `/scrape` `/search` `/crawl` `/map` `/interact` `/extract` `/agent` `/health`

---

## MCP

```json
{
  "mcpServers": {
    "ember": {
      "command": "ember",
      "args": ["mcp"]
    }
  }
}
```

Works with Claude Code, Cursor, and any MCP-compatible host.

Available tools: `scrape`, `search_web`, `crawl_site`, `map_site`, `batch_scrape`, `interact_page`, `extract_data`.

---

## How it works

Not every page needs a browser. ember knows the difference.

**Tier 1 — trafilatura** handles ~90% of the web: blogs, news, documentation, Wikipedia. Pure HTTP, no browser process, no memory overhead.

**Tier 2 — Lightpanda** handles JavaScript-heavy pages, SPAs, and interactive content. It's a real browser engine written in Zig, built for machines rather than humans — 20 MB total. ember downloads and caches it automatically on first use, and only falls back to it when tier 1 produces thin content.

Most requests never reach the browser.

### Memory footprint

| State                  | RAM     |
|------------------------|---------|
| Idle                   | ~17 MB  |
| Scraping a static page | ~20 MB  |
| Running the browser    | ~140 MB |

Firecrawl needs 4–8 GB in Docker. Crawl4AI imports at 171 MB before scraping anything. ember fits where your agent already runs.

---

## Environment variables

| Variable                  | Default                        | Description |
|---------------------------|--------------------------------|-------------|
| `EMBER_SAVE_DIR`          | _(none)_                       | Default directory for saved results. Overrides `ember config --save-dir` for the current shell. |
| `EMBER_API_KEY`           | _(none)_                       | Enables API key auth on the REST server (`X-API-Key` header). |
| `EMBER_PORT`              | `51251`                        | Default port for `ember serve`. Overridden by `--port` flag. |
| `EMBER_INTERACT_PROVIDER` | `openai`                       | LLM provider for `interact` (`openai`, `anthropic`, `ollama`, etc.). |
| `EMBER_LLM_API_KEY`       | _(none)_                       | API key for LLM-powered extraction. |
| `EMBER_LLM_BASE_URL`      | `https://api.openai.com/v1`    | LLM API endpoint for extraction. |
| `EMBER_LLM_MODEL`         | `gpt-4o-mini`                  | Model used by `extract`. |
| `EMBER_LIGHTPANDA_PATH`   | _(auto)_                       | Path to a custom Lightpanda binary. Skips auto-download if set. |

---

## License

[AGPL-3.0](LICENSE) — open source forever.
