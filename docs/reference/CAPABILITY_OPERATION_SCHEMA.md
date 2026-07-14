# Capability-operation schema — SUPERSEDED runtime shape (MA16 Gate 0)

> **Superseded by RV401 (2026-07-14).** Do not implement this document as a
> runtime Python object model, closed taxonomy, or dispatch contract. Retain it
> as design history and as input when moving rich provider facts into
> config/documentation. Current authority: MA16 and MA19 plan items. Runtime
> code exposes only fields used by current MA17 call sites; explicit provider
> registration, not catalog strings, enables handlers and execution ports.
> RV403 further assigns capability config, validation, loading, catalog
> generation, evidence linkage, and reference/status tooling to the providers
> component. Foundation owns neutral communication protocols only.
> RV404 supersedes that final sentence: capability request/result/gateway types
> are provider-specific too and belong to the providers public API. Foundation
> owns no capability concept. Do not create `foundation/ports` or a capability
> compatibility facade.
>
> **RV406 (2026-07-14, implemented):** `foundation/capability_catalog/` is
> DELETED. Dispatch = existing providers `ProviderRecipeRegistry` +
> `ProviderCapabilityRecipe`; `ProviderRecipeResult` is the public envelope.
> Mechanics ownership: generic-capability recipe implementations are
> provider-owned (built from descriptors, parameterized by requester payload);
> a provider path/filename/command in a requester-owned file is in the wrong
> place. Decomposition: requester intent → common declaration (§4/§8 remain
> the intent/vocabulary reference, §8 reconciled with ProviderRecipeKind);
> provider mechanics → provider recipes; backend behavior → owner's code
> recipes. Facts are declared; behavior is coded. Runtime authority remains
> explicit registration only.

Historical status: **APPROVED, NOW SUPERSEDED** (Gate 0 review completed 2026-07-14, RV373; open
questions resolved in §9). The strict loader implements exactly this shape;
any change from here goes through a plan review on MA16.

Design rules honored: foundation-neutral vocabulary only (no provider, memory,
Hindsight, LSP, harness, or package-manager terms in core fields); provider
facts live in provider-owned declarations; requesters can never name handlers,
paths, serializers, or provider metadata; single schema version, strict load.

## 1. Files and ownership

- Provider-owned declaration: `config/providers/capabilities/<provider-id>.yaml`
  — the sole editable source of provider capability facts. Descriptor-derived
  fields (probe, config surfaces, executables) are **compiled into** the
  machine catalog from the existing provider descriptor at build time; they are
  never hand-copied into the declaration.
- Generated machine catalog: deterministic JSON, one entry per provider,
  regenerated from declarations + descriptor compilation. Never hand-edited.
- Evidence records: referenced by id; format/process owned by MA19.

## 2. Capability kind taxonomy (closed set, v1)

`install`, `probe`, `execute`, `config-mutation`, `managed-mcp`,
`managed-lsp`, `instructions-surface`, `skills-surface`, `host-extension`,
`hooks`, `plugin`, `catalog-discovery`, `model-projection`, `launch-env`,
`launch-override`.

Unknown kind fails load (`VAL-CAP-002`). New kinds require schema review —
they are core vocabulary, not extension data. A kind names WHAT a capability
is, never HOW a provider exposes it: two providers may implement the same
kind through entirely different mechanisms, and future specialized
managed-config flavors enter as new distinct kinds (see §9.3).

## 3. Capability record shape

```yaml
schema: capability-catalog@1        # sole accepted version
provider-id: <provider>
capabilities:
  - capability-id: <stable neutral slug>   # unique per provider
    kind: <taxonomy kind>
    support: supported | manual | blocked | unsupported | unverified
    evidence: <evidence-record-id>          # required unless support: unverified
    evidence-review: approved | pending | quarantined
    operations:                             # lifecycle operations offered
      install | configure | verify | uninstall | prune: recipe:<name>   # named ref only (§9.1)
    modes:                                  # request modes; omitted mode = supported
      plan:   supported | not-applicable
      apply:  supported | not-applicable
      prune:  supported | not-applicable
      status: supported | not-applicable
    contract:
      payload-schema: <neutral payload schema id>   # e.g. managed-entry@1
      surface: config-file | process | env | host-extension | network
      ownership: managed-entry | managed-block | whole-file | none
      reload: none | file-watch | restart-required | declared-command
      dry-run: full | partial | not-applicable
      secrets: none | env-ref-only | resolved-at-write
    binding: <opaque provider-owned binding id>     # resolved ONLY in provider
                                                    # composition root (MA17);
                                                    # never requester input,
                                                    # never a dotpath
    manifestation:                          # agent-facing data (views: MA19)
      summary: <one line>
      when-to-use: <one line>
      action-needed: <text or null>
      limitations: [<short facts>]
    transports:                             # kind: execute only
      - transport: acp | cli-stream | cli-blocking | http-stream
        protocol: <version string or null>
        session: persistent | per-invocation
        events: incremental | final-only
        cancel: supported | unsupported | unknown
        permissions: interactive | default-deny | none
        launch-class: stdio-child | shell-command | http-endpoint
        state: verified | unverified
        evidence: <evidence-record-id>
    ext:
      <provider-id>: { ... }                # namespaced extension; validated
                                            # against provider-owned schema ref
```

