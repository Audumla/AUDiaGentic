"""Download and install a new audiagentic version from GitHub Releases."""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from audiagentic.foundation.cli_io import print_message

from . import GITHUB_REPO

logger = logging.getLogger(__name__)

_FROZEN = getattr(sys, "frozen", False)


def _safe_version(version: str) -> str:
    """Replace hyphens with underscores for wheel filename compatibility."""
    return version.replace("-", "_")


def _wheel_url(version: str) -> str:
    safe_ver = _safe_version(version)
    return (
        f"https://github.com/{GITHUB_REPO}/releases/download/v{version}/"
        f"audiagentic-{safe_ver}-py3-none-any.whl"
    )


def _download_wheel(url: str, version: str) -> Path:
    """Download the wheel to a temp file and return its path.

    Wheel filename must carry all five tags (name-ver-py-abi-platform.whl)
    so pip can validate and install it without raising 'wrong number of parts'.
    """
    safe_ver = _safe_version(version)
    filename = f"audiagentic-{safe_ver}-py3-none-any.whl"
    tmp = Path(tempfile.gettempdir()) / filename
    print_message(f"  Downloading audiagentic {version}...")
    urllib.request.urlretrieve(url, tmp)
    return tmp


def _pip_install(wheel_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", str(wheel_path)],
        capture_output=True,
        text=True,
    )


def _is_locked_exe_error(output: str) -> bool:
    """True when pip fails because the running .exe is locked (Windows WinError 32)."""
    return "WinError 32" in output or "being used by another process" in output


def _schedule_post_exit_install(wheel: Path, version: str) -> dict:
    """Spawn a detached PS1 that installs after this process exits (Windows frozen exe only).

    Once this process exits the exe lock is released, the script sleeps 2s to be
    sure then runs pip, reports the result, and deletes itself.
    Returns {"ok": "scheduled"} so prompt.py knows to call sys.exit().
    """
    script_template = (Path(__file__).parent / "_update.ps1").read_text(encoding="utf-8")
    script = script_template.format(
        version=version,
        python_exe=sys.executable,
        wheel=str(wheel),
    )
    script_path = wheel.parent / "_audiagentic_update.ps1"
    script_path.write_text(script, encoding="utf-8")

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Normal", "-File", str(script_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except Exception as exc:
        logger.error("Failed to spawn updater script", exc_info=True)
        script_path.unlink(missing_ok=True)
        return {
            "ok": False,
            "locked": True,
            "wheel": str(wheel),
            "error": f"could not spawn updater: {exc} — run: pip install \"{wheel}\"",
        }

    return {"ok": "scheduled", "version": version, "wheel": str(wheel)}


def install_version(version: str) -> dict:
    """Download and install the given version.

    On Windows when running as a frozen exe the running audiagentic.exe is locked
    and pip cannot replace it in-place.  We detect this early (frozen flag) rather
    than waiting for the WinError 32, schedule a detached PowerShell script that
    will perform the install after this process exits, and return {"ok": "scheduled"}
    so the caller can exit cleanly.

    On non-frozen installs (source / venv) pip can update the package in-place.
    """
    url = _wheel_url(version)

    try:
        wheel = _download_wheel(url, version)
    except Exception as exc:
        logger.error("Download failed for version %s", version, exc_info=True)
        return {"ok": False, "error": f"download failed: {exc}"}

    # On Windows frozen exe: schedule post-exit install instead of attempting
    # in-place pip replace (which will always fail with WinError 32).
    if _FROZEN and sys.platform == "win32":
        return _schedule_post_exit_install(wheel, version)

    result = _pip_install(wheel)

    if result.returncode != 0:
        combined = result.stdout + result.stderr
        if _is_locked_exe_error(combined):
            # Fallback: frozen detection missed somehow — still schedule gracefully.
            return _schedule_post_exit_install(wheel, version)
        try:
            wheel.unlink()
        except (OSError, PermissionError):
            logger.debug("Failed to clean up wheel file after install failure", exc_info=True)
        return {"ok": False, "error": f"pip install failed (rc={result.returncode})\n{result.stderr}"}

    try:
        wheel.unlink()
    except (OSError, PermissionError):
        logger.debug("Failed to clean up wheel file after successful install", exc_info=True)

    print_message("  Refreshing harness config...")
    try:
        from audiagentic.foundation.paths.home import global_harness_runtime
        from audiagentic.runtime.harness import install_to
        install_to(global_harness_runtime())
    except Exception as exc:
        logger.warning("Harness config refresh failed during update", exc_info=True)
        return {"ok": True, "version": version, "harness_warning": str(exc)}

    return {"ok": True, "version": version}
