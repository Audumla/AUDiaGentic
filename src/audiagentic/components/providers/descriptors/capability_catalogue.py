"""Executable capability catalogue — authoritative kind index.

Loads _capabilities.yaml and _families.yaml, validates cross-references,
and provides the enforcement surface (VAL-PCAP-009/011/013).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from audiagentic.components.providers.descriptors.base import (
    ACPFeatureNote,
    AgentFile,
    CliInstallRecipe,
    HostCapability,
    LaunchSpec,
    LspSelfSupportSpec,
    ModelsSpec,
    ObsTransportNote,
    ProviderPermissions,
)
from audiagentic.foundation.toolchains.config.managed_config import (
    ManagedConfigSpec,
    McpConfigSpec,
)

# ── CapabilityKind ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class CapabilityKind:
    """One canonical capability kind."""

    id: str
    domain: str
    authority: Literal["provisioned", "operational", "evidence-only"]
    family_id: str | None = None
    cardinality: Literal["single", "list"] = "single"
    mechanism_schema: str = "none"
    canonical_kind: str | None = None  # legacy kinds point here


# ── Family Declaration ───────────────────────────────────────────────────


@dataclass(frozen=True)
class FamilyDeclaration:
    """One automation family from _families.yaml."""

    family_id: str
    payload_contract: str
    result_contract: str
    supported_modes: tuple[str, ...]
    ownership_scope_required: bool = False

    @property
    def contracts(self) -> tuple[str, str]:
        """The (payload, result) contract pair for this family."""
        return (self.payload_contract, self.result_contract)


# ── Errors ───────────────────────────────────────────────────────────────


class CatalogueError(ValueError):
    """Raised when catalogue validation fails."""


# ── Mechanism Schema Registry ────────────────────────────────────────────
# Maps mechanism_schema strings to real Python types.
# Only mechanisms with actual type definitions are registered;
# conceptual patterns (boolean-set, tier-enum, callable-ref) are not.

MECHANISM_SCHEMA_MAP: dict[str, type] = {
    "cli-install-recipe": CliInstallRecipe,
    "host-capability": HostCapability,
    "managed-config-spec": ManagedConfigSpec,
    "mcp-config-spec": McpConfigSpec,
    "permissions-struct": ProviderPermissions,
    "agent-file": AgentFile,
    "model-spec": ModelsSpec,
    "launch-spec": LaunchSpec,
    "lsp-self-support-spec": LspSelfSupportSpec,
    "obs-transport-note": ObsTransportNote,
    "acp-feature-note": ACPFeatureNote,
}

# Mechanism schemas that are conceptual patterns (no real Python type).
# These pass VAL-PCAP-013 by definition.
CONCEPTUAL_MECHANISMS: frozenset[str] = frozenset(
    {
        "boolean-set",
        "callable-ref",
        "none",
        "surfaces-struct",
        "tier-enum",
    }
)

# ── Catalogue State ──────────────────────────────────────────────────────

_catalogue: CapabilityCatalogue | None = None


@dataclass(frozen=True)
class CapabilityCatalogue:
    """Loaded and validated capability catalogue."""

    kinds_by_id: dict[str, CapabilityKind]
    kinds_by_domain: dict[str, list[CapabilityKind]]
    families: dict[str, FamilyDeclaration]


def _get_config_dir() -> Path:
    """Return the config/providers directory containing _capabilities.yaml."""
    # Resolve from the audiagentic package root (src/audiagentic/)
    import audiagentic.components.providers as pkg

    return Path(pkg.__file__).resolve().parent.parent.parent / "config" / "providers"


def _known_provider_ids(config_dir: Path) -> frozenset[str]:
    """Provider ids inferred from provider YAML filenames (excludes `_*.yaml`
    catalogue/family files). Used by VAL-PCAP-014 to reject provider-named
    kind ids — a lightweight filename check, not a descriptor load."""
    return frozenset(
        p.stem.replace("_", "-")
        for p in config_dir.glob("*.yaml")
        if not p.stem.startswith("_")
    )


def load_catalogue() -> CapabilityCatalogue:
    """Load and validate the capability catalogue from config files.

    Validates:
    - Every automation kind's family_id exists in _families.yaml (VAL-PCAP-011)
    - Every mechanism_schema resolves to a real type or is conceptual
      (VAL-PCAP-013)
    - No duplicate kind ids
    """
    import yaml

    config_dir = _get_config_dir()
    capabilities_path = config_dir / "_capabilities.yaml"
    families_path = config_dir / "_families.yaml"

    # Load the capability catalogue (kinds + optional merged families: section).
    try:
        with open(capabilities_path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise CatalogueError(f"_capabilities.yaml not found at {capabilities_path}") from None

    if not isinstance(data, dict) or "kinds" not in data:
        raise CatalogueError("_capabilities.yaml must have a 'kinds' mapping")

    # Families ("pins"): prefer a merged `families:` section in _capabilities.yaml;
    # fall back to the standalone _families.yaml during the PC01 migration (which
    # merges the two files into one).
    families_data = data.get("families")
    if families_data is None:
        try:
            with open(families_path) as f:
                families_data = yaml.safe_load(f)
        except FileNotFoundError:
            raise CatalogueError(
                "no families: section in _capabilities.yaml and "
                f"_families.yaml not found at {families_path}"
            ) from None

    if not isinstance(families_data, dict):
        raise CatalogueError(
            "families must be a mapping (a families: section in _capabilities.yaml "
            "or the _families.yaml file)"
        )

    families: dict[str, FamilyDeclaration] = {}
    for fid, fdata in families_data.items():
        families[fid] = FamilyDeclaration(
            family_id=fid,
            payload_contract=fdata["payload_contract"],
            result_contract=fdata["result_contract"],
            supported_modes=tuple(fdata["supported_modes"]),
            ownership_scope_required=bool(fdata.get("ownership_scope_required", False)),
        )

    kinds_by_id: dict[str, CapabilityKind] = {}
    for kid, kdata in data["kinds"].items():
        if kid in kinds_by_id:
            raise CatalogueError(f"duplicate kind id '{kid}'")

        authority = kdata["authority"]
        family_id = kdata.get("family_id")

        # VAL-PCAP-011: provisioned kinds must reference a known family.
        if authority == "provisioned":
            if not family_id:
                raise CatalogueError(f"VAL-PCAP-011: provisioned kind '{kid}' missing family_id")
            if family_id not in families:
                raise CatalogueError(
                    f"VAL-PCAP-011: provisioned kind '{kid}' references "
                    f"unknown family '{family_id}' — must exist in the families set"
                )

        # VAL-PCAP-013: mechanism_schema must resolve or be conceptual
        mech = kdata.get("mechanism_schema", "none")
        if mech != "none" and mech not in MECHANISM_SCHEMA_MAP:
            if mech not in CONCEPTUAL_MECHANISMS:
                raise CatalogueError(
                    f"VAL-PCAP-013: unknown mechanism_schema '{mech}' for kind "
                    f"'{kid}' — must be one of "
                    f"{sorted(MECHANISM_SCHEMA_MAP)} or {sorted(CONCEPTUAL_MECHANISMS)}"
                )

        # VAL-PCAP-014: a kind id is a domain-neutral concept, never a
        # provider name or implementation detail. Distinguish per-provider
        # variation via mechanism/evidence on a shared kind, not by baking
        # the provider id into the kind id.
        kind_tokens = set(kid.split("-"))
        provider_hit = kind_tokens & _known_provider_ids(config_dir)
        if provider_hit:
            raise CatalogueError(
                f"VAL-PCAP-014: kind '{kid}' embeds provider id(s) "
                f"{sorted(provider_hit)} — kinds must be provider-neutral; "
                "disambiguate via mechanism/evidence on a shared kind instead"
            )

        kinds_by_id[kid] = CapabilityKind(
            id=kid,
            domain=kdata["domain"],
            authority=authority,
            family_id=family_id,
            cardinality=kdata.get("cardinality", "single"),
            mechanism_schema=mech,
            canonical_kind=kdata.get("canonical_kind"),
        )

    # Build domain index
    kinds_by_domain: dict[str, list[CapabilityKind]] = {}
    for kind in kinds_by_id.values():
        kinds_by_domain.setdefault(kind.domain, []).append(kind)

    global _catalogue
    _catalogue = CapabilityCatalogue(
        kinds_by_id=kinds_by_id,
        kinds_by_domain=kinds_by_domain,
        families=families,
    )
    return _catalogue


def get_catalogue() -> CapabilityCatalogue:
    """Return the loaded catalogue, loading on first access."""
    global _catalogue
    if _catalogue is None:
        return load_catalogue()
    return _catalogue


# ── Validation helpers ───────────────────────────────────────────────────


def validate_capability_id(capability_id: str) -> CapabilityKind | None:
    """VAL-PCAP-009: check that a capability_id resolves to a catalogue kind.

    Returns the kind if valid, None if not found (caller raises error).
    """
    catalogue = get_catalogue()
    return catalogue.kinds_by_id.get(capability_id)


def validate_family_declaration(
    family_id: str,
    payload_contract: str | None = None,
    result_contract: str | None = None,
    supported_modes: tuple[str, ...] | None = None,
) -> None:
    """VAL-PCAP-011: validate a provider automation declaration against family config.

    If contract/mode args are provided, they must match the family declaration.
    """
    catalogue = get_catalogue()
    family = catalogue.families.get(family_id)
    if family is None:
        raise CatalogueError(
            f"VAL-PCAP-011: declared automation family '{family_id}' is not in _families.yaml"
        )

    if payload_contract and payload_contract != family.payload_contract:
        raise CatalogueError(
            f"VAL-PCAP-011: payload contract mismatch for family '{family_id}': "
            f"'{payload_contract}' vs expected '{family.payload_contract}'"
        )
    if result_contract and result_contract != family.result_contract:
        raise CatalogueError(
            f"VAL-PCAP-011: result contract mismatch for family '{family_id}': "
            f"'{result_contract}' vs expected '{family.result_contract}'"
        )
    if supported_modes and set(supported_modes) - set(family.supported_modes):
        raise CatalogueError(
            f"VAL-PCAP-011: unsupported modes for family '{family_id}': "
            f"{sorted(set(supported_modes) - set(family.supported_modes))}"
        )


# ── Re-export ────────────────────────────────────────────────────────────

__all__ = [
    "CapabilityCatalogue",
    "CapabilityKind",
    "CONCEPTUAL_MECHANISMS",
    "CatalogueError",
    "FamilyDeclaration",
    "MECHANISM_SCHEMA_MAP",
    "get_catalogue",
    "load_catalogue",
    "validate_capability_id",
    "validate_family_declaration",
]