## 4. Request / result contract (consumed by MA17 gateway)

Request (requester-suppliable fields ONLY — anything else fails validation):

```yaml
provider-id: <target>
capability-id: <neutral id>
operation: plan | apply | prune | status
payload: { <typed per contract.payload-schema> }
ownership-scope: <opaque string, requester-owned>   # e.g. "coding-lsp/language-server/python"
correlation-id: <opaque string>
```

Result envelope (uniform across capabilities):

```yaml
status: ok | skipped | collision | action-needed | unsupported | blocked | error
changed-paths: [<paths>]            # empty for plan/status
ownership-actions: [{scope, action: adopted|written|updated|removed|skipped}]
collisions: [{name, reason}]
reload-required: <per contract.reload or null>
action-needed: <text or null>
diagnostics: { <redacted> }
correlation-id: <echoed>
```

Semantics: `plan`/`status` cause zero durable mutation; `apply` is
idempotent/atomic; `prune` touches only entries under the request's
`ownership-scope`. A mode declared `not-applicable` returns
`status: unsupported` through the generic path — no handler obligation.
`support: manual|blocked|unsupported|unverified` short-circuits at the
gateway with the canonical result; handlers are never invoked.

## 5. Validation policy

- Unknown core field → `VAL-CAP-001` (fail load, name the field).
- Unknown kind/support/mode/enum value → `VAL-CAP-002`.
- `schema` other than `capability-catalog@1` → `VAL-CAP-003` (no migration
  layer until a second version exists — policy owned by MA19).
- Extension data only under `ext.<provider-id>`; anywhere else fails.
- `support: supported` without an `approved` evidence ref → `VAL-CAP-004`
  (quarantined/pending evidence cannot promote; RV353/RV356).
- Duplicate `capability-id` within a provider → `VAL-CAP-005`.
- Remediation text lives in error-resolutions config, not raised messages.

## 6. Worked fixtures (targets for the Step 1 dialect inventory)

Existing dialects and their mapping targets — the T1 inventory fills one row
per current declaration site:

| Current dialect | Maps to |
| --- | --- |
| `cli_install` (provider YAML) | kind `install` + `probe`; operations from toolchain recipe; binding = provider CLI handler (MA12) |
| `mcp_config` / `language_servers_config` reader/writer/remover refs | kind `managed-mcp` / `managed-lsp`; contract.surface `config-file`; binding = provider adapter; refs leave the declaration and become provider-composition bindings |
| Hindsight matrix rows (`recipe_kind`, steps) | requester-side intent (MA02) + provider kinds `hooks`/`plugin`/`config-mutation`; matrix stops declaring provider mechanics |
| Probe mini-language (`binary:`, `command:` …) | kind `probe`; spec strings unchanged (MA13 registry executes) |
| Model projection (MO02) | kind `model-projection`; payload-schema `model-entry@1` |
| Launch env/override (MO15 seam) | kinds `launch-env` / `launch-override` |
| Execution (MA18 evidence) | kind `execute` + `transports` list; OpenCode declares verified `acp` (protocol 1) AND `cli-stream`; Pi ACP stays `unverified` |

## 7. Canonical status-vocabulary mapping (RV375)

Three status vocabularies exist in the codebase and each has exactly one
role. No component invents a fourth or a private translation:

| Level | Vocabulary | Home | Visibility |
| --- | --- | --- | --- |
| Execution internal | `StepResult` | `foundation/steps/results.py` | never crosses a public boundary (MA13 rule) |
| Recipe lifecycle | `RecipeState` (`recipe_contract.py`) | foundation toolchains | recipe/handler internal |
| Public / gateway | result envelope `status` (§4) | this schema | the ONLY vocabulary requesters, MCP tools, and timelines see |

