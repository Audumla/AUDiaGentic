# LSP MCP Enhancement Plan

## Goal

Make `coding-lsp` the provider-neutral code intelligence layer for agents that
do not have strong native LSP support, while preserving native provider LSP when
it is better integrated.

The enhanced layer should give agents precise navigation, diagnostics, linting,
format previews, safe refactor previews, and post-edit feedback without relying
on ad hoc shell commands or provider-specific behavior.

## Current AUDiaGentic LSP Surface

`ag-lsp` currently exposes:

| Function | MCP tool | Current status | Gap |
|---|---|---|---|
| Workspace symbol search | `lsp_symbols` | Present | No ranking/limit metadata beyond server response |
| Document outline | `lsp_doc_symbols` | Present | No tree normalization across servers |
| Go to definition | `lsp_definition` | Present | No type definition / implementation |
| Hover/type info | `lsp_hover` | Present | Raw server payload |
| Find references | `lsp_references` | Present | No include/exclude generated/vendor filters |
| Diagnostics | `lsp_diagnostics` | Present | Uses `workspace/diagnostic`; no `publishDiagnostics` cache |
| Rename preview | `lsp_rename_preview` | Present | Preview only; no apply workflow |

`ag-lsp-mgmt` currently exposes:

| Function | MCP tool | Current status | Gap |
|---|---|---|---|
| Config status | `lsp_config_status` | Present | Does not show provider routing outcome |
| List server implementations | `lsp_list_implementations` | Present | No capability metadata per implementation |
| Select server implementation | `lsp_select_implementation` | Present | OK |
| Enable language | `lsp_add_language` | Present | Name is add, behavior is enable + install |
| Remove language | `lsp_remove_language` | Present | OK |
| Set language option | `lsp_set_language_option` | Present | No schema/validation surfaced for keys |
| Reset language option | `lsp_reset_language_option` | Present | OK |
| List supported languages | `lsp_list_languages` | Present | No capability matrix per language/server |
| List missing binaries | `lsp_list_missing` | Present | OK |
| Install dependencies | `lsp_install_dependencies` | Present | Needs clearer approval model per toolchain |

Supported language specs today:

| Language | Server | Dependency | Notes |
|---|---|---|---|
| Python | `pyright-langserver --stdio` | `pyright` via `uv` | Type diagnostics; not Ruff lint |
| TypeScript/JavaScript | `typescript-language-server --stdio` | `typescript-language-server`, `typescript` via npm | TS diagnostics; not ESLint |
| Rust | `rust-analyzer` | `rust-analyzer` via rustup | Needs `cargo check`/Clippy layer |
| C/C++ | `clangd` | `clangd` via OS package manager | Needs clang-tidy optional layer |

## Provider Capability Mapping

Based on local provider descriptors.

| Provider | MCP capable | AUDiaGentic LSP routing today | Native/provider LSP path | Recommended final routing |
|---|---:|---|---|---|
| `aider` | No | None | No descriptor-native LSP | No LSP until provider gains MCP/native config |
| `claude` | Yes | Gets generic `ag-lsp` | No native LSP config in descriptor | Use enhanced `ag-lsp` |
| `cline` | Yes | Gets generic `ag-lsp` | No native LSP config in descriptor | Use enhanced `ag-lsp` |
| `codex` | Yes | Native language server config, no generic `ag-lsp` | `.codex/config.toml` `language_servers` | Prefer enhanced `ag-lsp` unless Codex native proves better exposed to agent |
| `continue` | Yes | Gets generic `ag-lsp` | No native LSP config in descriptor | Use enhanced `ag-lsp` |
| `copilot` | Yes | Gets generic `ag-lsp` | No native LSP config in descriptor | Use enhanced `ag-lsp` |
| `gemini` | Yes | Gets generic `ag-lsp` | No native LSP config in descriptor | Use enhanced `ag-lsp` |
| `goose` | Yes | Gets generic `ag-lsp` | No native LSP config in descriptor | Use enhanced `ag-lsp` |
| `local-openai` | No | None | No descriptor-native LSP | No LSP unless MCP support added |
| `opencode` | Yes | Native language server config, no generic `ag-lsp` | `.opencode/opencode.json` `lsp` | Native for v1; revisit hybrid after explicit diagnostic/tooling gap validation |
| `openhands` | No | None | No descriptor-native LSP | No LSP until provider gains MCP/native config |
| `pi` | Yes | `on_lsp_enabled` installs `pi-lens`, no generic `ag-lsp` | `pi-lens` extension auto-discovers servers | Use `pi-lens`; keep enhanced `ag-lsp` optional only for parity tests |
| `plandex` | No | None | No descriptor-native LSP | No LSP until provider gains MCP/native config |
| `qwen` | Yes | Native language server config, no generic `ag-lsp` | `.lsp.json` | Native by default; fallback/enhanced `ag-lsp` if experimental/native path is weak |
| `roo` | Yes | Gets generic `ag-lsp` | No native LSP config in descriptor | Use enhanced `ag-lsp` |

## Functional Mapping

