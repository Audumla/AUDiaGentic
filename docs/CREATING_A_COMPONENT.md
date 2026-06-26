# Creating a Component

How to add a capability to AUDiaGentic. Companion: [ARCHITECTURE_STANDARDS.md](ARCHITECTURE_STANDARDS.md) (the non-negotiable rules this guide operationalizes).

## 1. Mental model

A **component** is an installable product capability ("Agent planning", "Coding LSP", "Source control"). It is declared as a YAML descriptor (data) and backed by a Python package (code).

Optional sub-tiers, only needed when the capability has swappable backends or per-item sub-capabilities:

```text
Component        config/components/<id>.yaml          the installable unit
  Implementation config/components/<id>/<impl>.yaml   a swappable backend (one active if `exclusive`)
  Feature        config/components/<id>/<feat>.yaml   an optional sub-capability (e.g. a language)
  Binding        config/components/<id>/<bind>.yaml   declares impl X supports feature Y + how
```

**Options** are typed, validated settings attachable to any tier. The simplest component is one YAML descriptor + one MCP server module — skip the feature tier entirely unless you need it.

## 2. Where things live

```text
src/audiagentic/
  config/components/
    <id>.yaml                 # component descriptor (REQUIRED)
    <id>/                     # optional feature-layer descriptors (scanned ONE level deep only)
      <impl>.yaml             #   implementation
      <feature>.yaml          #   feature
      <impl>.<feature>.yaml   #   binding
      error-resolutions.yaml  #   optional: error-code → guidance
  components/<id>/
    __init__.py
    <id>_api.py               # pure logic — no MCP, no I/O-framework coupling
    <id>_mcp.py               # MCP server: thin tool wrappers over the api
    <id>_bootstrap.py         # optional: lifecycle observer / status hook
    README.md                 # intent + capabilities
```

Descriptor under `config/components/` is **data**; package under `components/` is **code**. YAML names dotted module paths; the runtime imports them lazily.

## 3. Discovery

`foundation/components/loader.py::register_all_components()` globs `config/components/*.yaml` and `config/components/*/*.yaml`, reads each file's `type`, and registers it. `type: component` → `ComponentDescriptor`; `type: feature|implementation|binding` → handed to `foundation/features/loader.py`. It validates IDs/links and imports each declared `lifecycle-observer` module.

Hard constraints:
- **No Python import lists / registries by hand** — dropping the YAML *is* the registration (Std §5).
- Feature-layer YAML must be **at most one directory deep**; deeper is not scanned.
- `type` is the discriminator — wrong value = silently parsed as the other kind.

## 4. Component descriptor

Minimal (`config/components/my-thing.yaml`):

```yaml
type: component
contract-version: v1
id: my-thing
display-name: My Thing
description: One-line summary.
```

`detection-marker` defaults to `.audiagentic/components/<id>.yaml` (project scope) or `components/<id>.yaml` (harness scope), and a `create-if-missing` marker file is auto-synthesized there. Only set `detection-marker:`/`files:` when deviating from the default.

Fields map to `ComponentDescriptor` ([base.py](../src/audiagentic/foundation/components/base.py)):

| YAML key | Meaning |
|---|---|
| `type` | Always `component`. |
| `id` | Unique kebab-case ID; the canonical key everywhere. |
| `display-name` / `description` | Human label / short summary. |
| `detection-marker` | `rel_path` proving installation. Defaults from `id`; override only for non-default paths. |
| `aliases` | Alternate IDs resolving to this component. |
| `files` | Managed files this component owns (§5). |
| `depends-on` | Component IDs that must install first. |
| `scope` | `project` (→ `project_root/.audiagentic/`) or `harness` (→ `audiagentic_home()`, shared). Default `project`. |
| `core` | `true` ⇒ cannot be uninstalled. |
| `mcp-servers` | Python-module MCP servers (§6). |
| `external-mcp-servers` | MCP servers backed by an external command, gated on PATH tools. |
| `harness-instructions` | Markdown sections injected into the agent harness (§7). |
| `contributions` | Reusable doctrine blocks routed to skills/instruction files (§7). |
| `feature-kinds` | Feature kinds this component defines (§8). |
| `implementation-cardinality` | `exclusive` (one impl active) or `multi`. Omit if no implementations. |
| `post-install` | Dotted `fn(project_root)` run after install. |
| `lifecycle-observer` | Dotted **module** imported at registration to self-subscribe to the event bus. |
| `lifecycle-hook` | Dotted `fn(event_type, payload, metadata)`. |
| `status-hook` | Dotted `fn(project_root) -> dict` powering status. |

## 5. Managed files

Each `files:` entry is a `ComponentFile` with a `lifecycle:` mode:

| Mode | Behavior |
|---|---|
| `required-managed` | Owned and overwritten on apply; component is source of truth. |
| `create-if-missing` | Written once at install, never overwritten (markers, user-editable seeds). |
| `generated-managed` | Regenerated from config on apply (projections, caches). Never hand-edit. |
| `runtime-only` | Created at runtime (logs, scratch). Not installed, not managed. |

