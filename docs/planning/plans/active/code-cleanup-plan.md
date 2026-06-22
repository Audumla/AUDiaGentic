---
id: plan-code-cleanup
label: Code cleanup (Standards compliance)
state: draft
summary: Address Standards 1/5/8/9 violations, dead code removal, and composition-root architecture correction
---

# Code cleanup (Standards compliance)

Address Standards 1/5/8/9 violations, dead code removal, and composition-root architecture correction

## Deferred

| Item | Standard | Reason | Priority |
|---|---|---|---|
| `binaries.py:170-182` — `taskkill`/`pkill` | Standard 4 | OS process management, not editor coupling. Already abstracted via `sys.platform`. | Low |

## Items

- [CC01](code-cleanup/CC01.md)
- [CC02](code-cleanup/CC02.md)
- [CC03](code-cleanup/CC03.md)
- [CC04](code-cleanup/CC04.md)
- [CC05](code-cleanup/CC05.md)
- [CC06](code-cleanup/CC06.md)
- [CC07](code-cleanup/CC07.md)
- [CC08](code-cleanup/CC08.md)
- [CC09](code-cleanup/CC09.md)
