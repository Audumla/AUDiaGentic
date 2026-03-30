# Prompt Extension (.2) — Readiness Assessment

**Review Date:** 2026-03-30  
**Scope:** Phase 0.2, 1.2, 2.2, and 3.2 extension readiness for prompt-tagged launch, ad hoc work, and multi-review

---

## Executive summary

### Status

The .2 extension is now **documented in implementation-ready form**, but it is **not yet implementation-complete** and is **not yet ready to begin coding until the .1 provider/model work is frozen**.

### What changed

The extension now has the missing detail that the earlier draft lacked:
- fixed prompt syntax
- fixed normalization boundary
- explicit `adhoc` target, with first-pass feature gating allowed
- explicit multi-review aggregation contract
- explicit tracked-config location
- explicit packet sequence and recovery expectations

### Operational status

| Extension packet | Status | Why |
|---|---|---|
| PKT-FND-009 | WAITING_ON_DEPENDENCIES | depends on .1 contract freeze |
| PKT-LFC-009 | WAITING_ON_DEPENDENCIES | depends on PKT-FND-009 |
| PKT-RLS-010 | WAITING_ON_DEPENDENCIES | depends on PKT-FND-009 |
| PKT-JOB-008 | WAITING_ON_DEPENDENCIES | depends on PKT-JOB-007 + PKT-FND-009 + PKT-LFC-009; `@adhoc` may remain disabled in pass 1 |
| PKT-JOB-009 | WAITING_ON_DEPENDENCIES | depends on PKT-JOB-008 |

---

## Resolved design gaps

| Gap from earlier draft | Resolution in this pack |
|---|---|
| tag syntax not frozen | `prefix-token-v1` fixed |
| generic ad hoc work not formalized | `target.kind=adhoc` added; `@adhoc` shorthand defined |
| review output was prose-only | `ReviewReport` and `ReviewBundle` contracts defined |
| multi-agent review unclear | deterministic `all-pass` aggregation defined |
| workflow override location conflicted | standardized on `.audiagentic/project.yaml` for MVP |
| CLI vs VS Code separation unclear | thin adapter rule defined |
| packet sequencing unclear | .2 packets split and dependency order frozen |

## Remaining dependency blocker

The extension still waits on the .1 line:
- `PKT-PRV-012`
- `PKT-FND-008`
- `PKT-JOB-007`

That blocker is intentional. It prevents the prompt launcher from consuming provider/model metadata before those fields are frozen.

## Recommendation

Do not start the .2 implementation packets yet.
Complete the .1 path first, then start:
1. `PKT-FND-009`
2. `PKT-LFC-009`
3. `PKT-RLS-010`
4. `PKT-JOB-008`
5. `PKT-JOB-009`

Pass-1 scope note:
- support `@plan`, `@implement`, `@review`, `@audit`, `@check-in-prep`
- support packet/workflow/job/artifact targets
- keep `@adhoc` accepted by parser/schema but optionally disabled by config until the core path is stable

## Final judgment

The .2 extension docs are now good enough to implement later without reopening the design question.
They are not a statement that the feature is already built.
