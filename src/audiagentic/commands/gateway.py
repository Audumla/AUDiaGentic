"""Shared gateway keyword CLI.

Public routes parse before importing service/configuration owners. Help is pure.
The existing foreground shutdown/restart lifecycle is shared by serve routes.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
    )
    from audiagentic.components.agents.gateway.service.host import GatewayServiceHost


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

    if getattr(args, "shared_config", None) is not None:
        host = GatewayServiceHost.create(shared_config=args.shared_config)
    else:
        host = GatewayServiceHost.create(
            host=args.host,
            port=args.port,
            token_path=Path(args.token_file).resolve() if args.token_file else None,
        )
    # ``gateway serve`` is also used as the foreground development host.  It
    # must expose the same live restart contract as the detached managed host;
    # the process below re-execs itself only after the old host has completed
    # its durable handoff cleanup.
    host.lifecycle.restart_enabled = True
    print(f"gateway endpoint: {host.endpoint}")
    print(f"gateway token file: {host.token_path}")
    shutdown_state = _install_shutdown_signals(host)
    try:
        host.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        if host.lifecycle.restart_requested:
            os.environ["AUDIAGENTIC_GATEWAY_RESTART_HANDOFF"] = "1"
        host.close()
    if host.lifecycle.restart_requested:
        os.environ.pop("AUDIAGENTIC_GATEWAY_RESTART_HANDOFF", None)
        os.execv(
            sys.executable,
            [sys.executable, "-m", "audiagentic.launcher", *sys.argv[1:]],
        )
    return 1 if shutdown_state.forced_fallback else 0


# - SH10 lifecycle operators -

def _json_out(data: object) -> None:
    """Print redacted JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


__all__ = ["cmd_gateway", "dispatch_keyword"]


_KEYWORD_HELP = {
    "gateway": """Shared gateway commands (keyword syntax):
  audiagentic gateway help
  audiagentic gateway serve help
  audiagentic gateway serve config FILE
  audiagentic gateway status config FILE [output json]
  audiagentic gateway connect config FILE project PATH [dry-run|non-interactive]
  audiagentic gateway node revoke config FILE node ID revision N
  audiagentic gateway node revoke status config FILE operation OP_ID output json

node revoke queues local operator intent; its status reads the local queue.
serve runs an independent foreground service using a server configuration.
status reads remote health only; it never starts or controls a local service.
connect validates a connector and checks remote health before binding a project.
Use COMMAND help for configuration and credential details.
Retired lifecycle commands drain/resume/stop/recover are not public CLI routes.
Options beginning with -- are not accepted; use the keywords shown above.""",
    "node": """Local node operator commands (keyword syntax):
  audiagentic gateway node revoke config FILE node ID revision N
  audiagentic gateway node revoke status config FILE operation OP_ID output json

FILE is the shared SERVER configuration, not a connector or node config.
The existing loader validates it and resolves service-root relative to FILE.
If service-root is omitted, use the canonical managed-service default root.
Both commands use the existing local management-operation store only: no HTTP,
MCP, browser, provider, service startup or direct node-authority execution.

revoke queues NODE_REVOKE with node-id and expected-grant-revision. N is a
positive decimal integer (1 through 9223372036854775807). The existing service
pump applies the revision fence; accepted means queued, not yet revoked.
The command prints a redacted JSON receipt containing operation-id and state.
Use that operation-id with revoke status to inspect completion or failure.
Status is read-only with respect to operation intent; it never retries or pumps
work. Outputs omit configuration paths, credentials, selectors and owner facts.
Each revoke invocation creates a new operation ID; inspect an existing receipt
before submitting again. A missing operation or wrong kind fails explicitly.
Only keywords are supported; no -- flags or remote fallback.

Examples:
  audiagentic gateway node revoke config server.yaml node build-node revision 7
  audiagentic gateway node revoke status config server.yaml operation op_0123456789abcdef output json

Help:
  audiagentic gateway node help
  audiagentic gateway node revoke help
  audiagentic gateway node revoke status help""",
    "serve": """Usage: audiagentic gateway serve config FILE

Run the shared gateway in the foreground. FILE is the Agents server config:
server-id, host, port, service-root, projects and principals are validated by
the owning shared-config loader. Projects map IDs to server-local roots.
TLS and principal credentials are server-owned; never pass client roots.
SIGINT/SIGTERM (and SIGBREAK on Windows) use the existing stop/close lifecycle.
No application, harness, browser or provider starts when displaying help.""",
    "status": """Usage: audiagentic gateway status config FILE [output json]

FILE is an Agents connector config with an HTTPS endpoint, server-id,
project-id, token-file and ca-file. Tokens remain in their private files.
Uses the configured CA trust and authenticated shared-client health endpoint.
Read-only: no lease acquisition, local service discovery, startup or control.
output json emits the health response as JSON; default is human-readable.""",
    "connect": """Usage: audiagentic gateway connect config FILE project PATH [dry-run|non-interactive]

Validate the Agents connector FILE and handshake with its HTTPS gateway.
Connector fields: endpoint, server-id, project-id, token-file and ca-file.
PATH must be an existing local project directory; it is never sent as a remote
server project root. The connector project-id selects the server project.
dry-run checks configuration, credentials, CA trust and remote health without
persisting any binding. non-interactive explicitly requests binding persistence.
A persisted binding must use the Agents implementation configuration owner and
reference the connector file; inline tokens are never written or displayed.
Without either keyword, confirmation is required before persistence.""",
}


