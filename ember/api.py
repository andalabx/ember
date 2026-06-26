"""FastAPI server. Exposes every ember feature as an HTTP endpoint."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ember import __version__
from ember.agent import extract as agent_extract
from ember.crawl import crawl as do_crawl
from ember.interact import interact as do_interact
from ember.map import map_url
from ember.scrape import scrape_url
from ember.search import search

app = FastAPI(title="ember", version=__version__)


# ── Request models ──────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str = Field(..., description="URL to scrape")
    use_browser: Optional[bool] = Field(None, description="Force browser rendering")
    timeout: int = Field(30, ge=1, le=120)


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    limit: int = Field(5, ge=1, le=50)


class CrawlRequest(BaseModel):
    url: str = Field(..., description="URL to start from")
    max_pages: int = Field(50, ge=1, le=500)
    max_depth: int = Field(3, ge=1, le=10)


class MapRequest(BaseModel):
    url: str = Field(..., description="Website URL")
    max_links: int = Field(500, ge=1, le=5000)


class InteractRequest(BaseModel):
    url: str = Field(..., description="URL to open")
    prompt: str = Field("", description="Natural language action")
    timeout: int = Field(30, ge=1, le=120)


class ExtractRequest(BaseModel):
    url: str = Field(..., description="URL to extract from")
    prompt: str = Field("", description="What to extract")
    model: str = Field("gpt-4o-mini", description="LLM model")


# ── Endpoints ───────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "name": "ember",
        "version": __version__,
        "endpoints": {
            "POST /scrape": "Extract markdown from a URL",
            "POST /crawl": "Crawl a website",
            "POST /search": "Search the web",
            "POST /map": "Discover URLs on a site",
            "POST /interact": "Browser interaction",
            "POST /extract": "LLM-powered structured extraction",
            "GET /health": "Health check",
        },
    }


@app.post("/scrape")
def api_scrape(req: ScrapeRequest):
    result = scrape_url(req.url, use_browser=req.use_browser, timeout=req.timeout)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return {"url": result.url, "title": result.title, "markdown": result.markdown}


@app.post("/crawl")
def api_crawl(req: CrawlRequest):
    result = do_crawl(req.url, max_pages=req.max_pages, max_depth=req.max_depth)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return {
        "url": result.url,
        "total": result.total,
        "pages": [{"url": p.url, "title": p.title, "markdown": p.markdown, "depth": p.depth}
                  for p in result.pages],
    }


@app.post("/search")
def api_search(req: SearchRequest):
    try:
        results = search(req.query, limit=req.limit)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "query": req.query,
        "results": [{"url": r.url, "title": r.title, "description": r.description} for r in results],
    }


@app.post("/map")
def api_map(req: MapRequest):
    result = map_url(req.url, max_links=req.max_links)
    return {"url": result.url, "total": result.total, "links": result.links}


@app.post("/interact")
def api_interact(req: InteractRequest):
    result = do_interact(req.url, prompt=req.prompt, timeout=req.timeout)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return {"url": result.url, "content": result.content}


@app.post("/extract")
@app.post("/agent")
def api_extract(req: ExtractRequest):
    result = agent_extract(req.url, prompt=req.prompt, model=req.model)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


# ── Server entry point ──────────────────────────────────────────────

def start_server(host: str = "0.0.0.0", port: int = 51251):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
