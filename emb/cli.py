from __future__ import annotations

import asyncio
import datetime
import html
import json
import os
import re
import shlex
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional
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
    # Enable VT on older Windows terminals.
    try:
        import ctypes
        _k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        _k32.SetConsoleMode(_k32.GetStdHandle(-11), 7)   # stdout
        _k32.SetConsoleMode(_k32.GetStdHandle(-12), 7)   # stderr
    except Exception:
        pass

_BANNER = (
    "  [bold yellow]███████╗███╗   ███╗██████╗ ███████╗██████╗[/bold yellow]\n"
    "  [bold yellow]██╔════╝████╗ ████║██╔══██╗██╔════╝██╔══██╗[/bold yellow]\n"
    "  [bold orange1]█████╗  ██╔████╔██║██████╔╝█████╗  ██████╔╝[/bold orange1]\n"
    "  [bold orange1]██╔══╝  ██║╚██╔╝██║██╔══██╗██╔══╝  ██╔══██╗[/bold orange1]\n"
    "  [bold dark_orange]███████╗██║ ╚═╝ ██║██████╔╝███████╗██║  ██║[/bold dark_orange]\n"
    "  [bold dark_orange3]╚══════╝╚═╝     ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝[/bold dark_orange3]\n"
)

console = Console(legacy_windows=False)

app = typer.Typer(
    name="ember",
    help="Lightweight headless browser for scraping, site discovery, and page automation.",
    no_args_is_help=False,
    invoke_without_command=True,
)
browser_app = typer.Typer(help="Manage the Lightpanda browser runtime.")
app.add_typer(browser_app, name="browser")


# Config

_CONFIG_PATH = Path.home() / ".config" / "ember" / "config.json"
_DEFAULT_SESSION_SAVE_DIR = Path("ember_results")


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
    if from_cfg:
        return Path(from_cfg)
    return _DEFAULT_SESSION_SAVE_DIR


# session_dir="" turns off auto-save.
# ext="" means directory mode.
def _resolve_save(
    explicit: str | None,
    cmd: str,
    ref: str,
    ext: str,
    session_dir: str | None = None,
) -> str | None:
    if explicit is not None:
        return explicit
    # Empty string turns auto-save off.
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


# Display helpers

def _err(msg: str, hint: str = "") -> None:
    console.print(f"  [red]✗[/red] {_clean_error(msg)}")
    if hint:
        console.print(f"  [bright_black]hint: {hint}[/bright_black]")


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
    console.print(f"  [green]✓[/green] saved → [orange1]{p}[/orange1]  [bright_black]{len(text):,} chars[/bright_black]")


# Clean markdown for display.
def _display_markdown(text: str) -> str:
    return _clean_scraped_md(text)


def _trim(text: str, limit: int = 72) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def _short_ref(ref: str, base_url: str = "", limit: int = 72) -> str:
    parsed = urlparse(ref)
    if not parsed.scheme and not parsed.netloc:
        return _trim(ref, limit)

    base_host = urlparse(base_url).netloc if base_url else ""
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    if parsed.fragment:
        path += f"#{parsed.fragment}"

    if base_host and parsed.netloc == base_host:
        label = path
    elif parsed.netloc:
        label = parsed.netloc if path == "/" else f"{parsed.netloc}{path}"
    else:
        label = ref

    return _trim(label, limit)


def _clean_error(msg: str, fallback: str = "request failed") -> str:
    text = re.sub(r"\s+", " ", msg or "").strip()
    if text.endswith(":"):
        text = text[:-1].rstrip()
    if text.lower() in {"fetch", "browser", "extract"}:
        text = ""
    return text or fallback


