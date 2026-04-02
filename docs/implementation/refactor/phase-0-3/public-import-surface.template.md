# Public Import Surface Template

## Scope

- checkpoint date:
- owner:
- packet:

## Public Import Paths

| Import Path | Why Public | Referenced By | Shim Required | Notes |
|---|---|---|---|---|
| `audiagentic...` | documented/tool/bootstrap/workflow |  | yes/no |  |

## Internal-Only Import Paths

| Import Path Pattern | Why Internal | Rewrite Strategy | Notes |
|---|---|---|---|
| `audiagentic...` | implementation-only/test-only/script-local | direct rewrite |  |

## Referenced Surfaces Checked

- tracked docs
- examples
- workflows
- install/bootstrap assets
- tool entrypoints
- explicitly documented import examples

## Follow-up Inputs for PKT-FND-011

- shim-heavy areas:
- paths safe to rewrite immediately:
- paths that must stay stable through one checkpoint:
