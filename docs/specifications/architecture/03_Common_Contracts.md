# Common Contracts

## Purpose

This document defines the canonical ids, schemas, return types, and contract rules used by all AUDiaGentic components.

## Naming and id rules

- component ids: **kebab-case**
- provider ids: **kebab-case**
- YAML keys: **kebab-case**
- Python packages: **snake_case**
- event and record ids: stable prefixes plus sortable identifiers

### Canonical provider ids
- `local-openai`
- `claude`
- `codex`
- `gemini`
- `qwen`
- `copilot`
- `continue`
- `cline`

### Canonical component ids
- `core-lifecycle`
- `release-audit-ledger`
- `agent-jobs`
- `provider-layer`
- `discord-overlay`
- `optional-server`

## Contract versioning

Every machine-readable contract in v1 must include:
- `contract-version`
- additive-only changes within v1
- explicit migration note if a later version is introduced

## ProjectConfig

```yaml
contract-version: v1
project-id: my-project
project-name: My Project
workflow-profile: lite
tracked-docs-root: docs
runtime-root: .audiagentic/runtime
release-strategy: release-please
```

Validation rules:
- `project-id` must be kebab-case
- `workflow-profile` must be one of `lite`, `standard`, `strict`, or a declared custom profile id
- `tracked-docs-root` must point at `docs`
- `runtime-root` must point at `.audiagentic/runtime`


### Phase 1.2 / 3.2 additive ProjectConfig fields

Prompt-tagged launch and review policy are tracked in `.audiagentic/project.yaml` for MVP.
`.audiagentic/workflows.yaml` is **not** part of the MVP tracked layout and remains deferred.

```yaml
contract-version: v1
project-id: my-project
project-name: My Project
workflow-profile: standard
tracked-docs-root: docs
runtime-root: .audiagentic/runtime
release-strategy: release-please
workflow-overrides:
  review:
    enabled: true
  audit:
    enabled: false
prompt-launch:
  syntax: prefix-token-v1
  allow-adhoc-target: false
  default-review-policy:
    required-reviews: 2
    aggregation-rule: all-pass
    require-distinct-reviewers: true
```

Additive rules:
- `workflow-overrides` stays in `.audiagentic/project.yaml` for MVP.
- `prompt-launch.syntax` is fixed to `prefix-token-v1` in MVP.
- `prompt-launch.allow-adhoc-target` defaults to `false` in the first executable pass when omitted, so `@adhoc` remains opt-in until the core launch path is stable.
- `prompt-launch.default-review-policy.required-reviews` must be an integer >= 1.
- `prompt-launch.default-review-policy.aggregation-rule` supports `all-pass` for MVP and may accept `majority-pass` only as a documented but not yet implemented future extension.
- `prompt-launch.default-review-policy.require-distinct-reviewers` defaults to `true`.

## ComponentConfig

```yaml
contract-version: v1
components:
  core-lifecycle:
    enabled: true
  release-audit-ledger:
    enabled: true
  agent-jobs:
    enabled: true
  provider-layer:
    enabled: true
  discord-overlay:
    enabled: false
  optional-server:
    enabled: false
```

Dependency validation:
- `release-audit-ledger` requires `core-lifecycle`
- `agent-jobs` requires `core-lifecycle`, `release-audit-ledger`, and `provider-layer`
- `discord-overlay` requires `core-lifecycle`; it may consume jobs and release services when enabled
- `optional-server` requires `core-lifecycle`

## ProviderConfig

```yaml
contract-version: v1
providers:
  local-openai:
    enabled: true
    install-mode: external-configured
    access-mode: none
    base-url: http://localhost:8000/v1
    default-model: qwen-coder
  claude:
    enabled: false
    install-mode: external-configured
    access-mode: env
    auth-ref: env:ANTHROPIC_API_KEY
```

Secret rule:
- tracked config stores secret references only
- secrets must not be written into tracked docs
- supported references in v1: `env:NAME`

Access-mode rules:
- `env` requires `auth-ref: env:NAME`
- `cli` uses credentials provided by the provider CLI at runtime
- `none` means no authentication is required (typical for local endpoints)

Provider install-orchestration note:
- Phase 4.7 adds optional install/bootstrap policy fields such as `install-mode`, `install-policy.on-missing`, `install-command`, and `install-check`
- those fields remain opt-in and project-local; they do not change the canonical provider execution contract

