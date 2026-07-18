# Gateway job execution context — envelope and manifest schema (SH02 draft)

Status: **draft v0.4** — 2026-07-17 (RV565 + RV566 + RV567 sponsor reviews
applied). This document defines the **shell** of the contract. Later items
that need more fields (SH06, SH07, RO roles, …) define and implement them
then, via a schema version bump — nothing speculative lands here.

Design rule (RV566): the envelope is **today's working submit contract made
explicit and versioned** — the agent profile remains the source of provider,
model, and execution parameters; component profiles remain the component
selection mechanism; provider configuration remains the owner of MCPs, env
shaping, and vendor keys. SH02 adds only what a shared gateway strictly
needs: a schema version, explicit project context, idempotency/correlation
identity, and the frozen resolution record. Future concerns (roles,
multi-root workspaces) arrive through schema version bumps when their owning
items land — that is what the version field is for.
Owner: SH02. Consumes the approved shared-gateway v2 design
([gateway-shared-service.md](gateway-shared-service.md), esp. §2 principle 2
and §2.1). Identity rules here are consumed by SH06 (worker reuse keys) and
SH07 (idempotency/attempt identity) per RV561.

## 1. Concepts

Two artifacts, strictly separated:

- **Submission envelope** — what a client *asks for*. Versioned, validated,
  may contain selections by id (profile ids, component profile name). Sent
  over MCP, CLI, event transport, or the future service transport.
- **Resolved execution manifest** — what the gateway *decided*. Immutable
  once admitted; every field is either copied from the envelope or resolved
  by the gateway. Workers receive the manifest, never the
  envelope. Records persist the manifest (redacted), never raw secrets or
  prompt text.

Resolution happens once, at admission, in the control plane. Nothing in the
manifest may depend on the submitting process's cwd, environment, or loaded
component profile (SH01 inventory rows 12/15; RV530: component profile is
frozen at request time).

Lifecycle (RV565 — deliberately simple):

```text
Submission envelope
        ↓
Admission and resolution
        ↓
Immutable execution manifest
        ↓
One or more technical attempts using that same manifest
```

A technical retry restarts the same execution context after a worker crash or
transient transport failure. **All attempts for a request use the same
immutable manifest.** A change to agent profile, provider, model, project
context, or resolved capabilities requires a new request and a new manifest.
Retries are operational retries, never policy-driven reselection. SH07's
model is therefore:

```text
request_id
  └── manifest_id
        ├── attempt 1
        ├── attempt 2
        └── attempt 3
```

## 2. Submission envelope (schema `audiagentic.gateway.envelope/1`)

This is the existing `submit_llm_request` surface plus four additive fields
(`schema_version`, `idempotency_key`, `correlation_id`, `source` — `source`
already exists on submit) and an explicit `component_profile` (today a
process-global flag/env var; per-request here because the shared gateway
serves many projects, RV530). `fallback_profile_ids` is deliberately absent
(RV565).

```yaml
envelope:
  schema_version: 1                    # integer; negotiation in §6

  # --- identity & idempotency (additive) ---
  idempotency_key: string | null       # client-scoped; §5.2 fallback if null
  correlation_id: string | null        # joins EventEnvelope correlation
  source: string | null                # e.g. "mcp", "event:agents.llm.gateway.requested"

  # --- project context (required) ---
  project_root: path                   # canonicalized per §4; also the execution cwd

  # --- selection (existing agent-profile doctrine precedence) ---
  agent_profile_id: string | null      # precedence 1
  provider_id: string | null           # precedence 2, only with model_id
  model_id: string | null
  component_profile: string | null     # name; resolved server-side (RV530)
                                       # null = base components

  # --- execution shaping (existing submit fields) ---
  mode: async | blocking
  timeout_seconds: number | null
  session:                             # AS04/AS08 session semantics, unchanged
    session_id: string | null
    keep_alive: bool
    idle_timeout_seconds: number | null
    max_lifetime_seconds: number | null

  # --- payload (existing submit fields) ---
  prompt_body: string | null           # never persisted raw; digest only (§5.2)
  metadata: {string: json} | null      # small, redacted, non-secret
```

Deliberately **not** in the envelope (RV566 — these concerns already have
owners in the working system):

| Not a field | Owner today |
| --- | --- |
| MCP servers / tools | provider configuration via managed-config families (RV565) |
| Env shaping, vendor keys, secrets | provider config capabilities (e.g. vendor-key injection), materialized at worker launch |
| Execution params (retry-count, max-concurrency, stream-controls) | agent profile `params` |
| Component/feature selection | component profile overlay directory |
| Roles / capability intent | future RO01–RO04; added via schema version bump |
| Working directory | `project_root` is the execution cwd, as today |