`recursive: true` marks a directory tree.

## 6. MCP servers

Most components ship **two** servers — keep the roles distinct:

| Role | Naming | `propagate` | Purpose |
|---|---|---|---|
| **Management** | `<comp>-mgmt` | `audiagentic` | Operator console: status, select implementation, add/remove features, install deps, set options. Never handed to providers. |
| **Activity** | `<comp>` | `audiagentic,providers` | The product itself: the tools that do the component's actual work, loaded into providers. |

`propagate` is the knob; `-mgmt` suffix signals the role. Rule of thumb: **management → `audiagentic`; activity → include `providers`** unless the provider already self-provides the capability (e.g. `ag-lsp` activity stays `audiagentic` because providers self-provide LSP). A component may declare only one server (pure activity, e.g. `git`) and add management later.

Declaration (`mcp-servers:`, Python module):

```yaml
mcp-servers:
  - name: ag-my-thing
    module: audiagentic.components.my_thing.my_thing_mcp
    direct-tools: [my_thing_do, my_thing_list]
    description: Short summary shown in tool listings.
    propagate: audiagentic,providers
    instructions: >
      Usage doctrine: when to call each tool, gotchas, ordering.
    tool-descriptions:
      my_thing_do: Longer per-tool description and arg notes.
```

- `module` must build with `mcp_server(__name__)` and run via `run_mcp_server(...)` — never construct `FastMCP` directly (Std §6).
- `instructions`/`tool-descriptions` live **here**, next to the server — not duplicated into provider instruction files.

The module stays thin; tools delegate to the pure `_api`:

```python
# components/my_thing/my_thing_mcp.py
from audiagentic.components.my_thing import my_thing_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call, mcp_server, project_root_from_env,
)

mcp = mcp_server(__name__)

@mcp.tool()
@log_tool_call
def my_thing_do(item: dict) -> dict:
    """One-line tool doc the agent sees."""
    return my_thing_api.do(project_root_from_env(), item)
```

For external-CLI tools use `external-mcp-servers:` with `command`, `requires` (PATH tools that gate inclusion), and optional `probe`.

### Ownership boundary (hard rule)

A component may expose a capability **consumable by providers**; it may **not** encode **provider-specific rendering**.

- **Allowed** in a non-provider component: generic capability state, implementation selection, provider-agnostic export data, neutral refresh hints, activity tools any provider may call.
- **Forbidden** unless the component *is* `providers`: hard-coded provider IDs (`if provider_id == "claude"`), provider file paths (`{"codex": "AGENTS.md"}`), provider-specific syntax branches, or code that writes `CLAUDE.md`/`AGENTS.md`/provider config directly.

Ownership split: **capability components** own upstream truth (selected impl, validated options, generic state, provider-agnostic exports). **The providers component / adapters** own downstream truth (which providers support it, what files they write, how generic data renders into surfaces).

If cross-component notification is unavoidable: the capability component emits a neutral hint (e.g. `needs_provider_recipe_refresh`); the providers component owns the observer that consumes it; any adapter lives in one small boundary module with architecture tests proving the dependency direction. Backend-specific integration knowledge (e.g. per-provider setup for a memory backend) stays in an implementation-owned package like `components/<component>/<implementation>/`, never in provider core.

## 7. Harness instructions and contributions

- **`harness-instructions:`** — markdown sections merged into the harness prompt (`section`, `content`, `propagate`). The tool catalog is **auto-generated** from `mcp-servers[].direct-tools` + `tool-descriptions` — do NOT hand-write one. Use this for operating rules and doctrine that can't be derived from MCP declarations.
- **`contributions:`** — reusable doctrine blocks with `preferred-targets` (`skill`, `instruction`); the surface system routes them to the right artifact. Use for process doctrine ("Planning process", "Release doctrine").

Both take `propagate` (`audiagentic` / `providers`). `propagate: providers` controls only *where guidance surfaces* — it does not transfer ownership of provider-specific rendering into the declaring component.

## 8. Features, implementations, bindings

The swappable-backend tier. Use it only for (a) interchangeable backends or (b) per-item optional sub-capabilities; otherwise skip §8. Unless the component *is* `providers`, implementations own the **generic backend contract only** — never provider matrices, paths, or render decisions. All three types are parsed by [features/loader.py](../src/audiagentic/foundation/features/loader.py) / [features/base.py](../src/audiagentic/foundation/features/base.py).

**Feature kinds / cardinality** (on the component):
```yaml
feature-kinds: [language]              # namespaces of features this component defines
implementation-cardinality: exclusive  # exclusive | multi
```

**Implementation** — a swappable backend (`coding-lsp/ag-lsp.yaml`):
```yaml
type: implementation
parent: coding-lsp
id: ag-lsp
default: true                  # active when user hasn't chosen
options-schema:
  mutation-enabled: { type: boolean, default: false }
projection:                    # what the runtime generates when active
  generic-mcp: { managed-id: coding-lsp/ag-lsp, name: ag-lsp, module: audiagentic.components.coding_lsp.lsp_mcp }
```
Key fields: `parent`, `id`, `default`, `options-schema`, `dependencies`, optional `projection`.

