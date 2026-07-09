# Provider Model Endpoint Capabilities

Status: reference draft
Last validated: 2026-07-09

This document records how AUDiaGentic should reason about local/custom model
configuration across provider adapters. It is intentionally provider-owned:
agent profiles choose a provider/model at dispatch time, while providers own
the config formats, auth conventions, model catalogs, and reload behavior that
make a model available.

> **Placeholder legend.** Cells marked `⟨FILL⟩` are fields whose value has not
> been verified against the upstream tool. Do not guess them — confirm against
> the installed tool version, then replace the token. A field left `⟨FILL⟩` is a
> blocker for that provider's adapter, not a default.

## What we are actually trying to achieve

One sentence: **declare a local/custom model endpoint once in AUDiaGentic
project config, and have the `providers` component project that single desired
state into each compatible third-party agent's own config format — so every
agent (pi, opencode, codex, …) can drive an AUDiaGentic-hosted model, without
clobbering the user's hand-added providers/models, and reversibly.**

This is the same problem shape AUDiaGentic already solved for MCP servers and
language servers: one desired-state declaration, many provider-specific config
formats, ownership tracked so unmanaged user entries survive. Model endpoint
propagation is therefore **a third managed-config kind**, not a new subsystem.

## Design Position

Model endpoint propagation belongs in the providers component.

- `agents` continue to bind jobs to `provider_id` and `model_id`.
- `providers` own desired local/custom model endpoint state and project that
  state into each compatible provider config.
- Provider adapters declare how model endpoints are read, written, removed,
  refreshed, and documented — as data, not bespoke services.
- Recipes call provider-owned sync services. They must not hand-write provider
  config files directly.

## Reuse Architecture — do not mirror existing code

The single most important constraint on this work: **model endpoint management
must reuse the managed-config machinery that already exists, not clone the MCP
sync service.** The prior draft of this plan proposed a standalone
`services/models.py` mirroring `services/mcp.py`; that is the wrong shape. The
codebase already carries every primitive needed.

### Existing primitives to reuse

| Concern | Existing primitive | Location | How model endpoints reuse it |
|---|---|---|---|
| Reconcile owned entries, preserve unmanaged, handle rename/collision | `reconcile_fragments` + `FragmentStore` (payload is `Any`) | `foundation/toolchains/fragments.py` | Directly. The payload is a model-entry dict; no new engine. |
| Ownership registry (`owner_scope → {managed_id → name}`) | `load/save_managed_mcp_registry` | `providers/services/managed_mcp_registry.py` | Generalize to one registry parametrized by filename/top-key (see below); do **not** copy the module per artifact kind. |
| Per-provider config format binding (path + reader/writer/remover + refresh) | `McpConfigSpec`, `LanguageServersConfigSpec` | `providers/descriptors/base.py` | Generalize to one `ManagedConfigSpec`; a `ModelConfigSpec` clone would be the third identical dataclass. |
| Thin sync/reload service over the reconciler | `_sync_managed_entries`, `reload_provider_mcp` | `providers/services/mcp.py` | Generalize the shared body to `sync_managed_config(spec, registry, …)` / `reload_provider_config(spec, …)`; MCP, LSP, and models all call it. |
| Lifecycle (probe/install/configure/verify/uninstall/dry_run), status, provenance stamping, `action_needed` | `ProviderCapabilityRecipe`, `ProviderRecipeRegistry`, `ProviderRecipeKind` | `providers/services/recipes.py` | Register model-endpoint management as a capability recipe. Reuse the registry's status/dry_run/lifecycle rather than inventing per-provider service methods. |
| "A human sets this up" (manual/unsupported/blocked tiers) | `NoAutomationRecipe` | `foundation/toolchains/recipe_patterns.py` | Bind it for env-projection and extension-storage providers. This **is** the manual-status implementation — no new code. |
| Reconcile trigger at provider enable / sync | `reconcile_provider` → `_sync_provider_mcp` | `providers/services/reconcile.py` | Add a sibling `_sync_provider_models` call in the same pass. |
| Action dispatch (the "events" surface) | `_ACTION_HANDLERS` dispatch table | `providers/services/lsp_projection.py` | Register model-sync handlers in the same table style; there is no separate event bus. |

### The three generalizations this plan should land (instead of new mirrors)

