## Planning Item Creation Policy

**Planning items (requests, specs, plans, tasks) can only be created with explicit user approval.**

This applies to all agents and providers.

### Rules

- Do not autonomously create planning items during analysis, review, or exploration work
- If analysis suggests a new request or spec is needed, **report findings and ask for approval**
- Use the canonical tags (`@ag-plan`) to signal planning work that requires user direction
- Only create planning items in response to:
  - Explicit user instruction
  - Approved workflow prompts via canonical tags
  - Automated workflows with explicit approval

### Why

This prevents unintended expansion of the planning record and maintains user control over scope and provenance.

### Examples

**❌ Wrong:** Autonomously creating request-0027 during MCP tool review  
**✓ Right:** Reporting "MCP review found bulk operations opportunity" and asking for direction  
**✓ Right:** Creating request-0027 when user says "@ag-plan bulk MCP operations"