Validation rejects: relative or non-canonicalizable `project_root`; raw
credential material in any field (canary patterns); `provider_id` without
`model_id`; unknown `schema_version` (§6).

## 3. Resolved execution manifest (schema `audiagentic.gateway.manifest/1`)

```yaml
manifest:
  schema_version: 1
  manifest_id: string                  # ULID, gateway-assigned
  request_id: string                   # admitted request identity (SH07)
  resolved_at: timestamp

  # --- identity-bearing resolved context (fingerprinted, §5.1) ---
  identity:
    project_root: canonical-path       # also the execution cwd

    agent_profile_id: string           # the profile that won resolution
    provider_id: string                # from the profile (or explicit pair)
    model_id: string
    provider_isolation_tier: full-isolation | partial-isolation | no-isolation
                                       # from MA20 descriptor fact, mandatory
    component_profile: string | ""     # "" = base components, frozen here

    agent_runtime_digest: sha256       # §3.1 — frozen resolved agent runtime
                                       # (covers profile params, attached MCPs,
                                       # tools, hooks, instructions, env/vendor
                                       # injection, sandbox, model settings)

  context_fingerprint: sha256          # over canonical JSON of `identity` (§5.1)

  # --- non-identity resolved fields ---
  session: { ... }                     # as admitted; session semantics stay AS-owned
  mode: async | blocking
  timeout_seconds: number | null
  prompt_digest: sha256                # §5.2; raw prompt never persisted
```

That is the whole manifest (RV567). Deliberately absent until an owning item
proves the need and adds them via a version bump: stored runtime-revision
diagnostics, per-field resolution provenance, protocol-version stamps
(SH04's handshake owns negotiation), and integrity/tamper machinery (SH07
owns the admission record it would protect).

Immutability (RV565): after admission the manifest never changes, and **all
attempts for a request use the same immutable manifest**. A change to agent
profile, provider, model, project context, or resolved capabilities requires
a new request and a new manifest. SH07 attempt identity (`worker_id`,
`attempt_epoch`) lives on the attempt record, never in the manifest.

### 3.1 Agent runtime digest

The gateway does not independently choose or assemble MCP sets, tools,
instructions, hooks, sandbox settings, or model parameters — the agent
profile and provider configuration (AUDiaGentic-managed) own those decisions,
and roles will later enhance that baseline. SH02 only guarantees the resolved
configuration is **frozen and identity-bearing**:

```text
agent_runtime_digest = sha256(
    agent_profile_revision      # content hash of the resolved agent profile
  + provider_config_revision    # content hash of the resolved provider config
                                # (includes its attached managed MCP entries)
  + component_profile_revision  # content hash of the resolved component overlay
)
```

Only the combined digest is stored or fingerprinted; the three input
revisions are computed at admission and discarded (RV567 — an item that
needs them for diagnostics adds them then). A
change to any managed configuration that would alter the effective agent
runtime therefore changes the digest — a pooled worker can never be reused
with a stale runtime — without SH02 understanding the configuration contents
individually.

## 4. Canonical path rules

One rule set for both fingerprinting and enforcement, applied at admission:

1. Resolve to absolute; resolve symlinks/junctions (`realpath` semantics).
2. Windows: casefold the drive letter and path for the **fingerprint form**
   only; preserve display form separately. Convert to forward slashes in the
   fingerprint form. Reject UNC paths in v1 (explicit unsupported error).
3. POSIX: no casefolding; NFC-normalize unicode.
4. `project_root` is the only root in v1 and is the execution cwd; additional
   workspace roots are a future schema version if an owning item ever needs
   them (RV566).

Round-trip tests must prove: the same directory submitted in any spelling
(case, separators, trailing slash, symlink) yields one identical fingerprint
on the same machine; two different directories never collide.

## 5. Identity derivation

### 5.1 Context fingerprint

`context_fingerprint = sha256(canonical_json(manifest.identity))` where
canonical_json sorts keys, uses fingerprint-form paths, and sorted arrays.
Included: exactly the `identity` block. Excluded by design: prompt, session
id, correlation/idempotency ids, timestamps, timeout/mode, metadata.

Consumers (RV561 — no parallel identity concepts):

- **SH06**: worker reuse key = `context_fingerprint` (+ worker-policy salt).
  Two jobs may share a pooled worker only on equal fingerprints.
- **SH07**: recovery and epoch checks compare attempt records against the
  manifest's fingerprint to detect context drift after restart.

### 5.2 Idempotency key

- Client-supplied `idempotency_key` wins; scope is
  `(project_root fingerprint-form, idempotency_key)`.
