---
name: ag-implement
description: Use for canonical @ag-implement launches. Carries out the requested change.
---

# ag-implement skill

Trigger:
- first non-empty line resolves to `ag-implement` or a configured alias

Do:
- carry out the requested implementation work
- prefer shared helpers and repository-owned scripts
- preserve the tracked-doc and baseline contracts

Do not:
- do not broaden scope beyond the requested change
- do not rewrite contracts without change control
