# Example Project Scaffold

This example shows the expected tracked layout for an AUDiaGentic-enabled project.

```text
project-root/
  docs/
    specifications/
    implementation/
    releases/
    decisions/
  .audiagentic/
    project.yaml
    components.yaml
    providers.yaml
    prompt-syntax.yaml
    prompts/
    runtime/
```

Only `.audiagentic/runtime/` is git-ignored by default.

Phase 1.4 extends this minimal example into the full managed install baseline by defining how
prompt templates and provider instruction assets are synchronized into clean or existing
projects.