1. **One `ManagedConfigSpec`.** `mcp_config` and `language_servers_config` are
   already the same dataclass shape (see `opencode.yaml`: both declare
   `config_path/reader/writer/remover/format`). Fold them — and the new model
   spec — into a single `ManagedConfigSpec` with a `kind` label, or make the
   descriptor hold `managed_configs: dict[kind, ManagedConfigSpec]`. One YAML
   builder in `loader.py` replaces `_build_mcp_config` + `_build_language_servers_config`
   + the would-be `_build_model_config`.
2. **One `ManagedFragmentRegistry`.** `managed_mcp_registry.py` is ~40 lines of
   JSON load/save keyed by `owner_scope → {managed_id → name}`. Parametrize it
   by filename and top-level key so `managed-mcp-servers.json` and
   `managed-model-endpoints.json` are two instances, not two modules.
3. **One `sync_managed_config` service body.** Extract the reconcile/reload core
   of `mcp.py::_sync_managed_entries` so MCP, LSP, and model sync are thin
   bindings (spec + registry + desired-entry builder) over one implementation.

> **Note (SL13 A6):** `recipe_patterns.py` records that a generic
> `ManagedEntryRecipe`/`ConfigEntryTarget` was *removed* once consumers moved to
> the provider fragment machinery. Do not resurrect it. The reconcile engine
> (`fragments.py`) is the reuse target; the recipe framework is for
> lifecycle/status/provenance, not for the reconcile loop.

### Env-projection and extension-storage are a different mechanism

The reconcile-a-config-file model only works for **structured-file** providers
(JSON/TOML/YAML with named entries). Two other mechanisms exist and must not be
forced through the fragment reconciler:

- **Env-projection** (OpenHands CLI, Aider): the endpoint is injected as launch
  environment (`LLM_BASE_URL`, `OPENAI_API_BASE`, …). There is no persistent
  file, no unmanaged-entry preservation, and no ownership registry. This is a
  launch-time concern — model it as a capability recipe that contributes env,
  reusing the execution/launch path, not `reconcile_fragments`.
- **Extension-storage** (Cline, Roo): state lives in VS Code extension
  storage/profiles whose format is not a stable public contract. Until the
  storage format is validated, bind `NoAutomationRecipe` and report
  supported-manual.

## Proposed Managed Model Shape

Project-level desired state supporting multiple local/custom models:

```yaml
contract-version: v1
model-endpoints:
  qwen36-local:
    display-name: Qwen3.6 local
    connector: openai-compatible   # see Connector taxonomy below
    base-url: http://127.0.0.1:1234/v1
    api-key-ref: env:AUDIAGENTIC_LOCAL_API_KEY
    model-id: qwen3.6-35b-a3b
    context-window: 262144
    max-output-tokens: 4096
    capabilities:
      tool-use: true
      reasoning: false
    provider-overrides:
      pi:
        api: openai-completions
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: false
      opencode:
        provider-id: audiagentic
      openhands:
        model-prefix: openai/
```

Stable managed id rule:

- Use `model-endpoints/<endpoint-id>` as the ownership `managed_id` passed to
  `reconcile_fragments` (the `owner_scope` stays the provider id, matching MCP).
- Provider-visible names may differ per adapter; the ownership id stays stable.
- Updating base URL, context window, token cap, or provider options replaces
  only the managed entry for that id.
- Removing an endpoint removes only entries owned by that id.
- Unmanaged user-defined model/provider entries are preserved.

## Connector / wire-protocol taxonomy

`openai-compatible` was only ever one example. Agents differ in which model
**connectors** (wire protocols / SDK backends) they can speak, and a single
endpoint may be reachable through several. An endpoint declares its `connector`;
each provider declares its `supported-connectors`; projection targets only
providers whose set includes the endpoint's connector, rendering it into that
provider's native representation.

Connector kinds:

