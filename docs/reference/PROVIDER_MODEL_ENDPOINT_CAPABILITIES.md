# Provider Model Endpoint Capabilities

Status: reference draft
Last validated: 2026-07-09
Planning set: `docs/planning/active/model-endpoint-management/MO01..MO06`

This document records how AUDiaGentic should reason about local/custom model endpoint configuration across provider adapters. It is provider-owned: agent profiles choose `provider_id` and `model_id` at dispatch time, while the `providers` component owns the config formats, auth conventions, model catalogs, reload behavior, and projection rules that make a model available to each provider.

> **Placeholder legend.** Cells marked `⟨FILL⟩` are fields whose value has not been verified against the installed upstream tool or this repo's own adapter code. Do not guess them. Confirm against the installed tool version or repository implementation, then replace the token. A `⟨FILL⟩` value is a blocker for auto-writing that provider, not a default.

## Goal

Declare a local/custom model endpoint once in AUDiaGentic project config, then let the `providers` component project that desired state into each compatible third-party agent's own config format so every supported provider can drive an AUDiaGentic-hosted model without clobbering unmanaged user entries and with reversible ownership tracking.

This is the same problem shape AUDiaGentic already handles for managed MCP server entries and language-server projection: one desired-state declaration, multiple provider-specific config surfaces, and ownership tracking so manually added user entries survive. Model endpoint propagation is therefore a **managed-config kind**, not a separate subsystem.

## Current code facts this plan must respect

The current repository has useful primitives, but the consolidation is not implemented yet.

| Area | Current code state | Planning consequence |
|---|---|---|
| Provider config specs | `McpConfigSpec` and `LanguageServersConfigSpec` are still separate dataclasses in `components/providers/descriptors/base.py`. MCP has `refresh_mode`, `reload_fn`, and `remote`; LSP currently does not. | MO06 must extract a `ManagedConfigSpec` that supports optional/feature-specific fields. Do not claim the shared spec already exists. |
| Descriptor loading | `loader.py` still has `_build_mcp_config` and `_build_language_servers_config` as separate builders. | MO06 must replace both with one builder or a managed-config map while keeping YAML compatibility. |
| Reconciler | `foundation/toolchains/fragments.py` is already domain-opaque: `FragmentStore`, `reconcile_fragments`, opaque `owner_scope`, and `Any` payloads. | Reuse this directly for structured model entries. Do not create another reconciler. |
| Registry | `managed_mcp_registry.py` is a provider-specific JSON registry hard-coded to `.audiagentic/runtime/providers/managed-mcp-servers.json`. | Generalize it into a parameterized `ManagedFragmentRegistry`; instantiate one registry for MCP and one for model endpoints. |
| MCP sync service | `services/mcp.py` contains the reusable sync/reload shape: resolve config path, bind `FragmentStore`, call `reconcile_fragments`, then reload or report no-op. | Extract shared `sync_managed_config` / `reload_managed_config`; MCP/LSP/model wrappers should stay thin. |
| Recipe framework | `ProviderRecipeKind` currently has no `MODEL_CONFIG`/`MODEL_ENDPOINTS` kind. `NoAutomationRecipe` is guidance-only and returns `ABSENT` plus `action_needed`. | Add an explicit model-config recipe kind. Use `NoAutomationRecipe` only for manual/unsupported/blocked providers, not for env-projection automation. |
| OpenCode harness | The runtime harness writes `.opencode/config.json` with top-level `providers`, while the provider descriptor currently manages MCP/LSP in `.opencode/opencode.json`. | OpenCode model config is a validation gate before implementation. Unify or intentionally separate these paths atomically. |
| Goose descriptor | The repo's Goose provider uses `.goose/config.yaml` for MCP and its execution adapter is currently a stub. | Do not assume a JSON custom-provider model config. Treat Goose model config as validate-first until path/schema are confirmed. |
| local-openai catalog | `local_openai/catalog.py` emits `status: "available"` and `context-window: None`, while the schema requires `status ∈ {active,deprecated,experimental}` and integer `context-window >= 1`. | MO05 remains the first isolated bug fix before broader endpoint projection. |

## Design position

Model endpoint projection belongs under the providers component.

