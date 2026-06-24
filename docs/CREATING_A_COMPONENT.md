# Creating a Component

A guide for agents and contributors adding a new capability to AUDiaGentic.

This document explains every concept involved — **components**, **implementations**,
**features**, **bindings**, and **options** — and walks through the files you create
and how the runtime discovers them. Read it end-to-end before adding a component;
the pieces interlock.

> Companion reading: [ARCHITECTURE_STANDARDS.md](ARCHITECTURE_STANDARDS.md) defines
> the non-negotiable rules (layering, config-over-code, MCP construction) that this
> guide operationalizes.

---

## 1. The mental model

A **component** is a product capability you can install into a project (or the shared
harness). "Agent planning", "Coding LSP", "Agent ledger", "Source control" are
components. Each one is declared as data — a YAML descriptor — and backed by Python
modules that implement its behavior and expose it over MCP.

The configuration layer has two tiers:

```text
Component            (config/components/<id>.yaml)          — the installable unit
  ├── Implementation (config/components/<id>/<impl>.yaml)   — a swappable backend
  ├── Feature        (config/components/<id>/<feat>.yaml)   — an optional capability
  └── Binding        (config/components/<id>/<bind>.yaml)   — wires an impl to a feature
```

- A **component** is the thing a user installs. It owns managed files, MCP servers,
  harness instructions, and lifecycle hooks.
- An **implementation** is one interchangeable way of backing the component. A
  planning component might be backed by local markdown files *or* a hosted issue
  tracker; only one is active at a time when the component is `exclusive`.
- A **feature** is an optional, user-selectable capability within the component —
  e.g. each programming language is a `language` feature of `coding-lsp`.
- A **binding** declares that a given implementation supports a given feature, and
  names the dependencies and projection writer used when that pair is active.
- **Options** are typed, validated settings attached to any of the above. They
  resolve through layers (schema default → component → feature/implementation state)
  with full provenance.

Not every component needs all four tiers. The simplest component is a single YAML
descriptor plus one MCP server module. The feature/implementation/binding tier is
only needed when the capability has swappable backends or per-item sub-capabilities.

---

## 2. Where things live

```text
src/audiagentic/
  config/components/
    <id>.yaml                 # the component descriptor (REQUIRED)
    <id>/                     # optional: feature-layer descriptors + companion assets
      <impl>.yaml             #   implementation descriptor(s)
      <feature>.yaml          #   feature descriptor(s)
      <impl>.<feature>.yaml   #   binding descriptor(s)
      error-resolutions.yaml  #   optional: error-code → guidance map
  components/
    <id>/
      __init__.py
      <id>_api.py             # pure logic — no MCP, no I/O framework coupling
      <id>_mcp.py             # MCP server: thin tool wrappers over the api
      <id>_paths.py           # path helpers (optional)
      <id>_bootstrap.py       # lifecycle observer / status hook (optional)
      README.md               # component intent + capabilities
```

The descriptor under `config/components/` is **data**. The package under
`components/` is **code**. Keep them separate: the loader reads YAML, the YAML names
dotted module paths, and the runtime imports those modules lazily.

---

## 3. Discovery: how the runtime finds your component

`foundation/components/loader.py::register_all_components()` is the entry point. It:

1. Globs `config/components/*.yaml` (top level) and `config/components/*/*.yaml`
   (one level deep).
2. For each file, reads `type`:
   - `type: component` → registered as a `ComponentDescriptor`.
   - `type: feature | implementation | binding` → handed to
     `foundation/features/loader.py` and registered in the feature registry.
3. Validates IDs and dependency links.
4. Imports each component's `lifecycle-observer` module (if declared) so it can
   self-register event-bus subscriptions.

Consequences you must respect:

- **No Python import lists.** You never edit a registry by hand. Dropping the YAML
  file *is* the registration (Architecture Standard §5).
- Feature-layer YAML must live **at most one directory deep** under
  `config/components/`. Deeper nesting is not scanned.
- The descriptor `type` field is the discriminator. Get it wrong and the file is
  silently treated as the other kind.

---

## 4. The component descriptor

Minimal viable descriptor (`config/components/my-thing.yaml`):

```yaml
type: component
contract-version: v1
id: my-thing
display-name: My Thing
description: One-line summary of what this capability does.
```

The `detection-marker` defaults to `.audiagentic/components/<id>.yaml` (or
`components/<id>.yaml` for `scope: harness`). The loader also synthesizes a
`create-if-missing` marker `ComponentFile` at that path when no explicit entry
matches — you only need `detection-marker:` and `files:` when deviating from the
default or adding non-marker files.