def _clean_scraped_md(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        # Drop table separator rows.
        if s.startswith("|") and re.fullmatch(r"[|\s\-:]+", s):
            continue
        # Join table cells into plain text.
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|") if c.strip()]
            if cells:
                out.append("  ".join(cells))
            continue
        # Clean orphan table pipes.
        if "||" in line:
            line = re.sub(r"\s*\|\|\s*", "  ", line)
        out.append(line)
    # Keep spacing tight.
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
            short = _short_ref(u, base_url)
            branch.add(f"[white]{short}[/white]")
        if n > _MAX:
            branch.add(f"[dim]… {n - _MAX} more[/dim]")

    console.print(tree)


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


_SESSION_BROWSE: list[tuple[str, str]] = [
    ("url example.com", "scrape one page"),
    ("search openai api", "search the web"),
    ("crawl example.com", "scrape a whole site"),
    ("map example.com", "list site URLs"),
    ("batch urls.txt", "scrape URLs from a file"),
]

_SESSION_LLM: list[tuple[str, str]] = [
    ("interact example.com -p \"summarize\"", "control a page with AI"),
    ("extract example.com -p \"title, pricing\"", "pull data with AI"),
]

_SESSION_ACTIONS: list[tuple[str, str]] = [
    ("save page.md", "save the last result"),
    ("output ./research", "auto-save next results"),
    ("output clear", "turn off auto-save"),
    ("help", "show the full guide"),
    ("quit", "exit"),
]

_SESSION_ADMIN: list[tuple[str, str]] = [
    ("browser status", "show browser runtime status"),
    ("browser install", "download Lightpanda now"),
    ("browser clear", "remove cached browser"),
    ("config", "show current config"),
    ("config --save-dir ./out", "set default save folder"),
    ("version", "show ember version"),
    ("serve", "start the REST API"),
    ("mcp", "start the MCP server"),
]


def _format_example(example: str, width: int = 54) -> str:
    cmd, sep, rest = example.partition(" ")
    if not sep:
        return f"[orange1]{cmd:<{width}}[/orange1]"
    return f"[orange1]{cmd}[/orange1] [white]{rest:<{width - len(cmd) - 1}}[/white]"


def _print_help_row(example: str, desc: str) -> None:
    console.print(f"  {_format_example(example)} [white]{desc}[/white]")


def _print_session_quickstart() -> None:
    console.print("  [bold yellow]Quick Start[/bold yellow]")
    _print_help_row("url example.com", "scrape one page")
    _print_help_row("search openai api", "search the web")
    _print_help_row('interact example.com -p "summarize"', "control a page with AI")
    _print_help_row("output ./research", "change auto-save folder")
    _print_help_row("help", "show the full guide")
    _print_help_row("quit", "exit")


def _print_session_help() -> None:
    console.print("  [bold yellow]Browse[/bold yellow]")
    for example, desc in _SESSION_BROWSE:
        _print_help_row(example, desc)
    console.print()
    console.print("  [bold yellow]AI[/bold yellow]")
    for example, desc in _SESSION_LLM:
        _print_help_row(example, desc)
    console.print()
    console.print("  [bold yellow]Session[/bold yellow]")
    for example, desc in _SESSION_ACTIONS:
        _print_help_row(example, desc)
    console.print()
    console.print("  [bold yellow]Outside Session[/bold yellow]")
    for example, desc in _SESSION_ADMIN:
        _print_help_row(example, desc)
    console.print()
    console.print("  [bold yellow]Saving[/bold yellow]")
    _print_help_row("url example.com -o page.md", "save one result now")
    _print_help_row("ember_results/", "default CLI save folder")
    _print_help_row("output ./research", "auto-save future results")
    _print_help_row("EMBER_SAVE_DIR=./out", "set shell-only default")


def _print_session_home(state: dict | None = None) -> None:
    console.print(_BANNER)
    console.print(f"  [bold]v{__version__}[/bold]  [white]lightweight headless browser for AI agents[/white]")
    console.print()
    _print_session_quickstart()

    current = None
    if state is not None:
        session_dir = state.get("save_dir")
        if session_dir == "":
            current = ""
        elif session_dir:
            current = str(session_dir)
    if current is None:
        global_dir = _get_save_dir()
        current = str(global_dir) if global_dir else None

    if current:
        console.print()
        console.print(f"  [green]✓[/green] [white]auto-save on → {current}[/white]  [bright_black](change with 'output <dir>')[/bright_black]")
    console.print()


def _print_result(body: str, title: str = "", subtitle: str = "") -> None:
    if title:
        console.print(f"\n  [bold]{title}[/bold]")
    if subtitle:
        console.print(f"  [white]{subtitle}[/white]")
    if title or subtitle:
        console.print()
    try:
        console.print(Markdown(body))
    except Exception:
        console.print(body)


def _browser_step_message(event: str, data: dict[str, Any]) -> str | None:
    if event == "download_needed":
        size = data.get("size_text") or "browser package"
        return (
            f"Browser mode needed once. Pausing work to set up Lightpanda "
            f"({size})..."
        )
    if event == "download_progress":
        percent = data.get("percent")
        downloaded = data.get("downloaded_text") or "0 B"
        total = data.get("total_text") or "?"
        speed = data.get("speed_text") or "0 B/s"
        if percent is None:
            return f"Downloading Lightpanda... {downloaded} at {speed}"
        return f"Downloading Lightpanda... {percent}% ({downloaded} / {total}, {speed})"
    if event == "verifying":
        return "Verifying Lightpanda download..."
    if event == "ready":
        return "Browser ready. Resuming work..."
    return None


def _print_browser_status(info: dict[str, Any]) -> None:
    source = info.get("source") or "not installed"
    source_map = {
        "env": "EMBER_LIGHTPANDA_PATH",
        "path": "PATH",
        "cache": "cache",
        "not installed": "not installed",
    }
    size_bytes = info.get("download_size_bytes")
    size_text = ""
    if isinstance(size_bytes, int) and size_bytes > 0:
        size_text = f"{size_bytes / (1024 * 1024):.1f} MiB"

    console.print("\n  [bold]browser[/bold]\n")
    if info.get("available"):
        console.print("  [green]✓[/green] [white]ready[/white]")
        console.print(f"  [bright_black]source:[/bright_black] [white]{source_map.get(source, source)}[/white]")
        console.print(f"  [bright_black]path:[/bright_black] [orange1]{info['path']}[/orange1]")
    else:
        console.print("  [yellow]![/yellow] [white]not ready[/white]")
        console.print(f"  [bright_black]source:[/bright_black] [white]{source_map.get(source, source)}[/white]")
    console.print(
        f"  [bright_black]platform:[/bright_black] "
        f"[white]{info['platform']} {info['machine']}[/white]"
    )
    console.print(f"  [bright_black]cache:[/bright_black] [white]{info['cache_path']}[/white]")
    if size_text:
        console.print(f"  [bright_black]first download:[/bright_black] [white]{size_text}[/white]")
    if info.get("error"):
        console.print(f"  [red]×[/red] {info['error']}")
    if info.get("hint"):
        console.print(f"  [bright_black]hint:[/bright_black] {info['hint']}")
    console.print()


def _run_with_steps(fn: Callable[[], Any], steps: list[str], interval: float = 0.8) -> Any:
    from emb import _browser as _browser_mod

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}
    browser_state: dict[str, Any] = {"message": "", "clear_at": 0.0}

    def _worker() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:
            error["value"] = exc

    def _browser_progress(event: str, data: dict[str, Any]) -> None:
        message = _browser_step_message(event, data)
        if message:
            browser_state["message"] = message
            browser_state["clear_at"] = time.monotonic() + 0.9 if event == "ready" else 0.0

    with _browser_mod.report_progress(_browser_progress):
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        index = 0
        next_tick = time.monotonic()
        with console.status(f"[white]{steps[0]}[/white]") as status:
            while thread.is_alive():
                now = time.monotonic()
                clear_at = browser_state.get("clear_at", 0.0)
                if clear_at and now >= clear_at:
                    browser_state["message"] = ""
                    browser_state["clear_at"] = 0.0
                message = browser_state.get("message")
                if message:
                    status.update(f"[white]{message}[/white]")
                elif now >= next_tick:
                    status.update(f"[white]{steps[index % len(steps)]}[/white]")
                    index += 1
                    next_tick = now + interval
                thread.join(timeout=0.1)

    if "value" in error:
        raise error["value"]
    return result.get("value")


