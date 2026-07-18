# providers/adapters/opencode/

OpenCode provider adapter.

Owns OpenCode-specific descriptor, execution bridge, language-server helpers, and managed surface content. Use this area for OpenCode runtime contract differences only.

## Vendor key injection mechanism (verified v1.17.18)

**Standard env var injection is NOT supported.** OpenCode requires its own credential flow:
`opencode providers login -p <provider>` stores credentials in `~\.local\share\opencode\auth.json`.
Built-in credential vendors: OpenAI (OAuth), Anthropic (OAuth), Google (API key).
OpenRouter is not a listed credential provider — would require custom openai-compatible config entry.

For AG-driven model availability: user must login via the CLI; AG reads the resulting catalog
via `catalog.py::_fetch_opencode_catalog` (`opencode models --verbose`).
Env var probes (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`) confirmed rejected by v1.17.18.

## Capability matrix

Full provider × vendor support matrix and evidence: see [endpoints/provider-model-endpoints.md](../../../../../../docs/reference/PROVIDER_CAPABILITY_REFERENCE/endpoints/provider-model-endpoints.md#agent-provider--vendor-support-matrix)
OpenCode-specific evidence: [harnesses/profiles/opencode.md](../../../../../../docs/reference/PROVIDER_CAPABILITY_REFERENCE/harnesses/profiles/opencode.md)
