# foundation/components/

Component descriptor and loader infrastructure.

## Intent

This area defines what a component is and how AUDiaGentic discovers it from packaged YAML.

## Capabilities

- Model component descriptors, managed files, MCP declarations, and harness instructions.
- Load descriptors from `src/audiagentic/config/components/`.
- Validate IDs and dependency links between components.
- Register descriptors into in-memory registry for lifecycle and status code.
- Expose dependency probes and reusable component dependency workflows.

This is metadata infrastructure, not component behavior itself.
