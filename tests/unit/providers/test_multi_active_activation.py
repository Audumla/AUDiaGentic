from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.descriptors import registry as descriptor_registry
from audiagentic.components.providers.services.provider_config import set_provider_enabled
from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.features.state import get_implementation_state


def _two_provider_ids() -> tuple[str, str]:
    ids = sorted(descriptor_registry.all_descriptors())
    assert len(ids) >= 2, "expected at least two registered providers for multi-active test"
    return ids[0], ids[1]


def test_enabling_one_provider_does_not_deselect_another(tmp_path: Path) -> None:
    first, second = _two_provider_ids()

    set_provider_enabled(tmp_path, first, enabled=True)
    set_provider_enabled(tmp_path, second, enabled=True)

    # multi cardinality: both stay active, no auto-deselect.
    assert get_implementation_state(tmp_path, COMPONENT_PROVIDERS, first).enabled is True
    assert get_implementation_state(tmp_path, COMPONENT_PROVIDERS, second).enabled is True


def test_disabling_one_provider_leaves_others_active(tmp_path: Path) -> None:
    first, second = _two_provider_ids()

    set_provider_enabled(tmp_path, first, enabled=True)
    set_provider_enabled(tmp_path, second, enabled=True)
    set_provider_enabled(tmp_path, first, enabled=False)

    assert get_implementation_state(tmp_path, COMPONENT_PROVIDERS, first).enabled is False
    assert get_implementation_state(tmp_path, COMPONENT_PROVIDERS, second).enabled is True
