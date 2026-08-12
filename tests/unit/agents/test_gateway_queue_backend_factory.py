from __future__ import annotations

import pytest

from audiagentic.components.agents.gateway.queue import InMemoryAgentWorkQueue, create_work_queue
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_queue_backend_factory_defaults_to_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_GATEWAY_QUEUE_BACKEND", raising=False)
    assert isinstance(create_work_queue(), InMemoryAgentWorkQueue)


def test_queue_backend_factory_fails_closed_for_unavailable_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_QUEUE_BACKEND", "mqtt")
    with pytest.raises(AudiaGenticError) as exc_info:
        create_work_queue()
    assert exc_info.value.code == "CFG-AGW-110"
