"""Focused tests for the event observer's canonical Work adapter."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.components.agents.context.service import open_context
from audiagentic.components.agents.models.prompt_definition import PromptDefinition, PromptTextPart
from audiagentic.components.agents.work.service import get_work


def _seed(root: Path) -> str:
    AgentsConfigRepository().replace(
        root,
        AgentsConfigDocument(
            "v2",
            (PromptDefinition("p", "", (PromptTextPart("x"),)),),
            ({"role_id": "r", "instructions": "x", "required_capabilities": []},),
            ({"profile_id": "p", "provider_id": "local-openai", "instances": ["plain"]},),
            ({"agent_id": "a", "name": "A", "prompt_id": "p", "role_ids": ["r"], "execution_profile_id": "p"},),
        ),
        expected_digest=None,
    )
    return open_context(root, "a", "event test").context_id


def _write_trigger(root: Path, *, trigger_id: str = "t-01") -> None:
    path = root / ".audiagentic" / "config" / "agent-jobs" / "event-triggers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"triggers": [{
        "contract-version": "v1",
        "trigger-id": trigger_id,
        "kind": "event",
        "enabled": True,
        "event-pattern": "planning.item.created",
        "prompt-template": "Review {event.type}",
    }]}), encoding="utf-8")


def _audit(root: Path) -> list[dict]:
    path = root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_matched_event_is_admitted_as_canonical_work(tmp_path: Path) -> None:
    from audiagentic.components.agent_jobs.event_observer import EventObserver
    from audiagentic.foundation.event.event_bus import get_bus, reset_bus

    context_id = _seed(tmp_path)
    _write_trigger(tmp_path)
    reset_bus()
    observer = EventObserver(context_id=context_id)
    observer.initialize(tmp_path)
    get_bus().publish("planning.item.created", {"item": "one"}, metadata={"event-id": "evt-1"})

    fired = [entry for entry in _audit(tmp_path) if entry["status"] == "fired"]
    assert len(fired) == 1
    work = get_work(tmp_path, fired[0]["job_id"])
    assert work.work_id == fired[0]["job_id"]
    assert work.active_execution_id is not None
    assert not (tmp_path / ".audiagentic" / "runtime" / "jobs").exists()


def test_replaying_event_reuses_one_work_and_gateway_admission(tmp_path: Path) -> None:
    from audiagentic.components.agent_jobs.event_observer import EventObserver
    from audiagentic.foundation.event.event_bus import get_bus, reset_bus

    context_id = _seed(tmp_path)
    _write_trigger(tmp_path)
    reset_bus()
    observer = EventObserver(context_id=context_id)
    observer.initialize(tmp_path)
    bus = get_bus()
    message = {"item": "same"}
    metadata = {"event-id": "evt-replay"}
    bus.publish("planning.item.created", message, metadata=metadata)
    first = [entry for entry in _audit(tmp_path) if entry["status"] == "fired"][0]["job_id"]
    bus.publish("planning.item.created", message, metadata=metadata)
    fired = [entry for entry in _audit(tmp_path) if entry["status"] == "fired"]
    assert [entry["job_id"] for entry in fired] == [first, first]
    assert len(get_work(tmp_path, first).to_mapping()) > 0


def test_observer_without_context_fails_closed_without_legacy_job(tmp_path: Path) -> None:
    from audiagentic.components.agent_jobs.event_observer import EventObserver
    from audiagentic.foundation.event.event_bus import get_bus, reset_bus

    _seed(tmp_path)
    _write_trigger(tmp_path)
    reset_bus()
    observer = EventObserver()
    observer.initialize(tmp_path)
    get_bus().publish("planning.item.created", {"item": "no-context"}, metadata={"event-id": "evt-2"})

    failed = [entry for entry in _audit(tmp_path) if entry["status"] == "failed"]
    assert failed and failed[-1]["error_message"]
    assert not (tmp_path / ".audiagentic" / "runtime" / "jobs").exists()