# Default command

@app.callback()
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        session()


# Config command

@app.command(help="Show or update ember config.")
def config(
    save_dir: Optional[str] = typer.Option(None, "--save-dir", help="Default directory for saved results"),
    clear_save_dir: bool = typer.Option(False, "--clear-save-dir", help="Clear the saved default directory"),
    reset: bool = typer.Option(False, "--reset", help="Reset all settings to defaults"),
):
    if reset:
        _save_config({})
        console.print(f"\n  [green]✓[/green] config reset  [bright_black]{_CONFIG_PATH}[/bright_black]\n")
        return

    cfg = _load_config()
    changed = False

    if clear_save_dir and save_dir is not None:
        _err("Choose either --save-dir or --clear-save-dir, not both")
        raise typer.Exit(1)

    if clear_save_dir:
        cfg.pop("save_dir", None)
        console.print("  [bright_black]save_dir cleared - results will not be auto-saved[/bright_black]")
        changed = True

    if save_dir is not None:
        if save_dir.strip() == "":
            cfg.pop("save_dir", None)
            console.print("  [bright_black]save_dir cleared - results will not be auto-saved[/bright_black]")
        else:
            cfg["save_dir"] = save_dir.strip()
        changed = True

    if changed:
        _save_config(cfg)
        console.print(f"\n  [green]✓[/green] saved → [orange1]{_CONFIG_PATH}[/orange1]\n")

    # Show current settings.
    env_dir = os.environ.get("EMBER_SAVE_DIR", "").strip()
    cfg_dir = cfg.get("save_dir", "").strip()
    default_dir = str(_DEFAULT_SESSION_SAVE_DIR)
    effective = env_dir or cfg_dir or default_dir

    console.print(f"\n  [bold]ember config[/bold]  [bright_black]{_CONFIG_PATH}[/bright_black]\n")
    if effective:
        src = "EMBER_SAVE_DIR" if env_dir else "config" if cfg_dir else "default"
        console.print(f"  [dim]save_dir[/dim]  [orange1]{effective}[/orange1]  [bright_black]({src})[/bright_black]")
    else:
        console.print("  [dim]save_dir[/dim]  [bright_black](not set)[/bright_black]")
    console.print()


# Url command

@app.command(name="url", help="Scrape one page into clean markdown.")
def cmd_url(
    url: str = typer.Argument(..., help="URL to scrape"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save markdown to file (auto-named if save-dir is set)"),
    browser: bool = typer.Option(False, "--browser", "-b", help="Force Lightpanda browser"),
):
    from emb.scrape import scrape_url

    url = _ensure_scheme(url)
    result = _run_with_steps(
        lambda: scrape_url(url, use_browser=True if browser else None),
        [
            f"Working on {url}",
            "Fetching page...",
            "Reading content...",
            "Extracting clean text...",
            "Putting it together...",
        ],
    )

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
    chars = f"{len(result.markdown):,} chars"
    _print_result(
        _display_markdown(result.markdown),
        title=result.title or url,
        subtitle=f"{result.url}  {chars}",
    )
    if out:
        _write(out, result.markdown)


# Search command

@app.command(help="Search the web and show ranked results.")
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to .json or .txt"),
):
    from emb.search import search as _search

    try:
        results = _run_with_steps(
            lambda: _search(query, limit=limit),
            [
                f"Searching for {query!r}",
                "Finding sources...",
                "Ranking results...",
                "Putting it together...",
            ],
        )
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
        console.print(f"     [white]{r.url}[/white]")
        if r.description:
            snippet = textwrap.shorten(r.description, width=max(60, console.width - 10), placeholder="…")
            console.print(f"     [white]{snippet}[/white]")
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


# Crawl command

