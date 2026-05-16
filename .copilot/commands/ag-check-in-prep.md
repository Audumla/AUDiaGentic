<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# ag-check-in-prep skill

Provider surface: `copilot`

Launch example: `@ag-check-in-prep-copilot`

Use this skill for canonical `@ag-check-in-prep` launches.

Trigger:
- first non-empty line resolves to `ag-check-in-prep` or a configured alias (`agc`, `c`, `check-in-prep`)

Do:
- summarize outstanding changes and their verification state (typed, tested, reviewed)
- confirm baseline assets are current and no managed files have unexpected drift
- check that tracked docs, release artifacts, and planning records are synchronized
- report any open blockers, failing checks, or uncommitted work that could destabilize the check-in
- keep output concise and action-oriented — one clear status per concern

Do not:
- do not change implementation behavior or introduce new changes
- do not broaden into feature work or bug fixes
- do not mark the repo as check-in-ready if there are open blockers
- do not skip checks to produce a faster summary
