# interoperability/protocols/streaming/

Live streaming protocol for capturing and normalizing real-time provider output.

## Purpose

Implements direct streaming of provider responses:
- Streaming sink abstractions
- Completion capture and normalization
- Stream event production
- Live output formatting

## Owns

- Streaming sinks (in-memory, console, log, normalized event)
- Completion dataclass and normalization
- Provider stream result handling
- Stream control protocol

## Key modules

- **sinks.py**: `StreamSink`, `NormalizedEventSink`, sink implementations
- **completion.py**: `ProviderCompletion`, normalization, validation
- **provider_streaming.py**: `StreamedCommandResult`, streaming command execution

## Must not own

- Protocol negotiation (handled by adapters)
- Release logic
- Job state management

## Migration notes

- Moved from top-level `streaming/` (2026-04-12)
- Part of interoperability/protocols layer
