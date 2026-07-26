# Provider to Hindsight Installation Map

This is the canonical human-readable map of every AUDiaGentic provider descriptor
to the Hindsight integration route selected by the current runtime.

It is documentation, not an executable dispatch matrix. Runtime selection remains
capability-driven through `list_provider_descriptors()` and the fixed preference
order in `provision.py`:

1. `managed-hooks`
2. `managed-mcp`
3. `plugin-entry`
4. guidance-only when none of those families is advertised

Reviewed on 2026-07-26 against the working tree after the Hindsight recipe
migration: provider-owned config (hook/MCP/plugin entries) is delegated to the
`providers_api` families; Hindsight-owned artifacts (`~/.hindsight/*`) are
produced by declarative recipes (see "Hindsight-owned artifact recipes" below),
not hand-rolled writers.

## Summary

- Current provider descriptors: **16**
- Resolved to managed hooks: **1**
- Resolved to managed MCP: **12**
- Resolved to plugin entry: **0**
- Guidance-only: **3**
- Deprecated provider retained in the registry: **Gemini**, replaced by Antigravity

## Runtime installation references

Each provider gets two independent operations per reconcile: the **provider-owned
family** call (below) and, if the provider has an entry in `_ARTIFACT_RECIPES`, a
**Hindsight-owned artifact recipe** (see the recipe section). `_combine_summary`
folds the two results.

### H1 — managed hooks

Used by Codex because `managed-hooks` has precedence over its `managed-mcp`
capability. Provider-owned hook entries only:

```text
components/memory/hindsight/provision.py::_apply_hooks
  -> _build_codex_hook_entries          # per-event commands pointing at the fetched scripts
  -> providers/providers_api.py::manage_hook_entries
```

The Hindsight-owned artifacts (`~/.hindsight/codex.json` and the hook scripts
under `~/.hindsight/codex/scripts/`) are produced by the `hindsight-codex.yaml`
artifact recipe, not by `_apply_hooks`.

### M1 — managed MCP

The standard route for providers that advertise `managed-mcp` and do not resolve
to managed hooks first. Provider-owned MCP entry only:

```text
components/memory/hindsight/provision.py::_apply_mcp
  -> components/memory/hindsight/mcp_recipe.py::build_hindsight_managed_entry
  -> providers/providers_api.py::manage_mcp_entries
  -> provider descriptor mcp_config reader/writer/remover
```

The managed entry ID is `ag-hindsight`. HTTP/SSE entries point to the backend's
`/mcp` endpoint and include `Authorization` and `X-Bank-Id` headers when
configured. Stdio uses `hindsight-mcp --base-url <base-url>`. Pi additionally
runs the `hindsight-pi.yaml` artifact recipe to write its `~/.hindsight/config.json`
host block — that host block is a Hindsight-owned artifact, **not** part of the
provider MCP entry.

### R1 — Hindsight-owned artifact recipes

Files under `~/.hindsight/*` that Hindsight owns are provisioned declaratively,
independent of the provider family. `provision.py` holds only a data catalogue —
no `if provider_id == …` branches:

```text
provision.py::_ARTIFACT_RECIPES = {"codex": "hindsight-codex.yaml", "pi": "hindsight-pi.yaml"}
provision.py::_run_artifact_recipe(provider_id, backend, mode)
  -> foundation/toolchains/recipe_execution.py::execute_recipe_mode
  -> config/components/memory/recipes/<recipe>.yaml
```

- `hindsight-codex.yaml` — `download` step fetches the hook scripts from
  `vectorize-io/hindsight/main/hindsight-integrations/codex`; `config-set` steps
  write `~/.hindsight/codex.json`. Uninstall removes those keys.
- `hindsight-pi.yaml` — `config-set` steps write the `~/.hindsight/config.json`
  host block (`enabled`, `recall_mode`, `auto_recall_tags`, …). Uninstall removes
  them.