- `agents` keep provider/model binding and execution selection.
- `providers` own endpoint declaration, connector compatibility, provider config rendering, auth projection, reload/refresh behavior, and provider status.
- Recipes call provider-owned sync/status operations; recipes must not hand-write provider config files directly.
- Structured config adapters must preserve unmanaged provider entries.
- Env-projection providers must not be forced through fragment reconciliation.
- VS Code extension-storage providers must stay manual/blocked until storage profile format and host-adapter access are validated.

## Managed mechanisms

| Mechanism | Use for | Managed unit | Ownership model | Implementation vehicle |
|---|---|---|---|---|
| Structured managed config | Pi, OpenCode, Codex, Qwen, Continue, Plandex after validation, Goose only after validation | Provider block, model entry, or provider+model tuple | `owner_scope = provider_id`, `managed_id = model-endpoints/<endpoint-id>` | `ManagedConfigSpec` + `ManagedFragmentRegistry` + `sync_managed_config` over `reconcile_fragments` |
| Native AUDiaGentic catalog | `local-openai` | AG catalog entry/alias | AG-owned catalog record | Fix catalog schema output, expose endpoint entries as provider catalog models |
| Launch env projection | OpenHands, Aider, possibly Goose if file path remains unvalidated | Env vars and launch args | No persistent fragment ownership | Provider capability recipe that contributes launch env; no fragment registry |
| Extension storage/manual | Cline, Roo | VS Code extension profile state | No stable managed contract yet | `NoAutomationRecipe` with action-needed text until storage format validated through host adapter |
| Native vendor/account service | Gemini CLI, Claude Code, Copilot | Native model selection/account catalog | Not a local endpoint entry | No generic custom endpoint projection unless a vendor-gateway recipe is explicitly added |
| Managed-agent API | Antigravity | Remote agent id/session | Not a local model endpoint | Research-only, out of model-endpoint propagation scope |

## Proposed managed model shape

```yaml
contract-version: v1
model-endpoints:
  qwen36-local:
    display-name: Qwen3.6 local
    connector: openai-compatible
    base-url: http://127.0.0.1:1234/v1
    api-key-ref: env:AUDIAGENTIC_LOCAL_API_KEY
    model-id: qwen3.6-35b-a3b
    context-window: 262144
    max-output-tokens: 4096
    capabilities:
      tool-use: true
      reasoning: false
      vision: false
    provider-overrides:
      pi:
        api: openai-completions
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: false
      opencode:
        provider-id: audiagentic-local
      openhands:
        model-prefix: openai/
```

Stable ownership rules:

- Use `model-endpoints/<endpoint-id>` as the stable managed id passed to the reconciler.
- Keep `owner_scope` as the AUDiaGentic provider id, matching current MCP registry semantics.
- Provider-visible names may vary by adapter; the stable managed id must not.
- Updating URL, model id, context window, output limit, or provider overrides updates only the owned entry.
- Removing an endpoint removes only entries owned by that endpoint id.
- Unmanaged user-defined provider/model entries must survive every sync.

## Connector taxonomy

`openai-compatible` is only one connector. The endpoint declares its connector; each provider declares `supported-connectors`; projection occurs only when the provider can carry the endpoint's connector or a declared provider override maps to a supported fallback.

| Connector | Wire/backend | Auth shape | Notes |
|---|---|---|---|
| `openai-compatible` | OpenAI-style `/v1` chat/completions or compatible gateway | Bearer/API key + base URL | Baseline for llama.cpp, vLLM, LM Studio, Ollama OpenAI shim, and many gateways. |
| `anthropic` | Anthropic Messages API | `x-api-key`, version header, optional base URL | Native Claude/gateway path; not the same as OpenAI-compatible. |
| `gemini` | Google Generative Language API | API key or OAuth + API version | Native Gemini connector; distinct from Gemini's OpenAI-compatible shim as consumed by other clients. |
| `openrouter` | OpenAI-compatible wire plus OpenRouter routing/catalog extensions | Bearer key | Treat as first-class where provider has native OpenRouter support because routing/catalog semantics matter. |
| `litellm` | LiteLLM prefix abstraction | Backend-specific env keys | Routing abstraction used by OpenHands/Aider style model strings; not a wire protocol by itself. |
| `ollama` | Native Ollama API or OpenAI shim | Usually none/local | Prefer native only when provider has a dedicated Ollama connector. |
| `native-vendor` | Provider's own account/login path | Vendor account or CLI login | Claude Code, Gemini CLI, Copilot; model selection only, not generic local endpoint propagation. |