### Phase 3.4 job-control note

Job cancellation and stop control are tracked separately from approvals and prompt launch.
Phase 3.4 adds a dedicated job-control record and cancellation request shape, but it does not
change the canonical launch grammar or provider execution contract.

Suggested job-control record:
```json
{
  "contract-version": "v1",
  "job-id": "job_20260329_0001",
  "project-id": "my-project",
  "requested-action": "cancel",
  "requested-by": "operator",
  "requested-at": "2026-03-30T00:10:00Z",
  "reason": "user requested stop",
  "result": "applied",
  "applied-at": "2026-03-30T00:10:02Z"
}
```

Rules:
- job-control records are append-only and project-local
- cancellation must preserve existing stage outputs and job provenance
- `running -> cancelled` is a legal Phase 3.4 control transition when the runner acknowledges the stop
- approval flows remain separate from job-control flows


### Phase 4.3 — Provider prompt-surface and prompt-tag fields

Phase 4.3 adds provider-surface metadata that keeps CLI and VS Code prompt tagging synchronized without changing the canonical prompt-launch contract.

ProviderConfig may include an optional `prompt-surface` block with `enabled`, `tag-syntax`, `first-line-policy`, `cli-mode`, `vscode-mode`, and `settings-profile` fields.

ProviderDescriptor may include additive prompt-tag capability fields:
- `supports-prompt-tag-launch`
- `prompt-tag-syntaxes`
- `prompt-tag-cli-mode`
- `prompt-tag-vscode-mode`
- `requires-surface-settings-sync`

Rules:
- prompt-surface config is additive and must not redefine prompt tag meaning
- if prompt-surface is enabled, the provider must declare the supported surface mode(s) and settings profile name
- provider descriptor prompt-tag fields must match the surface contract and the shared prompt-launch grammar
- prompt-tag surface changes remain separate from model catalog and provider status reporting

### DRAFT — Provider model catalog and selection