| Capability | Current `ag-lsp` | OpenCode native | Codex native config | Qwen native | Pi `pi-lens` | Enhanced target |
|---|---:|---:|---:|---:|---:|---:|
| Workspace symbols | Yes | Likely | Unknown agent exposure | Yes | Yes | Yes, normalized |
| Document symbols | Yes | Likely | Unknown agent exposure | Yes | Yes | Yes, normalized |
| Definition | Yes | Yes | Unknown agent exposure | Yes | Yes | Yes |
| Hover/type info | Yes | Yes | Unknown agent exposure | Yes | Yes | Yes |
| References | Yes | Yes | Unknown agent exposure | Yes | Yes | Yes |
| Workspace diagnostics | Partial | Yes | Unknown agent exposure | Yes | Yes | Yes |
| File diagnostics after edit | No | Provider-dependent | Unknown | Yes | Yes | Yes |
| Cached publish diagnostics | No | Provider-dependent | Unknown | Yes | Yes | Yes |
| Completion | No | Yes | Unknown | Yes | Yes | Yes |
| Signature help | No | Likely | Unknown | Yes | Likely | Yes |
| Code actions / quick fixes | No | Partial/unknown | Unknown | Yes | Yes | Yes preview |
| Apply code action | No | Provider-dependent | Unknown | Unknown | Yes | Preview first, apply only explicit |
| Formatting | No | OpenCode has formatter config | Unknown | Unknown | Yes | Preview + optional apply |
| Organize imports | No | Via code actions/formatter | Unknown | Unknown | Yes | Preview + optional apply |
| Rename preview | Yes | Likely | Unknown | Yes | Yes | Yes, normalized |
| Rename apply | No | Provider-dependent | Unknown | Unknown | Maybe | Apply only explicit |
| Type definition | No | Likely | Unknown | Yes | Yes | Yes |
| Implementation | No | Likely | Unknown | Yes | Yes | Yes |
| Call hierarchy | No | Unknown | Unknown | Yes | Maybe | Yes where server supports |
| Ruff/ESLint/Clippy lint | No | Formatter/linter config varies | No | No | Yes | Yes |
| Secret scan | No | No | No | No | Yes | Optional separate tool |
| Tree-sitter fallback | No | No | No | No | Yes | Later optional fallback |

## Design Principles

- Provider-neutral first: expose one stable MCP contract to agents.
- Native when stronger: do not remove provider-native LSP for Pi/OpenCode/Qwen.
- Explicit over ambient: agents should call tools for diagnostics/navigation instead
  of guessing shell commands.
- Preview before mutation: code actions, formatting, rename, organize imports should
  return a patch preview before applying.
- Changed-file feedback first: after edits, prefer changed-file diagnostics over
  noisy workspace-wide scans.
- Capability-aware: every tool should report unsupported server capability clearly.
- Safe command execution: language server/linter commands must come from trusted
  specs or project config, not arbitrary tool arguments.
- Bounded latency: file-level tools should return quickly enough for agent edit
  loops; slow workspace scans must be explicit.
- Recoverable sessions: hung or crashed language servers should be restarted or
  reported as degraded without poisoning later tool calls.

## V1 Scope Boundaries

In scope for `coding-lsp` v1:

- LSP transport hardening.
- File and changed-file diagnostics.
- Capability discovery.
- Existing navigation tools plus high-value missing navigation primitives.
- Preview-only code actions/formatting if protocol support is stable enough.

Deferred from `coding-lsp` v1:

- Inlay hints.
- Tree-sitter fallback.
- Secret scanning.
- Whole-project quality suites beyond LSP diagnostics.
- Automatic apply for code actions, formatting, or rename edits.
- **Agent skills (workflow recipes such as `code-intelligence`, `safe-refactor`,
  `post-edit-verify`).** Skills are bounded by the MCP capability surface — they
  cannot add coverage the server lacks, only orchestrate it. Usage reliability is
  better and more universally fixed by MCP tool ergonomics (descriptions, position
  format, severity semantics; see Phase 2) than by opt-in skill prose. Build the MCP
  surface + ergonomics first; revisit a thin skill layer only after v1 ships and a
  measured usage gap remains. See "Skills vs MCP coverage boundary" in Decisions.

Linting and non-LSP quality checks should move to a separate `coding-quality`
component plan. `coding-lsp` can consume or merge diagnostics from that component
later, but should not own arbitrary linter process orchestration in v1.

## Proposed Enhanced MCP Tools

### Diagnostics

| Tool | Purpose |
|---|---|
| `lsp_file_diagnostics(file, min_severity=4, timeout_ms=5000)` | Open/sync one file, wait until `publishDiagnostics` arrives for that uri/version (event, not fixed sleep), return cached result |
| `lsp_changed_diagnostics(files, min_severity=4, limit=50)` | Batch diagnostics for changed files |
| `lsp_workspace_diagnostics(root='.', min_severity=4, limit=200)` | Rename current `lsp_diagnostics` behavior or keep alias |
| `lsp_diagnostic_sources(root='.')` | Show active LSP/linter sources and availability |

Implementation notes:
- Extend `LspJsonRpc` to dispatch notifications (Phase 0 infra).
- Cache `textDocument/publishDiagnostics` by `(uri, version)` in `LspSession`.
  Many servers (pyright) omit `version` in publish; fall back to stamping the
  cache with the last `did_change` version and accept the next publish for that
  uri as current.
- Keep `workspace/diagnostic` as fallback for servers that support it.
- Normalize diagnostics into `{source, severity, code, message, file, range, related}`.

### Navigation

| Tool | Purpose |
|---|---|
| `lsp_type_definition(file, position)` | Type definition lookup |
| `lsp_implementation(file, position)` | Implementation lookup |
| `lsp_call_hierarchy(file, position, direction='incoming|outgoing')` | Call hierarchy |
| `lsp_symbol_context(file, position)` | Combined hover + definition + references summary |

Implementation notes:
- Reuse `_open_file_session`.
- Add server capability checks before request.
- Normalize locations to repo-relative paths where possible.

### Editing And Refactor Preview

