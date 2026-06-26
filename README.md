# ember

Open source lightweight headless browser for AI agents.

```bash
pip install ember-browser

ember url https://example.com
ember search "AI agents"
ember serve
```

No Docker is required. No setup is needed. No API key is necessary to start.

---

## Why we built it

We needed our agents to browse the web, but faced some limitations.

Existing tools either required Docker, needed API keys for basic features, or shipped with a full Chromium browser that was 641 MB and too heavy to run on a normal machine.

So we built ember. It does what the heavy tools do but at a fraction of the cost. We optimized for:

- **Lightness:** ember idles at about 17 MB. You can run it on a laptop, on a VPS alongside other services, or on a Raspberry Pi.
- **Simplicity:** pip install ember-browser is all you need. No Docker, no config files, no accounts.
- **Smart defaults:** The tool decides for you whether a page needs a browser. You just give it a URL.
- **Lazy resources:** Nothing loads until you need it. The browser, the search engine, and the heavy dependencies all wait until they are called.
- **Free search:** DuckDuckGo is built in. No API key is needed and there are no rate limits.
- **Open source:** There is no vendor lock in, no surprise bills, and no data leaves your infrastructure.

The result is a browser for agents that actually fits where you are running your agents.

## Install

```bash
pip install ember-browser
```

Browser features like clicking, scrolling, and interacting auto install on first use. You do not have to do anything.

## What your agent can do with it

Read any page:

```bash
ember url https://en.wikipedia.org/wiki/Python
```

Search the web:

```bash
ember search "AI agents python"
```

Crawl a whole site:

```bash
ember crawl https://docs.example.com --max-pages 20
```

Discover every URL on a site:

```bash
ember map https://example.com
```

Control a page in plain English:

```bash
ember interact https://amazon.com --prompt "search for mechanical keyboard and tell me the first result price"
```

Extract structured data with an LLM:

```bash
export EMBER_LLM_API_KEY=***
ember extract https://example.com/pricing --prompt "list all plans and their prices"
```

Start the API:

```bash
ember serve
```

## How it works

Not every page needs a browser. Most are just HTML. Ember knows the difference.

For blogs, news, documentation, and most of the web, it uses trafilatura. That is a text extraction library that gets the content without spinning up a browser. It is fast and has zero memory overhead.

For sites with basic anti bot protection, it uses curl_cffi. That is TLS impersonation at the network level. Still no browser.

For JavaScript heavy pages, SPAs, and interactive content, it uses Lightpanda. That is a real browser engine built for machines not humans in Zig. It downloads the first time you need it and caches itself.

The browser only loads when the page actually needs it. Most requests never get past the first tier.

## Size

- Idle: about 17 MB of RAM
- Scraping a normal page: about 20 MB of RAM
- Running a full browser: about 140 MB of RAM

For comparison, Firecrawl needs 4 to 8 GB in Docker. Crawl4AI takes 140 MB or more just to import. We built ember to do more with less.

## For agent frameworks

Start the REST API with ember serve. It listens on port 51251 by default. Change it with `--port`.

```bash
ember serve
```

```bash
curl -X POST http://localhost:51251/scrape -H "Content-Type: application/json" -d '{"url": "https://example.com"}'
```

Endpoints include /scrape, /search, /crawl, /map, /interact, /extract, and /agent.

For MCP, add this to your configuration:

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

It works with Claude Code, OpenClaw, and anything that speaks MCP.

## Benchmarks

We ran ember against Crawl4AI across 29 URLs. The set included docs, news, blogs, ecommerce, tech, and government sites. We used the same machine, same network, and same timeout.

Ember imported at 48.5 MB. Crawl4AI imported at 171.8 MB.

Ember scraped with a 97% success rate. Crawl4AI got 90%. It could not handle Reuters, Amazon, or StackOverflow.

Ember browser binary is 20 MB using Lightpanda. Crawl4AI uses Chromium at 641 MB.

We used ember as the browser layer for an agent running the [GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA) benchmark. Ember successfully retrieved web content, searched for information, and fed results back for every question it was given.

## Environment variables

- **EMBER_LLM_API_KEY** with no default. This is the key for LLM extraction.
- **EMBER_LLM_BASE_URL** with a default of https://api.openai.com/v1. This is the LLM API endpoint.
- **EMBER_LLM_MODEL** with a default of gpt-4o-mini. This is the LLM model.
- **EMBER_LIGHTPANDA_PATH** with a default of lightpanda. This is the path to the browser binary.

## License

AGPL-3.0
