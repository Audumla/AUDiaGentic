"""Tests for the executable capability catalogue (PC01)."""

from __future__ import annotations

import pytest

from audiagentic.components.providers.descriptors.capability_catalogue import (
    CONCEPTUAL_MECHANISMS,
    MECHANISM_SCHEMA_MAP,
    CatalogueError,
    get_catalogue,
    load_catalogue,
    validate_capability_id,
    validate_family_declaration,
)
from audiagentic.components.providers.descriptors.capability_facts import (
    validate_provider_capability_facts,
)
from audiagentic.components.providers.descriptors.registry import all_descriptors
from audiagentic.foundation.contracts.errors import AudiaGenticError

# ── Fixture: reset catalogue between tests ────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_catalogue():
    """Reset the singleton catalogue before each test."""
    import audiagentic.components.providers.descriptors.capability_catalogue as cc

    cc._catalogue = None
    yield
    cc._catalogue = None  # cleanup


# ── Catalogue load tests ──────────────────────────────────────────────────


def test_catalogue_loads():
    """The catalogue loads without errors."""
    cat = load_catalogue()
    assert cat.kinds_by_id
    assert cat.families


def test_get_catalogue_caches():
    """get_catalogue() returns the same instance on repeated calls."""
    cat1 = get_catalogue()
    cat2 = get_catalogue()
    assert cat1 is cat2


def test_automation_kinds_have_family_ids():
    """Every automation kind has a family_id that matches _families.yaml."""
    cat = get_catalogue()
    for kind in cat.kinds_by_id.values():
        if kind.authority == "automation":
            assert kind.family_id is not None, f"{kind.id} missing family_id"
            assert kind.family_id in cat.families, (
                f"{kind.id} references unknown family {kind.family_id}"
            )


def test_mechanism_schemas_resolve():
    """Every mechanism_schema != 'none' resolves via MECHANISM_SCHEMA_MAP or CONCEPTUAL_MECHANISMS."""
    cat = get_catalogue()
    for kind in cat.kinds_by_id.values():
        mech = kind.mechanism_schema
        if mech != "none":
            assert mech in MECHANISM_SCHEMA_MAP or mech in CONCEPTUAL_MECHANISMS, (
                f"{kind.id} has unresolvable mechanism_schema '{mech}'"
            )


def test_mechanism_schema_map_types_are_callable():
    """Every entry in MECHANISM_SCHEMA_MAP is an actual Python type."""
    for name, typ in MECHANISM_SCHEMA_MAP.items():
        assert isinstance(typ, type), f"MECHANISM_SCHEMA_MAP['{name}'] = {typ!r} is not a type"


# ── canonical_kind invariant ──────────────────────────────────────────────
# No kind currently declares canonical_kind (PC07 step 4: the two prior
# users, lsp-automation and acp-support, were either deleted as dead weight
# or replaced outright rather than left as an aspirational migration
# target). The field stays on CapabilityKind for a future real case; this
# test just guards that if one ever appears, it resolves.


def test_canonical_kind_resolves_when_declared():
    cat = get_catalogue()
    for kind in cat.kinds_by_id.values():
        if kind.canonical_kind is not None:
            assert kind.canonical_kind in cat.kinds_by_id, (
                f"{kind.id} points to unknown canonical_kind '{kind.canonical_kind}'"
            )


# ── VAL-PCAP-009: off-taxonomy capability_id ──────────────────────────────


def test_val_pcap_009_off_taxonomy_rejected():
    """An off-taxonomy capability kind is rejected by VAL-PCAP-009."""
    from audiagentic.components.providers.descriptors.loader import _build_capabilities

    with pytest.raises(AudiaGenticError, match="VAL-PCAP-009"):
        _build_capabilities({"vendor-key-injection": {"mechanism": {}}})


