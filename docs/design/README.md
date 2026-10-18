# Design documents

Design documents define architecture and contracts. Read the status line in
each document before relying on it: frozen designs define current boundaries,
while audit baselines and drafts explain a bounded decision or migration.

- [Shared gateway architecture](gateway-shared-service.md) — frozen target
  topology, ownership boundaries, security policy, and migration status.
- [Gateway execution context](gateway-execution-context.md) — SH02 envelope,
  manifest, fingerprint, idempotency, and versioning baseline.
- [Managed process and service lifecycle](managed-process-service-lifecycle.md)
  — foundation lifecycle contract used by gateway and detached sessions.
- [Recipe upgrade inventory](recipe-upgrade-inventory.md) — PR09 audit of
  explicit recipe upgrade behavior; not an authorization to mutate at launch.

For maintenance and authority rules, see
[Documentation status](../DOCUMENTATION_STATUS.md).