| Tool | Purpose |
|---|---|
| `lsp_code_actions(file, range=None, diagnostics=None, only=None)` | List code actions |
| `lsp_code_action_preview(file, action_id)` | Return patch/workspace edit preview |
| `lsp_format_preview(file)` | Return formatting patch |
| `lsp_organize_imports_preview(file)` | Return import cleanup patch |
| `lsp_rename_preview(file, position, new_name)` | Existing tool, normalize output |
| `lsp_apply_workspace_edit(edit_id)` | Optional later phase; explicit only |

Implementation notes:
- Store short-lived edit/action previews in process memory.
- Never auto-apply in first release.
- Convert `WorkspaceEdit` to unified patch format.

### Completion And Assistance

| Tool | Purpose |
|---|---|
| `lsp_completion(file, position, limit=20)` | Completion candidates |
| `lsp_signature_help(file, position)` | Function signature help |
| `lsp_inlay_hints(file, range=None)` | Optional if server supports |

Implementation notes:
- These are lower priority than diagnostics/code actions for coding agents.
- Useful for generated code validation and API discovery.

### Lint And Tooling Layer

These tools are **not part of `coding-lsp`** — they belong to the deferred
`coding-quality` component (see V1 Scope Boundaries and Phase 5) and are listed
here only to fix the contract before that plan exists. Note `format_file_preview`
(non-LSP formatter) overlaps `lsp_format_preview` (LSP `textDocument/formatting`);
keep the names distinct or pick one path per language so agents are not offered
two formatters.

| Tool | Purpose |
|---|---|
| `lint_file(file)` | Run configured linter(s) for one file |
| `lint_changed(files)` | Run configured linters on changed files |
| `lint_workspace(root='.', limit=200)` | Project-level lint/check |
| `format_file_preview(file)` | Non-LSP formatter fallback |

Initial lint sources:

| Language | Sources |
|---|---|
| Python | Pyright LSP, Ruff, optional mypy |
| TypeScript/JavaScript | TypeScript LSP, ESLint, optional Biome |
| Rust | rust-analyzer LSP, `cargo check`, Clippy |
| C/C++ | clangd LSP, optional clang-tidy |

Implementation notes:
- Move this layer to a separate `coding-quality` component unless explicitly
  accepted as part of `coding-lsp` v2.
- If implemented, linter command specs should live beside language specs or in
  `config/components/optional/coding-quality/<language>.yaml`, with explicit
  version/update policy.
- Detection should be project-aware: use tool only if config exists or user enables it.
- Output same normalized diagnostic schema as LSP.

## Agent Workflows

Intended usage of the tool surface, expressed as the processes an agent runs. This
documents the contract, validates per-phase tool coverage, and is the spec for the
deferred skill layer (see V1 Scope Boundaries) — it does **not** imply building skills
in v1. Composite-tool vs skill placement is noted per workflow.

Contract note for changed-file workflows: the **caller supplies the changed-file
list** (from git status or job context). `coding-lsp` does not own a source of truth
for "what changed" and must not branch on git state.

| # | Workflow | Tool sequence | Placement | Capability dep |
|---|---|---|---|---|
| 1 | Orient before editing a symbol | `lsp_symbols` → `lsp_symbol_context` (hover+def+refs) | Composite tool | base |
| 2 | Post-edit verification loop | edit → `lsp_changed_diagnostics(files)` → fix → repeat | Agent loop / Phase 7 helper | base |
| 3 | Safe rename | `lsp_references` → `lsp_rename_preview` → review → `lsp_apply_workspace_edit` → `lsp_changed_diagnostics` | Skill (branches on blast radius) | rename |
| 4 | Diagnose → quick-fix | `lsp_file_diagnostics` → `lsp_code_actions` → `lsp_code_action_preview` → apply → re-diagnose | Skill | codeAction |
| 5 | Explore unfamiliar code | `lsp_doc_symbols` → `lsp_definition`/`lsp_type_definition`/`lsp_implementation` → `lsp_call_hierarchy` | Agent ad hoc | typeDefinition, implementation, callHierarchy |
| 6 | Pre-commit / changed-file gate | `lsp_changed_diagnostics(git_changed, min_severity=2)` → `lsp_format_preview`/`lsp_organize_imports_preview` → apply → commit | Skill (LSP+git, cross-domain) | formatting |
| 7 | Capability probe (defensive prelude) | `lsp_capabilities(file)` before workflows 4–6 | Agent ad hoc | base |

Workflow details:

- **1 — Orient.** Turn a symbol *name* into a *position*, then summarize it. The
  name→position step is the recurring friction; `lsp_symbol_context` collapses the
  three follow-up calls into one (the only sequence that earns being a composite tool:
  always-together, no branching).
- **2 — Post-edit loop.** The core agent edit loop. Replaces "run linter in a shell and
  grep." Server-side it depends on the Phase 1 disk→buffer re-sync + version-correlated
  publish; the agent just passes the edited-file list. Phase 7 wires this in
  automatically after job edits.
- **3 — Safe rename.** Preview before apply is mandatory; apply is explicit-only.
  Branches on site count → canonical skill candidate, not a composite tool.
- **4 — Diagnose→fix.** Uses server-suggested fixes instead of hand-rolled edits.
  Returns empty unless the `codeAction` client capability is declared in initialize
  (Phase 0 prerequisite).
- **5 — Explore.** Navigation without grep guessing. The extra navigation tools each
  need their capability declared and checked (`lsp_capabilities`); not every server
  supports call hierarchy.
- **6 — Pre-commit gate.** Cross-domain (LSP + git + commit) → skill, deferred.
- **7 — Capability probe.** Cheap insurance before capability-gated workflows so the
  agent does not call tools that error on this server.