## Capability matrix

| Provider | Custom endpoint | Config mechanism | Current repo signal | Reconcile/projection unit | Support status | Priority | Review stance |
|---|---:|---|---|---|---|---:|---|
| `pi` | Yes | structured JSON | Harness template has `providers.<id>.models[]` | provider block + model list | auto after MO06 | P1 | Good structured adapter candidate. |
| `opencode` | Yes | structured JSON | Descriptor uses `.opencode/opencode.json`; harness writes `.opencode/config.json` | provider block + models map | blocked until path/container unified | P1 | Validation gate before writer. |
| `local-openai` | Yes | AG catalog | Catalog output currently violates schema | catalog entry/alias | auto after MO05 | P1 | First bug fix. |
| `openhands` | Yes | env projection first; settings file unvalidated | No repo model writer yet | launch env | auto env / blocked file | P1 | Do not use fragments for env. |
| `goose` | Yes, upstream likely supports multiple providers | repo currently has `.goose/config.yaml` MCP and stub execution | no confirmed model-config writer | ⟨FILL⟩ | blocked/validate-first | P1/P2 | Remove JSON assumption. Confirm path/schema first. |
| `codex` | Limited/custom | user-global TOML | No writer yet | provider table + active model | auto only with explicit consent | P1 | Dry-run + consent required. |
| `qwen` | Yes | structured JSON | No writer yet | `modelProviders` entries | auto after schema/path validation | P1 | Merge/collision risk. |
| `continue` | Yes | structured YAML first; legacy JSON second | No writer yet | `models[]` entries | auto after adapter validation | P2 | Preserve roles/capabilities. |
| `cline` | Yes | VS Code extension storage | No stable storage adapter | manual profile | manual/blocked | P2 | Host-adapter validation required. |
| `roo` | Yes | VS Code extension storage | Descriptor currently says `access_mode: env`, which is misleading for extension profile state | manual profile | manual/blocked | P2 | Fix descriptor semantics before model adapter. |
| `aider` | Yes | env projection first | execution adapter currently not a real launch target | launch env + model flag | manual → auto env when execution exists | P2 | No persistent file writer until `.aider.conf.yml` merge behavior verified. |
| `plandex` | Yes | structured custom model config | adapter/path not wired | provider + model + pack | blocked | P2 | Implement after path/schema discovery. |
| `gemini` | Native/account primarily | vendor CLI/account | no generic endpoint writer | native model id only | unsupported for arbitrary local endpoint | P3 | Exclude from generic projection. |
| `claude` | Native/gateway primarily | vendor CLI/account/env | no generic endpoint writer | native/gateway recipe only | unsupported for OpenAI-compatible local endpoint | P3 | Separate gateway recipe if needed. |
| `copilot` | No generic | account service | account-derived | N/A | unsupported | N/A | Not a target. |
| `antigravity` | Not validated | managed-agent/API research | no provider adapter | N/A | research-only | N/A | Not part of endpoint propagation. |

## Connector capability per provider

`⟨FILL⟩` means verify against installed upstream or repo adapter before enabling auto-projection.

| Provider | openai-compatible | anthropic | gemini | openrouter | ollama/local | Preferred projection |
|---|---:|---:|---:|---:|---:|---|
| `pi` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | via compatible fallback ⟨FILL⟩ | Yes via shim | Pi provider block with `api`/`compat`. |
| `opencode` | Yes | Yes | Yes | Yes | Yes | Native AI SDK provider where available; fallback OpenAI-compatible. |
| `local-openai` | Yes | No | No | via base URL only | Yes via OpenAI shim | AG OpenAI-compatible catalog. |
| `openhands` | Yes | Yes via LiteLLM | Yes via LiteLLM | Yes via LiteLLM | Yes | LiteLLM/OpenAI model prefixes through launch env. |
| `goose` | Yes | Yes | ⟨FILL⟩ | ⟨FILL⟩ | Yes | ⟨FILL: config path/schema/reload⟩. |
| `codex` | Yes if required wire API is supported | Not generic | Not generic | ⟨FILL⟩ | built-ins/compat only | `~/.codex/config.toml`, consent-gated. |
| `qwen` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | `modelProviders` after merge semantics verified. |
| `continue` | Yes | Yes | Yes | Yes | Yes | Continue provider type / YAML `models[]`. |
| `cline` | Yes | Yes | Yes | Yes | Yes | Manual extension profile. |
| `roo` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | Yes | ⟨FILL⟩ | Manual extension profile until storage validated. |
| `aider` | Yes | Yes via LiteLLM | Yes via LiteLLM | Yes | Yes | Env + model prefix/flag. |
| `plandex` | Yes only for custom providers | No generic custom wire | No generic custom wire | As OpenAI-compatible only | If OpenAI-compatible | Custom model config after path discovery. |
| `gemini` | Gemini API can expose an OpenAI-compatible endpoint to other clients, but Gemini CLI as consumer is not validated | No | Yes | No | No | Native vendor. |
| `claude` | No generic OpenAI-compatible consumer path | Yes | No | Gateway only | No | Native vendor/gateway. |
| `copilot` | No | No | No | No | No | N/A. |
| `antigravity` | ⟨FILL⟩ | ⟨FILL⟩ | Gemini-managed | ⟨FILL⟩ | No | Managed-agent research. |

