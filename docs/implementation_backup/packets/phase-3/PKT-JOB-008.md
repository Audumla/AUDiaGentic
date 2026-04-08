# PKT-JOB-008 — Prompt-tagged launch core + ad hoc target

**Phase:** Phase 3.2  
**Primary owner group:** Jobs

## Goal

Implement the normalized prompt launch path that parses `prefix-token-v1`, resolves a legal workflow target, creates or resumes a job, preserves provenance, and supports generic ad hoc work without changing the Phase 3 state machine.

## Why this packet exists now

The current job core can execute stages, but it still lacks a deterministic entry path from interactive prompts. The original requirement was to let prompts in VS Code and CLI tools trigger workflow work safely. This packet adds that entry path and closes the missing `adhoc` path for generic work, but `adhoc` can remain feature-gated in the first implementation pass.

## Dependencies

- Phase 3 gate `VERIFIED`
- `PKT-JOB-007`
- `PKT-FND-009`
- `PKT-LFC-009`

## Concrete inputs

This packet must support:

- `prefix-token-v1` prompt parsing
- prompt surfaces `cli` and `vscode`
- tags: `plan`, `implement`, `review`, `audit`, `check-in-prep`
- shorthand `@adhoc`
- target kinds: `packet`, `job`, `artifact`, `adhoc`
- optional provider/model metadata already frozen by .1 packets
- optional review policy fields passed through without yet aggregating review bundles

## Ownership boundary

This packet owns the following implementation surface:

- `docs/specifications/architecture/26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `docs/implementation/35_Phase_3_2_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `src/audiagentic/execution/jobs/prompt_parser.py`
- `src/audiagentic/execution/jobs/prompt_launch.py`
- additive updates in `src/audiagentic/execution/jobs/records.py`
- additive updates in `src/audiagentic/execution/jobs/store.py`
- additive updates in `src/audiagentic/execution/jobs/packet_runner.py`
- job tests under `tests/unit/jobs/` and `tests/integration/jobs/`

### It may read from
- workflow profile contracts
- provider/model metadata contracts from .1 packets
- lifecycle-owned config handling for `.audiagentic/project.yaml`

### It must not edit directly
- provider selection rules
- release generators
- review bundle aggregation logic beyond storing the launch request and subject references
- tracked release docs

## Detailed build steps

1. Implement a parser for `prefix-token-v1`.
2. Normalize CLI/VS Code input into `PromptLaunchRequest`.
3. Validate tag and target-kind combinations.
4. Resolve whether the request creates a new job or resumes an existing one.
5. Preserve prompt provenance on the job record and change/event source metadata.
6. Implement `adhoc` target creation with runtime subject manifest storage.
7. Ensure launch validation rejects illegal state/profile transitions.
8. Keep the existing job state machine intact.
9. Add fixtures and tests for valid/invalid prompt launch requests.
10. Add integration tests for CLI launch, VS Code launch, resume, and ad hoc creation.

## Required runtime artifacts

This packet must write only runtime artifacts such as:

- `.audiagentic/runtime/jobs/<job-id>/launch-request.json`
- `.audiagentic/runtime/jobs/<job-id>/subject.json` for `adhoc`

It must not create tracked docs.

## Integration points

- `src/audiagentic/execution/jobs/state_machine.py`
- `src/audiagentic/execution/jobs/stages.py`
- `src/audiagentic/execution/jobs/approvals.py`
- `src/audiagentic/execution/jobs/release_bridge.py`
- CLI/editor adapter entry points that call into jobs

## Tests to add or update

- `tests/unit/jobs/test_prompt_parser.py`
- `tests/unit/jobs/test_prompt_launch_validation.py`
- `tests/integration/jobs/test_prompt_launch_flow.py`

Minimum cases:
- valid `@plan target=packet:...`
- valid `@implement target=job:...`
- valid `@adhoc`
- invalid duplicate directives
- invalid unknown tag
- invalid target for current stage/state
- invalid resume of terminal job

## Acceptance criteria

- prompts normalize deterministically into `PromptLaunchRequest`
- CLI and VS Code provenance is preserved on runtime job/event data
- `@adhoc` is accepted by parser/schema validation
- illegal target or stage transitions fail with explicit validation errors
- existing Phase 3 state transitions remain unchanged

### Optional / feature-gated in first pass

- `@adhoc` creates a valid generic subject and job when `prompt-launch.allow-adhoc-target=true`
- ad hoc work can be deferred to a second implementation pass without contract churn

## Recovery procedure

If this packet fails mid-implementation:
- revert changes in `src/audiagentic/execution/jobs/prompt_parser.py`, `prompt_launch.py`, and additive job-module edits
- delete partial runtime launch artifacts under `.audiagentic/runtime/jobs/*/launch-request.json`
- delete partial ad hoc subject manifests under `.audiagentic/runtime/jobs/*/subject.json`
- rerun `python -m pytest tests/unit/jobs/test_prompt_parser.py tests/unit/jobs/test_prompt_launch_validation.py tests/integration/jobs/test_prompt_launch_flow.py`

## Parallelization note

This packet may run only after dependencies are verified and only in parallel with work that does not modify job modules.

## Out of scope

- review bundle aggregation
- majority-pass review policy
- natural-language routing without tags
- automatic multi-agent fan-out
