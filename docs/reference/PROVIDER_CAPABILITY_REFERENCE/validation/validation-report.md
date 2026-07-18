# Validation Report

Validated: 2026-07-17

## Structural validation

- All source documents were moved into the normalized domain structure.
- No duplicate legacy/original directory is present.
- Registry YAML parses successfully.
- JSON schemas parse successfully.
- Internal relative Markdown links were checked.
- Source-to-destination SHA-256 hashes are recorded in `migration-ledger.md`.

## Current primary-source validations

| Claim | Result |
|---|---|
| OpenRouter account credits endpoint | Verified: `/api/v1/credits`; management key required |
| OpenRouter current key allowance | Verified: `/api/v1/key` exposes limit, remaining and usage; embedded `rate_limit` is deprecated |
| OpenRouter request cost/token stats | Verified in normalized usage and generation statistics documentation |
| Gemini quota dimensions | Verified: project-scoped RPM, TPM and RPD; active limits shown in AI Studio; model/tier dependent |
| GitHub Copilot CLI ACP | Verified public preview; supports stdio and TCP ACP server modes |
| GitHub Copilot CLI MCP | Verified local/stdio/HTTP/SSE configuration and runtime management |
| OpenAI generic remaining prepaid balance | Not established; registry intentionally marks unavailable rather than inventing a value |
| Claude Pro/Max subscription allowance API | No supported public API established; kept separate from Anthropic API rate limits |

## Coverage limits

The package contains extensive provider/harness observations, but not every claim has been re-probed against an installed current binary. Such claims retain their existing wording and are represented as documented, observed, expected or open-validation items in the detailed references. The next validation phase should pin concrete harness versions and generate reproducible probe evidence.
