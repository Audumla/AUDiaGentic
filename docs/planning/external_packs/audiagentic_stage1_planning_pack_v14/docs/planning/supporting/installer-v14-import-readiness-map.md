# Installer v14 import-readiness map

## Status

External only. Not imported.

## Purpose

Provide a collision-safe id remap for later planning import.

## Validation basis

Live planning lane already contains:
- `request-020`
- `spec-0079`
- `plan-0014`
- duplicate live `wp-0020`
- core tasks through `task-0335`, plus later outliers

Therefore the external v14 ids must not be imported unchanged.

## Proposed import ids

### Request

| External | Import target |
| --- | --- |
| `request-0032` | `request-021` |

### Specifications

| External | Import target |
| --- | --- |
| `spec-0049` | `spec-0080` |
| `spec-0050` | `spec-0081` |
| `spec-0051` | `spec-0082` |
| `spec-0052` | `spec-0083` |
| `spec-0053` | `spec-0084` |

### Plan

| External | Import target |
| --- | --- |
| `plan-0017` | `plan-0023` |

### Work packages

| External | Import target |
| --- | --- |
| `wp-0020` | `wp-0028` |
| `wp-0021` | `wp-0029` |
| `wp-0022` | `wp-0030` |
| `wp-0023` | `wp-0031` |

### Tasks

| External | Import target |
| --- | --- |
| `task-0251` | `task-0336` |
| `task-0252` | `task-0337` |
| `task-0253` | `task-0338` |
| `task-0254` | `task-0339` |
| `task-0255` | `task-0340` |
| `task-0256` | `task-0341` |
| `task-0257` | `task-0342` |
| `task-0258` | `task-0343` |
| `task-0259` | `task-0344` |
| `task-0260` | `task-0345` |
| `task-0261` | `task-0346` |
| `task-0262` | `task-0347` |

## Import notes

- Keep external files unchanged until actual import.
- Apply id remap during import, not before.
- Rewrite all internal refs with the same mapping in one pass.
- Recheck for collisions immediately before import because live planning ids may advance.
- Prefer MCP-backed import workflow when available.
