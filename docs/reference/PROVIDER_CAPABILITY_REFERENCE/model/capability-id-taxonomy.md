# Canonical Capability ID Mapping

**Authority:** provider-capability-model (PC) plan. Generated from `_capabilities.yaml` by `taxonomy_doc_generator.py` -- do not hand-edit; run `python -m audiagentic.components.providers.descriptors.taxonomy_doc_generator` to regenerate after changing the catalogue.

This is a **closed catalogue**: every provider `capabilities:` entry's kind must resolve here (VAL-PCAP-009). Provisioned kinds must reference a valid family (VAL-PCAP-011); mechanism schemas must resolve to a real type or a known conceptual pattern (VAL-PCAP-013); no kind id may embed a provider/harness/implementation name (VAL-PCAP-014).

## Capability kinds

### Provisioned kinds (reconcile against a family)

#### `cli-install`

**Authority:** provisioned | **Cardinality:** single | **Family:** cli-lifecycle (modes: plan, apply, prune, status, upgrade-status, upgrade) | **Mechanism:** cli-install-recipe

Provider can be installed from the harness via a known install command plus a version probe.

#### `hooks`

**Authority:** provisioned | **Cardinality:** single | **Family:** managed-hooks (modes: apply, prune, status) | **Mechanism:** managed-config-spec

Provider has a manageable hooks config file with reader/writer/remover operations.

#### `lsp-config`

**Authority:** provisioned | **Cardinality:** single | **Family:** language-server-projection (modes: apply, prune, status) | **Mechanism:** managed-config-spec

Provider has a manageable LSP config surface (reader/writer/remover over a config file). Dispatches via the language-server-projection family -- kept separate from lsp-self-support because the two route through genuinely different, already-wired automation handlers (PC07 step 4).

#### `lsp-self-support`

**Authority:** provisioned | **Cardinality:** single | **Family:** self-provided-lsp (modes: apply, status) | **Mechanism:** lsp-self-support-spec

Provider self-provides LSP via a callable hook that installs support, with an optional non-mutating probe for status queries. Dispatches via the self-provided-lsp family.

#### `mcp`

**Authority:** provisioned | **Cardinality:** single | **Family:** managed-mcp (modes: apply, prune, status) | **Mechanism:** mcp-config-spec

Provider has a manageable MCP server config file with reader/writer/remover operations.

#### `models`

**Authority:** provisioned | **Cardinality:** single | **Family:** model-projection (modes: plan, apply, prune, status) | **Mechanism:** model-spec

Compound: curation (store) + entry renderer + catalog refresh + supported connectors + per-vendor credential references (secrets.py scheme:locator strings).

#### `plugins`

**Authority:** provisioned | **Cardinality:** single | **Family:** plugin-entry (modes: apply, prune, status) | **Mechanism:** managed-config-spec

Provider has a manageable plugin config with reader/writer/remover over a known path.

#### `surface-instruction`

**Authority:** provisioned | **Cardinality:** single | **Family:** generated-surfaces (modes: plan, apply, prune, status) | **Mechanism:** boolean-set

Provider has an instruction file in the project root that the harness contributes managed content to.

#### `surface-skill`

**Authority:** provisioned | **Cardinality:** single | **Family:** generated-surfaces (modes: plan, apply, prune, status) | **Mechanism:** none

Provider has a dedicated skill folder path where skills are contributed for this provider.

#### `surfaces`

**Authority:** provisioned | **Cardinality:** single | **Family:** generated-surfaces (modes: plan, apply, prune, status) | **Mechanism:** surfaces-struct

Provider supports rendering generated provider surfaces (skills + instructions) via a renderer declaration.

### Operational kinds (harness reads for decisions)

#### `agent-files`

**Authority:** operational | **Cardinality:** list | **Mechanism:** agent-file

Provider's agent instruction files (managed or unmanaged) in the project root.

#### `execution-isolation`

**Authority:** operational | **Cardinality:** single | **Mechanism:** tier-enum

Provider's execution isolation level, used for resource allocation and contention routing. Tiers are open-ended.

#### `host-extensions`

**Authority:** operational | **Cardinality:** list | **Mechanism:** host-capability

Provider declares host/editor extensions it requires or uses (e.g. a VS Code extension id). List cardinality -- a provider may declare multiple.

#### `launch`

**Authority:** operational | **Cardinality:** single | **Mechanism:** launch-spec

Compound: declared per-intent channel surface (execute/interactive/agent -> interaction/observability channels) + declarative launch recipes keyed by profile name.

#### `launch-isolation`

**Authority:** operational | **Cardinality:** single | **Mechanism:** tier-enum

Can the provider launch MCP servers in isolation (only caller's curated entries, no user global config)? Tiers are open-ended.

#### `permissions`

**Authority:** operational | **Cardinality:** single | **Mechanism:** permissions-struct

Provider declares its permission surface via boolean flags (write_files, execute_shell, browse_web, read_env).

### Evidence-only kinds (inert records)

#### `acp`

**Authority:** evidence-only | **Cardinality:** list | **Mechanism:** acp-feature-note

ACP protocol-feature evidence. One list entry per feature (mechanism.feature: stdio-transport|live-session|session-resume|shared-live-session), each with its own evidence -- verification status genuinely differs per feature. Never a provider-specific tag (VAL-PCAP-014).

#### `model-config-projection`

**Authority:** evidence-only | **Cardinality:** single | **Mechanism:** none

Provider could potentially have model config projected into its native file, but the mechanism is unresolved/blocked. Evidence-only with action_needed tracking.

#### `model-local-state`

**Authority:** evidence-only | **Cardinality:** single | **Mechanism:** none

Provider has a local model config file/state directory that is not a configurable surface like mcp. Evidence-only because the harness cannot automate against it.

#### `obs-transport-observability`

**Authority:** evidence-only | **Cardinality:** list | **Mechanism:** obs-transport-note

Can the harness observe this provider's execution over a given transport? One list entry per transport (mechanism.transport, a generic transport concept -- never a provider tag, VAL-PCAP-014), each with its own evidence.

## Provider capability matrix

Not hand-maintained here -- a hand-written matrix drifts the moment a provider YAML changes (this is exactly what went stale before PC07 step 4). Use `describe_provider(provider_id)` (`providers_api.py`) or read the provider's YAML under `config/providers/<id>.yaml` directly for the live, authoritative per-provider capability set.

## Evidence source mapping

| Source | Path | Use for |
| --- | --- | --- |
| Provider YAML | `config/providers/<id>.yaml` | Verified facts from descriptor fields |
| Evidence docs | `harnesses/profiles/<id>.md` | Model-related capabilities (catalog, connectors, vendor injection) |
| Capability matrix | `endpoints/provider-model-endpoints.md` | Cross-reference for model connector support, projection modes |

## Fact anchor convention

Evidence `source` values use these forms:

- Descriptor field: `config/providers/<id>.yaml#<capability-kind>`
- Evidence doc: `harnesses/profiles/<id>.md#<section>`
- Capability matrix: `endpoints/provider-model-endpoints.md#<provider>`
