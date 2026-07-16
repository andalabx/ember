from __future__ import annotations

import hashlib
import os
import platform
import secrets
import stat
import subprocess
import sys
from pathlib import Path

import httpx

CACHE_DIR = Path.home() / ".cache" / "ember"
BINARY_NAME = "lightpanda"
BINARY_PATH = CACHE_DIR / BINARY_NAME

LIGHTPANDA_VERSION = "0.3.3"

# SHA-256 digests for the pinned Lightpanda binaries.
_BINARY_HASHES: dict[tuple[str, str], str] = {
    ("Linux",  "x86_64"):  "b6ab613846f5291cc6bafd7f44ffb9718df51bf00eb83954e1fc5d7f52c7b886",
    ("Linux",  "aarch64"): "db35c06ee074a79c2e039965c404e578748c1d22cb296e853461970ea0c2945f",
    ("Darwin", "x86_64"):  "631cec32766d2f98f1005e3af6af74794fb55cc28d193d97176cfa21f1d26d0c",
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


def is_available() -> bool:
    if BINARY_PATH.exists():
        return True
    try:
        subprocess.run(["lightpanda", "version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _platform_url() -> str | None:
    system = platform.system()
    machine = platform.machine()
    return _DOWNLOAD_URLS.get((system, machine))


def ensure() -> str:
    # Check the env override.
    env_path = os.environ.get("EMBER_LIGHTPANDA_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists() and p.is_file():
            return str(p)
        # Allow a bare name from PATH.
        if os.sep not in env_path and "/" not in env_path:
            try:
                r = subprocess.run([env_path, "version"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    return env_path
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        raise RuntimeError(
            f"EMBER_LIGHTPANDA_PATH={env_path!r} — binary not found or not executable. "
            f"Check the path and try again."
        )

    # Check PATH.
    try:
        r = subprocess.run(["lightpanda", "version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "lightpanda"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check the cached binary.
    if BINARY_PATH.exists():
        try:
            r = subprocess.run([str(BINARY_PATH), "version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return str(BINARY_PATH)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        BINARY_PATH.unlink(missing_ok=True)

    # Download the binary.
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
            f"See: https://lightpanda.io/docs/open-source/installation"
        )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BINARY_PATH.with_suffix(".tmp")
    try:
        print("  Downloading Lightpanda...", file=sys.stderr)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)

        expected = _BINARY_HASHES.get((platform.system(), platform.machine()))
        if expected is None:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"No SHA-256 hash registered for {platform.system()} {platform.machine()}. "
                "Add the expected hash to _BINARY_HASHES before enabling downloads for this platform."
            )
        actual = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if not secrets.compare_digest(actual, expected):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"Lightpanda binary digest mismatch — download may be corrupted or tampered.\n"
                f"  expected: {expected}\n"
                f"  got:      {actual}"
            )

        tmp.chmod(tmp.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        tmp.rename(BINARY_PATH)
        print(f"  ✓ Lightpanda cached at {BINARY_PATH}", file=sys.stderr)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download Lightpanda: {e}") from e

    return str(BINARY_PATH)
