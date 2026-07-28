"""Single source of truth for the capability-id taxonomy reference doc.

_capabilities.yaml is authoritative for kind mechanics (domain, authority,
cardinality, family_id, mechanism_schema) -- this module reads it directly
so the generated table can never drift from the real catalogue the loader
enforces (VAL-PCAP-009/011/013/014). One-line prose per kind is hand-curated
here (the catalogue has no natural place for prose) and reviewed whenever a
kind is added, renamed, or removed.

``docs/reference/PROVIDER_CAPABILITY_REFERENCE/model/capability-id-taxonomy.md``
is generated from ``render_taxonomy_doc()`` -- run this module as a script to
regenerate; ``test_taxonomy_doc_matches_generator`` is the drift guard.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.descriptors.capability_catalogue import (
    get_catalogue,
)

_DOC_PATH = (
    Path(__file__).resolve().parents[5]
    / "docs"
    / "reference"
    / "PROVIDER_CAPABILITY_REFERENCE"
    / "model"
    / "capability-id-taxonomy.md"
)

# One-line description per kind id. Reviewed whenever a kind is added,
# renamed, or removed (see the module docstring) -- the catalogue itself
# only carries mechanics, not prose.
KIND_DESCRIPTIONS: dict[str, str] = {
    "cli-install": "Provider can be installed from the harness via a known install command plus a version probe.",
    "mcp": "Provider has a manageable MCP server config file with reader/writer/remover operations.",
    "hooks": "Provider has a manageable hooks config file with reader/writer/remover operations.",
    "models": "Compound: curation (store) + entry renderer + catalog refresh + supported connectors + per-vendor credential references (secrets.py scheme:locator strings).",
    "surfaces": "Provider supports rendering generated provider surfaces (skills + instructions) via a renderer declaration.",
    "lsp-config": "Provider has a manageable LSP config surface (reader/writer/remover over a config file). Dispatches via the language-server-projection family -- kept separate from lsp-self-support because the two route through genuinely different, already-wired automation handlers (PC07 step 4).",
    "lsp-self-support": "Provider self-provides LSP via a callable hook that installs support, with an optional non-mutating probe for status queries. Dispatches via the self-provided-lsp family.",
    "host-extensions": "Provider declares host/editor extensions it requires or uses (e.g. a VS Code extension id). List cardinality -- a provider may declare multiple.",
    "permissions": "Provider declares its permission surface via boolean flags (write_files, execute_shell, browse_web, read_env).",
    "agent-files": "Provider's agent instruction files (managed or unmanaged) in the project root.",
    "launch": "Compound: declared per-intent channel surface (execute/interactive/agent -> interaction/observability channels) + declarative launch recipes keyed by profile name.",
    "surface-skill": "Provider has a dedicated skill folder path where skills are contributed for this provider.",
    "surface-instruction": "Provider has an instruction file in the project root that the harness contributes managed content to.",
    "launch-isolation": "Can the provider launch MCP servers in isolation (only caller's curated entries, no user global config)? Tiers are open-ended.",
    "execution-isolation": "Provider's execution isolation level, used for resource allocation and contention routing. Tiers are open-ended.",
    "plugins": "Provider has a manageable plugin config with reader/writer/remover over a known path.",
    "acp": "ACP protocol-feature evidence. One list entry per feature (mechanism.feature: stdio-transport|live-session|session-resume|shared-live-session), each with its own evidence -- verification status genuinely differs per feature. Never a provider-specific tag (VAL-PCAP-014).",
    "model-local-state": "Provider has a local model config file/state directory that is not a configurable surface like mcp. Evidence-only because the harness cannot automate against it.",
    "model-config-projection": "Provider could potentially have model config projected into its native file, but the mechanism is unresolved/blocked. Evidence-only with action_needed tracking.",
    "obs-transport-observability": "Can the harness observe this provider's execution over a given transport? One list entry per transport (mechanism.transport, a generic transport concept -- never a provider tag, VAL-PCAP-014), each with its own evidence.",
}

_AUTHORITY_HEADING = {
    "provisioned": "Provisioned kinds (reconcile against a family)",
    "operational": "Operational kinds (harness reads for decisions)",
    "evidence-only": "Evidence-only kinds (inert records)",
}
_AUTHORITY_ORDER = ("provisioned", "operational", "evidence-only")


def render_taxonomy_doc() -> str:
    catalogue = get_catalogue()
    lines: list[str] = [
        "# Canonical Capability ID Mapping",
        "",
        "**Authority:** provider-capability-model (PC) plan. Generated from "
        "`_capabilities.yaml` by `taxonomy_doc_generator.py` -- do not hand-edit; "
        "run `python -m "
        "audiagentic.components.providers.descriptors.taxonomy_doc_generator` "
        "to regenerate after changing the catalogue.",
        "",
        "This is a **closed catalogue**: every provider `capabilities:` entry's "
        "kind must resolve here (VAL-PCAP-009). Provisioned kinds must reference "
        "a valid family (VAL-PCAP-011); mechanism schemas must resolve to a real "
        "type or a known conceptual pattern (VAL-PCAP-013); no kind id may embed "
        "a provider/harness/implementation name (VAL-PCAP-014).",
        "",
        "## Capability kinds",
        "",
    ]

    for authority in _AUTHORITY_ORDER:
        kinds = sorted(
            (k for k in catalogue.kinds_by_id.values() if k.authority == authority),
            key=lambda k: k.id,
        )
        if not kinds:
            continue
        lines.append(f"### {_AUTHORITY_HEADING[authority]}")
        lines.append("")
        for kind in kinds:
            lines.append(f"#### `{kind.id}`")
            lines.append("")
            meta = [f"**Authority:** {kind.authority}", f"**Cardinality:** {kind.cardinality}"]
            if kind.family_id:
                family = catalogue.families[kind.family_id]
                meta.append(f"**Family:** {kind.family_id} (modes: {', '.join(family.supported_modes)})")
            meta.append(f"**Mechanism:** {kind.mechanism_schema}")
            lines.append(" | ".join(meta))
            lines.append("")
            description = KIND_DESCRIPTIONS.get(kind.id)
            if description:
                lines.append(description)
                lines.append("")

    lines.extend(
        [
            "## Provider capability matrix",
            "",
            "Not hand-maintained here -- a hand-written matrix drifts the moment a "
            "provider YAML changes (this is exactly what went stale before PC07 "
            "step 4). Use `describe_provider(provider_id)` "
            "(`providers_api.py`) or read the provider's YAML under "
            "`config/providers/<id>.yaml` directly for the live, authoritative "
            "per-provider capability set.",
            "",
            "## Evidence source mapping",
            "",
            "| Source | Path | Use for |",
            "| --- | --- | --- |",
            "| Provider YAML | `config/providers/<id>.yaml` | Verified facts from descriptor fields |",
            "| Evidence docs | `harnesses/profiles/<id>.md` | Model-related capabilities (catalog, connectors, vendor injection) |",
            "| Capability matrix | `endpoints/provider-model-endpoints.md` | Cross-reference for model connector support, projection modes |",
            "",
            "## Fact anchor convention",
            "",
            "Evidence `source` values use these forms:",
            "",
            "- Descriptor field: `config/providers/<id>.yaml#<capability-kind>`",
            "- Evidence doc: `harnesses/profiles/<id>.md#<section>`",
            "- Capability matrix: `endpoints/provider-model-endpoints.md#<provider>`",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    _DOC_PATH.write_text(render_taxonomy_doc(), encoding="utf-8")
    print(f"wrote {_DOC_PATH}")
