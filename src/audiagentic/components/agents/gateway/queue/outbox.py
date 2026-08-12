"""Durable admission-to-publication seam for SH25."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import gateway_publication_path, gateway_root
from audiagentic.components.agents.gateway.queue.backend import AgentWorkQueue, PublishReceipt
from audiagentic.foundation.io import atomic_write_json, read_text_with_retry


@dataclass(frozen=True)
class PublicationIntent:
    request_id: str
    attempt_epoch: int
    state: str
    receipt: dict[str, Any] | None = None


class DurablePublicationOutbox:
    """Filesystem-backed outbox for stable request/attempt publication identity."""

    def stage(self, project_root: Path, request_id: str, *, attempt_epoch: int) -> PublicationIntent:
        if not request_id or attempt_epoch <= 0:
            raise ValueError("publication identity is invalid")
        path = gateway_publication_path(
            project_root, request_id, attempt_epoch=attempt_epoch,
        )
        if path.is_file():
            existing = self._read(path)
            if existing.attempt_epoch != attempt_epoch:
                raise ValueError("publication attempt identity changed")
            return existing
        intent = PublicationIntent(request_id, attempt_epoch, "pending")
        atomic_write_json(path, self._payload(intent))
        return intent

    def flush(
        self,
        project_root: Path,
        queue: AgentWorkQueue,
        *,
        after_publish: Callable[[PublicationIntent, PublishReceipt], None] | None = None,
    ) -> tuple[PublishReceipt, ...]:
        receipts: list[PublishReceipt] = []
        root = gateway_root(project_root)
        if not root.is_dir():
            return ()
        for path in sorted(root.glob("*/publication-*.json")):
            intent = self._read(path)
            if intent.state == "published":
                continue
            receipt = queue.publish(intent.request_id, attempt_epoch=intent.attempt_epoch)
            if not receipt.accepted:
                continue
            if after_publish is not None:
                after_publish(intent, receipt)
            updated = PublicationIntent(
                intent.request_id, intent.attempt_epoch, "published",
                {"request-id": receipt.request_id, "attempt-epoch": receipt.attempt_epoch, "accepted": receipt.accepted},
            )
            atomic_write_json(path, self._payload(updated))
            receipts.append(receipt)
        return tuple(receipts)

    @staticmethod
    def _payload(intent: PublicationIntent) -> dict[str, Any]:
        return {
            "request-id": intent.request_id,
            "attempt-epoch": intent.attempt_epoch,
            "state": intent.state,
            "receipt": intent.receipt,
        }

    @staticmethod
    def _read(path: Path) -> PublicationIntent:
        import json

        raw = json.loads(read_text_with_retry(path))
        return PublicationIntent(
            str(raw["request-id"]), int(raw["attempt-epoch"]),
            str(raw["state"]), raw.get("receipt"),
        )


__all__ = ["DurablePublicationOutbox", "PublicationIntent"]
