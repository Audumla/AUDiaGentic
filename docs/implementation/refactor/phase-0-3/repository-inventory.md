# Repository Inventory

## Scope

- checkpoint date: 2026-04-02
- owner: Phase 0.3 checkpoint
- packet: PKT-FND-010
- status: seeded working inventory

## Inventory Table

| Current path/root | Current purpose | Dominant responsibility | Secondary responsibility | Proposed target domain/path | Public import affected | Baseline/install impact | Notes |
|---|---|---|---|---|---|---|---|
| `src/audiagentic/contracts/*` | canonical contracts, errors, schemas, glossary helpers | contracts | validation | `src/audiagentic/contracts/*` | yes | yes | keep in place |
| `src/audiagentic/cli/*` | CLI entry and command routing | channels | tool wrapper orchestration | `src/audiagentic/channels/cli/*` | yes | yes | entrypoints should stay thin |
| `src/audiagentic/lifecycle/*` | install/update/cutover/baseline logic | runtime | baseline management | `src/audiagentic/runtime/lifecycle/*` | yes | yes | likely shimmed legacy root initially |
| `src/audiagentic/release/*` | release/audit/bootstrap logic | runtime | packaging/release workflow | `src/audiagentic/runtime/release/*` | yes | yes | keep nested under runtime in this tranche |
| `src/audiagentic/jobs/*` | job orchestration, prompt launch, reviews, state transitions | execution | runtime persistence coupling | `src/audiagentic/execution/jobs/*` | yes | yes | session input remains here; persistence helpers may later split |
| `src/audiagentic/providers/*` | provider adapters, selection, execution helpers | execution | streaming/progress coupling | `src/audiagentic/execution/providers/*` | yes | yes | move intact first |
| `src/audiagentic/server/*` | optional server surface | channels | integration surface | `src/audiagentic/channels/server/*` | yes | possible | keep thin |
| `src/audiagentic/overlay/discord/*` | Discord overlay/channel behavior | channels | collaboration surface | `src/audiagentic/channels/discord/*` | yes | yes | packet naming may still say discord |
| `tools/*` | deterministic utility entrypoints | tools/wrappers | internal library callers | `tools/*` wrappers + library logic under `src/audiagentic/*` | yes | yes | do not absorb tool entrypoints into package root |
| `tests/*` | centralized tests | tests | mirrors package structure | `tests/*` | no | yes | remap to new domains |
| `docs/schemas/*` | canonical schemas | contracts/docs | validation source | keep in place | yes | yes | ownership only, not relocation |
| `docs/examples/*` | canonical examples | docs/examples | onboarding/reference | keep in place | yes | yes | ownership only, not relocation |
| `.github/workflows/*` | workflow automation | baseline asset | CI/CD | keep in place | yes | yes | path-sensitive during baseline checks |
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules*`, `.claude/`, `.agents/skills/` | provider instruction assets | baseline asset | provider guidance | keep in place | yes | yes | path-sensitive during install/baseline sync |
| future `src/audiagentic/nodes/*` | reserved extension root | extension | later runtime/channel alignment | keep reserved root | no | no | not baseline prerequisite |
| future `src/audiagentic/discovery/*` | reserved extension root | extension | locator providers | keep reserved root | no | no | not baseline prerequisite |
| future `src/audiagentic/federation/*` | reserved extension root | extension | node events/control | keep reserved root | no | no | not baseline prerequisite |
| future `src/audiagentic/connectors/*` | reserved extension root | extension | external tool/task systems | keep reserved root | no | no | not baseline prerequisite |

## Baseline-sensitive areas

- `.audiagentic/runtime/**` path layout and exclusions
- `.github/workflows/*`
- provider instruction assets (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules*`, `.claude/`, `.agents/skills/`)
- `docs/schemas/*`
- `docs/examples/*`
- CLI entrypoints and tool wrappers

## Initial findings

- The dominant structural move is from legacy package roots (`lifecycle`, `release`, `jobs`, `providers`, `server`, `overlay/discord`) into repository domains (`runtime`, `execution`, `channels`).
- `session_input.py` remains an execution concern in the first pass, but output sinks/adapters should move under `streaming/`.
- The strongest later split candidates are low-level runtime persistence helpers such as `jobs/store.py` and the persistence half of `jobs/reviews.py`.
- `scoping/` should remain a prepared root in this tranche unless the inventory later reveals clearly separable scope/request/plan code.