@app.command(help="Scrape many pages from one site.")
def crawl(
    url: str = typer.Argument(..., help="URL to start from"),
    max_pages: int = typer.Option(50, "--max-pages", "-n", help="Max pages"),
    max_depth: int = typer.Option(3, "--max-depth", "-d", help="Max depth"),
    delay: float = typer.Option(0.0, "--delay", "-w", help="Seconds between requests"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to dir/ or .json"),
):
    from emb.crawl import crawl as _crawl

    url = _ensure_scheme(url)
    result = _run_with_steps(
        lambda: _crawl(url, max_pages=max_pages, max_depth=max_depth, delay=delay),
        [
            f"Working on {url}",
            "Fetching pages...",
            "Following links...",
            "Collecting content...",
            "Putting it together...",
        ],
        interval=1.0,
    )

    if not result.success:
        _err(result.error or "Crawl failed", "check the URL is reachable and publicly accessible")
        raise typer.Exit(1)
    if not result.pages:
        _err("No pages found", "try --max-depth 5 or check the domain")
        raise typer.Exit(1)

    base_host = urlparse(url).netloc or url
    tree = Tree(f"[orange1]{base_host}[/orange1]  [bright_black]{result.total} {_plural(result.total, 'page')}[/bright_black]")
    _nodes: dict[int, Any] = {-1: tree}
    for p in result.pages:
        parent = _nodes.get(p.depth - 1, tree)
        label = f"[white]{_short_ref(p.url, url)}[/white]"
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


# Map command

@app.command(help="List discovered URLs on a site.")
def map(
    url: str = typer.Argument(..., help="Website URL"),
    max_links: int = typer.Option(500, "--max-links", "-n", help="Max links"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to .txt or .json"),
):
    from emb.map import map_url as _map

    url = _ensure_scheme(url)
    result = _run_with_steps(
        lambda: _map(url, max_links=max_links),
        [
            f"Working on {url}",
            "Checking sitemaps...",
            "Following links...",
            "Collecting URLs...",
            "Putting it together...",
        ],
        interval=1.0,
    )

    if result.error:
        _err(result.error, "add https:// or check the domain" if "scheme" in (result.error or "").lower()
             else "site may be unreachable or block crawlers")
        raise typer.Exit(1)
    if not result.links:
        _err("No URLs discovered", "site may have no sitemap — try: ember crawl " + url)
        raise typer.Exit(1)

    base_host = urlparse(url).netloc or url
    console.print(f"\n  [bold]Map[/bold]  [orange1]{base_host}[/orange1]  [bright_black]{result.total} {_plural(result.total, 'URL')}[/bright_black]\n")
    _display_links(result.links, url)

    out = _resolve_save(save, "map", url, ".txt")
    if out:
        if Path(out).suffix.lower() == ".json":
            _write(out, {"url": url, "total": result.total, "links": result.links})
        else:
            _write(out, "\n".join(result.links))


# Interact command

@app.command(help="Use a browser or page chat with an LLM.")
def interact(
    url: str = typer.Argument(..., help="URL to open"),
    prompt: str = typer.Option("", "--prompt", "-p", help="What to do on the page"),
    provider: str = typer.Option("openai", "--provider", help="LLM provider (openai, anthropic, ollama, ...)"),
    model: str = typer.Option("", "--model", "-m", help="Model name override"),
    timeout: int = typer.Option(60, "--timeout", "-t", help="Timeout in seconds"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save result to file"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip Lightpanda; use an OpenAI-compatible LLM over scraped content"),
):
    from emb.interact import interact as _interact
    import platform as _platform

    url = _ensure_scheme(url)
    # Windows uses the no-browser path.
    use_browser = not no_browser and _platform.system() != "Windows"
    interact_steps = [
        f"Working on {url}",
        "Opening page...",
        "Reading page state...",
        "Running your prompt..." if prompt else "Loading page...",
        "Putting it together...",
    ]
    result = _run_with_steps(
        lambda: _interact(url, prompt=prompt, provider=provider, model=model, timeout=timeout, use_browser=use_browser),
        interact_steps,
        interval=1.0,
    )

    if not result.success:
        err = result.error or ""
        _err(err, (
            "set EMBER_LLM_API_KEY or the provider's key env var" if "API_KEY" in err or "api_key" in err.lower()
            else "the no-browser path only supports an OpenAI-compatible API" if "OpenAI-compatible API" in err
            else "valid providers: openai, anthropic, gemini, ollama, llama_cpp" if "provider" in err.lower()
            else "Lightpanda browser is not yet available on this platform — use --no-browser" if "Lightpanda" in err
            else ""
        ))
        raise typer.Exit(1)

    if not result.content or not result.content.strip():
        _err("No content returned", "Try --no-browser to use trafilatura fallback")
        raise typer.Exit(1)

    body = _display_markdown(result.content) if not prompt else result.content
    _print_result(body, title=url)
    out = _resolve_save(save, "interact", url, ".md")
    if out:
        _write(out, result.content)


# Extract command

@app.command(help="Ask an LLM to pull data from a page.")
def extract(
    url: str = typer.Argument(..., help="URL to extract from"),
    prompt: str = typer.Option("", "--prompt", "-p", help="What to extract"),
    model: str = typer.Option(
        os.environ.get("EMBER_LLM_MODEL", "gpt-4o-mini"),
        "--model", "-m",
        help="LLM model",
    ),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save result to file"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip Lightpanda. Extract still requires EMBER_LLM_API_KEY"),
):
    from emb.agent import extract as _extract
    import platform as _platform

    url = _ensure_scheme(url)
    use_browser: bool | None = None if (not no_browser and _platform.system() != "Windows") else False
    result = _run_with_steps(
        lambda: _extract(url, prompt=prompt, model=model, use_browser=use_browser),
        [
            f"Working on {url}",
            "Fetching page...",
            "Reading content...",
            "Pulling structured data...",
            "Putting it together...",
        ],
        interval=1.0,
    )

    if "error" in result:
        err = result["error"]
        if "requires EMBER_LLM_API_KEY" in err:
            err = "LLM API key required for extract"
        _err(
            err,
            "set EMBER_LLM_API_KEY or OPENAI_API_KEY; use ember url for raw page content"
            if "requires EMBER_LLM_API_KEY" in result["error"]
            else "set EMBER_LLM_API_KEY or OPENAI_API_KEY" if "key" in result["error"].lower()
            else "",
        )
        raise typer.Exit(1)

    content = result.get("content") or result.get("markdown")
    if content:
        body = _display_markdown(content) if "markdown" in result and "content" not in result else content
        _print_result(body, title=url)
        out = _resolve_save(save, "extract", url, ".json")
        if out:
            _write(out, result if Path(out).suffix.lower() == ".json" else content)
    else:
        console.print_json(json.dumps(result))
        out = _resolve_save(save, "extract", url, ".json")
        if out:
            _write(out, result)


# Batch command

@app.command(help="Scrape many URLs from a file.")
def batch(
    file: Path = typer.Argument(..., help="Text file — one URL per line, # lines are skipped"),
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Parallel requests"),
    save: Optional[str] = typer.Option(None, "--save", "-o", help="Save to dir/ or .json"),
):
    from emb.scrape import scrape_url_async

    if not file.exists():
        _err(f"File not found: {file}")
        raise typer.Exit(1)

    raw = file.read_text(encoding="utf-8-sig").splitlines()
    urls = [
        _ensure_scheme(u.strip().lstrip("\ufeff"))
        for u in raw
        if u.strip() and not u.lstrip("\ufeff").startswith("#")
    ]
    if not urls:
        _err("No URLs in file", "one URL per line — lines starting with # are comments")
        raise typer.Exit(1)

    async def _run() -> list:
        sem = asyncio.Semaphore(concurrency)
        async def _one(u: str):
            async with sem:
                return await scrape_url_async(u)
        return list(await asyncio.gather(*[_one(u) for u in urls]))

    results = _run_with_steps(
        lambda: asyncio.run(_run()),
        [
            f"Working on {len(urls)} URLs",
            "Reading URL list...",
            "Fetching pages...",
            "Collecting results...",
            "Putting it together...",
        ],
        interval=1.0,
    )

    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]

    console.print(f"\n  [bold]Batch[/bold]  [bright_black]{file.name}[/bright_black]")
    console.print(f"  [orange1]{len(ok)}[/orange1] ok  [red]{len(fail)}[/red] failed\n")
    for r in ok:
        target = _short_ref(r.url)
        info = f"  [white]{_trim(r.title, 44)}[/white]" if r.title else ""
        console.print(f"  [green]✓[/green]  [white]{target}[/white]{info}  [bright_black]{len(r.markdown):,}c[/bright_black]")
    for r in fail:
        target = _short_ref(r.url)
        console.print(f"  [red]✗[/red]  [white]{target}[/white]  [red]{_clean_error(r.error)}[/red]")
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
    return "  [orange1]ember[/orange1] [bright_black]›[/bright_black] "


