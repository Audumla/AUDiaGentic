---
id: request-0004
label: Enhance planning profiles and documentation surfaces
state: captured
summary: Prepare an implementation-ready planning pack for installable profile packs, documentation surfaces, supporting docs, and MCP documentation operations without implementing the runtime changes yet
source_refs:
  - planning_profiles_docs_complete_pack_v3
current_understanding: The current planning module already has config splitting, a planning API, and an MCP surface, but the proposed documentation/profile extension overlaps existing concepts and must stay safe for template installation into other repositories.
open_questions:
  - Should supporting docs become first-class indexed planning objects in this phase, or remain sidecar docs with structured metadata?
  - Which documentation surfaces are seeded on install versus managed or hybrid during runtime in installed projects?
  - Should request profiles (feature and issue) live beside profile packs, or remain a narrower classification layer under requests only?
---

# Notes

- This request is documentation-first and implementation-second.
- The goal is a merge-ready implementation pack, not immediate feature delivery.
- The resulting design must work when AUDiaGentic is installed into other repositories.
