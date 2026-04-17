---
id: request-25
label: Config-driven planning document structure
state: distilled
summary: Refactor planning module to use config-driven document structure, relationships,
  and defaults instead of hardcoded values
source: code-review
guidance: standard
current_understanding: Initial intake captured; requirements are understood well enough
  to proceed.
open_questions:
- What exact outcome is required?
- What constraints or non-goals apply?
- How will success be verified?
spec_refs:
- spec-0029
---




## Problem Statement

The planning module (`src/audiagentic/planning/app/`) contains significant hardcoded logic for:

1. **Document structure** - Each manager has hardcoded body templates:
   - `spec_mgr.py:18` - Hardcoded sections: Purpose, Scope, Requirements, Constraints, Acceptance Criteria
   - `task_mgr.py:34` - Hardcoded sections: Description, Acceptance Criteria, Notes
   - `plan_mgr.py:28` - Hardcoded sections: Objectives, Delivery Approach, Dependencies
   - `wp_mgr.py:13` - Hardcoded sections: Objective, Scope, Inputs, Instructions, Required Outputs, Acceptance Checks, Non-Goals
   - `std_mgr.py:9` - Hardcoded sections: Standard, Requirements

2. **Section registry** - `section_registry.py:3-24` contains hardcoded `SECTION_KEYS` dict mapping kinds to section lists

3. **Relationship assumptions** - Each manager hardcodes which refs are required/optional:
   - `spec_mgr.py` requires `request_refs`, `task_refs`
   - `plan_mgr.py` requires `spec_refs`, `work_package_refs`
   - `wp_mgr.py` requires `plan_ref`, `task_refs`
   - `task_mgr.py` has optional `spec_ref`, `parent_task_ref`

4. **Default values** - `req_mgr.py:21-45` has hardcoded default open questions and understanding text per profile

## Current Config State

The config already has some structure in `.audiagentic/planning/config/profiles.yaml`:
- Guidance levels with `spec_sections` and `task_sections` (lines 12-17, 40-45, 69-74)
- Object profiles with `required_sections` and `suggested_sections` (lines 161-169)
- Profile defaults for requests (lines 98-106, 112-120, etc.)

But this config is **not used** by the managers - they ignore it and use hardcoded values instead.

## Goals

1. Make all document structure (sections, body templates) config-driven
2. Make relationship requirements (required refs, optional refs) config-driven
3. Make default values (open questions, understanding text) fully config-driven
4. Remove hardcoded SECTION_KEYS from section_registry.py
5. Allow profiles/guidance levels to override document structure
6. Maintain backward compatibility with existing documents

## Proposed Changes

### Phase 1: Config Schema Extensions

1. Extend `profiles.schema.json` to support full document structure config:
   - Add `document_templates` section for each kind (request, spec, task, plan, wp, standard)
   - Add `relationships` section defining required/optional refs per kind
   - Add `defaults` section for default values per kind

2. Create new `document-structure.schema.json` for reusable templates

### Phase 2: Core Infrastructure

1. Create `TemplateEngine` class in `src/audiagentic/planning/app/template_engine.py`:
   - Load templates from config
   - Render body content from templates with variable substitution
   - Support section ordering, required/suggested flags

2. Create `RelationshipConfig` class in `src/audiagentic/planning/app/rel_config.py`:
   - Load relationship requirements from config
   - Validate refs against config rules
   - Provide API for managers to check required/optional refs

3. Update `Config` class to expose new APIs:
   - `document_template(kind, profile=None, guidance=None)` -> template config
   - `relationship_config(kind)` -> relationship requirements
   - `defaults_for(kind, profile=None)` -> default values

### Phase 3: Manager Refactoring

1. Refactor each manager to use config-driven approach:
   - `RequestMgr` - already partially uses config, needs cleanup
   - `SpecMgr` - replace hardcoded body with template engine
   - `TaskMgr` - replace hardcoded body with template engine
   - `PlanMgr` - replace hardcoded body with template engine
   - `WPMgr` - replace hardcoded body with template engine
   - `StandardMgr` - replace hardcoded body with template engine

2. Update `section_registry.py` to load from config instead of hardcoded dict

3. Update `rel_mgr.py` to use config for relationship validation

### Phase 4: Config Migration

1. Migrate existing hardcoded values to config:
   - Move SECTION_KEYS to `profiles.yaml` or new `document-structure.yaml`
   - Move body templates to config
   - Move relationship requirements to config

2. Update existing profile configs to use new structure

3. Add migration script for existing projects

### Phase 5: Testing & Validation

1. Add tests for template engine
2. Add tests for relationship config
3. Add integration tests for each manager
4. Validate existing documents still work

## File Changes

### New Files
- `src/audiagentic/planning/app/template_engine.py`
- `src/audiagentic/planning/app/rel_config.py`
- `src/audiagentic/foundation/contracts/schemas/planning/document-structure.schema.json`

### Modified Files
- `src/audiagentic/planning/app/config.py` - add new APIs
- `src/audiagentic/planning/app/section_registry.py` - load from config
- `src/audiagentic/planning/app/rel_mgr.py` - use config for validation
- `src/audiagentic/planning/app/spec_mgr.py` - use template engine
- `src/audiagentic/planning/app/task_mgr.py` - use template engine
- `src/audiagentic/planning/app/plan_mgr.py` - use template engine
- `src/audiagentic/planning/app/wp_mgr.py` - use template engine
- `src/audiagentic/planning/app/std_mgr.py` - use template engine
- `src/audiagentic/planning/app/req_mgr.py` - cleanup, use config fully
- `.audiagentic/planning/config/profiles.yaml` - extend with document structure
- `src/audiagentic/foundation/contracts/schemas/planning/profiles.schema.json` - extend schema

## Risks

1. **Breaking changes** - Existing code using managers may break if signatures change
2. **Config complexity** - New config structure may be complex for users
3. **Migration burden** - Existing projects need to migrate configs
4. **Performance** - Template rendering may be slower than hardcoded strings

## Mitigation

1. Maintain backward compatibility in manager APIs
2. Provide sensible defaults in config
3. Provide migration scripts and documentation
4. Template rendering is minimal overhead for document creation

# Notes

Assessment on 2026-04-17: request remains valid and still open. `TemplateEngine` and `RelationshipConfig` are implemented and stale task records for that work have been completed. Remaining valid work is narrower: finish schema/config cleanup (`task-0329`) and integrate relationship validation into manager create paths (`task-3253`).
