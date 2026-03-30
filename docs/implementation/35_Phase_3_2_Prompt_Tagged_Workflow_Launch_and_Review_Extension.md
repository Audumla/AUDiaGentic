# Phase 3.2 Prompt-Tagged Workflow Launch and Review Extension

## Purpose

This is the execution-ready implementation guide for the .2 extension.
It turns the preserved draft into concrete packetized work that can be carried forward from the current codebase without rewriting completed Phase 1-4 behavior.

## Current codebase assumption

The current codebase already has:
- Phase 3 core jobs verified
- Phase 4 providers verified
- Phase 4.1 model catalog work documented but not yet merged
- build registry and packet execution discipline in place

The extension must therefore be additive.

## What changed from the earlier draft

The earlier draft identified intent but left too much open.
This guide freezes the missing details:

- tag syntax is now chosen
- ad hoc work is now a defined target kind, but the first executable pass may keep it feature-gated
- multi-review is now a deterministic bundle model
- review evidence is runtime-only unless surfaced intentionally
- CLI and VS Code are now explicitly thin adapters
- `.audiagentic/project.yaml` is the single MVP override location

## Adapter contract

Interactive surfaces must do only three things before passing control to jobs:
1. parse the first non-empty line
2. normalize into `PromptLaunchRequest`
3. forward the request and prompt body to jobs

They must not:
- decide stage legality on their own
- write review bundles directly
- bypass job validation
- write tracked docs

## Prefix-token-v1 grammar

The first non-empty line uses this grammar:

```text
@<tag> [target=<kind>:<value>] [job=<job-id>] [provider=<provider-id>] [model=<model-ref>] [profile=<profile-id>] [review-count=<n>] [aggregation=<rule>]
```

Examples:

```text
@plan target=packet:PKT-JOB-008 profile=standard
```

```text
@implement target=job:job_20260330_0007 provider=codex model=gpt-5.4-mini
```

```text
@review target=artifact:art_job_0007_impl_plan review-count=2 aggregation=all-pass
```

```text
@adhoc
```

Parsing rules:
- duplicate directives are invalid
- unknown directives are invalid
- unknown tags are invalid
- the prompt body may be empty only for `audit` or `check-in-prep`
- `aggregation=majority-pass` is parsed but must fail validation in MVP as not yet implemented
- `@adhoc` must parse and validate, but execution may return a deterministic `not-enabled` result until the feature gate is explicitly turned on

## Job core implications

### Job creation
The launcher must create a normal JobRecord plus runtime launch metadata.

### Job resumption
The launcher must resolve whether the requested tag is legal for the job’s current state/profile.

### No state machine rewrite
The base state machine remains:
- created
- ready
- running
- awaiting-approval
- completed
- failed
- cancelled

The launcher decides which stage to enter; it does not add new terminal states.

## Review system model

### Review subject
Review runs against a stable subject reference:
- job
- artifact
- packet
- ad hoc subject

### Report
Each review run emits one `ReviewReport`.

### Bundle
The bundle tracks:
- how many reviews are required
- whether distinct reviewers are required
- which reports count
- final decision

### Decision table

| Condition | Decision |
|---|---|
| fewer than required reviews | `pending` |
| duplicate reviewer and distinct required | ignore duplicate for count |
| any counted report = `block` | `blocked` |
| any counted report = `rework` | `rework` |
| all counted reports = `pass` or `pass-with-notes` and count met | `approved` |

## Ad hoc execution model

Ad hoc work uses the same job engine but with a synthetic subject instead of a packet.
In the first executable pass, this may be disabled behind `prompt-launch.allow-adhoc-target=false` while the parser and schema still accept it.
Recommended runtime subject manifest:

```json
{
  "contract-version": "v1",
  "subject-id": "adh_20260330_0001",
  "kind": "adhoc",
  "summary": "Review the current implementation plan and identify missing packet detail."
}
```

This keeps generic work traceable without pretending it is a packet.

## Minimal file/module plan

Planned additive modules:
- `src/audiagentic/jobs/prompt_parser.py`
- `src/audiagentic/jobs/prompt_launch.py`
- `src/audiagentic/jobs/reviews.py`

Expected touch points:
- `src/audiagentic/jobs/records.py`
- `src/audiagentic/jobs/store.py`
- `src/audiagentic/jobs/packet_runner.py`
- `src/audiagentic/jobs/stages.py`
- `src/audiagentic/jobs/approvals.py`
- CLI/editor adapter entry points only for normalization

## Packet breakdown

### PKT-FND-009
Adds schemas, fixtures, contract text, and config schema updates for prompt launch and review bundle artifacts.

### PKT-LFC-009
Ensures lifecycle preserves and validates new `project.yaml` fields.

### PKT-RLS-010
Defines what release/check-in outputs must omit or summarize.

### PKT-JOB-008
Implements parser, normalization, launch plumbing, legal target resolution, and ad hoc target creation.

### PKT-JOB-009
Implements review reports, review bundles, multi-review aggregation, and review-gated progression behavior.

## Required tests

### Contract tests
- prompt-launch-request valid/invalid
- review-report valid/invalid
- review-bundle valid/invalid
- project-config valid/invalid with prompt-launch block

### Unit tests
- prefix-token parser
- target normalization
- stage legality checks
- review aggregation logic
- distinct reviewer counting

### Integration tests
- CLI prompt launches packet work
- VS Code prompt resumes a job
- ad hoc prompt creates generic job
- review prompt emits review report
- second review updates bundle to approved/rework deterministically

### E2E regression checks
- existing Phase 3 state machine behavior unchanged
- release scripts still own tracked doc writes
- lifecycle keeps new config fields during fresh install/update

## Recovery expectations

Every .2 packet must include:
- runtime paths to clean if partial work fails
- the exact pytest targets to rerun
- a note that tracked docs must not be manually edited to compensate for failed runtime artifacts

## Completion criteria for the extension

The extension is **not complete** until all .2 packets are verified and the build registry says so.

This doc pack intentionally marks the work as pending:
- contracts are defined
- packets are defined
- build order is defined
- implementation is still to be done
