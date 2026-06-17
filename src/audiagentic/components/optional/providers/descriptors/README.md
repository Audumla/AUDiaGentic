# components/optional/providers/descriptors/

Provider descriptor model and registry.

## Intent

Define uniform metadata contract for every provider adapter.

## Capabilities

- Model provider identity, access mode, install recipes, MCP config shape, and surface hooks.
- Register descriptors from adapter packages into a shared registry.
- Give higher-level services one stable abstraction for provider discovery.

If you need to add a new provider, start by understanding `base.py` and `registry.py`, then inspect one existing adapter package.
