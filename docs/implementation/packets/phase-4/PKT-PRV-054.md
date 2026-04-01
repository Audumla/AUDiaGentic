# PKT-PRV-054 — Session provenance redaction and secure-session reference seam

**Phase:** Phase 4.10
**Status:** DEFERRED_DRAFT
**Owner:** Codex

## Objective

Capture the follow-on security boundary for live provider sessions: raw provider session keys,
tokens, or other secret session material must not be treated as log-safe runtime data.

AUDiaGentic may preserve non-secret session provenance for correlation, but durable runtime
artifacts should store only redacted handles or secure references once the fuller secure-session
design is implemented.

## Why this exists

The current live-stream and live-input work introduces runtime artifacts such as:

- `.audiagentic/runtime/jobs/<job-id>/stdout.log`
- `.audiagentic/runtime/jobs/<job-id>/stderr.log`
- `.audiagentic/runtime/jobs/<job-id>/input.ndjson`
- `.audiagentic/runtime/jobs/<job-id>/stdin.log`
- `.audiagentic/runtime/jobs/<job-id>/input-events.ndjson`

Those files are useful for operator visibility and later overlays, but they should not become a
durable store for raw provider session secrets.

## Scope

This packet should eventually define:

1. which session values are safe to persist directly
2. which values must be redacted, omitted, or replaced with secure references
3. how runtime provenance keeps correlation without exposing secret material
4. how later providers and overlays consume secure session references safely

## Non-goals

- no full secret/session vault design yet
- no change to the current provider launch grammar
- no requirement that every provider expose the same session model
- no forced rewrite of current raw runtime logs in the same slice

## Dependencies

- `PKT-PRV-051`
- current Phase 4.10 contract and runtime artifact layout

## Expected outputs

- canonical rule in the common contracts and live-input/live-stream docs
- a secure-session-reference design note for later implementation
- future redaction/update tasks for the shared streaming and session-input harnesses

## Acceptance criteria

- the docs explicitly say raw provider session keys are not log-safe
- the docs distinguish non-secret session provenance from sensitive provider session material
- the follow-on secure-session store/reference seam is named without over-specifying it
- later implementation packets can apply the rule without redefining provider workflow semantics
