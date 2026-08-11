"""Advisory wake-up seam for durable gateway operations."""

from __future__ import annotations

from .contracts import ManagementWorkNotifier


class NoopManagementWorkNotifier:
    """Default notifier: a periodic/startup pump discovers accepted work."""

    def notify(self, operation_id: str) -> None:
        del operation_id


def notify_best_effort(notifier: ManagementWorkNotifier, operation_id: str) -> bool:
    """Return whether notification was delivered without making it authoritative."""
    try:
        notifier.notify(operation_id)
    except Exception:  # noqa: BLE001 - an advisory notifier must not roll back admission
        return False
    return True


__all__ = ["NoopManagementWorkNotifier", "notify_best_effort"]
