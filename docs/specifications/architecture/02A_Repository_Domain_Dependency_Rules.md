# Repository-Domain Dependency Rules (v3)

> **Updated for v3 structural refactor.** This document replaces the pre-refactor
> `Phase 0.3` addendum. Domain names now reflect the live `src/audiagentic/` tree.

## Purpose

Defines the canonical package-level repository-domain dependency rules for the v3 structure.
This is the single source of truth for which domain may import from which.

## Domain inventory

### Implemented domains

Under `src/audiagentic/`:

| Domain | Description |
| -------- | ----------- |
| `foundation` | Shared contracts, config, and schema registry (base layer) |
| `planning` | Planning workflows, item types, state machine, and file system layer |
| `execution` | Job orchestration, prompt bridges, state machine, and reviews |
| `interoperability` | Provider adapters, streaming protocol, and protocol scaffolding |
| `runtime` | Lifecycle management and durable state persistence |
| `release` | Release governance, audit, and finalization |
| `channels/cli` | CLI operator surface |

### Scaffold-only domains (reserved, no executable code)

| Domain | Status |
| -------- | ------ |
| `knowledge` | Optional capability domain — reserved to prevent other modules absorbing this ownership |
| `channels/vscode` | VS Code editor integration — deferred until CLI is stable |
| `interoperability/mcp` | MCP protocol server — scaffolding only |
| `interoperability/protocols/acp` | ACP inter-agent protocol — scaffolding only |

## Allowed repository-domain dependencies

This table is the canonical source of truth. It is enforced by `tools/checks/check_cross_domain_imports.py`.

| Domain | May import from |
| -------- | --------------- |
| `foundation` | *(none — base layer)* |
| `planning` | `foundation` |
| `execution` | `foundation`, `runtime`, `interoperability`, `release` (see seam note) |
| `interoperability` | `foundation`, `execution` (see seam note) |
| `runtime` | `foundation` |
| `release` | `foundation`, `runtime` |
| `channels` | `foundation`, `runtime`, `execution`, `release` |
| `knowledge` | `foundation` |

## Forbidden dependencies

- `foundation → any domain`
- `runtime → execution`, `runtime → release`, `runtime → channels`
- `release → channels`, `release → execution`
- `channels → execution internals beyond approved entrypoints`

## Approved cross-layer seams

Two one-way cross-layer seams are intentionally allowed and must not be expanded without a boundary review.

**Seam 1: interoperability → execution**
`interoperability/providers/adapters/gemini.py` imports from `execution.jobs.prompt_launch`
and `execution.jobs.prompt_parser`. The gemini adapter needs to launch sub-jobs. Approved.

**Seam 2: execution → release**
`execution/jobs/release_bridge.py` imports from `release.*`. The release bridge is an
orchestration connector — execution triggers the release domain on job completion. Approved.
No other execution code may import from release without a boundary review.

## Enforcement

Run after any code motion:

```bash
python tools/checks/check_cross_domain_imports.py
```

This tool enforces the allowed/forbidden rules above by scanning all Python source under
`src/audiagentic/` and reporting violations.
