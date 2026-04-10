# Phase 3 — Jobs and simple workflows

This phase introduces the job engine, but keeps it intentionally simple. The job engine must consume frozen contracts from earlier phases and must use the release scripts instead of reimplementing release logic internally. Only `lite`, `standard`, and `strict` workflow profiles are in scope.

## Phase deliverables

See the packet files for exact build steps.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.


## Phase 3.2 extension note

Prompt-tagged launch and structured review are additive follow-on packets. Do not begin them until `.1` provider/model work and `.2` contract/lifecycle prerequisites are verified. Use `35_Phase_3_2_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md` and the Phase 3.2 packet set for execution.

## Phase 3.3 extension note

Prompt shorthand and default-launch behavior are an ergonomic follow-on packet set. Use `37_Phase_3_3_Prompt_Tagged_Workflow_Shortcuts_and_Defaults.md` and the Phase 3.3 packet set for execution. This enhancement must keep the normalized prompt-launch contract intact while adding provider shorthand and inferred defaults.
