"""SH09 — gateway trigger ingress: idempotent admission through the public
application, poison isolation, and offline durability."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.agents.gateway.event_topics import (
    GATEWAY_CANCEL_REQUESTED_TOPIC,
    GATEWAY_REQUESTED_TOPIC,
)
from audiagentic.components.agents.gateway.ingress import (
    drain_gateway_ingress,
    gateway_ingress_spool,
    ingress_backlog,
    publish_gateway_trigger,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


class FakeApplication:
    """Public-application double recording admissions; scriptable failures."""

    def __init__(self) -> None:
        self.submissions: list[dict[str, Any]] = []
        self.cancels: list[tuple[Path, str]] = []
        self.raise_code: str | None = None

    def submit_execution_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        if self.raise_code:
            raise AudiaGenticError(
                code=self.raise_code, kind="agents", message="scripted", details={}
            )
        self.submissions.append({"project_root": project_root, **kwargs})
        return {"request-id": f"req_{len(self.submissions)}", "state": "queued"}

    def cancel_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        self.cancels.append((project_root, request_id))
        return {"request-id": request_id, "state": "cancelled"}


@pytest.fixture
def rig(tmp_path):
    return FakeApplication(), tmp_path / "service-root", tmp_path / "project"


def _publish_request(service_root: Path, project: Path, **overrides) -> str:
    payload = {"project-root": str(project), "prompt-body": "hello", **overrides}
    return publish_gateway_trigger(
        GATEWAY_REQUESTED_TOPIC, payload,
        metadata={"correlation_id": "corr-1"}, service_root=service_root,
    )


def test_spooled_request_admitted_with_delivery_idempotency(rig):
    app, service_root, project = rig
    event_id = _publish_request(service_root, project, **{"execution-profile-id": "p1"})
    assert ingress_backlog(service_root) == {"pending": 1, "dead-letter": 0}

    outcome = drain_gateway_ingress(app, service_root=service_root)
    assert outcome["delivered"] == 1
    assert ingress_backlog(service_root) == {"pending": 0, "dead-letter": 0}

    submitted = app.submissions[0]
    assert submitted["prompt_body"] == "hello"
    assert submitted["execution_profile_id"] == "p1"
    assert submitted["mode"] == "async"  # spooled triggers are always async
    assert submitted["metadata"]["idempotency_key"] == f"gateway-spool:{event_id}"
    assert submitted["metadata"]["correlation_id"] == "corr-1"


def test_redelivery_reuses_the_same_idempotency_key(rig):
    """A crash between admission and ack redelivers; the identical
    idempotency key makes SH07 replay the original request identity."""
    app, service_root, project = rig
    event_id = _publish_request(service_root, project)
    spool = gateway_ingress_spool(service_root)
    original = (spool.pending_dir / f"{event_id}.json").read_text(encoding="utf-8")

    drain_gateway_ingress(app, service_root=service_root)
    (spool.pending_dir / f"{event_id}.json").write_text(original, encoding="utf-8")
    drain_gateway_ingress(app, service_root=service_root)

    keys = [s["metadata"]["idempotency_key"] for s in app.submissions]
    assert keys == [f"gateway-spool:{event_id}"] * 2


def test_publisher_supplied_idempotency_key_wins(rig):
    app, service_root, project = rig
    publish_gateway_trigger(
        GATEWAY_REQUESTED_TOPIC,
        {"project-root": str(project), "prompt-body": "x"},
        metadata={"idempotency_key": "mine-1"},
        service_root=service_root,
    )
    drain_gateway_ingress(app, service_root=service_root)
    assert app.submissions[0]["metadata"]["idempotency_key"] == "mine-1"


def test_malformed_payload_dead_letters_and_unblocks_queue(rig):
    app, service_root, project = rig
    publish_gateway_trigger(
        GATEWAY_REQUESTED_TOPIC, {"prompt-body": "no root"}, service_root=service_root
    )
    _publish_request(service_root, project)

    outcome = drain_gateway_ingress(app, service_root=service_root)
    assert outcome["delivered"] == 1 and outcome["dead-lettered"] == 1
    assert len(app.submissions) == 1
    assert ingress_backlog(service_root)["dead-letter"] == 1


def test_validation_failure_is_poison_transient_is_retried(rig):
    app, service_root, project = rig
    _publish_request(service_root, project)

    app.raise_code = "VAL-AGW-002"
    outcome = drain_gateway_ingress(app, service_root=service_root)
    assert outcome["dead-lettered"] == 1 and ingress_backlog(service_root)["pending"] == 0

    _publish_request(service_root, project)
    app.raise_code = "NET-AGW-001"
    outcome = drain_gateway_ingress(app, service_root=service_root)
    assert outcome["failed"] == 1
    assert ingress_backlog(service_root)["pending"] == 1  # retained for retry

    app.raise_code = None
    outcome = drain_gateway_ingress(app, service_root=service_root)
    assert outcome["delivered"] == 1


def test_cancel_trigger_routed(rig):
    app, service_root, project = rig
    publish_gateway_trigger(
        GATEWAY_CANCEL_REQUESTED_TOPIC,
        {"project-root": str(project), "request-id": "req_9"},
        service_root=service_root,
    )
    outcome = drain_gateway_ingress(app, service_root=service_root)
    assert outcome["delivered"] == 1
    assert app.cancels == [(project, "req_9")]


def test_offline_publish_survives_until_drain(rig):
    """Events spooled while no service is running are admitted at startup."""
    app, service_root, project = rig
    for _ in range(3):
        _publish_request(service_root, project)
    # no consumer ran yet — this is the 'service down' window
    assert ingress_backlog(service_root)["pending"] == 3
    outcome = drain_gateway_ingress(app, service_root=service_root)
    assert outcome["delivered"] == 3
    assert len(app.submissions) == 3
