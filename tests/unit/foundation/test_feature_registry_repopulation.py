from audiagentic.foundation.components.loader import _reset_registration_cache
from audiagentic.foundation.features import registry


def test_partial_registry_repopulates_missing_implementations() -> None:
    registry.clear()
    _reset_registration_cache()
    # Seed a partial registry: this previously suppressed lazy loading.
    from audiagentic.foundation.features.base import ImplementationDescriptor

    registry.register(
        ImplementationDescriptor(
            parent="fixture",
            implementation_id="only",
            display_name="Only",
        )
    )
    assert registry.get_implementation("memory", "hindsight") is not None
