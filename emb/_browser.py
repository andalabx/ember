from __future__ import annotations

import hashlib
import os
import platform
import secrets
import stat
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

CACHE_DIR = Path.home() / ".cache" / "ember"
BINARY_NAME = "lightpanda"
BINARY_PATH = CACHE_DIR / BINARY_NAME

LIGHTPANDA_VERSION = "0.3.3"
_DOWNLOAD_CHUNK_BYTES = 262_144

# SHA-256 digests for the pinned Lightpanda binaries.
_BINARY_HASHES: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "b6ab613846f5291cc6bafd7f44ffb9718df51bf00eb83954e1fc5d7f52c7b886",
    ("Linux", "aarch64"): "db35c06ee074a79c2e039965c404e578748c1d22cb296e853461970ea0c2945f",
    ("Darwin", "x86_64"): "631cec32766d2f98f1005e3af6af74794fb55cc28d193d97176cfa21f1d26d0c",
    ("Darwin", "aarch64"): "1ef236a72e63975cf8acc7430e52dd31af5fff27a0b62ba81876eb8dde3e18e2",
}

_DOWNLOAD_URLS = {
    ("Linux", "x86_64"): (
        f"https://github.com/lightpanda-io/browser/releases/download/{LIGHTPANDA_VERSION}/"
        "lightpanda-x86_64-linux"
    ),
    ("Linux", "aarch64"): (
        f"https://github.com/lightpanda-io/browser/releases/download/{LIGHTPANDA_VERSION}/"
        "lightpanda-aarch64-linux"
    ),
    ("Darwin", "x86_64"): (
        f"https://github.com/lightpanda-io/browser/releases/download/{LIGHTPANDA_VERSION}/"
        "lightpanda-x86_64-macos"
    ),
    ("Darwin", "aarch64"): (
        f"https://github.com/lightpanda-io/browser/releases/download/{LIGHTPANDA_VERSION}/"
        "lightpanda-aarch64-macos"
    ),
}

_BINARY_SIZES: dict[tuple[str, str], int] = {
    ("Linux", "x86_64"): 139_469_968,
    ("Linux", "aarch64"): 145_113_816,
    ("Darwin", "x86_64"): 69_304_840,
    ("Darwin", "aarch64"): 66_269_944,
}

_PROGRESS_REPORTER: Callable[[str, dict[str, Any]], None] | None = None


def _platform_key() -> tuple[str, str]:
    return platform.system(), platform.machine()


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _format_speed(size: float) -> str:
    if size <= 0:
        return "0 B/s"
    return f"{_format_bytes(int(size))}/s"


def _emit(event: str, **data: Any) -> None:
    if _PROGRESS_REPORTER is not None:
        _PROGRESS_REPORTER(event, data)


@contextmanager
def report_progress(callback: Callable[[str, dict[str, Any]], None]) -> Iterator[None]:
    global _PROGRESS_REPORTER
    previous = _PROGRESS_REPORTER
    _PROGRESS_REPORTER = callback
    try:
        yield
    finally:
        _PROGRESS_REPORTER = previous


def download_size_bytes() -> int | None:
    return _BINARY_SIZES.get(_platform_key())