Canonical mapping (implemented once, in the foundation result normalizer;
MA12's boundary adapter and the MA16 loader consume it, never redefine it):

| RecipeState (source) | Envelope `status` |
| --- | --- |
| satisfied / applied successfully | `ok` |
| already-satisfied probe short-circuit | `ok` (with `ownership-actions: skipped`) |
| skipped / no-automation | `skipped` (+ `action-needed` text when declared) |
| blocked by constraint/support state | `blocked` |
| unsupported operation/mode | `unsupported` |
| adoption conflict | `collision` |
| failure | `error` (canonical code; step detail redacted into diagnostics) |

`StepResult` values never map directly to the envelope — they aggregate into
a RecipeState first. Legacy public payloads (e.g. provider CLI result dicts)
are preserved by boundary adapters that translate FROM the envelope, not
from raw step/recipe internals.

## 8. Canonical capability vocabulary v1 (RV383 — pre-map for Block C)

Pins the capability-ids, payload-schema ids, and ownership-scope conventions
the Block C/D migrations declare. Requester items (MA12/MA02/MA08/MO02)
consume this table; they do not invent parallel ids.

Ownership-scope convention: `<requester-domain>/<family>/<stable-id>` —
opaque to providers, stable across runs, owned by the requester.

| capability-id | kind | payload-schema | typical operations | ownership-scope pattern | consumer item |
| --- | --- | --- | --- | --- | --- |
| `cli` | install | `cli-install@1` | install, verify, uninstall | `providers/cli/<provider-id>` | MA12 |
| `cli-probe` | probe | `probe-spec@1` (MA13 strings) | verify | n/a (read-only; plan/prune not-applicable) | MA12/MA13 |
| `mcp-entries` | managed-mcp | `managed-entry@1` | configure, prune | `<requester>/mcp/<entry-name>` | MA02, surfaces |
| `language-servers` | managed-lsp | `managed-entry@1` | configure, prune | `coding-lsp/language-server/<language-id>` (pinned in MA08) | MA08 |
| `config-fragment` | config-mutation | `config-fragment@1` (container path class + nested keys) | configure, prune | `<requester>/config/<fragment-id>` | MA02, MA06 |
| `hooks` | hooks | `hook-registration@1` | install, configure, uninstall, prune | `<requester>/hooks/<hook-id>` | MA02 |
| `plugin-entries` | plugin | `plugin-entry@1` | configure, prune | `<requester>/plugin/<entry-id>` | MA02 |
| `instructions` | instructions-surface | `instruction-contribution@1` | configure, prune | `<requester>/instructions/<block-id>` | MA02, surfaces |
| `model-projection` | model-projection | `model-entry@1` | configure, prune | `providers/model-source/<source-id>` | MO02 |
| `model-catalog` | catalog-discovery | `catalog-query@1` | (status only; other modes not-applicable) | n/a | MO02/MO07 |
| `launch-env` | launch-env | `env-contribution@1` (secret-ref values only) | configure, prune | `<requester>/launch-env/<contribution-id>` | MO07/MO15 seam |
| `execute` | execute | `execute-request@1` | (status only; transports drive execution via MA17 resolver) | n/a | MA17/MA18 |

Rules:

- **`repair` is not an operation.** MA12's repair action = requester-level
  flow: `status`/probe first, then idempotent `apply` of `install` only when
  the probe fails. No schema addition.
- Read-only capabilities declare `plan`/`prune`/`apply` `not-applicable` as
  fits; the gateway returns canonical `unsupported` for those modes.
- Memory-library-specific desired VALUES (e.g. Hindsight payload content)
  live inside the neutral payloads; the capability-ids and payload schemas
  above contain no memory/Hindsight vocabulary — a second memory library
  reuses them unchanged (MA02 doctrine).
- New capability-ids require adding a row here (schema review), same as new
  kinds.

## 9. Resolved decisions (Gate 0 review, 2026-07-14)

1. **Operation bodies use named recipe refs** (`recipe:<name>`), never inline
   steps. The catalog record is a fact sheet, not a script; step bodies live
   in provider-owned recipe declarations (MA12). The loader validates every
   ref resolves.
2. **`binding` is per capability.** The handler receives the operation/mode
   in the request and dispatches internally; per-operation bindings would
   multiply registry entries without adding information and bloat the MA17
   binding graph. A provider needing split implementations delegates inside
   its handler — invisible to the catalog.
3. **`managed-mcp` and `managed-lsp` stay distinct kinds** — and this is the
   general rule for future managed-config flavors: capabilities are
   legitimately distinct when providers do different things with them,
   regardless of the fact that they happen to materialize in config files.
    A kind names WHAT the capability is, never HOW a provider exposes it — a
    provider may implement the same kind through a completely different
    mechanism, and the kind must not lock in implementation. New specialized
    managed-config kinds join the taxonomy as new kinds via schema review
    (they are core vocabulary, §2), not as subtypes of a merged
    `managed-config` kind. Shared-file coexistence between kinds is handled a
    layer down by the shared merge primitive (MA04), not by the taxonomy.
4. **Vocabularies are closed sets validated at load time** (VAL-CAP-002).
    Python representation is plain strings with single-source frozensets,
    never enum classes — one definition per vocabulary (RV394, 2026-07-14).
