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
    base-url: http://localhost:8000/v1
    default-model: qwen-coder
  claude:
    enabled: false
    install-mode: external-configured
    auth-ref: env:ANTHROPIC_API_KEY
```

Secret rule:
- tracked config stores secret references only
- secrets must not be written into tracked docs
- supported references in v1: `env:NAME`

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
