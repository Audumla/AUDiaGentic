---
id: wp-22
label: 'Phase 5: Testing'
state: done
summary: Add tests for config-driven structure
plan_ref: plan-18
task_refs:
- ref: task-331
  seq: 1000
standard_refs:
- standard-6
---










## Objective

Add comprehensive tests for the config-driven planning structure implemented in plan-0014 phases 1-4.

## Scope of This Package

- Test TemplateEngine functionality with all document kinds and guidance levels
- Test RelationshipConfig validation
- Test Config class methods (required_sections, document_template, relationship_rules)
- Test manager integration with config-driven approach
- Validate backward compatibility with existing documents

## Inputs

- Phase 1-4 implementation complete (wp-0016 through wp-0019)
- Config files in `.audiagentic/planning/config/`
- Existing test patterns in `tools/planning/tests/test_tm_helper.py`

## Instructions

1. Create test file at `tools/planning/tests/test_config_driven_structure.py`
2. Test all Config methods added in phases 1-4
3. Test document templates vary by guidance level (light/standard/deep)
4. Test relationship rules for all document kinds
5. Test manager integration with config-driven approach
6. Validate backward compatibility
7. Ensure all tests pass with `pytest tools/planning/tests/test_config_driven_structure.py`

## Required Outputs

- Test file with comprehensive coverage
- All tests passing
- Test documentation in task notes

## Acceptance Checks

- [x] 42 tests created and passing
- [x] All document kinds tested (request, spec, plan, wp, task, standard)
- [x] All guidance levels tested (light, standard, deep)
- [x] Relationship rules validated
- [x] Manager integration verified
- [x] Backward compatibility confirmed

## Non-Goals

- Performance testing
- Integration with external systems
- UI/UX testing
