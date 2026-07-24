# Check-In Summary

Total changes: 2

- Pi's MCP-exclusive isolation patch now refuses to apply on unsupported adapter versions instead of silently warning, with test coverage confirming isolated agent jobs never touch your native Pi config.
- Removed the last public/MCP-exposed universal provider-reconcile API now that its dependencies are satisfied, and fixed a component-boundary leak in the agents gateway.