Fields map to `ComponentDescriptor` in
[foundation/components/base.py](../src/audiagentic/foundation/components/base.py).
The full set:

| YAML key | Meaning |
|---|---|
| `type` | Always `component` for a component descriptor. |
| `id` | Unique component ID (kebab-case). Used everywhere as the canonical key. |
| `display-name` | Human label. |
| `description` | One/two-line summary. |
| `detection-marker` | A `rel_path` proving installation. Defaults to `.audiagentic/components/<id>.yaml` (project scope) or `components/<id>.yaml` (harness scope). Only override for non-default paths. |
| `aliases` | Alternate IDs that resolve to this component. |
| `files` | Managed files this component owns (see §5). |
| `depends-on` | Other component IDs that must be installed first. |
| `scope` | `project` (installs into `project_root/.audiagentic/`) or `harness` (installs into `audiagentic_home()`, shared across projects). Default `project`. |
| `core` | `true` ⇒ component cannot be uninstalled. |
| `mcp-servers` | Python-module MCP servers (see §6). |
| `external-mcp-servers` | MCP servers backed by an external command, gated on PATH tools. |
| `harness-instructions` | Markdown sections injected into the agent harness (see §7). |
| `contributions` | Reusable doctrine blocks routed to skills/instruction files (see §7). |
| `feature-kinds` | List of feature kinds this component defines (see §8). |
| `implementation-cardinality` | `exclusive` (one impl active) or `multi` (several). Omit if the component has no implementations. |
| `post-install` | Dotted path to `fn(project_root)` run after install. |
| `lifecycle-observer` | Dotted **module** path imported at registration so it can subscribe to the event bus. |
| `lifecycle-hook` | Dotted path to `fn(event_type, payload, metadata)`. |
| `status-hook` | Dotted path to `fn(project_root) -> dict` powering status output. |

---

## 5. Managed files and lifecycle modes

Each entry in `files:` is a `ComponentFile` with a `lifecycle` mode:

| Mode (`lifecycle:`) | Behavior |
|---|---|
| `required-managed` | Owned and overwritten by AUDiaGentic on apply. The component is the source of truth. |
| `create-if-missing` | Written once at install; never overwritten. Used for install markers and user-editable seeds. |
| `generated-managed` | Regenerated from component config on apply (projections, caches). Never hand-edit. |
| `runtime-only` | Created at runtime (logs, scratch). Not installed, not managed. |

`recursive: true` marks a directory tree. The `detection-marker` is conventionally a
`create-if-missing` marker file under `.audiagentic/components/`.

---

## 6. MCP servers

A component exposes its tools to agents via MCP servers. Two declaration shapes:

`mcp-servers:` — backed by a Python module in your component package:

```yaml
mcp-servers:
  - name: ag-my-thing
    module: audiagentic.components.my_thing.my_thing_mcp
    direct-tools: [my_thing_do, my_thing_list]
    description: Short summary shown in tool listings.
    propagate: audiagentic,providers
    instructions: >
      Usage doctrine for the agent: when to call each tool, gotchas, ordering.
    tool-descriptions:
      my_thing_do: Longer per-tool description and arg notes.
```

- `module` — dotted path to the server module. It must build its server with
  `mcp_server(__name__)` and run via `run_mcp_server(...)` (Architecture Standard §6).
  Never construct `FastMCP` directly.
- `direct-tools` — tools surfaced directly to the agent harness.
- `propagate` — who receives this server: `audiagentic` (the AUDiaGentic agent),
  `providers` (downstream provider harnesses), or `audiagentic,providers` (both).
- `instructions` / `tool-descriptions` — usage doctrine lives **here**, next to the
  server, not duplicated into every provider's instruction file (it drifts).

The server module itself stays thin — tools delegate to a pure `_api` module:

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

For tools backed by an external CLI (not a Python module), use
`external-mcp-servers:` with `command`, `requires` (PATH tools that gate inclusion),
and an optional `probe` command to verify usability.

---

## 7. Harness instructions and contributions

Two ways to inject guidance for the agent:

- **`harness-instructions:`** — markdown sections merged into the harness prompt.
  Each has a `section` (grouping header), `content`, and `propagate`. Use for the
  "What you can do" tool catalog and operating rules.

