# runtime/config/

Layered runtime config loading.

## Intent

Provide small, reusable helpers for reading YAML config across package-default, user-global, and project-local tiers.

## Capabilities

- Read YAML files safely from disk.
- Deep-merge layered config sources.
- Resolve AUDiaGentic home paths and project-local namespace files.

This area should stay generic. Component-specific config semantics belong in the component that consumes them.
