"""Durable cross-process gateway trigger ingress (SH09).

Characterization (SH09 step 1): the current cross-process triggers are the
``agents.execution.gateway.requested`` / ``agents.execution.gateway.cancel-requested``
events. The in-process EventBus cannot cross processes and the SH04 HTTP
client requires the publisher and the service to be online simultaneously.
Required properties: durable once-only admission despite redelivery, offline
publishing while the service is down, single-machine deployment, and poison
isolation. The smallest transport meeting them is the foundation
``DurableSpoolTransport`` (atomic file spool) — no broker premise.

This module is a THIN adapter: it maps spooled events onto the public
``GatewayApplication`` submission/cancel operations and onto the gateway's
SH07 idempotency contract (the spool ``event-id`` becomes the idempotency
key unless the publisher supplied one, so redelivery returns the original
request identity instead of double-dispatching). It imports no gateway
store/queue/dispatch internals.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_event_topics import (
    GATEWAY_CANCEL_REQUESTED_TOPIC,
    GATEWAY_REQUESTED_TOPIC,
)
from audiagentic.components.agents.agents_mapping import first_present
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event.durable_spool import DurableSpoolTransport, SpoolPoison

logger = logging.getLogger(__name__)

INGRESS_TOPICS = frozenset({GATEWAY_REQUESTED_TOPIC, GATEWAY_CANCEL_REQUESTED_TOPIC})
_INGRESS_DIR = "ingress"

# Error prefixes that can never succeed on redelivery — dead-letter, don't retry.
_POISON_PREFIXES = ("VAL-", "RES-", "CON-", "CFG-", "VER-", "UNS-")


def gateway_ingress_spool(service_root: Path | None = None) -> DurableSpoolTransport:
    """Return the machine-scoped ingress spool beside the service record."""
    from audiagentic.components.agents.agents_gateway_service_host import (
        GATEWAY_SERVICE_KEY,
    )
    from audiagentic.foundation.system.managed_service import ManagedServiceStore

    store = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=service_root)
    return DurableSpoolTransport(store.root / _INGRESS_DIR, allowed_topics=INGRESS_TOPICS)


def publish_gateway_trigger(
    topic: str,
    payload: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    service_root: Path | None = None,
) -> str:
    """Durably publish one gateway trigger from ANY process; returns event-id.

    Safe while the gateway service is down — the event is admitted when the
    service next drains its ingress spool.
    """
    return gateway_ingress_spool(service_root).publish(topic, payload, metadata=metadata)


def _admit_request(application: Any, event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    project_root_raw = first_present(payload, "project-root", "project_root")
    if not project_root_raw or not isinstance(project_root_raw, str):
        raise SpoolPoison("payload missing required 'project-root'")
    prompt_body = first_present(payload, "prompt-body", "prompt_body")
    if not prompt_body or not isinstance(prompt_body, str):
        raise SpoolPoison("payload missing required 'prompt-body'")

    metadata = dict(event.get("metadata") or {})
    # Delivery identity → gateway idempotency (SH09 step 3): redelivery of the
    # same spool event replays the original submission instead of duplicating.
    metadata.setdefault("idempotency_key", f"gateway-spool:{event['event-id']}")

    application.submit_execution_request(
        Path(project_root_raw),
        agent_profile_id=first_present(payload, "agent-profile-id", "agent_profile_id"),
        prompt_body=prompt_body,
        # Spooled triggers are fire-and-forget: async regardless of payload.
        mode="async",
        source=first_present(payload, "source") or f"spool:{GATEWAY_REQUESTED_TOPIC}",
        metadata=metadata,
    )


def _admit_cancel(application: Any, event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    project_root_raw = first_present(payload, "project-root", "project_root")
    request_id = first_present(payload, "request-id", "request_id")
    if not project_root_raw or not isinstance(project_root_raw, str):
        raise SpoolPoison("cancel payload missing required 'project-root'")
    if not request_id or not isinstance(request_id, str):
        raise SpoolPoison("cancel payload missing required 'request-id'")
    application.cancel_execution_request(Path(project_root_raw), request_id)


def drain_gateway_ingress(
    application: Any,
    *,
    service_root: Path | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Admit spooled triggers through the public gateway application.

    Validation failures dead-letter (poison); transient failures leave the
    event for ordered redelivery. Never raises.
    """
    spool = gateway_ingress_spool(service_root)

    def _handle(event: dict[str, Any]) -> None:
        topic = event.get("topic")
        try:
            if topic == GATEWAY_REQUESTED_TOPIC:
                _admit_request(application, event)
            elif topic == GATEWAY_CANCEL_REQUESTED_TOPIC:
                _admit_cancel(application, event)
            else:
                raise SpoolPoison(f"unknown ingress topic {topic!r}")
        except SpoolPoison:
            raise
        except AudiaGenticError as exc:
            if exc.code.startswith(_POISON_PREFIXES):
                raise SpoolPoison(f"{exc.code}: {exc.message}") from exc
            raise  # transient — bounded redelivery

    try:
        outcome = spool.consume(_handle, limit=limit)
    except Exception:  # noqa: BLE001 — ingress must never take the host down
        logger.error("gateway ingress drain failed", exc_info=True)
        return {"delivered": 0, "failed": 0, "dead-lettered": 0}
    if outcome["dead-lettered"]:
        logger.warning("gateway ingress dead-lettered events", extra=outcome)
    return outcome


def ingress_backlog(service_root: Path | None = None) -> dict[str, int]:
    """Redacted ingress counters for status/quiescence surfaces."""
    spool = gateway_ingress_spool(service_root)
    return {
        "pending": spool.pending_count(),
        "dead-letter": len(spool.dead_letter_ids()),
    }


__all__ = [
    "INGRESS_TOPICS",
    "drain_gateway_ingress",
    "gateway_ingress_spool",
    "ingress_backlog",
    "publish_gateway_trigger",
]
