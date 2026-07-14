# AUDiaGentic Architecture Standards

Non-negotiable. Violation = architectural defect, not style.

## 1. Layer Boundaries

```
CLI / composition root
Components --consume--> Foundation (capabilities) --may read--> Runtime environment
Runtime (orchestration) --bootstraps/wires via seams--> Foundation capabilities
```

- CLI/composition root (`audiagentic/launcher.py`, `audiagentic/commands/*`): wire app; may import any layer, including optional components.
- Components: product capabilities; may import foundation and runtime.
- Foundation: shared capabilities: errors, events, IO, toolchains, workflow, MCP, lifecycle (`foundation/lifecycle`). May read `runtime/system` to adapt (for example platform tool selection).
- `runtime/system`: read-only live facts: platform, process identity, paths. Importable by all.
- Runtime orchestration (`runtime/harness`, `rig`, `update`, `build`): bootstrap, lifecycle, durable state. May call foundation during bootstrap; after startup prefer events/contribution registries. Guidance only.

**Rules:**
- Foundation never imports components or runtime orchestration; `runtime/system` allowed.
- `runtime/system`: facts only; no orchestration or imports from foundation, components, or other runtime.
- Runtime never imports optional component internals; use events/contribution registries.
- Tests exempt from production import rules.
- Foundation modules/functions/event strings/registry keys must be domain-neutral; component vocabulary = layering violation.
- Composition roots exempt from import direction.
- Do not use `get_capability`/`register_capability` callbacks for direct imports: use events, no indirection, or composition-root registry check + import.

### 1.1 Registries Are Extension Points, Not Hidden Coupling

A string key does not remove a dependency. Registries may select among implementations
only when all of these are explicit and machine-checked:

- one owning layer/component defines the typed protocol and key namespace;
- declarations identify support/capability, while handler binding occurs in that owner
  or an approved composition root;
- callers depend on the protocol and receive typed results, never retrieve arbitrary
  services or call foreign implementation symbols;
- keys carry no foreign removable-domain vocabulary or policy;
- registration, replacement, lifetime, duplicate-key behavior, and unknown-key failure
  are deterministic and tested.

Forbidden: service-locator APIs, arbitrary `dict[str, Callable]` used to conceal a
component call, string/dotpath lookup introduced only to evade an import boundary,
requester-owned handler names, or a registry that makes a forbidden dependency appear
indirect. Use a direct import for allowed same-layer dependencies, a typed event for
decoupled notification, or composition-root wiring for optional implementations.

Architecture graph checks follow resolved registry bindings as dependency edges. A
registry never grants an exemption from layer, ownership, vocabulary, or mutation rules.

## 2. Config Over Code

- Extensibility never requires Python edits.
- Entity lists (components, providers, tools, states, policies, capabilities) live in YAML/JSON, never Python.
- No entity-name `if/elif`; use config lookup or a §1.1-compliant typed extension registry.
- New capability: config file or registry contribution.

## 3. Logic Containment

- Shared logic in 2+ files: extract to foundation immediately.
- God object: >350 lines or >3 responsibilities: split by concern unless one cohesive unit.
- Dataclasses with >80% field overlap: one canonical type.

## 4. Platform Independence

- No editor-specific CLI, binary, or paths; use pluggable host adapter.
- Resolve host behavior (extensions, workspace detection) at runtime via config-driven adapter.
- No local folders, network, or environment details in code; use uncommitted config/env.

## 5. Component Discovery

- No Python import list or `__all__` for pluggable modules; use `pkgutil.iter_modules()` or config discovery.
- IDs come from loaded descriptors, never parallel Python constants.

## 6. MCP Server Construction

- Use `mcp_server(__name__)` from `foundation.mcp.component_server`; never `FastMCP` directly.
- `main()` uses `run_mcp_server(server_factory, label)`.

## 7. Virtual Assets

- Generated assets: `(path_pattern, generator_fn)` registry; components register via lifecycle hooks.
- Runtime iterates registry; never branches on asset paths.

## 8. Error Handling

- Only domain exception: `AudiaGenticError`; no parallel hierarchies or raw `ValueError`/`RuntimeError` at public boundaries.
- Every error has stable `PREFIX-COMPONENT-NNN` code (example `VAL-PCFG-001`). Prefer `make_error()` from `foundation.contracts.errors`, module-bound `make_error_factory(...)`, or thin helper.
- Before using code, add it to owning `config/components/<component>/error-resolutions.yaml`; component segment determines owner. Audits cover every `code=` in `AudiaGenticError(...)` under `src/`; missing entries become plan items before release.
- `code`: canonical identity. `message`: concise operator statement. Config-only optional `resolution`: remediation/checks, not message repeat. `details`: context only.
- `except Exception:` only at external boundaries. Every `except`: log `exc_info=True`, wrap `AudiaGenticError`, or safe default. Silent `pass` only harmless expected teardown.
- Never place raw stdout/stderr, API keys, tokens, or prompts in error details; redact/summarize.