**Feature** — an optional capability (`coding-lsp/python.yaml`):
```yaml
type: feature
parent: coding-lsp
kind: language                 # must be one of the component's feature-kinds
id: python
dependencies:
  pyright: { probe: binary:pyright-langserver, toolchain: uv, package: pyright }
options-schema:
  server-settings: { type: object, default: {} }
```
Key fields: `parent`, `kind`, `id`, `scope`. **Scope** is `shared` (applies regardless of impl) or `implementation` (only for one named `implementation:`). Setting `implementation:` defaults scope to `implementation`.

**Binding** — derived glue saying "impl X supports feature Y" (`coding-lsp/ag-lsp.python.yaml`):
```yaml
type: binding
parent: coding-lsp
implementation: ag-lsp
feature-kind: language
feature: python
uses-dependencies: [pyright]       # which of the feature's deps this pairing needs
projection: { writer-key: coding-lsp.lsp-json }   # registered generator for runtime files
```
Bindings have no display name and no own dependencies — they reference the feature's deps and name a `projection.writer-key`. Identity: `(parent, implementation, feature-kind, feature)`. A missing binding means that impl does not support that feature (N impls × M features = up to N×M bindings).

## 9. Options and resolution

Declared as `options-schema:` ([options.py](../src/audiagentic/foundation/features/options.py)):
```yaml
options-schema:
  retries: { type: integer, default: 3, min: 0, max: 10 }   # bool|string|int|float|enum|list|object
  mode:    { type: enum, values: [fast, safe], default: safe }
```
Validation enforces type, `enum` membership, numeric `min`/`max`. Unknown keys rejected unless `allow-unknown: true`.

`resolve_options(schema, *layers)` merges last-wins: **schema-default → component-state → feature/implementation-state**. `resolve_options_with_provenance(...)` returns the same values plus which layer set each (use when debugging an option's value).

## 10. Dependencies and toolchains

Feature/impl `dependencies:` install through the workflow step system ([dependencies.py](../src/audiagentic/foundation/components/dependencies.py)), not ad-hoc shell. Each entry names:
- `probe` — presence check, e.g. `binary:pyright-langserver` or `all-binaries:a,b`.
- `toolchain` / `package` — how to install (e.g. `uv` + package name).

Platform/package-manager resolution lives in [toolchains/detect.py](../src/audiagentic/foundation/toolchains/detect.py); the runner builds `SequenceStep`/`SelectStep` trees so one declaration works cross-platform.

## 11. Lifecycle hooks

Declared on the component as dotted paths:
- `post-install: pkg.mod.fn` — `fn(project_root)` once after install.
- `lifecycle-observer: pkg.mod` — **module** imported at registration; self-registers event-bus subscribers at import time.
- `lifecycle-hook: pkg.mod.fn` — `fn(event_type, payload, metadata)` per event.
- `status-hook: pkg.mod.fn` — `fn(project_root) -> dict` for status.

Keep observers idempotent — `register_all_components()` may run multiple times per process.

## 12. Recipe — add component `my-thing`

1. **Descriptor.** `config/components/my-thing.yaml` with `type: component`, `id`, `display-name`, `description` (marker auto-derived; §4).
2. **Package.** `components/my_thing/` with `__init__.py`, `my_thing_api.py` (pure logic), `README.md`.
3. **MCP server.** `my_thing_mcp.py` via `mcp_server(__name__)`/`run_mcp_server(...)`; declare under `mcp-servers:` with `direct-tools`, `propagate`, `instructions` (§6).
4. **Harness guidance.** Add `harness-instructions:` for rules/context (tool catalog auto-generates — don't write one) and `contributions:` doctrine (§7).
5. **(Optional) Feature tier.** Set `feature-kinds` + `implementation-cardinality`, add impl/feature/binding YAML (§8).
6. **(Optional) Options.** `options-schema:` on whichever descriptors need settings (§9).
7. **(Optional) Deps & hooks.** `dependencies:` (§10), `lifecycle-observer`/`status-hook`/`post-install` (§11).
8. **Verify.** Run any component CLI command or start the MCP server (both trigger `register_all_components()`); confirm no validation errors, then exercise the tools.

### Guardrails (from ARCHITECTURE_STANDARDS.md)
- Extensibility = dropping a YAML file. Never add import lists or `if/elif` on component IDs (§2, §5).
- MCP servers via `mcp_server(__name__)` only (§6).
- Generated files go through a registered `(path, generator)` pair, not path-branching (§7).
- Respect layering: foundation imports nothing from runtime/components (§1).

## 13. Reference components

- **`planning.yaml`** + `components/planning/` — clean two-server (mgmt + activity) component, `contributions`, `exclusive`, one implementation.
- **`coding-lsp.yaml`** + `config/components/coding-lsp/` — full feature tier: `feature-kinds`, implementations, features, bindings with projections + dependencies.
- **`project.yaml`** / **`session.yaml`** — always-on `core: true` components.
