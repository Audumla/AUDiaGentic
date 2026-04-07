# Phase 4 Remaining Work Execution Guide

This guide is the execution companion for all remaining Phase 4 work.

Use it with:
- `docs/implementation/31_Build_Status_and_Work_Registry.md`
- the packet files under `docs/implementation/packets/phase-4/`
- the phase specs `40`, `41`, `45`, `46`, `47`, and `48`

If a junior developer is picking up Phase 4 work, this is the document that should answer:
- where the code changes belong
- which config files control the behavior
- what runtime artifacts should exist after the work
- which tests must be added or updated
- which docs/specs must stay in sync

## Shared rules for all remaining Phase 4 work

### Canonical config locations

- project defaults: `.audiagentic/project.yaml`
- provider defaults and provider execution policy: `.audiagentic/providers.yaml`
- prompt grammar and provider skill surfaces: `.audiagentic/prompt-syntax.yaml`
- canonical provider-function source: `.audiagentic/skills/<tag>/skill.md`

### Canonical runtime artifacts

Unless a packet explicitly says otherwise, provider runtime artifacts live under:

```text
.audiagentic/runtime/jobs/<job-id>/
```

Common artifacts used in the remaining Phase 4 work:
- `launch-request.json`
- `stdout.log`
- `stderr.log`
- `events.ndjson`
- `input.ndjson`
- `input-events.ndjson`
- `completions/completion.<provider-id>.json`
- existing review artifacts such as `review-report.*.json` and `review-bundle.json`

### Canonical schema locations

Runtime schemas no longer live under `docs/schemas/`. Use:

```text
src/audiagentic/contracts/schemas/
```

Always resolve schemas through:
- `src/audiagentic/contracts/schema_registry.py`

### Test placement rules

- shared runtime tests: `tests/unit/streaming/`
- prompt launch and bridge tests: `tests/integration/jobs/`
- provider adapter tests: `tests/integration/providers/`
- provider-surface generation tests: existing unit/integration coverage around regeneration and baseline sync

### Required documentation sync

When a Phase 4 packet changes behavior, update the packet doc and the matching provider/phase docs:
- provider prompt-trigger runbooks under `docs/implementation/providers/`
- phase docs under `docs/implementation/`
- shared contracts in `docs/specifications/architecture/03_Common_Contracts.md`
- provider-specific specs under `docs/specifications/architecture/providers/`

## Execution order

### Review and closeout first

These packets are implementation-complete enough that the remaining work is review, reconciliation, or smoke-test closeout:
- `PKT-PRV-015`
- `PKT-PRV-016`
- `PKT-PRV-023`
- `PKT-PRV-024`
- `PKT-PRV-032`
- `PKT-PRV-034`
- `PKT-PRV-035`
- `PKT-PRV-037`
- `PKT-PRV-038`
- `PKT-PRV-048`
- `PKT-PRV-051`
- `PKT-PRV-062`
- `PKT-PRV-063`
- `PKT-PRV-064`
- `PKT-PRV-065`
- `PKT-PRV-066`
- `PKT-PRV-067`

### Active build path next

Build in this order:
1. `PKT-PRV-056`
2. `PKT-PRV-049`
3. `PKT-PRV-050`
4. `PKT-PRV-072`
5. `PKT-PRV-073`
6. `PKT-PRV-057`
7. `PKT-PRV-058`
8. `PKT-PRV-068`
9. `PKT-PRV-069`
10. `PKT-PRV-071`
11. `PKT-PRV-074`
12. `PKT-PRV-075`
13. `PKT-PRV-076`
14. `PKT-PRV-077`
15. `PKT-PRV-078`

### Deferred line

Do not start these without an explicit phase unlock:
- `PKT-PRV-039` through `PKT-PRV-047`
- `PKT-PRV-019`, `PKT-PRV-027`, `PKT-PRV-036`

## Packet-by-packet execution notes

### Review and closeout packets

#### PKT-PRV-015 / PKT-PRV-016 / PKT-PRV-023 / PKT-PRV-024
- Purpose: documentation reconciliation only; later provider work already covers the practical path.
- Files: packet docs, provider runbooks, provider specs, and any stale references in build/assessment docs.
- Config: no new config.
- Artifacts: none.
- Tests: only add/adjust smoke tests if docs claim they exist and they do not.
- Done when: stale wording is removed and the docs point to the current bridge/surface path.

#### PKT-PRV-032 / PKT-PRV-034 / PKT-PRV-035 / PKT-PRV-037 / PKT-PRV-038 / PKT-PRV-067
- Purpose: prompt-trigger launch closeout for provider surfaces that are already largely scaffolded.
- Files:
  - bridge tools under `tools/`
  - provider prompt-trigger runbooks under `docs/implementation/providers/`
  - provider specs under `docs/specifications/architecture/providers/`
  - provider surface files already generated under `.agents/skills/`, `.gemini/commands/`, `.clinerules/skills/`, `.github/prompts/`, `.github/agents/`, `.opencode/skills/`
