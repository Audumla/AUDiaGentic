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
| Enable language | `lsp_add_language` | Present | Name is add, behavior is enable + install |
| Remove language | `lsp_remove_language` | Present | OK |
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

Linting and non-LSP quality checks should move to a separate `coding-quality`
component plan. `coding-lsp` can consume or merge diagnostics from that component
later, but should not own arbitrary linter process orchestration in v1.

## Proposed Enhanced MCP Tools

### Diagnostics

| Tool | Purpose |
|---|---|
| `lsp_file_diagnostics(file, min_severity=4, wait_ms=750)` | Open/sync one file, wait for diagnostics, return cached `publishDiagnostics` |
| `lsp_changed_diagnostics(files, min_severity=4, limit=50)` | Batch diagnostics for changed files |
| `lsp_workspace_diagnostics(root='.', min_severity=4, limit=200)` | Rename current `lsp_diagnostics` behavior or keep alias |
| `lsp_diagnostic_sources(root='.')` | Show active LSP/linter sources and availability |

Implementation notes:
- Extend `LspJsonRpc` to dispatch notifications.
- Cache `textDocument/publishDiagnostics` by URI in `LspSession`.
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

## Implementation Phases

### Phase 0: LSP Infrastructure Hardening

Files:
- `src/audiagentic/components/optional/coding_lsp/lsp_bridge.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_lifecycle.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_session_manager.py`
- tests under `tests/unit/coding_lsp/`

Tasks:
- Add notification dispatch/callback support in `LspJsonRpc`.
- Add per-request default timeouts and method-specific timeout overrides.
- Track in-flight requests and fail them cleanly when server exits.
- Add server restart/recovery path for crashed or wedged sessions.
- Add stale-session invalidation when config changes or command disappears.
- Add cache TTLs for diagnostics and capabilities.
- Add structured error envelopes for timeout, unsupported capability, crashed server,
  invalid position, file not found, and no configured language server.
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
- Hung request returns timeout error and later requests still work.
- Crashed server is detected and a new session can be created.
- Unsupported capability returns clear error envelope.
- Stale diagnostics expire by TTL and do not survive file content changes.

### Phase 1: Diagnostics v2

Files:
- `src/audiagentic/components/optional/coding_lsp/lsp_bridge.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_lifecycle.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_api.py`
- `src/audiagentic/components/optional/coding_lsp/lsp_mcp.py`
- tests under `tests/unit/coding_lsp/`

Tasks:
- Add notification dispatch/callback support in `LspJsonRpc`.
- Capture `textDocument/publishDiagnostics`.
- Add `file_diagnostics` and `changed_diagnostics` service APIs.
- Add MCP tools.
- Normalize diagnostic schema.
- Keep existing `lsp_diagnostics` as compatibility alias.

Acceptance:
- Pyright file diagnostics works after opening a Python file.
- TypeScript file diagnostics works after opening a TypeScript file.
- Unsupported server/method returns clear error envelope.
- File not covered by configured language server returns clear no-server error.
- Workspace diagnostic fallback still works.
- Diagnostics are invalidated when file content changes.

### Phase 2: Capability Discovery And Normalization

Tasks:
- Store initialize capabilities per session.
- Add `lsp_capabilities(file_or_language)`.
- Add capability checks for all existing tools.
- Normalize symbols, locations, hovers, workspace edits.

Acceptance:
- Agent can ask what LSP can do for current file.
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
