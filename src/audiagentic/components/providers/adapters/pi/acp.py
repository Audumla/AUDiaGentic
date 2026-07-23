"""Pi ACP bridge launch declaration for the shared ACP transport."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.transports import AcpLaunch


def _materialize_pi_command_wrapper(
    request_runtime_root: Path,
    extra_args: tuple[str, ...],
) -> Path:
    """Create a request-owned command that pi-acp can invoke as its Pi RPC child."""
    from audiagentic.foundation.io import atomic_write_text

    pi_command = shutil.which("pi")
    if pi_command is None:
        raise make_error(
            prefix="RES",
            component="PIACP",
            number=2,
            kind="pi-harness",
            message="Pi CLI not found while preparing isolated Pi ACP launch",
        )
    wrapper_root = request_runtime_root.resolve() / "pi" / "acp"
    if os.name == "nt":
        wrapper = wrapper_root / "isolated-pi.cmd"
        quoted = [f'"{value.replace(chr(34), chr(34) * 2)}"' for value in (pi_command, *extra_args)]
        content = "@echo off\r\n" + " ".join(quoted) + " %*\r\n"
    else:
        wrapper = wrapper_root / "isolated-pi"
        content = "#!/bin/sh\nexec " + " ".join(shlex.quote(value) for value in (pi_command, *extra_args)) + ' "$@"\n'
    atomic_write_text(wrapper, content)
    if os.name != "nt":
        wrapper.chmod(0o700)
    return wrapper


def _system_pi_acp_argv() -> list[str]:
    """Resolve the system-installed pi-acp bridge (PATH, else npx)."""
    from audiagentic.components.providers.adapters.pi.system import resolve_system_pi_acp_argv

    argv = resolve_system_pi_acp_argv()
    if argv is None:
        raise make_error(
            prefix="RES",
            component="PIACP",
            number=1,
            kind="pi-harness",
            message=(
                "pi-acp bridge not found on the system. Install pi-acp (or "
                "npx) so AUDiaGentic can launch the Pi ACP bridge."
            ),
            details={"hint": "npm i -g pi-acp, or ensure npx is on PATH"},
        )
    return argv


def _request_environment(request_runtime_root: Path) -> dict[str, str]:
    pi_root = request_runtime_root.resolve() / "pi"
    agent_root = pi_root / "agent"
    agent_root.mkdir(parents=True, exist_ok=True)
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
    mcp_surface=None,
) -> AcpLaunch:
    """Build a Pi ACP launch from the recipe-managed runtime.

    The provider descriptor's isolation policy remains authoritative; this
    adapter only declares the child command and does not alter concurrency.
    """
    argv = _system_pi_acp_argv()
    args = argv[1:] + ["--cwd", str(project_root.resolve())]
    environment: dict[str, str] = {}
    if request_runtime_root is not None:
        pi_root = request_runtime_root.resolve() / "pi"
        args.extend(["--session-dir", str(pi_root / "sessions")])
        environment = _request_environment(request_runtime_root)
    if mcp_surface is not None:
        if request_runtime_root is None or mcp_surface.applied_isolation != "exact":
            raise make_error(
                prefix="UNS",
                component="PIACP",
                number=3,
                kind="pi-harness",
                message="Pi ACP MCP isolation requires an exclusive request-owned surface",
            )
        wrapper = _materialize_pi_command_wrapper(
            request_runtime_root,
            tuple(mcp_surface.extra_args),
        )
        environment["PI_ACP_PI_COMMAND"] = str(wrapper)
    if model_id:
        args.extend(["--model", model_id])
    return AcpLaunch(executable=argv[0], args=tuple(args), environment=environment)
