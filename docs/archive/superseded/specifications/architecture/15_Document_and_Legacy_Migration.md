# Document and Legacy Migration

## Purpose

This document defines safe migration of legacy docs and recognized tracked project material into the new layout.

## Migration outcomes

- `migrated`
- `copied-for-review`
- `skipped-ambiguous`
- `skipped-conflict`

## Safe migration heuristics

A file is `migrated` only if all are true:
- the source path clearly maps to a target doc class
- target file is absent or byte-identical
- filename and content category agree
- no conflicting managed file ownership exists

A file is `copied-for-review` if:
- likely category can be inferred
- but target already exists with different content

A file is `skipped-ambiguous` if:
- file type or intent cannot be classified confidently

A file is `skipped-conflict` if:
- migrating it would overwrite managed or user-retained material

## Migration report

Every cutover must emit a report with per-file outcome and rationale.


## Outcome examples

### migrated
- source: `docs/specifications/architecture/old_release_notes.md`
- target: `docs/releases/RELEASE_NOTES.md`
- rule: clearly classified retained release doc with no target conflict

### copied-for-review
- source: `docs/mixed_notes/release_and_design.md`
- target: `.audiagentic/runtime/migration/review/release_and_design.md`
- rule: document mixes architecture and release content so safe automatic placement is not possible

### skipped-ambiguous
- source: `notes/tmp.md`
- result: left in place, noted in migration report
- rule: document classification confidence below migration threshold

### skipped-conflict
- source: `docs/releases/CHANGELOG.md`
- result: left in place, conflict recorded
- rule: target file already exists with materially different managed content and cannot be reconciled safely
