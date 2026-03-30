# Phase 4.4 — Provider Tag Execution Implementation

Status: additive implementation spec  
Completion state: NOT IMPLEMENTED  
Coding readiness: PARTIAL — ready for provider-by-provider execution only after the existing
Phase 4.3 provider-surface contract line is frozen

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`

## Packet set

1. `PKT-PRV-022` — shared provider execution compliance model and conformance matrix
2. `PKT-PRV-023` — Codex execution implementation
3. `PKT-PRV-024` — Claude Code execution implementation
4. `PKT-PRV-025` — Gemini execution implementation
5. `PKT-PRV-026` — GitHub Copilot execution implementation
6. `PKT-PRV-027` — Continue execution implementation
7. `PKT-PRV-028` — Cline execution implementation
8. `PKT-PRV-029` — local OpenAI-compatible execution implementation
9. `PKT-PRV-030` — Qwen Code execution implementation

## Purpose

This document translates the provider tag execution compliance model into an external
implementation plan. It supplements the existing provider plans instead of replacing them.

## Goals

1. confirm how canonical prompt tags can be executed for each provider
2. identify where wrappers are required
3. avoid duplicating core semantics in every provider
4. provide one stable checklist for external implementation teams

## Shared outputs required from every provider integration

Every provider implementation must end with the following concrete outputs:

- canonical tag map
- provider settings ownership document
- CLI execution path
- VS Code execution path (if the provider has one)
- review-mode restrictions
- smoke-test results
- known-limitations note
- rollback procedure

## Required canonical smoke tests

Each provider implementation should pass these tests before being marked complete.

### ST-01 plan launch
Input:
- `@plan packet PKT-JOB-008`

Expected:
- provider surface recognizes the tag
- provider normalizes the request
- provider enters planning-safe mode
- provider does not start unrestricted implementation work

### ST-02 implementation launch
Input:
- `@implement packet PKT-JOB-008`

Expected:
- provider recognizes the tag
- provider sets implementation mode/tool policy
- provider preserves provenance
- provider does not silently downgrade to generic chat mode

### ST-03 review launch
Input:
- `@review artifact docs/specifications/...`

Expected:
- provider enters review mode
- provider uses review prompt/skill/agent/workflow
- provider returns structured review output or equivalent normalized review artifact

### ST-04 unsupported tag
Input:
- `@unknown hello`

Expected:
- deterministic validation error
- no provider-side freeform execution

### ST-05 no-tag prompt
Input:
- `please review this packet`

Expected:
- standard provider behavior
- no canonical tag normalization unless explicit config enables heuristic upgrades

## Provider sequencing recommendation

Recommended order:
1. Claude Code
2. Gemini CLI / Gemini Code Assist
3. Cline
4. Codex
5. GitHub Copilot
6. Continue
7. Qwen Code
8. local OpenAI-compatible backend documentation only

Reason:
- start with providers that expose real prompt interception
- then implement adapter-based providers
- treat backend-only providers as wiring notes rather than user-facing tag surfaces

## Shared implementation files to create in code later

These are implementation targets, not part of the docs delta:
- `provider_adapters/shared/normalize_prompt_tag.py`
- `provider_adapters/shared/request_envelope.py`
- `provider_adapters/shared/tag_validation.py`
- `provider_adapters/<provider>/...`

## Decision gates

Do not start execution if:
- the existing `.1` provider/model contract line is not frozen
- canonical tags are still changing
- `@adhoc` scope is still undecided for the initial execution pass

## Success condition

This phase is complete only when:
- every enabled provider has a written implementation record
- every enabled provider passes canonical smoke tests
- CLI and VS Code surfaces are synchronized where both exist
- provider docs reflect whether native intercept or adapter mode is used

