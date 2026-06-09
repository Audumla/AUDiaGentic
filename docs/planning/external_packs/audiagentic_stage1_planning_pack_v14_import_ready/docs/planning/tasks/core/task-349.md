---
id: task-349
label: Freeze registry ownership and migration guardrails
state: draft
summary: Define which installer definitions are registry-owned and which current contracts remain product-owned, including backward-compatible migration boundaries.
spec_ref: spec-81
request_refs:
- request-32
standard_refs:
- standard-6
- standard-7
- standard-11
---

# Description

Keep generic installer growth in registries and resolution layers, not in widened canonical-id lists.

# Inputs

Read before starting:
- `docs/installer/current-state-inventory.md` (output from task-347)
- `docs/installer/noun-layer-assignment.md` (output from task-348)
- `spec-81` — architecture model spec
- `spec-82` — migration rules spec
- `standard-7` — migration and change-control standard
- `standard-11` — component architecture standard

# Blocker handling

- if `task-347` or `task-348` recorded unresolved path drift, cite it as a blocker in the migration seams section
- if spec-81 and spec-82 appear to conflict, record the conflict explicitly and defer to the narrower backward-compatibility rule until a consistency decision is made

# Output

Produce `docs/installer/registry-ownership-matrix.md` with these sections:

## Registry groups

For each registry group the installer owns:
- Group name (exact identifier)
- Which nouns it stores/manages
- Which layer it lives in
- Which components may read from it
- Which components may write to it

## Product-owned contracts (stable)

For each product-owned contract that remains stable:
- Contract name
- File path
- Whether installer reads it, writes it, or both
- Whether it requires migration or is already compatible

## Migration and normalization seams

For each seam between old config format and new installer-facing definitions:
- Old format (what exists today)
- New format (what installer expects)
- Migration function location (file:line or module path)
- Backward-compatibility rule (what must still work)

## Backward-compatibility rules

Explicit rules for backward compatibility:
- Rule 1: [description]
- Rule 2: [description]
- ...

# Provider variant discovery

Document the entry point discovery mechanism for provider variants:

- Entry point group names per registry group (e.g. `audiagentic.providers`, `audiagentic.protocols`)
- How the registry loader calls `importlib.metadata.entry_points(group=...)` to discover variants
- Confirm that no central registry file lists provider names — providers self-register via `pyproject.toml` entry points
- Show the entry point declaration format for a reference provider

This section replaces any approach that would maintain a hardcoded list of providers in a core registry file.

# What not to change

- do not widen canonical-id lists to include installer-owned nouns
- do not modify `src/audiagentic/foundation/contracts/canonical_ids.py`
- do not modify `src/audiagentic/foundation/config/provider_registry.py`
- do not change product-owned contract file paths or signatures
- do not introduce new registry groups without spec-81 approval
- do not remove existing registry groups
- do not change backward-compatibility rules for existing product features
- do not build a hardcoded central list of provider variants; use entry points for discovery

# Acceptance criteria

- [ ] every registry group lists exact read/write permissions per component
- [ ] every product-owned contract specifies installer access mode (read/write/both)
- [ ] every migration seam specifies old format, new format, and migration function location
- [ ] backward-compatibility rules are explicit and testable (not vague statements)
- [ ] no new canonical-id lists are widened; all installer-owned nouns go through registry groups
- [ ] reviewer can verify by checking that each registry group's read/write permissions match the layer assignments in task-348 output
