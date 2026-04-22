---
id: spec-85
label: Component lifecycle manifest schema and disable/uninstall semantics
state: draft
summary: Define the declarative manifest schema that each component registry entry must carry to support enable, disable, and uninstall operations, and specify what each operation does at runtime.
request_refs:
- request-32
standard_refs:
- standard-6
- standard-8
- standard-11
---

# Purpose

Components must not implement their own teardown code. Instead, each component declares what it owns in its registry entry. The installer backend reads the manifest and executes mutations. This keeps components passive and makes every lifecycle operation auditable through `--mode plan` before `--mode apply` runs.

# Discovery requirement

Before freezing the manifest schema, survey the current knowledge component configuration and event subscription model to identify what a real component actually owns. The schema must be grounded in at least one live component, not invented abstractly.

Minimum survey targets:

- `.audiagentic/knowledge/config/config.yml` — owned config structure
- `src/audiagentic/knowledge/__init__.py` — event subscription entry point
- `src/audiagentic/planning/app/api.py` lines 78-86 — where knowledge is wired in
- `.audiagentic/interoperability/config.yaml` — event bus config that knowledge subscribes to

# Scope

This spec defines:

- the manifest schema fields a component registry entry must carry for lifecycle support
- the semantics of `disable` (reversible) versus `uninstall` (teardown and remove)
- preservation policy defaults for user-generated data
- how a 3rd-party replacement component declares its installation slot

# Constraints

- components must not implement teardown functions; lifecycle is backend-executed from the manifest
- the manifest must be declarative YAML; no executable code in component definitions
- `disable` must be reversible without data loss by default
- `uninstall` must honor preservation policy before removing files
- the manifest schema must not reference AUDiaGentic-specific component ids; it must be generic
- backend handlers execute manifest instructions; they do not interpret component business logic
- `--mode plan` must be able to enumerate all actions from the manifest without executing any mutation

# Manifest schema

## Required fields for lifecycle support

Each component registry entry that supports lifecycle operations must declare:

```yaml
component: <component_id>
kind: component            # component | provider | protocol | surface
label: <human-readable name>
depends_on: []             # component ids that must be installed before this one
entry_point: null          # importlib.metadata entry point group and name, or null
owns:
  config_keys: []          # dotted config keys this component owns
  directories: []          # relative paths under project root
  event_subscriptions: []  # event topic patterns this component subscribes to
  python_package: null     # importable package name, or null if not applicable
disable:
  effect: set_config_flag  # set_config_flag | remove_subscriptions | both
  config_flag_path: null   # dotted path to write enabled: false, required if effect includes set_config_flag
uninstall:
  effect: remove           # remove | disable_only
  preserves: []            # relative paths under project root to keep even on full uninstall
  remove_python_package: false  # whether to pip-uninstall the package
```

## Field semantics

### kind

Classifies the component for filtering and grouping. Allowed values:

- `component` — core infrastructure unit (planning, jobs, event-bus, lifecycle, state, release)
- `provider` — AI provider adapter (depends on providers-framework component)
- `protocol` — wire-level protocol adapter (streaming, acp)
- `surface` — operator surface (cli, vscode, mcp)

### depends_on

List of component ids that must be installed and enabled before this component can be enabled. The reconcile flow validates dependencies before generating enable or install plan steps. If a dependency is missing, the plan step is blocked with an explicit error rather than silently skipping.

### entry_point

`importlib.metadata` entry point reference in the form `"group:name"`. Used by the registry loader to discover the component's implementation at runtime without hardcoding import paths. Null for components that are always present as part of the core package. Required for provider, protocol, and surface variants that self-register.

Example: `"audiagentic.providers:claude"` maps to the `claude` entry point in the `audiagentic.providers` group.

### owns.config_keys
Dotted paths to config values this component owns. On uninstall, these keys are removed from project config unless preserved. On disable, these keys remain but the enable flag is set.

### owns.directories
Directories under project root that this component owns. The installer will not remove directories listed here without an explicit uninstall with `--mode apply`.

### owns.event_subscriptions
Event topic patterns this component subscribes to. On disable, subscriptions are torn down. On re-enable, subscriptions are restored.

### owns.python_package
Importable package name. Used to verify installation state for `status` and `doctor` commands. Not removed on disable; removed on uninstall only if `remove_python_package: true`.

### disable.effect
- `set_config_flag`: write `enabled: false` at `config_flag_path`; package and files remain
- `remove_subscriptions`: tear down event subscriptions; leave config and files intact
- `both`: set config flag and remove subscriptions

### disable.config_flag_path
Dotted path to the `enabled` key in the component's config. Example: `knowledge.enabled`. Required when `disable.effect` includes `set_config_flag`.

### uninstall.effect
- `remove`: execute full teardown — remove subscriptions, remove owned directories not in `preserves`, remove config keys, optionally remove python package
- `disable_only`: treat uninstall as disable; do not remove files or directories (safe default for components with user data)

### uninstall.preserves
Paths to keep even on full uninstall. Designed for user-generated data (vault contents, custom config). Preservation is the default; removal requires explicit override flag at runtime.

### uninstall.remove_python_package
Whether to call the backend package manager to remove the python package. Defaults to false. Requires explicit `--remove-package` flag at runtime to activate.

## Reference example: knowledge component

```yaml
component: knowledge
kind: component
label: AUDiaGentic knowledge management
depends_on: [event-bus]
entry_point: null          # part of core package, not self-registered
owns:
  config_keys: [knowledge]
  directories: [.audiagentic/knowledge/]
  event_subscriptions: [planning.*]
  python_package: audiagentic.knowledge
disable:
  effect: both
  config_flag_path: knowledge.enabled
uninstall:
  effect: remove
  preserves: [.audiagentic/knowledge/vault/]
  remove_python_package: false
```

# Replacement slot

When a component is disabled to make room for a 3rd-party replacement, the replacement declares its own registry entry with the same `owns.event_subscriptions` patterns. The installer backend validates that only one component subscribes to each topic pattern in the active desired state.

```yaml
component: knowledge-external
kind: component
label: External knowledge management (3rd party)
depends_on: [event-bus]
entry_point: audiagentic.components:knowledge-external
replaces: knowledge
owns:
  event_subscriptions: [planning.*]
disable:
  effect: set_config_flag
  config_flag_path: knowledge-external.enabled
uninstall:
  effect: disable_only
```

The `replaces` field signals to the reconcile flow that enabling this component should disable its predecessor.

# Likely implementation surfaces

- new registry file: `.audiagentic/components/<component_id>.yml` per component
- schema validation: `src/audiagentic/foundation/contracts/` (new lifecycle contract)
- manifest loader: `src/audiagentic/runtime/lifecycle/` (new or extended module)
- backend executor: adjacent to existing lifecycle modules

# Do not define in this spec

- how the backend physically removes files (infrastructure concern, belongs in backend handler)
- which components exist in the registry (product concern, belongs in component registry files)
- CLI flag parsing (surface concern, belongs in spec-80 and task-350)
- reconcile flow orchestration (application concern, belongs in spec-82 and task-360)
