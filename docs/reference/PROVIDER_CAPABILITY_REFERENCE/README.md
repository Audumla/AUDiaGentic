# AUDiaGentic Provider Capability Reference

Status: canonical code-facing reference resource  
Package files last synchronized: 2026-09-13. The latest registry rebuild
recorded in the evidence remains 2026-07-17. Individual facts carry their own
validation timestamp; treat this package as evidence with explicit freshness,
not as a claim that every upstream capability is current today.

This package describes the provider, harness, endpoint, transport, configuration, control, telemetry, and operation capabilities known to AUDiaGentic. It is **curated evidence and design reference** — not executable implementation code and not runtime configuration.

The `registries/providers.yaml` keys are normalized vendor/endpoint capability
families, not a count of the provider adapter descriptors installed in this
checkout. The runtime descriptor inventory lives under
`src/audiagentic/config/providers/`; differences between those sets are
expected and must not be “fixed” by copying one registry into the other.

## Runtime authority boundary (RV560)

Nothing in this package is runtime authority. Runtime behavior is enabled only by:

1. **Provider descriptors** (`src/audiagentic/config/providers/*.yaml`) — MA20 capability declarations and operational fields, loaded by the providers component.
2. **MA19 `capability_facts`** in those same descriptors — typed evidence records.

This package is the knowledge source that humans and agents **project into** those descriptors (see each file's projection notes). Runtime code MUST NOT load `registries/*.yaml`, profiles, or matrices from this package; an architecture guard enforces the no-runtime-import rule (MA19 validation 9/10).

## Authority order within this package

When two artefacts here disagree, use this precedence:

1. `registries/*.yaml` — normalized evidence index.
2. `schemas/*.schema.json` — structural contracts for those registries.
3. Domain specifications under `model/`, `protocols/`, `execution/`, `configuration/`, `endpoints/`, and `telemetry/`.
4. Harness profiles under `harnesses/profiles/`.
5. `validation/` evidence and unresolved-item records.

A registry fact must not be promoted to `verified` without evidence. Unknown and unsupported are distinct states.

## Plan-item projection

| Package area | Projects into | Consuming plan items |
| --- | --- | --- |
| `model/capability-operation-contract.md` | providers_api family contracts | MA16, MA20 (authority doc) |
| `model/capability-id-taxonomy.md` | `capability_facts` ids (open namespace) | MA19 |
| `harnesses/harness-observability-lifecycle.md` | descriptor observability declaration + MA19 facts | AS19, AS21, SH07 |
| `harnesses/profiles/*.md`, `registries/harnesses.yaml` | reference-only probe targets and evidence anchors | MA19 and bounded provider/harness probe items created on demand |
| `protocols/acp-capabilities.md` | ACP capability facts, transport semantics | MA18, AS13/AS14 |
| `configuration/provider-config-projection.md` | isolation-tier facts, materialization strategy | MA20 validation 12, SH02, SH06 |
| `execution/*` | execution boundary contracts | MA17, MA18 |
| `endpoints/`, `telemetry/` | model/endpoint facts, telemetry adapters | MO07, PT01/PT02 |

## Start here

- [Reference architecture](architecture/reference-architecture.md)
- [Capability taxonomy](model/capability-id-taxonomy.md)
- [Operation contract](model/capability-operation-contract.md)
- [Provider model endpoints](endpoints/provider-model-endpoints.md)
- [Provider telemetry](telemetry/provider-telemetry.md)
- [ACP capabilities](protocols/acp-capabilities.md)
- [Harness observability & lifecycle model](harnesses/harness-observability-lifecycle.md)
- [Harness capability matrix](harnesses/provider-capability-matrix.md)
- [Validation status](validation/validation-report.md)

## Machine-readable resources

- `registries/capabilities.yaml`
- `registries/harnesses.yaml`
- `registries/providers.yaml`
- `registries/protocols.yaml`
- `registries/telemetry.yaml`
- `registries/evidence.yaml`

## Package map

- `architecture/` — reference topology and resource-consumption guidance.
- `model/` — capability IDs and operation contracts.
- `protocols/` — protocol-specific capability and lifecycle semantics.
- `execution/` — provider execution boundaries and transport mappings.
- `endpoints/` — provider/model endpoint and configuration projections.
- `configuration/` — managed provider-configuration projection guidance.
- `harnesses/` — harness profiles, observability lifecycle, and capability
  matrix.
- `telemetry/` — telemetry capability and evidence definitions.
- `schemas/` and `registries/` — machine-readable structure and normalized
  evidence indexes.
- `validation/` — package validation, migration, and freshness evidence.

## Design boundaries

- Harness identity is separate from provider identity.
- Provider identity is separate from endpoint family and upstream model vendor.
- ACP controls agent sessions; MCP carries tools and structured tool results.
- A displayed tool call is not automatically a client execution request.
- Provider connectivity does not imply provider telemetry.
- Context remaining is usually derived from model limits plus observed token usage.
- Subscription allowances, API balances, rate limits, and context budgets are independent.
- Scraped or inferred facts must never be represented as official facts.
