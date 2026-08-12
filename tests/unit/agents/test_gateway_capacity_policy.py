from __future__ import annotations

import pytest

from audiagentic.components.agents.gateway.queue.capacity_policy import (
    resolve_pending_capacity,
    resolve_virtual_capacity,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_virtual_capacity_defaults_and_validates() -> None:
    assert resolve_virtual_capacity({}) == 1
    with pytest.raises(AudiaGenticError):
        resolve_virtual_capacity({"virtual-capacity": "two"})
    with pytest.raises(AudiaGenticError):
        resolve_virtual_capacity({"virtual-capacity": 0})


def test_pending_capacity_defaults_from_virtual_capacity() -> None:
    assert resolve_pending_capacity({}, 1) == 8
    assert resolve_pending_capacity({}, 5) == 10
    assert resolve_virtual_capacity({"virtual-capacity": 3}) == 3
    assert resolve_pending_capacity({"pending-capacity": 7}, 3) == 7
