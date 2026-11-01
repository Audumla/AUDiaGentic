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
  audiagentic gateway init [dir PATH] [project PATH] [dry-run]
  audiagentic gateway validate server|node|connector config FILE
  audiagentic gateway connect config FILE [dry-run|non-interactive]
  audiagentic gateway restart [non-interactive] [output json]
  audiagentic gateway drain [non-interactive] [output json]
  audiagentic gateway resume [output json]
  audiagentic gateway stop [force] [non-interactive] [output json]
  audiagentic gateway recover reason TEXT [non-interactive] [output json]
  audiagentic gateway node serve config FILE
  audiagentic gateway node serve help
  audiagentic gateway node revoke config FILE node ID revision N
  audiagentic gateway node revoke status config FILE operation OP_ID output json

restart replaces the machine's managed gateway service with one on the installed code: the running
service drains and starts its own replacement (no process is signalled), and the command waits until
the replacement answers. Do it after moving the runtime install. It asks first unless non-interactive.
node revoke queues local operator intent; its status reads the local queue.
serve runs an independent foreground service using a server configuration.
validate checks one role document offline: no service, network, token read or project binding.
status reads remote health only; it never starts or controls a local service.
connect validates a connector and checks remote health before selecting it for this machine.
Use COMMAND help for configuration and credential details.
drain/resume/stop/recover act on the already running service (they never start one). stop refuses while
work is in flight unless force; recover only records a failed owner and never signals a pid.
Agent sessions run the lifecycle commands only on an explicit operator request.
Options beginning with -- are not accepted; use the keywords shown above.""",
    "drain": """Drain the running gateway service (keyword syntax):
  audiagentic gateway drain [non-interactive] [output json]

The service stops admitting new work; in-flight work finishes. It acts on the running service only and
never starts one. Undo with resume. Asks first unless non-interactive. Explicit operator request only.""",
    "resume": """Resume a drained gateway service (keyword syntax):
  audiagentic gateway resume [output json]

The service admits new work again. It acts on the running service only and never starts one.""",
    "stop": """Stop the running gateway service (keyword syntax):
  audiagentic gateway stop [force] [non-interactive] [output json]

A graceful stop is refused while work is in flight; force stops anyway and reports the affected work.
No process is signalled by pid. Asks first unless non-interactive. Explicit operator request only.""",
    "recover": """Record recovery of an unprovable gateway owner (keyword syntax):
  audiagentic gateway recover reason TEXT [non-interactive] [output json]

For a recorded owner that is alive but cannot be proven: the record is marked failed under a new owner
epoch so a stale writer is fenced. No process is signalled or adopted, and it is refused while the owner
is provable (use stop). Asks first unless non-interactive. Explicit operator request only.""",
    "restart": """Restart the managed gateway service (keyword syntax):
  audiagentic gateway restart [non-interactive] [output json]

The running service drains in-flight work through its normal restart recovery and starts its own
replacement on the installed code; no process is signalled by pid. The command waits (bounded) until
the replacement is serving and then reports the old and new owner epochs. Without non-interactive
it asks for confirmation first, because every session using the shared gateway is affected.
Agent sessions do not run this on their own: it needs an explicit operator request.""",
    "node": """Local node operator commands (keyword syntax):
  audiagentic gateway node serve config FILE
  audiagentic gateway node serve help
  audiagentic gateway node revoke config FILE node ID revision N
  audiagentic gateway node revoke status config FILE operation OP_ID output json

