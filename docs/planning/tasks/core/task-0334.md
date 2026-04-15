---
id: task-0334
label: Add tests for config-driven structure
state: done
summary: Add tests for TemplateEngine, RelationshipConfig, and manager refactoring
spec_ref: spec-0029
request_refs: []
standard_refs:
- standard-0005
- standard-0006
---





# Description

Create comprehensive tests for the config-driven planning structure implemented in plan-0014 phases 1-4. Tests must validate:

1. **TemplateEngine functionality**:
   - Template rendering with variable substitution for all document kinds
   - Guidance level variations (light/standard/deep) produce different section structures
   - Profile variations (feature/issue/fix/enhancement) override templates correctly
   - Error handling for missing templates or invalid variables

2. **RelationshipConfig functionality**:
   - Required ref validation for each document kind
   - Optional ref acceptance
   - Error messages for missing required refs
   - Config loading from relationships.yaml

3. **Config class new methods**:
   - `required_sections(kind)` returns correct sections from profiles.yaml
   - Document template loading works for all kinds and guidance levels
   - Defaults loading from config profiles

4. **Refactored managers**:
   - spec_mgr, task_mgr, plan_mgr, wp_mgr, std_mgr, req_mgr all use TemplateEngine
   - Created documents have correct section structure based on config
   - No hardcoded templates remain in manager classes

5. **Backward compatibility**:
   - Existing documents remain valid after refactoring
   - Manager APIs unchanged - create() signatures compatible
   - Default config values match previous hardcoded values

# Acceptance Criteria

1. Test file created at `tools/planning/tests/test_config_driven_structure.py`
2. All tests pass with `pytest tools/planning/tests/test_config_driven_structure.py`
3. Test coverage includes:
   - TemplateEngine with all 6 document kinds (request, spec, plan, wp, task, standard)
   - TemplateEngine with all 3 guidance levels (light, standard, deep)
   - RelationshipConfig validation for required and optional refs
   - Config.required_sections() method for all kinds
   - Manager integration tests verifying TemplateEngine usage
   - Backward compatibility validation
4. No hardcoded values in tests - all test data from config files
5. Tests document expected behavior for future reference

# Notes
## Test Results

All 42 tests pass successfully:

- **TestConfigRequiredSections**: 7 tests - Validates required_sections() method for all document kinds
- **TestConfigDocumentTemplates**: 10 tests - Validates document templates vary by guidance level (light/standard/deep) for all 6 kinds
- **TestConfigRelationshipRules**: 6 tests - Validates relationship rules (can_reference, required_refs)
- **TestConfigGuidanceLevels**: 7 tests - Validates guidance level configuration and defaults
- **TestConfigStandardDefaults**: 4 tests - Validates standard defaults for spec, task, plan, wp
- **TestManagerIntegration**: 5 tests - Validates manager create() methods work with config-driven approach
- **TestBackwardCompatibility**: 3 tests - Validates existing documents remain valid and APIs unchanged

## Test Coverage

1. ✅ TemplateEngine functionality with all 6 document kinds
2. ✅ Guidance level variations (light/standard/deep) produce different section structures
3. ✅ RelationshipConfig validation for required and optional refs
4. ✅ Config.required_sections() method for all kinds
5. ✅ Manager integration tests verifying config usage
6. ✅ Backward compatibility validation
7. ✅ All test data from config files, no hardcoded values