| Connector | Wire / backend | Auth shape | Notes |
|---|---|---|---|
| `openai-compatible` | OpenAI `/v1/chat/completions` | Bearer key + base-url | Universal baseline: llama.cpp, vLLM, Ollama's OpenAI shim, most gateways. |
| `anthropic` | Anthropic Messages API | `x-api-key` + `anthropic-version` + base-url | Native Claude; agents on `@ai-sdk/anthropic` or LiteLLM `anthropic/`. Base-url override reaches gateways/Bedrock/Vertex fronts. |
| `gemini` | Google Generative Language API | API key / OAuth + api-version | Native Gemini; `@ai-sdk/google` or LiteLLM `gemini/`. Distinct from Gemini's own OpenAI-compat shim. |
| `openrouter` | OpenAI-compatible + OpenRouter extensions | Bearer key | Aggregator — see below. Namespaced model ids + routing prefs + catalog. |
| `litellm` | LiteLLM prefix strings (`anthropic/`, `gemini/`, `openrouter/`, `bedrock/`, `vertex_ai/`, `ollama/`) | per-backend env keys | Not a wire protocol — a routing abstraction inside OpenHands/Aider. One connector, many backends. |
| `ollama` | Ollama native (or its OpenAI shim) | none / local | Local models; several agents special-case it. |
| `native-vendor` | The agent's built-in vendor path | vendor account / CLI login | Claude Code, Gemini CLI — model *selection* only, endpoint not user-swappable (or only via vendor gateway env). |

Endpoint-level connector fields (beyond `base-url` / `api-key-ref`) are
connector-specific and mostly `⟨FILL⟩` until confirmed per agent: `anthropic`
needs version header handling; `gemini` needs api-version; `openrouter` may
carry `provider` routing preferences and namespaced `model-id`.

### Aggregators / unified gateways (OpenRouter and alternatives)

OpenRouter is **OpenAI-compatible on the wire** (`https://openrouter.ai/api/v1`,
Bearer key) but is **more than a plain endpoint**: one key exposes hundreds of
vendor-namespaced models (`anthropic/claude-…`, `google/gemini-…`), plus routing
/ fallback preferences, a `/models` catalog (pricing, context), and unified
billing. Most agents ship a **dedicated OpenRouter provider type** rather than
generic openai-compatible, to expose namespacing + routing + catalog.

Alternatives fall in two groups:

- **Drop-in openai-compatible gateways** — Together, Groq, Fireworks, DeepInfra,
  vLLM, local llama.cpp. Model these as `openai-compatible` + base-url + key.
- **Unified control planes** — LiteLLM proxy, Portkey (and OpenRouter). OpenAI
  wire, but add routing, fallbacks, caching, observability, virtual keys. Model
  these as their own connector (`openrouter` / a generic `aggregator`) so the
  extra capability (namespacing, routing prefs, catalog) is representable, and
  fall back to `openai-compatible` for agents that only see the wire.

Design rule: **use a provider's native connector when it has one** (unlocks
namespacing/catalog/routing); **fall back to `openai-compatible`** for agents
that can only speak the wire. AUDiaGentic declares the endpoint's connector once;
per-provider `provider-overrides` may pin an alternate connector where an agent
prefers it.

## Comprehensive Capability Matrix

Two axes were previously conflated. They are now separate:

- **Support status** — `auto` (AUDiaGentic reconciles the config),
  `manual` (capability real, human configures; `NoAutomationRecipe`),
  `unsupported` (no custom-endpoint path), `blocked` (needs upstream/storage
  validation first).
- **Priority** — implementation ordering, independent of status.

### Summary matrix

