from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from audiagentic.components.agents.agents_paths import agent_work_inputs_path
from audiagentic.components.agents.work.contracts import WorkInputMessage
from audiagentic.foundation.io import atomic_write_text


def append_work_input(project_root: Path, work_id: str, message: WorkInputMessage) -> WorkInputMessage:
    path = agent_work_inputs_path(project_root, work_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                existing[value["message_id"]] = value
    candidate = {"message_id": message.message_id, "text": message.text, "inputs": dict(message.inputs), "created_at": message.created_at}
    prior = existing.get(message.message_id)
    if prior is not None and prior != candidate:
        raise ValueError("work message ID payload conflict")
    if prior is None:
        existing[message.message_id] = candidate
        atomic_write_text(path, "".join(json.dumps(value, sort_keys=True) + "\n" for value in existing.values()))
    return message


def new_work_input(message_id: str, text: str, inputs: dict | None = None) -> WorkInputMessage:
    return WorkInputMessage(message_id, text, inputs or {}, datetime.now(timezone.utc).isoformat())


def latest_work_input(project_root: Path, work_id: str) -> WorkInputMessage:
    path = agent_work_inputs_path(project_root, work_id)
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not values:
        raise ValueError(f"Work {work_id!r} has no input message")
    value = values[-1]
    return WorkInputMessage(value["message_id"], value["text"], value.get("inputs") or {}, value["created_at"])
