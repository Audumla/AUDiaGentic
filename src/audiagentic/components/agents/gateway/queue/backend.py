"""Backend-neutral work queue contract and conformance fake (SH25)."""

from __future__ import annotations

import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Protocol


class NackDisposition(StrEnum):
    REQUEUE = "requeue"
    DEAD_LETTER = "dead-letter"


@dataclass(frozen=True)
class PublishReceipt:
    request_id: str
    attempt_epoch: int
    accepted: bool


@dataclass(frozen=True)
class ConsumerIdentity:
    consumer_id: str
    owner_epoch: str


@dataclass(frozen=True)
class ClaimToken:
    request_id: str
    attempt_epoch: int
    consumer_id: str
    token: str
    lease_expires_at: float
    # A consumer id identifies a process role; the owner epoch fences an
    # incarnation of that process.  Keeping it on the receipt makes a lease
    # from before a restart unusable even if the consumer id is reused.
    owner_epoch: str = ""


@dataclass(frozen=True)
class ClaimedWork:
    request_id: str
    attempt_epoch: int
    claim: ClaimToken


@dataclass(frozen=True)
class QueueHealth:
    pending: int
    claimed: int
    dead_letter: int
    draining: bool


class AgentWorkQueue(Protocol):
    def publish(self, request_id: str, *, attempt_epoch: int) -> PublishReceipt: ...
    def claim(self, consumer: ConsumerIdentity, *, visibility_seconds: int) -> ClaimedWork | None: ...
    def renew(self, claim: ClaimToken) -> ClaimToken: ...
    def ack(self, claim: ClaimToken) -> None: ...
    def nack(self, claim: ClaimToken, *, disposition: NackDisposition) -> None: ...
    def health(self) -> QueueHealth: ...


class AgentWorkQueueAdmin(Protocol):
    """Operator-only controls kept separate from delivery semantics."""

    def set_draining(self, draining: bool) -> None: ...
    def inspect_dead_letter(self, *, limit: int = 100) -> tuple[str, ...]: ...
    def requeue_dead_letter(self, request_ids: tuple[str, ...]) -> int: ...
    def purge_dead_letter(self, request_ids: tuple[str, ...] | None = None) -> int: ...


class InMemoryAgentWorkQueue:
    """Deterministic fake used to prove broker semantics before adapter choice."""

    def __init__(self, *, clock: Callable[[], float] | None = None, max_delivery_attempts: int = 3) -> None:
        self._clock = clock or time.monotonic
        self._max_delivery_attempts = max_delivery_attempts
        self._lock = RLock()
        self._pending: deque[tuple[str, int]] = deque()
        self._attempts: dict[tuple[str, int], int] = {}
        self._claims: dict[str, tuple[ClaimToken, tuple[str, int]]] = {}
        self._published: set[tuple[str, int]] = set()
        self._dead: set[tuple[str, int]] = set()
        self._draining = False

    def publish(self, request_id: str, *, attempt_epoch: int) -> PublishReceipt:
        key = (request_id, attempt_epoch)
        if not request_id or attempt_epoch <= 0:
            raise ValueError("request identity is invalid")
        with self._lock:
            if self._draining:
                return PublishReceipt(request_id, attempt_epoch, False)
            if key not in self._published and key not in self._dead:
                self._published.add(key)
                self._pending.append(key)
            return PublishReceipt(request_id, attempt_epoch, True)

    def claim(self, consumer: ConsumerIdentity, *, visibility_seconds: int) -> ClaimedWork | None:
        if visibility_seconds <= 0 or not consumer.consumer_id or not consumer.owner_epoch:
            raise ValueError("claim parameters are invalid")
        with self._lock:
            self._requeue_expired()
            while self._pending:
                key = self._pending.popleft()
                if key in self._dead:
                    continue
                delivery = self._attempts.get(key, 0) + 1
                self._attempts[key] = delivery
                if delivery > self._max_delivery_attempts:
                    self._dead.add(key)
                    continue
                token = ClaimToken(
                    key[0], key[1], consumer.consumer_id, uuid.uuid4().hex,
                    self._clock() + visibility_seconds, consumer.owner_epoch,
                )
                self._claims[token.token] = (token, key)
                return ClaimedWork(key[0], key[1], token)
        return None

    def renew(self, claim: ClaimToken) -> ClaimToken:
        with self._lock:
            current = self._require_current_claim(claim)
            lease_seconds = max(1.0, claim.lease_expires_at - self._clock())
            renewed = ClaimToken(
                claim.request_id, claim.attempt_epoch, claim.consumer_id, claim.token,
                self._clock() + lease_seconds, claim.owner_epoch,
            )
            self._claims[claim.token] = (renewed, current[1])
            return renewed

    def ack(self, claim: ClaimToken) -> None:
        with self._lock:
            self._require_current_claim(claim)
            del self._claims[claim.token]

    def nack(self, claim: ClaimToken, *, disposition: NackDisposition) -> None:
        with self._lock:
            current = self._require_current_claim(claim)
            del self._claims[claim.token]
            key = current[1]
            if disposition is NackDisposition.DEAD_LETTER:
                self._dead.add(key)
            else:
                self._pending.appendleft(key)

    def set_draining(self, draining: bool) -> None:
        with self._lock:
            self._draining = draining

    def health(self) -> QueueHealth:
        with self._lock:
            self._requeue_expired()
            return QueueHealth(len(self._pending), len(self._claims), len(self._dead), self._draining)

    def dead_letter_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(request_id for request_id, _ in self._dead))

    def inspect_dead_letter(self, *, limit: int = 100) -> tuple[str, ...]:
        if limit <= 0:
            raise ValueError("dead-letter limit must be positive")
        with self._lock:
            return tuple(sorted(request_id for request_id, _ in self._dead))[:limit]

    def requeue_dead_letter(self, request_ids: tuple[str, ...]) -> int:
        with self._lock:
            selected = {request_id for request_id in request_ids}
            matches = {key for key in self._dead if key[0] in selected}
            for key in matches:
                self._dead.remove(key)
                self._attempts[key] = 0
                self._pending.append(key)
            return len(matches)

    def purge_dead_letter(self, request_ids: tuple[str, ...] | None = None) -> int:
        with self._lock:
            selected = None if request_ids is None else set(request_ids)
            matches = {
                key for key in self._dead if selected is None or key[0] in selected
            }
            for key in matches:
                self._dead.remove(key)
                self._published.discard(key)
                self._attempts.pop(key, None)
            return len(matches)

    def _requeue_expired(self) -> None:
        now = self._clock()
        expired = [token for token, (claim, _) in self._claims.items() if claim.lease_expires_at <= now]
        for token in expired:
            claim, key = self._claims.pop(token)
            self._pending.append(key)

    def _require_current_claim(self, claim: ClaimToken) -> tuple[ClaimToken, tuple[str, int]]:
        """Return only a live receipt held by its original consumer epoch.

        Calling this before every mutating operation ensures that delivery
        expiry is a fencing event even when no other consumer has polled yet.
        Receipt equality also rejects a forged or stale copy bearing only a
        known token string.
        """
        self._requeue_expired()
        current = self._claims.get(claim.token)
        if (
            current is None
            or current[0] != claim
            or not claim.owner_epoch
        ):
            raise KeyError("claim is not owned by this consumer epoch")
        return current


__all__ = [
    "AgentWorkQueue", "AgentWorkQueueAdmin", "ClaimToken", "ClaimedWork", "ConsumerIdentity", "InMemoryAgentWorkQueue",
    "NackDisposition", "PublishReceipt", "QueueHealth",
]
