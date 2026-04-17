---
id: wp-19
label: 'Phase 4: Config Migration'
state: done
summary: Migrate hardcoded values to config files
plan_ref: plan-14
task_refs:
- ref: task-333
  seq: 1000
standard_refs:
- standard-6
---






# Objective


# Scope of This Package


# Inputs


# Instructions
## Completed Work

1. **Analyzed remaining hardcoded references**:
   - `api.py`: Kind-based routing is necessary for API design - ACCEPT AS-IS
   - `ext_mgr.py`: Transitive standard ref computation is business logic - ACCEPT AS-IS
   - `states.py`: CANONICAL_KINDS is a constant, not logic - ACCEPT AS-IS
   - `val_mgr.py`: REQ_SECTIONS migrated to config

2. **Migrated REQ_SECTIONS to config**:
   - Added `required_sections` to `.audiagentic/planning/config/profiles.yaml`
   - Added `required_sections()` method to `Config` class
   - Updated `val_mgr.py` to load required sections from config
   - Removed hardcoded `REQ_SECTIONS` dict

3. **Created comprehensive README**:
   - Documented config-driven approach overview
   - Explained all config-driven components (templates, guidance, profiles, relationships, sections, state propagation, workflows)
   - Provided examples for extending guidance levels, profiles, templates
   - Listed best practices and testing procedures
   - Added references to planning documents

4. **Fixed indentation issues**:
   - `plan_mgr.py`: Fixed indentation in create() method
   - `req_mgr.py`: Fixed indentation in _build_body() and create() methods
   - `wp_mgr.py`: Fixed indentation in create() method

## Verification

```bash
# Test config method
python -c "from src.audiagentic.planning.app.config import Config; c = Config(Path('.')); print(c.required_sections('spec'))"
# Output: ['Purpose', 'Scope', 'Requirements', 'Constraints', 'Acceptance Criteria']

# Test validator method
python -c "from src.audiagentic.planning.app.val_mgr import Validator; v = Validator(Path('.')); print(v._get_required_sections('task'))"
# Output: ['Description']
```
# Required Outputs


# Acceptance Checks


# Non-Goals