## Per-provider adapter notes

### `pi`

- Current repo template: `src/audiagentic/runtime/harness/pi/templates/home/agent/models.json` uses `providers.<id>.models[]` with model objects keyed by `id`.
- Writer should reconcile models inside a dedicated AUDiaGentic-managed provider id and preserve unmanaged providers/models.
- Still verify project/home scope and reload behavior before marking adapter complete.

### `opencode`

- Current repo conflict: descriptor MCP/LSP config points at `.opencode/opencode.json`, but the harness materializer writes `.opencode/config.json` with top-level `providers`.
- Do not implement model writing until this is resolved atomically for MCP + LSP + model config.
- Adapter must also validate whether installed OpenCode expects `provider` or `providers` for the current version.

### `local-openai`

- Fix catalog output first: map status to `active|deprecated|experimental`, provide positive integer context-window fallback, keep booleans boolean.
- This is a native AG catalog bridge; no external provider file is written.

### `openhands`

- Env projection first: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, with provider-specific model prefix where needed.
- `.openhands/settings.json` remains blocked until schema and safe managed-write behavior are validated.

### `goose`

- Current repo has `.goose/config.yaml` for MCP and execution is a stub. The prior JSON custom-provider assumption is not valid against current code.
- Treat model config as validate-first: confirm Goose provider config path, format, keys, reload behavior, and whether model config belongs in `.goose/config.yaml`, user config, or env.
- If no safe file contract is available, use env/config guidance and `NoAutomationRecipe` rather than fragments.

### `codex`

- User-global `~/.codex/config.toml` writes require explicit consent and dry-run.
- Use env-key references, not inline secrets.
- Adapter must validate required `wire_api` compatibility; chat-completions-only local servers may not be enough.

### `qwen`

- Target `modelProviders` only after settings path/scope and merge/replacement behavior are verified.
- Add collisions tests for unmanaged entries and duplicate visible ids.

### `continue`

- Modern YAML first; legacy JSON second.
- Preserve roles/capabilities and unmanaged models.
- Do not assume a single global active model pointer because Continue supports role-based model selection.

### `cline` and `roo`

- Capability exists, but automation is blocked by extension-storage/profile uncertainty.
- Use host adapter if storage access is ever automated; do not hard-code VS Code global/workspace storage paths.
- Roo descriptor semantics should be fixed before model work; `access_mode: env` currently implies `auth-ref` behavior that does not match extension-managed profile state.

### `aider`

- Env projection and CLI model flag first, once execution adapter is a real launch target.
- `.aider.conf.yml` writer remains blocked until merge/removal behavior is validated.

### `plandex`

- Custom providers are OpenAI-compatible, but adapter path/schema must be discovered first.
- Confirm model pack behavior, unique provider/model ids, and config scope before writing.

### `gemini`, `claude`, `copilot`, `antigravity`

- Keep out of generic local endpoint propagation.
- Gemini/Claude may later get native model-selection or gateway recipes, but those are not OpenAI-compatible local endpoint adapters.
- Copilot is account/service-derived.
- Antigravity is managed-agent research, not endpoint projection.

## Implementation requirements

### Descriptor metadata

Preferred target shape after MO06:

```yaml
managed_configs:
  model-endpoints:
    config_path: ".opencode/config.json"
    reader: "...:read_opencode_models"
    writer: "...:write_opencode_models"
    remover: "...:remove_opencode_models"
    format: "opencode-json"
    refresh_mode: "file-watch"
    supported_connectors:
      - openai-compatible
      - openrouter
```

