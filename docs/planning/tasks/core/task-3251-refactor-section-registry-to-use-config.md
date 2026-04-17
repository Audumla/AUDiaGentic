---
id: task-3251
label: Refactor section_registry to use config
state: done
summary: Replace hardcoded SECTION_KEYS with config-driven section lists
spec_ref: spec-0029
request_refs: []
standard_refs:
- standard-0005
- standard-0006
---




## Description

Refactor `section_registry.py` to load section lists from config instead of hardcoded `SECTION_KEYS` dict.

## Current State

`section_registry.py:3-24` contains hardcoded `SECTION_KEYS` dict:
- request: []
- spec: [purpose, scope, requirements, constraints, acceptance_criteria]
- plan: [objectives, delivery_approach, dependencies]
- task: [description, acceptance_criteria, notes, implementation_notes]
- wp: [objective, scope_of_this_package, inputs, instructions, required_outputs, acceptance_checks, non_goals]
- reference: [overview, usage, notes]

This is NOT used by managers (they have their own hardcoded templates), but the `list_sections()` function exists and should be config-driven for consistency.

## Required Changes

1. Remove `SECTION_KEYS` hardcoded dict
2. Update `list_sections(kind)` to load from config
3. Config must provide section lists for each kind
4. Support guidance-level overrides (light/standard/deep can have different sections)

## Acceptance Criteria

- `SECTION_KEYS` dict removed from section_registry.py
- `list_sections(kind)` loads from config
- `list_sections(kind, guidance)` optional parameter for guidance-level sections
- Backward compatible - existing calls without guidance param still work
- Config provides sensible defaults matching current hardcoded values
