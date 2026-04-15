# planning/

## Purpose
Planning workflows and task management for AUDiaGentic. Owns the full lifecycle of planning items: requests, specifications, plans, tasks, work packages, and standards.

## Ownership
- Planning item creation, update, mutation, and deletion
- Item state tracking (pending, in-progress, complete, archived)
- Planning profiles and workflow configuration
- MCP tool surface for planning operations
- Planning data persistence under `.audiagentic/planning/`

## Must NOT Own
- Job execution orchestration (→ `execution`)
- Provider selection or dispatch (→ `interoperability`)
- Release audit or change ledger (→ `release`)
- Runtime state or job records (→ `runtime/state`)

## Allowed Dependencies
- `foundation/contracts` — schema validation and canonical error types
- `foundation/config` — project configuration loading

## Code That Belongs Here
- Planning API and domain model (`app/`, `domain/`, `fs/`)
- MCP server for planning tool surface
- Profile configuration and workflow overlays
- TM helper utilities (`tools/planning/tm_helper.py` bridges here)

## Code That Does NOT Belong Here
- Anything that launches or executes an agent job
- Streaming or provider communication
- Release bootstrap or audit generation

## Related Domains
- `execution` — jobs reference planning items by ID
- `release` — completed items feed the change ledger
- `foundation` — shared contracts and validation

---

# Config-Driven Planning Structure

The planning module uses a **config-driven approach** where document templates, validation rules, and relationship constraints are defined in YAML configuration files rather than hardcoded in Python.

## Architecture Overview

This design enables:
- **Extensibility**: Add new guidance levels, profiles, or document structures without code changes
- **Consistency**: Centralized configuration ensures all managers use the same rules
- **Customization**: Projects can override defaults by modifying config files
- **Maintainability**: Business rules are visible and editable without touching code

## Config-Driven Components

### 1. Document Templates (`TemplateEngine`)

**Location**: `.audiagentic/planning/config/profiles.yaml` → `planning.document_templates`

Document body templates are rendered based on kind and optional guidance level:

```yaml
document_templates:
  spec:
    default: "# Purpose\n\n\n# Scope\n\n\n# Requirements\n\n"
    by_guidance:
      light: "# Purpose\n\n\n# Scope\n\n\n# Requirements\n\n"
      standard: "# Purpose\n\n\n# Scope\n\n\n# Requirements\n\n\n# Constraints\n\n"
      deep: "# Purpose\n\n\n# Scope\n\n\n# Requirements\n\n\n# Constraints\n\n\n# Acceptance Criteria\n\n"
```

**Usage**:
```python
from .template_engine import TemplateEngine
engine = TemplateEngine(config)
body = engine.render("spec", guidance="deep")
```

**Managers using TemplateEngine**: `spec_mgr`, `task_mgr`, `plan_mgr`, `wp_mgr`, `std_mgr`, `req_mgr`

### 2. Guidance Levels

**Location**: `.audiagentic/planning/config/profiles.yaml` → `planning.guidance_levels`

| Level | Target | Philosophy |
|-------|--------|------------|
| `light` | Experienced implementors | Minimal scaffolding |
| `standard` | AI agents, mid-level devs | Balanced structure |
| `deep` | Junior devs, complex work | Comprehensive docs |

Each level defines: `spec_sections`, `task_sections`, `acceptance_criteria_depth`, `semantics`

### 3. Request Profiles

**Location**: `.audiagentic/planning/config/profiles.yaml` → `planning.profiles`

Defines request types with stack topology: `enhancement`, `feature`, `issue`, `fix`

### 4. Relationship Configuration

**Location**: `.audiagentic/planning/config/profiles.yaml` → `planning.relationship_config`

Defines which kinds can reference which, and required references.

### 5. Required Sections

**Location**: `.audiagentic/planning/config/profiles.yaml` → `planning.required_sections`

Minimum required sections for each kind (enforced by validator).

### 6. State Propagation

**Location**: `.audiagentic/planning/config/state_propagation.yaml`

Defines how state changes propagate through relationships.

### 7. Workflows (State Machines)

**Location**: `.audiagentic/planning/config/workflows.yaml`

Defines valid states and transitions for each kind.

## Configuration Files

| File | Purpose | Required |
|------|---------|----------|
| `planning.yaml` | Core planning settings | Yes |
| `profiles.yaml` | Guidance, profiles, templates, relationships | Yes |
| `workflows.yaml` | State machine definitions | Yes |
| `automations.yaml` | Automation rules | Yes |
| `state_propagation.yaml` | State propagation rules | Yes |
| `documentation.yaml` | Documentation settings | No |

## How to Extend

### Add a New Guidance Level

1. Add to `profiles.yaml` under `planning.guidance_levels`
2. Add document templates under `planning.document_templates`
3. Optionally update `planning.yaml` default

### Add a New Request Profile

1. Add to `profiles.yaml` under `planning.profiles`
2. Use with: `python -m audiagentic.planning.cli new request --profile <name>`

### Configure State Propagation

Add rules to `state_propagation.yaml`:

```yaml
rules:
  - trigger:
      kind: plan
      state: done
    propagate:
      - target_field: work_package_refs
        state: done
```

## Best Practices

1. **Use guidance levels appropriately**: light for quick tasks, standard for typical work, deep for complex/critical work
2. **Choose the right profile**: enhancement (broad), feature (bounded), issue (bugs), fix (corrections)
3. **Maintain backward compatibility**: Keep existing guidance levels, extend don't replace
4. **Leverage state propagation**: Configure automatic state updates through relationships

## Testing

After modifications:

```python
from .config import Config
config = Config(root)
assert not config.validate(), "Config validation failed"

from .template_engine import TemplateEngine
engine = TemplateEngine(config)
assert engine.render("spec", guidance="standard")

from .api import PlanningAPI
api = PlanningAPI(root, test_mode=True)
errors = api.validator.validate_all()
assert not errors, f"Validation failed: {errors}"
```

## References

- [Plan 0014](../../docs/planning/plans/plan-0014-implement-config-driven-planning-structure.md)
- [Spec 0029](../../docs/planning/specifications/spec-0029-config-driven-planning-document-structure.md)
- [Request 0021](../../docs/planning/requests/request-0021.md)
