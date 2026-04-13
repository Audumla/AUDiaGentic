# interoperability/

External integrations: provider adapters, protocol implementations, and host bridges.

## Purpose

AUDiaGentic's integration layer with external systems:
- `providers/`: Provider-native adapters (Claude, Gemini, Cline, Codex, etc.)
- `protocols/`: Protocol implementations (streaming, ACP, etc.)
- `mcp/`: Model Context Protocol integration

## Owns

- Provider adapters and model selection logic
- Protocol implementations (streaming, ACP)
- MCP surfaces and integration
- Provider health checks, status, surfaces

## Must not own

- Job orchestration state machine
- Runtime state management
- Release logic
- Operator-facing channel semantics

## Allowed dependencies

- foundation/ (contracts, config)
- execution/ (orchestration calls, one-way from adapters to job launch)
- Other interoperability layers

## Anti-examples

```python
# WRONG: Interoperability should not import from execution jobs
# (except for cross-layer seams like gemini adapter launching jobs)

# WRONG: Interoperability should not own durable persistence
```

## Migration notes

- `providers/` moved from `execution/providers/` (2026-04-12)
- `protocols/streaming/` moved from top-level `streaming/` (2026-04-12)
