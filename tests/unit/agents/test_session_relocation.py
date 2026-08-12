import json
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.session.relocation import (
    recover_relocations,
    relocate_session_state,
)
from audiagentic.components.agents.gateway.session.retention import request_retention_pin


def test_relocation_preserves_state_and_clears_journal(tmp_path: Path) -> None:
    source = tmp_path / "request"
    destination = tmp_path / "session"
    source.mkdir()
    (source / "record.json").write_text('{"session-id":"ses-1","provider-ref":"ref-1"}', encoding="utf-8")
    relocate_session_state(source, destination)
    assert (destination / "record.json").read_text(encoding="utf-8").find("ses-1") >= 0
    assert not destination.with_suffix(".relocating").exists()


def test_relocation_publishes_durable_lineage_registry(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "sessions" / "ses-1"
    source.mkdir()
    (source / "provider-state.json").write_text("{}", encoding="utf-8")
    relocate_session_state(
        source,
        destination,
        project_root=tmp_path,
        session_id="ses-1",
        request_ids=("req-open",),
    )
    pin = request_retention_pin(tmp_path, "req-open")
    assert pin.pinned is True
    assert pin.reason == "relocated-session-lineage"


def test_recovery_clears_interrupted_journal_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "request"
    source.mkdir()
    journal = tmp_path / "session.relocating"
    journal.write_text(json.dumps({"source": str(source), "destination": str(tmp_path / "session")}), encoding="utf-8")
    assert recover_relocations(tmp_path) == 1
    assert source.is_dir()
    assert not journal.exists()


@pytest.mark.parametrize("provider", ["fake", "acp", "mcp-a2a", "gpt-auto"])
def test_relocation_preserves_provider_neutral_resume_lineage(tmp_path: Path, provider: str) -> None:
    source = tmp_path / provider
    destination = tmp_path / (provider + "-session")
    source.mkdir()
    payload = {"session-id": "ses-1", "provider-id": provider, "provider-session-ref": "ref-1"}
    (source / "binding.json").write_text(json.dumps(payload), encoding="utf-8")
    relocate_session_state(source, destination)
    assert json.loads((destination / "binding.json").read_text(encoding="utf-8")) == payload
