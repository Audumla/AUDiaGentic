# Agent Actions

Agent actions are the prompt-triggered workflows surfaced onto provider skill files.
Actions are owned by components. Providers do not define action names directly.

## How it works

1. A component declares action descriptor files in its component YAML under `contributions:` or legacy `actions:`.
2. Each action descriptor is a YAML file with `type: action`.
3. The providers surface layer loads all declared actions and projects their skills, prompts, and instruction blocks onto installed provider surfaces.
4. Surfaces are regenerated with `skill_surfaces`.

Actions and providers stay decoupled. The surface layer bridges them at render time.

## Add action to existing component

### 1. Create action files

Put the action descriptor and related files under the component-owned config area.

Example for `agent-jobs`:

```text
src/audiagentic/config/components/optional/agent-jobs/
  ag-my-action.yaml
  ag-my-action-skill.md
  ag-my-action-prompt.md
```

Use a short lowercase hyphenated `tag-id`.

### 2. Write action descriptor

```yaml
type: action
contract-version: v1
tag-id: ag-my-action
display-name: My Action
description: One-line description
aliases:
  - my-action
  - ma
directives:
  - id
  - target
  - context
requires-body: true
is-generic-tag: false
is-review-tag: false
skill-content-file: ag-my-action-skill.md

files:
  - path: .audiagentic/skills/ag-my-action/skill.md
    lifecycle: required-managed
    description: canonical skill source

content:
  body: |
    - First non-empty line routes to `ag-my-action`.
    - Describe the action contract here.

prompts:
  - name: default
    content-file: ag-my-action-prompt.md
```

Notes:
- `content.body` is the primary instruction block pushed into provider surfaces.
- Additional instruction blocks can be declared with `instructions:` or legacy `surface-contributions:`.

### 3. Write skill file

```markdown
---
name: ag-my-action
description: One-line description for skill metadata.
---

# My Action skill

Trigger:
- first non-empty line resolves to `ag-my-action` or an alias

Do:
- describe what this action should do

Do not:
- describe what must not happen
```

### 4. Declare action in component YAML

Example in `src/audiagentic/config/components/optional/agent-jobs.yaml`:

```yaml
contributions:
  - id: agent-jobs/prompt-tags
    owner: agent-jobs
    title: Prompt tag doctrine
    preferred-targets:
      - instruction
    content:
      body: |
        - First non-empty line is the routing tag.
  - config: components/optional/agent-jobs/ag-implement.yaml
  - config: components/optional/agent-jobs/ag-plan.yaml
  - config: components/optional/agent-jobs/ag-my-action.yaml
```

The `config:` path is relative to `src/audiagentic/config/`.

### 5. Regenerate provider surfaces

```sh
python -m audiagentic.components.optional.providers.skill_surfaces --project-root .
```

## Add actions to new component

1. Create the action YAML and supporting files under that component's config directory.
2. Add `- config: ...` entries to the component YAML's `contributions:` list, or legacy `actions:` list.
3. Register the component normally through the component config tree.
4. Reconcile provider surfaces.

## Remove or modify action

Remove:
1. Delete the `config:` entry from the owning component YAML.
2. Delete the action files.
3. Regenerate provider surfaces.

Modify:
1. Edit the action YAML or skill file.
2. Regenerate provider surfaces.

## Project-level override

Project-local override path:

```text
.audiagentic/skills/<tag-id>/skill.md
```

This overrides only the skill body, not the action descriptor metadata.

## Discovery chain

```text
providers reconcile / skill_surfaces run
  └─ load_all_tags()
       └─ register_all_components()
       └─ for each ComponentDescriptor with yaml_path:
            └─ read component YAML
                 └─ contributions: or actions:
                      └─ config: <action yaml>
                           └─ load_tag_from_yaml(...)
                                └─ register(ActionDescriptor)
```

## Internals

| File | Role |
|------|------|
| `providers/tags/base.py` | `ActionDescriptor` dataclass |
| `providers/tags/registry.py` | In-process action registry |
| `providers/tags/loader.py` | Loads action YAMLs declared by components |
| `providers/skill_surfaces.py` | Renders provider-facing skill surfaces |

Backward-compatibility note:
- Some internals still use the old “tag” naming in symbols such as `load_all_tags()` and `load_tag_from_yaml()`.
- The live descriptor type is `action`, and the live component wiring uses `contributions:` / `actions:` entries with `config:` references.
