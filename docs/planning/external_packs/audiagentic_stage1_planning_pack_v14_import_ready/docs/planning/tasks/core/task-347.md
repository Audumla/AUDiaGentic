---
id: task-347
label: Freeze current-state inputs and ownership boundaries
state: draft
summary: Record the current repo contracts, config files, lifecycle surfaces, and hardcoded hot spots that the installer slice must respect or route around.
spec_ref: spec-81
request_refs:
- request-32
standard_refs:
- standard-6
- standard-11
---

# Description

List the current repo-owned contracts and the installer-facing seams that must not reuse them as source of truth.

# Inputs

Read before starting:
- `src/audiagentic/channels/cli/main.py` — current CLI entrypoint
- `src/audiagentic/foundation/contracts/canonical_ids.py` — canonical-id definitions
- `src/audiagentic/foundation/config/provider_registry.py` — provider registry
- `src/audiagentic/execution/jobs/profiles.py` — profile execution
- `tools/validation/validate_ids.py` — ID validation
- `.audiagentic/*.yaml` — current project config files
- supporting note: v13 review findings from the predecessor external pack

# Output

Produce `docs/installer/current-state-inventory.md` with these sections:

## Current product-owned contracts

For each contract, document:
- File path and line range
- Contract name and purpose
- Whether it is read-only for installer or requires migration

## Installer-facing seams

For each seam where installer logic must interface with existing code:
- Seam name
- Existing file/function to call
- What the installer must not modify

## Hardcoded hot spots

For each hardcoded dependency:
- Location (file:line)
- What it hardcodes
- Risk level (high/medium/low)
- Recommended installer-side workaround

## Richer-project preservation risks

For each risk:
- Risk description
- Affected feature
- Mitigation strategy

## Blockers and drift

If any expected source file is missing, moved, or materially different from planning assumptions, document:
- missing or changed path
- expected role
- discovered replacement path if found
- whether execution can continue safely
- recommended follow-up

# Setup instruction

Create `docs/installer/` if it does not exist before writing outputs for this pack. Later tasks may assume this directory already exists.

# Blocker handling

- if a referenced source file does not exist, search for the replacement path and record the result under `Blockers and drift`
- if no replacement is found, stop making assumptions about that surface and mark it as a blocker
- if two source surfaces conflict with each other, record the conflict and prefer the live repo behavior over stale assumptions
- do not invent function signatures or module paths that are not discoverable in the live repo

# What not to change

- do not rewrite or replace any product-owned config contracts
- do not propose installer growth by widening canonical-id lists
- do not modify `src/audiagentic/foundation/contracts/canonical_ids.py`
- do not modify `src/audiagentic/foundation/config/provider_registry.py`
- do not modify `src/audiagentic/execution/jobs/profiles.py`
- do not propose changes to existing CLI entrypoint behavior
- do not introduce new canonical-id formats without spec-81 approval

# Acceptance criteria

- [ ] every source file listed in Inputs is cited in the output with at least one finding or blocker note
- [ ] no product-owned contract is proposed for rewrite or replacement
- [ ] each installer-facing seam specifies the exact function/signature to call
- [ ] each hardcoded hot spot has a risk level and a workaround
- [ ] `docs/installer/` creation is explicit
- [ ] any missing or changed source path is captured under `Blockers and drift`
- [ ] reviewer can verify by cross-referencing output file paths against the source files listed in Inputs
