# components/providers/protocols/

## Purpose
Communication protocols used to interact with external systems. Each protocol subdomain owns a distinct transport or exchange mechanism.

## Ownership
- Protocol-level abstractions for external system communication
- Streaming protocol implementation (`streaming/`)

## Must NOT Own
- Provider-specific business logic (→ `interoperability/providers/`)
- Job orchestration (→ `execution/`)
- Durable state (→ `runtime/state/`)

## Allowed Dependencies
- `foundation/contracts` — canonical types and errors
- `execution` — for streaming adapters that bridge to job execution

## Subdomains

### streaming/
Generic streaming primitives shared across all provider adapters.
- Sinks: `NormalizedEventSink`, `InMemorySink`, `ConsoleSink`, `RawLogSink`
- Command execution: `run_streaming_command()`
- Result normalization: `ProviderCompletion`

ACP client framing is provider-neutral and lives in `foundation/execution/`.
Provider adapters may declare only provider-specific ACP launch/config details.

## Related Domains
- `interoperability/providers` — adapters use streaming/ sinks
- `execution/jobs` — packet_runner uses streaming primitives
