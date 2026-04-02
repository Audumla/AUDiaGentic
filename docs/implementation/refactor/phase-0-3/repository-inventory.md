# Repository Inventory

## Scope

- checkpoint date: 2026-04-02
- owner: Phase 0.3 checkpoint
- packet: PKT-FND-010 through PKT-FND-013
- status: inventory frozen and validated against the completed code move

## Inventory Table

| Current path/root | Current purpose | Dominant responsibility | Secondary responsibility | Proposed target domain/path | Public import affected | Baseline/install impact | Notes |
|---|---|---|---|---|---|---|---|
| `src/audiagentic/contracts/*` | canonical contracts, errors, schemas, glossary helpers | contracts | validation | `src/audiagentic/contracts/*` | yes | yes | keep in place |
| `src/audiagentic/config/provider_config.py`, `src/audiagentic/config/provider_catalog.py`, `src/audiagentic/config/provider_registry.py` | stable provider configuration, catalog, and registry helpers | config | provider-facing validation helpers | keep under `src/audiagentic/config/*` | yes | yes | moved in slice `12B`; legacy `providers/*.py` files now forward here |
| `src/audiagentic/cli/*` | CLI entry and command routing | channels | tool wrapper orchestration | `src/audiagentic/channels/cli/*` | yes | yes | canonical CLI entrypoint moved; legacy shim remains for one checkpoint |
| `src/audiagentic/lifecycle/*` | install/update/cutover/baseline logic | runtime | baseline management | `src/audiagentic/runtime/lifecycle/*` | yes | yes | canonical modules moved; legacy root now forwards to `runtime/lifecycle/*` |
| `src/audiagentic/release/*` | release/audit/bootstrap logic | runtime | packaging/release workflow | `src/audiagentic/runtime/release/*` | yes | yes | canonical modules moved; legacy root now forwards to `runtime/release/*` |
| `src/audiagentic/jobs/*` | job orchestration, prompt launch, reviews, state transitions | execution | runtime persistence coupling | `src/audiagentic/execution/jobs/*` | yes | yes | canonical execution modules moved; persistence helpers still remain grouped here in first pass |
| `src/audiagentic/providers/*` | provider adapters, selection, execution helpers | execution | streaming/progress coupling | `src/audiagentic/execution/providers/*` | yes | yes | canonical provider execution modules moved; selected config helpers now live under `config/*` |
| `src/audiagentic/server/*` | optional server surface | channels | integration surface | `src/audiagentic/channels/server/*` | yes | possible | canonical server seam moved; legacy root remains thin |
| `src/audiagentic/overlay/discord/*` | Discord overlay/channel behavior | channels | collaboration surface | `src/audiagentic/channels/discord/*` | yes | yes | reserved compatibility root only in this tranche; packet naming may still say discord |
| `src/audiagentic/streaming/provider_streaming.py` | provider stdout/stderr tee and runtime stream helper | streaming | execution/provider bridge support | keep under `src/audiagentic/streaming/*` | yes | yes | moved from legacy `providers/streaming.py` with shim preserved |
| `.audiagentic/project.yaml`, `.audiagentic/components.yaml`, `.audiagentic/providers.yaml`, `.audiagentic/prompt-syntax.yaml`, `.audiagentic/prompts/*` | tracked installable baseline assets and prompt defaults | baseline asset | project configuration and prompt templates | keep in place | yes | yes | canonical install baseline; must remain syncable by Phase 1.4 |
| `.audiagentic/installed.json` | installed-state record | runtime state | lifecycle/reporting input | keep in place | yes | yes | generated/tracked state; not part of fresh baseline seed but path must remain valid |
| `.audiagentic/runtime/**` | runtime jobs, ledger fragments, and transient session artifacts | runtime state | local diagnostics | keep in place and remain excluded from install baseline | no | yes | exclusion is as important as the path itself |
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
- `.audiagentic/*.yaml` tracked baseline configuration and prompt template paths
- `.audiagentic/installed.json` path stability and lifecycle expectations
- `.github/workflows/*`
- provider instruction assets (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules*`, `.claude/`, `.agents/skills/`)
- `docs/schemas/*`
- `docs/examples/*`
- CLI entrypoints and tool wrappers

## Initial findings

- The dominant structural move from legacy package roots into repository domains is now complete for the current tranche: `lifecycle`/`release` -> `runtime`, `jobs`/provider execution -> `execution`, and CLI/server -> `channels`.
- Stable provider config/catalog/registry helpers are now living examples of the new `config/` domain, with compatibility shims preserved at the legacy `providers/*` roots.
- `session_input.py` remains an execution concern in the first pass, while lower-level stream adapters stay a later `streaming/` extraction follow-on.
- The strongest later split candidates are low-level runtime persistence helpers such as `jobs/store.py` and the persistence half of `jobs/reviews.py`.
- `scoping/` should remain a prepared root in this tranche unless the inventory later reveals clearly separable scope/request/plan code.
- `.audiagentic/` already contains both installable baseline assets and generated runtime state, so the refactor must preserve that distinction rather than treating the whole tree as one ownership class.