Coverage read-out: workflows 1, 2, 5 map cleanly onto base/Phase-1 tools; 3, 4, 6 are
silently broken unless Phase 0 declares the matching client capabilities — reinforcing
that capability declaration is a prerequisite, not an enhancement.

## Provider Routing Policy

Add a policy layer instead of hard-coded native-vs-MCP split.

Suggested config:

```yaml
coding-lsp:
  provider-routing:
    default: enhanced-mcp
    providers:
      pi: native
      opencode: hybrid
      qwen: native-with-mcp-fallback
      codex: enhanced-mcp
```

Routing modes:

| Mode | Behavior |
|---|---|
| `native` | Sync native provider LSP only; no `ag-lsp` |
| `enhanced-mcp` | Propagate `ag-lsp`/`ag-lsp-mgmt` only |
| `hybrid` | Sync native LSP and propagate `ag-lsp` for explicit tools |
| `native-with-mcp-fallback` | Native by default; add `ag-lsp` if native unavailable/disabled |
| `none` | No LSP propagation |

Recommended defaults:

| Provider | Default |
|---|---|
| `pi` | `native` |
| `opencode` | `native` for v1; `hybrid` only after explicit diagnostic/tooling gap validation |
| `qwen` | `native-with-mcp-fallback` |
| `codex` | `enhanced-mcp` |
| `claude`, `cline`, `continue`, `copilot`, `gemini`, `goose`, `roo` | `enhanced-mcp` |
| `aider`, `local-openai`, `openhands`, `plandex` | `none` until MCP/native support exists |

## Execution Sequence

Every change from this plan, ordered by **dependency wave** rather than phase number —
later items assume earlier ones exist. Within a wave, items are independent and may be
parallelized. Each item lists files, steps, validation, and prerequisites. The phase
sections below remain the detailed reference; this is the build order.

Convention: land each wave as its own reviewable change with its tests green before
starting the next. Waves 0–4 complete Phase 0; do not start Wave 5 until Wave 0–4 ship.

### Wave 0 — Reader-loop message demux (unblocks everything)

The reader loop currently only routes responses (`id in _pending`); notifications and
server→client requests are dropped. Nothing downstream works until this is fixed.

- **W0.1 — Notification dispatch.**
  - Files: `lsp_bridge.py`.
  - Steps: in `_reader_loop`, branch on message shape — `id` present + in `_pending`
    → response (current path); `method` present + no `id` → notification → invoke a
    registered callback map keyed by method; neither → log + drop. Add
    `on_notification(method, handler)` registration.
  - Validate: fake server emits `textDocument/publishDiagnostics`; handler fires.
  - Depends: none.
- **W0.2 — Server→client request handling.**
  - Files: `lsp_bridge.py`.
  - Steps: `method` present + `id` present → inbound request. Reply to
    `workspace/configuration` (null/defaults per item) and `client/registerCapability`
    (ack/empty result); write a JSON-RPC response with the same `id`. Default-reply
    null + log for unknown server requests.
  - Validate: fake server issues `workspace/configuration`; bridge replies; server
    unblocks and proceeds to publish. This is the pyright/tsserver stall fix.
  - Depends: W0.1 (shared demux branch).

### Wave 1 — Error model (one canonical type before errors multiply)

Do this before every later item starts raising errors, or the cleanup compounds.

- **W1.1 — Collapse `LspError`/`LspServerError` into `AudiaGenticError` (Std 8).**
  - Files: `lsp_bridge.py` (defs at :22,:37), plus `except LspError`/`LspServerError`
    sites in bridge `shutdown`, `lsp_session_manager.py`, `lsp_api.py`.
  - Steps: replace both subclasses with `AudiaGenticError(code=..., kind="coding-lsp",
    details=...)` (or a `make_error()` factory); preserve `EXT-LSP-001`/`002` payloads
    in `details`. Retarget call sites to catch `AudiaGenticError` + check `.code`
    **before** deleting the classes.
  - Validate: no subclass remains; Std 8 parallel-hierarchy grep clean; existing
    catch sites still function.
  - Depends: none (can run parallel to Wave 0, but must precede Wave 2+).
- **W1.2 — `EXT-LSP-NNN` code namespace + structured envelopes.**
  - Files: `lsp_bridge.py`/`lsp_lifecycle.py`, a code table doc-comment.
  - Steps: assign one code per envelope shape — timeout, unsupported-capability,
    crashed-server, invalid-position, file-not-found, no-configured-server. Build a
    single `_lsp_error(code, message, **details)` helper all sites use.
  - Validate: each failure path returns its code; table documented beside the bridge.
  - Depends: W1.1.

### Wave 2 — Request lifecycle & resilience

- **W2.1 — Per-request + method-specific timeouts.** Files: `lsp_bridge.py`. Replace the
  single 30s default with a method→timeout map and per-call override. Validate against
  the performance-budget table. Depends: W1.2 (timeout → envelope).
- **W2.2 — `$/cancelRequest` on timeout.** Files: `lsp_bridge.py`. On `event.wait`
  expiry, send `$/cancelRequest` with the request id before raising the timeout
  envelope. Validate: hung request cancels; later requests still succeed. Depends: W2.1.
- **W2.3 — In-flight tracking + clean fail on server exit.** Files: `lsp_bridge.py`.
  Already partially present (reader-loop except sets pending events); make it
  deterministic — on `_process` exit, fail all `_pending` with a crashed-server
  envelope. Validate: kill server mid-request → caller gets envelope, not a hang.
  Depends: W1.2.
- **W2.4 — stderr drain thread.** Files: `lsp_bridge.py`. Spawn a daemon thread reading
  `stderr` to `logger.debug`. Validate: chatty fake server does not wedge the request
  loop (fills-pipe regression test). Depends: none (independent; group here).
