"""Public in-process client for the agent execution gateway.

Inbound surfaces depend on this module, never on the gateway implementation
modules.  SH03 keeps the current in-process control plane, but makes the
client boundary explicit so a later local-service client can implement the
same operations without changing MCP or event adapters.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from audiagentic.components.agents.gateway.application import (
    GatewayApplication,
    get_gateway_application,
)

logger = logging.getLogger(__name__)


def validate_node_selectors(node_id: Any, workspace_id: Any) -> tuple[str, str]:
    """Validate an explicit pair of configured IDs without resolving files or clients."""
    if not all(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value)
               for value in (node_id, workspace_id)):
        from audiagentic.foundation.contracts.errors import make_error_factory

        raise make_error_factory("VAL", "AGSV", "gateway-service")(
            22, "node_id and workspace_id require a complete pair of configured IDs, not paths"
        )
    return node_id, workspace_id


def _uses_shared_connector(root: Path) -> bool:
    """Inspect selection only; never construct or discover a gateway client."""
    if _resolve_implementation_id(root)[0] != "standalone":
        return False
    path = _connector_path()
    if path is None:
        return False
    from .service.shared_config import load_shared_connector_config

    try:
        return load_shared_connector_config(path).mode == "shared"
    except Exception:  # noqa: BLE001 - routing never fails on a bad document; get_gateway_client reports it
        return False


def resolve_request_project_root(root: Path, request_id: str) -> Path:
    """Route a project-scoped request using the public client boundary."""
    if _uses_shared_connector(root):
        return root
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    from . import store as gateway_store
    from .api import _resolve_workspace_project_root
    if not isinstance(request_id, str) or not request_id.startswith("req_"):
        return root
    parts = request_id.split("_")
    if len(parts) < 3 or len(parts[-1]) != 12 or any(
        character not in "0123456789abcdef" for character in parts[-1].casefold()
    ):
        return root
    # The project slug is not necessarily unique across configured worktrees
    # (for example, a main checkout and a detached Codex worktree can share
    # project-id/project-name). Prefer the durable request record, which is
    # authoritative and already carries the exact project root, before using
    # the human-readable slug resolver.
    from .workspace_roots import configured_workspace_roots

    configured = configured_workspace_roots()
    if configured:
        candidates = configured
    else:
        candidates = [root]
        if root.parent.is_dir():
            candidates.extend(
                child.resolve()
                for child in root.parent.iterdir()
                if child.is_dir() and child.resolve() != root
            )
    matches: list[Path] = []
    for candidate in dict.fromkeys(candidates):
        try:
            gateway_store.read_record(candidate, request_id)
        except AudiaGenticError as exc:
            if exc.code == "RES-AGW-001":
                continue
            raise
        matches.append(candidate)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AudiaGenticError(
            code="VAL-AGW-152",
            kind="agents",
            message="gateway request id is ambiguous across project checkouts",
            details={"request-id": request_id, "project-roots": [str(path) for path in matches]},
        )
    return _resolve_workspace_project_root(root, "_".join(parts[1:-1]))


def resolve_session_project_root(root: Path, session_id: str) -> Path:
    """Find the owning checkout for a session before dispatching resume.

    Session IDs are intentionally opaque and therefore cannot encode a
    project slug.  The MCP process may nevertheless serve sibling checkouts;
    probing their durable session records avoids routing resume through the
    process CWD.  Multiple matches fail closed rather than selecting a
    session from the wrong project.
    """
    if _uses_shared_connector(root):
        return root
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    from .session import sessions_store

    root = root.resolve()
    from .workspace_roots import configured_workspace_roots

    configured = configured_workspace_roots()
    if configured:
        candidates = configured
    else:
        parent = root.parent
        candidates = [root]
        if parent.is_dir():
            candidates.extend(
                child.resolve()
                for child in parent.iterdir()
                if child.is_dir() and child.resolve() != root
            )

    matches: list[Path] = []
    for candidate in dict.fromkeys(candidates):
        try:
            sessions_store.read_session_record(candidate, session_id)
        except AudiaGenticError as exc:
            if exc.code == "RES-AGW-002":
                continue
            raise
        matches.append(candidate)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AudiaGenticError(
            code="VAL-AGW-152",
            kind="agents",
            message="gateway session id is ambiguous across project checkouts",
            details={"session-id": session_id, "project-roots": [str(path) for path in matches]},
        )
    return root

_COMPONENT_ID = "agents"


class GatewayClient(Protocol):
    """Requester-facing gateway operations, independent of inbound transport."""

    def list_agent_definition_cards(self, project_root: Path) -> list[dict[str, Any]]: ...

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]: ...
    def get_execution_request(self, project_root: Path, request_id: str, *, include_response: bool = False) -> dict[str, Any]: ...
    def get_execution_diagnostics(self, project_root: Path, request_id: str, *, limit: int = 25) -> dict[str, Any]: ...
    def get_execution_observations(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_execution_evidence(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def replay_execution_observations(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def recover_execution_request(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]: ...

    def get_execution_response_payload(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def get_execution_response(self, project_root: Path, request_id: str) -> str: ...
    def get_execution_failure_response(self, project_root: Path, request_id: str) -> str: ...
    def focus_execution_chat(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def complete_execution_from_provider(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def wait_execution_request(
        self,
        project_root: Path,
        request_id: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]: ...
    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def run_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]: ...
    def request_runtime_status(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def list_execution_requests(
        self, project_root: Path, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    def gateway_overview(self, project_root: Path) -> dict[str, Any]: ...
    def list_execution_sessions(
        self, project_root: Path, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    def close_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]: ...
    def purge_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]: ...
    def purge_execution_sessions(
        self,
        project_root: Path,
        *,
        dry_run: bool = True,
        session_ids: list[str] | None = None,
    ) -> dict[str, Any]: ...
    def control_execution_session(
        self, project_root: Path, session_id: str, **kwargs: Any
    ) -> dict[str, Any]: ...
    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]: ...
    def open_agent_context(self, project_root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]: ...
    def get_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]: ...
    def list_agent_contexts(self, project_root: Path) -> list[dict[str, Any]]: ...
    def close_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]: ...
    def submit_agent_work(self, project_root: Path, context_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def submit_agent_work_child(self, project_root: Path, parent_work_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def get_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]: ...
    def list_agent_work(self, project_root: Path) -> list[dict[str, Any]]: ...
    def add_agent_work_message(self, project_root: Path, work_id: str, message: dict[str, Any]) -> dict[str, Any]: ...
    def cancel_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]: ...
    def read_agent_work_output(self, project_root: Path, work_id: str) -> dict[str, Any]: ...


class EmbeddedGatewayClient:
    """SH03 backend adapter for the in-process control plane (SH11: renamed
    from InProcessGatewayClient -- "embedded" is the component-implementation
    id; no compatibility alias kept, per this migration's no-legacy stance)."""

    def __init__(
        self,
        application: GatewayApplication | None = None,
        *,
        logical_client_id: str | None = None,
    ) -> None:
        self._application = application or get_gateway_application()
        self._logical_client_id = logical_client_id

    def list_agent_definition_cards(self, project_root: Path) -> list[dict[str, Any]]:
        from audiagentic.components.agents.configuration.management import (
            list_agent_definition_cards,
        )

        return list_agent_definition_cards(project_root)

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        if self._logical_client_id is not None:
            kwargs.setdefault("logical_client_id", self._logical_client_id)
        return self._application.submit_execution_request(project_root, **kwargs)

    def get_execution_request(self, project_root: Path, request_id: str, *, include_response: bool = False) -> dict[str, Any]:
        if include_response:
            return self._application.get_execution_request(project_root, request_id, include_response=True)
        return self._application.get_execution_request(project_root, request_id)

    def get_execution_observations(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._application.get_execution_observations(project_root, request_id, **kwargs)

    def get_execution_evidence(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._application.get_execution_evidence(project_root, request_id, **kwargs)

    def get_execution_diagnostics(self, project_root: Path, request_id: str, *, limit: int = 25) -> dict[str, Any]:
        return self._application.get_execution_diagnostics(project_root, request_id, limit=limit)

    def replay_execution_observations(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.replay_execution_observations(project_root, request_id)

    def recover_execution_request(self, project_root: Path, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._application.recover_execution_request(project_root, request_id, **kwargs)

    def get_execution_response_payload(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.get_execution_response_payload(project_root, request_id)

    def get_execution_response(self, project_root: Path, request_id: str) -> str:
        return self._application.get_execution_response(project_root, request_id)

    def get_execution_failure_response(self, project_root: Path, request_id: str) -> str:
        return self._application.get_execution_failure_response(project_root, request_id)

    def focus_execution_chat(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.focus_execution_chat(project_root, request_id)

    def complete_execution_from_provider(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.complete_execution_from_provider(project_root, request_id)

    def wait_execution_request(
        self,
        project_root: Path,
        request_id: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._application.wait_execution_request(project_root, request_id, timeout_seconds)

    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.cancel_execution_request(project_root, request_id)

    def request_runtime_status(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.request_runtime_status(project_root, request_id)

    def run_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._application.run_execution_request(project_root, **kwargs)

    def list_execution_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._application.list_execution_requests(project_root, **kwargs)

    def gateway_overview(self, project_root: Path) -> dict[str, Any]:
        return self._application.gateway_overview(project_root)

    def list_execution_sessions(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return self._application.list_execution_sessions(project_root, **kwargs)

    def close_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return self._application.close_execution_session(project_root, session_id)

    def purge_execution_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return self._application.purge_execution_session(project_root, session_id)

    def purge_execution_sessions(
        self,
        project_root: Path,
        *,
        dry_run: bool = True,
        session_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._application.purge_execution_sessions(
            project_root, dry_run=dry_run, session_ids=session_ids
        )

    def control_execution_session(
        self, project_root: Path, session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._application.control_execution_session(project_root, session_id, **kwargs)

    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._application.resume_execution_session(project_root, source_session_id, **kwargs)

    def open_agent_context(self, project_root: Path, agent_id: str, title: str | None = None) -> dict[str, Any]:
        return self._application.open_agent_context(project_root, agent_id, title)

    def get_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]:
        return self._application.get_agent_context(project_root, context_id)

    def list_agent_contexts(self, project_root: Path) -> list[dict[str, Any]]:
        return self._application.list_agent_contexts(project_root)

    def close_agent_context(self, project_root: Path, context_id: str) -> dict[str, Any]:
        return self._application.close_agent_context(project_root, context_id)

    def submit_agent_work(self, project_root: Path, context_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self._application.submit_agent_work(project_root, context_id, message, **kwargs)

    def submit_agent_work_child(self, project_root: Path, parent_work_id: str, message: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self._application.submit_agent_work_child(project_root, parent_work_id, message, **kwargs)

    def get_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]:
        return self._application.get_agent_work(project_root, work_id)

    def list_agent_work(self, project_root: Path) -> list[dict[str, Any]]:
        return self._application.list_agent_work(project_root)

    def add_agent_work_message(self, project_root: Path, work_id: str, message: dict[str, Any]) -> dict[str, Any]:
        return self._application.add_agent_work_message(project_root, work_id, message)

    def cancel_agent_work(self, project_root: Path, work_id: str) -> dict[str, Any]:
        return self._application.cancel_agent_work(project_root, work_id)

    def read_agent_work_output(self, project_root: Path, work_id: str) -> dict[str, Any]:
        return self._application.read_agent_work_output(project_root, work_id)


_CLIENT_LOCK = threading.Lock()
_CLIENT: GatewayClient | None = None
_CLIENT_CONFIG: tuple[Any, ...] | None = None


def _has_live_provable_shared_owner() -> bool:
    """Read-only: does a live, provable shared gateway service already own
    this machine's gateway record? Reuses the exact ownership-proof logic
    ``ManagedServiceOwner.claim()`` uses to refuse a second owner
    (``foundation.system.managed_service_owner._reject_live_owner``) --
    this is its read-only counterpart: observe, never claim or mutate."""
    from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY
    from audiagentic.foundation.system.managed_process import observe_process, ownership_matches
    from audiagentic.foundation.system.managed_service import ManagedServiceStore

    store = ManagedServiceStore(GATEWAY_SERVICE_KEY)
    if not store.record_path.exists():
        return False
    record = store.read()
    if record.process is None or record.state not in ("running", "draining"):
        return False
    observed = observe_process(record.process)
    return observed is not None and ownership_matches(record.process, observed)


def _resolve_embedded_coexistence_policy(project_root: Path | None) -> str:
    """"warn" or "refuse" when a live shared owner exists (SH11 Slice D).

    The project's ``embedded`` implementation config, else the descriptor
    default (``refuse``, per RV736 A6 -- silent coexistence beside a shared
    owner is the exact dual-ownership bug this boundary exists to prevent).
    """
    if project_root is not None:
        from audiagentic.components.agents.gateway.management_api import gateway_get_config

        config = gateway_get_config(project_root, "embedded")
        policy = config.get("config", {}).get("allow-with-live-shared-owner")
        if policy:
            return str(policy)
    return "refuse"


def connector_client(connector: Any, project_root: Path | None, project_id: str | None):
    """The standalone client a loaded connector document describes."""
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    token = load_auth_token(connector.token_file)
    if connector.mode == "plain":
        return StandaloneGatewayClient(connector.endpoint, token)
    ssl_context = None
    if connector.endpoint.startswith("https://"):
        import ssl

        ssl_context = ssl.create_default_context(cafile=str(connector.ca_file) if connector.ca_file else None)
    return StandaloneGatewayClient(
        connector.endpoint, token,
        shared_server_id=connector.server_id, shared_project_id=project_id,
        **({"shared_source_node_config": connector.source_node_config_file,
            "shared_caller_root": project_root}
           if connector.source_node_config_file is not None else {}),
        ssl_context=ssl_context,
    )


def _declared_project_id(project_root: Path | None) -> str | None:
    """The project's declared ``project.id`` (any settings layer), or None; never a derived value."""
    if project_root is None:
        return None
    from audiagentic.foundation.config.settings import resolve_settings_cached

    value = resolve_settings_cached(project_root).get("project.id")
    return value if isinstance(value, str) and value else None


def _connector_path() -> Path | None:
    """The machine's connector document: the ``gateway.connector`` setting, or None."""
    from audiagentic.components.agents.gateway.settings import gateway_setting

    value = gateway_setting("connector")
    return Path(str(value)).expanduser() if value else None


def _resolve_implementation_id(project_root: Path | None) -> tuple[str, str]:
    """Resolve which gateway implementation is active, and how it was chosen.

    Resolution order (SH11 Slice B), highest precedence first:
    1. ``gateway.implementation`` in settings (CFG09).
    2. the project's selected component implementation
       (``foundation.features.registry.resolve_active_implementation``),
       which itself falls through to the descriptor-declared default
       (``automatic``) when nothing was ever explicitly selected.
    3. "automatic" as a final fallback -- only reachable without a project
       root or if the registry itself is unavailable (e.g. descriptors not
       loaded), so resolution never raises merely for lack of project context.

    Returns ``(implementation_id, source)`` where source is one of
    ``settings`` / ``component-config`` / ``schema-default``.
    """
    from audiagentic.components.agents.gateway.settings import gateway_setting

    configured = gateway_setting("implementation")
    if configured:
        return str(configured), "settings"

    if project_root is not None:
        from audiagentic.foundation.features.registry import resolve_active_implementation

        implementation_id = resolve_active_implementation(
            project_root, _COMPONENT_ID, fallback="automatic"
        )
        if implementation_id:
            return implementation_id, "component-config"

    return "automatic", "schema-default"


def get_gateway_client(project_root: Path | None = None) -> GatewayClient:
    """Return the selected gateway client for this process/project.

    ``project_root`` is optional and additive (SH11): omit it to preserve
    exact pre-SH11 behavior (env-var/hardcoded-default resolution only,
    process-wide caching). Pass it to let a project's own selected
    implementation (set via ``agent_gateway_select_implementation``) take
    effect -- see ``_resolve_implementation_id`` for the full precedence.
    """
    from audiagentic.foundation.contracts.errors import make_error_factory

    config_error = make_error_factory("CFG", "AGSV", "gateway-service")
    mode, _source = _resolve_implementation_id(project_root)
    connector = None
    connector_path = None
    project_id = None
    if mode == "standalone":
        connector_path = _connector_path()
        if connector_path is None:
            raise config_error(1, "standalone gateway selected but no connector is configured")
        from .service.shared_config import load_shared_connector_config

        connector = load_shared_connector_config(connector_path)
        if connector.mode == "shared":
            project_id = _declared_project_id(project_root)
            if project_id is None:
                raise config_error(3, "a shared gateway connection needs a declared project.id in the project's settings")
    config = (
        str(project_root) if project_root is not None else None,
        mode, str(connector_path) if connector_path else None, connector, project_id,
    )
    global _CLIENT, _CLIENT_CONFIG
    with _CLIENT_LOCK:
        if _CLIENT is not None and _CLIENT_CONFIG == config:
            return _CLIENT
        if _CLIENT is not None:
            close = getattr(_CLIENT, "close", None)
            if callable(close):
                close()
        if mode == "embedded":
            if _has_live_provable_shared_owner():
                policy = _resolve_embedded_coexistence_policy(project_root)
                if policy == "warn":
                    logger.warning(
                        "running embedded gateway beside a live shared owner "
                        "(allow-with-live-shared-owner=warn) -- this is a "
                        "migration escape hatch, not a supported steady state"
                    )
                elif policy == "refuse":
                    raise config_error(
                        5,
                        "a live shared gateway already owns this machine's gateway "
                        "record; refusing to run embedded beside it",
                    )
                else:
                    raise config_error(
                        6, "unknown embedded coexistence policy", policy=policy
                    )
            client: GatewayClient = EmbeddedGatewayClient()
        elif mode == "standalone":
            client = connector_client(connector, project_root, project_id)
        elif mode == "automatic":
            from audiagentic.components.agents.gateway.service.bootstrap import (
                start_or_attach_gateway,
            )

            client = start_or_attach_gateway()
        else:
            raise config_error(2, "unknown gateway mode", mode=mode)
        _CLIENT = client
        _CLIENT_CONFIG = config
        return client


def reset_gateway_client() -> None:
    """Release the selected client; intended for process shutdown and tests."""
    global _CLIENT, _CLIENT_CONFIG
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            close = getattr(_CLIENT, "close", None)
            if callable(close):
                close()
        _CLIENT = None
        _CLIENT_CONFIG = None


# GP06: methods safe to silently retry once against a freshly-reconnected
# client after NET-AGSV-002. A network failure does not prove the original
# RPC never reached the server, so mutating operations (submit, resume,
# control, close, cancel) are deliberately excluded -- reconnecting the
# client is always safe, but replaying a mutation blindly is not.
_READ_ONLY_GATEWAY_METHODS = frozenset({
    "list_agent_definition_cards",
    "get_execution_request",
    "get_execution_diagnostics",
    "get_execution_observations",
    "get_execution_evidence",
    "replay_execution_observations",
    "get_execution_response",
    "get_execution_response_payload",
    "get_execution_failure_response",
    "list_execution_requests",
    "gateway_overview",
    "list_execution_sessions",
    "request_runtime_status",
    "list_agent_contexts",
    "get_agent_context",
    "get_agent_work",
    "list_agent_work",
})

# Mutating methods whose own handler independently documents a server-side
# idempotency guarantee, verified against each handler before inclusion:
# - resume_execution_session: api.py docstring -- "control_id makes
#   repeated calls idempotent (returns the original result, never creates
#   a second successor generation)".
# - control_execution_session: session/controls.py -- "Durable idempotency
#   for closed generic session controls", keyed on control_id.
# - close_execution_session: api.py docstring -- "Idempotent -- closing a
#   session that is already terminal ... returns its final record".
# submit_execution_request and cancel_execution_request are deliberately
# excluded: submit creates new work on every call, and cancel's replay
# safety was not independently verified here.
_IDEMPOTENT_MUTATING_GATEWAY_METHODS = frozenset({
    "resume_execution_session",
    "control_execution_session",
    "close_execution_session",
})

_RETRY_ELIGIBLE_GATEWAY_METHODS = _READ_ONLY_GATEWAY_METHODS | _IDEMPOTENT_MUTATING_GATEWAY_METHODS

# A gateway restart is not instantaneous. A single immediate retry can
# still land inside the outage window (observed live 2026-08-18: a caller
# retrying session-resume by hand, each attempt getting exactly one
# immediate reconnect-and-try, kept missing a several-second restart
# window). Retry eligible methods across this backoff instead of once.
_RETRY_BACKOFF_SECONDS = (0.5, 1.5, 3.0)


def call_gateway_method(
    method_name: str, project_root: Path | None, *args: Any, **kwargs: Any
) -> Any:
    """Call a GatewayClient method, self-healing a dead cached 'automatic'
    client on NET-AGSV-002.

    get_gateway_client()'s cache previously never revisited its choice after
    the first call in a process's lifetime: if the underlying gateway
    process later died and was restarted, every subsequent call kept
    failing against the dead reference forever, with no self-recovery
    (confirmed live 2026-08-16, tracked as GP06). Reconnection is
    unconditionally safe -- a dead client is useless no matter what is being
    called -- but REPLAYING the specific failed call is not always safe, so
    only methods proven safe to replay (read-only, or mutating with a
    verified server-side idempotency key) are retried after reconnecting,
    across a short backoff to ride out a genuine restart; every other
    mutating call is re-raised so the caller decides, now against a live
    client for their next attempt.
    """
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    if "node_id" in kwargs or "workspace_id" in kwargs:
        validate_node_selectors(kwargs.get("node_id"), kwargs.get("workspace_id"))
        if project_root is None or not _uses_shared_connector(project_root):
            from audiagentic.foundation.contracts.errors import make_error_factory

            raise make_error_factory("VAL", "AGSV", "gateway-service")(
                22, "node selectors require an explicitly configured shared connector"
            )
    client = get_gateway_client(project_root)
    try:
        return getattr(client, method_name)(project_root, *args, **kwargs)
    except AudiaGenticError as exc:
        if exc.code != "NET-AGSV-002":
            raise
        reset_gateway_client()
        client = get_gateway_client(project_root)
        if method_name not in _RETRY_ELIGIBLE_GATEWAY_METHODS:
            raise
        last_exc: AudiaGenticError = exc
        for delay in _RETRY_BACKOFF_SECONDS:
            try:
                return getattr(client, method_name)(project_root, *args, **kwargs)
            except AudiaGenticError as retry_exc:
                if retry_exc.code != "NET-AGSV-002":
                    raise
                last_exc = retry_exc
                time.sleep(delay)
                reset_gateway_client()
                client = get_gateway_client(project_root)
        raise last_exc