def _shared_client(config: Any) -> StandaloneGatewayClient:
    import ssl

    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    return StandaloneGatewayClient(
        config.endpoint,
        load_auth_token(config.token_file),
        shared_server_id=config.server_id,
        shared_project_id=config.project_id,
        ssl_context=ssl.create_default_context(cafile=str(config.ca_file) if config.ca_file else None),
    )


def dispatch_keyword(tokens: list[str]) -> int:
    """Closed keyword route; parse and help before importing any runtime owner."""
    from audiagentic.foundation.cli_io import print_error

    if not tokens or tokens == ["help"]:
        print(_KEYWORD_HELP["gateway"])
        return 0
    command = tokens[0]
    if command == "node":
        return _dispatch_node_keyword(tokens[1:])
    if command in _KEYWORD_HELP and tokens[1:] == ["help"]:
        print(_KEYWORD_HELP[command])
        return 0
    valid = command in {"serve", "status", "connect"}
    valid = valid and len(tokens) >= 3 and tokens[1] == "config"
    if valid:
        tail = tokens[3:]
        if command == "serve":
            valid = not tail
        elif command == "status":
            valid = tail in ([], ["output", "json"])
        else:
            valid = (len(tail) in {2, 3} and tail[0] == "project"
                     and (len(tail) == 2 or tail[2] in {"dry-run", "non-interactive"}))
    if not valid or any(token.startswith("--") for token in tokens):
        print_error("Invalid gateway syntax. Run: audiagentic gateway help")
        return 2
    config_path = Path(tokens[2]).resolve()
    from audiagentic.components.agents.gateway.service.shared_config import (
        load_shared_connector_config,
        load_shared_server_config,
    )

    if command == "serve":
        config = load_shared_server_config(config_path)
        return cmd_gateway(argparse.Namespace(gateway_cmd="serve", shared_config=config), Path.cwd())
    config = load_shared_connector_config(config_path)
    root = None
    if command == "connect":
        root = Path(tail[1]).resolve()
        if not root.is_dir():
            print_error("project PATH must be an existing directory")
            return 2
    client = _shared_client(config)
    try:
        health = client.health()
    finally:
        client.close()
    if command == "status":
        if tail:
            _json_out(health)
        else:
            for key, value in health.items():
                print(f"{key}: {value}")
        return 0
    if tail[-1] == "dry-run":
        print("Gateway connector validated; health handshake succeeded. No binding written.")
        return 0
    if tail[-1] != "non-interactive":
        try:
            accepted = input(f"Connect project {root} using {config_path}? [y/N] ").strip().lower()
        except (EOFError, OSError):
            accepted = ""
        if accepted not in {"y", "yes"}:
            print("Gateway connector not selected. No binding written.")
            return 1
    from audiagentic.components.agents.gateway.client import reset_gateway_client
    from audiagentic.components.agents.gateway.management_api import gateway_connect_config

    gateway_connect_config(root, config_path)
    reset_gateway_client()
    print("Gateway connector selected for project.")
    return 0



def _dispatch_node_keyword(tokens: list[str]) -> int:
    """Local operator adapter: queue intent and read status through owners."""
    import re
    import uuid

    from audiagentic.foundation.cli_io import print_error

    if tokens in ([], ["help"], ["revoke", "help"], ["revoke", "status", "help"]):
        print(_KEYWORD_HELP["node"])
        return 0
    status = (
        len(tokens) == 8 and tokens[:3] == ["revoke", "status", "config"]
        and tokens[4] == "operation" and tokens[6:] == ["output", "json"]
    )
    revoke = (
        len(tokens) == 7 and tokens[:2] == ["revoke", "config"]
        and tokens[3] == "node" and tokens[5] == "revision"
        and re.fullmatch(r"[0-9]{1,19}", tokens[6]) is not None
    )
    if (not status and not revoke) or any(token.startswith("--") for token in tokens):
        print_error("Invalid node operator syntax. Run: audiagentic gateway node help")
        return 2

    from audiagentic.components.agents.gateway.operations import (
        GatewayOperationsApplication,
        ManagementCommand,
        ManagementOperationKind,
        ManagementOperationStore,
    )
    from audiagentic.components.agents.gateway.operations.contracts import (
        validate_node_revoke_scope,
    )
    from audiagentic.components.agents.gateway.service.shared_config import (
        load_shared_server_config,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    scope = None
    if revoke:
        scope = validate_node_revoke_scope({
            "node-id": tokens[4], "expected-grant-revision": int(tokens[6]),
        })
    config = load_shared_server_config(Path(tokens[3] if status else tokens[2]).resolve())
    # Use the serving owner's canonical key and Foundation root resolution;
    # never create a second queue directly beneath the config's base directory.
    from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY
    from audiagentic.foundation.system.managed_service import ManagedServiceStore

    service = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root)
    store = ManagementOperationStore(service.root)
    if revoke:
        command = ManagementCommand(
            operation_id=f"op_{uuid.uuid4().hex}", kind=ManagementOperationKind.NODE_REVOKE,
            scope=scope,
        )
        record = store.create(command, local_only=True)
        operation_id = record["operation-id"]
    else:
        operation_id = tokens[5]
    result = GatewayOperationsApplication(store).get_operation(operation_id)
    if result["kind"] != ManagementOperationKind.NODE_REVOKE.value:
        raise AudiaGenticError("VAL-AGM-004", "agents", "operation is not a node-revoke operation", {})
    _json_out(result)
    return 0
