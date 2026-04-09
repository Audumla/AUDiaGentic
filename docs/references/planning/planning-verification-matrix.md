# Planning verification matrix

This matrix defines the minimum verification expected when the installable profiles and documentation-surfaces overlay is applied to the `planning-module-implementation` branch.

## Scope

This matrix covers:
- profile-pack config loading and validation
- documentation surface discovery
- reference-doc discovery
- supporting-doc sidecar discovery
- MCP/helper compatibility for the added documentation calls
- section and subsection access semantics
- documentation-sync requirement queries

## Minimum smoke checks

### Config
- `documentation.yaml` loads without schema errors
- profile packs under `.audiagentic/planning/config/profile-packs/` load without schema errors
- no overlap is implied between planning profile packs and execution workflow profiles

- profile-pack files load from a top-level `profile_pack` key
- a known profile pack returns non-empty doc-sync requirements
- missing `documentation.yaml` degrades safely
- unknown profile-pack ids fail clearly or return empty with an explicit note
- request profiles can be listed and read from config

### Helper / MCP surface
- documentation surfaces can be listed
- a single documentation surface can be queried by id
- reference docs can be listed
- support docs can be listed
- `workflow` can be passed through task and work-package creation wrappers without signature mismatch

### Sections
- top-level section get/set/append works on a planning document
- subsection lookup works on heading-path best effort semantics
- subsection access failures are reported clearly when the heading path is not found

### Support docs
- support docs are discoverable under `docs/planning/supporting/`
- support-doc metadata is readable
- support docs are not treated as core planning kinds by scan/index/validator in this phase

### Documentation sync
- required documentation updates can be queried by work kind/profile
- pending documentation updates can be reported without mutating project docs
- changelog remains a minimal documentation surface in the shipped profiles

## Out of scope for this phase
- turning support docs into first-class planning kinds
- structured canonical subsection bodies beyond heading-path best effort
- automatic mutation of project documentation on completion
- splitting a separate project-doc MCP from planning MCP
