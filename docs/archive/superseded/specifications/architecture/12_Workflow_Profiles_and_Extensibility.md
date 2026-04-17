# Workflow Profiles and Extensibility

## Purpose

Profiles let simple projects start with light process and later opt into stricter behavior.

## Built-in profiles

### lite
- plan
- implement
- optional summary on request

### standard
- plan
- implement
- review
- check-in prep

### strict
- plan
- approval
- implement
- review
- audit
- check-in prep
- approval

## Profile schema

```yaml
profile-id: lite
stages:
  - id: plan
    required: true
  - id: implement
    required: true
  - id: review
    required: false
```

## Override rules

- projects may override stage enablement only in MVP
- projects may not reorder built-in stages in MVP
- projects may not add new stage ids in MVP without explicit implementation support

## Failure semantics

- required stage failure stops the job
- optional stage failure records warning and continues if profile allows


## Phase 3.2 extension: prompt-tagged workflow launch

Phase 3.2 adds prompt tags that select a workflow activity deterministically.

Frozen MVP rules:
- prompt syntax is `prefix-token-v1`
- tags are `plan`, `implement`, `review`, `audit`, and `check-in-prep`
- shorthand `@adhoc` is accepted as `@implement target=adhoc`, but may remain feature-gated in the first executable pass
- tag resolution happens before the stage runner starts
- prompt launch never reorders profile stages; it only enters or resumes the correct legal stage

Target rules:
- packet-oriented work uses `target.kind=packet`
- generic user-directed work uses `target.kind=adhoc`
- review uses `target.kind=artifact`, `job`, or `packet`

Review output must be structured so a later prompt can respond to findings deterministically.

## Stage execution contract


Every built-in stage executes against a common contract:

```yaml
stage-contract:
  input:
    - job-record
    - packet-context
    - previous-stage-output  # optional
  output:
    stage-result: success | failure | skipped
    artifacts: []
    next-stage-recommendation: continue | stop | escalate
    warnings: []
```

Stage timeout rules:
- `plan`: 10 minutes
- `implement`: provider-defined, but caller must surface timeout as failure
- `review`: 10 minutes
- `audit`: 10 minutes
- `check-in-prep`: 10 minutes


## Override storage

MVP profile overrides live in `.audiagentic/project.yaml`.

Example:

```yaml
workflow-profile: standard
workflow-overrides:
  review:
    enabled: false
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

Override rules:
- only stage enablement may be overridden in MVP
- built-in stage order is fixed in MVP
- projects may disable only optional stages
- required stages in a built-in profile may not be disabled
- prompt-launch policy is stored in `.audiagentic/project.yaml` for MVP
- `.audiagentic/workflows.yaml` is deferred and must not be introduced by implementation packets unless the architecture is explicitly revised
- `prompt-launch.allow-adhoc-target` may be turned on later without requiring contract rewrites