- **W2.5 — Server restart/recovery + stale-session invalidation.** Files:
  `lsp_lifecycle.py`, `lsp_session_manager.py`. Detect dead/wedged session; allow
  `get_or_create` to rebuild; invalidate when config changes or command disappears.
  Validate: crashed server → new session created on next call. Depends: W2.3.

### Wave 3 — Handshake correctness (prerequisites for later tool phases)

- **W3.1 — Expand declared client capabilities.** Files: `lsp_lifecycle.py`
  `_client_capabilities()` (:266). Declare `codeAction`, `completion`(+resolve),
  `signatureHelp`, `formatting`/`rangeFormatting`, `inlayHint`, `callHierarchy`,
  `typeDefinition`, `implementation`. Validate: capability smoke test asserts each is
  present. Depends: none. **Gates Phases 3/4/Completion — must land in Phase 0.**
- **W3.2 — Position encoding negotiation.** Files: `lsp_lifecycle.py`, shared helper.
  Advertise `general.positionEncodings`; read server choice; convert agent offsets in
  one helper used by all position tools; default UTF-16. Validate: definition/hover on
  a non-ASCII line resolves correctly. Depends: none.
- **W3.3 — Project-root marker resolution.** Files: `lsp_api.py` `resolve_project_root`/
  `_open_file_session`, per-language markers. Resolve to `Cargo.toml`/`tsconfig.json`/
  `compile_commands.json` dir, not cwd. Validate: nested file resolves to marker root.
  Depends: none.

### Wave 4 — Caching & observability (completes Phase 0)

- **W4.1 — Cache TTLs for diagnostics + capabilities.** Files: `lsp_lifecycle.py`.
  Validate: stale entries expire; survive no content change. Depends: W1.2.
- **W4.2 — Latency logging for all LSP requests.** Files: `lsp_bridge.py`. Wrap
  `send_request` with timing → `logger.debug` with method + ms. Depends: none.

### Wave 5 — Diagnostics v2 (Phase 1)

- **W5.1 — Capture `publishDiagnostics` into a per-(uri) cache.** Depends: W0.1.
- **W5.2 — Mandatory disk→buffer re-sync before every file-scoped query.** Single
  enforced path: re-read disk → `didChange` (bump version) → then query. Depends: W3.2
  (encoding), W3.3 (root).
- **W5.3 — Version-correlated publish wait** (`>=` sent version + settle window;
  pyright no-version fallback gates on last `did_change` stamp). Depends: W5.1, W5.2.
- **W5.4 — `file_diagnostics` + `changed_diagnostics` service APIs + MCP tools +
  normalized schema.** Caller supplies changed-file list. Depends: W5.3.
- **W5.5 — Fail loud:** replace `except Exception: return {}` (`lsp_lifecycle.py:216`)
  with the W1.2 envelope; keep `lsp_diagnostics` as compatibility alias. Depends: W1.2.

### Wave 6 — Capability discovery + tool ergonomics (Phase 2)

- **W6.1 — `lsp_capabilities(file_or_language)`** exposing stored initialize caps;
  add capability checks to all tools. Depends: W3.1.
- **W6.2 — Normalize** symbols, locations, hovers, workspace edits to shared schema.
  Depends: W5.4.
- **W6.3 — Tool ergonomics** (the agent-usability gate): docstrings on every tool;
  self-documenting `position` (or split to `line`/`character`); document `min_severity`;
  one result/error envelope; symbol→position note. Validate: no-docstring schema-lint;
  position round-trip has no off-by-one. Depends: W6.2 (shared envelope).

### Wave 7 — Feature phases (independent, capability-gated)

Order by value; each depends on its Wave 3 capability + Wave 6 normalization.

- **W7.1 — Navigation (Phase 3):** `lsp_type_definition`, `lsp_implementation`,
  `lsp_call_hierarchy`, `lsp_symbol_context`. Depends: W3.1, W6.2.
- **W7.2 — Code actions + format preview (Phase 4):** `lsp_code_actions`,
  `*_preview`, workspace-edit→patch (shared with rename), preview cache + TTL.
  Depends: W3.1, W4.1, W6.2.
- **W7.3 — Provider routing policy (Phase 6):** routing config + defaults, update
  `sync_generic_lsp_mcp_to_providers`, `hybrid` mode, Codex default. Depends: W5.4.
- **W7.4 — Agent feedback loop (Phase 7):** post-job changed-file diagnostics helper,
  bounded output. Depends: W5.4.
- **W7.5 — Coding-quality split (Phase 5):** separate component plan; lint/format tools
  leave `coding-lsp`. Depends: none (planning), but ship after W5.4 contract is stable.

Deferred (not scheduled in this sequence): completion/signature/inlay-hints, agent
skills, tree-sitter fallback, secret scan, auto-apply. See V1 Scope Boundaries.

### Critical path

W0.1 → W0.2 → W5.1 → W5.2 → W5.3 → W5.4 → (W6.x) → W7.x. The error model (W1.x) and
handshake (W3.x) are parallel tributaries that must merge before Wave 5/7 respectively.
Wave 2 resilience and Wave 4 observability are independent and can land any time after
their noted prerequisites.

## Implementation Phases

### Phase 0: LSP Infrastructure Hardening

Files:
- `src/audiagentic/components/optional/coding_lsp/lsp_bridge.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_lifecycle.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_session_manager.py`
- tests under `tests/unit/coding_lsp/`

Tasks:
- Add notification dispatch/callback support in `LspJsonRpc` (notifications have
  no `id`; currently dropped by the reader loop).
