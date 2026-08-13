# Agent-jobs ingress adapters

Execution lifecycle is owned by Agents Context/Work and Foundation
interactions. This package is retained only for ingress compatibility:

- prompt parsing, syntax, aliases, targets, templates, and context rendering;
- trigger configuration evaluation and the bounded event observer adapter;
- redacted dead-letter evidence for failed ingress handling.

Prompt and packet submission, approvals, session input, review children, status,
and cancellation all use the public Agents Work APIs. The former job store,
records, state machine, stage runner, review persistence, and job-control
modules have been retired.

Example trigger configuration:

```yaml
triggers:
  - contract-version: v1
    trigger-id: plan-item-review
    kind: event
    event-pattern: planning.item.created
    filter:
      payload.priority: [P0, P1]
    prompt-template: Review {{subject}}.
```
