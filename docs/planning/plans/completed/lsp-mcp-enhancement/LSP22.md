---
id: LSP22
order: 22
plan: plan-lsp-mcp-enhancement
state: superseded
superseded-by: CAP04 (completion/signature/inlay-hints), CAP05 (auto-apply); skills/tree-sitter/secret-scan remain deferred
validate-first: true
complexity: complex
wave: deferred
phase: post-v1
---

# Completion, signature help, inlay hints, skills, tree-sitter, secret scan

## Context

Wave deferred — Deferred — Post-v1.

## Steps

- Completion/signature/inlay-hints tools
- Agent skills (`code-intelligence`, `safe-refactor`, `post-edit-verify`)
- Tree-sitter fallback
- Secret scanning
- Auto-apply for code actions, formatting, rename

**Rationale (from Decisions):** Skills are bounded by the MCP capability surface — they cannot add coverage the server lacks, only orchestrate it. Usage reliability is better fixed by MCP tool ergonomics (Phase 2) than by opt-in skill prose. Build the MCP surface + ergonomics first; revisit a thin skill layer only after v1 ships and a measured usage gap remains.

## Files

Deferred

## Validation

N/A — deferred

## Architecture Standards Assessment

**Standards risk: N/A.** Deferred — not actionable until v1 ships.

## Resolution Assessment

**Complexity: Deferred.** Not actionable until v1 ships.

**Scope:** Completion/signature/inlay-hints tools, agent skills (code-intelligence, safe-refactor, post-edit-verify), tree-sitter fallback, secret scanning, auto-apply for code actions/formatting/rename.

**Rationale:** Skills are bounded by the MCP capability surface — they cannot add coverage the server lacks, only orchestrate it. Usage reliability is better fixed by MCP tool ergonomics (Phase 2 / LSP20) than by opt-in skill prose. Build the MCP surface + ergonomics first; revisit a thin skill layer only after v1 ships and a measured usage gap remains.

## Dependencies

V1 completion

## Notes

See V1 Scope Boundaries in plan overview.