- Handle server→client **requests** (inbound message with both `id` and `method`).
  At minimum reply to `workspace/configuration` (return null/defaults per item)
  and `client/registerCapability` (ack). Pyright and typescript-language-server
  block on `workspace/configuration`; without a reply they stall and never
  publish diagnostics. This is a prerequisite for Phase 1, not optional.
- **Expand declared client capabilities to match the planned tool surface
  (prerequisite, not enhancement).** `lsp_lifecycle.py:266-281` `_client_capabilities()`
  declares only definition/hover/references/rename/documentSymbol/workspace-symbol +
  publishDiagnostics. Servers gate features on what the client advertises — pyright
  and typescript-language-server will return empty or refuse `codeAction`,
  `completion` (+ `completionItem.resolve`), `signatureHelp`, `formatting`/
  `rangeFormatting`, `inlayHint`, `callHierarchy`, `typeDefinition`, and
  `implementation` unless declared here. Add the matching `textDocument.*`
  capabilities now so Phases 3/4/Completion do not silently under-deliver and look
  like bugs. This is the same prerequisite class as the `workspace/configuration`
  reply above.
- **Negotiate position encoding (correctness, non-ASCII files).** LSP positions are
  UTF-16 code units by default; current tools pass `character` straight through, so
  any line with non-ASCII content yields off-by-N positions. Advertise
  `general.positionEncodings: ["utf-8","utf-16"]` in initialize, read the server's
  chosen `positionEncoding` from the result, and convert agent (codepoint/UTF-8)
  offsets to the negotiated encoding in one shared helper used by every
  position-taking tool. Default to UTF-16 when the server does not negotiate.
- **Resolve the real project root per language (correctness).** Sessions are keyed on
  the passed root/cwd, but `rust-analyzer`/`typescript-language-server`/`clangd` need
  the project-marker directory (`Cargo.toml`, `tsconfig.json`/`package.json`,
  `compile_commands.json`). Add marker-based root resolution per language; a wrong
  root yields empty or misconfigured results that look like missing capability.
- Send `$/cancelRequest` when a request times out so the server stops computing
  abandoned work during edit loops.
- Drain server `stderr` to the log on a thread. It is captured as a PIPE today
  but never read; a chatty server fills the OS pipe buffer, blocks on write, and
  presents as a hang.
- Add per-request default timeouts and method-specific timeout overrides.
- Track in-flight requests and fail them cleanly when server exits.
- Add server restart/recovery path for crashed or wedged sessions.
- Add stale-session invalidation when config changes or command disappears.
- Add cache TTLs for diagnostics and capabilities.
- Add structured error envelopes for timeout, unsupported capability, crashed server,
  invalid position, file not found, and no configured language server.
- **Collapse the parallel exception hierarchy (Standard 8 — prerequisite, not cleanup).**
  `lsp_bridge.py:22,37` defines `class LspError(AudiaGenticError)` and
  `class LspServerError(AudiaGenticError)`. `ARCHITECTURE_STANDARDS.md` §8 forbids
  this verbatim: *"No parallel hierarchies (`EventBusError`, `LspError`)."* The
  structured-error-envelope work above **must not** add more `LspError`-style
  subclasses on top of a construct the standard already prohibits. Replace both with
  direct `AudiaGenticError(code=..., kind="coding-lsp", details=...)` raises (or a
  thin `make_error()` factory), preserving the current `EXT-LSP-001` (server error
  code) / `EXT-LSP-002` (process death) payloads as `details`. Audit the ~6 `except
  LspError`/`except LspServerError` call sites (bridge `shutdown`, session manager,
  `lsp_api`) and retarget them to `AudiaGenticError` + code checks before deleting
  the subclasses. Do this in Phase 0 so every later phase raises one canonical type.
- **Canonical code namespace for the new envelopes.** Reserve the `EXT-LSP-NNN`
  range (already in use: `001` server error, `002` process death) and assign codes
  per envelope shape: timeout, unsupported-capability, crashed-server,
  invalid-position, file-not-found, no-configured-server. Document the table beside
  the bridge so later phases reuse codes instead of inventing strings.
- Add latency logging for all LSP requests.

Performance budgets:

| Operation class | Target | Hard timeout |
|---|---:|---:|
| File diagnostics | <= 1.5s typical | 5s |
| Hover/definition/references | <= 750ms typical | 3s |
| Workspace symbols | <= 2s typical | 8s |
| Workspace diagnostics | explicit only | 30s |
| Server initialize | <= 5s typical | 30s |

Acceptance:
- Fake JSON-RPC server can emit async `textDocument/publishDiagnostics`.
- Fake server can issue a `workspace/configuration` request and the bridge
  replies, unblocking the server.
- Hung request returns timeout error, emits `$/cancelRequest`, and later requests
  still work.
- Server stderr output is logged and does not wedge the request loop.
- Crashed server is detected and a new session can be created.
- Unsupported capability returns clear error envelope.
- Stale diagnostics expire by TTL and do not survive file content changes.
- Declared client capabilities cover every method a later phase calls; a capability
  smoke test asserts the initialize payload lists code-action/completion/
  signature-help/formatting/inlay-hint/call-hierarchy/type-definition/implementation.
- Position round-trip is correct on a non-ASCII line: a definition/hover request at a
  column past a multibyte character resolves to the right symbol under the negotiated
  encoding.
- Project root resolves to the marker directory (`tsconfig.json`/`Cargo.toml`/
  `compile_commands.json`) for a file nested below it, not the raw cwd.
