# channels/vscode/

VS Code editor integration and operator surface.

## Purpose

Provides AUDiaGentic functionality as a VS Code extension/integration:
- Code editor commands and actions
- Inline AI assistance
- Integration with interoperability seams
- Operator-facing UI and feedback

## Status

**Scaffold only. No executable code exists in this directory.**

This directory is reserved to establish VS Code as an explicit channel boundary. The `__init__.py` contains only a module docstring. No extension code, command handlers, or UI integration exists yet. Implementation is deferred until the CLI channel is stable and the interoperability seams it depends on are finalized.

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
