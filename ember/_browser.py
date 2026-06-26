"""Auto-download and cache Lightpanda browser binary.

The browser is downloaded on first use — no manual install required.
Cached at ~/.cache/ember/lightpanda for subsequent use.
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "ember"
BINARY_NAME = "lightpanda"
BINARY_PATH = CACHE_DIR / BINARY_NAME

# Nightly builds for each platform
_DOWNLOAD_URLS = {
    ("Linux", "x86_64"): (
        "https://github.com/lightpanda-io/browser/releases/download/nightly/"
        "lightpanda-x86_64-linux"
    ),
    ("Linux", "aarch64"): (
        "https://github.com/lightpanda-io/browser/releases/download/nightly/"
        "lightpanda-aarch64-linux"
    ),
    ("Darwin", "x86_64"): (
        "https://github.com/lightpanda-io/browser/releases/download/nightly/"
        "lightpanda-x86_64-macos"
    ),
    ("Darwin", "aarch64"): (
        "https://github.com/lightpanda-io/browser/releases/download/nightly/"
        "lightpanda-aarch64-macos"
    ),
}


def is_available() -> bool:
    """Check if Lightpanda binary is installed."""
    if BINARY_PATH.exists():
        return True
    try:
        subprocess.run(["lightpanda", "version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _platform_url() -> str | None:
    """Get the download URL for the current platform."""
    system = platform.system()
    machine = platform.machine()
    return _DOWNLOAD_URLS.get((system, machine))


def ensure() -> str:
    """Ensure Lightpanda is available. Download if needed.

    Returns the path to the Lightpanda binary.
    Raises RuntimeError if download fails.
    """
    # Check env override
    env_path = os.environ.get("EMBER_LIGHTPANDA_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return str(p)
        try:
            subprocess.run([env_path, "version"], capture_output=True, timeout=5)
            return env_path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Check PATH
    try:
        r = subprocess.run(["lightpanda", "version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "lightpanda"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check cached binary
    if BINARY_PATH.exists():
        try:
            r = subprocess.run([str(BINARY_PATH), "version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return str(BINARY_PATH)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        BINARY_PATH.unlink(missing_ok=True)

    # Download
    url = _platform_url()
    if not url:
        raise RuntimeError(
            f"Lightpanda not available for {platform.system()} {platform.machine()}. "
            f"Install manually: https://lightpanda.io/docs/open-source/installation"
        )
    import httpx

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BINARY_PATH.with_suffix(".tmp")
    try:
        print("  Downloading Lightpanda...", file=sys.stderr)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)
        tmp.chmod(tmp.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        tmp.rename(BINARY_PATH)
        print(f"  ✓ Lightpanda cached at {BINARY_PATH}", file=sys.stderr)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download Lightpanda: {e}") from e

    return str(BINARY_PATH)
