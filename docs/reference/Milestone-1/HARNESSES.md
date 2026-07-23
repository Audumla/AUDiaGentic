# Harness Surface Guidance

## Evidence axes

For every surface keep these separate:

- **declared candidate** — documentation or source indicates a possible route;
- **validation state** — exact version/platform/mode probe status;
- **effective production level** — what runtime may actually publish or execute.

Documentation can create a probe task. It cannot enable lifecycle evidence, content streaming, attach/resume, or controls.

## Pi

### Pi native RPC

Primary deep-control candidate. Use `pi --mode rpc --no-session` with strict LF-delimited JSONL, private codec/process handling, explicit request correlation, managed isolated HOME/config/session paths, and deterministic shutdown. Validate exact event/control behavior from installed source and transcript fixtures.

### Pi ACP

Independent optional surface. Never inherit RPC controls, correlation, status, content, or resume capability. Select it explicitly through `AS29` configuration and validate it independently.

### Pi hooks/plugins

Observation-only. Use only for correlated capability evidence that RPC/ACP does not already provide, such as compaction/retry details. They never become transport owners or external control channels.

## OpenCode

`AS55` owns the first OpenCode ACP vertical slice. Reuse the provider-local ACP launch builder and private ACP adapter. OpenCode native server/CLI/plugin routes are separate surfaces and require their own probes. ACP resume and CLI `run --session` must never be treated as one fallback identity route.

## Codex

`AS50` owns Codex ACP through the managed `codex-acp` bridge and exact model fidelity. `AS51` owns Codex App Server external/live attachment and gateway/TUI sharing. CLI, ACP, App Server, extension, and provider thread identities are independent until proven.

## Claude

Model Claude ACP and Claude CLI hooks separately. Hooks such as `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, and `SessionEnd` remain candidates until project-scoped config lifecycle, payload, correlation, non-vetoing behavior, and reload semantics are probed.

## Gemini

Treat Gemini ACP and CLI hooks separately. Candidate hook events include `BeforeAgent`, `BeforeModel`, `AfterModel`, `BeforeTool`, `AfterTool`, `AfterAgent`, and `SessionEnd`, but no hook/config write is allowed before exact-version proof.

## Other candidates

Qwen ACP, Cline ACP/SDK, Goose ACP/API, Copilot ACP, Kilo ACP, OpenHands WebSocket/API, Continue structured one-shot output, and other surfaces follow `AS54` and `AS46`. Aider, Plandex, Roo, terminal UI scraping, and similar unresolved routes remain process-only/O0 when locally owned and otherwise unsupported.

## Admission checklist

A production surface requires:

- explicit provider/surface ID and exact version/platform evidence;
- one registered authoritative transport;
- identity and `AS30` mapping semantics;
- declared controls with typed unsupported behavior;
- lifecycle source, ordering, correlation, freshness, and redaction rules;
- content channels and bounds, or an explicit empty content set;
- ownership/isolation/cleanup behavior;
- transcript/unit/integration tests;
- direct Windows evidence where supported and Linux Docker evidence for Linux promotion;
- no provider-specific branch in agents/gateway code.
