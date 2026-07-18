# providers/adapters/codex/

Codex provider adapter.

Owns Codex-specific descriptor, execution bridge, MCP-format translation, language-server integration helpers, and managed surface content. This area handles Codex runtime quirks that other providers do not share.

## Vendor key injection mechanism (verified v0.87.0)

**OpenAI: native vendor account via `codex login` — no key injection.** Other vendors require `[model_providers]` entries in config with `base_url`, `env_key` (env var reference), and `wire_api` compatibility flag. Config override via `-c 'model_providers.<id>.key="value"'` is accepted, confirming the PATH exists. However: wire API compatibility with Anthropic/Gemini endpoints NOT verified, project-scope `.codex/config.toml` precedence over global NOT verified, authenticated execution against non-OpenAI vendors NOT tested. Two config surfaces: user-global `~/.codex/config.toml` (primary authority) and project-local `.codex/config.toml` (managed by repo for MCP/LSP). Selectable granularity via provider tables.

## Capability matrix

Full provider × vendor support matrix: see [endpoints/provider-model-endpoints.md](../../../../../../docs/reference/PROVIDER_CAPABILITY_REFERENCE/endpoints/provider-model-endpoints.md#agent-provider--vendor-support-matrix)
Codex-specific evidence: [harnesses/profiles/codex.md](../../../../../../docs/reference/PROVIDER_CAPABILITY_REFERENCE/harnesses/profiles/codex.md)
