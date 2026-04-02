---
name: adhoc
description: Optional skill for @adhoc launches when the project feature gate is enabled. Handles ad hoc subjects conservatively.
---

# adhoc skill

Optional skill for `@adhoc` launches when feature-gated.

Trigger:
- first non-empty line resolves to `adhoc`

Do:
- handle the ad hoc subject conservatively
- preserve provenance and the normalized envelope

Do not:
- enable ad hoc execution if the project gate disables it
- redefine the canonical grammar
