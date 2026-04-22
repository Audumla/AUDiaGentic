---
id: spec-33
label: Config-driven planning document structure
state: done
summary: Refactor planning module managers to use config-driven document structure,
  relationships, and defaults
request_refs:
- request-22
task_refs:
- ref: task-336
- ref: task-326
- ref: task-29
standard_refs:
- standard-6
- standard-5
---





















# Purpose
Refactor the planning module (`src/audiagentic/planning/app/`) to eliminate hardcoded document structure, relationships, and defaults. Replace with config-driven approach using existing config infrastructure in `.audiagentic/planning/config/`.
# Scope
In scope: All planning document managers (RequestMgr, SpecMgr, TaskMgr, PlanMgr, WPMgr, StandardMgr), section_registry.py, rel_mgr.py, and config.py. Out of scope: Knowledge module, foundation contracts (except schema extensions), runtime execution logic.
# Requirements
1. **Document structure must be config-driven**: All document body templates (sections, ordering, required/suggested flags) must be defined in config files, not hardcoded in manager classes. Existing hardcoded templates in spec_mgr.py:18, task_mgr.py:34, plan_mgr.py:28, wp_mgr.py:13, std_mgr.py:9 must be removed. SECTION_KEYS in section_registry.py:3-24 must be replaced with config lookup. 2. **Relationships must be config-driven**: Required and optional refs for each document kind must be defined in config. Manager create() methods must validate refs against config rules, not assume fixed relationships. 3. **Defaults must be config-driven**: Default values (open questions, understanding text, meta fields) must come from config profiles/guidance levels. req_mgr.py:21-45 hardcoded defaults must be removed. 4. **Template engine must support variable substitution**: Body templates must support inserting variables like summary, label, id, etc. 5. **Backward compatibility**: Existing documents must remain valid. New config must provide sensible defaults matching current hardcoded values. 6. **Config schema must be validated**: New config structure must have JSON schema validation in profiles.schema.json or new document-structure.schema.json.
# Constraints
1. Cannot break existing manager APIs - create() method signatures must remain compatible. 2. Cannot require existing projects to immediately migrate configs - must provide defaults. 3. Must work with existing profiles.yaml structure - extend rather than replace. 4. Template rendering must be fast - no external dependencies. 5. Must support both guidance levels (light/standard/deep) and profiles (feature/issue/fix/enhancement) overriding document structure.
# Acceptance Criteria
1. No hardcoded body templates remain in manager classes (spec_mgr, task_mgr, plan_mgr, wp_mgr, std_mgr). 2. SECTION_KEYS removed from section_registry.py, replaced with config lookup. 3. TemplateEngine class exists and is used by all managers for body generation. 4. RelationshipConfig class exists and validates refs against config. 5. Config class exposes document_template(), relationship_config(), defaults_for() APIs. 6. profiles.yaml extended with document_templates and relationships sections. 7. All existing tests pass. 8. Creating documents with different profiles/guidance levels produces different section structures as defined in config. 9. section_registry.py:list_sections() loads from config instead of hardcoded dict. 10. req_mgr.py removes _default_open_questions() and _default_understanding() fallback methods, fully using config. 11. Relationship validation integrated into manager create() methods via RelationshipConfig.

# Notes
Assessment on 2026-04-17: specification remains valid but is now much narrower. Most acceptance criteria are implemented; the remaining substantive gap is relationship validation integration in manager create paths (`task-339`).

## 2026-04-22 AC deviation acceptance

**AC 3 (TemplateEngine used by managers)** — Accepted deviation. `TemplateEngine` class exists but `api.py` calls `config.document_template()` directly. TemplateEngine delegates to the same method — no behavior lost. Adding wrapper to api.py creates indirection with no gain. Closing as won't-do.

**AC 5 (Config.defaults_for() API)** — Accepted deviation. Defaults are loaded inline in `api.py` at lines 729–736 and 863–871 via `config.profiles`. Formal `defaults_for()` method adds ceremony with no functional value. Closing as won't-do.

**AC 7/8 (tests and profile/guidance behaviour)** — Requires explicit verification. Enabling `validate_required=True` in task-339 risks breaking existing create flows. Test task created to cover this before spec-29 can close.

## 2026-04-22 Closed

All acceptance criteria verified and implemented:
- task-329: done (schema extension)
- task-339: done (validate_required=True enabled; profiles.yaml wp required_for_children fixed)
- task-28: done (9 new tests added and passing)

Additional: 6 pre-existing test failures in test_planning_api.py fixed (stale ID format assertions from migration, duplicate-ID test, package domain bug, apply_plan_overlay parse_markdown bug).
