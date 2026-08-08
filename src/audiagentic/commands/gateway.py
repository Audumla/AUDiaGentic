"""Explicit standalone gateway service command and lifecycle CLI (SH10 Slice A).

This module owns ``gateway serve`` (existing) and the SH10 operator lifecycle
sub-commands: ``status``, ``drain``, ``resume``, ``stop [--force]``, and
``recover [--confirm] [--reason]``.  Lifecycle handlers dispatch exactly once
through the standalone gateway client (HTTP) or the record-only recovery
helper; they contain no lifecycle/store/signal logic.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
    )
    from audiagentic.components.agents.gateway.service.host import GatewayServiceHost


def _standalone_client_from_env() -> StandaloneGatewayClient:
    """Build a StandaloneGatewayClient from environment (same env as get_gateway_client)."""
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    endpoint = os.environ.get("AUDIAGENTIC_GATEWAY_ENDPOINT")
    token_file = os.environ.get("AUDIAGENTIC_GATEWAY_TOKEN_FILE")
    if not endpoint or not token_file:
        print(
            "error: standalone gateway client requires "
            "AUDIAGENTIC_GATEWAY_ENDPOINT and AUDIAGENTIC_GATEWAY_TOKEN_FILE",
            file=sys.stderr,
        )
        sys.exit(1)
    return StandaloneGatewayClient(endpoint, load_auth_token(Path(token_file)))


# - serve (existing) -


class _ShutdownState:
    """Mutable flag set by the signal handler, read after serve_forever() returns.

    A plain attribute container rather than a bool local: the handler is a
    closure invoked asynchronously by the interpreter's signal machinery, so
    it needs a mutable object to record onto, not a rebound name.
    """

    def __init__(self) -> None:
        self.forced_fallback = False


def _shutdown_signals() -> list[int]:
    """SIGINT/SIGTERM always; SIGBREAK too on Windows (CTRL_CLOSE/taskkill
    maps there, not to SIGTERM). A hard TerminateProcess/-9 runs no handler —
    that is covered by the next start's owner-claim liveness check and SH07
    recovery, not by anything here."""
    sigs = [signal.SIGINT, signal.SIGTERM]
    win_break = getattr(signal, "SIGBREAK", None)
    if win_break is not None:
        sigs.append(win_break)
    return sigs


def _install_shutdown_signals(host: GatewayServiceHost) -> _ShutdownState:
    """Drain-first signal handling for the serving process (SH10 Slice B).

    Refuse-force semantics make no sense on an OS kill signal -- there is no
    interactive way to "drain first" in response to SIGTERM, so this goes
    straight to a forced stop. If that itself fails for some reason, fall
    back to a raw server shutdown so the process still exits rather than
    hanging on a broken lifecycle path.
    """
    state = _ShutdownState()

    def _handler(signum: int, _frame: object) -> None:
        del signum
        try:
            if host.lifecycle is not None:
                host.lifecycle.request_stop(force=True)
            else:
                host.shutdown()
        except Exception:
            state.forced_fallback = True
            with contextlib.suppress(Exception):
                host.shutdown()

    for sig in _shutdown_signals():
        with contextlib.suppress(OSError, ValueError):
            signal.signal(sig, _handler)
    return state


def cmd_gateway(args: argparse.Namespace, project_root: Path) -> int:
    del project_root
    if args.gateway_cmd != "serve":
        raise ValueError(f"unsupported gateway command: {args.gateway_cmd}")
    from audiagentic.components.agents.gateway.service.host import GatewayServiceHost

    host = GatewayServiceHost.create(
        host=args.host,
        port=args.port,
        token_path=Path(args.token_file).resolve() if args.token_file else None,
    )
    print(f"gateway endpoint: {host.endpoint}")
    print(f"gateway token file: {host.token_path}")
    shutdown_state = _install_shutdown_signals(host)
    try:
        host.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        host.close()
    return 1 if shutdown_state.forced_fallback else 0


# - SH10 lifecycle operators -

def _json_out(data: object) -> None:
    """Print redacted JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def cmd_gateway_status(args: argparse.Namespace, project_root: Path) -> int:
    """gateway status - query service state via HTTP client."""
    client = _standalone_client_from_env()
    try:
        result = client.service_status(project_root)
    finally:
        client.close()
    _json_out(result)
    return 0


def cmd_gateway_drain(args: argparse.Namespace, project_root: Path) -> int:
    """gateway drain - begin graceful drain via HTTP client."""
    del args
    client = _standalone_client_from_env()
    try:
        result = client.service_drain(project_root)
    finally:
        client.close()
    _json_out(result)
    return 0


def cmd_gateway_resume(args: argparse.Namespace, project_root: Path) -> int:
    """gateway resume - cancel draining via HTTP client."""
    del args
    client = _standalone_client_from_env()
    try:
        result = client.service_resume(project_root)
    finally:
        client.close()
    _json_out(result)
    return 0


def cmd_gateway_stop(args: argparse.Namespace, project_root: Path) -> int:
    """gateway stop [--force] - request operator stop via HTTP client."""
    client = _standalone_client_from_env()
    try:
        result = client.service_stop(project_root, force=args.force)
    finally:
        client.close()
    _json_out(result)
    return 0


def cmd_gateway_recover(args: argparse.Namespace, project_root: Path) -> int:
    """gateway recover - record-only dead-owner recovery (never HTTP).

    Deliberately bypasses the HTTP client because recovery targets a
    dead/unprovable service; it goes straight to the store via the
    lifecycle module.
    """
    from audiagentic.components.agents.gateway.service.lifecycle import (
        recover_unprovable_owner,
    )

    result = recover_unprovable_owner(
        service_root=project_root,
        confirm=args.confirm,
        reason=args.reason,
    )
    _json_out(result)
    return 0


__all__ = [
    "cmd_gateway",
    "cmd_gateway_drain",
    "cmd_gateway_recover",
    "cmd_gateway_resume",
    "cmd_gateway_status",
    "cmd_gateway_stop",
]
