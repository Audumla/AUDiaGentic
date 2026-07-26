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

Reviewed against `harness-agent-session-fixes` on 2026-07-26.

## Summary

- Current provider descriptors: **16**
- Resolved to managed hooks: **1**
- Resolved to managed MCP: **12**
- Resolved to plugin entry: **0**
- Guidance-only: **3**
- Deprecated provider retained in the registry: **Gemini**, replaced by Antigravity

## Runtime installation references

### H1 — managed hooks

Used by Codex because `managed-hooks` has precedence over its `managed-mcp`
capability.

```text
components/memory/hindsight/provision.py::_apply_hooks
  -> _build_codex_desired
  -> _download_codex_scripts
  -> _write_codex_user_config
  -> providers/providers_api.py::manage_hook_entries
```

Hindsight-owned artifacts include `~/.hindsight/codex.json` and the downloaded
hook scripts under `~/.hindsight/codex/scripts/`. Provider-owned hook config is
written through the Codex `managed-hooks` family.

### M1 — managed MCP

The standard route for providers that advertise `managed-mcp` and do not resolve
to managed hooks first.

```text
components/memory/hindsight/provision.py::_apply_mcp
  -> components/memory/hindsight/mcp_recipe.py::build_hindsight_managed_entry
  -> providers/providers_api.py::manage_mcp_entries
  -> provider descriptor mcp_config reader/writer/remover
```

The managed entry ID is `ag-hindsight`. HTTP/SSE entries point to the backend's
`/mcp` endpoint and include `Authorization` and `X-Bank-Id` headers when
configured. Stdio uses `hindsight-mcp --base-url <base-url>`.

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
| Codex (`codex`) | `config/providers/codex.yaml` | Active | `managed-hooks`, `managed-mcp` | **H1** | `config/providers/codex.yaml#managed_hooks_config`; Hindsight-owned Codex script/config artifacts | [Codex integration](https://hindsight.vectorize.io/sdks/integrations/codex); scripts are sourced from `vectorize-io/hindsight/main/hindsight-integrations/codex` |
| Continue (`continue`) | `config/providers/continue.yaml` | Active | `managed-mcp` | **M1** | `config/providers/continue.yaml#mcp_config` | [Continue integration](https://hindsight.vectorize.io/sdks/integrations/continue); the upstream context-provider installer is not the current AUDiaGentic route |
| GitHub Copilot (`copilot`) | `config/providers/copilot.yaml` | Active | `managed-mcp` | **M1** | `config/providers/copilot.yaml#mcp_config` | [GitHub Copilot integration](https://hindsight.vectorize.io/sdks/integrations/github-copilot); current AUDiaGentic uses its generic MCP writer rather than the direct installer |
| Gemini (`gemini`) | `config/providers/gemini.yaml` | **Deprecated**; replacement `antigravity` | `managed-mcp` | **M1** | `config/providers/gemini.yaml#mcp_config` | [Gemini Spark integration](https://hindsight.vectorize.io/sdks/integrations/gemini-spark); retained only while the deprecated provider remains registered |
| Goose (`goose`) | `config/providers/goose.yaml` | Active | `managed-mcp` | **M1** | `config/providers/goose.yaml#mcp_config` | No direct upstream integration recorded; current support is generic MCP through Goose's YAML writer |
| Local OpenAI Bridge (`local-openai`) | `config/providers/local_openai.yaml` | Active | none | **G1** | No provider mutation; REST endpoint provider has no managed integration family | No direct upstream integration recorded |
| OpenCode (`opencode`) | `config/providers/opencode.yaml` | Active | `managed-mcp`, `plugin-entry` | **M1** | `config/providers/opencode.yaml#mcp_config`; `plugin-entry` is available but not selected | [OpenCode integration](https://hindsight.vectorize.io/sdks/integrations/opencode); the upstream plugin is deliberately bypassed by current family precedence |
| OpenHands (`openhands`) | `config/providers/openhands.yaml` | Active | `managed-mcp` | **M1** | `config/providers/openhands.yaml#mcp_config` | [OpenHands integration](https://hindsight.vectorize.io/sdks/integrations/openhands); the retired matrix marked direct automation blocked, while current generic MCP support is descriptor-backed |
| Pi Coding Agent (`pi`) | `config/providers/pi.yaml` | Active | `managed-mcp` | **M1** | `config/providers/pi.yaml#mcp_config`; materialized through the Pi MCP adapter/config writer | No direct upstream integration recorded; current support is generic MCP |
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
4. **Codex is the only managed-hooks route.** The implementation contains
   Codex-specific Hindsight-owned script acquisition and config materialization;
   other provider writes remain provider-owned through `providers_api`.
5. **Gemini remains mapped only while its deprecated descriptor exists.** New
   work should target Antigravity.

## Drift checklist

Update this file whenever any of the following changes:

- a file is added to or removed from `config/providers/`;
- a provider adds or removes `managed-hooks`, `managed-mcp`, or `plugin-entry`;
- `_hindsight_families()` changes order;
- a provider's `mcp_config` or managed-hooks destination changes;
- an upstream direct Hindsight integration is added, removed, or superseded.

The executable source of truth remains the provider descriptors plus
`components/memory/hindsight/provision.py`; this map must never become a second
runtime dispatch table.
