# Gemini / Antigravity Provider — P1 Vendor Verification Evidence (updated)

<a name="gemini-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `gemini` |
| upstream-id | Google/gemini-cli (deprecated) → Google/antigravity (successor, v2.2.1) |
| tool-version | gemini CLI 0.49.0 installed; antigravity 2.2.1 installed via winget; antigravity CLI (`agy`) binary not in PATH — requires terminal restart |
| verified-at | 2026-07-13 UTC, 2026-07-16 UTC (upstream doc revalidation) |
| evidence-kind | installed-tool inspection (gemini `--help`, antigravity config surface at `~/.gemini/antigravity-cli/`), deprecation error from gemini runtime, antigravity bundled docs (`builtin/skills/antigravity_guide/references/cli.md`), upstream docs verification (docs.openhands.dev) |
| **correction-note** | **2026-07-16 revalidation**: Gemini CLI is now an ACP agent in OpenHands Agent Canvas via `npx -y @google/gemini-cli --acp`. Subscription login path uses `~/.gemini/oauth_creds.json`; API key fallback is `GEMINI_API_KEY`.

---

## Vendor: OpenAI

| Field | Value |
|---|---|
| **Sanitized source** | gemini CLI help shows no external vendor routing; antigravity settings at `~/.gemini/antigravity-cli/settings.json` contain only colorScheme, telemetry, permissions, trustedWorkspaces — no model/vendor config surface. Auth type is `"oauth-personal"` (Google account). Bundled docs reference Google-only features. |
| **Sanitized summary** | Neither gemini CLI nor antigravity supports external vendor routing. Both are native Google-only tools that use Google's own models through the user's Google account authentication. |
| **Support state** | not supported — native vendor (Google) only |

---

## Vendor: Anthropic

| Field | Value |
|---|---|
| **Sanitized source** | No Anthropic integration in gemini CLI help or antigravity config surface. |
| **Sanitized summary** | Anthropic models are not accessible through Gemini CLI or Antigravity. These are native Google-only tools. |
| **Support state** | not supported — native vendor (Google) only |

---

## Vendor: Google (Gemini)

| Field | Value |
|---|---|
| **Sanitized source** | gemini CLI v0.49.0 returns `IneligibleTierError` for free/individual tier with message "migrate to Antigravity". antigravity v2.2.1 installed; CLI binary is `agy` (not in current shell PATH). Auth: `"oauth-personal"` Google account login at `~/.gemini/settings.json`. Config surface: `~/.gemini/antigravity-cli/settings.json`. Bundled docs at `~/.gemini/antigravity-cli/builtin/skills/antigravity_guide/references/` confirm CLI-only model selection via `-m/--model` flag (same as gemini). |
| **Sanitized summary** | Google/Gemini models are the native vendor. Antigrativity is the active tool (gemini CLI deprecated for free tier). Authentication through Google OAuth personal account. Model selection via `-m <model-id>` on CLI or UI in IDE variant. `gemini gemma` subcommand available for local Gemma model routing via LiteRT-LM. No external vendor integration surface visible in config, help text, or bundled documentation. |
| **Support state** | verified native (Google account oauth-personal; antigravity v2.2.1 active, gemini CLI deprecated) |

---

## Vendor: OpenRouter

| Field | Value |
|---|---|
| **Sanitized source** | No external vendor routing in gemini CLI help or antigravity config surface. Bundled docs contain no OpenRouter references. |
| **Sanitized summary** | OpenRouter is not a supported vendor for Gemini CLI or Antigravity. Both are native Google-only tools with no multi-vendor model routing capability. |
| **Support state** | not supported — native vendor (Google) only |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `~/.gemini/settings.json` (shared gemini/antigravity settings with auth config); `~/.gemini/antigravity-cli/settings.json` (CLI-specific: colorScheme, permissions, trustedWorkspaces); `~/.gemini/antigravity/mcp_config.json` (IDE MCP servers) |
| **Key mechanism** | Google account OAuth login only (`oauth-personal`). No external vendor key injection surface. |
| **Model granularity** | Google model set determined by account tier entitlements. CLI `-m/--model` flag selects active model. No multi-vendor routing or custom endpoint configuration visible. |

---

## New upstream capabilities (verified 2026-07-16)

### ACP agent in OpenHands Agent Canvas

Gemini CLI is now an ACP agent in OpenHands Agent Canvas via `npx -y @google/gemini-cli --acp`. The free Google login path uses `~/.gemini/oauth_creds.json`; API key fallback is `GEMINI_API_KEY`. Subscription login takes priority over API key.

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | Native |
| **Registry ID** | `gemini` |
| **Launch command** | `npx @google/gemini-cli --acp` |
| **Distribution** | npx (npm) |

Gemini CLI natively implements ACP. Also runs as an ACP agent in OpenHands Agent Canvas via the same command.

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No documented `--config` flag |
| **Env var** | No documented env var for config override |

Gemini CLI does not support startup config override. Config is fixed at user home path (`~/.gemini/`).

---

## Projection mode implications for AG

- Gemini / Antigravity is a **native vendor tool** — Google-only models, no external vendor routing surface.
- Not a target for generic local endpoint propagation or vendor key injection.
- The antigravity CLI (`agy`) would require terminal restart to appear in PATH; not probed for detailed model list due to authentication flow requiring interactive OAuth login.