- No `LspError`/`LspServerError` subclasses remain; all bridge/session failures raise
  `AudiaGenticError` with an `EXT-LSP-NNN` code, and existing `except` sites still
  catch them via the canonical type. Standard 8 parallel-hierarchy check passes.

### Phase 1: Diagnostics v2

Files:
- `src/audiagentic/components/optional/coding_lsp/lsp_bridge.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_lifecycle.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_api.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_mcp.py`
- tests under `tests/unit/coding_lsp/`

Tasks:
- Capture `textDocument/publishDiagnostics` (uses Phase 0 notification dispatch).
- **Mandatory disk→buffer re-sync before every file-scoped query (#1 source of wrong
  diagnostics).** Agents edit files on disk, but `sync_document` (`lsp_lifecycle.py:109`)
  holds an in-memory buffer and only re-sends on text mismatch. Every file diagnostic
  (and every position tool) must re-read current disk content, push it via
  `didChange` with a bumped version, and only then wait for the publish — otherwise
  the server answers from a stale buffer. Make this a single enforced path, not a
  per-caller convention.
- **Wait on a version-correlated publish, not "the next publish."** Servers emit
  publishes asynchronously and may send a stale-version publish after a new
  `didChange`, or multiple publishes per version. Wait for a publish whose version is
  `>=` the version just sent (with a short settle window); the pyright "omits version"
  fallback must still gate on the last `did_change` stamp, not blindly accept the next
  arrival.
- Add `file_diagnostics` and `changed_diagnostics` service APIs.
- Add MCP tools.
- Normalize diagnostic schema.
- **Make diagnostics fail loud, not empty.** `lsp_lifecycle.py:216`
  `except Exception: return {}` hides request failures as "no diagnostics" — an agent
  cannot tell a clean file from a broken request. Return the Phase 0 structured error
  envelope on failure; reserve empty result for genuinely clean files.
- Keep existing `lsp_diagnostics` as compatibility alias.

Acceptance:
- Pyright file diagnostics works after opening a Python file.
- TypeScript file diagnostics works after opening a TypeScript file.
- Editing a file on disk then calling file diagnostics returns results for the new
  content, not the previously synced buffer (disk re-sync + version bump verified).
- Unsupported server/method returns clear error envelope.
- File not covered by configured language server returns clear no-server error.
- A failed diagnostics request returns a structured error envelope, distinct from the
  empty result for a clean file.
- Workspace diagnostic fallback still works.
- Diagnostics are invalidated when file content changes.

### Phase 2: Capability Discovery And Normalization

Tasks:
- Expose stored initialize capabilities (already captured in `LspSession`) via
  `lsp_capabilities(file_or_language)`.
- Add capability checks for all existing tools.
- Normalize symbols, locations, hovers, workspace edits.
- **Tool ergonomics & discoverability (the "will an agent use it right" gap).** The
  current tools ship with no descriptions and opaque parameters; an agent cannot use
  them reliably from the schema alone. This is the deterministic, provider-neutral fix
  that must land before any skill layer is considered:
  1. **Docstrings on every MCP tool.** `lsp_mcp.py`/`lsp_manage_mcp.py` tools have no
     docstrings; FastMCP surfaces the docstring as the tool description. Add a clear
     one-liner + parameter notes to each so the schema is self-explanatory.
  2. **Self-documenting `position`.** `position: str` is parsed as `'line:col'`,
     **1-based** (`parse_position`, `lsp_api.py:45`), with none of that in the schema.
     Either document the format and base in the description, or change the signature to
     explicit `line: int, character: int` with the base stated. The opaque string is
     the worst option.
  3. **Document `min_severity` semantics.** `1=Error … 4=Hint` is explained only on an
     internal method; surface it in the tool description, or switch to a string enum
     (`"error"|"warning"|"info"|"hint"`).
  4. **One consistent result/error envelope.** Today success and the `{"error": ...}`
     path (`_open_file_session`, `lsp_api.py:145`) return different shapes; align them
     with the Phase 0/1 envelope so an agent can distinguish "no results" from "failed."
  5. **Symbol→position workflow note** in the `lsp_symbols`/navigation descriptions:
     find a symbol → take its location → feed to position-based tools.

Acceptance:
- Agent can ask what LSP can do for current file.
- Every MCP tool has a description and documented parameters; a schema-lint test
  asserts no tool ships without a docstring.
- `position` format and indexing are unambiguous from the tool schema alone (no
  off-by-one in an agent round-trip test).
- Success and error results share a documented envelope shape across all tools.
- Missing capability error includes server and requested method.

### Phase 3: Navigation Expansion

Tasks:
- Add type definition, implementation, call hierarchy.
- Add `lsp_symbol_context`.

Acceptance:
- Tools pass unit tests against mocked LSP responses.
- Pyright/rust-analyzer integration tests where available.

Scope note:
- Call hierarchy is optional for v1 and should be deferred if diagnostics and
  code action previews need the same implementation time.

### Phase 4: Code Actions And Format Preview

Tasks:
- Add code action request.
- Add formatting request.
- Add workspace edit to patch conversion.
- Add preview cache with TTL.

Acceptance:
- Tool returns patch preview.
- No tool mutates files by default.
- Workspace edit conversion is shared with rename preview.
- Timed-out or unsupported code-action requests return clear error envelope.

### Phase 5: Coding Quality Split

Tasks:
- Create separate `coding-quality` component plan.
- Define linter spec model and SSOT location.
- Define version/update policy for external tools.
- Define unified diagnostic schema shared with `coding-lsp`.
- Decide whether `coding-lsp` aggregates `coding-quality` diagnostics or agents
  call both components separately.