- If absent, the gateway derives
  `sha256(context_fingerprint + prompt_digest + session.session_id)` —
  deterministic resubmission of the identical request returns the original
  `request_id` (SH07 idempotent admission; SH09 maps event delivery identity
  onto this same key).
- `prompt_digest = sha256(utf8(prompt_body))`; the raw prompt is used for
  dispatch only and never persisted in gateway records.

## 6. Versioning and negotiation

- Envelope and manifest carry independent integer `schema_version`s.
- The gateway advertises `min/max` accepted envelope versions in its health
  handshake (SH04) and in the MCP tool description.
- Unknown/too-old version → stable canonical error `VAL-AGW-069` with the
  supported range; no silent coercion.
- Minor evolution is additive-only (new optional fields). A field that
  changes meaning requires a version bump and an explicit translation shim
  in the gateway (never in adapters), deleted when the old version's
  obligation window closes (SH11 discipline).
- Persisted manifests are readable forever: manifest readers must handle all
  historical manifest versions or refuse with a named migration error.

## 7. Environment and secret handling (RV566)

Environment shaping, vendor keys, and secrets are **provider-configuration
concerns**, not job-request fields. They are materialized at worker launch by
SH06 from the managed provider configuration (e.g. the vendor-key-injection
capability), and any change to that configuration changes
`provider_config_revision` and therefore the fingerprint.

The envelope and manifest carry no environment or secret fields. Two rules
still bind the gateway:

- The *submitting* client's process environment is never inherited by the
  worker (SH01 row 15); everything the job's runtime needs comes from
  resolved managed configuration.
- Redaction canaries in tests assert no secret value round-trips through
  envelope→manifest→record→event, regardless of where it originated.

## 8. Test obligations (SH02 exit gate)

1. Round-trip schema tests for envelope and manifest on Windows and POSIX
   path forms (§4 cases).
2. Determinism: identical intent → identical fingerprint and derived
   idempotency key; distinct roots/profiles/MCP sets → distinct fingerprints.
3. Cross-project bleed: two projects with conflicting component profiles and
   provider/runtime configurations produce manifests whose identity blocks
   (including `agent_runtime_digest`) share no resolved values sourced from
   process state.
4. Redaction: secret canaries absent from persisted manifests, records, and
   events; prompt absent, digest present.
5. Version negotiation: old client receives `VAL-AGW-069` with range.

(Manifest integrity/tamper testing moves to SH07 with the admission record it
protects — RV567.)

## 9. Design decisions and open points

Decided (RV565 sponsor review, 2026-07-17):

- **No fallback reselection.** `fallback_profile_ids` is absent from the
  envelope and has been removed from the in-process gateway. Retries are
  operational, never policy-driven reselection; a caller wanting reselection
  submits a new request.
- **MCPs are not first-class gateway selections.** Removed `mcp_set_digest`
  and `mcp_servers` from the manifest; the frozen `agent_runtime_digest`
  (§3.1) covers attached MCPs and every other runtime decision owned by the
  agent profile / provider configuration. Roles will later dictate MCP
  launch sets by enhancing the profile baseline — not by adding gateway
  fields.
- **Envelope anchors on the working base (RV566).** Removed invented fields:
  `enabled_features`, `role_intent`, `startup_cwd`, `workspace_roots`,
  `env_allowlist`, `secret_refs`, and the manifest's `role_resolution_ref`.
  The agent profile is the source of provider/model/execution params;
  component profiles select components; provider config owns env/vendor
  keys/MCPs (all frozen via `agent_runtime_digest`). `project_root` is the
  execution cwd. Roles and any multi-root workspace support enter through a
  schema version bump when RO items (or a real requirement) land.
- **Shell only (RV567).** Manifest stripped to identity + fingerprint +
  execution basics. Removed: `runtime_revisions`, the per-field `provenance`
  array, `gateway_protocol_version`, and integrity/tamper machinery. Later
  items define the fields they need when they need them.

- **Runtime digest recipe (approved 2026-07-17):** hash the *resolved
  objects*, never raw file bytes — (1) `resolve_profile()` output
  (profile_id, provider_id, model_id, params), (2) the provider's
  managed-config state for that provider, (3) the component-profile overlay
  descriptors — each as canonical JSON (sorted keys), concatenated, sha256.
  Real config changes move the digest; cosmetic file noise does not.

Still open (resolve before implementation):

1. **UNC/network project roots** — v1 rejects; revisit only on demand.
2. **Blocking mode over the service transport** — envelope keeps `mode`, but
   SH04 may translate blocking waits into poll/wait at the client; manifest
   treats mode as non-identity either way.
