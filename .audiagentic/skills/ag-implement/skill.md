---
name: ag-implement
description: Use for canonical @ag-implement launches. Carries out the requested change within the contracted scope.
---

# ag-implement skill

Trigger:
- first non-empty line resolves to `ag-implement` or a configured alias (`agi`, `i`, `implement`)

Do:
- carry out the requested implementation work within the stated scope
- prefer shared helpers, repository-owned scripts, and existing patterns
- preserve the tracked-doc, baseline, and schema contracts
- keep provenance visible — provider id, surface, and session id should survive the change
- run verification steps (type checks, tests) when available before declaring done

Do not:
- do not broaden scope beyond the requested change
- do not rewrite contracts, schemas, or canonical IDs without explicit change control
- do not create or modify planning items without user approval
- do not skip tests or type checking to complete faster
