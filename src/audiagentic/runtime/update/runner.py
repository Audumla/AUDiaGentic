"""Download and install a new audiagentic version from GitHub Releases."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

GITHUB_REPO = "Audumla/AUDiaGentic"

_FROZEN = getattr(sys, "frozen", False)


def _wheel_url(version: str) -> str:
    safe_ver = version.replace("-", "_")
    return (
        f"https://github.com/{GITHUB_REPO}/releases/download/v{version}/"
        f"audiagentic-{safe_ver}-py3-none-any.whl"
    )


def _download_wheel(url: str, version: str) -> Path:
    """Download the wheel to a temp file and return its path.

    Wheel filename must carry all five tags (name-ver-py-abi-platform.whl)
    so pip can validate and install it without raising 'wrong number of parts'.
    """
    safe_ver = version.replace("-", "_")
    filename = f"audiagentic-{safe_ver}-py3-none-any.whl"
    tmp = Path(tempfile.gettempdir()) / filename
    print(f"  Downloading audiagentic {version}...", flush=True)
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
    script = (
        f"# audiagentic auto-update — do not close\n"
        f"Start-Sleep -Seconds 2\n"
        f"Write-Host ''\n"
        f"Write-Host '  Installing audiagentic {version}...'\n"
        f"& \"{sys.executable}\" -m pip install --no-cache-dir \"{wheel}\"\n"
        f"if ($LASTEXITCODE -eq 0) {{\n"
        f"    Write-Host ''\n"
        f"    Write-Host '  audiagentic {version} installed. Run audiagentic to start.'\n"
        f"    Remove-Item -Force \"{wheel}\" -ErrorAction SilentlyContinue\n"
        f"}} else {{\n"
        f"    Write-Host ''\n"
        f"    Write-Host '  Install failed. Run manually:'\n"
        f"    Write-Host \"    pip install `\"{wheel}`\"\"\n"
        f"}}\n"
        f"Remove-Item -Force $MyInvocation.MyCommand.Path -ErrorAction SilentlyContinue\n"
        f"Write-Host ''\n"
        f"Write-Host '  Press any key to close...'\n"
        f"$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')\n"
    )
    script_path = wheel.parent / "_audiagentic_update.ps1"
    script_path.write_text(script, encoding="utf-8")

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Normal", "-File", str(script_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"pip install failed (rc={result.returncode})\n{result.stderr}"}

    try:
        wheel.unlink()
    except Exception:  # noqa: BLE001
        pass

    print("  Refreshing harness config...", flush=True)
    try:
        from audiagentic.provisioning.harness.pi.install import install_to
        from audiagentic.provisioning.home import global_harness_runtime
        install_to(global_harness_runtime())
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "version": version, "harness_warning": str(exc)}

    return {"ok": True, "version": version}
