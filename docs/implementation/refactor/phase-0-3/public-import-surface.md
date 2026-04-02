# Public Import Surface

## Scope

- checkpoint date: 2026-04-02
- owner: Phase 0.3 checkpoint
- packet: PKT-FND-010
- status: seeded working surface list

## Public import surface rule

For the Phase 0.3 refactor, the following are treated as public import or path surfaces and must be preserved through approved shims or explicit migration handling:

- console-entry and CLI-facing package paths
- paths imported by `tools/*`
- package paths referenced by tracked docs/examples as supported
- paths referenced by install/bootstrap/baseline workflows
- package roots explicitly treated as stable in current implementation docs

Internal-only imports may be rewritten directly during `PKT-FND-012`.

## Seed public surfaces

| Surface | Why public | Shim/migration expectation |
|---|---|---|
| `audiagentic.cli.*` | console-entry and operator-facing CLI surface | preserve via wrapper or compatible import path |
| `audiagentic.lifecycle.*` | install/update/cutover and baseline lifecycle surface | preserve one checkpoint via shim |
| `audiagentic.release.*` | release/bootstrap/audit workflow surface | preserve one checkpoint via shim |
| `audiagentic.jobs.*` | current execution-oriented import surface used by CLI and docs | preserve one checkpoint via shim |
| `audiagentic.providers.*` | current provider integration surface | preserve one checkpoint via shim |
| `audiagentic.server.*` | optional server-facing surface | preserve one checkpoint via shim |
| `audiagentic.overlay.discord.*` | current Discord overlay/channel import surface | preserve one checkpoint via shim |
| `tools/*` module entrypoints | deterministic wrappers used directly | keep stable as visible entrypoints |
| `docs/schemas/*` | schema validation inputs | no relocation in this tranche |
| `docs/examples/*` | examples cited as stable | no relocation in this tranche |
| `.github/workflows/*` references | CI/CD and managed baseline resolution | path-sensitive; must remain valid |
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules*`, `.claude/`, `.agents/skills/` | provider instruction assets | path-sensitive; must remain valid |

## Internal-only candidates

These are likely internal-only and may be rewritten directly during `PKT-FND-012` unless later inventory finds tracked external references:

- deep module imports within `jobs/*`
- deep module imports within `providers/*`
- implementation helpers under new domain roots once introduced
- test-only imports

## Notes for PKT-FND-011

- public roots above should map to forwarding/re-export shims during the checkpoint
- no new code may be added against those legacy roots once `PKT-FND-012` begins
- internal-only imports should be rewritten rather than shimmed