- **`contributions:`** — reusable doctrine blocks with `preferred-targets`
  (e.g. `skill`, `instruction`). The surface system routes them into the right
  artifact (a generated skill file, an instruction file) rather than hardcoding
  where the text lands. Use for process doctrine ("Planning process", "Release
  doctrine") that should appear as a skill or in CLAUDE.md.

Both support `propagate` with the same `audiagentic` / `providers` semantics as MCP
servers.

---

## 8. Features, implementations, and bindings

This is the swappable-backend tier. Reach for it when the component has either
(a) interchangeable backends, or (b) per-item optional sub-capabilities. If neither
applies, skip this section entirely.

All three descriptor types are parsed by
[foundation/features/loader.py](../src/audiagentic/foundation/features/loader.py)
and modeled in
[foundation/features/base.py](../src/audiagentic/foundation/features/base.py).

### 8.1 Feature kinds and cardinality

On the **component** descriptor:

```yaml
feature-kinds: [language]            # the kinds of feature this component defines
implementation-cardinality: exclusive   # exclusive | multi
```

`feature-kinds` declares the namespaces of features (coding-lsp defines the
`language` kind — Python, Rust, etc.). `implementation-cardinality` controls whether
one implementation is active at a time (`exclusive`) or several (`multi`).

### 8.2 Implementation descriptor

A swappable backend (`config/components/coding-lsp/ag-lsp.yaml`):

```yaml
type: implementation
contract-version: v1
parent: coding-lsp
id: ag-lsp
display-name: AG LSP
description: AUDiaGentic native MCP language-server bridge
default: true                  # active impl when the user has not chosen one
options-schema:
  mutation-enabled:
    type: boolean
    default: false
    description: Allow LSP mutation tools (rename, apply, format).
projection:                    # how this impl is surfaced (e.g. as an MCP server)
  generic-mcp:
    managed-id: coding-lsp/ag-lsp
    name: ag-lsp
    module: audiagentic.components.coding_lsp.lsp_mcp
```

Key fields: `parent` (the component id), `id`, `default`, `options-schema`,
`dependencies`, and an optional `projection` describing what the runtime generates
when this implementation is active.

### 8.3 Feature descriptor

An optional capability within the component
(`config/components/coding-lsp/python.yaml`):

```yaml
type: feature
contract-version: v1
parent: coding-lsp
kind: language                 # must be one of the component's feature-kinds
id: python
display-name: Python (pyright)
# ...feature-specific facts (server command, file extensions, markers)...
dependencies:
  pyright:
    display-name: Pyright (Python LSP)
    probe: binary:pyright-langserver
    toolchain: uv
    package: pyright
options-schema:
  server-settings:
    type: object
    default: {}
```

Key fields: `parent`, `kind`, `id`, plus `scope`. **Scope** is `shared` (the feature
applies regardless of implementation) or `implementation` (it only exists for one
named `implementation:`). If you set `implementation:`, scope defaults to
`implementation` automatically.

### 8.4 Binding descriptor

A binding says "implementation X supports feature Y, and here is how"
(`config/components/coding-lsp/ag-lsp.python.yaml`):

```yaml
type: binding
contract-version: v1
parent: coding-lsp
implementation: ag-lsp
feature-kind: language
feature: python
uses-dependencies: [pyright]       # which of the feature's deps this pairing needs
projection:
  writer-key: coding-lsp.lsp-json  # registered generator that writes the projection
```

Bindings are **derived glue**: no display name, no own dependencies — they
*reference* the feature's dependencies via `uses-dependencies` and name a
`projection.writer-key` (a registered generator that produces runtime files when the
impl+feature pair is active). The full identity is
`(parent, implementation, feature-kind, feature)`.

### 8.5 The matrix

With N implementations and M features of a kind, you have up to N×M bindings. Each
binding that exists declares that pairing is supported; a missing binding means that
implementation does not support that feature.

---

## 9. Options and resolution

Options give any descriptor typed, validated settings. Declared as `options-schema:`
(parsed by [foundation/features/options.py](../src/audiagentic/foundation/features/options.py)):

```yaml
options-schema:
  retries:
    type: integer        # bool|boolean, string|str, int|integer, float|number, enum, list, object
    default: 3
    min: 0
    max: 10
  mode:
    type: enum
    values: [fast, safe]
    default: safe
```

Validation enforces type, `enum` membership, and numeric `min`/`max`. Unknown keys
are rejected unless `allow-unknown: true`.

**Resolution layers.** `resolve_options(schema, *layers)` merges, last-wins, in order:

```text
schema-default  →  component-state  →  feature-state / implementation-state
```

`resolve_options_with_provenance(...)` returns the same values plus a map of which
layer set each one (`ResolvedOption(value, source)`) — use it when debugging why an
option has a given value.

---

## 10. Dependencies and toolchains

Dependencies declared on a feature/implementation are installed through the workflow
step system ([foundation/components/dependencies.py](../src/audiagentic/foundation/components/dependencies.py)),
not ad-hoc shell calls. A dependency entry names:

- `probe` — how to detect it's present, e.g. `binary:pyright-langserver` or
  `all-binaries:a,b`.
- `toolchain` / `package` — how to install it (e.g. `uv` + a package name).

Platform/package-manager resolution lives in
[foundation/toolchains/detect.py](../src/audiagentic/foundation/toolchains/detect.py)
(`detect_pkg_manager`, `platform_key`, `uv_available`, `privilege_prefix`). The
dependency runner builds `SequenceStep`/`SelectStep` trees so the same declaration
works across platforms.

---

## 11. Lifecycle hooks

Optional integration points, all declared on the component descriptor as dotted
paths:

- `post-install: pkg.mod.fn` — `fn(project_root)` runs once after install.
- `lifecycle-observer: pkg.mod` — the **module** is imported at registration; it
  self-registers event-bus subscribers at import time. Use this to react to events
  (e.g. regenerate a projection when config changes).
- `lifecycle-hook: pkg.mod.fn` — `fn(event_type, payload, metadata)` dispatched per
  lifecycle event.
- `status-hook: pkg.mod.fn` — `fn(project_root) -> dict` feeding status reporting.

Keep observers idempotent — `register_all_components()` can run multiple times in a
process.

---

## 12. Step-by-step recipe

To add a new component `my-thing`:

1. **Descriptor.** Create `config/components/my-thing.yaml` with `type: component`,
    `id`, `display-name`, and `description`. The `detection-marker` and its
    `create-if-missing` marker file are auto-derived from `id` (and `scope` if
    harness-scoped). Add explicit `detection-marker:` and `files:` entries only
    when deviating from the default (§4–§5).
2. **Package.** Create `components/my_thing/` with `__init__.py`, `my_thing_api.py`
   (pure logic), and a `README.md` stating intent + capabilities.
3. **MCP server.** Add `my_thing_mcp.py` using `mcp_server(__name__)` and
   `run_mcp_server(...)`; declare it under `mcp-servers:` with `direct-tools`,
   `propagate`, and `instructions` (§6).
4. **Harness guidance.** Add `harness-instructions:` (tool catalog) and any
   `contributions:` doctrine blocks (§7).
5. **(Optional) Feature tier.** If the component has swappable backends or
   per-item capabilities: set `feature-kinds` and `implementation-cardinality` on
   the component, then add `implementation`, `feature`, and `binding` YAML files
   under `config/components/my-thing/` (§8).
6. **(Optional) Options.** Add `options-schema:` to whichever descriptors need
   typed settings (§9).
7. **(Optional) Dependencies & hooks.** Declare `dependencies:` on features/impls
   (§10) and any `lifecycle-observer` / `status-hook` / `post-install` (§11).
8. **Verify.** Run `register_all_components()` (it runs on any component CLI command
   or MCP server start) and confirm your descriptor loads without validation errors.
   Then exercise the MCP tools.

### Guardrails (from ARCHITECTURE_STANDARDS.md)

- Extensibility = dropping a YAML file. **Never** add Python import lists or
  `if/elif` chains branching on component IDs (§2, §5).
- MCP servers via `mcp_server(__name__)` only (§6).
- Generated/projected files go through a registered `(path, generator)` pair, not
  path-branching code (§7).
- Respect layering: foundation imports nothing from runtime/components; runtime
  imports no specific optional component (§1).

---

## 13. Reference components

Study these as worked examples:

- **`config/components/planning.yaml`** + `components/planning/` — a clean
  component with two MCP servers (management + tools), `contributions`,
  `implementation-cardinality: exclusive`, and a single implementation in
  `config/components/planning/planning-local-docs.yaml`.
- **`config/components/coding-lsp.yaml`** + `config/components/coding-lsp/` —
  the full feature tier: `feature-kinds`, implementations (`ag-lsp.yaml`), features
  (`python.yaml`), and bindings (`ag-lsp.python.yaml`) with projections and
  dependencies.
- **`config/components/project.yaml`** and **`session.yaml`** — always-on
  `core: true` components that cannot be uninstalled.
</content>
</invoke>
