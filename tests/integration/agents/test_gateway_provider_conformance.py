from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers import gateway_provider_conformance as conformance

pytestmark = pytest.mark.no_parallel


def test_gateway_provider_conformance_covers_every_descriptor() -> None:
    assert conformance.provider_ids() == (
        "activity-rig",
        "aider",
        "antigravity",
        "claude",
        "cline",
        "codex",
        "continue",
        "copilot",
        "crush",
        "gemini",
        "goose",
        "gpt-auto",
        "gpt-auto-t1",
        "gpt-auto-t2",
        "kilo",
        "local-openai",
        "opencode",
        "openhands",
        "pi",
        "plandex",
        "qwen",
        "roo",
        "zed",
    )


@pytest.mark.parametrize("provider_id", conformance.provider_ids())
def test_every_provider_exercises_gateway_request_states(
    provider_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conformance.assert_one_shot_state_matrix(tmp_path, provider_id, monkeypatch)
