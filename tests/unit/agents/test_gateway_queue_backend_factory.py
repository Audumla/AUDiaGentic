from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers.gateway_settings import use_gateway_settings

from audiagentic.components.agents.gateway.queue import InMemoryAgentWorkQueue, create_work_queue
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_queue_backend_factory_defaults_to_in_memory() -> None:
    assert isinstance(create_work_queue(), InMemoryAgentWorkQueue)


def test_queue_backend_factory_fails_closed_for_unavailable_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    use_gateway_settings(monkeypatch, tmp_path, queue_backend="mqtt")
    with pytest.raises(AudiaGenticError) as exc_info:
        create_work_queue()
    assert exc_info.value.code == "CFG-AGW-110"
