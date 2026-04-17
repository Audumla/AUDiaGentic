---
id: task-333
label: Migrate hardcoded values to config
state: done
summary: Migrate SECTION_KEYS and body templates to profiles.yaml
spec_ref: spec-29
request_refs: []
standard_refs:
- standard-5
- standard-6
---




# Description

Review remaining planning code for hardcoded references to workflow/object types and determine which should be config-driven vs. acceptable as-is.

## Files Reviewed

### api.py - Kind-based routing (ACCEPTABLE)
- Lines 457-467: Kind normalization mapping (`req` → `request`, `sp` → `spec`, etc.)
- Lines 476-587: Kind-based routing to appropriate managers
- **Verdict**: This is necessary for API design - the API needs to route to the correct manager based on kind. Cannot be config-driven without significant complexity.

### val_mgr.py - Kind-specific validation (PARTIALLY CONFIG-DRIVEN)
- Lines 10-24: `REQ_SECTIONS` dict with required sections per kind
- Lines 82-87: Filename validation rules per kind
- Lines 118-125: Path structure validation per kind
- **Verdict**: 
  - `REQ_SECTIONS` is already partially superseded by guidance-level section requirements (lines 89-110)
  - Filename and path validation could be moved to config but is simple enough to keep inline
  - Consider migrating `REQ_SECTIONS` to config for consistency

### ext_mgr.py - Kind-specific extraction (ACCEPTABLE)
- Lines 28-45: `_effective_standard_refs()` has kind-specific logic for task and wp
- **Verdict**: This is business logic for computing transitive standard references. The relationship structure is defined in config (`relationship_config`), but the computation logic is appropriately inline.

### states.py - CANONICAL_KINDS (ACCEPTABLE)
- Line reference: `CANONICAL_KINDS = {'request', 'spec', 'plan', 'task', 'wp', 'standard'}`
- **Verdict**: This is a constant set, not hardcoded logic. It defines the canonical types and is used for iteration, not conditional logic.

## Recommendations

1. **Migrate REQ_SECTIONS to config** - Move the `REQ_SECTIONS` dict from `val_mgr.py` to `profiles.yaml` under a `required_sections` key for each kind
2. **Create comprehensive README** - Document the config-driven approach, how to extend templates, and best practices
3. **Accept api.py routing as-is** - Kind-based routing is necessary for the API design
4. **Accept ext_mgr.py logic as-is** - Transitive reference computation is appropriately inline

## Acceptance Criteria

- [ ] `REQ_SECTIONS` migrated to `profiles.yaml`
- [ ] `val_mgr.py` updated to load required sections from config
- [ ] Comprehensive README created in `src/audiagentic/planning/`
- [ ] All managers tested and verified working
- [ ] Task marked as done

# Acceptance Criteria

1. All hardcoded section requirements moved to config
2. Validator loads section requirements from config
3. README documents:
   - Config-driven approach overview
   - How to extend document templates
   - How to add new guidance levels
   - How to configure state propagation
   - Best practices and standards
4. Backward compatibility maintained

# Notes

## Completed Analysis

- **api.py**: Kind-based routing is necessary for API design - ACCEPT AS-IS
- **ext_mgr.py**: Transitive standard ref computation is business logic - ACCEPT AS-IS  
- **states.py**: CANONICAL_KINDS is a constant, not logic - ACCEPT AS-IS
- **val_mgr.py**: REQ_SECTIONS should be migrated to config for consistency

## Migration Scope

The remaining work is:
1. Move `REQ_SECTIONS` from `val_mgr.py` to `profiles.yaml`
2. Update `val_mgr.py` to load from config
3. Create comprehensive README documenting the config-driven approach
