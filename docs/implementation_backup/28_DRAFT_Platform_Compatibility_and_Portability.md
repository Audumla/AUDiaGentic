# DRAFT Platform Compatibility and Portability

> Draft guidance only. Not an MVP blocker.

## Purpose

Capture portability rules so implementation does not drift into platform-specific assumptions.

## Recommended baseline rules

- use `pathlib.Path` for all filesystem paths
- avoid string-concatenated paths
- prefer LF for generated text files
- keep lock semantics abstracted behind a helper
- keep shell-specific assumptions out of core modules

## Suggested future CI enhancement

Add a platform matrix once Phase 0 stabilizes:
- ubuntu-latest
- macos-latest
- windows-latest

## Why this is draft

Portability matters, but it should not widen MVP scope before the core contracts, lifecycle, and ledger behavior are stable.