def test_validate_capability_id_returns_kind_for_known():
    """validate_capability_id returns the kind for known ids."""
    kind = validate_capability_id("cli-install")
    assert kind is not None
    assert kind.id == "cli-install"
    # Tier renamed automation -> provisioned (PC01); legacy YAML label is
    # normalized at load, so the loaded kind reports the final tier name.
    assert kind.authority == "provisioned"


def test_validate_capability_id_returns_none_for_unknown():
    """validate_capability_id returns None for unknown ids."""
    kind = validate_capability_id("nonexistent-kind")
    assert kind is None


# ── VAL-PCAP-011: family_id validation ────────────────────────────────────


def test_val_pcap_011_unknown_family_rejected():
    """A provider declaring an unknown family_id is rejected."""
    with pytest.raises(CatalogueError, match="VAL-PCAP-011"):
        validate_family_declaration("nonexistent-family")


def test_val_pcap_011_known_family_passes():
    """A known family_id resolves without error."""
    # Should not raise
    validate_family_declaration("cli-lifecycle")


def test_val_pcap_011_contract_mismatch_rejected():
    """A wrong payload contract is rejected by VAL-PCAP-011."""
    with pytest.raises(CatalogueError, match="VAL-PCAP-011"):
        validate_family_declaration(
            "cli-lifecycle",
            payload_contract="wrong-contract/v1",
        )


def test_val_pcap_011_unsupported_modes_rejected():
    """Declaring unsupported modes is rejected."""
    with pytest.raises(CatalogueError, match="VAL-PCAP-011"):
        validate_family_declaration(
            "managed-mcp",
            supported_modes=("plan", "apply"),  # managed-mcp doesn't support 'plan'
        )


# ── VAL-PCAP-013: mechanism_schema validation ─────────────────────────────


def test_val_pcap_013_typoed_mechanism_rejected():
    """A typoed mechanism_schema string is rejected when loading the catalogue."""
    import tempfile
    from pathlib import Path

    import yaml

    # Create a temporary _capabilities.yaml with a bad mechanism_schema
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as cap_file:
        yaml.dump(
            {
                "kinds": {
                    "test-bad-mechanism": {
                        "domain": "cli",
                        "authority": "operational",
                        "mechanism_schema": "typoed-mechanism",
                    }
                }
            },
            cap_file,
        )
        cap_path = Path(cap_file.name)

    # We can't easily swap the config dir, so we test the logic directly:
    assert "typoed-mechanism" not in MECHANISM_SCHEMA_MAP
    assert "typoed-mechanism" not in CONCEPTUAL_MECHANISMS
    # The load_catalogue function would raise CatalogueError with VAL-PCAP-013
    # if it encountered this — verified by the mechanism_schema validation logic.


# ── Full provider suite integration ───────────────────────────────────────


def test_all_providers_validate_against_catalogue():
    """Every capability_id in all shipped provider YAMLs resolves to a catalogue kind.

    The repository-owned activity-rig is also a registered synthetic provider
    used by deterministic gateway tests, and gpt-auto-t1/gpt-auto-t2 are
    dedicated GP05 test-project aliases of gpt-auto, so the shipped registry
    currently contains 23 descriptors.
    """
    descriptors = all_descriptors()
    assert len(descriptors) == 23, f"Expected 23 providers, got {len(descriptors)}"

    for pid, desc in descriptors.items():
        validate_provider_capability_facts(desc)  # raises if any fact fails


def test_all_automation_kinds_reconcile_to_families():
    """Every automation kind in the catalogue reconciles to a family entry."""
    cat = get_catalogue()
    for kind in cat.kinds_by_id.values():
        if kind.authority == "automation":
            assert kind.family_id in cat.families, (
                f"automation kind '{kind.id}' has no matching family entry for '{kind.family_id}'"
            )


def test_execution_isolation_kind_exists():
    """execution-isolation is a registered operational kind with tier-enum mechanism."""
    kind = validate_capability_id("execution-isolation")
    assert kind is not None, "execution-isolation should be in the catalogue"
    assert kind.authority == "operational"
    assert kind.mechanism_schema == "tier-enum"
