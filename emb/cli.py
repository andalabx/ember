"""CLI entry point."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import shlex
import sys
import textwrap
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.tree import Tree

from emb import __version__

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # Enable VT processing so ANSI colours work in Windows Console / PowerShell 5.1
    try:
        import ctypes
        _k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        _k32.SetConsoleMode(_k32.GetStdHandle(-11), 7)   # stdout
        _k32.SetConsoleMode(_k32.GetStdHandle(-12), 7)   # stderr
    except Exception:
        pass

_BANNER = """
  [bold yellow]███████╗███╗   ███╗██████╗ ███████╗██████╗[/bold yellow]
  [bold yellow]██╔════╝████╗ ████║██╔══██╗██╔════╝██╔══██╗[/bold yellow]
  [bold orange1]█████╗  ██╔████╔██║██████╔╝█████╗  ██████╔╝[/bold orange1]
  [bold orange1]██╔══╝  ██║╚██╔╝██║██╔══██╗██╔══╝  ██╔══██╗[/bold orange1]
  [bold dark_orange]███████╗██║ ╚═╝ ██║██████╔╝███████╗██║  ██║[/bold dark_orange]
  [bold dark_orange3]╚══════╝╚═╝     ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝[/bold dark_orange3]
"""

console = Console(legacy_windows=False)

app = typer.Typer(
    name="ember",
    help="Open source, lightweight headless browser for AI agents.",
    no_args_is_help=False,
    invoke_without_command=True,
)


# ===========================================================================
# Config  (~/.config/ember/config.json  or  EMBER_SAVE_DIR env var)
# ===========================================================================

_CONFIG_PATH = Path.home() / ".config" / "ember" / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text()) if _CONFIG_PATH.exists() else {}
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _get_save_dir() -> Path | None:
    from_env = os.environ.get("EMBER_SAVE_DIR", "").strip()
    if from_env:
        return Path(from_env)
    from_cfg = _load_config().get("save_dir", "").strip()
    return Path(from_cfg) if from_cfg else None


# session_dir="" means the user cleared output in-session (disables auto-save).
# ext="" signals directory mode — caller creates the dir at the returned path.
def _resolve_save(
    explicit: str | None,
    cmd: str,
    ref: str,
    ext: str,
    session_dir: str | None = None,
) -> str | None:
    if explicit is not None:
        return explicit
    # Empty string signals "cleared in session"
    if session_dir == "":
        return None
    base = Path(session_dir) if session_dir else _get_save_dir()
    if base is None:
        return None
    parsed = urlparse(ref)
    slug = parsed.netloc or re.sub(r"[^\w\-]", "_", ref)[:40].strip("_") or cmd
    ts = datetime.datetime.now().strftime("%H%M%S")
    base.mkdir(parents=True, exist_ok=True)
    return str(base / f"{cmd}_{slug}_{ts}{ext}")


# ===========================================================================
# Shared display helpers
# ===========================================================================

def _err(msg: str, hint: str = "") -> None:
    console.print(f"\n  [red]✗[/red] {msg}")
    if hint:
        console.print(f"  [bright_black]hint: {hint}[/bright_black]")
    console.print()


def _ensure_scheme(url: str) -> str:
    if url and "://" not in url:
        url = f"https://{url}"
        console.print(f"  [bright_black]→ {url}[/bright_black]")
    return url


def _write(path_str: str, data: Any) -> None:
    p = Path(path_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".json" or isinstance(data, (dict, list)):
        text = json.dumps(data, indent=2, ensure_ascii=False) if not isinstance(data, str) else data
    else:
        text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
    p.write_text(text, encoding="utf-8")
    console.print(f"\n  [green]✓[/green] saved → [orange1]{p}[/orange1]  [bright_black]{len(text):,} chars[/bright_black]\n")


# Trafilatura turns multi-column layouts into pipe-delimited tables that render
# horribly in a narrow Rich panel — flatten them to readable prose before display.
def _clean_scraped_md(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        # Drop pure separator rows: |---|---| or |:--:|---|
        if s.startswith("|") and re.fullmatch(r"[|\s\-:]+", s):
            continue
        # Table data row: | a | b | c | → join non-empty cells with two spaces
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|") if c.strip()]
            if cells:
                out.append("  ".join(cells))
            continue
        # Inline || → two spaces (orphan pipes from partial table extraction)
        if "||" in line:
            line = re.sub(r"\s*\|\|\s*", "  ", line)
        out.append(line)
    # Collapse 3+ blank lines to 2
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _display_links(links: list[str], base_url: str) -> None:
    from collections import defaultdict

    base_host = urlparse(base_url).netloc
    groups: dict[str, list[str]] = defaultdict(list)

    for link in links:
        p = urlparse(link)
        if p.netloc and p.netloc != base_host:
            groups["[external]"].append(link)
            continue
        parts = p.path.strip("/").split("/")
        key = f"/{parts[0]}/" if parts[0] else "/"
        groups[key].append(link)

    _MAX = 6
    tree = Tree(f"[orange1]{base_host}[/orange1]  [bright_black]{len(links)} URLs[/bright_black]")
    for key in sorted(groups):
        urls = groups[key]
        n = len(urls)
        label = (
            f"[dim]{key}[/dim]  [bright_black]{n} URL{'s' if n != 1 else ''}[/bright_black]"
            if not key.startswith("[")
            else f"[bright_black]{key}  {n} URL{'s' if n != 1 else ''}[/bright_black]"
        )
        branch = tree.add(label)
        for u in urls[:_MAX]:
            short = u.replace(f"https://{base_host}", "").replace(f"http://{base_host}", "") or "/"
            branch.add(f"[bright_black]{short}[/bright_black]")
        if n > _MAX:
            branch.add(f"[dim]… {n - _MAX} more[/dim]")

    console.print()
    console.print(tree)
    console.print()


def _panel(body: str, title: str = "", subtitle: str = "") -> Panel:
    kw: dict = {"border_style": "dark_orange3", "padding": (1, 2)}
    if title:
        kw["title"] = title
    if subtitle:
        kw["subtitle"] = subtitle
    try:
        return Panel(Markdown(body), **kw)
    except Exception:
        return Panel(body, **kw)


# ===========================================================================
# Callback — no args → launch session
# ===========================================================================

@app.callback()
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        session()


# ===========================================================================
# ember config
# ===========================================================================

@app.command()
def config(
    save_dir: Optional[str] = typer.Option(None, "--save-dir", help="Default directory for saved results ('' to clear)"),
    reset: bool = typer.Option(False, "--reset", help="Reset all settings to defaults"),
):
    """Show or update ember configuration.

    Settings are stored in ~/.config/ember/config.json.
    The EMBER_SAVE_DIR environment variable overrides save_dir for the current shell.

    Examples:

      ember config                      # show current settings
      ember config --save-dir ./out/    # save all results here by default
      ember config --save-dir ""        # clear the default (stop auto-saving)
      ember config --reset              # wipe the config file
    """
    if reset:
        _save_config({})
        console.print(f"\n  [green]✓[/green] config reset  [bright_black]{_CONFIG_PATH}[/bright_black]\n")
        return

    cfg = _load_config()
    changed = False

    if save_dir is not None:
        if save_dir.strip() == "":
            cfg.pop("save_dir", None)
            console.print("  [bright_black]save_dir cleared — results will not be auto-saved[/bright_black]")
        else:
            cfg["save_dir"] = save_dir.strip()
        changed = True

    if changed:
        _save_config(cfg)
        console.print(f"\n  [green]✓[/green] saved → [orange1]{_CONFIG_PATH}[/orange1]\n")

    # Always show current effective settings
    env_dir = os.environ.get("EMBER_SAVE_DIR", "").strip()
    cfg_dir = cfg.get("save_dir", "").strip()
    effective = env_dir or cfg_dir

    console.print(f"\n  [bold]ember config[/bold]  [bright_black]{_CONFIG_PATH}[/bright_black]\n")
    if effective:
        src = "EMBER_SAVE_DIR" if env_dir else "config"
        console.print(f"  [dim]save_dir[/dim]  [orange1]{effective}[/orange1]  [bright_black]({src})[/bright_black]")
    else:
        console.print("  [dim]save_dir[/dim]  [bright_black](not set)[/bright_black]")
    console.print()


# ===========================================================================
# ember url
# ===========================================================================

@app.command(name="url")
def cmd_url(
    url: str = typer.Argument(..., help="URL to scrape"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save markdown to file (auto-named if save-dir is set)"),
    browser: bool = typer.Option(False, "--browser", "-b", help="Force Lightpanda browser"),
):
    """Scrape a URL and return clean markdown content."""
    from emb.scrape import scrape_url

    url = _ensure_scheme(url)
    with console.status(f"[dim]Fetching {url}[/dim]"):
        result = scrape_url(url, use_browser=True if browser else None)

    if not result.success:
        hint = (
            "try --browser to render JavaScript-heavy pages"
            if "extract" in (result.error or "").lower()
            else "private/localhost URLs are blocked for security"
            if "private" in (result.error or "").lower() or "SSRF" in (result.error or "")
            else ""
        )
        _err(result.error or "Unknown error", hint)
        raise typer.Exit(1)

    out = _resolve_save(save, "url", url, ".md")
    chars = f"[bright_black]{len(result.markdown):,} chars[/bright_black]"
    console.print(_panel(
        _clean_scraped_md(result.markdown),
        title=f"[bold]{result.title or url}[/bold]",
        subtitle=f"[dim]{result.url}[/dim]  {chars}",
    ))
    if out:
        _write(out, result.markdown)


# ===========================================================================
# ember search
# ===========================================================================

@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to .json or .txt"),
):
    """Search the web and display ranked results."""
    from emb.search import search as _search

    with console.status(f"[dim]Searching {query!r}[/dim]"):
        try:
            results = _search(query, limit=limit)
        except Exception as e:
            _err(str(e), "check your internet connection")
            raise typer.Exit(1)

    if not results:
        _err("No results found", "try a broader search query")
        raise typer.Exit(1)

    console.print(
        f"\n  [bold]Results for[/bold] [orange1]{query}[/orange1]"
        f"  [bright_black]{len(results)} found[/bright_black]\n"
    )
    for i, r in enumerate(results, 1):
        console.print(f"  [bold orange1]{i}[/bold orange1]  [bold]{r.title}[/bold]")
        console.print(f"     [dim]{r.url}[/dim]")
        if r.description:
            snippet = textwrap.shorten(r.description, width=max(60, console.width - 10), placeholder="…")
            console.print(f"     [bright_black]{snippet}[/bright_black]")
        console.print()

    out = _resolve_save(save, "search", query, ".json")
    if out:
        data = [{"title": r.title, "url": r.url, "description": r.description} for r in results]
        if Path(out).suffix.lower() == ".txt":
            _write(out, "\n\n".join(
                f"{i}. {r.title}\n   {r.url}\n   {r.description}" for i, r in enumerate(data, 1)
            ))
        else:
            _write(out, data)


# ===========================================================================
# ember crawl
# ===========================================================================

@app.command()
def crawl(
    url: str = typer.Argument(..., help="URL to start from"),
    max_pages: int = typer.Option(50, "--max-pages", "-n", help="Max pages"),
    max_depth: int = typer.Option(3, "--max-depth", "-d", help="Max depth"),
    delay: float = typer.Option(0.0, "--delay", "-w", help="Seconds between requests"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to dir/ or .json"),
):
    """Crawl a website and display its page tree."""
    from emb.crawl import crawl as _crawl

    url = _ensure_scheme(url)
    with console.status(f"[dim]Crawling {url}[/dim]"):
        result = _crawl(url, max_pages=max_pages, max_depth=max_depth, delay=delay)

    if not result.success:
        _err(result.error or "Crawl failed", "check the URL is reachable and publicly accessible")
        raise typer.Exit(1)
    if not result.pages:
        _err("No pages found", "try --max-depth 5 or check the domain")
        raise typer.Exit(1)

    tree = Tree(f"[orange1]{url}[/orange1]  [bright_black]{result.total} pages[/bright_black]")
    _nodes: dict[int, Any] = {-1: tree}
    for p in result.pages:
        parent = _nodes.get(p.depth - 1, tree)
        short_url = p.url if len(p.url) <= 60 else p.url[:57] + "…"
        label = f"[dim]{short_url}[/dim]"
        if p.title:
            label += f"  [bold]{p.title}[/bold]"
        label += f"  [bright_black]{len(p.markdown):,}c[/bright_black]"
        _nodes[p.depth] = parent.add(label)  # type: ignore[union-attr]

    console.print()
    console.print(tree)
    console.print()

    out = _resolve_save(save, "crawl", url, "")  # "" → directory mode
    if out:
        outp = Path(out)
        if outp.suffix.lower() == ".json":
            _write(out, {
                "url": result.url, "total": result.total,
                "pages": [{"url": p.url, "title": p.title, "depth": p.depth, "markdown": p.markdown}
                          for p in result.pages],
            })
        else:
            outp.mkdir(parents=True, exist_ok=True)
            for i, p in enumerate(result.pages):
                slug = p.url.replace("://", "_").replace("/", "_").replace("?", "_")[:80]
                (outp / f"{i:03d}_{slug}.md").write_text(
                    f"# {p.title or p.url}\n\nURL: {p.url}\n\n{p.markdown}", encoding="utf-8"
                )
            console.print(f"  [green]✓[/green] saved {result.total} pages → [orange1]{outp}/[/orange1]\n")


# ===========================================================================
# ember map
# ===========================================================================

@app.command()
def map(
    url: str = typer.Argument(..., help="Website URL"),
    max_links: int = typer.Option(500, "--max-links", "-n", help="Max links"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to .txt or .json"),
):
    """Discover all URLs on a website (sitemap + link extraction)."""
    from emb.map import map_url as _map

    url = _ensure_scheme(url)
    with console.status(f"[dim]Mapping {url}[/dim]"):
        result = _map(url, max_links=max_links)

    if result.error:
        _err(result.error, "add https:// or check the domain" if "scheme" in (result.error or "").lower()
             else "site may be unreachable or block crawlers")
        raise typer.Exit(1)
    if not result.links:
        _err("No URLs discovered", "site may have no sitemap — try: ember crawl " + url)
        raise typer.Exit(1)

    console.print(f"\n  Found [orange1]{result.total}[/orange1] URLs  [bright_black]{url}[/bright_black]\n")
    _display_links(result.links, url)

    out = _resolve_save(save, "map", url, ".txt")
    if out:
        if Path(out).suffix.lower() == ".json":
            _write(out, {"url": url, "total": result.total, "links": result.links})
        else:
            _write(out, "\n".join(result.links))


# ===========================================================================
# ember interact
# ===========================================================================

@app.command()
def interact(
    url: str = typer.Argument(..., help="URL to open"),
    prompt: str = typer.Option("", "--prompt", "-p", help="What to do on the page"),
    provider: str = typer.Option("openai", "--provider", help="LLM provider (openai, anthropic, ollama, ...)"),
    model: str = typer.Option("", "--model", "-m", help="Model name override"),
    timeout: int = typer.Option(60, "--timeout", "-t", help="Timeout in seconds"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save result to file"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip Lightpanda; use trafilatura + LLM (works on Windows)"),
):
    """Control a browser with natural language. Requires an LLM when --prompt is given."""
    from emb.interact import interact as _interact
    import platform as _platform

    url = _ensure_scheme(url)
    # Auto-apply no-browser on Windows (browser not available)
    use_browser = not no_browser and _platform.system() != "Windows"
    action = f"[dim]{prompt[:60]}[/dim]" if prompt else "[dim]loading page[/dim]"
    with console.status(f"  {action}"):
        result = _interact(url, prompt=prompt, provider=provider, model=model, timeout=timeout, use_browser=use_browser)

    if not result.success:
        err = result.error or ""
        _err(err, (
            "set EMBER_LLM_API_KEY or the provider's key env var" if "API_KEY" in err or "api_key" in err.lower()
            else "valid providers: openai, anthropic, gemini, ollama, llama_cpp" if "provider" in err.lower()
            else "Lightpanda browser is not yet available on this platform — use --no-browser" if "Lightpanda" in err
            else ""
        ))
        raise typer.Exit(1)

    if not result.content or not result.content.strip():
        _err("No content returned", "Try --no-browser to use trafilatura fallback")
        raise typer.Exit(1)

    console.print(_panel(result.content, title=f"[bold]{url}[/bold]"))
    out = _resolve_save(save, "interact", url, ".md")
    if out:
        _write(out, result.content)


# ===========================================================================
# ember extract
# ===========================================================================

@app.command()
def extract(
    url: str = typer.Argument(..., help="URL to extract from"),
    prompt: str = typer.Option("", "--prompt", "-p", help="What to extract"),
    model: str = typer.Option(
        os.environ.get("EMBER_LLM_MODEL", "gpt-4o-mini"),
        "--model", "-m",
        help="LLM model",
    ),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save result to file"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip Lightpanda; use trafilatura only (works on Windows)"),
):
    """Extract structured data from a page using an LLM."""
    from emb.agent import extract as _extract
    import platform as _platform

    url = _ensure_scheme(url)
    use_browser: bool | None = None if (not no_browser and _platform.system() != "Windows") else False
    with console.status(f"[dim]Extracting from {url}[/dim]"):
        result = _extract(url, prompt=prompt, model=model, use_browser=use_browser)

    if "error" in result:
        _err(result["error"], "set EMBER_LLM_API_KEY or OPENAI_API_KEY" if "key" in result["error"].lower() else "")
        raise typer.Exit(1)

    content = result.get("content") or result.get("markdown")
    if content:
        console.print(_panel(content))
        out = _resolve_save(save, "extract", url, ".json")
        if out:
            _write(out, content)
    else:
        console.print_json(json.dumps(result))
        out = _resolve_save(save, "extract", url, ".json")
        if out:
            _write(out, result)


# ===========================================================================
# ember batch  — async multi-URL scraping
# ===========================================================================

@app.command()
def batch(
    file: Path = typer.Argument(..., help="Text file — one URL per line, # lines are skipped"),
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Parallel requests"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to dir/ or .json"),
):
    """Scrape multiple URLs concurrently (async). Great for bulk jobs."""
    from emb.scrape import scrape_url_async

    if not file.exists():
        _err(f"File not found: {file}")
        raise typer.Exit(1)

    raw = file.read_text(encoding="utf-8").splitlines()
    urls = [_ensure_scheme(u.strip()) for u in raw if u.strip() and not u.startswith("#")]
    if not urls:
        _err("No URLs in file", "one URL per line — lines starting with # are comments")
        raise typer.Exit(1)

    async def _run() -> list:
        sem = asyncio.Semaphore(concurrency)
        async def _one(u: str):
            async with sem:
                return await scrape_url_async(u)
        return list(await asyncio.gather(*[_one(u) for u in urls]))

    with console.status(f"[dim]Scraping {len(urls)} URLs  (concurrency={concurrency})[/dim]"):
        results = asyncio.run(_run())

    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]

    console.print(f"\n  [orange1]{len(ok)}[/orange1] ok  [red]{len(fail)}[/red] failed  from [bold]{file.name}[/bold]\n")
    for r in ok:
        host = urlparse(r.url).netloc or r.url[:40]
        info = f"  [bright_black]{r.title}[/bright_black]" if r.title else ""
        console.print(f"  [green]✓[/green]  [dim]{host}[/dim]{info}  [bright_black]{len(r.markdown):,}c[/bright_black]")
    for r in fail:
        host = urlparse(r.url).netloc or r.url[:40]
        console.print(f"  [red]✗[/red]  [dim]{host}[/dim]  [red]{r.error}[/red]")
    console.print()

    out = _resolve_save(save, "batch", str(file), "")
    if out:
        outp = Path(out)
        if outp.suffix.lower() == ".json":
            _write(out, [
                {"url": r.url, "title": r.title, "success": r.success,
                 "markdown": r.markdown if r.success else None, "error": r.error}
                for r in results
            ])
        else:
            outp.mkdir(parents=True, exist_ok=True)
            for r in (r for r in results if r.success):
                slug = r.url.replace("://", "_").replace("/", "_").replace("?", "_")[:80]
                (outp / f"{slug}.md").write_text(
                    f"# {r.title or r.url}\n\nURL: {r.url}\n\n{r.markdown}", encoding="utf-8"
                )
            console.print(f"  [green]✓[/green] saved {len(ok)} pages → [orange1]{outp}/[/orange1]\n")


# ===========================================================================
# ember session — interactive REPL
# ===========================================================================

_SESSION_HELP = """\

  [bold]Commands[/bold]

  [orange1]url[/orange1] <url> [-o file] [-b]             scrape a page
  [orange1]search[/orange1] <query> [-n 5] [-o file]      web search
  [orange1]crawl[/orange1] <url> [-n 50] [-d 3] [-o path] crawl a site
  [orange1]map[/orange1] <url> [-o file]                  discover all URLs
  [orange1]interact[/orange1] <url> [-p "..."] [-o file]  browser + LLM
  [orange1]extract[/orange1] <url> [-p "..."] [-o file]   LLM data extraction
  [orange1]batch[/orange1] <urls.txt> [-c 5] [-o path]    async multi-URL scrape

  [orange1]save[/orange1] <file>          write the last result to a specific file
  [orange1]output[/orange1] <dir>         show or change the auto-save directory
  [orange1]output clear[/orange1]         stop auto-saving this session
  [orange1]help[/orange1]                 show this message
  [orange1]quit[/orange1]                 exit

  When [orange1]output[/orange1] is set, every command auto-saves without needing [orange1]-o[/orange1].
  Pass [orange1]-o[/orange1] on any command to override just that run.\
