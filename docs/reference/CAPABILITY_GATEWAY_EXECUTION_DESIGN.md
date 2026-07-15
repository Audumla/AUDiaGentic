# Provider execution boundary

**Authority:** MA17. Provider automation is defined separately in
[Provider API contract](CAPABILITY_OPERATION_SCHEMA.md).

Agents call one provider-owned execution entry through `providers_api` with
project root, provider id, selected model id or alias, and provider-neutral
packet data. Providers check enablement, load provider configuration, resolve
the model, and invoke an explicitly composed execution adapter.

Agents retain profile selection, retry and fallback policy, cancellation,
correlation, and timeline persistence. Provider facts never select execution.
Execution has no automation mode, ownership scope, recipe, or catalog lookup.

Foundation retains only independently domain-neutral execution primitives. It
does not expose a provider facade or capability gateway.