def _env_path() -> str | None:
    env_path = os.environ.get("EMBER_LIGHTPANDA_PATH")
    if not env_path:
        return None

    p = Path(env_path)
    if p.exists() and p.is_file():
        return str(p)

    if os.sep not in env_path and "/" not in env_path:
        try:
            r = subprocess.run([env_path, "version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return env_path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    raise RuntimeError(
        f"EMBER_LIGHTPANDA_PATH={env_path!r} - binary not found or not executable. "
        "Check the path and try again."
    )


def _path_binary() -> str | None:
    try:
        r = subprocess.run(["lightpanda", "version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "lightpanda"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _cached_binary() -> str | None:
    if not BINARY_PATH.exists():
        return None
    try:
        r = subprocess.run([str(BINARY_PATH), "version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return str(BINARY_PATH)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    BINARY_PATH.unlink(missing_ok=True)
    return None


def is_available() -> bool:
    try:
        return _env_path() is not None or _path_binary() is not None or _cached_binary() is not None
    except RuntimeError:
        return False


def _platform_url() -> str | None:
    return _DOWNLOAD_URLS.get(_platform_key())


def status() -> dict[str, Any]:
    system, machine = _platform_key()
    info: dict[str, Any] = {
        "available": False,
        "path": None,
        "source": None,
        "cache_path": str(BINARY_PATH),
        "platform": system,
        "machine": machine,
        "download_size_bytes": download_size_bytes(),
        "supported": _platform_url() is not None,
        "error": "",
        "hint": "",
    }

    try:
        env_path = _env_path()
    except RuntimeError as exc:
        info["source"] = "env"
        info["error"] = str(exc)
        info["hint"] = "Fix EMBER_LIGHTPANDA_PATH or unset it."
        return info

    if env_path is not None:
        info["available"] = True
        info["path"] = env_path
        info["source"] = "env"
        return info

    path_binary = _path_binary()
    if path_binary is not None:
        info["available"] = True
        info["path"] = path_binary
        info["source"] = "path"
        return info

    cached = _cached_binary()
    if cached is not None:
        info["available"] = True
        info["path"] = cached
        info["source"] = "cache"
        return info

    if system == "Windows":
        info["hint"] = "Browser features need Linux or WSL2. Run browser-free commands on Windows."
    elif not info["supported"]:
        info["hint"] = f"Lightpanda is not available for {system} {machine}."
    else:
        info["hint"] = "Run `ember browser install` to download Lightpanda once."
    return info


def clear_cache() -> bool:
    removed = False
    for target in (BINARY_PATH, BINARY_PATH.with_suffix(".tmp")):
        if target.exists():
            target.unlink(missing_ok=True)
            removed = True
    try:
        CACHE_DIR.rmdir()
    except OSError:
        pass
    return removed


def ensure() -> str:
    env_path = _env_path()
    if env_path is not None:
        return env_path

    path_binary = _path_binary()
    if path_binary is not None:
        return path_binary

    cached = _cached_binary()
    if cached is not None:
        return cached

    url = _platform_url()
    if not url:
        if platform.system() == "Windows":
            raise RuntimeError(
                f"Lightpanda does not support Windows natively ({platform.machine()}).\n"
                "Agents using ember should run on Linux. For local development, use WSL2:\n"
                "  wsl --install\n"
                "  then run ember inside WSL.\n"
                "Browser-free features (scrape, search, crawl, map) work on Windows as-is."
            )
        raise RuntimeError(
            f"Lightpanda not available for {platform.system()} {platform.machine()}. "
            "See: https://lightpanda.io/docs/open-source/installation"
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BINARY_PATH.with_suffix(".tmp")
    size_bytes = download_size_bytes()

    try:
        _emit(
            "download_needed",
            version=LIGHTPANDA_VERSION,
            cache_path=str(BINARY_PATH),
            size_bytes=size_bytes,
            size_text=_format_bytes(size_bytes) if size_bytes else "",
            url=url,
        )
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            total_bytes = int(resp.headers.get("content-length", "0") or 0) or size_bytes or 0
            hasher = hashlib.sha256()
            downloaded = 0
            started = time.monotonic()
            last_emit = started

            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(_DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    hasher.update(chunk)
                    f.write(chunk)

                    now = time.monotonic()
                    if now - last_emit >= 0.2:
                        elapsed = max(now - started, 0.001)
                        speed = downloaded / elapsed
                        percent = int(downloaded * 100 / total_bytes) if total_bytes else None
                        _emit(
                            "download_progress",
                            downloaded_bytes=downloaded,
                            downloaded_text=_format_bytes(downloaded),
                            total_bytes=total_bytes,
                            total_text=_format_bytes(total_bytes) if total_bytes else "",
                            percent=percent,
                            speed_bytes_per_sec=speed,
                            speed_text=_format_speed(speed),
                        )
                        last_emit = now

        elapsed = max(time.monotonic() - started, 0.001)
        speed = downloaded / elapsed
        percent = int(downloaded * 100 / total_bytes) if total_bytes else None
        _emit(
            "download_progress",
            downloaded_bytes=downloaded,
            downloaded_text=_format_bytes(downloaded),
            total_bytes=total_bytes,
            total_text=_format_bytes(total_bytes) if total_bytes else "",
            percent=percent,
            speed_bytes_per_sec=speed,
            speed_text=_format_speed(speed),
        )

        expected = _BINARY_HASHES.get(_platform_key())
        if expected is None:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"No SHA-256 hash registered for {platform.system()} {platform.machine()}. "
                "Add the expected hash to _BINARY_HASHES before enabling downloads for this platform."
            )

        _emit("verifying", path=str(tmp))
        actual = hasher.hexdigest()
        if not secrets.compare_digest(actual, expected):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                "Lightpanda binary digest mismatch - download may be corrupted or tampered.\n"
                f"  expected: {expected}\n"
                f"  got:      {actual}"
            )

        tmp.chmod(tmp.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        tmp.rename(BINARY_PATH)
        _emit("ready", path=str(BINARY_PATH), source="download")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download Lightpanda: {e}") from e

    return str(BINARY_PATH)
