---
id: request-10
label: Optimize planning single-item lookup and extract token usage
state: closed
summary: Improve planning API and MCP efficiency by replacing repeated full-repo scans
  for single-item reads with index-backed lookup, and refine extract/show surfaces
  to reduce unnecessary body payloads and side-effect writes.
source: codex
current_understanding: Every single-item read in the planning API currently triggers
  a full scan_items() pass — rglob('*.md') plus parse_markdown() on every planning
  document. ext_mgr.show() does one full scan, and ext_mgr.extract() does a second
  scan then calls show() internally, resulting in a triple scan per extract call.
  The idx_mgr already generates per-kind index files containing id, label, state,
  and path, but these are never read for lookups. A single global lookup index keyed
  by id would allow _find(), show(), and extract() to resolve items via one JSON read
  and one targeted markdown parse, eliminating O(n) scans for single-item operations.
  Additionally, extract() always includes full body content and always writes an artifact
  to disk, which is unnecessary overhead for callers that only need metadata. Adding
  explicit include_body and write_to_disk controls, and exposing a lean head(id) surface
  in both the helper and MCP layers, would significantly reduce token usage for AI
  consumers.
open_questions: []
context: 'Derived from review of planning API and MCP read paths. Key concerns: repeated
  scan_items() usage in single-item operations, extract() always including body and
  persisting extracts, and need for lean single-item MCP/read surfaces.'
spec_refs:
- spec-007
standard_refs:
- standard-0001
meta:
  current_understanding: 'All optimization work complete and verified: lookup.json
    generates correctly, lookup(id) and head(id) helpers implemented with proper fallback,
    single-item read paths refactored to use index-backed lookup eliminating O(n)
    scans, extract() controls (include_body, write_to_disk) fully exposed in API/MCP/helper,
    all 15 test cases passing.'
---




# Understanding

Every single-item read in the planning API currently triggers a full `scan_items()` pass — `rglob('*.md')` plus `parse_markdown()` on every planning document. `ext_mgr.show()` does one full scan, and `ext_mgr.extract()` does a second scan then calls `show()` internally, resulting in a triple scan per extract call.

The `idx_mgr` already generates per-kind index files containing `id`, `label`, `state`, and `path`, but these are never read for lookups. A single global lookup index keyed by id would allow `_find()`, `show()`, and `extract()` to resolve items via one JSON read and one targeted markdown parse, eliminating the O(n) scan cost for all single-item operations.

Additionally, `extract()` always includes full body content and always writes an artifact to `.audiagentic/planning/extracts/{id}.json`, which is unnecessary overhead for callers that only need metadata.

# Open Questions

- None — requirements and constraints are fully understood.

## Outcome Required

1. A global lookup index (`lookup.json`) generated alongside existing per-kind indexes, keyed by id with at minimum `{id, kind, path, label, state, deleted}`.
2. An internal `lookup(id)` resolver in `api.py` that reads the index and parses only the target file.
3. `_find()`, `show()`, and `extract()` refactored to use the lookup path for single-item reads.
4. A lean `head(id)` surface returning only index-level metadata (no markdown doc parse).
5. `extract()` gains explicit `include_body` and `write_to_disk` controls.
6. MCP layer exposes distinct low-token (head/show) vs body-inclusive (extract) read tools.

## Constraints and Non-Goals

- Markdown files remain the canonical source of truth; indexes are accelerators only.
- Bulk operations (`validate()`, `index()`, `status()`) may continue to use full scans — this request does not require eliminating those.
- Per-instance scan caching for bulk operations is out of scope for this request.
- Existing create surfaces are not in scope.
- Backward compatibility should be preserved where practical; if extract() defaults change, a transition path must exist.

## Notes

Index staleness is a known risk: if a markdown file is edited without running `index()`, the lookup index will be stale. The implementation should document that index freshness is the caller's responsibility, and optionally fall back to scan on a cache miss.

Spec-0043 contains the detailed design and acceptance criteria.