"""

_FLAG_ALIASES: dict[str, str] = {
    "-o": "save", "--save": "save",
    "-n": "n", "--limit": "n", "--max-pages": "n", "--max-links": "n",
    "-d": "d", "--max-depth": "d",
    "-c": "c", "--concurrency": "c",
    "-b": "b", "--browser": "b",
    "-p": "p", "--prompt": "p",
    "-m": "model", "--model": "model",
    "-t": "t", "--timeout": "t",
    "--provider": "provider",
}


def _parse_flags(parts: list[str]) -> tuple[list[str], dict[str, Any]]:
    positional: list[str] = []
    flags: dict[str, Any] = {}
    i = 0
    while i < len(parts):
        p = parts[i]
        if p in _FLAG_ALIASES:
            key = _FLAG_ALIASES[p]
            if key == "b":
                flags["b"] = True
                i += 1
            elif i + 1 < len(parts):
                flags[key] = parts[i + 1]
                i += 2
            else:
                i += 1
        else:
            positional.append(p)
            i += 1
    return positional, flags


def _ses_resolve(flags: dict, cmd: str, ref: str, ext: str, state: dict) -> str | None:
    return _resolve_save(flags.get("save"), cmd, ref, ext, session_dir=state.get("save_dir"))


def _ses_prompt(state: dict) -> str:
    sd = state.get("save_dir")
    if sd is None:
        g = _get_save_dir()
        sd = str(g) if g else None
    if sd:
        name = Path(sd).name or sd
        return f"  [orange1]ember[/orange1][bright_black]/{name} ›[/bright_black] "
    return "  [orange1]ember[/orange1] [bright_black]›[/bright_black] "


def _session_run(line: str, state: dict) -> dict:
    try:
        parts = shlex.split(line)
    except ValueError as e:
        _err(f"Parse error: {e}")
        return state

    if not parts:
        return state

    cmd, rest = parts[0].lower(), parts[1:]

    # ---- meta ----
    if cmd in ("help", "?", "h"):
        console.print(_SESSION_HELP)
        return state

    if cmd in ("quit", "exit", "q"):
        raise SystemExit(0)

    if cmd in ("clear", "cls"):
        console.clear()
        return state

    if cmd == "save":
        if not rest:
            _err("Usage: save <file>"); return state
        last = state.get("last", {})
        if not last:
            _err("Nothing to save yet — run a command first"); return state
        _write(rest[0], last["data"])
        return state

    if cmd == "output":
        if not rest:
            current = state.get("save_dir")
            if current is None:
                g = _get_save_dir()
                current = str(g) if g else None
            if current:
                console.print(f"\n  output [orange1]{current}[/orange1]\n")
            else:
                console.print("\n  [bright_black]output not set — use 'output <dir>' to configure[/bright_black]\n")
                sd = _get_save_dir()
                if sd:
                    console.print(f"  [bright_black]global default from config: {sd}[/bright_black]\n")
            return state
        if rest[0].lower() in ("clear", "none", "off", "--clear"):
            state = {**state, "save_dir": ""}  # "" = explicitly cleared
            console.print("  [bright_black]output cleared — results won't be auto-saved this session[/bright_black]\n")
        else:
            d = rest[0]
            Path(d).mkdir(parents=True, exist_ok=True)
            state = {**state, "save_dir": d}
            console.print(f"\n  [green]✓[/green] output → [orange1]{d}[/orange1]  [bright_black](all results auto-saved here)[/bright_black]\n")
        return state

    # ---- url ----
    if cmd == "url":
        if not rest:
            _err("Usage: url <url> [-o file] [-b]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.scrape import scrape_url
        with console.status(f"[dim]Fetching {url}[/dim]"):
            r = scrape_url(url, use_browser=True if flags.get("b") else None)
        if not r.success:
            _err(r.error or "Failed", "try -b to use the browser"); return state
        console.print(_panel(_clean_scraped_md(r.markdown),
                             title=f"[bold]{r.title or url}[/bold]",
                             subtitle=f"[dim]{url}[/dim]  [bright_black]{len(r.markdown):,}c[/bright_black]"))
        out = _ses_resolve(flags, "url", url, ".md", state)
        if out:
            _write(out, r.markdown)
        return {**state, "last": {"data": r.markdown, "meta": {"url": url, "title": r.title}}}

    # ---- search ----
    if cmd == "search":
        if not rest:
            _err("Usage: search <query> [-n 5] [-o file]"); return state
        pos, flags = _parse_flags(rest)
        query = " ".join(pos)
        from emb.search import search as _search
        with console.status(f"[dim]Searching {query!r}[/dim]"):
            try:
                results = _search(query, limit=int(flags.get("n", 5)))
            except Exception as e:
                _err(str(e)); return state
        if not results:
            _err("No results", "try a broader query"); return state
        console.print(f"\n  [bold]Results for[/bold] [orange1]{query}[/orange1]  [bright_black]{len(results)} found[/bright_black]\n")
        for i, r in enumerate(results, 1):
            console.print(f"  [bold orange1]{i}[/bold orange1]  [bold]{r.title}[/bold]")
            console.print(f"     [dim]{r.url}[/dim]")
            if r.description:
                snippet = textwrap.shorten(r.description, width=max(60, console.width - 10), placeholder="…")
                console.print(f"     [bright_black]{snippet}[/bright_black]")
            console.print()
        data = [{"title": r.title, "url": r.url, "description": r.description} for r in results]
        out = _ses_resolve(flags, "search", query, ".json", state)
        if out:
            _write(out, data if Path(out).suffix.lower() != ".txt" else
                   "\n\n".join(f"{i}. {r['title']}\n   {r['url']}\n   {r['description']}" for i, r in enumerate(data, 1)))
        return {**state, "last": {"data": data, "meta": {"query": query}}}

    # ---- crawl ----
    if cmd == "crawl":
        if not rest:
            _err("Usage: crawl <url> [-n 50] [-d 3] [-o path]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.crawl import crawl as _crawl
        with console.status(f"[dim]Crawling {url}[/dim]"):
            r = _crawl(url, max_pages=int(flags.get("n", 50)), max_depth=int(flags.get("d", 3)))
        if not r.success:
            _err(r.error or "Crawl failed"); return state
        tree = Tree(f"[orange1]{url}[/orange1]  [bright_black]{r.total} pages[/bright_black]")
        _nodes: dict[int, Any] = {-1: tree}
        for p in r.pages:
            parent = _nodes.get(p.depth - 1, tree)
            short_url = p.url if len(p.url) <= 60 else p.url[:57] + "…"
            lbl = f"[dim]{short_url}[/dim]"
            if p.title:
                lbl += f"  [bold]{p.title}[/bold]"
            lbl += f"  [bright_black]{len(p.markdown):,}c[/bright_black]"
            _nodes[p.depth] = parent.add(lbl)  # type: ignore[union-attr]
        console.print()
        console.print(tree)
        console.print()
        pages = [{"url": p.url, "title": p.title, "depth": p.depth, "markdown": p.markdown} for p in r.pages]
        out = _ses_resolve(flags, "crawl", url, "", state)
        if out:
            outp = Path(out)
            if outp.suffix.lower() == ".json":
                _write(out, {"url": url, "total": r.total, "pages": pages})
            else:
                outp.mkdir(parents=True, exist_ok=True)
                for i, p in enumerate(r.pages):
                    slug = p.url.replace("://", "_").replace("/", "_").replace("?", "_")[:80]
                    (outp / f"{i:03d}_{slug}.md").write_text(
                        f"# {p.title or p.url}\n\nURL: {p.url}\n\n{p.markdown}", encoding="utf-8")
                console.print(f"  [green]✓[/green] saved {r.total} pages → [orange1]{outp}/[/orange1]\n")
        return {**state, "last": {"data": pages, "meta": {"url": url, "total": r.total}}}

    # ---- map ----
    if cmd == "map":
        if not rest:
            _err("Usage: map <url> [-o file]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.map import map_url as _map
        with console.status(f"[dim]Mapping {url}[/dim]"):
            r = _map(url, max_links=int(flags.get("n", 500)))
        if r.error:
            _err(r.error, "add https:// or check the domain"); return state
        if not r.links:
            _err("No URLs found", "try: crawl " + url); return state
        console.print(f"\n  Found [orange1]{r.total}[/orange1] URLs  [bright_black]{url}[/bright_black]\n")
        _display_links(r.links, url)
        out = _ses_resolve(flags, "map", url, ".txt", state)
        if out:
            _write(out, {"url": url, "total": r.total, "links": r.links}
                   if Path(out).suffix.lower() == ".json" else "\n".join(r.links))
        return {**state, "last": {"data": r.links, "meta": {"url": url, "total": r.total}}}

    # ---- interact ----
    if cmd == "interact":
        if not rest:
            _err("Usage: interact <url> [-p 'prompt'] [-o file]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.interact import interact as _interact
        prompt = flags.get("p", "")
        with console.status(f"[dim]{prompt[:60] or 'loading page'}[/dim]"):
            r = _interact(url, prompt=prompt, provider=flags.get("provider", "openai"),
                          model=flags.get("model", ""), timeout=int(flags.get("t", 60)))
        if not r.success:
            _err(r.error or "Failed"); return state
        if not r.content or not r.content.strip():
            _err("No content", "Lightpanda not available — try: url " + url); return state
        console.print(_panel(r.content, title=f"[bold]{url}[/bold]"))
        out = _ses_resolve(flags, "interact", url, ".md", state)
        if out:
            _write(out, r.content)
        return {**state, "last": {"data": r.content, "meta": {"url": url}}}

    # ---- extract ----
    if cmd == "extract":
        if not rest:
            _err("Usage: extract <url> [-p 'what to extract'] [-o file]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.agent import extract as _extract
        with console.status(f"[dim]Extracting from {url}[/dim]"):
            r = _extract(url, prompt=flags.get("p", ""), model=flags.get("model", "gpt-4o-mini"))
        if "error" in r:
            _err(r["error"]); return state
        content = r.get("content") or r.get("markdown") or json.dumps(r, indent=2)
        console.print(_panel(content))
        out = _ses_resolve(flags, "extract", url, ".json", state)
        if out:
            _write(out, content)
        return {**state, "last": {"data": content, "meta": {"url": url}}}

    # ---- batch ----
    if cmd == "batch":
        if not rest:
            _err("Usage: batch <urls.txt> [-c 5] [-o path]"); return state
        pos, flags = _parse_flags(rest)
        f = Path(pos[0])
        if not f.exists():
            _err(f"File not found: {f}"); return state
        from emb.scrape import scrape_url_async
        raw = f.read_text(encoding="utf-8").splitlines()
        urls = [_ensure_scheme(u.strip()) for u in raw if u.strip() and not u.startswith("#")]
        if not urls:
            _err("No URLs in file"); return state
        conc = int(flags.get("c", 5))

        async def _run() -> list:
            sem = asyncio.Semaphore(conc)
            async def _one(u: str):
                async with sem:
                    return await scrape_url_async(u)
            return list(await asyncio.gather(*[_one(u) for u in urls]))

        with console.status(f"[dim]Scraping {len(urls)} URLs (concurrency={conc})[/dim]"):
            batch_results = asyncio.run(_run())

        ok = [r for r in batch_results if r.success]
        fail = [r for r in batch_results if not r.success]
        console.print(f"\n  [orange1]{len(ok)}[/orange1] ok  [red]{len(fail)}[/red] failed\n")
        for r in ok:
            host = urlparse(r.url).netloc or r.url[:40]
            info = f"  [bright_black]{r.title}[/bright_black]" if r.title else ""
            console.print(f"  [green]✓[/green]  [dim]{host}[/dim]{info}  [bright_black]{len(r.markdown):,}c[/bright_black]")
        for r in fail:
            host = urlparse(r.url).netloc or r.url[:40]
            console.print(f"  [red]✗[/red]  [dim]{host}[/dim]  [red]{r.error}[/red]")
        console.print()
        data = [{"url": r.url, "title": r.title, "success": r.success,
                 "markdown": r.markdown if r.success else None, "error": r.error}
                for r in batch_results]
        out = _ses_resolve(flags, "batch", str(f), "", state)
        if out:
            outp = Path(out)
            if outp.suffix.lower() == ".json":
                _write(out, data)
            else:
                outp.mkdir(parents=True, exist_ok=True)
                for r in (r for r in batch_results if r.success):
                    slug = r.url.replace("://", "_").replace("/", "_").replace("?", "_")[:80]
                    (outp / f"{slug}.md").write_text(
                        f"# {r.title or r.url}\n\nURL: {r.url}\n\n{r.markdown}", encoding="utf-8")
                console.print(f"  [green]✓[/green] saved {len(ok)} pages → [orange1]{outp}/[/orange1]\n")
        return {**state, "last": {"data": data, "meta": {"total": len(urls), "ok": len(ok)}}}

    _err(f"Unknown command: {cmd!r}", "type 'help' for available commands")
    return state


@app.command()
def session():
    """Start an interactive ember session — run any command, auto-save results."""
    console.print(_BANNER)
    console.print(f"  [bold]v{__version__}[/bold]  [bright_black]lightweight headless browser for AI agents[/bright_black]\n")

    # Command quick-reference
    cmds = [
        ("url",      "<url>",          "scrape a page to markdown"),
        ("search",   "<query>",        "web search"),
        ("crawl",    "<url>",          "crawl a whole website"),
        ("map",      "<url>",          "discover all URLs on a site"),
        ("interact", "<url>",          "control a browser with natural language"),
        ("extract",  "<url>",          "pull structured data with an LLM"),
        ("batch",    "<urls.txt>",     "scrape many URLs concurrently"),
    ]
    for name, arg, desc in cmds:
        console.print(f"  [orange1]{name:<10}[/orange1] [dim]{arg:<18}[/dim] [bright_black]{desc}[/bright_black]")
    console.print()
    console.print("  [dark_orange3]─── saving results ───────────────────────────────────────────[/dark_orange3]")
    console.print("  [dim]one result [/dim] [orange1]url example.com -o page.md[/orange1]")
    console.print("  [dim]everything [/dim] [orange1]output ./research/[/orange1]  [bright_black]then all results auto-save[/bright_black]")
    console.print("  [dim]last result[/dim] [orange1]save page.md[/orange1]        [bright_black]after any command[/bright_black]")

    # Show configured output dir if set
    global_dir = _get_save_dir()
    if global_dir:
        console.print(f"\n  [green]✓[/green] [bright_black]auto-save on → {global_dir}  (change with 'output <dir>')[/bright_black]")
    console.print()

    # save_dir=None means "use global config"; "" means "cleared this session"
    state: dict = {"last": {}, "save_dir": None}

    # Enable readline on platforms that support it — gives arrow keys, history, Ctrl+L
    try:
        import readline as _rl
        _rl.parse_and_bind("tab: complete")
    except ImportError:
        pass

    while True:
        try:
            console.print(_ses_prompt(state), end="", highlight=False)
            console.file.flush()
            try:
                line = input()
            except EOFError:
                break
            # Ctrl+L sends form-feed (\x0c) on terminals without readline
            if "\x0c" in line:
                console.clear()
                line = line.replace("\x0c", "").strip()
                if not line:
                    continue
            line = line.strip()
            if not line:
                continue
            state = _session_run(line, state)
        except SystemExit:
            break
        except KeyboardInterrupt:
            console.print("\n  [bright_black](Ctrl+C — type quit to exit)[/bright_black]")

    console.print("\n  [bright_black]bye[/bright_black]\n")


# ===========================================================================
# ember serve / mcp / version
# ===========================================================================

@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(
        int(os.environ.get("EMBER_PORT", "51251")),
        "--port", "-p",
        help="Port (default 51251, overridden by EMBER_PORT env var)",
    ),
):
    """Start the REST API server."""
    from emb.api import start_server
    console.print(f"\n  [bold]ember[/bold] API  [orange1]http://{host}:{port}[/orange1]\n")
    start_server(host=host, port=port)


@app.command()
def mcp():
    """Start the MCP server for agent frameworks."""
    from emb.mcp import start_mcp
    start_mcp()


@app.command()
def version():
    """Show version."""
    console.print(f"  ember [orange1]v{__version__}[/orange1]")