def _pt_prompt(state: dict):
    from prompt_toolkit.formatted_text import HTML

    return HTML('  <style fg="ansibrightyellow">ember</style><style fg="ansibrightblack"> › </style>')


def _make_prompt_session(state_ref: dict[str, dict]):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import run_in_terminal
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.lexers import Lexer
    from prompt_toolkit.styles import Style

    class _SessionLexer(Lexer):
        def lex_document(self, document):
            lines = document.lines

            def _get_line(lineno: int):
                if lineno >= len(lines):
                    return []
                line = lines[lineno]
                if not line:
                    return []
                head, sep, tail = line.partition(" ")
                tokens = [("class:cmd", head)]
                if sep:
                    tokens.append(("class:arg", sep + tail))
                return tokens

            return _get_line

    bindings = KeyBindings()

    @bindings.add("c-l")
    def _clear(event) -> None:
        def _reset() -> None:
            console.clear()
            _print_session_home(state_ref["value"])

        event.app.current_buffer.reset()
        run_in_terminal(_reset)

    style = Style.from_dict({
        "cmd": "#ffaf00 bold",
        "arg": "#ffffff",
    })

    return PromptSession(key_bindings=bindings, lexer=_SessionLexer(), style=style)


def _session_run(line: str, state: dict) -> dict:
    try:
        parts = shlex.split(line)
    except ValueError as e:
        _err(f"Parse error: {e}")
        return state

    if not parts:
        return state

    cmd, rest = parts[0].lower(), parts[1:]

    # Meta
    if cmd in ("help", "?", "h"):
        _print_session_help()
        return state

    if cmd in ("quit", "exit", "q"):
        raise SystemExit(0)

    if cmd in ("clear", "cls"):
        console.clear()
        _print_session_home(state)
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
                console.print(f"  output [orange1]{current}[/orange1]")
            else:
                console.print("  [bright_black]output not set — use 'output <dir>' to configure[/bright_black]")
                sd = _get_save_dir()
                if sd:
                    console.print(f"  [bright_black]global default from config: {sd}[/bright_black]")
            return state
        if rest[0].lower() in ("clear", "none", "off", "--clear"):
            state = {**state, "save_dir": ""}  # "" = explicitly cleared
            console.print("  [bright_black]output cleared — results won't be auto-saved this session[/bright_black]")
        else:
            d = rest[0]
            Path(d).mkdir(parents=True, exist_ok=True)
            state = {**state, "save_dir": d}
            console.print(f"  [green]✓[/green] output → [orange1]{d}[/orange1]  [bright_black](all results auto-saved here)[/bright_black]")
        return state

    if cmd == "browser":
        sub = rest[0].lower() if rest else "status"
        if sub == "status":
            _browser_status_action()
            return state
        if sub == "install":
            _browser_install_action()
            return state
        if sub == "path":
            _browser_path_action()
            return state
        if sub == "clear":
            _browser_clear_action()
            return state
        _err("Usage: browser <status|install|path|clear>")
        return state

    # Url
    if cmd == "url":
        if not rest:
            _err("Usage: url <url> [-o file] [-b]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.scrape import scrape_url
        r = _run_with_steps(
            lambda: scrape_url(url, use_browser=True if flags.get("b") else None),
            [
                f"Working on {url}",
                "Fetching page...",
                "Reading content...",
                "Extracting clean text...",
                "Putting it together...",
            ],
        )
        if not r.success:
            _err(r.error or "Failed", "try -b to use the browser"); return state
        _print_result(
            _display_markdown(r.markdown),
            title=r.title or url,
            subtitle=f"{url}  {len(r.markdown):,} chars",
        )
        out = _ses_resolve(flags, "url", url, ".md", state)
        if out:
            _write(out, r.markdown)
        return {**state, "last": {"data": r.markdown, "meta": {"url": url, "title": r.title}}}

    # Search
    if cmd == "search":
        if not rest:
            _err("Usage: search <query> [-n 5] [-o file]"); return state
        pos, flags = _parse_flags(rest)
        query = " ".join(pos)
        from emb.search import search as _search
        try:
            results = _run_with_steps(
                lambda: _search(query, limit=int(flags.get("n", 5))),
                [
                    f"Searching for {query!r}",
                    "Finding sources...",
                    "Ranking results...",
                    "Putting it together...",
                ],
            )
        except Exception as e:
            _err(str(e)); return state
        if not results:
            _err("No results", "try a broader query"); return state
        console.print(f"  [bold]Results for[/bold] [orange1]{query}[/orange1]  [bright_black]{len(results)} found[/bright_black]")
        for i, r in enumerate(results, 1):
            console.print(f"  [bold orange1]{i}[/bold orange1]  [bold]{r.title}[/bold]")
            console.print(f"     [white]{r.url}[/white]")
            if r.description:
                snippet = textwrap.shorten(r.description, width=max(60, console.width - 10), placeholder="…")
                console.print(f"     [white]{snippet}[/white]")
            if i != len(results):
                console.print()
        data = [{"title": r.title, "url": r.url, "description": r.description} for r in results]
        out = _ses_resolve(flags, "search", query, ".json", state)
        if out:
            _write(out, data if Path(out).suffix.lower() != ".txt" else
                   "\n\n".join(f"{i}. {r['title']}\n   {r['url']}\n   {r['description']}" for i, r in enumerate(data, 1)))
        return {**state, "last": {"data": data, "meta": {"query": query}}}

    # Crawl
    if cmd == "crawl":
        if not rest:
            _err("Usage: crawl <url> [-n 50] [-d 3] [-o path]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.crawl import crawl as _crawl
        r = _run_with_steps(
            lambda: _crawl(url, max_pages=int(flags.get("n", 50)), max_depth=int(flags.get("d", 3))),
            [
                f"Working on {url}",
                "Fetching pages...",
                "Following links...",
                "Collecting content...",
                "Putting it together...",
            ],
            interval=1.0,
        )
        if not r.success:
            _err(r.error or "Crawl failed"); return state
        base_host = urlparse(url).netloc or url
        tree = Tree(f"[orange1]{base_host}[/orange1]  [bright_black]{r.total} {_plural(r.total, 'page')}[/bright_black]")
        _nodes: dict[int, Any] = {-1: tree}
        for p in r.pages:
            parent = _nodes.get(p.depth - 1, tree)
            lbl = f"[white]{_short_ref(p.url, url)}[/white]"
            if p.title:
                lbl += f"  [bold]{p.title}[/bold]"
            lbl += f"  [bright_black]{len(p.markdown):,}c[/bright_black]"
            _nodes[p.depth] = parent.add(lbl)  # type: ignore[union-attr]
        console.print(tree)
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
                console.print(f"  [green]✓[/green] saved {r.total} pages → [orange1]{outp}/[/orange1]")
        return {**state, "last": {"data": pages, "meta": {"url": url, "total": r.total}}}

    # Map
    if cmd == "map":
        if not rest:
            _err("Usage: map <url> [-o file]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.map import map_url as _map
        r = _run_with_steps(
            lambda: _map(url, max_links=int(flags.get("n", 500))),
            [
                f"Working on {url}",
                "Checking sitemaps...",
                "Following links...",
                "Collecting URLs...",
                "Putting it together...",
            ],
            interval=1.0,
        )
        if r.error:
            _err(r.error, "add https:// or check the domain"); return state
        if not r.links:
            _err("No URLs found", "try: crawl " + url); return state
        base_host = urlparse(url).netloc or url
        console.print(f"  [bold]Map[/bold]  [orange1]{base_host}[/orange1]  [bright_black]{r.total} {_plural(r.total, 'URL')}[/bright_black]")
        _display_links(r.links, url)
        out = _ses_resolve(flags, "map", url, ".txt", state)
        if out:
            _write(out, {"url": url, "total": r.total, "links": r.links}
                   if Path(out).suffix.lower() == ".json" else "\n".join(r.links))
        return {**state, "last": {"data": r.links, "meta": {"url": url, "total": r.total}}}

    # Interact
    if cmd == "interact":
        if not rest:
            _err("Usage: interact <url> [-p 'prompt'] [-o file]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.interact import interact as _interact
        prompt = flags.get("p", "")
        r = _run_with_steps(
            lambda: _interact(
                url,
                prompt=prompt,
                provider=flags.get("provider", "openai"),
                model=flags.get("model", ""),
                timeout=int(flags.get("t", 60)),
            ),
            [
                f"Working on {url}",
                "Opening page...",
                "Reading page state...",
                "Running your prompt..." if prompt else "Loading page...",
                "Putting it together...",
            ],
            interval=1.0,
        )
        if not r.success:
            _err(r.error or "Failed"); return state
        if not r.content or not r.content.strip():
            _err("No content", "Lightpanda not available — try: url " + url); return state
        body = _display_markdown(r.content) if not prompt else r.content
        _print_result(body, title=url)
        out = _ses_resolve(flags, "interact", url, ".md", state)
        if out:
            _write(out, r.content)
        return {**state, "last": {"data": r.content, "meta": {"url": url}}}

    # Extract
    if cmd == "extract":
        if not rest:
            _err("Usage: extract <url> [-p 'what to extract'] [-o file]"); return state
        pos, flags = _parse_flags(rest)
        url = _ensure_scheme(pos[0])
        from emb.agent import extract as _extract
        r = _run_with_steps(
            lambda: _extract(url, prompt=flags.get("p", ""), model=flags.get("model", "gpt-4o-mini")),
            [
                f"Working on {url}",
                "Fetching page...",
                "Reading content...",
                "Pulling structured data...",
                "Putting it together...",
            ],
            interval=1.0,
        )
        if "error" in r:
            err = r["error"]
            hint = ""
            if "requires EMBER_LLM_API_KEY" in err:
                err = "LLM API key required for extract"
                hint = "set EMBER_LLM_API_KEY or OPENAI_API_KEY; use url for raw page content"
            _err(err, hint); return state
        content = r.get("content") or r.get("markdown") or json.dumps(r, indent=2)
        body = _display_markdown(content) if "markdown" in r and "content" not in r else content
        _print_result(body, title=url)
        out = _ses_resolve(flags, "extract", url, ".json", state)
        if out:
            _write(out, r if Path(out).suffix.lower() == ".json" else content)
        return {**state, "last": {"data": content, "meta": {"url": url}}}

    # Batch
    if cmd == "batch":
        if not rest:
            _err("Usage: batch <urls.txt> [-c 5] [-o path]"); return state
        pos, flags = _parse_flags(rest)
        f = Path(pos[0])
        if not f.exists():
            _err(f"File not found: {f}"); return state
        from emb.scrape import scrape_url_async
        raw = f.read_text(encoding="utf-8-sig").splitlines()
        urls = [
            _ensure_scheme(u.strip().lstrip("\ufeff"))
            for u in raw
            if u.strip() and not u.lstrip("\ufeff").startswith("#")
        ]
        if not urls:
            _err("No URLs in file"); return state
        conc = int(flags.get("c", 5))

        async def _run() -> list:
            sem = asyncio.Semaphore(conc)
            async def _one(u: str):
                async with sem:
                    return await scrape_url_async(u)
            return list(await asyncio.gather(*[_one(u) for u in urls]))

        batch_results = _run_with_steps(
            lambda: asyncio.run(_run()),
            [
                f"Working on {len(urls)} URLs",
                "Reading URL list...",
                "Fetching pages...",
                "Collecting results...",
                "Putting it together...",
            ],
            interval=1.0,
        )

        ok = [r for r in batch_results if r.success]
        fail = [r for r in batch_results if not r.success]
        console.print(f"  [bold]Batch[/bold]  [bright_black]{f.name}[/bright_black]")
        console.print(f"  [orange1]{len(ok)}[/orange1] ok  [red]{len(fail)}[/red] failed")
        for r in ok:
            target = _short_ref(r.url)
            info = f"  [white]{_trim(r.title, 44)}[/white]" if r.title else ""
            console.print(f"  [green]✓[/green]  [white]{target}[/white]{info}  [bright_black]{len(r.markdown):,}c[/bright_black]")
        for r in fail:
            target = _short_ref(r.url)
            console.print(f"  [red]✗[/red]  [white]{target}[/white]  [red]{_clean_error(r.error)}[/red]")
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
                console.print(f"  [green]✓[/green] saved {len(ok)} pages → [orange1]{outp}/[/orange1]")
        return {**state, "last": {"data": data, "meta": {"total": len(urls), "ok": len(ok)}}}

    _err(f"Unknown command: {cmd!r}", "type 'help' for available commands")
    return state


@app.command(help="Start the interactive session.")
def session():
    # None uses global config. "" turns auto-save off.
    state: dict = {"last": {}, "save_dir": None}
    state_ref: dict[str, dict] = {"value": state}
    _print_session_home(state)

    # Enable readline when available.
    try:
        import readline as _rl
        _rl.parse_and_bind("tab: complete")
    except ImportError:
        pass

    prompt_session = None
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            prompt_session = _make_prompt_session(state_ref)
        except Exception:
            prompt_session = None

    while True:
        try:
            if prompt_session is not None:
                try:
                    line = prompt_session.prompt(_pt_prompt(state))
                except EOFError:
                    break
            else:
                console.print(_ses_prompt(state), end="", highlight=False)
                console.file.flush()
                try:
                    line = input()
                except EOFError:
                    break
                # Handle Ctrl+L without readline.
                if "\x0c" in line:
                    console.clear()
                    _print_session_home(state)
                    line = line.replace("\x0c", "").strip()
                    if not line:
                        continue
            line = line.strip()
            if not line:
                continue
            state = _session_run(line, state)
            state_ref["value"] = state
        except SystemExit:
            break
        except KeyboardInterrupt:
            break

    console.print("\n  [bright_black]bye[/bright_black]\n")


# Service commands

@app.command(help="Start the REST API server.")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(
        int(os.environ.get("EMBER_PORT", "51251")),
        "--port", "-p",
        help="Port (default 51251, overridden by EMBER_PORT env var)",
    ),
):
    from emb.api import start_server
    console.print(f"\n  [bold]ember[/bold] API  [orange1]http://{host}:{port}[/orange1]\n")
    start_server(host=host, port=port)


@app.command(help="Start the MCP server.")
def mcp():
    from emb.mcp import start_mcp
    start_mcp()


@app.command("help", help="Show the full command guide.")
def help_command() -> None:
    _print_session_help()


@app.command(help="Show the version.")
def version():
    console.print(f"  ember [orange1]v{__version__}[/orange1]")


@browser_app.callback(invoke_without_command=True)
def browser_main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        browser_status()


@browser_app.command("status", help="Show browser runtime status.")
def browser_status() -> None:
    from emb import _browser

    _print_browser_status(_browser.status())


@browser_app.command("install", help="Download and cache Lightpanda now.")
def browser_install() -> None:
    from emb import _browser

    info = _browser.status()
    if info.get("available"):
        console.print()
        console.print(f"  [green]✓[/green] browser ready → [orange1]{info['path']}[/orange1]\n")
        return

    path = _run_with_steps(
        _browser.ensure,
        [
            "Checking browser runtime...",
            "Preparing browser setup...",
        ],
        interval=1.0,
    )
    console.print()
    console.print(f"  [green]✓[/green] browser ready → [orange1]{path}[/orange1]\n")


@browser_app.command("path", help="Show the resolved browser binary path.")
def browser_path() -> None:
    from emb import _browser

    info = _browser.status()
    if not info.get("available"):
        _err("Browser not ready", info.get("hint", "run `ember browser install` first"))
        raise typer.Exit(1)
    console.print(f"\n  [orange1]{info['path']}[/orange1]\n")


@browser_app.command("clear", help="Remove the cached browser binary.")
def browser_clear() -> None:
    from emb import _browser

    removed = _browser.clear_cache()
    if removed:
        console.print(
            f"\n  [green]✓[/green] cleared cached browser → "
            f"[orange1]{_browser.BINARY_PATH}[/orange1]\n"
        )
        return
    console.print(
        f"\n  [bright_black]no cached browser at {_browser.BINARY_PATH}[/bright_black]\n"
    )


def _browser_status_action() -> None:
    from emb import _browser

    _print_browser_status(_browser.status())


def _browser_install_action() -> bool:
    from emb import _browser

    info = _browser.status()
    if info.get("available"):
        console.print()
        console.print(f"  [green]ok[/green] browser ready -> [orange1]{info['path']}[/orange1]\n")
        return True

    try:
        path = _run_with_steps(
            _browser.ensure,
            [
                "Checking browser runtime...",
                "Preparing browser setup...",
            ],
            interval=1.0,
        )
    except RuntimeError as exc:
        _err(str(exc))
        return False

    console.print()
    console.print(f"  [green]ok[/green] browser ready -> [orange1]{path}[/orange1]\n")
    return True


def _browser_path_action() -> bool:
    from emb import _browser

    info = _browser.status()
    if not info.get("available"):
        _err("Browser not ready", info.get("hint", "run `ember browser install` first"))
        return False
    console.print(f"\n  [orange1]{info['path']}[/orange1]\n")
    return True


def _browser_clear_action() -> None:
    from emb import _browser

    removed = _browser.clear_cache()
    if removed:
        console.print(
            f"\n  [green]ok[/green] cleared cached browser -> "
            f"[orange1]{_browser.BINARY_PATH}[/orange1]\n"
        )
        return
    console.print(
        f"\n  [bright_black]no cached browser at {_browser.BINARY_PATH}[/bright_black]\n"
    )


def _browser_install_callback() -> None:
    if not _browser_install_action():
        raise typer.Exit(1)


def _browser_path_callback() -> None:
    if not _browser_path_action():
        raise typer.Exit(1)


for _command in browser_app.registered_commands:
    if _command.name == "status":
        _command.callback = _browser_status_action
    elif _command.name == "install":
        _command.callback = _browser_install_callback
    elif _command.name == "path":
        _command.callback = _browser_path_callback
    elif _command.name == "clear":
        _command.callback = _browser_clear_action
