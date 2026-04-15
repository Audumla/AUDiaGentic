---
id: spec-007
label: Index-backed planning lookup and lean extract/read surfaces
state: ready
summary: Design and implement a lookup-index-based single-item read path for planning
  objects, add lean metadata fetch capability, and refine extract semantics so body
  inclusion and persistence are explicit and token-efficient.
request_refs:
- request-010
task_refs:
- ref: task-0221
- ref: task-0222
- ref: task-0223
- ref: task-0224
- ref: task-0225
- ref: task-0226
standard_refs:
- standard-0006
- standard-0005
---










# Purpose

Reduce planning API and MCP overhead for single-item reads by replacing repeated full-repository markdown scans with index-backed lookup, and make read surfaces more token-efficient for AI consumers. The intended outcome is lower I/O cost, clearer tool semantics, and smaller default payloads without disrupting the existing planning object model.

# Scope

This specification covers:

- single-item lookup for planning objects by id
- index-backed resolution from id to kind/path/summary metadata
- refactoring `show()` and `extract()` to use direct lookup instead of repeated `scan_items()` passes
- adding a lean single-item metadata fetch surface for low-token consumers
- refining extract semantics so body inclusion and extract persistence are explicit controls
- corresponding MCP surface refinement so AI consumers can choose the cheapest read tool for the job

This specification does not require redesigning the planning kinds, replacing the existing per-kind indexes, or eliminating full scans from bulk operations such as validation or full index rebuilds.

# Requirements

1. The planning system must provide a canonical single-item lookup path that resolves a planning item id to its kind and file path without scanning and parsing every planning markdown file.

2. Index generation must produce and maintain a single global lookup index at `.audiagentic/planning/indexes/lookup.json` that is sufficient to support single-item resolution without consulting the per-kind index files. The lookup data must be keyed by planning item id and must include at least `id`, `kind`, `path`, `label`, and `state`, and should also preserve `deleted` status when available.

3. Single-item read paths must use the lookup index rather than full-repository scans whenever the operation only needs one planning item.

4. `show()` must remain a metadata-focused read surface and must not include markdown body content by default.

5. The system must expose a lean single-item metadata fetch surface, such as `head(id)` or `get(id)`, that returns only the minimum metadata needed for low-token callers. The intended default shape is:

```json
{
  "id": "spec-007",
  "kind": "spec",
  "label": "Index-backed planning lookup and lean extract/read surfaces",
  "state": "draft",
  "path": "docs/planning/specifications/spec-007-index-backed-planning-lookup-and-lean-extract-read-surfaces.md"
}
```

6. `extract()` must continue to support optional related-item and resource expansion via `with_related` and `with_resources`.

7. On the refined read surface described in this specification, `with_related` and `with_resources` must both default to `False`. If any transitional compatibility path is required for older callers, it must be exposed separately and documented explicitly rather than changing the default contract for the refined surface.

8. `extract()` must make markdown body inclusion an explicit control. The implementation must support an `include_body` flag or an equivalent separation between metadata reads and body-inclusive reads.

9. `extract()` must make persistence of generated extract artifacts explicit. The implementation must support a `write_to_disk` or equivalent control so callers can obtain extract data without always writing `.audiagentic/planning/extracts/{id}.json`.

10. The MCP layer must expose read surfaces that make the low-token path obvious. At minimum, the tool surface should distinguish:
- lean single-item metadata reads
- metadata/frontmatter reads
- body-inclusive extraction

11. Existing behavior should remain backward-compatible where practical. If defaults remain body-inclusive, related-inclusive, or persistence-inclusive during transition, the implementation should still provide explicit lower-cost paths for new callers.

12. Lookup behavior must define how stale indexes are handled. On lookup miss or index/path inconsistency, the implementation must either:
- fall back to a direct repository scan and optionally repair the lookup index, or
- fail with a clear stale-index error and document that `index()` or `reconcile()` is required

The chosen behavior must be consistent across helper and MCP single-item read paths.

13. Bulk operations that genuinely require all items, including `validate()`, `index()`, and similar corpus-wide operations, may continue to use full scans. This work does not need to eliminate those scans.

14. The design should leave room for later per-instance scan caching for bulk operations, but caching is not required to complete this specification.

# Constraints

The solution must preserve the existing planning file layout and markdown-based source of truth. Lookup indexes are accelerators, not replacements for canonical planning documents.

The MCP and helper APIs should be refined incrementally rather than redesigned wholesale. Existing create surfaces are already appropriately split by kind and do not need to be reworked as part of this specification.

The implementation should avoid introducing surprising side effects into read operations. If extract persistence remains enabled by default for compatibility, the lower-side-effect path must still be straightforward and documented.

The design should optimize for both runtime efficiency and AI token efficiency. Smaller payload shapes are a first-class goal, especially for single-item MCP reads.

Per-instance caching for scan-heavy bulk operations is a secondary optimization and should not delay the lookup/index improvements for single-item reads.

# Acceptance Criteria

- A planning item can be resolved by id through an index-backed lookup path without invoking a full `scan_items()` traversal across the repository.
- `_find()` and the internal implementation of single-item read surfaces are refactored to use the lookup path for single-item resolution.
- `show()` returns metadata/frontmatter for a single item without including markdown body content.
- A lean single-item metadata fetch surface exists and is available to helper and/or MCP consumers.
- `extract()` supports explicit control over whether markdown body content is included.
- `extract()` supports explicit control over whether an extract artifact is written to disk.
- `with_related` and `with_resources` remain optional and default to `False` on the refined read surface.
- MCP consumers have a clear low-token read path for single-item access and are not forced to call body-inclusive extraction for ordinary metadata reads.
- Existing bulk operations that require all planning items continue to function correctly.
- Tests cover index-backed single-item resolution, lean single-item reads, body/persistence controls for extract behavior, and MCP/helper behavior for the refined read surfaces.
