# Installer v14 import-ready status

## Status

This copy is reformatted to raw integer IDs matching live planning lane format (`kind-n`, no zero-padding).

It remains external only. Not imported.

## Current live-safe IDs (raw integer format)

All IDs use raw integer format matching the live planning lane (`kind-n`, no padding).

- request: `request-32`
- specs: `spec-80` through `spec-85`
- plan: `plan-23`
- work packages: `wp-28` through `wp-31`
- tasks: `task-347` through `task-360`

## ID remap (pack padded format -> live-safe raw format)

| Pack (padded) | Live-safe (raw) |
|---|---|
| request-021 | request-32 |
| spec-0080 | spec-80 |
| spec-0081 | spec-81 |
| spec-0082 | spec-82 |
| spec-0083 | spec-83 |
| spec-0084 | spec-84 |
| spec-0085 | spec-85 |
| plan-0023 | plan-23 |
| wp-0028 | wp-28 |
| wp-0029 | wp-29 |
| wp-0030 | wp-30 |
| wp-0031 | wp-31 |
| task-0348 | task-347 |
| task-0349 | task-348 |
| task-0350 | task-349 |
| task-0351 | task-350 |
| task-0352 | task-351 |
| task-0353 | task-352 |
| task-0354 | task-353 |
| task-0355 | task-354 |
| task-0356 | task-355 |
| task-0357 | task-356 |
| task-0358 | task-357 |
| task-0359 | task-358 |
| task-0360 | task-359 |
| task-0361 | task-360 |

## Pre-import rule

Re-run a live collision check immediately before import. If any ID is now occupied,
create a fresh remap — do not import stale IDs.

## v14 additions (component lifecycle)

Added after initial v14 recut. No predecessor IDs — these are new items:

- `spec-85` (new) — component lifecycle manifest schema and semantics
- `task-359` (new) — freeze component lifecycle manifest schema (wp-28, seq 4000)
- `task-360` (new) — freeze disable and uninstall reconcile behavior (wp-29, seq 4000)
