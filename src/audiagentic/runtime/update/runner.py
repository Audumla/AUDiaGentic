"""Download and install a new audiagentic version from GitHub Releases."""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.error import URLError

from audiagentic.foundation.cli_io import print_message

from . import GITHUB_REPO

logger = logging.getLogger(__name__)

def _safe_version(version: str) -> str:
    """Replace hyphens with underscores for wheel filename compatibility."""
    return version.replace("-", "_")


def _wheel_url(version: str) -> str:
    safe_ver = _safe_version(version)
    return (
        f"https://github.com/{GITHUB_REPO}/releases/download/v{version}/"
        f"audiagentic-{safe_ver}-py3-none-any.whl"
    )


def _download_wheel(url: str, version: str, directory: Path) -> Path:
    """Download the wheel to a temp file and return its path.

    Wheel filename must carry all five tags (name-ver-py-abi-platform.whl)
    so pip can validate and install it without raising 'wrong number of parts'.
    """
    safe_ver = _safe_version(version)
    filename = f"audiagentic-{safe_ver}-py3-none-any.whl"
    tmp = directory / filename
    print_message(f"  Downloading audiagentic {version}...")
    urllib.request.urlretrieve(url, tmp)
    return tmp


def _pip_install(wheel_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", str(wheel_path)],
        capture_output=True,
        text=True,
    )


def install_version(version: str) -> dict:
    """Download and install an AUDiaGentic wheel into the active Python environment."""
    url = _wheel_url(version)
    try:
        with tempfile.TemporaryDirectory(prefix="audiagentic-update-") as temp_dir:
            try:
                wheel = _download_wheel(url, version, Path(temp_dir))
            except (OSError, URLError) as exc:
                logger.warning("Update download failed for version %s", version, exc_info=True)
                return {"ok": False, "error": f"download failed: {exc}"}
            try:
                result = _pip_install(wheel)
            except OSError as exc:
                logger.warning("pip could not start for update %s", version, exc_info=True)
                return {"ok": False, "error": f"pip install could not start: {exc}"}
    except (OSError, URLError) as exc:
        logger.warning("Could not create temporary update workspace", exc_info=True)
        return {"ok": False, "error": f"could not prepare update: {exc}"}

    if result.returncode:
        logger.warning("pip install failed for update %s (rc=%s)", version, result.returncode)
        return {"ok": False, "error": f"pip install failed (rc={result.returncode})\n{result.stderr}"}

    return {"ok": True, "version": version}
