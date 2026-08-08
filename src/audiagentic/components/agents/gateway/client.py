"""Public in-process client for the agent execution gateway.

Inbound surfaces depend on this module, never on the gateway implementation
modules.  SH03 keeps the current in-process control plane, but makes the
client boundary explicit so a later local-service client can implement the
same operations without changing MCP or event adapters.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Protocol

from audiagentic.components.agents.gateway.application import (
    GatewayApplication,
    get_gateway_application,
)

logger = logging.getLogger(__name__)

_COMPONENT_ID = "agents"
# SH11 migration compatibility: AUDIAGENTIC_GATEWAY_MODE historically used
# "in-process"; the component-implementation id is "embedded". Accept both
# on the env path without silently favoring one meaning over the other.
_MODE_ALIASES = {"in-process": "embedded"}


class GatewayClient(Protocol):
    """Requester-facing gateway operations, independent of inbound transport."""

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]: ...
    def get_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]: ...
    def wait_execution_request(
        self, project_root: Path, request_id: str, timeout_seconds: float | None = None
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
    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]: ...


class EmbeddedGatewayClient:
    """SH03 backend adapter for the in-process control plane (SH11: renamed
    from InProcessGatewayClient -- "embedded" is the component-implementation
    id; no compatibility alias kept, per this migration's no-legacy stance)."""

    def __init__(self, application: GatewayApplication | None = None) -> None:
        self._application = application or get_gateway_application()

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        return self._application.submit_execution_request(project_root, **kwargs)

    def get_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._application.get_execution_request(project_root, request_id)

    def wait_execution_request(
        self, project_root: Path, request_id: str, timeout_seconds: float | None = None
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

    def resume_execution_session(
        self, project_root: Path, source_session_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self._application.resume_execution_session(project_root, source_session_id, **kwargs)


_CLIENT_LOCK = threading.Lock()
_CLIENT: GatewayClient | None = None
_CLIENT_CONFIG: tuple[str | None, str, str | None, str | None] | None = None


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

    Precedence: ``AUDIAGENTIC_GATEWAY_EMBEDDED_ALLOW`` env override (explicit
    migration escape hatch) > the project's ``embedded`` implementation
    config > the descriptor default (``refuse``, per RV736 A6 -- silent
    coexistence beside a shared owner is the exact dual-ownership bug this
    boundary exists to prevent).
    """
    env_override = os.environ.get("AUDIAGENTIC_GATEWAY_EMBEDDED_ALLOW")
    if env_override:
        return env_override.strip().lower()
    if project_root is not None:
        from audiagentic.components.agents.gateway.management_api import gateway_get_config

        config = gateway_get_config(project_root, "embedded")
        policy = config.get("config", {}).get("allow-with-live-shared-owner")
        if policy:
            return str(policy)
    return "refuse"


def _resolve_implementation_id(project_root: Path | None) -> tuple[str, str]:
    """Resolve which gateway implementation is active, and how it was chosen.

    Resolution order (SH11 Slice B), highest precedence first:
    1. explicit ``AUDIAGENTIC_GATEWAY_MODE`` env override -- compatibility
       path for the pre-SH11 env-only world; the "in-process" spelling is
       aliased to "embedded", the real implementation id, without silently
       treating them as different things.
    2. the project's selected component implementation
       (``foundation.features.registry.resolve_active_implementation``),
       which itself falls through to the descriptor-declared default
       (``embedded``) when nothing was ever explicitly selected.
    3. "embedded" as a final, hardcoded fallback -- only reachable if the
       registry itself is unavailable (e.g. descriptors not loaded), so
       resolution never raises merely for lack of project context.

    Returns ``(implementation_id, source)`` where source is one of
    ``env-override`` / ``component-config`` / ``schema-default``.
    """
    env_mode = os.environ.get("AUDIAGENTIC_GATEWAY_MODE")
    if env_mode:
        normalized = env_mode.strip().lower()
        resolved = _MODE_ALIASES.get(normalized, normalized)
        if resolved != normalized:
            logger.warning(
                "AUDIAGENTIC_GATEWAY_MODE=%r is a compatibility alias for %r; "
                "prefer selecting the 'embedded' implementation via component config",
                normalized, resolved,
            )
        return resolved, "env-override"

    if project_root is not None:
        from audiagentic.foundation.features.registry import resolve_active_implementation

        implementation_id = resolve_active_implementation(
            project_root, _COMPONENT_ID, fallback="embedded"
        )
        if implementation_id:
            return implementation_id, "component-config"

    return "embedded", "schema-default"


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
    endpoint = os.environ.get("AUDIAGENTIC_GATEWAY_ENDPOINT")
    token_file = os.environ.get("AUDIAGENTIC_GATEWAY_TOKEN_FILE")
    config = (str(project_root) if project_root is not None else None, mode, endpoint, token_file)
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
            if not endpoint or not token_file:
                raise config_error(
                    1,
                    "standalone gateway requires explicit endpoint and token file",
                )
            from audiagentic.components.agents.gateway.remote_client import (
                StandaloneGatewayClient,
                load_auth_token,
            )

            client = StandaloneGatewayClient(endpoint, load_auth_token(Path(token_file)))
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
