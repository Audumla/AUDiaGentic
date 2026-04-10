# Release Please Invocation

> **Status:** DRAFT implementation decision.  
> This document records the recommended MVP pattern without making richer alternatives part of the baseline.

## Recommended MVP pattern

Release Please is treated as an **external workflow authority**. AUDiaGentic prepares tracked release docs and managed workflow/config files, then validates the workflow-managed outputs in a later step.

## MVP rule

`finalize-release` must not embed Release Please as an in-process dependency. It must:
1. prepare deterministic release docs and checkpoints
2. prepare/update the managed Release Please workflow and config
3. stop after writing the handoff state expected by the workflow
4. verify resulting changes on the next validation pass

## Non-goals for MVP

- GitHub API polling loop inside core release code
- library embedding of Release Please
- alternative invocation backends

## Revisit point

Revisit in Phase 2 only if the managed workflow path proves insufficient.