A backward-compatible interim shape may use `model_config`, but the implementation must not introduce a third long-lived `ModelConfigSpec` clone.

### Service shape

Expose model operations as thin bindings over the generalized sync/reload core:

- `sync_managed_provider_models(provider_id, project_root, desired_entries)`
- `sync_managed_provider_models_subset(..., managed_ids={...})`
- `list_provider_models_config(provider_id, project_root)`
- `reload_provider_models(provider_id, project_root)`

Use:

- `reconcile_fragments` + `FragmentStore` for structured entries.
- One generalized `ManagedFragmentRegistry` instance for `.audiagentic/runtime/providers/managed-model-endpoints.json`.
- A model-specific `ProviderRecipeKind` for lifecycle/status/dry-run.
- `NoAutomationRecipe` for manual/unsupported/blocked providers.
- A dedicated launch-env contribution recipe for env-projection providers.
- A sibling `_sync_provider_models` call inside `reconcile.py::reconcile_provider`.
- Provider status fields for support mode, config path, managed count, refresh mode, collisions, last sync, and action-needed.

Do not:

- Clone `services/mcp.py` into a second full model service.
- Add a third persistent `*ConfigSpec` dataclass.
- Add a second hard-coded registry module.
- Write provider model config directly from recipes.
- Use text block patching for JSON/TOML/YAML entries.
- Force env-projection or extension-storage through `reconcile_fragments`.
- Treat unsupported vendor/account catalogs as custom endpoint allowlists.

## Review gates

| Gate | Required evidence |
|---|---|
| MO05 catalog gate | `local-openai` catalog payload validates against `provider-model-catalog.schema.json`. |
| MO06 shared-core gate | MCP and LSP tests pass unchanged through the generalized managed-config core. |
| Endpoint schema gate | `model-endpoints` schema validates multiple endpoints, connector-specific fields, provider overrides, and secret refs. |
| Structured adapter gate | First OpenCode/Pi writer preserves unmanaged entries, removes only owned entries, and reports collisions. |
| Env projection gate | OpenHands/Aider launch env receives endpoint-derived values without registry fragments or secret logging. |
| Consent gate | Codex dry-run and apply require explicit user-global write consent. |
| Manual/blocked gate | Cline/Roo/Plandex/unsupported providers report guidance-only status with action-needed text. |
| Documentation gate | This reference is updated whenever any `⟨FILL⟩` field becomes verified. |

## First implementation order

1. Fix `local-openai` catalog validation.
2. Consolidate `ManagedConfigSpec`, `ManagedFragmentRegistry`, and `sync_managed_config` so MCP/LSP/model config share one implementation.
3. Add `model-endpoints` project schema and tests for connector taxonomy and multiple local models.
4. Resolve OpenCode config path/container mismatch before any OpenCode writer.
5. Implement Pi structured adapter.
6. Implement OpenHands env-projection capability recipe.
7. Implement Codex with consent-gated user-global TOML writes.
8. Implement Qwen after path/merge validation.
9. Reassess Goose after path/schema validation; do not assume JSON.
10. Implement Continue YAML adapter.
11. Keep Cline/Roo/Plandex blocked/manual until storage/path validation is done.

## Open verification list

| Provider | Verification blocker |
|---|---|
| `pi` | Project/home scope, active/default model selection, reload behavior. |
| `opencode` | `.opencode/config.json` vs `.opencode/opencode.json`, `providers` vs `provider`, active model pointer. |
| `openhands` | Settings file schema and safe managed-write scope. |
| `goose` | Provider model config path/format/schema/reload behavior; current repo only confirms `.goose/config.yaml` MCP. |
| `codex` | Required wire API and restart/reload behavior. |
| `qwen` | Settings path, selection semantics, merge/replacement behavior. |
| `continue` | Config path/version and file-watch behavior. |
| `cline` | Extension storage format/profile scope. |
| `roo` | Descriptor access-mode semantics, extension storage format/profile scope, tool-calling constraints. |
| `aider` | Real execution launch seam and `.aider.conf.yml` merge behavior. |
| `plandex` | Custom model config path/scope/schema. |
| `gemini` / `claude` | Only vendor/gateway recipes unless a generic custom-endpoint consumer path is validated. |
