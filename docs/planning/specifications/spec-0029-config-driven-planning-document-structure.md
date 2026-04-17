---
id: spec-0029
label: Config-driven planning document structure
state: ready
summary: Refactor planning module managers to use config-driven document structure,
  relationships, and defaults
request_refs:
- request-0021
task_refs: []
standard_refs:
- standard-0006
- standard-0005
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

Assessment on 2026-04-17: specification remains valid but is now much narrower. Most acceptance criteria are implemented; the remaining substantive gap is relationship validation integration in manager create paths (`task-3253`).
