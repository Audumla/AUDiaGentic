# channels/vscode/

VS Code editor integration and operator surface.

## Purpose

Provides AUDiaGentic functionality as a VS Code extension/integration:
- Code editor commands and actions
- Inline AI assistance
- Integration with interoperability seams
- Operator-facing UI and feedback

## Status

**Scaffolding in progress** — detailed implementation deferred.

## Must not own

- Provider-native execution mechanics
- Protocol ownership
- Release logic
- Runtime persistence

## Allowed dependencies

- interoperability/* (provider and protocol seams)
- execution/jobs (for launching prompts)
- channels/cli (shared command infrastructure)

## Migration notes

- Introduced as scaffolding in Slice A (2026-04-12)
