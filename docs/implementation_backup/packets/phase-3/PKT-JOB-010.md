# PKT-JOB-010 — Prompt shorthand and default-launch behavior

**Phase:** Phase 3.3  
**Primary owner group:** Jobs

## Goal

Add ergonomic prompt-launch shorthand so a user can type a provider or short action alias and still get a deterministic prompt-launch request, default subject, and provider-selected model without rewriting the existing Phase 3.2 launch contract.

## Why this packet exists now

The prompt-launch path is already in place, but it still requires more typing than necessary for common workflows. This enhancement keeps the same normalized launch envelope while making the user-facing prompt form shorter and easier to use.

## Dependencies

- `PKT-JOB-008`
- `PKT-PRV-012`
- `PKT-PRV-013`

## Concrete inputs

This packet must support:

- short action aliases for launch tags
- provider shorthand prompt tokens
- default runtime subject generation when target is omitted
- provider-default model selection during launch and resume
- existing `prefix-token-v1` normalization

## Ownership boundary

This packet owns the following implementation surface:

- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/specifications/architecture/08_Agent_Jobs_MVP.md`
- `docs/specifications/architecture/26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `docs/implementation/37_Phase_3_3_Prompt_Tagged_Workflow_Shortcuts_and_Defaults.md`
- `src/audiagentic/execution/jobs/prompt_parser.py`
- `src/audiagentic/execution/jobs/prompt_launch.py`
- `src/audiagentic/config/provider_config.py`
- `src/audiagentic/contracts/schemas/prompt-launch-request.schema.json`
- `tests/unit/jobs/test_prompt_parser.py`
- `tests/integration/jobs/test_prompt_launch_flow.py`

### It may read from
- prompt-launch contracts from PKT-JOB-008 / PKT-FND-009
- provider model catalog and status contracts from PKT-PRV-012 / PKT-PRV-013
- lifecycle handling for project config

### It must not edit directly
- review aggregation logic
- provider adapters
- release generation
- tracked release docs

## Detailed build steps

1. Add short action aliases to the prompt parser.
2. Add provider shorthand prompt handling and validate conflicts.
3. Generate a default runtime subject when target is omitted.
4. Resolve provider default model from provider config during launch/resume.
5. Preserve the existing normalized launch envelope and runtime provenance.
6. Add tests for shorthand tags, provider shorthand, and omitted-target defaults.
7. Update build registry and tracker entries.

## Integration points

- `src/audiagentic/execution/jobs/prompt_parser.py`
- `src/audiagentic/execution/jobs/prompt_launch.py`
- `src/audiagentic/config/provider_config.py`
- `src/audiagentic/execution/providers/models.py`
- `src/audiagentic/execution/providers/status.py`
- `tests/unit/jobs/test_prompt_parser.py`
- `tests/integration/jobs/test_prompt_launch_flow.py`

## Acceptance criteria

- `@p`, `@i`, `@r`, `@a`, and `@c` normalize to the same workflow tags as their long forms
- provider shorthand launches infer a provider and default model deterministically
- omitted targets create a sensible default runtime subject and job id
- explicit `@adhoc` remains separately feature-gated from shorthand provider launches
- the existing prompt-launch contract and review path remain stable

## Recovery procedure

If this packet fails mid-implementation:
- revert prompt parser and prompt launch edits
- remove partially written runtime launch artifacts under `.audiagentic/runtime/jobs/*/`
- rerun the focused prompt parser and prompt launch test set

## Parallelization note

This packet may run only after `PKT-JOB-008`, `PKT-PRV-012`, and `PKT-PRV-013` are verified.

## Out of scope

- changing the review bundle contract
- changing provider CLI health checks
- automatic fan-out to multiple jobs from one prompt
