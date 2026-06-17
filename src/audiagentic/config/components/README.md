# config/components/

Component descriptor package data.

## Intent

Declare installable components in YAML so runtime lifecycle code can stay data-driven.

## Contents

- `core/` descriptors for always-on project/session components.
- `optional/` descriptors for pluggable components and their packaged companion assets.

Descriptor YAML defines managed files, dependencies, MCP servers, harness instructions, hooks, and install markers. `foundation/components/loader.py` is primary reader.