node serve is experimental and uses NODE configuration; see node serve help.
For revoke/status, FILE is the shared SERVER configuration, not a node config.
The existing loader validates it and resolves service-root relative to FILE.
If service-root is omitted, use the canonical managed-service default root.
Both revoke commands use the existing local management-operation store only: no HTTP,
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
    "node-serve": """Usage: audiagentic gateway node serve config FILE

EXPERIMENTAL: explicit foreground recipient; native end-to-end qualification is
pending. Install the pinned transport extra: pip install 'audiagentic[node]'.
FILE is NODE YAML, never SERVER YAML (node revoke still takes SERVER YAML).
Required: schema-version: 1, node-id, server-id, endpoint, token-file, state-root,
workspaces. endpoint is wss://HOST/shared/v1/nodes/connect exactly: no userinfo,
query or fragment. Optional ca-file selects private CA trust; TLS verification
stays enabled. token-file is a private node credential, not a human credential;
never put token values in YAML, arguments or logs. Protect secrets and local state.
state-root and each workspace root must already exist; relative paths resolve
from FILE. workspaces maps IDs to {root: PATH, execution-profiles: [PROFILE]}.
Only allowed local profiles and configured workspaces can prepare isolated work;
read-only configuration/inspection grants do not authorize execution. This route
does not grant enrollment or access, attach to human sessions, or enable joins.
Native effect execution over this channel is NOT yet qualified against RV1232's
integration gates (DRAIN-vs-disabled-grant isolation, trusted terminal-from-intent
proof, protected output envelope validation). Do not point this at a production
grant or credential until that review closes.
SIGINT/SIGTERM/SIGBREAK request stop only. Shutdown waits for the retained producer;
repeated signals never kill it. Drain preserves historical receipts/ACK/artifacts.
A clean explicit stop exits 0, including after transient errors; exhausted retry
budget or deferred terminal boundaries exit nonzero. Retry uses finite fixed delay
and a stable-connection reset, not automatic prompt replay. A new boot requires a
new OS process: use explicit OS supervision, never same-process restart.
Help starts no endpoint, configuration loader, provider, catalog or application.""",
    "init": """Usage: audiagentic gateway init [dir PATH] [project PATH] [dry-run]

Generate a working same-machine shared gateway: server.yaml, connector.yaml and
credentials/operator.token in one directory (default: the gateway folder of the user
configuration directory). Ids and the token are generated, the token is a private file and
is never printed, and nothing existing is overwritten or rotated. The project (the current
checkout, or project PATH) gets a declared project.id in its tracked settings if it has none,
and this machine is bound to the generated connector (gateway.connector) when none is set.
Then run: audiagentic gateway serve config <dir>/server.yaml. dry-run writes nothing.""",
    "validate": """Usage: audiagentic gateway validate server|node|connector config FILE

Parse and validate one role document with the same loader the service uses, then print
"valid: ROLE". Nothing is started, no network is touched, token files are checked for
mode and identity but never read, and no project is bound. Failures print the registered
error code and message and exit 1.""",
    "serve": """Usage: audiagentic gateway serve config FILE

Run the shared gateway in the foreground. FILE is the Agents server config:
server-id, host, port, service-root, projects and principals are validated by
the owning shared-config loader. Projects map IDs to server-local roots.
TLS and principal credentials are server-owned; never pass client roots.
SIGINT/SIGTERM (and SIGBREAK on Windows) use the existing stop/close lifecycle.
No application, harness, browser or provider starts when displaying help.""",
    "status": """Usage: audiagentic gateway status config FILE [output json]

FILE is an Agents connector document (mode plain or shared). Tokens remain in their
private files. A shared connection addresses the current project's declared project.id.
Read-only: no lease acquisition, local service discovery, startup or control.
output json emits the health response as JSON; default is human-readable.""",
    "connect": """Usage: audiagentic gateway connect config FILE [dry-run|non-interactive]

Validate the connector FILE and handshake with its gateway, then select it for every
project on this machine: gateway.connector and gateway.implementation: standalone are
written to the user settings. Run it from a project with a declared project.id when the
connector is shared. Connector fields: mode plain (endpoint http://127.0.0.1:PORT,
token-file) or shared (endpoint https or http://127.0.0.1:PORT, server-id, token-file,
optional ca-file). dry-run checks and handshakes without writing. non-interactive
writes without asking. Inline tokens are never written or displayed.""",
}


_LIFECYCLE_PROMPTS = {
    "restart": "Restart the shared gateway service? In-flight work drains first and every session using it is "
               "briefly interrupted. [y/N] ",
    "drain": "Drain the shared gateway service? It stops admitting new work for every session until resumed. [y/N] ",
    "stop": "Stop the shared gateway service? Every session using it loses it until it is started again. [y/N] ",
    "recover": "Record recovery of the unprovable gateway owner? No process is signalled. [y/N] ",
}


