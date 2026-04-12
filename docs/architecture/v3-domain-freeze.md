# AUDiaGentic v3 Domain Freeze

**Status**: FROZEN — structure locked as of v3 structural refactor (2026-04-12)

This document is the canonical reference for the AUDiaGentic v3 package structure.
It supersedes all pre-refactor scaffold diagrams and Phase 0.x target trees.

---

## Target tree

```
src/audiagentic/
  foundation/
    contracts/      ← schema registry, error types, validation
    config/         ← provider catalog, model configuration
  planning/
    app/            ← PlanningAPI public interface
    domain/         ← item models, state machine, relationship rules
    fs/             ← file system read/write layer
  execution/
    jobs/           ← job orchestration, bridges, state machine, reviews
  interoperability/
    providers/      ← provider adapters, selection, health, surfaces
      adapters/     ← per-provider adapter implementations
      surfaces/     ← tag surface files
    protocols/
      streaming/    ← provider output streaming sinks
      acp/          ← scaffold: ACP inter-agent protocol (reserved)
    mcp/            ← scaffold: MCP server scaffolding (reserved)
  runtime/
    lifecycle/      ← project layout, baseline sync
    state/          ← durable job/review/session persistence
  release/          ← governance, audit, finalization, fragments
  channels/
    cli/            ← CLI operator surface
    vscode/         ← scaffold: VS Code integration (reserved)
  knowledge/        ← scaffold: optional capability domain (reserved)
```

---

## Domain status

| Domain | Status | Notes |
| -------- | ------ | ----- |
| `foundation` | Implemented | Base layer; no domain deps |
| `planning` | Implemented | Full CRUD, state machine, MCP server |
| `execution` | Implemented | Job lifecycle, bridges, reviews |
| `interoperability/providers` | Implemented | Adapters, selection, health |
| `interoperability/protocols/streaming` | Implemented | Pluggable sink architecture |
| `runtime/lifecycle` | Implemented | Baseline sync, project layout |
| `runtime/state` | Implemented | jobs_store, reviews_store, session_input_store |
| `release` | Implemented | Governance, audit, finalization |
| `channels/cli` | Implemented | Full CLI with lifecycle commands |
| `knowledge` | **Scaffold only** | Reserved; no executable code |
| `channels/vscode` | **Scaffold only** | Reserved until CLI stable |
| `interoperability/mcp` | **Scaffold only** | Reserved for MCP server |
| `interoperability/protocols/acp` | **Scaffold only** | Reserved for ACP protocol |

---

## Dependency rules (frozen)

Enforced by `tools/checks/check_cross_domain_imports.py`. See
`docs/specifications/architecture/02A_Repository_Domain_Dependency_Rules.md`
for the full matrix.

Summary:
- `foundation` → no deps (base layer)
- `planning` → `foundation`
- `execution` → `foundation`, `runtime`, `interoperability`, `release`\*
- `interoperability` → `foundation`, `execution`\*
- `runtime` → `foundation`
- `release` → `foundation`, `runtime`
- `channels` → `foundation`, `runtime`, `execution`, `release`
- `knowledge` → `foundation`

\* Intentional one-way seams:
  - `execution → release`: `release_bridge.py` is the only approved crossing
  - `interoperability → execution`: `gemini.py` adapter calls `prompt_launch`

---

## Install model

AUDiaGentic is a **shared install, project-local runtime** model:

| Concern | Location |
| -------- | -------- |
| Shared code (immutable) | `src/audiagentic/` — installed once per environment |
| Project configuration | `.audiagentic/` — per-project, not shared |
| Runtime data | `.audiagentic/runtime/` — per-project, gitignored |
| Planning documents | `docs/planning/` — per-project, version-controlled |

Install:
```bash
pip install -e ".[test]"       # editable with test deps
pip install -e ".[dev]"        # editable with dev tools
pip install -e ".[mcp]"        # with MCP server support
```

CLI entrypoint: `audiagentic` (defined in `pyproject.toml`)

---

## Optional capability domains

`knowledge/` is the canonical example of an optional domain. It is:
- Installed with the shared package (always present as a module)
- Enabled or disabled per consuming project
- Backed by different implementations per project
- Safe to ignore if not needed (scaffold only until implemented)

---

## Deferred decisions

| Item | Decision |
| ---- | -------- |
| `channels/server` | Removed entirely. Reintroduce only with a concrete implementation plan. |
| `interoperability/protocols/acp` | Scaffold reserved. Implement when inter-agent messaging is scoped. |
| `interoperability/mcp` | Scaffold reserved. Separate from `tools/mcp/` server scripts. |
| `channels/vscode` | Scaffold reserved. Implement after CLI surface is stable. |
| `knowledge` | Scaffold reserved. Implement as the next major capability domain. |

---

## Validation commands

Run after any code motion or structural change:

```bash
python tools/misc/refactor_smoke.py
python tools/checks/check_cross_domain_imports.py
python tools/checks/find_legacy_paths.py
python tools/checks/check_baseline_assets.py
python -m pytest tests/unit tests/integration
```

All five must pass before merging structural changes.
