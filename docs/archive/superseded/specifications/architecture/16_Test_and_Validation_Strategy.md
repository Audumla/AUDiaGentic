# Test and Validation Strategy

## Purpose

This document defines the minimum validation needed before and during implementation.

## Phase 0 requirements

- all schema examples validate
- at least one valid and invalid fixture per schema exists
- naming normalization checks exist
- lifecycle CLI examples validate

## Destructive test matrix

Required destructive scenarios:
- cutover interrupted before destructive cleanup
- cutover interrupted after workflow rename
- finalize-release interrupted after historical ledger append
- uninstall preserving tracked docs by default
- update from unsupported version returns blocking error
- mixed-or-invalid detection stops safely

## Concurrency test requirements

- concurrent `record-change-event` writes for distinct event ids
- concurrent `sync-current-release-ledger` attempts (one must fail cleanly with lock error)
- rerun of `finalize-release` after partial checkpoint completion
