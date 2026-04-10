# Planning Standards Map

This reference maps the standards families that make the planning surface easier to use across different kinds of work.

Use this as a selection guide:
- apply the universal defaults broadly
- add activity standards when the work is non-coding or process-heavy
- add implementation standards only when the language or tooling is actually in scope

## Universal Defaults

These should usually remain active for planning-led work in this repository.

- `standard-0001` — planning documentation and maintenance standard
- `standard-0002` — documentation surface and content organization standard
- `standard-0003` — versioning and changelog standard

## Activity Standards

These are good candidates for future standards that support recurring non-coding work.

- planning record quality
  - what a good request, spec, plan, work package, or task must contain
  - required scope, non-goals, sequencing, risks, and verification
- review findings and evidence
  - findings-first review output
  - severity, file references, residual risks, and missing-test callouts
- verification and test evidence
  - what counts as acceptable validation
  - when manual verification is acceptable and how to record it
- migration and change control
  - source-to-target mapping
  - rollout/cutover notes
  - archival and backward-compatibility expectations
- research and spike output
  - how to capture options, assumptions, unknowns, and recommendation quality
- release readiness
  - release notes, versioning, changelog, verification, and rollback visibility
- audit and compliance
  - traceability, evidence capture, exception handling, and ownership
- design and UX review
  - design intent, accessibility expectations, acceptance examples, and validation screenshots

## Implementation Standards

These are good candidates when a project actually uses the relevant runtime or toolchain.

- Python implementation standard
- TypeScript or JavaScript implementation standard
- PowerShell scripting standard
- configuration and schema authoring standard
- testing standard
- API contract standard

## How To Apply Standards

- attach broad defaults at the spec or plan level
- attach focused activity standards at the work-package or task level
- attach language-specific standards only where the implementation actually uses that stack
- avoid attaching every standard everywhere; too many inherited standards reduce clarity

## MCP Usage

Useful planning MCP calls for standards work:

- `tm_list_standards()` to discover available standards quickly
- `tm_get_standard(standard_id)` to inspect a standard with its body and metadata
- `tm_standards(item_id)` to see the effective standards inherited by a planning item

## Recommended Next Additions

If we keep growing the standards surface, the highest-value next standards are:

1. review findings and evidence standard
2. verification and test evidence standard
3. planning record quality standard
4. Python implementation standard
5. configuration and schema authoring standard