Phase 4.1 introduces a provider model catalog contract and model selection rules.
See `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.

### Phase 3.2 dependency note

Prompt-tagged launch consumes provider/model metadata only after the Phase 4.1 contract is frozen. Prompt launch therefore depends on the .1 provider/model contract but does not redefine it.


## ProviderDescriptor

```json
{
  "contract-version": "v1",
  "provider-id": "claude",
  "install-mode": "external-configured",
  "supports-jobs": true,
  "supports-interactive": true,
  "supports-skill-wrapper": true,
  "supports-structured-output": true,
  "supports-server-session": false,
  "supports-baseline-healthcheck": true
}
```



### Provider health check contract

Every provider with `supports-baseline-healthcheck: true` must implement:

```python
healthcheck(project_context) -> HealthCheckResult
```

```json
{
  "contract-version": "v1",
  "provider-id": "claude",
  "status": "healthy",
  "configured": true,
  "latency-ms": 150,
  "error": null,
  "checked-at": "2026-03-29T00:05:00Z"
}
```

Valid `status` values:
- `healthy`
- `unhealthy`
- `unknown`

Configured rule:
- `configured: true` means required provider configuration is present and syntactically valid
- `configured: false` means the provider may be installed but cannot be selected for job execution

Timeout rule:
- MVP health checks must time out within 5 seconds and return `status: "unknown"` or `status: "unhealthy"` with an error string

### Provider selection contract

Provider selection for MVP jobs follows this order:
1. explicit `provider-id` on the job request
2. project-level default provider for the active workflow profile
3. hard fail with validation error if neither is available

Fallback rule:
- MVP does not perform automatic multi-provider failover
- if the selected provider is unhealthy or unconfigured, job creation fails with a blocking validation error
- later phases may add optional fallback policies, but they are out of scope for MVP

### Secret reference policy

MVP supports secret references in the form `env:NAME` only.

Validation rules:
- install/cutover validates only syntax, not secret presence
- runtime validation must fail fast if the referenced environment variable is missing
- runtime failure must emit a clear error naming the missing reference without printing secret values

Future extension:
- additional secret reference types are deferred and remain an explicit post-MVP decision

## JobRecord

```json
{
  "contract-version": "v1",
  "job-id": "job_20260329_0001",
  "packet-id": "pkt-job-implement-001",
  "project-id": "my-project",
  "provider-id": "local-openai",
  "workflow-profile": "lite",
  "state": "running",
  "created-at": "2026-03-29T00:00:00Z",
  "updated-at": "2026-03-29T00:01:00Z",
  "artifacts": [
    {
      "artifact-id": "art_job_001_summary",
      "path": ".audiagentic/runtime/jobs/job_20260329_0001/summary.json",
      "kind": "job-summary"
    }
  ],
  "approvals": [
    {
      "approval-id": "apr_001",
      "kind": "job-continue"
    }
  ]
}
```

Valid `state` values:
- `created`
- `ready`
- `running`
- `awaiting-approval`
- `completed`
- `failed`
- `cancelled`


### Phase 3.1 / 3.2 additive JobRecord fields

The following fields are additive and optional until the .1 and .2 packets are implemented:

- `model-id`
- `model-alias`
- `default-model`
- `launch-source`
- `launch-tag`
- `launch-target`
- `review-policy`
- `review-bundle-id`

Recommended shapes:

```json
{
  "model-id": "gpt-5.4-mini",
  "model-alias": "fast-default",
  "default-model": "gpt-5.4-mini",
  "launch-source": {
    "prompt-id": "prm_20260330_0001",
    "surface": "vscode",
    "session-id": "sess_001"
  },
  "launch-tag": "implement",
  "launch-target": {
    "kind": "packet",
    "packet-id": "PKT-JOB-007"
  },
  "review-policy": {
    "required-reviews": 2,
    "aggregation-rule": "all-pass",
    "require-distinct-reviewers": true
  },
  "review-bundle-id": "rvb_20260330_0001"
}
```

Rules:
- additive fields must not change the base state machine
- `launch-tag` must be one of `plan`, `implement`, `review`, `audit`, `check-in-prep`
- `launch-target.kind` must be one of `packet`, `job`, `artifact`, `adhoc`
- `review-bundle-id` is present only after a review loop has been opened

## ChangeEvent

```json
{
  "contract-version": "v1",
  "event-id": "chg_20260329_0001",
  "timestamp-utc": "2026-03-29T00:01:00Z",
  "project-id": "my-project",
  "source": {
    "kind": "interactive-prompt",
    "provider-id": "claude",
    "surface": "vscode",
    "session-id": "sess_001",
    "job-id": null,
    "packet-id": "pkt-job-implement-001"
  },
  "change-class": "code-fix",
  "files": ["src/core/ledger.py"],
  "diff-stats": {
    "files-changed": 1,
    "insertions": 14,
    "deletions": 2
  },
  "technical-summary": "Added ledger append helper.",
  "user-summary-candidate": "Improved change ledger recording.",
  "status": "unreleased"
}
```

Valid `source.kind` values:
- `interactive-prompt`
- `job-run`
- `workflow-stage`
- `manual-script`
- `release-finalization`

Valid `change-class` values:
- `feature`
- `code-fix`
- `refactor`
- `docs`
- `tests`
- `config`
- `release`
- `audit`
- `workflow`


### Phase 3.2 additive ChangeEvent source fields

Prompt-tagged launch extends `source` with the following optional fields:

- `prompt-id`
- `prompt-tag`
- `target-kind`
- `target-ref`
- `review-id`

Rules:
- prompt metadata is runtime provenance and must not be treated as release-visible by default
- `target-ref` may contain a packet id, job id, artifact id/path token, or adhoc id depending on `target-kind`
- review-derived events may include `review-id` when a structured review report was emitted

## ApprovalRequest

```json
{
  "contract-version": "v1",
  "approval-id": "apr_001",
  "project-id": "my-project",
  "kind": "release-finalize",
  "source-kind": "release-service",
  "source-id": "rel_001",
  "summary": "Approve version bump and Release Please finalization.",
  "state": "pending",
  "requested-at": "2026-03-29T00:02:00Z",
  "expires-at": "2026-03-29T08:02:00Z"
}
```

Valid approval states:
- `pending`
- `approved`
- `rejected`
- `expired`
- `cancelled`

Default expiration policy:
- if omitted by caller, default TTL is 8 hours

## EventEnvelope

```json
{
  "contract-version": "v1",
  "event-id": "evt_001",
  "event-type": "job-state-changed",
  "project-id": "my-project",
  "source-kind": "job-service",
  "source-id": "job_20260329_0001",
  "occurred-at": "2026-03-29T00:03:00Z",
  "payload": {
    "old-state": "ready",
    "new-state": "running"
  }
}
```

Required event types in MVP:
- `lifecycle-state-changed`
- `job-state-changed`
- `approval-requested`
- `approval-resolved`
- `release-state-changed`
- `migration-item-skipped`

## ReleaseStrategy contract

A release strategy implementation must provide these typed results:

- `collect_inputs(project-root) -> ReleaseInputs`
- `determine_version(inputs) -> VersionDecision`
- `prepare_workspace_changes(inputs, version) -> WorkspaceChangeSet`
- `prepare_release_outputs(inputs, version) -> ReleaseOutputs`
- `finalize_release(inputs, version) -> ReleaseResult`

### ReleaseInputs
```json
{
  "contract-version": "v1",
  "project-id": "my-project",
  "project-root": "/repo",
  "current-release-ledger-path": "docs/releases/CURRENT_RELEASE_LEDGER.ndjson",
  "current-release-summary-path": "docs/releases/CURRENT_RELEASE.md"
}
```

### VersionDecision
```json
{
  "contract-version": "v1",
  "version": "1.2.0",
  "tag": "v1.2.0",
  "rationale": "feature + code-fix changes since previous release"
}
```

### WorkspaceChangeSet
```json
{
  "contract-version": "v1",
  "files": [
    {"path": "docs/releases/CHANGELOG.md", "operation": "update"},
    {"path": "docs/releases/RELEASE_NOTES.md", "operation": "update"}
  ]
}
```

### ReleaseOutputs
```json
{
  "contract-version": "v1",
  "release-record-id": "rel_20260329_001",
  "release-version": "1.2.0",
  "release-tag": "v1.2.0",
  "files-to-write": [
    "docs/releases/CHANGELOG.md",
    "docs/releases/RELEASE_NOTES.md",
    "docs/releases/VERSION_HISTORY.md"
  ]
}
```

### ReleaseResult
```json
{
  "contract-version": "v1",
  "release-record-id": "rel_20260329_001",
  "status": "completed",
  "release-version": "1.2.0",
  "release-tag": "v1.2.0"
}
```

## Lifecycle module contract

- `plan(context) -> LifecyclePlan`
- `apply(context) -> LifecycleResult`
- `validate(context) -> ValidationReport`

### LifecyclePlan
```json
{
  "contract-version": "v1",
  "action": "legacy-cutover",
  "project-root": "/repo",
  "warnings": ["legacy workflow will be renamed"],
  "migrated-items": [],
  "deleted-items": []
}
```

### LifecycleResult
```json
{
  "contract-version": "v1",
  "action": "legacy-cutover",
  "status": "completed",
  "warnings": ["manual workflow migration still required"],
  "applied-items": []
}
```

### ValidationReport
```json
{
  "contract-version": "v1",
  "action": "legacy-cutover",
  "status": "valid",
  "checks": [
    {"name": "project-layout", "result": "pass"},
    {"name": "baseline-workflow", "result": "pass"}
  ]
}
```

## Stability rule

Breaking contract changes require:
- new contract version
- migration note
- update logic
- schema fixture updates


## Release strategy return objects

### ReleaseInputs

```json
{
  "contract-version": "v1",
  "project-id": "my-project",
  "release-strategy": "release-please",
  "current-release-ledger-path": "docs/releases/CURRENT_RELEASE_LEDGER.ndjson",
  "current-release-summary-path": "docs/releases/CURRENT_RELEASE.md",
  "tracked-release-docs-root": "docs/releases"
}
```

### VersionDecision

```json
{
  "contract-version": "v1",
  "strategy-id": "release-please",
  "version": "1.2.0",
  "version-kind": "semver",
  "reason": "feature + fix entries detected in current release ledger",
  "blocking-errors": []
}
```

### WorkspaceChangeSet

```json
{
  "contract-version": "v1",
  "project-id": "my-project",
  "changes": [
    {
      "path": "docs/releases/CHANGELOG.md",
      "operation": "update"
    }
  ]
}
```

### ReleaseOutputs

```json
{
  "contract-version": "v1",
  "release-documents": [
    "docs/releases/CHANGELOG.md",
    "docs/releases/RELEASE_NOTES.md",
    "docs/releases/CHECKIN.md",
    "docs/releases/AUDIT_SUMMARY.md"
  ],
  "version-history-updated": true,
  "current-release-reset": true
}
```

### ReleaseResult

```json
{
  "contract-version": "v1",
  "status": "success",
  "version": "1.2.0",
  "warnings": [],
  "checkpoint-dir": ".audiagentic/runtime/release/checkpoints"
}
```

## Lifecycle return objects

### LifecyclePlan

```json
{
  "contract-version": "v1",
  "mode": "plan",
  "state-classification": "legacy-only",
  "operations": [
    "scan-project",
    "migrate-docs",
    "convert-history",
    "install-baseline-release-please",
    "remove-legacy-markers"
  ],
  "warnings": [
    "legacy release workflow will be renamed and requires manual migration review"
  ],
  "blocking-errors": []
}
```

### LifecycleResult

```json
{
  "contract-version": "v1",
  "mode": "apply",
  "status": "success",
  "completed-operations": [
    "create-.audiagentic",
    "write-project-config",
    "install-workflow"
  ],
  "warnings": [],
  "checkpoint-dir": ".audiagentic/runtime/lifecycle/checkpoints"
}
```

### ValidationReport

```json
{
  "contract-version": "v1",
  "status": "pass",
  "checks": [
    {
      "check-id": "docs-structure",
      "result": "pass",
      "details": "tracked docs layout matches expected structure"
    }
  ],
  "warnings": []
}
```

## Contract glossary note

See `19_Glossary.md` for canonical meanings of:
- project root
- tracked docs
- packet
- release artifact
- job artifact


## InstalledStateManifest

```json
{
  "contract-version": "v1",
  "installation-kind": "fresh|cutover|update",
  "current-version": "0.1.0",
  "previous-version": null,
  "components": {
    "core-lifecycle": "installed",
    "release-audit-ledger": "installed"
  },
  "providers": {
    "local-openai": "configured"
  },
  "last-lifecycle-action": "fresh-install",
  "updated-at": "2026-03-29T00:00:00Z"
}
```

Validation rules:
- file path is `.audiagentic/installed.json`
- file is written atomically using temp-file + rename
- corrupted manifest blocks destructive lifecycle apply until replaced or repaired

## HealthCheckResult

```json
{
  "contract-version": "v1",
  "provider-id": "local-openai",
  "status": "healthy",
  "latency-ms": 120,
  "error": null,
  "checked-at": "2026-03-29T00:00:00Z"
}
```

Rules:
- status enum: `healthy`, `unhealthy`, `unknown`
- default timeout: 30 seconds
- health checks must not mutate project state
- `unknown` is valid when configuration exists but the check cannot complete deterministically in MVP

## ErrorEnvelope

```json
{
  "contract-version": "v1",
  "ok": false,
  "error-code": "LFC-VALIDATION-001",
  "error-kind": "validation",
  "message": "project config failed validation",
  "details": {
    "field": "workflow-profile"
  }
}
```

Rules:
- every CLI/script with `--json` support must emit `ErrorEnvelope` on failure
- error kinds in MVP: `validation`, `business-rule`, `io`, `external`, `internal`
- code ranges:
  - `FND-*` foundation/contracts
  - `LFC-*` lifecycle
  - `RLS-*` release
  - `JOB-*` jobs
  - `PRV-*` providers
  - `DSC-*` Discord
  - `MIG-*` migration

## EventPublisher contract

```python
class EventPublisher:
    def publish(self, event: dict) -> None: ...
    def publish_many(self, events: list[dict]) -> None: ...