Acceptance:
- `coding-lsp` remains focused on LSP protocol operations.
- Linter execution is not added to `coding-lsp` without explicit follow-up plan.

### Phase 6: Provider Routing Policy

Tasks:
- Add routing config and defaults.
- Update `sync_generic_lsp_mcp_to_providers`.
- Add `hybrid` mode for OpenCode.
- Change Codex default to enhanced MCP unless native exposure is validated.

Acceptance:
- Provider sync report shows native/MCP/hybrid decision per provider.
- Existing provider surface tests updated.

### Phase 7: Agent Feedback Loop

Tasks:
- Add helper to run changed-file diagnostics after job edits.
- Keep output bounded.
- Integrate with provider execution result artifacts if appropriate.

Acceptance:
- After implementation jobs, final result can include concise diagnostics summary.
- No noisy whole-project scan by default.

## Test Strategy

- Unit-test LSP protocol request/response handling with fake JSON-RPC server.
- Fake server must support timed async notification injection for
  `textDocument/publishDiagnostics`.
- Unit-test notification diagnostics cache, TTL expiry, and invalidation on file changes.
- Unit-test normalization for diagnostics, symbols, workspace edits.
- Integration-test Pyright file diagnostics.
- Integration-test TypeScript file diagnostics.
- Provider sync tests for routing matrix.
- Windows tests for command argv/path handling.
- Regression tests for unsupported capability and server failure cases.
- Timeout/recovery tests for hung request and crashed server.

## Risks

- LSP servers differ widely; normalize but preserve raw payload under `raw`.
- Some servers do not support `workspace/diagnostic`; rely on publish cache.
- Linters can be slow; default to changed-file/file-level commands.
- Formatter/code-action apply can surprise users; keep preview-only first.
- Hybrid provider mode may duplicate context/tools; only enable where explicit tools add value.
- Servers that block on `workspace/configuration` will not publish diagnostics until
  answered; the bridge must reply to server-initiated requests, not just notifications.
- Fixed-delay diagnostic waits are racy on cold servers; wait on the publish event.
- Features silently absent if the corresponding client capability is undeclared in
  initialize; expand `_client_capabilities()` alongside each tool phase.
- Stale in-memory buffer vs on-disk edits yields wrong diagnostics; re-sync disk
  content with a version bump before every file-scoped query.
- UTF-16 position default mis-locates symbols on non-ASCII lines unless encoding is
  negotiated and offsets converted in one shared helper.
- Wrong project root (cwd instead of marker dir) yields empty results that mimic a
  missing-capability failure.

## Open Questions

- Should OpenCode receive hybrid `ag-lsp` by default after v1, or only with config opt-in?
- Should Codex native `language_servers` remain enabled if enhanced MCP becomes primary?
- Should lint dependencies install with language enablement in `coding-quality`, or require separate explicit enable?
- Should `coding-quality` aggregate into `coding-lsp` diagnostics, or remain separate MCP tools?

## Decisions From Review

- Add Phase 0 before Diagnostics v2 for transport, timeout, recovery, cache TTL,
  and async notification hardening.
- Keep OpenCode `native` for v1; revisit `hybrid` after validation shows explicit
  `ag-lsp` tools improve agent outcomes.
- Move linting/non-LSP tools to a separate `coding-quality` plan.
- Keep tree-sitter fallback, inlay hints, and secret scan out of `coding-lsp` v1.
- Expand Phase 1 acceptance beyond Pyright to include TypeScript and failure cases.
- Phase 0 must handle server→client requests (`workspace/configuration`,
  `client/registerCapability`), request cancellation (`$/cancelRequest`), and
  stderr draining — these are prerequisites for diagnostics, not enhancements.
- Replace fixed `wait_ms` diagnostic delay with event-driven wait keyed by
  `(uri, version)`.
- Lint/format tools (`lint_*`, `format_file_preview`) belong to `coding-quality`,
  not `coding-lsp`; listed in this plan only to fix the contract early.
- Phase 0 must collapse `LspError`/`LspServerError` into `AudiaGenticError` with
  `EXT-LSP-NNN` codes. These subclasses are the parallel exception hierarchy that
  `ARCHITECTURE_STANDARDS.md` §8 prohibits by name; the error-envelope work would
  otherwise expand a standards violation rather than fix it.
- Three correctness prerequisites added after design review of the current handshake
  and file-sync code — without them the layer ships subtly-wrong results: (1) expand
  declared client capabilities in initialize to match every planned tool (Phase 0);
  (2) mandatory disk→buffer re-sync with version bump before any file-scoped query
  (Phase 1); (3) negotiate/convert position encoding for non-ASCII files (Phase 0).
  Plus: diagnostics must fail loud (structured error) instead of returning empty, and
  project root must resolve to the language's marker directory, not cwd.
- **Skills vs MCP coverage boundary — skills deferred.** Capability coverage (what LSP
  operations are possible) is owned entirely by the MCP server; a skill has no
  transport to the language server and is strictly bounded by the MCP surface — it
  cannot add coverage, only orchestrate it (the alternative, shelling out, is the
  ad-hoc-shell anti-pattern this component exists to remove). Usage reliability (does
  the agent call tools correctly) is better fixed by MCP tool ergonomics — always
  present in the schema, deterministic, provider-neutral — than by opt-in skill prose
  that may not be loaded and that not every provider supports. Priority order locked:
  (1) MCP capability, (2) tool ergonomics (Phase 2), (3) skills last. Agent skills
  (`code-intelligence`, `safe-refactor`, `post-edit-verify`) are deferred to a
  post-v1 layer, to be reconsidered only if a measured usage gap remains after the
  ergonomics work lands.
