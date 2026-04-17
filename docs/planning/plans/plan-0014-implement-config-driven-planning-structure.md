---
id: plan-0014
label: Implement config-driven planning structure
state: done
summary: Plan to refactor planning module to use config-driven document structure
spec_refs:
- spec-0029
request_refs:
- request-25
work_package_refs:
- ref: wp-0016
- ref: wp-0017
- ref: wp-0018
- ref: wp-0019
- ref: wp-0020
standard_refs:
- standard-0006
---














# Objectives
Eliminate all hardcoded document structure from planning module managers. Replace with config-driven approach that allows profiles and guidance levels to control document templates, sections, and relationships. Maintain backward compatibility while enabling flexible configuration.
# Delivery Approach
Delivery Approach

Work will proceed in 5 phases:

1. **Config Schema Extensions** (wp-0016): Extend profiles.schema.json and create document-structure.schema.json to support document templates, sections, and relationships in config.

2. **Core Infrastructure** (wp-0017): Create TemplateEngine class for rendering document bodies from config templates, and RelationshipConfig class for validating refs against config rules.

3. **Manager Refactoring** (wp-0018): Refactor all managers (SpecMgr, TaskMgr, PlanMgr, WPMgr, StandardMgr) to use TemplateEngine instead of hardcoded body templates. Update section_registry.py to load from config.

4. **Config Migration** (wp-0019): Migrate existing hardcoded values (SECTION_KEYS, body templates) to profiles.yaml. Provide migration path for existing projects.

5. **Testing** (wp-0020): Add tests for TemplateEngine, RelationshipConfig, and refactored managers. Validate backward compatibility.

Each phase builds on the previous. Phase 1 must complete before Phase 2. Phase 2 must complete before Phase 3. Phase 3 and 4 can run in parallel. Phase 5 validates all previous phases.
# Dependencies
wp-0016


# Status Summary
## Completed Phases

- ✅ **Phase 1 (wp-0016)**: Config schema extensions complete
- ✅ **Phase 2 (wp-0017)**: TemplateEngine and RelationshipConfig created
- ✅ **Phase 3 (wp-0018)**: All managers refactored to use TemplateEngine
- ✅ **Phase 4 (wp-0019)**: Config migration complete
  - ✅ REQ_SECTIONS migrated to profiles.yaml
  - ✅ val_mgr.py updated to load from config
  - ✅ Config method `required_sections()` added
  - ✅ Comprehensive README created
  - ✅ Hardcoded reference analysis complete (api.py, ext_mgr.py, states.py accepted as-is)
- ✅ **Phase 5 (wp-0020)**: Testing complete
  - ✅ 42 tests created in `tools/planning/tests/test_config_driven_structure.py`
  - ✅ All tests passing
  - ✅ Coverage: Config methods, document templates, guidance levels, relationship rules, manager integration, backward compatibility

## Key Deliverables

1. **Config-driven templates**: All managers use `TemplateEngine` to render document bodies
2. **Config-driven sections**: Required sections loaded from `profiles.yaml` → `required_sections`
3. **Guidance level support**: Templates vary by light/standard/deep guidance levels
4. **Comprehensive documentation**: README explains config-driven approach, how to extend, and best practices
5. **Comprehensive tests**: 42 tests validating all aspects of config-driven structure
6. **Backward compatibility**: Existing documents remain valid, manager APIs unchanged

## Files Modified

### Config
- `.audiagentic/planning/config/profiles.yaml` - Added `required_sections`, `document_templates`, `relationship_config`

### Code
- `src/audiagentic/planning/app/config.py` - Added `required_sections()`, `document_template()`, `relationship_rules()`, `can_reference()`, `required_refs()` methods
- `src/audiagentic/planning/app/val_mgr.py` - Removed hardcoded `REQ_SECTIONS`, loads from config
- Fixed indentation issues in `plan_mgr.py`, `req_mgr.py`, `wp_mgr.py`

### Tests
- `tools/planning/tests/test_config_driven_structure.py` - 42 comprehensive tests

### Documentation
- `src/audiagentic/planning/README.md` - Comprehensive config-driven documentation
