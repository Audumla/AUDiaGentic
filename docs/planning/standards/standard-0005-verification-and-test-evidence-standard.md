---
id: standard-0005
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
- repository planning validation and test practices
- project verification matrix references

# Requirements

1. Every meaningful change should identify how it was verified.
2. Verification records must separate:
- automated tests that were run
- manual checks that were performed
- checks that were expected but not run
3. When verification is partial, the record must state what remains unverified and why.
4. Verification should be proportional to risk. High-risk changes need stronger evidence than low-risk documentation updates.
5. Planning work should include validation of planning integrity where relevant, such as planning schema validation, link integrity, or task/work-package consistency.
6. Claims of completeness should not be made without matching evidence.
7. If a command, test suite, or validation pass fails, the failure should be recorded with the important reason instead of being hidden.

# Default Rules

- Prefer concrete command or tool evidence where possible.
- Keep verification records short but specific.
- Distinguish between smoke coverage and comprehensive coverage.
- Treat missing tests and missing validation as explicit gaps.

# Minimum Verification Shape

- what changed
- what was verified
- what commands or checks were run
- what was not verified
- current residual risk

# Non-Goals

- forcing all work to have the same test depth
- replacing release-specific signoff processes
- treating manual checks as invalid when automation is not yet practical
