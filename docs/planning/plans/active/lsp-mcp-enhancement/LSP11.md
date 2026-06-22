---
id: LSP11
order: 11
plan: plan-lsp-mcp-enhancement
state: draft
wave: W3.2
phase: Phase 0
---

# Position encoding negotiation

## Context

Wave W3.2 — Handshake correctness (prerequisites for later tool phases).

## Steps

LSP positions are UTF-16 code units by default; current tools pass `character` straight through, so any line with non-ASCII content yields off-by-N positions.

Advertise `general.positionEncodings: ['utf-8','utf-16']` in initialize, read the server's chosen `positionEncoding` from the result, and convert agent (codepoint/UTF-8) offsets to the negotiated encoding in one shared helper used by every position-taking tool. Default to UTF-16 when the server does not negotiate.

## Files

`lsp_lifecycle.py`, shared helper

## Validation

Definition/hover on a non-ASCII line resolves correctly.

## Dependencies

None

## Notes