- Config:
  - `.audiagentic/prompt-syntax.yaml`
  - `.audiagentic/providers.yaml` prompt-surface blocks
- Artifacts:
  - `launch-request.json`
  - job creation/resume artifacts under `.audiagentic/runtime/jobs/<job-id>/`
- Tests:
  - add or finish integration smoke tests in `tests/integration/jobs/` or `tests/integration/providers/`
  - prove `@plan` and `@review` at minimum for the provider-specific bridge/surface
- Done when:
  - provider surface invokes the shared bridge
  - provenance survives normalization
  - smoke tests pass
  - docs no longer describe a fallback path as if it were the primary path unless that is intentional

#### PKT-PRV-048 / PKT-PRV-051 / PKT-PRV-062 / PKT-PRV-063 / PKT-PRV-064 / PKT-PRV-065 / PKT-PRV-066
- Purpose: review and verify already-implemented shared/runtime or opencode work.
- Files: existing implementation files plus packet docs.
- Config: verify tracked config aligns with the implementation; no new config unless a review finds drift.
- Tests:
  - make sure the relevant unit/integration suites pass
  - add only missing regression coverage discovered in review
- Done when: review findings are resolved and registry can move from `READY_FOR_REVIEW` to `VERIFIED`.

### Active build packets

#### PKT-PRV-056 — shared structured completion
- Code files:
  - `src/audiagentic/streaming/completion.py`
  - `src/audiagentic/streaming/__init__.py`
  - `src/audiagentic/contracts/schemas/provider-completion.schema.json`
- Config:
  - no provider-specific execution flags here
  - use current launch/runtime provenance already present in the launch request
- Artifacts:
  - `completions/completion.<provider-id>.json`
- Tests:
  - `tests/unit/streaming/test_completion.py`
  - add explicit tests for `persist_completion()`, path helpers, invalid persistence rejection, and untested schema fields
- Spec hooks:
  - `docs/specifications/architecture/36_Provider_Structured_Completion_and_Result_Normalization.md`
  - `docs/implementation/47_Phase_4_11_Provider_Structured_Completion_and_Result_Normalization.md`
- Junior note: do not wire provider-specific parsing into this packet; keep it shared and provider-neutral.

#### PKT-PRV-049 — Codex stream extractor
- Code files:
  - `src/audiagentic/execution/providers/adapters/codex.py`
  - any Codex bridge/tests under `tools/` and `tests/integration/providers/`
- Config:
  - consume `stream-controls` from launch/runtime packet context
  - do not invent Codex-only stream config in the adapter
- Artifacts:
  - `stdout.log`, `stderr.log`, `events.ndjson`
- Tests:
  - add Codex extractor tests proving milestone lines become canonical events
  - verify streaming-disabled path still works
- Spec hooks:
  - phase docs `34` and `45`
- Junior note: do not modify the shared sink harness in this packet.

#### PKT-PRV-050 — Cline stream extractor
- Code files:
  - `src/audiagentic/execution/providers/adapters/cline.py`
- Config and artifacts: same pattern as `PKT-PRV-049`
- Tests:
  - parse native Cline NDJSON into canonical events
  - prove concurrent stdout/stderr still yields valid `events.ndjson`
- Junior note: keep provider parsing in `cline.py`, not the shared harness.

#### PKT-PRV-072 — Gemini sink-harness uplift
- Code files:
  - `src/audiagentic/execution/providers/adapters/gemini.py`
- Config:
  - use `stream-controls` from packet context
  - keep command behavior provider-config-driven where already documented
- Artifacts:
  - same standard streaming artifacts under the job runtime directory
- Tests:
  - add integration coverage that Gemini runs now produce runtime stream artifacts
- Spec hooks:
  - phase docs `45` and provider doc `04_Gemini.md`
- Junior note: this packet owns Gemini participation in the shared sink harness, not native prompt-trigger behavior.

#### PKT-PRV-073 — Qwen sink-harness uplift
- Code files:
  - `src/audiagentic/execution/providers/adapters/qwen.py`
- Config/artifacts/tests: same shape as `PKT-PRV-072`
- Junior note: keep backend/bridge semantics unchanged; only uplift runtime capture ownership.