Only Codex and Pi have artifact recipes; every other provider's integration is
entirely its provider family. Adding one is a YAML drop-in plus a catalogue entry.

### P1 — plugin entry

Implemented by `provision.py::_apply_plugin` through
`providers_api.manage_plugin_entry`, but currently selected by no provider.
OpenCode advertises both `managed-mcp` and `plugin-entry`; `managed-mcp` wins by
the fixed preference order.

### G1 — guidance-only

`reconcile_hindsight()` records a successful `guidance-only` result and writes no
provider artifact. This means Hindsight is not actually installed into that
provider by AUDiaGentic.

## Current provider map

| Provider | Descriptor | State | Advertised relevant families | Selected route | Provider destination/install reference | Upstream Hindsight reference |
|---|---|---|---|---|---|---|
| Aider (`aider`) | `config/providers/aider.yaml` | Active | none | **G1** | No provider mutation; descriptor has no managed MCP, hooks, or plugin family | [Aider integration](https://hindsight.vectorize.io/sdks/integrations/aider) existed in the retired matrix, but its wrapper installer is not invoked by current AUDiaGentic |
| Antigravity (`antigravity`) | `config/providers/antigravity.yaml` | Active; Gemini replacement | `managed-mcp` | **M1** | `config/providers/antigravity.yaml#mcp_config` | No Antigravity-specific direct installer is recorded; current support is generic MCP |
| Claude (`claude`) | `config/providers/claude.yaml` | Active | `managed-mcp` | **M1** | `config/providers/claude.yaml#mcp_config` | [Claude Code integration](https://hindsight.vectorize.io/sdks/integrations/claude-code); the upstream plugin is not the current AUDiaGentic route |
| Cline (`cline`) | `config/providers/cline.yaml` | Active | `managed-mcp` | **M1** | `config/providers/cline.yaml#mcp_config` | [Cline integration](https://hindsight.vectorize.io/sdks/integrations/cline); the upstream hook installer is not the current AUDiaGentic route |
| Codex (`codex`) | `config/providers/codex.yaml` | Active | `managed-hooks`, `managed-mcp` | **H1** + **R1** | `config/providers/codex.yaml#managed_hooks_config`; Hindsight-owned artifacts via `recipes/hindsight-codex.yaml` | [Codex integration](https://hindsight.vectorize.io/sdks/integrations/codex); scripts are sourced from `vectorize-io/hindsight/main/hindsight-integrations/codex` |
| Continue (`continue`) | `config/providers/continue.yaml` | Active | `managed-mcp` | **M1** | `config/providers/continue.yaml#mcp_config` | [Continue integration](https://hindsight.vectorize.io/sdks/integrations/continue); the upstream context-provider installer is not the current AUDiaGentic route |
| GitHub Copilot (`copilot`) | `config/providers/copilot.yaml` | Active | `managed-mcp` | **M1** | `config/providers/copilot.yaml#mcp_config` | [GitHub Copilot integration](https://hindsight.vectorize.io/sdks/integrations/github-copilot); current AUDiaGentic uses its generic MCP writer rather than the direct installer |
| Gemini (`gemini`) | `config/providers/gemini.yaml` | **Deprecated**; replacement `antigravity` | `managed-mcp` | **M1** | `config/providers/gemini.yaml#mcp_config` | [Gemini Spark integration](https://hindsight.vectorize.io/sdks/integrations/gemini-spark); retained only while the deprecated provider remains registered |
| Goose (`goose`) | `config/providers/goose.yaml` | Active | `managed-mcp` | **M1** | `config/providers/goose.yaml#mcp_config` | No direct upstream integration recorded; current support is generic MCP through Goose's YAML writer |
| Local OpenAI Bridge (`local-openai`) | `config/providers/local_openai.yaml` | Active | none | **G1** | No provider mutation; REST endpoint provider has no managed integration family | No direct upstream integration recorded |
| OpenCode (`opencode`) | `config/providers/opencode.yaml` | Active | `managed-mcp`, `plugin-entry` | **M1** | `config/providers/opencode.yaml#mcp_config`; `plugin-entry` is available but not selected | [OpenCode integration](https://hindsight.vectorize.io/sdks/integrations/opencode); the upstream plugin is deliberately bypassed by current family precedence |
| OpenHands (`openhands`) | `config/providers/openhands.yaml` | Active | `managed-mcp` | **M1** | `config/providers/openhands.yaml#mcp_config` | [OpenHands integration](https://hindsight.vectorize.io/sdks/integrations/openhands); the retired matrix marked direct automation blocked, while current generic MCP support is descriptor-backed |
| Pi Coding Agent (`pi`) | `config/providers/pi.yaml` | Active | `managed-mcp` | **M1** + **R1** | `config/providers/pi.yaml#mcp_config` for the MCP entry; `~/.hindsight/config.json` host block via `recipes/hindsight-pi.yaml` | No direct upstream integration recorded; current support is generic MCP + Hindsight-owned host block |
| Plandex (`plandex`) | `config/providers/plandex.yaml` | Active | none | **G1** | No provider mutation; descriptor has no managed MCP, hooks, or plugin family | No direct upstream integration recorded |
| Qwen (`qwen`) | `config/providers/qwen.yaml` | Active | `managed-mcp` | **M1** | `config/providers/qwen.yaml#mcp_config` | No direct upstream integration recorded; current support is generic MCP |
| Roo Code (`roo`) | `config/providers/roo.yaml` | Active | `managed-mcp` | **M1** | `config/providers/roo.yaml#mcp_config` | [Roo Code integration](https://hindsight.vectorize.io/sdks/integrations/roo-code); current AUDiaGentic uses generic MCP rather than the direct installer |

## Removed stale matrix rows

The retired Hindsight matrix contained `cursor` and `windsurf`. Neither has a
current provider descriptor, so neither belongs in the active AUDiaGentic map.

The retired matrix did not contain `antigravity`; it was added after that matrix
was written and replaces the deprecated Gemini provider.

## Important behavior notes

1. **An upstream Hindsight integration does not mean AUDiaGentic invokes it.**
   The selected route is determined only by current descriptor capabilities and
   the family preference order above.
2. **OpenCode currently resolves to managed MCP, not its upstream plugin.**
   Changing that requires changing family precedence or provider capabilities,
   not editing this document.
3. **Guidance-only is not installation.** Aider, Local OpenAI Bridge, and Plandex
   currently receive no Hindsight provider artifact.
4. **Codex is the only managed-hooks route.** Its Hindsight-owned script
   acquisition and `codex.json` are provisioned by the `hindsight-codex.yaml`
   artifact recipe (R1); the hook entries remain provider-owned through
   `providers_api`. All other provider writes remain provider-owned.
5. **Hindsight-owned artifacts are recipe-driven (R1).** Only Codex and Pi have
   artifact recipes; the provider→recipe map is the `_ARTIFACT_RECIPES` catalogue
   in `provision.py`, executed via `execute_recipe_mode`. This is code, not a
   duplicate table in this document.
6. **Gemini remains mapped only while its deprecated descriptor exists.** New
   work should target Antigravity.

## Drift checklist

Update this file whenever any of the following changes:

- a file is added to or removed from `config/providers/`;
- a provider adds or removes `managed-hooks`, `managed-mcp`, or `plugin-entry`;
- `_hindsight_families()` changes order;
- a provider's `mcp_config` or managed-hooks destination changes;
- an artifact recipe is added, removed, or retargeted — the `_ARTIFACT_RECIPES`
  catalogue in `provision.py` or a file under `config/components/memory/recipes/`;
- an upstream direct Hindsight integration is added, removed, or superseded.

The executable source of truth remains the provider descriptors, the
`_ARTIFACT_RECIPES` catalogue plus `config/components/memory/recipes/*.yaml`, and
`components/memory/hindsight/provision.py`; this map must never become a second
runtime dispatch table.
