---
id: LSP19
order: 19
plan: plan-lsp-mcp-enhancement
state: done
wave: W5.5
phase: Phase 1
---

# Fail loud on diagnostics errors

## Context

Wave W5.5 — Diagnostics v2 (Phase 1).

## Steps

Replace `except Exception: return {}` (`lsp_lifecycle.py:216`) with the W1.2 envelope. An agent cannot tell a clean file from a broken request. Return the Phase 0 structured error envelope on failure; reserve empty result for genuinely clean files. Keep `lsp_diagnostics` as compatibility alias.

## Files

`lsp_lifecycle.py` (:216)

## Validation

A failed diagnostics request returns a structured error envelope, distinct from the empty result for a clean file.

## Dependencies

LSP04

## Notes


