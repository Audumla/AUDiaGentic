"""Pi ACP bridge launch declaration for the shared ACP transport."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.transports import AcpLaunch


def _rpc_tap_shim_invocation() -> tuple[str, ...]:
    """Argv prefix that runs this same interpreter's rpc_tap_shim module.

    AS40: substituted ahead of the real `pi` command in the materialized
    wrapper so the wrapper execs the tee shim instead of `pi` directly. The
    shim then spawns the real `pi` (its argv is appended after this prefix)
    and fans its stdout through untouched while tapping a read-only copy.
    """
    return (sys.executable, "-m", "audiagentic.components.providers.adapters.pi.rpc_tap_shim")


def _materialize_pi_command_wrapper(
    request_runtime_root: Path,
    extra_args: tuple[str, ...],
    *,
    rpc_tap_enabled: bool = False,
) -> Path:
    """Create a request-owned command that pi-acp can invoke as its Pi RPC child.

    When `rpc_tap_enabled`, the wrapper execs the Python tee shim
    (`rpc_tap_shim`) with the real pi command and `extra_args` as its own
    argv, instead of exec'ing pi directly (AS40). Otherwise this is the
    original transparent passthrough wrapper (MCP isolation only).
    """
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
    command_prefix: tuple[str, ...] = (
        (*_rpc_tap_shim_invocation(), pi_command, *extra_args)
        if rpc_tap_enabled
        else (pi_command, *extra_args)
    )
    if os.name == "nt":
        wrapper = wrapper_root / "isolated-pi.cmd"
        quoted = [f'"{value.replace(chr(34), chr(34) * 2)}"' for value in command_prefix]
        content = "@echo off\r\n" + " ".join(quoted) + " %*\r\n"
    else:
        wrapper = wrapper_root / "isolated-pi"
        content = "#!/bin/sh\nexec " + " ".join(shlex.quote(value) for value in command_prefix) + ' "$@"\n'
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


def _seed_isolated_models_registry(agent_root: Path) -> None:
    """Copy the caller's managed Pi model registry into an isolated agent dir.

    build_acp_launch scopes PI_CODING_AGENT_DIR to a fresh, empty per-request
    directory (correct isolation — extensions/sessions/other mutable agent
    state must not leak across requests). Without this, pi-acp's session/new
    sees zero configured models and rejects with "Authentication required"
    before ever reaching a real prompt exchange, regardless of what models
    are actually configured. Mirrors
    agents/gateway/queue/worker.py::_replacement_environment, which solves
    the identical problem for the one-shot dispatch path — this is the
    session/ACP path's counterpart, kept here (not in generic gateway code)
    since it is pi-specific.
    """
    source_pi_dir = os.environ.get("PI_CODING_AGENT_DIR")
    source_models = (
        Path(source_pi_dir) / "models.json"
        if source_pi_dir
        else Path.home() / ".pi" / "agent" / "models.json"
    )
    if source_models.is_file():
        shutil.copy2(source_models, agent_root / "models.json")


def _request_environment(request_runtime_root: Path) -> dict[str, str]:
    pi_root = request_runtime_root.resolve() / "pi"
    agent_root = pi_root / "agent"
    agent_root.mkdir(parents=True, exist_ok=True)
    _seed_isolated_models_registry(agent_root)
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
    model_selector: str | None = None,
    provider_config: dict | None = None,
    request_runtime_root: Path | None = None,
    mcp_surface=None,
    enable_rpc_tap: bool = False,
) -> AcpLaunch:
    """Build a Pi ACP launch from the recipe-managed runtime.

    The provider descriptor's isolation policy remains authoritative; this
    adapter only declares the child command and does not alter concurrency.

    `enable_rpc_tap` (AS40): install the tee shim at the same PI_ACP_PI_COMMAND
    hook used for MCP isolation, and configure a per-request tap address/
    authkey in the returned environment. The caller must open a listener at
    that address (`rpc_tap_transport.open_tap_listener`) *before* spawning
    this launch -- `build_acp_launch` only declares the command, it does not
    itself open the listener or start the process.

    AS49: a resume passes THIS SAME session's original request_runtime_root
    back in (SessionRuntime reuses it rather than allocating a fresh one --
    see _resume_session), so pi-acp finds its own preserved session history
    without any special-casing here.
    """
    del provider_config
    argv = _system_pi_acp_argv()
    args = argv[1:] + ["--cwd", str(project_root.resolve())]
    environment: dict[str, str] = {}
    if request_runtime_root is not None:
        pi_root = request_runtime_root.resolve() / "pi"
        args.extend(["--session-dir", str(pi_root / "sessions")])
        environment = _request_environment(request_runtime_root)
    if enable_rpc_tap and request_runtime_root is None:
        raise make_error(
            prefix="UNS",
            component="PIACP",
            number=4,
            kind="pi-harness",
            message="Pi ACP RPC tap requires a request-owned runtime root",
        )
    if mcp_surface is not None or enable_rpc_tap:
        if mcp_surface is not None and (
            request_runtime_root is None or mcp_surface.applied_isolation != "exact"
        ):
            raise make_error(
                prefix="UNS",
                component="PIACP",
                number=3,
                kind="pi-harness",
                message="Pi ACP MCP isolation requires an exclusive request-owned surface",
            )
        extra_args = tuple(mcp_surface.extra_args) if mcp_surface is not None else ()
        wrapper = _materialize_pi_command_wrapper(
            request_runtime_root,
            extra_args,
            rpc_tap_enabled=enable_rpc_tap,
        )
        environment["PI_ACP_PI_COMMAND"] = str(wrapper)
        if enable_rpc_tap:
            from audiagentic.components.providers.adapters.pi.rpc_tap_shim import (
                TAP_ADDRESS_ENV,
                TAP_AUTHKEY_ENV,
            )
            from audiagentic.components.providers.adapters.pi.rpc_tap_transport import (
                tap_address,
            )

            environment[TAP_ADDRESS_ENV] = tap_address(request_runtime_root)
            environment[TAP_AUTHKEY_ENV] = os.urandom(32).hex()
    initial_config_options: dict[str, str | bool] = {}
    if model_id:
        # pi-acp does not support a ``--model`` command-line argument.  Its
        # standard ACP model selector is session/set_config_option, which is
        # applied by AcpSessionTransport before the first prompt. The gateway
        # supplies the already-admitted provider-qualified selector, so no
        # mutable config is read at provider-session open time.
        if not model_selector:
            raise make_error(
                prefix="VAL",
                component="PIACP",
                number=5,
                kind="pi-harness",
                message="Pi ACP requires an admitted provider-qualified model selector",
                details={"model-id": model_id},
            )
        if model_selector.rsplit("/", 1)[-1] != model_id:
            raise make_error(
                prefix="VAL",
                component="PIACP",
                number=6,
                kind="pi-harness",
                message="admitted Pi selector does not match its admitted model",
                details={"model-id": model_id},
            )
        initial_config_options["model"] = model_selector
    return AcpLaunch(
        executable=argv[0],
        args=tuple(args),
        environment=environment,
        initial_config_options=tuple(initial_config_options.items()),
    )
