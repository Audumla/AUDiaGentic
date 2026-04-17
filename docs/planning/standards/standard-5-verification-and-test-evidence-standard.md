---
id: standard-5
label: Verification and test evidence standard
state: ready
summary: Default standard for how implementation and planning work should record verification
  scope, evidence, and gaps.
---

# Standard

Default standard for how implementation and planning work should record verification scope, evidence, and known gaps.

# Source Basis

This standard is derived from repository validation practice and general software verification principles, adapted for planning-led work in AUDiaGentic-based projects.

Sources:

- Repository planning validation and test practices
- [Google Testing Blog — Test Sizes](https://testing.googleblog.com/2010/12/test-sizes.html)
- [pytest documentation](https://docs.pytest.org/en/stable/)
- Project verification matrix references

# Requirements

1. Every meaningful change must identify how it was verified.
2. Verification records must separate:

   - automated tests that were run
   - manual checks that were performed
   - checks that were expected but not run

3. When verification is partial, the record must state what remains unverified and why.
4. Verification must be proportional to risk. High-risk changes need stronger evidence than low-risk documentation updates.
5. Planning work must include validation of planning integrity where relevant: schema validation, link integrity, and task/work-package consistency.
6. Claims of completeness must not be made without matching evidence.
7. If a command, test suite, or validation pass fails, the failure must be recorded with the reason rather than hidden or skipped.
8. Smoke test: after any meaningful code change, verify the project compiles or imports cleanly before marking work complete:

   - Python: `python -m py_compile <file>` or `python -c "import <module>"`
   - JS/TS: `npx tsc --noEmit` or `node --check <file>`
   - Shell: `bash -n <script>`
   - Tests: `python -m pytest tests/ -q` or project equivalent

9. Architectural verification must confirm compliance with standard-0011 where applicable:

   - no outward imports from inner layers
   - config-driven behavior testable with different config values
   - extension points exercised by at least one non-default implementation test
   - bootstrap wiring covered by at least one integration test

10. MCP server changes must verify tool registration and schema generation using the mcp CLI or test harness, per standard-0008.

# Default Rules

- Prefer concrete command or tool evidence where possible.
- Keep verification records short but specific.
- Distinguish between smoke coverage and comprehensive coverage.
- Treat missing tests and missing validation as explicit gaps, not as implied acceptance.
- Do not mark a task done if smoke tests have not been run.

# Minimum Verification Shape

- what changed
- what was verified
- what commands or checks were run
- what was not verified
- current residual risk

# Non-Goals

- Forcing all work to have the same test depth.
- Replacing release-specific signoff processes.
- Treating manual checks as invalid when automation is not yet practical.