| Provider | Custom endpoint | Config mechanism | Config scope | Reconcile unit | Reuse vehicle | Support status | Priority |
|---|---|---|---|---|---|---|---|
| `pi` | Yes | structured-file (JSON) | project | provider-block + model-entry | fragments + `ManagedConfigSpec` | auto | P1 |
| `opencode` | Yes | structured-file (JSON) | project | provider-block + model-entry | fragments + `ManagedConfigSpec` | auto | P1 |
| `local-openai` | Yes | AG provider config / catalog | project (AG) | catalog entry | native catalog (fix schema) | auto | P1 |
| `openhands` | Yes | env-projection (+ settings file ⟨FILL⟩) | launch-env / ⟨FILL⟩ | n-a (env) | capability recipe (env contrib) | auto (env) / blocked (file) | P1 |
| `goose` | Yes | structured-file (JSON) | ⟨FILL: project vs user⟩ | provider-block | fragments + `ManagedConfigSpec` | auto | P1 |
| `codex` | Yes | structured-file (TOML) | **user-global** | provider-block + active-model | fragments + `ManagedConfigSpec` | auto (consent-gated) | P1 |
| `qwen` | Yes | structured-file (JSON) | project | provider-block + model-entry | fragments + `ManagedConfigSpec` | auto | P1 |
| `continue` | Yes | structured-file (YAML; legacy JSON) | project | model-entry | fragments + `ManagedConfigSpec` | auto | P2 |
| `cline` | Yes | extension-storage | ⟨FILL⟩ | n-a | `NoAutomationRecipe` | manual → blocked | P2 |
| `roo` | Yes | extension-storage | ⟨FILL⟩ | n-a | `NoAutomationRecipe` | manual → blocked | P2 |
| `aider` | Yes | env-projection (+ `.aider.conf.yml` ⟨FILL⟩) | launch-env / project | n-a (env) | capability recipe (env contrib) | manual → auto (env) | P2 |
| `plandex` | Yes | structured-file ⟨FILL: format/path⟩ | ⟨FILL⟩ | provider + model | fragments + `ManagedConfigSpec` | blocked (adapter stub) | P2 |
| `gemini` | Native primarily | native catalog / CLI flag | n-a | n-a | native catalog | unsupported (custom) | P3/blocked |
| `claude` | Native primarily | native catalog / CLI flag | n-a | n-a | native catalog | unsupported (custom) | P3/blocked |
| `copilot` | Account-derived | account | n-a | n-a | n-a | unsupported | not target |
| `antigravity` | Unknown | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | research-only | not target |

### Connector capability per provider

