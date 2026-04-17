# Feasibility, Risks, and Open Questions

## Purpose

This document tracks only unresolved items that remain after this corrective pass.

## Remaining open decisions

1. exact long-term optional-server API style if it is ever implemented
2. whether provider session mirroring will ever be attempted beyond Discord summary overlay
3. whether additional secret reference types beyond `env:` are needed post-MVP (MVP remains env-only)

## Risks already addressed in this pack

- missing common contracts
- under-specified lifecycle result types
- ledger idempotency gaps
- managed workflow ambiguity
- approval timeout gaps
- naming inconsistency


## Draft companion notes

The following draft documents fill future-facing gaps without changing MVP scope:
- `20_DRAFT_Secrets_and_CI_Guidance.md`
- `21_DRAFT_Operational_Scale_and_Performance_Notes.md`
- `22_DRAFT_ReleasePlease_Invocation_Options.md`
- `23_DRAFT_Optional_Server_and_Session_Mirroring.md`