### 8.1 External-service failures

External services include remote APIs, catalog/discovery endpoints, and
connectivity probes. Classify every failure as exactly one of:

| Class | Examples | Retry | Fallback |
|---|---|---|---|
| `transient` | timeout, unreachable service, HTTP 429, HTTP 5xx | One bounded retry | Last-known-good cache when available |
| `configuration` | invalid base URL, unsupported wire API, invalid local setup | Never | None |
| `authorization` | HTTP 401/403, expired or absent credential | Never | None |
| `contract` | malformed or incompatible response | Never | None |

- Best-effort background work, including catalog refresh and connectivity
  probes, degrades to cached state when available. It reports `action_needed`
  and must not fail enclosing sync or reconcile solely for that remote failure.
- Explicit user-invoked operations may return the owning component's canonical
  `CON-*` error. Error details contain failure class and safe structural
  context only.
- A degraded result uses semantic fields `failure_class`, `fallback`
  (`cached|none`), `stale`, `stale_age` when known, `action_needed`, and
  `error_code`. Do not introduce a cross-domain result dataclass merely for
  these fields.
- Never retry authorization, configuration, or contract failures. Never add
  retry loops, sleep-loop polling, or unbounded backoff.
- Do not log or persist API keys, authorization headers, key-bearing URLs, raw
  response bodies, or unredacted exception text. Apply canonical redaction at
  the remote-call boundary before producing logs, timelines, results, or
  dead-letter records.
- When a remote call runs in an event-bus handler, §14 takes precedence:
  handler exceptions never escape, the failure is redacted and dead-lettered,
  and cached degradation/action-needed supplements rather than replaces that
  record.

## 9. Logging

- Module logger only: `logger = logging.getLogger(__name__)`; never inline.
- `print()` only CLI entry points; library code uses logger.
- Levels: `debug` trace; `info` notable ops; `warning` non-fatal + `exc_info=True`; `error` failure + `exc_info=True`.
- Entity messages include `extra={"component": ..., "provider": ..., "item_id": ...}`.
- Never log MCP tool args.

## 10. Migration Doctrine

- No compatibility shims, deprecations, legacy paths, or deferred tests unless explicitly required. Remove old code with replacement.
- Each migration step works; add/update tests with migration.
- Moves/renames/deletes: grep whole repo, including `tests/`, for old dotted path as string (patches, `importlib`, decorators, config/YAML). Proof = green full suite: `python -m pytest tests/unit`; grep or partial suite insufficient.

## 11. Lazy Initialization

Lazy loading invisible to callers.

- Prefer on-first-access loading for config registries, heavy dependencies, shared state.
- Public API exposes no loaders, priming, or load-state checks; accessor returns ready value.
- Guard stays inside accessor; loader idempotent, cached no-op after completion.
- Prefer shared registry lazy-loader support over local `_loaded`/`_ensure_loaded()`.

## 12. Anti-Pattern Quick Reference

| Anti-pattern | Fix |
|---|---|
| Hardcoded entities / entity-name `if/elif` | Config or `(key, handler)` registry |
| Foundation imports components/runtime outside `runtime/system` | Events/registry, invert dependency, or move fact to `runtime/system` |
| `runtime/system` orchestration/upward imports | Read-only facts only |
| Runtime imports optional component | Events/contribution registry |
| Manual `FastMCP(...)` | `mcp_server(__name__)` |
| Public `ValueError` | `AudiaGenticError(code=..., ...)` |
| `except Exception: pass` | Log, wrap, or safe default |
| Inline logger / library `print(...)` | Module `logger` |
| Raw process output in errors/results/logs | `redact_text()` at boundary |
| Pluggable `__all__` / editor CLI/path | Discovery / host adapter |
| Caller loads/checks state; repeated loader work | Internal idempotent accessor loader |
| Local lazy guard | Shared registry lazy-loader |
| Callback lookup for direct import | Event or composition-root import |
| Component vocabulary in foundation | Domain-neutral name or move to component |
| Unregistered error code | Owning `error-resolutions.yaml` entry first |

## 13. Contract Schema Ownership