Which connectors each agent can carry (the endpoint's `connector` must be in the
provider's set for projection). `⟨FILL⟩` = confirm against the installed tool.

| Provider | openai-compatible | anthropic | gemini | openrouter | ollama | Backend / SDK | Native connector to prefer |
|---|---|---|---|---|---|---|---|
| `pi` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | Yes (compat) | Pi `api` field (`openai-completions`) | openai-compatible |
| `opencode` | Yes | Yes | Yes | Yes | Yes | Vercel AI SDK (`@ai-sdk/*`) | native per vendor |
| `local-openai` | Yes | No | No | via base-url | Yes | AG HTTP bridge | openai-compatible |
| `openhands` | Yes | Yes | Yes | Yes | Yes | LiteLLM | litellm prefixes |
| `goose` | Yes | Yes | ⟨FILL⟩ | ⟨FILL⟩ | Yes | Goose provider types | native per vendor |
| `codex` | Yes | ⟨FILL: via wire_api?⟩ | ⟨FILL⟩ | ⟨FILL⟩ | Yes (compat) | Codex `model_providers` + `wire_api` | openai-compatible |
| `qwen` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | Qwen `modelProviders` | openai-compatible |
| `continue` | Yes | Yes | Yes | Yes | Yes | Continue provider types | native per vendor |
| `cline` | Yes | Yes | Yes | Yes | Yes | extension provider picker | native per vendor |
| `roo` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | Yes | ⟨FILL⟩ | extension provider picker | ⟨FILL⟩ |
| `aider` | Yes | Yes | Yes | Yes | Yes | LiteLLM | litellm prefixes |
| `plandex` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | custom providers (OpenAI-compat required) | openai-compatible |
| `gemini` | ⟨FILL: compat shim?⟩ | No | Yes | No | No | native Google / Vertex | native-vendor |
| `claude` | No | Yes | No | No | No | native Anthropic (base-url override) | native-vendor |
| `copilot` | No | No | No | No | No | account service | n-a |
| `antigravity` | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ |

### Per-provider adapter spec

Each block lists the fields an adapter author needs. `⟨FILL⟩` marks unverified
data to confirm before writing the adapter. Fields: config path · provider
container key · model container key · active-model pointer · auth mechanism ·
refresh mode · source docs.

#### `pi`
- Config path: `~/.pi/agent/models.json` ⟨FILL: confirm project vs home scope for managed use⟩ (harness template: `runtime/harness/pi/templates/home/agent/models.json`)
- Provider container key: `providers.<provider-id>`
- Model container key: `providers.<provider-id>.models[]` (list, keyed by `id`)
- Active-model pointer: ⟨FILL: how Pi selects default/active model⟩
- Auth mechanism: `providers.<id>.apiKey` (inline) + `api: openai-completions`
- Refresh mode: ⟨FILL: file-watch vs restart⟩
- Sources: https://pi.dev/docs/latest/custom-provider · https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md

#### `opencode`
- Config path: `.opencode/opencode.json` **(unresolved: harness installer writes `.opencode/config.json` with top-level `providers`; descriptor/MCP/LSP use `.opencode/opencode.json` with `provider`. Reconcile before writing.)**
- Provider container key: `provider.<provider-id>` (note `provider`, singular)
- Model container key: `provider.<id>.models.<model-id>` (map)
- Active-model pointer: top-level `model: "<provider-id>/<model-id>"`
- Auth mechanism: `provider.<id>.options` (`baseURL`, key) + `npm: "@ai-sdk/openai-compatible"`
- Refresh mode: file-watch
- Sources: https://opencode.ai/docs/config/ · https://opencode.ai/docs/models/ · https://opencode.ai/docs/providers/

#### `local-openai`
- Config path: AUDiaGentic provider config only (no external file)
- **Known bug:** `local_openai/catalog.py` emits `status: "available"` and
  `context-window: None`; schema requires `status ∈ {active,deprecated,experimental}`
  and integer `context-window ≥ 1`. Catalog cannot persist until fixed.
- Reuse: reads shared `model-endpoints`, exposes selected endpoint(s) as catalog
  entries/aliases. No external writer — this is the AG-side bridge.

#### `openhands`
- Env-projection: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`; model string uses `openai/<model-id>`
- Settings file: `.openhands/settings.json` ⟨FILL: schema + whether managed writes are safe⟩ (MCP uses `.openhands/config.toml` — different file)
- Reuse: env contribution via capability recipe first; file writer only after schema validated
- Sources: https://docs.openhands.dev/openhands/usage/llms/openai-llms · https://docs.openhands.dev/openhands/usage/llms/local-llms

#### `goose`
- Config path: ⟨FILL: custom-provider JSON file path/location⟩
- Provider container key: ⟨FILL⟩ · Model container key: ⟨FILL⟩
- Auth mechanism: ⟨FILL: auth/custom-headers fields⟩
- Refresh mode: ⟨FILL⟩
- Source: https://goose-docs.ai/docs/getting-started/providers/

#### `codex`
- Config path: `~/.codex/config.toml` (**user-global**; project `.codex/config.toml` ignores provider keys — consent-gated)
- Provider container key: `[model_providers.<id>]` (`name`, `base_url`, `env_key`, headers)
- Active-model pointer: top-level `model = "<model-id>"` + `model_provider = "<id>"`
- Auth mechanism: `env_key` referencing an env var (not inline)
- Refresh mode: ⟨FILL: confirm restart-required⟩
- Sources: https://developers.openai.com/codex/config-basic · https://developers.openai.com/codex/config-advanced · https://developers.openai.com/codex/config-reference

#### `qwen`
- Config path: `settings.json` ⟨FILL: full path/scope⟩
- Provider container key: `modelProviders.<id>`
- Model container key: model entries with `id`, `name`, `envKey`, `baseUrl`, `generationConfig`, `contextWindowSize`
- Active-model pointer: ⟨FILL: `/model` selection semantics⟩
- Auth mechanism: `envKey`
- Refresh mode: ⟨FILL⟩
- Source: https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/model-providers.md

#### `continue`
- Config path: `config.yaml` (modern) / `.continue/config.json` (legacy — existing MCP writer targets JSON)
- Model container key: top-level `models[]` (each: `name`, `provider`, `model`, `apiBase`, `roles`, `capabilities`)
- Active-model pointer: ⟨FILL: role-based selection⟩
- Auth mechanism: ⟨FILL⟩
- Refresh mode: file-watch ⟨FILL: confirm⟩
- Decision: support modern YAML first, legacy JSON second
- Sources: https://docs.continue.dev/reference · https://docs.continue.dev/customize/model-providers/top-level/openai

#### `cline`
- Extension-storage; capability real (OpenAI-compatible, Ollama, LM Studio) but storage format ⟨FILL⟩. Bind `NoAutomationRecipe` until validated.
- Source: https://docs.cline.bot/provider-config/openai-compatible

#### `roo`
- Extension-storage. Current descriptor `access_mode: env` is misleading (forces `auth-ref`); does not model extension-managed profiles. Storage format ⟨FILL⟩. `NoAutomationRecipe` until validated.
- Sources: https://docs.aimlapi.com/integrations/roo-code · https://docs.portkey.ai/docs/virtual_key_old/integrations/libraries/roo-code

#### `aider`
- Env-projection: `OPENAI_API_BASE`, `OPENAI_API_KEY` + CLI model flag; persistent `.aider.conf.yml` ⟨FILL: managed-entry schema⟩
- Reuse: env contribution via capability recipe; execution adapter is currently a stub
- Sources: https://aider.chat/docs/llms/openai-compat.html · https://aider.chat/docs/llms.html

#### `plandex`
- Config path/format: ⟨FILL: custom provider/model file⟩ · adapter is a stub
- Constraint: all custom providers must be OpenAI-compatible; provider/model ids unique
- Source: https://docs.plandex.ai/models/custom-models/

#### `gemini` / `claude`
- Native vendor catalogs; CLI `-m`/`--model` supported. No validated generic
  local-endpoint path. Treat as unsupported for custom-endpoint propagation
  unless upstream docs prove a generic OpenAI-compatible consumer path.
- Sources: https://ai.google.dev/gemini-api/docs/openai

#### `copilot`
- Account/service-derived models; not a local-endpoint target.

#### `antigravity`
- No validated custom-endpoint capability. All fields ⟨FILL⟩. Research-only.

## Implementation Requirements

### Descriptor metadata (generalized, not a new spec)

Prefer folding into one `ManagedConfigSpec`. Interim YAML shape for the model
kind, mirroring the existing `mcp_config`/`language_servers_config` blocks:

```yaml
model_config:
  config_path: ".opencode/opencode.json"
  reader: "...:read_opencode_models"
  writer: "...:write_opencode_models"
  remover: "...:remove_opencode_models"
  format: "opencode-json"
  refresh_mode: "file-watch"
  supports:
    openai-compatible: true
    multiple-local-models: true
    provider-auth-trigger: true
```

### Service (thin bindings over shared core, no `mcp.py` clone)

Expose model operations as thin wrappers over the generalized
`sync_managed_config` / `reload_provider_config`, and register them as a provider
capability recipe (`ProviderRecipeKind` for model config) so status, dry_run,
lifecycle, provenance, and `action_needed` are reused:

- `sync_managed_provider_models(provider_id, project_root, desired_entries)`
- `sync_managed_provider_models_subset(..., managed_ids={...})`
- `list_provider_models_config(provider_id, project_root)`
- `reload_provider_models(provider_id, project_root)`

Use:

- `reconcile_fragments` + `FragmentStore` for structured entries (payload = model dict).
- One generalized `ManagedFragmentRegistry` instance at
  `.audiagentic/runtime/providers/managed-model-endpoints.json`.
- `NoAutomationRecipe` for manual/unsupported/blocked providers.
- Env-contribution capability recipe (not the reconciler) for env-projection providers.
- Sibling `_sync_provider_models` call inside `reconcile.py::reconcile_provider`.
- Provider status fields: `model-config-supported`, `managed-model-count`,
  `model-config-path`, `model-config-refresh-mode`, collisions, action-needed.

Do not:

- Clone `services/mcp.py` into `services/models.py`; extract shared core instead.
- Add a third `*ConfigSpec` dataclass or a third registry module.
- Write provider model config directly from recipes.
- Use `apply_managed_block` for JSON/TOML/YAML entries.
- Force env-projection or extension-storage through `reconcile_fragments`.
- Overwrite unmanaged provider config or treat account catalogs as an allowlist.
- Conflate AUDiaGentic providers with upstream model vendors (`opencode` is an
  AG provider; `openai`/`openrouter`/`audiagentic-local` are endpoints inside it).

## First Implementation Order

1. Fix `local-openai` catalog validation (isolated bug; unblocks valid catalog persistence today).
2. Generalize `ManagedConfigSpec`, `ManagedFragmentRegistry`, and `sync_managed_config` so MCP/LSP/models share one implementation.
3. Add shared `model-endpoints` project config + schema and tests for multiple local models.
4. OpenCode model adapter after resolving `opencode.json` vs `config.json` / `provider` vs `providers`.
5. Pi model adapter (reconcile `providers.<id>.models[]`).
6. OpenHands env-projection capability recipe.
7. Goose, Codex (consent-gated, user-scope), Qwen writers.
8. Continue YAML writer.
9. Cline/Roo/Plandex only after storage/adapter path is validated — `NoAutomationRecipe` until then.
