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
```

Override rules:
- only stage enablement may be overridden in MVP
- built-in stage order is fixed in MVP
- projects may disable only optional stages
- required stages in a built-in profile may not be disabled


## Override location

Project-specific overrides live in:

```text
.audiagentic/workflows.yaml
```

MVP rules:
- built-in profile id remains in `.audiagentic/project.yaml`
- override details live in `.audiagentic/workflows.yaml`
- only stage enablement may be overridden in MVP
- `plan` and `implement` may not be disabled