- Component schema `components/<component>/contracts/<name>.schema.json` is authoritative writable copy.
- Same-name `foundation/contracts/schemas/<name>.schema.json` is read-only `schema_registry` mirror; update byte-identically after source change.
- Component-only schemas stay under component; no foundation mirror, `schema_registry.py`, or `canonical_ids.py` registration.
- Foundation-native schemas stay only in `foundation/contracts/schemas/`.
- Unit test asserts byte equality for every matching component/foundation pair; foundation-only schemas exempt.

**Decision:** 2026-07-10 — `event-trigger.schema.json` agent-jobs-only; no foundation mirror or registry entry.

## 14. Async Event Handling

Extends §8 at async/event boundaries.

- Handlers never raise from bus. Boundary exceptions: log and durably dead-letter with `write_dead_letter`; pipeline continues.
- v1: no automatic trigger retry. LLM launches may duplicate jobs/charges. Automatic retry requires documented component idempotency guard/key.
- Failed firing, dispatch, or outcome apply: append-only ndjson via `write_dead_letter` (`audiagentic.components.agent_jobs.dead_letter`) and shared `append_operational_record` (EDJ20), at `.audiagentic/runtime/agent-jobs/dead-letter.ndjson`.
- Record: `{event_type, payload_summary (redacted, max 500 chars), metadata, trigger_id/job_id, error_code, error_message, correlation_id, timestamp}`.
- Manual replay: `read_dead_letters`, recover inputs, redispatch. Automatic replay out of scope v1.
- No raw prompts, keys, tokens, or LLM output. `payload_summary` is redacted description; denylist enforced at write.

**Decision:** 2026-07-10 — async error standard added after EDJ02/04/05 review; EDJ12 owns dead-letter format.

## 15. Output Redaction at Subprocess Boundaries

Captured subprocess stdout/stderr must be redacted before structured returns, persistence, or logs; it can contain credentials.

- At disk boundary (logs, completion JSON, results, ndjson), apply `redact_text()` from `foundation/logging/redaction.py`.
- At structured-return boundary (dict, `StepResult`, return), apply `redact_text()`.
- Only pattern authority: `DEFAULT_REDACT_PATTERNS` in `foundation/logging/redaction.py`; extend it, never local regex lists.
- `AudiaGenticError._redact_value()` is insufficient (1024-char truncation/subset patterns). Redact raw output at call site before adding error details.
- Redaction changes output boundaries only; direct streaming/interactive terminal output exempt.

**Exempt:** intentional credential provisioning to config; auth token returns; transport-only Authorization headers; captured-and-discarded output when only exit code is used.

**Decision:** 2026-07-12 — standard added after OU01 audit; prior §8, observability, and §14 rules missed general structured/disk subprocess output.

## 16. Managed Mutation Ownership

Every durable mutation has one owner and one lifecycle path. Choose the primitive by
artifact shape; do not create a component-local ownership or reconciliation system.

| Artifact shape | Required primitive |
|---|---|
| Named entries in shared external config | `ManagedConfigSpec` + `sync_managed_config` + `ManagedFragmentRegistry` |
| Nested keys in shared JSON/YAML/TOML | `ConfigPatcher` + `ArtifactRegistry` |
| Whole file owned by one recipe | `WriteFileStep` + `ArtifactRegistry` |
| Generated component/provider surface | descriptor virtual asset or registered renderer + managed block |
| Owning-component durable record | component store + atomic helper from `foundation.io` |
| Dynamically discovered, unowned third-party repair | bounded adapter-local exemption meeting every rule below |

Generic orchestration owns path resolution, ownership/adoption, collisions, dry-run,
apply/prune, reload, status, error normalization, redaction, and observability. Custom
implementations own format parsing, rendering, and merge semantics only. Code outside
the generic managed-config core must not call a `ManagedConfigSpec` writer/remover
directly.

Adapter-specific logic is justified by format, not entity name. Generic builders and
services never branch on provider/component ids to select an implementation; config or
a `(key, handler)` registry selects the adapter. Generic specs use domain-opaque payloads
and never import a component-owned payload type.

An exemption is valid only when all are true:

- artifact belongs to an external tool and is not created/owned by AUDiaGentic;
- location or shape is dynamically discovered and no existing primitive fits;
- mutation is contained in one adapter-local function;
- write is atomic and redacted, with preservation and failure tests;
- code comment cites the audit/plan item and states why each generic primitive fails.

Literal brace values, surgical nested-key edits, convenience, or one current consumer
are not exemptions. `ConfigPatcher` accepts arbitrary values without template
substitution and exists for surgical structured-config edits.

Inventory and current remediation ownership live in
`docs/reference/MANAGED_MUTATION_AUDIT.md`. Architecture tests keep its scanner and
table in exact agreement.
