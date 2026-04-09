---
id: standard-0008
label: Python implementation standard
state: ready
summary: Default standard for Python implementation work in AUDiaGentic-based projects,
  covering code quality, tests, and change boundaries.
---

# Standard

Default standard for Python implementation work in AUDiaGentic-based projects.

# Source Basis

This standard is derived from the repository's existing Python code style and test expectations, adapted for practical implementation work in this codebase.

Sources:
- current repository Python modules and tests
- repository validation and review expectations

# Requirements

1. Python changes must preserve existing module boundaries and avoid unnecessary rewrites.
2. New behavior should be added in the smallest coherent seam that matches the current architecture.
3. Public or tool-facing behavior changes should include focused tests where practical.
4. Error handling should fail clearly and specifically rather than hiding important problems.
5. Optional configuration should remain optional in runtime behavior and validation unless the spec explicitly changes that contract.
6. Helper layers and wrappers must stay aligned with the underlying API signatures they expose.
7. Changes must not silently broaden scope into unrelated runtime, lifecycle, or provider behavior.
8. Tests and verification should be proportional to risk, with direct coverage for regressions being fixed.

# Default Rules

- Prefer explicit code over clever shortcuts.
- Keep helper functions small and single-purpose where practical.
- Reuse existing managers and app-layer seams instead of introducing parallel abstractions without need.
- Add comments only where the code would otherwise be hard to follow.
- Keep file and function names aligned with repository conventions.

# Verification Expectations

- run the smallest focused tests that exercise the changed behavior
- run broader validation when the change affects planning structure or shared configuration
- record what was not verified if full coverage was not practical

# Non-Goals

- mandating one formatter or linter policy beyond what the repo already uses
- replacing language-specific framework standards in downstream installed projects
- forcing every small change to carry broad integration-test coverage
