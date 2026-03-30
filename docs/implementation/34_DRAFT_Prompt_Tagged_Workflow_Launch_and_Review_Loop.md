# Draft Guide - Prompt-Tagged Workflow Launch and Review Loop

## Goal

Define the implementation shape for the Phase 3.2 prompt-tag feature before any code changes.

## What the feature should do

- let a tagged prompt start a workflow activity
- let a second prompt continue or finish the work
- let a review prompt validate another agent's output
- preserve whether the prompt came from CLI or VS Code

## Recommended flow

1. User writes a prompt with an explicit workflow tag.
2. Launcher resolves the tag to a workflow activity.
3. Launcher creates or resumes a job record.
4. The selected stage executes and writes an artifact.
5. A later prompt with `review` inspects the artifact and emits findings.
6. Follow-up prompts can loop until acceptance criteria are met.

## Suggested tag strategy

The tag should be simple and explicit. Good candidates are:
- prefix token such as `@plan`, `@implement`, `@review`
- fenced metadata block that includes `tag` and optional `job-id`

The implementation should choose one syntax and freeze it before coding.

## Suggested data to record

- prompt id
- prompt surface (`cli` or `vscode`)
- provider id
- workflow profile
- tag
- packet id or job id
- review result when applicable

## Required integration points

- `docs/specifications/architecture/25_DRAFT_Prompt_Tagged_Workflow_Launch_and_Review_Loop.md`
- `docs/specifications/architecture/12_Workflow_Profiles_and_Extensibility.md`
- `docs/specifications/architecture/08_Agent_Jobs_MVP.md`
- `src/audiagentic/jobs/`
- CLI or VS Code prompt entry path

## Next steps

1. Freeze the tag syntax.
2. Decide whether launch creates a new job or a launch envelope around an existing job.
3. Add the new packet and tracker entry for Phase 3.2.
4. Implement parser and launch plumbing.
5. Add review artifact schema and tests.
6. Add CLI and VS Code entry point tests.

## Risks

- ambiguous tag syntax will create user confusion
- review prompts without explicit acceptance criteria may become subjective
- if prompt provenance is not preserved, CLI and VS Code behavior may drift