def _dispatch_lifecycle(command: str, tail: list[str]) -> int:
    """``gateway restart|drain|resume|stop|recover``: thin adapters over the management API."""
    from audiagentic.foundation.cli_io import print_error

    rest = list(tail)
    non_interactive = "non-interactive" in rest
    if non_interactive:
        rest.remove("non-interactive")
    as_json = rest[-2:] == ["output", "json"]
    if as_json:
        rest = rest[:-2]
    force = command == "stop" and "force" in rest
    if force:
        rest.remove("force")
    reason = None
    if command == "recover" and len(rest) >= 2 and rest[0] == "reason":
        reason = " ".join(rest[1:])
        rest = []
    if rest or (command == "recover" and not reason) or any(token.startswith("--") for token in tail):
        print_error("Invalid gateway syntax. Run: audiagentic gateway help")
        return 2
    if command in _LIFECYCLE_PROMPTS and not non_interactive and command != "resume":
        if input(_LIFECYCLE_PROMPTS[command]).strip().lower() not in {"y", "yes"}:
            print(f"Not {command}ed." if command != "stop" else "Not stopped.")
            return 1
    from audiagentic.components.agents.gateway import management_api
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        if command == "restart":
            result = management_api.gateway_restart(Path.cwd())
        elif command == "drain":
            result = management_api.gateway_drain(Path.cwd())
        elif command == "resume":
            result = management_api.gateway_resume(Path.cwd())
        elif command == "stop":
            result = management_api.gateway_stop(Path.cwd(), force=force)
        else:
            result = management_api.gateway_recover(reason=str(reason))
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if as_json:
        _json_out(result)
        return 0
    if command == "restart":
        old = (result.get("restarting") or {}).get("owner-epoch")
        new = (result.get("status") or {}).get("owner-epoch")
        print(f"gateway service restarted: owner epoch {str(old)[:8]} -> {str(new)[:8]}, state "
              f"{(result.get('status') or {}).get('state', 'unknown')}")
    else:
        print(f"gateway {command}: {json.dumps(result, default=str)}")
    return 0


def dispatch_keyword(tokens: list[str]) -> int:
    """Closed keyword route; parse and help before importing any runtime owner."""
    from audiagentic.foundation.cli_io import print_error

    if not tokens or tokens == ["help"]:
        print(_KEYWORD_HELP["gateway"])
        return 0
    command = tokens[0]
    if command == "node":
        return _dispatch_node_keyword(tokens[1:])
    if command == "validate" and tokens[1:] != ["help"]:
        return _dispatch_validate(tokens[1:])
    if command == "init" and tokens[1:] != ["help"]:
        return _dispatch_init(tokens[1:])
    if command in _LIFECYCLE_PROMPTS | {"resume": ""} and tokens[1:] != ["help"]:
        return _dispatch_lifecycle(command, tokens[1:])
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
            valid = tail in ([], ["dry-run"], ["non-interactive"])
    if not valid or any(token.startswith("--") for token in tokens):
        print_error("Invalid gateway syntax. Run: audiagentic gateway help")
        return 2
    config_path = Path(tokens[2]).resolve()
    if command == "serve":
        from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config

        config = load_shared_server_config(config_path)
        return cmd_gateway(argparse.Namespace(gateway_cmd="serve", shared_config=config), Path.cwd())
    from audiagentic.components.agents.gateway import management_api
    from audiagentic.foundation.config.settings import discover_project_root

    health = management_api.gateway_connector_health(config_path, discover_project_root(None))
    if command == "status":
        if tail:
            _json_out(health)
        else:
            for key, value in health.items():
                print(f"{key}: {value}")
        return 0
    if tail == ["dry-run"]:
        print("Gateway connector validated; health handshake succeeded. Nothing written.")
        return 0
    if tail != ["non-interactive"]:
        try:
            accepted = input(f"Use {config_path} for every project on this machine? [y/N] ").strip().lower()
        except (EOFError, OSError):
            accepted = ""
        if accepted not in {"y", "yes"}:
            print("Gateway connector not selected. Nothing written.")
            return 1
    from audiagentic.components.agents.gateway.client import reset_gateway_client

    management_api.gateway_connect_config(config_path)
    reset_gateway_client()
    print("Gateway connector selected for this machine (gateway.connector, gateway.implementation: standalone).")
    return 0


