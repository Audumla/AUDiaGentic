# PKT-JOB-008 - Prompt-tagged workflow launch and review loop

**Phase:** Phase 3.2  
**Primary owner group:** Jobs

## Goal

Implement a tagged prompt launch path so CLI or VS Code prompts can start or resume workflow activities such as `plan`, `implement`, and `review`, while preserving prompt provenance and structured review feedback.

## Why this packet exists now

Users want to split work across prompts without losing workflow context. The current job core can execute stages, but it does not yet define how a tagged prompt maps to a workflow activity or how a review prompt should consume another agent's work.

## Dependencies

- `PKT-JOB-002`
- `PKT-JOB-003`
- `PKT-JOB-005`
- `PKT-JOB-007`

## Concrete inputs

This packet must handle:

- prompt source surface: `cli` or `vscode`
- prompt source kind: `interactive-prompt`
- workflow tag: `plan`, `implement`, `review`, `audit`, `check-in-prep`
- optional `job-id` for resuming a previous job
- optional `packet-id` for launching a specific packet

## Ownership boundary

This packet owns the following implementation surface:

- `docs/specifications/architecture/25_DRAFT_Prompt_Tagged_Workflow_Launch_and_Review_Loop.md`
- `docs/implementation/34_DRAFT_Prompt_Tagged_Workflow_Launch_and_Review_Loop.md`
- `src/audiagentic/jobs/` prompt launch plumbing
- prompt-launch tests under `tests/unit/jobs/` and `tests/integration/jobs/`

### It may read from
- workflow profile contracts
- stage execution contract
- job record and approval contracts

### It must not edit directly
- release scripts
- provider adapters
- contract schemas unless they are needed for the prompt envelope itself

## Detailed build steps

1. Freeze the tag syntax and prompt launch envelope.
2. Add a parser/resolver that maps prompt tags to workflow activities.
3. Extend job records so prompt source and tag are preserved.
4. Implement prompt launch plumbing for CLI and VS Code entry surfaces.
5. Add review-stage output that reports findings, missing items, and recommendation.
6. Add fixture-driven tests for plan, implement, and review prompt flows.
7. Verify the prompt launcher does not change the existing sequential job engine.

## Integration points

- `src/audiagentic/jobs/records.py`
- `src/audiagentic/jobs/store.py`
- `src/audiagentic/jobs/packet_runner.py`
- `src/audiagentic/jobs/stages.py`
- `src/audiagentic/jobs/approvals.py`
- `docs/specifications/architecture/08_Agent_Jobs_MVP.md`
- `docs/specifications/architecture/12_Workflow_Profiles_and_Extensibility.md`

## Acceptance criteria

- tagged prompts can launch or resume workflow activities deterministically
- review prompts can evaluate another agent's work artifact and emit structured feedback
- CLI and VS Code provenance is preserved in job and event data
- existing job state machine behavior remains unchanged

## Recovery procedure

If this packet fails mid-implementation:
- revert prompt-launch changes
- rerun `python -m pytest tests/unit/jobs tests/integration/jobs`

## Out of scope

- natural-language-only intent parsing
- automatic fan-out to multiple agents
- provider model catalog behavior
