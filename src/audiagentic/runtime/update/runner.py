"""Download and install a new audiagentic version from GitHub Releases."""
from __future__ import annotations

import subprocess
import sys

GITHUB_REPO = "Audumla/AUDiaGentic"


def _wheel_url(version: str) -> str:
    safe_ver = version.replace("-", "_")
    return (
        f"https://github.com/{GITHUB_REPO}/releases/download/v{version}/"
        f"audiagentic-{safe_ver}-py3-none-any.whl"
    )


def install_version(version: str) -> dict:
    """pip-install the given version from GitHub Releases, then refresh harness config."""
    url = _wheel_url(version)
    print(f"  Downloading audiagentic {version}...", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", url],
    )
    if result.returncode != 0:
        return {"ok": False, "error": f"pip install failed (rc={result.returncode})"}

    print("  Refreshing harness config...", flush=True)
    try:
        from audiagentic.provisioning.harness.pi.install import install_to
        from audiagentic.provisioning.home import global_harness_runtime
        install_to(global_harness_runtime())
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "version": version, "harness_warning": str(exc)}

    return {"ok": True, "version": version}