def _dispatch_init(tokens: list[str]) -> int:
    """``init [dir PATH] [project PATH] [dry-run]``: parse, delegate, print."""
    from audiagentic.foundation.cli_io import print_error

    options: dict[str, str] = {}
    rest = list(tokens)
    dry_run = False
    while rest:
        word = rest.pop(0)
        if word == "dry-run" and not dry_run:
            dry_run = True
        elif word in ("dir", "project") and word not in options and rest and not rest[0].startswith("--"):
            options[word] = rest.pop(0)
        else:
            print_error("Invalid gateway init syntax. Run: audiagentic gateway init help")
            return 2
    from audiagentic.components.agents.gateway import management_api
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        result = management_api.gateway_init(
            directory=Path(options["dir"]) if "dir" in options else None,
            project=Path(options["project"]) if "project" in options else None,
            dry_run=dry_run,
        )
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    print(f"gateway setup: {result['state']}")
    print(f"directory: {result['directory']}")
    for path in result["files"]:
        print(f"  {path}")
    print(f"project: {result['project-id']} ({result['project-root']})"
          + (" - project.id " + ("will be written" if result.get("project-id-would-write") else "declared")
             if dry_run else (" - project.id written" if result["project-id-written"] else "")))
    print(f"binding: {result['binding']} - {result['binding-note']}")
    if not dry_run:
        print(f"next: audiagentic gateway serve config {Path(result['directory']) / 'server.yaml'}")
    return 0


def _dispatch_validate(tokens: list[str]) -> int:
    """Offline check of one role document through its owning loader."""
    from audiagentic.foundation.cli_io import print_error

    if len(tokens) != 3 or tokens[0] not in {"server", "node", "connector"} or tokens[1] != "config" \
            or any(token.startswith("--") for token in tokens):
        print_error("Invalid gateway validate syntax. Run: audiagentic gateway validate help")
        return 2
    from audiagentic.components.agents.gateway import management_api
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        management_api.gateway_validate_role_config(tokens[0], Path(tokens[2]))
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    print(f"valid: {tokens[0]}")
    return 0


def _dispatch_node_keyword(tokens: list[str]) -> int:
    """Local operator adapter: queue intent and read status through owners."""
    import re
    import uuid

    from audiagentic.foundation.cli_io import print_error

    if tokens == ["serve", "help"]:
        print(_KEYWORD_HELP["node-serve"])
        return 0
    if tokens and tokens[0] == "serve":
        if (len(tokens) != 3 or tokens[1] != "config"
                or any(token.startswith("--") for token in tokens)):
            print_error("Invalid node serve syntax. Run: audiagentic gateway node serve help")
            return 2
        return _serve_node(Path(tokens[2]))
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
        ManagementOperationKind,
    )
    from audiagentic.components.agents.gateway.service.shared_config import (
        load_shared_server_config,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    config = load_shared_server_config(Path(tokens[3] if status else tokens[2]).resolve())
    application = GatewayOperationsApplication.for_local_server(config)
    if revoke:
        record = application.create_local_node_revoke(
            operation_id=f"op_{uuid.uuid4().hex}", node_id=tokens[4],
            expected_grant_revision=int(tokens[6]),
        )
        operation_id = record["operation-id"]
    else:
        operation_id = tokens[5]
    result = application.get_operation(operation_id)
    if result["kind"] != ManagementOperationKind.NODE_REVOKE.value:
        raise AudiaGenticError("VAL-AGM-004", "agents", "operation is not a node-revoke operation", {})
    _json_out(result)
    return 0


def _serve_node(config_path: Path) -> int:
    """Explicit process composition root, reached only after closed parsing."""
    import asyncio

    from audiagentic.components.agents.gateway.node.contracts import invalid
    from audiagentic.components.agents.gateway.service.shared_config import load_shared_node_config
    from audiagentic.foundation.cli_io import print_error

    try:
        import websockets
        if websockets.__version__.partition(".")[0] != "15":
            raise ImportError
        from audiagentic.components.agents.gateway.node.host import NodeRecipientHost
    except ImportError:
        raise invalid(1, "Node serve requires websockets>=15,<16; install with pip install 'audiagentic[node]'") from None

    from audiagentic.runtime.component_context import collect_component_context

    config = load_shared_node_config(config_path.resolve())
    host = NodeRecipientHost.create(config, component_context_reader=collect_component_context)
    previous = {}

    def stop_only(_signum, _frame):
        host.request_stop()

    try:
        for sig in _shutdown_signals():
            with contextlib.suppress(OSError, ValueError):
                old = signal.getsignal(sig)
                signal.signal(sig, stop_only)
                previous[sig] = old
        outcome = asyncio.run(host.run())
    finally:
        for sig, handler in previous.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, handler)
    if outcome.disposition == "stopped":
        return 0
    cause = outcome.terminal_cause
    stage = cause.details.get("stage")
    reason = cause.details.get("reason-code")
    print_error(f"Node recipient {outcome.disposition}: {cause.code} ({stage}/{reason})")
    return 1
