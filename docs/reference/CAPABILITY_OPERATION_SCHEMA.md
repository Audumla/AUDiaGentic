# Capability-operation schema — DRAFT v0 (MA16 Gate 0 review input)

Status: **DRAFT for review** (T3 design 2026-07-14). This is the record shape
MA16 Step 0 requires review approval on before immutable schema design. It is
NOT yet a runtime contract. Once approved, the strict loader implements exactly
this; changes after approval go through a plan review on MA16.

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
they are core vocabulary, not extension data.

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
      install | configure | verify | uninstall | prune: <step/recipe ref or declared>
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
|---|---|
| `cli_install` (provider YAML) | kind `install` + `probe`; operations from toolchain recipe; binding = provider CLI handler (MA12) |
| `mcp_config` / `language_servers_config` reader/writer/remover refs | kind `managed-mcp` / `managed-lsp`; contract.surface `config-file`; binding = provider adapter; refs leave the declaration and become provider-composition bindings |
| Hindsight matrix rows (`recipe_kind`, steps) | requester-side intent (MA02) + provider kinds `hooks`/`plugin`/`config-mutation`; matrix stops declaring provider mechanics |
| Probe mini-language (`binary:`, `command:` …) | kind `probe`; spec strings unchanged (MA13 registry executes) |
| Model projection (MO02) | kind `model-projection`; payload-schema `model-entry@1` |
| Launch env/override (MO15 seam) | kinds `launch-env` / `launch-override` |
| Execution (MA18 evidence) | kind `execute` + `transports` list; OpenCode declares verified `acp` (protocol 1) AND `cli-stream`; Pi ACP stays `unverified` |

## 7. Open questions for review (decide before freeze)

1. Do `operations` bodies reference MA11 step definitions inline or by named
   recipe id? (Recommendation: named ref; bodies stay in provider files.)
2. Is `binding` per capability or per (capability, operation)?
   (Recommendation: per capability; operations dispatch inside the handler.)
3. Does `managed-mcp`/`managed-lsp` deserve distinct kinds or one
   `managed-config` kind with a `config-kind` field? (Recommendation: keep
   distinct — they gate different requesters and audits.)
