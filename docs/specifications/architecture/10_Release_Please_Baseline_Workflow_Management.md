# Release Please Baseline Workflow Management

## Purpose

Release Please is the first release strategy plugin and the baseline release workflow installed into a project during enablement or cutover.

## Canonical managed files

Managed by AUDiaGentic:
- `.github/workflows/release-please.yml`
- optional supporting release-please config files if the baseline uses them

These files must be tracked in the managed file registry.

## Invocation pattern

In the baseline architecture, AUDiaGentic prepares tracked release docs and managed workflow/config files. Release Please is then executed through the installed GitHub workflow as the primary release strategy implementation.

AUDiaGentic does **not** require a local Release Please CLI for MVP correctness.

The project-level `release-bootstrap` command is the local bootstrap entry point that prepares the tracked docs, installed state, and managed workflow baseline before normal release execution continues.

## Workflow state classification

- `absent`
- `managed-unmodified`
- `managed-modified`
- `legacy-detected`
- `external-unknown`

## Behavior rules

### Fresh enablement
- if absent, install baseline workflow

### Legacy cutover
- rename old workflow to `*.legacy-pre-audiagentic.yml`
- install baseline workflow
- emit warning requiring manual migration of custom logic

### Update
- if managed-unmodified, update baseline
- if managed-modified or external-unknown, preserve existing file and install candidate workflow as `.audiagentic.candidate.yml`, then emit warning

## Warning rule

Any workflow preservation or rename action must emit:
- console warning
- machine-readable warning record
- entry in lifecycle result summary


## MVP invocation model

Release Please is invoked in MVP as a GitHub Actions workflow installed into the target project.

Invocation rules:
- AUDiaGentic prepares tracked release documents locally
- the managed Release Please workflow runs on GitHub as the authoritative release strategy execution surface
- AUDiaGentic does not poll GitHub continuously in MVP
- follow-up status is determined by explicit operator review of workflow results or CI status in the normal project flow
- webhook or API-driven callback integration is deferred until a later phase

## Managed files

The managed baseline file name in MVP is:

```text
.github/workflows/release-please.audiagentic.yml
```

Conflict policy:
- existing project or legacy workflows are never overwritten silently
- legacy workflow candidates are renamed with a `.legacy-pre-audiagentic.yml` suffix
- externally managed unknown workflows remain in place and trigger a warning


## Recommended implementation note

For MVP, AUDiaGentic treats the GitHub workflow as the invocation mechanism of record. The release core prepares the tracked docs and managed files, then validates workflow-driven outcomes on a later pass. Direct library embedding or polling loops are DRAFT future options.
