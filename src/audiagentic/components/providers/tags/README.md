# components/providers/tags/

Prompt launch tag parsing for provider selection.

## Intent

Normalize first-line workflow tags into stable provider routing metadata.

## Capabilities

- Define tag model and parsing rules.
- Load provider tag definitions from registry/config.
- Resolve raw prompt tags into canonical provider and surface choices.

This area is small but important because prompt routing must stay stable across provider surfaces.