```

Rules:
- MVP delivery guarantee is **best-effort append to the project-local event log**
- subscribers are out of scope for the core contract; overlays may tail/filter the event log
- event log path is under `.audiagentic/runtime/logs/events.ndjson`

## StageExecutionContract

```json
{
  "contract-version": "v1",
  "stage-id": "implement",
  "input": {
    "job-record-id": "job-123",
    "packet-id": "PKT-JOB-003",
    "previous-stage-output": null
  },
  "output": {
    "stage-result": "success",
    "artifacts": [],
    "next-stage-recommendation": "continue"
  }
}
```

Rules:
- stage result enum: `success`, `failure`, `skipped`
- next-stage recommendation enum: `continue`, `stop`, `escalate`
- profiles may only mark non-core stages optional in MVP



## PromptLaunchRequest

Phase 3.2 introduces a normalized prompt launch envelope. CLI, VS Code, and other interactive surfaces must normalize into this shape before the jobs layer consumes the request.

```json
{
  "contract-version": "v1",
  "prompt-id": "prm_20260330_0001",
  "source": {
    "kind": "interactive-prompt",
    "surface": "vscode",
    "provider-id": "codex",
    "session-id": "sess_001",
    "model-id": "gpt-5.4-mini",
    "model-alias": "fast-default"
  },
  "tag": "implement",
  "target": {
    "kind": "packet",
    "packet-id": "PKT-JOB-007"
  },
  "workflow-profile": "standard",
  "existing-job-id": null,
  "prompt-body": "Continue the packet implementation using the approved spec updates.",
  "review-policy": {
    "required-reviews": 2,
    "aggregation-rule": "all-pass",
    "require-distinct-reviewers": true
  },
  "commit-scope": "proposal"
}
```

Required rules:
- the parser consumes `prefix-token-v1` syntax only in MVP
- the first non-empty line may use a short action alias such as `@p`, `@i`, `@r`, `@a`, or `@c`
- the first non-empty line may also use a provider shorthand such as `@codex` or `@claude`; in that case the launcher defaults to the provider's normal action path and model selection rules
- when the target is omitted, the launcher may infer a default runtime subject and still assign a generated job id
- supported target kinds are `packet`, `job`, `artifact`, and `adhoc`
- `existing-job-id` resumes a job only when the target and stage transition are compatible
- `commit-scope` is advisory metadata for the launcher and does not bypass approval policy
- provider-owned prompt-trigger behavior is defined separately in Phase 4.6 and must feed this contract rather than replacing it

## ReviewReport

```json
{
  "contract-version": "v1",
  "review-id": "rvr_20260330_0001",
  "subject": {
    "kind": "artifact",
    "job-id": "job_20260330_0007",
    "artifact-id": "art_job_0007_impl_plan"
  },
  "reviewer": {
    "provider-id": "claude",
    "surface": "cli",
    "session-id": "sess_044",
    "prompt-id": "prm_20260330_0044",
    "reviewer-key": "claude:cli:sess_044"
  },
  "criteria": [
    "matches packet scope",
    "preserves existing contracts",
    "covers tests and recovery"
  ],
  "findings": [
    {
      "finding-id": "fdg_001",
      "severity": "major",
      "blocking": true,
      "summary": "Schema fixture coverage is incomplete.",
      "suggested-fix": "Add valid and invalid fixtures for the new launch envelope."
    }
  ],
  "recommendation": "rework",
  "follow-up-actions": [
    "Add missing fixtures",
    "rerun schema validation"
  ],
  "created-at": "2026-03-30T03:00:00Z"
}
```

Rules:
- `recommendation` must be one of `pass`, `pass-with-notes`, `rework`, or `block`
- each finding must explicitly state whether it is blocking
- review reports are runtime artifacts unless a later stage intentionally summarizes them into tracked docs

## ReviewBundle

```json
{
  "contract-version": "v1",
  "review-bundle-id": "rvb_20260330_0001",
  "subject": {
    "kind": "artifact",
    "job-id": "job_20260330_0007",
    "artifact-id": "art_job_0007_impl_plan"
  },
  "required-reviews": 2,
  "aggregation-rule": "all-pass",
  "require-distinct-reviewers": true,
  "reports": [
    {
      "review-id": "rvr_20260330_0001",
      "reviewer-key": "claude:cli:sess_044",
      "recommendation": "pass"
    },
    {
      "review-id": "rvr_20260330_0002",
      "reviewer-key": "codex:vscode:sess_015",
      "recommendation": "rework"
    }
  ],
  "decision": "rework",
  "status": "complete",
  "updated-at": "2026-03-30T03:15:00Z"
}
```

Rules:
- `required-reviews` defaults from `ProjectConfig.prompt-launch.default-review-policy`
- `aggregation-rule: all-pass` means any `rework` or `block` prevents an approved decision
- `require-distinct-reviewers: true` means duplicate `reviewer-key` values do not count twice
- `decision` must be one of `pending`, `approved`, `rework`, or `blocked`
