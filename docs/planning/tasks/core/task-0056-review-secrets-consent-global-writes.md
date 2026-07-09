---
id: task-0056
label: MO review - secrets consent and global writes
state: review
summary: Review secret handling, auth references, and consent gates for user-global provider config.
domain: core
workflow: review_heavy
---

## Review focus

Confirm endpoint projection never leaks secrets and never mutates user-global config without explicit consent.

## Checks

- `api-key-ref` supports env references and does not require inline secrets.
- Structured writers preserve env-key references where upstream supports them.
- Codex global TOML writes are consent-gated and dry-runnable.
- Any provider requiring inline keys marks that fact as action-needed.
- Logs/status/dry-run output redacts secret values.
- Uninstall/removal deletes only AUDiaGentic-owned global entries.

## Evidence required

- Redaction tests.
- Codex consent-required test.
- Global-write dry-run snapshot.
- Removal test for owned entries only.
- User-facing warning/action-needed text.

## Exit criteria

No auto writer may write secrets or global config until consent, redaction, and rollback tests exist.
