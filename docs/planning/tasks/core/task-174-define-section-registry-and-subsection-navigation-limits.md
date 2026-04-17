---
id: task-174
label: Define section registry and subsection navigation limits
state: done
summary: Review section and subsection operations so the docs reflect current heading-based
  behavior and future extension seams accurately
spec_ref: spec-5
---








# Description

Review the proposed section registry and subsection helpers and document what is truly supported today versus what remains best-effort.

**Status: IMPLEMENTED**

All implementation work for task-0174 is complete:
- Section registry in section_registry.py defines SECTION_KEYS per planning kind
- split_section_path() supports both dot and slash notation, normalizes to consistent parts
- Helper functions: get_section(), set_section(), append_section(), get_subsection()
- Subsection navigation is explicitly best-effort and heading-based (not canonical data model)
- _find_section() searches all heading levels (## through ######) for flexible heading structures
- Missing section/subsection returns {"found": False, "content": ""}
- Tests verify:
  - Top-level section lookup works
  - Nested subsection lookup with dot notation works
  - Nested subsection lookup with slash notation works
  - Deep nested subsections work (description.notes.deep detail)
  - Missing paths return found=False
- Docs in planning-verification-matrix.md document subsection behavior as best-effort
- Junior implementer knows this is an ergonomic layer, not a canonical data model

# Acceptance Criteria

1. The task explains how current heading-string matching works in `PlanningAPI.update_content`.
2. The task states whether the proposed section registry is canonical or advisory in this phase.
3. The task lists any body-shape, heading-depth, or formatting limitations that affect correctness.
4. The task defines the minimum tests needed for section and subsection behavior.
5. The task explicitly treats subsection addressing as heading-path best-effort behavior in this phase.

# Notes

- Suitable with revision.
- The current pack adds useful ergonomics, but the implementation is still layered on top of literal markdown headings rather than a first-class structured section model.
- The docs must not promise more determinism than the branch can actually provide.

# Implementation Notes

- Keep language precise: subsection support is best-effort until deeper API work exists.
- Add explicit examples for missing-section, replace-section, and nested-subsection behavior.
- Avoid presenting section keys as a source of truth unless validator and writer behavior also use them.


# Execution Checklist

Implementation type: section-navigation helper code + tests + docs.

Files to change:
- `src/audiagentic/planning/app/section_registry.py`
- `tools/planning/tm_helper.py`
- `docs/references/planning/planning-verification-matrix.md`
- `tests/integration/planning/test_tm_helper_extensions.py`

Steps:
1. Keep section addressing explicitly best-effort and heading-based for this phase.
2. Support the documented section-path syntax consistently. If docs mention dot paths, runtime code must accept dot paths.
3. Add tests for top-level section lookup, missing section behavior, nested subsection lookup, and path-format handling.
4. Do not promise a canonical structured section model unless the underlying API also changes.
5. Document any assumptions about heading depth or formatting.

Do not change:
- core markdown storage format
- planning object schemas just to encode section structure
- validator behavior beyond what the helper actually supports

Verification:
- `pytest -q tests/integration/planning/test_tm_helper_extensions.py`
- manually confirm subsection examples in docs match the helper behavior

Done means:
- subsection examples in docs work in practice
- failures for missing paths are clear
- a junior implementer knows this is an ergonomic layer, not a canonical data model
