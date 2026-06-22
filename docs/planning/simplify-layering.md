---
id: plan-simplify-layering
label: Simplify component/feature/option layering
state: draft
summary: Address structural concerns in the component/feature/option layering to reduce complexity, improve maintainability, and eliminate drift risks
---

# Objective

Reduce structural complexity in the component/feature/option layering. Target: smaller descriptors, typed contributions, provenance-aware options, and reduced lock contention.

---

## Concern 1: Descriptor bloat

**Description:** `ComponentDescriptor` carries 20+ fields. Most components use only a subset (e.g., `session` uses MCP servers and harness instructions but not external MCP servers or dependencies). The fat dataclass forces every consumer to carry unused fields and obscures which fields are relevant for a given component.

**Proposed solution:** Split `ComponentDescriptor` into composable mixins:
- `BaseDescriptor` — id, display name, description, detection marker, scope, core flag
- `FileDescriptorMixin` — files, lifecycle modes
- `McpServerMixin` — mcp servers, external mcp servers
- `LifecycleMixin` — hooks, observers, post-install
- `FeatureMixin` — implementation cardinality, feature kinds

Compose via nested dataclasses or a flat descriptor that delegates to focused sub-objects. Reduces per-component memory footprint and makes validation scoped to relevant fields.

---

## Concern 2: Feature descriptor type dispatch is string-based

**Description:** The loader dispatches on `type` string (`feature`, `implementation`, `binding`). A typo silently falls through to `VAL-FDESC-012`. No compile-time or schema-level enforcement.

**Proposed solution:** Define an enum `DescriptorType { FEATURE, IMPLEMENTATION, BINDING }` and parse the YAML `type` field into it during loading. Reject unknown values immediately with a specific error code rather than falling through to a generic "unsupported type" error.

---

## Concern 3: Options resolution lacks provenance

**Description:** `resolve_options` merges layers (descriptor defaults -> component options -> feature/implementation state) but discards which layer provided each value. When debugging why an option has an unexpected value, there's no audit trail.

**Proposed solution:** Return a `ResolvedOption` dataclass `(value, source: str)` alongside the resolved dict, where `source` is one of `"descriptor-default"`, `"component-state"`, `"feature-state"`, `"implementation-state"`. Add an MCP tool `get_option_provenance` for debugging. Keep the existing `dict[str, Any]` return for callers that don't need provenance, but make the enriched version available.

---

## Concern 4: Monolithic state file creates contention

**Description:** All features and implementations share `.audiagentic/config/runtime/features.yaml`. Every mutation acquires the same file lock. As the number of components grows, unrelated mutations (e.g., enabling a language in LSP vs. setting a ledger option) contend on the same lock.

**Proposed solution:** Shard state by component: `.audiagentic/config/runtime/features/{parent}.yaml`. Each component gets its own lock file. The `mutate_feature_state` API remains the same but routes to the appropriate shard. Add a lightweight index file `features.yaml` that maps component IDs to shard paths for discovery. Backward migration: on first write, detect the legacy monolithic file and migrate contents to shards.

---

## Concern 5: Contributions schema is underspecified

**Description:** The `contributions` field in component YAML is a raw list of dicts with no typed schema. Fields like `preferred-targets`, `config:`, and `content:` have implicit contracts. No validation that `preferred-targets` values are valid surface types. The `agent-jobs.yaml` contributions include `config:` references that point to other YAML files, but there's no model for this.

**Proposed solution:** Define a `ContributionDescriptor` dataclass with typed fields:
- `id` (str, required)
- `owner` (str, required)
- `kind` (enum: `rule`, `content`, `config-reference`, default `content`)
- `title` (str)
- `preferred_targets` (tuple of validated surface types)
- `content` (union: inline body dict, or config reference path)
- `skill_content_file` (str, optional)

Add post-load validation that checks `preferred-targets` against known surface types and that `config:` references resolve to existing files.

---

## Concern 6: External dependencies lack version pinning

**Description:** The `source-control` component declares platform-specific installers (`winget`, `scoop`, `brew`, etc.) but never pins versions. A package manager update could install an incompatible version of `git`, `gh`, or `uv`.

**Proposed solution:** Add an optional `version` field to dependency declarations:
```yaml
dependencies:
  gh:
    display-name: GitHub CLI
    probe: binary:gh
    version: ">=2.60.0"
    via:
      winget: GitHub.cli
```
The dependency installer checks the installed version against the constraint and warns if unsatisfied. Keep it optional — components without version requirements don't need to specify it.

---

## Concern 7: Harness instructions duplicate MCP server instructions

**Description:** Each component declares instructions for both MCP servers (`instructions` field) and harness (`harness-instructions`). These are semantically similar but expressed differently, creating a drift risk. For example, `agent-ledger.yaml` has MCP instructions about `record_change_event` and separate harness instructions that repeat the same tool list.

**Proposed solution:** Derive `harness-instructions` from MCP server declarations automatically. The harness instruction renderer reads `direct-tools` and `tool-descriptions` from MCP server declarations and generates the harness section. Components can still provide custom harness instructions, but the default is derived. Add a validation check that flags fields where MCP instructions and harness instructions describe different tool sets.

---

## Concern 8: Deep state nesting is error-prone

**Description:** Feature state uses 3-level nesting: `component -> features[kind][id]` and `component -> implementations[id] -> features[kind][id]`. The `get_implementation_feature_enabled_explicit` function requires 30 lines of defensive `isinstance` checks and `.get()` chaining. This nesting makes it easy to introduce None dereference bugs.

**Proposed solution:** Flatten the state structure to use composite keys:
```yaml
coding-lsp:
  features:
    "language:python":
      enabled: true
      options: {}
    "language:cpp":
      enabled: false
  implementations:
    ag-lsp:
      enabled: true
      features:
        "language:python":
          enabled: true
```
Or introduce a `FeaturePath` dataclass (`parent`, `scope`, `kind`, `id`) that encapsulates the nesting logic and provides safe accessors. The flattened key approach is simpler and avoids deep nesting while preserving the logical grouping.

---

## Prioritization

| Priority | Concern | Effort | Risk if unchanged |
|----------|---------|--------|-------------------|
| P0 | #5 Contributions schema | Medium | Surface drift, silent misconfigurations |
| P0 | #3 Options provenance | Low | Debugging difficulty grows with adoption |
| P1 | #1 Descriptor bloat | High | Technical debt, but not breaking |
| P1 | #8 State nesting | Medium | Bug surface area, but contained |
| P2 | #4 State sharding | Medium | Contention is theoretical at current scale |
| P2 | #7 Harness instructions | Low | Drift risk, but detectable |
| P3 | #2 Type enum | Low | Minor robustness improvement |
| P3 | #6 Version pinning | Low | External risk, not immediate |
