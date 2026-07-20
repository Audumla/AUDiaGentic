"""Pi ACP bridge launch declaration for the shared ACP transport."""

from __future__ import annotations

import os
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.paths.home import global_harness_runtime
from audiagentic.foundation.transports import AcpLaunch


def _managed_pi_acp(runtime: Path) -> Path:
    """Resolve only the bridge installed in the managed Pi runtime."""
    binary = runtime / "cli" / "node_modules" / ".bin" / (
        "pi-acp.cmd" if os.name == "nt" else "pi-acp"
    )
    if not binary.is_file():
        raise make_error(
            prefix="RES",
            component="PIACP",
            number=1,
            kind="pi-harness",
            message=(
                "Managed Pi ACP bridge is not installed. "
                "Run 'audiagentic install' to provision the Pi recipe."
            ),
            details={"expected-path": str(binary)},
        )
    return binary


def _request_environment(request_runtime_root: Path) -> dict[str, str]:
    pi_root = request_runtime_root.resolve() / "pi"
    agent_root = pi_root / "agent"
    sessions_root = pi_root / "sessions"
    environment = {
        "PI_CODING_AGENT_DIR": str(agent_root),
    }
    if os.name == "nt":
        home = pi_root / "home"
        temp = pi_root / "tmp"
        environment.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "HOMEDRIVE": home.drive,
                "HOMEPATH": str(home)[len(home.drive):],
                "APPDATA": str(home / "AppData" / "Roaming"),
                "LOCALAPPDATA": str(home / "AppData" / "Local"),
                "TEMP": str(temp),
                "TMP": str(temp),
                "XDG_CONFIG_HOME": str(pi_root / "xdg" / "config"),
                "XDG_CACHE_HOME": str(pi_root / "xdg" / "cache"),
                "XDG_DATA_HOME": str(pi_root / "xdg" / "data"),
                "XDG_STATE_HOME": str(pi_root / "xdg" / "state"),
            }
        )
    return environment


def build_acp_launch(
    project_root: Path,
    *,
    model_id: str | None = None,
    request_runtime_root: Path | None = None,
) -> AcpLaunch:
    """Build a Pi ACP launch from the recipe-managed runtime.

    The provider descriptor's isolation policy remains authoritative; this
    adapter only declares the child command and does not alter concurrency.
    """
    executable = _managed_pi_acp(global_harness_runtime())
    args = ["--cwd", str(project_root.resolve())]
    environment: dict[str, str] = {}
    if request_runtime_root is not None:
        pi_root = request_runtime_root.resolve() / "pi"
        args.extend(["--session-dir", str(pi_root / "sessions")])
        environment = _request_environment(request_runtime_root)
    if model_id:
        args.extend(["--model", model_id])
    return AcpLaunch(executable=str(executable), args=tuple(args), environment=environment)
