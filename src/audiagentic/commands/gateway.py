"""Explicit standalone gateway service command and lifecycle CLI (SH10 Slice A).

This module owns ``gateway serve`` (existing) and the SH10 operator lifecycle
sub-commands: ``status``, ``drain``, ``resume``, ``stop [--force]``, and
``recover [--confirm] [--reason]``.  Lifecycle handlers dispatch exactly once
through the standalone gateway client (HTTP) or the record-only recovery
helper; they contain no lifecycle/store/signal logic.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
    )


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
    try:
        host.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        host.close()
    return 0


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