#### PKT-PRV-057 / PKT-PRV-058 / PKT-PRV-068 / PKT-PRV-069 / PKT-PRV-071
- Shared goal: provider-specific structured-completion integration on top of `PKT-PRV-056`
- Code files by provider:
  - Codex: `src/audiagentic/execution/providers/adapters/codex.py`
  - Cline: `src/audiagentic/execution/providers/adapters/cline.py`
  - Claude: `src/audiagentic/execution/providers/adapters/claude.py`
  - opencode: `src/audiagentic/execution/providers/adapters/opencode.py`
  - Gemini: `src/audiagentic/execution/providers/adapters/gemini.py`
- Config:
  - launch/runtime provenance already comes from the prompt-launch request
  - prompt/provider-surface shaping changes must continue to flow through `.audiagentic/skills/` + `.audiagentic/prompt-syntax.yaml` + regenerated provider surfaces
- Artifacts:
  - `completions/completion.<provider-id>.json`
  - existing review artifacts must remain intact
- Tests:
  - one provider integration test per provider proving direct result vs synthetic fallback behavior
  - prove review/report paths can consume the persisted completion artifact
- Junior note: do not add provider-private final-result schemas; every provider must end at the shared completion schema.

#### PKT-PRV-074 / PKT-PRV-075 / PKT-PRV-076
- Shared goal: post-4.9.0 streaming hardening
- Config location:
  - project defaults: `.audiagentic/project.yaml` under `prompt-launch.default-stream-controls`
  - provider overrides: `.audiagentic/providers.yaml` under `providers.<provider-id>.stream-controls`
  - request overrides: normalized launch request `stream-controls`
  - precedence: request -> provider -> project
- Code files:
  - `src/audiagentic/streaming/provider_streaming.py`
  - `src/audiagentic/streaming/sinks.py`
- Artifacts:
  - standard streaming artifacts plus quarantine output for invalid events when policy says so
- Tests:
  - timeout warning vs hard timeout
  - sink failure observability
  - invalid-event quarantine or fail behavior
  - bounded memory behavior for stdout and stderr independently
- Junior note: warning-first is the default; do not hardcode short limits or aggressive failures.

#### PKT-PRV-077 — execution policy config contract
- Config location:
  - `.audiagentic/providers.yaml`
  - use `providers.<provider-id>.execution-policy`
- Expected keys:
  - `output-format`
  - `permission-mode`
  - `safety-mode`
  - `auto-approve`
  - `full-auto`
  - `ephemeral`
  - `target-type`
  - `timeout-seconds`
- Spec hooks:
  - `docs/specifications/architecture/03_Common_Contracts.md`
  - `docs/implementation/48_Phase_4_12_Provider_Optimization_and_Shared_Workflow_Extensibility.md`
- Tests:
  - config parsing and precedence tests
- Junior note: only move policy-bearing values here; do not relocate ordinary stable CLI plumbing just because it is a string literal.

#### PKT-PRV-078 — adapter execution-policy normalization
- Code files:
  - `src/audiagentic/execution/providers/adapters/codex.py`
  - `src/audiagentic/execution/providers/adapters/claude.py`
  - `src/audiagentic/execution/providers/adapters/cline.py`
  - `src/audiagentic/execution/providers/adapters/gemini.py`
  - `src/audiagentic/execution/providers/adapters/qwen.py`
  - `src/audiagentic/execution/providers/adapters/opencode.py`
  - `src/audiagentic/execution/providers/adapters/copilot.py`
- Config:
  - read from `providers.<provider-id>.execution-policy`
- Tests:
  - each adapter must have at least one test proving configured policy values change command construction
  - safety-sensitive modes must never silently enable themselves in code
- Junior note: preserve current behavior by encoding defaults in tracked config, not by leaving hidden fallbacks in the adapter.

### Deferred packets

#### PKT-PRV-039 through PKT-PRV-047
- These remain intentionally deferred.
- If they are reactivated later, the shared config locations should be:
  - `.audiagentic/providers.yaml` for provider install policy and checks
  - `.audiagentic/project.yaml` only for project-level opt-in behavior
- Required tests when reactivated:
  - availability probe
  - allowed install
  - denied install
  - already-installed no-op
  - post-bootstrap recheck
- Junior note: these packets must not be started opportunistically while active runtime packets remain unfinished.

#### PKT-PRV-019 / PKT-PRV-027 / PKT-PRV-036
- Continue remains deferred in the current rollout.
- If reactivated later, follow the same config, artifact, and bridge rules as the other providers.

## Final checklist for a worker starting any remaining Phase 4 packet

1. Confirm the packet status in `31_Build_Status_and_Work_Registry.md`.
2. Confirm dependencies are satisfied.
3. Read the packet file and the matching phase doc.
4. Identify config files, runtime artifacts, and tests before changing code.
5. Update both the packet doc and the phase/provider docs if behavior changes.
6. Add or adjust tests before marking the packet `READY_FOR_REVIEW`.
7. Do not move shared logic into provider files or provider logic into shared files unless the packet explicitly owns that boundary.
