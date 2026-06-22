---
id: lsp-plan-context
plan: plan-lsp-mcp-enhancement
type: reference
---

# LSP MCP Enhancement — Plan Context

This file holds plan-level reference material that applies across multiple items.
Read before working on any LSP item.

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
- Cache `textDocument/publishDiagnostics` by `(uri, version)` in `LspSession`. Many servers (pyright) omit `version` in publish; fall back to stamping the cache with the last `did_change` version and accept the next publish for that uri as current.
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

### Lint And Tooling Layer (NOT part of coding-lsp)

These tools belong to the deferred `coding-quality` component (see V1 Scope Boundaries and Phase 5). Listed here only to fix the contract before that plan exists.

| Tool | Purpose |
|---|---|
| `lint_file(file)` | Run configured linter(s) for one file |
| `lint_changed(files)` | Run configured linters on changed files |
| `lint_workspace(root='.', limit=200)` | Project-level lint/check |
| `format_file_preview(file)` | Non-LSP formatter fallback |

## Agent Workflows

Contract note: the **caller supplies the changed-file list** (from git status or job context). `coding-lsp` does not own a source of truth for "what changed" and must not branch on git state.

| # | Workflow | Tool sequence | Placement | Capability dep |
|---|---|---|---|---|
| 1 | Orient before editing a symbol | `lsp_symbols` → `lsp_symbol_context` (hover+def+refs) | Composite tool | base |
| 2 | Post-edit verification loop | edit → `lsp_changed_diagnostics(files)` → fix → repeat | Agent loop / Phase 7 helper | base |
| 3 | Safe rename | `lsp_references` → `lsp_rename_preview` → review → `lsp_apply_workspace_edit` → `lsp_changed_diagnostics` | Skill (branches on blast radius) | rename |
| 4 | Diagnose → quick-fix | `lsp_file_diagnostics` → `lsp_code_actions` → `lsp_code_action_preview` → apply → re-diagnose | Skill | codeAction |
| 5 | Explore unfamiliar code | `lsp_doc_symbols` → `lsp_definition`/`lsp_type_definition`/`lsp_implementation` → `lsp_call_hierarchy` | Agent ad hoc | typeDefinition, implementation, callHierarchy |
| 6 | Pre-commit / changed-file gate | `lsp_changed_diagnostics(git_changed, min_severity=2)` → `lsp_format_preview`/`lsp_organize_imports_preview` → apply → commit | Skill (LSP+git, cross-domain) | formatting |
| 7 | Capability probe (defensive prelude) | `lsp_capabilities(file)` before workflows 4–6 | Agent ad hoc | base |

Coverage read-out: workflows 1, 2, 5 map cleanly onto base/Phase-1 tools; 3, 4, 6 are silently broken unless Phase 0 declares the matching client capabilities — reinforcing that capability declaration is a prerequisite, not an enhancement.

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
- Agent skills (`code-intelligence`, `safe-refactor`, `post-edit-verify`).

## Test Strategy

- Unit-test LSP protocol request/response handling with fake JSON-RPC server.
- Fake server must support timed async notification injection for `textDocument/publishDiagnostics`.
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
- Servers that block on `workspace/configuration` will not publish diagnostics until answered; the bridge must reply to server-initiated requests, not just notifications.
- Fixed-delay diagnostic waits are racy on cold servers; wait on the publish event.
- Features silently absent if the corresponding client capability is undeclared in initialize; expand `_client_capabilities()` alongside each tool phase.
- Stale in-memory buffer vs on-disk edits yields wrong diagnostics; re-sync disk content with a version bump before every file-scoped query.
- UTF-16 position default mis-locates symbols on non-ASCII lines unless encoding is negotiated and offsets converted in one shared helper.
- Wrong project root (cwd instead of marker dir) yields empty results that mimic a missing-capability failure.

## Open Questions

- Should OpenCode receive hybrid `ag-lsp` by default after v1, or only with config opt-in?
- Should Codex native `language_servers` remain enabled if enhanced MCP becomes primary?
- Should lint dependencies install with language enablement in `coding-quality`, or require separate explicit enable?
- Should `coding-quality` aggregate into `coding-lsp` diagnostics, or remain separate MCP tools?

## Decisions From Review

- Add Phase 0 before Diagnostics v2 for transport, timeout, recovery, cache TTL, and async notification hardening.
- Keep OpenCode `native` for v1; revisit `hybrid` after validation shows explicit `ag-lsp` tools improve agent outcomes.
- Move linting/non-LSP tools to a separate `coding-quality` plan.
- Keep tree-sitter fallback, inlay hints, and secret scan out of `coding-lsp` v1.
- Expand Phase 1 acceptance beyond Pyright to include TypeScript and failure cases.
- Phase 0 must handle server→client requests (`workspace/configuration`, `client/registerCapability`), request cancellation (`$/cancelRequest`), and stderr draining — these are prerequisites for diagnostics, not enhancements.
- Replace fixed `wait_ms` diagnostic delay with event-driven wait keyed by `(uri, version)`.
- Lint/format tools (`lint_*`, `format_file_preview`) belong to `coding-quality`, not `coding-lsp`; listed in this plan only to fix the contract early.
- Phase 0 must collapse `LspError`/`LspServerError` into `AudiaGenticError` with `EXT-LSP-NNN` codes. These subclasses are the parallel exception hierarchy that `ARCHITECTURE_STANDARDS.md` §8 prohibits by name.
- Three correctness prerequisites added after design review of the current handshake and file-sync code — without them the layer ships subtly-wrong results: (1) expand declared client capabilities in initialize to match every planned tool (Phase 0); (2) mandatory disk→buffer re-sync with version bump before any file-scoped query (Phase 1); (3) negotiate/convert position encoding for non-ASCII files (Phase 0). Plus: diagnostics must fail loud (structured error) instead of returning empty, and project root must resolve to the language's marker directory, not cwd.
- **Skills vs MCP coverage boundary — skills deferred.** Capability coverage is owned entirely by the MCP server; a skill has no transport to the language server and is strictly bounded by the MCP surface. Usage reliability is better fixed by MCP tool ergonomics (Phase 2) than by opt-in skill prose. Priority order locked: (1) MCP capability, (2) tool ergonomics (Phase 2), (3) skills last.