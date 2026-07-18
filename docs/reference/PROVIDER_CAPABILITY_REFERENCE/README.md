# AUDiaGentic Provider Capability Reference

Status: canonical code-facing reference resource  
Rebuilt: 2026-07-17

This package describes the provider, harness, endpoint, transport, configuration, control, telemetry, and operation capabilities known to AUDiaGentic. It is **curated evidence and design reference** — not executable implementation code and not runtime configuration.

## Runtime authority boundary (RV560)

Nothing in this package is runtime authority. Runtime behavior is enabled only by:

1. **Provider descriptors** (`config/providers/*.yaml`) — MA20 capability declarations and operational fields, loaded by the providers component.
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

## Design boundaries

- Harness identity is separate from provider identity.
- Provider identity is separate from endpoint family and upstream model vendor.
- ACP controls agent sessions; MCP carries tools and structured tool results.
- A displayed tool call is not automatically a client execution request.
- Provider connectivity does not imply provider telemetry.
- Context remaining is usually derived from model limits plus observed token usage.
- Subscription allowances, API balances, rate limits, and context budgets are independent.
- Scraped or inferred facts must never be represented as official facts.
