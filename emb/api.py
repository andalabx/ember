from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from emb import __version__
from emb._url_validator import validate_url
from emb.agent import extract as agent_extract
from emb.crawl import crawl as do_crawl
from emb.interact import interact as do_interact
from emb.map import map_url
from emb.scrape import scrape_url
from emb.search import search

app = FastAPI(title="ember", version=__version__)

_API_KEY = os.environ.get("EMBER_API_KEY", "")

if not _API_KEY:
    print(
        "WARNING: EMBER_API_KEY is not set. The API server is open to any caller. "
        "Set EMBER_API_KEY to require authentication.",
        file=sys.stderr,
    )


@app.middleware("http")
async def _auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.url.path in ("/", "/health"):
        return await call_next(request)
    if _API_KEY:
        key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(key, _API_KEY):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


def _safe_url(url: str) -> str:
    try:
        validate_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return url


class ScrapeRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="URL to scrape")
    use_browser: bool | None = Field(None, description="Force browser rendering")
    timeout: int = Field(30, ge=1, le=120)


class SearchRequest(BaseModel):
    query: str = Field(..., max_length=500, description="Search query")
    limit: int = Field(5, ge=1, le=50)


class CrawlRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="URL to start from")
    max_pages: int = Field(50, ge=1, le=500)
    max_depth: int = Field(3, ge=1, le=10)
    timeout: int = Field(30, ge=1, le=300)
    delay: float = Field(0.0, ge=0.0, le=10.0, description="Seconds between requests")


class MapRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="Website URL")
    max_links: int = Field(500, ge=1, le=5000)


class InteractRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="URL to open")
    prompt: str = Field("", description="Natural language action")
    provider: Literal[
        "openai", "anthropic", "gemini", "mistral",
        "huggingface", "vercel", "ollama", "llama_cpp"
    ] = Field("openai", description="LLM provider")
    model: str = Field("", max_length=128, description="Model name override")
    timeout: int = Field(60, ge=1, le=300)


class ExtractRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="URL to extract from")
    prompt: str = Field("", description="What to extract")
    model: str = Field("gpt-4o-mini", max_length=128, description="LLM model")


@app.get("/")
def root() -> dict[str, Any]:
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
            "POST /agent": "Alias for /extract",
            "GET /health": "Health check",
        },
    }


@app.post("/scrape")
def api_scrape(req: ScrapeRequest) -> dict[str, Any]:
    _safe_url(req.url)
    result = scrape_url(req.url, use_browser=req.use_browser, timeout=req.timeout)
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error)
    return {"url": result.url, "title": result.title, "markdown": result.markdown}


@app.post("/crawl")
def api_crawl(req: CrawlRequest) -> dict[str, Any]:
    _safe_url(req.url)
    result = do_crawl(
        req.url,
        max_pages=req.max_pages,
        max_depth=req.max_depth,
        timeout=req.timeout,
        delay=req.delay,
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error)
    return {
        "url": result.url,
        "total": result.total,
        "pages": [{"url": p.url, "title": p.title, "markdown": p.markdown, "depth": p.depth}
                  for p in result.pages],
    }


@app.post("/search")
def api_search(req: SearchRequest) -> dict[str, Any]:
    try:
        results = search(req.query, limit=req.limit)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "query": req.query,
        "results": [{"url": r.url, "title": r.title, "description": r.description} for r in results],
    }


@app.post("/map")
def api_map(req: MapRequest) -> dict[str, Any]:
    _safe_url(req.url)
    result = map_url(req.url, max_links=req.max_links)
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    return {"url": result.url, "total": result.total, "links": result.links}


@app.post("/interact")
def api_interact(req: InteractRequest) -> dict[str, Any]:
    _safe_url(req.url)
    result = do_interact(req.url, prompt=req.prompt, provider=req.provider, model=req.model, timeout=req.timeout)
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error)
    return {"url": result.url, "content": result.content}


@app.post("/extract")
@app.post("/agent")
def api_extract(req: ExtractRequest) -> dict[str, Any]:
    _safe_url(req.url)
    result = agent_extract(req.url, prompt=req.prompt, model=req.model)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


def start_server(host: str = "127.0.0.1", port: int = 51251) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port)
