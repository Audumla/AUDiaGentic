"""Host-owned, per-connection receipt sender; never native execution authority.

No automatic enablement. Start run(connection) after connect; the host owns its
Task and decides whether a deferred failure warrants close/reconnect. All local
receipt I/O runs off-loop. Peer resume metadata never becomes a local ACK.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping

from .connection import NodeConnection
from .contracts import MAX_FRAME_BYTES, _identifier, _integer, conflict, invalid
from .receipts import ReceiptCheckpoint, _digest, _log_id
from .recipient_runtime import NodeRecipientRuntime
from .work_protocol import ReceiptResume, ReceiptResumeReply, parse_work_frame


class NodeReceiptSender:
    def __init__(
        self,
        runtime: NodeRecipientRuntime,
        *,
        ack_timeout_seconds: float = 10,
        poll_interval_seconds: float = 1,
    ):
        if type(runtime) is not NodeRecipientRuntime:
            raise invalid(1, "Receipt sender requires the process-owned recipient runtime")
        for value in (ack_timeout_seconds, poll_interval_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise invalid(1, "Receipt sender timing bounds must be positive finite values")
        if poll_interval_seconds > 1:
            raise invalid(1, "Receipt sender producer polling must not exceed one second")
        self.runtime = runtime
        self.ack_timeout = ack_timeout_seconds
        self.poll_interval = poll_interval_seconds

    def _current(self, connection):
        return (
            self.runtime.current_connection is connection
            and connection.close_reason is None
            and connection.failure is None
        )

    async def _cursor_row(self, connection, sequence, digest):
        _integer(sequence, 0)
        if sequence == 0:
            if digest is not None:
                raise conflict(
                    1,
                    "Receipt cursor has a nonempty zero digest",
                    reason_code="receipt-cursor-mismatch",
                )
            return
        _digest(digest)
        rows = await asyncio.to_thread(
            self.runtime.execution_owner.receipts_after, sequence - 1, limit=1
        )
        if (
            len(rows) != 1
            or rows[0].sequence != sequence
            or rows[0].digest != digest
            or rows[0].identity.node_id != connection.identity.node_id
        ):
            raise conflict(
                1,
                "Receipt cursor does not match local metadata",
                reason_code="receipt-cursor-mismatch",
            )

    async def _checkpoint(self, connection, previous=None):
        checkpoint = await asyncio.to_thread(self.runtime.execution_owner.receipt_checkpoint)
        if checkpoint is None:
            if previous is not None:
                raise conflict(1, "Receipt log disappeared", reason_code="receipt-log-changed")
            return None
        if type(checkpoint) is not ReceiptCheckpoint:
            raise invalid(1, "Receipt sender requires a typed durable checkpoint")
        _log_id(checkpoint.log_incarnation_id)
        _integer(checkpoint.through_sequence, 0)
        if checkpoint.server_id is not None:
            _identifier(checkpoint.server_id)
        if (checkpoint.through_sequence == 0 and checkpoint.server_id is not None) or (
            checkpoint.through_sequence > 0 and checkpoint.server_id is None
        ):
            raise conflict(
                1, "Invalid durable receipt cursor", reason_code="receipt-cursor-mismatch"
            )
        if previous is not None and (
            checkpoint.log_incarnation_id != previous.log_incarnation_id
            or checkpoint.through_sequence < previous.through_sequence
            or (previous.server_id is not None and checkpoint.server_id != previous.server_id)
            or (
                checkpoint.through_sequence == previous.through_sequence
                and checkpoint.through_receipt_sha256 != previous.through_receipt_sha256
            )
        ):
            raise conflict(
                1,
                "Durable receipt cursor changed incompatibly",
                reason_code="receipt-cursor-mismatch",
            )
        await self._cursor_row(
            connection, checkpoint.through_sequence, checkpoint.through_receipt_sha256
        )
        return checkpoint

    async def _resume(self, connection, checkpoint):
        # Shield the bounded request's correlation lifetime. Cancelling only the
        # sender must not turn its late reply into an unsolicited channel error.
        request = asyncio.create_task(
            connection.request_work(
                "reconcile",
                {
                    "kind": "receipt-resume",
                    "log-incarnation-id": checkpoint.log_incarnation_id,
                    "through-sequence": checkpoint.through_sequence,
                    "through-receipt-sha256": checkpoint.through_receipt_sha256,
                },
                reply_types=(ReceiptResumeReply,),
                timeout=self.ack_timeout,
            )
        )
        try:
            sent, reply, message = await asyncio.shield(request)
        except asyncio.CancelledError:
            request.add_done_callback(self._consume_request)
            raise
        except TimeoutError:
            # Only the bounded network request await owns this classification;
            # local checkpoint/cursor I/O elsewhere must remain fail-closed.
            raise conflict(
                1, "Receipt resume deadline elapsed", reason_code="receipt-resume-timeout"
            ) from None
        parsed_request = parse_work_frame(
            sent,
            role="gateway",
            current_connection=connection.identity,
            capability=connection.capability,
            max_artifact_bytes=MAX_FRAME_BYTES,
        )
        parsed_reply = parse_work_frame(
            reply,
            role="node",
            current_connection=connection.identity,
            capability=connection.capability,
            max_artifact_bytes=MAX_FRAME_BYTES,
        )
        if (
            type(parsed_request) is not ReceiptResume
            or type(message) is not ReceiptResumeReply
            or parsed_reply != message
            or message.in_reply_to != sent.message_id
            or parsed_request.log_incarnation_id != checkpoint.log_incarnation_id
            or parsed_request.through_sequence != checkpoint.through_sequence
            or parsed_request.through_receipt_sha256 != checkpoint.through_receipt_sha256
            or message.log_incarnation_id != checkpoint.log_incarnation_id
        ):
            raise conflict(
                1, "Receipt resume correlation changed", reason_code="receipt-resume-mismatch"
            )
        if message.after_sequence < checkpoint.through_sequence:
            raise conflict(
                1,
                "Central receipt custody is behind the durable local ACK",
                reason_code="receipt-cursor-contradiction",
            )
        await self._cursor_row(connection, message.after_sequence, message.after_receipt_sha256)
        # Even a validated central-ahead cursor never replaces local ACK truth.

    @staticmethod
    def _consume_request(task):
        if not task.cancelled():
            task.exception()

    async def _wait(self, closed, events, timeout=None):
        waiters = [asyncio.create_task(event.wait()) for event in events]
        try:
            await asyncio.wait(
                [closed, *waiters], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            return not closed.done()
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    async def _await_ack(self, connection, closed, checkpoint, receipt):
        deadline = asyncio.get_running_loop().time() + self.ack_timeout
        deferred_handoff = False
        while self._current(connection) and not closed.done():
            self.runtime.acknowledgement_event.clear()
            self.runtime.state_changed_event.clear()
            current = await self._checkpoint(connection, checkpoint)
            if current.through_sequence >= receipt.sequence:
                return "advanced", current
            pending_before = self.runtime.producer_pending
            remaining = deadline - asyncio.get_running_loop().time()
            if pending_before or deferred_handoff or remaining <= 0:
                snapshot = await asyncio.to_thread(self.runtime.execution_owner.snapshot)
                # Remember an observed live producer/scope mismatch before it
                # can finish between the snapshot and the event-loop wakeup.
                if snapshot.handoff_pending and pending_before:
                    deferred_handoff = True
                if deferred_handoff and not snapshot.handoff_pending:
                    return "resume", current
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                if (
                    deferred_handoff
                    and snapshot.handoff_pending
                    and (pending_before or self.runtime.producer_pending)
                ):
                    if not await self._wait(
                        closed, [self.runtime.state_changed_event], self.poll_interval
                    ):
                        break
                    continue
                raise conflict(
                    1,
                    "Receipt ACK did not advance before its deadline",
                    reason_code="receipt-ack-timeout",
                )
            if not await self._wait(
                closed,
                [self.runtime.acknowledgement_event, self.runtime.state_changed_event],
                remaining,
            ):
                break
        return "closed", checkpoint

    async def run(self, connection: NodeConnection):
        if type(connection) is not NodeConnection or connection.role != "node":
            raise invalid(1, "Receipt sender requires its authenticated node connection")
        closed = asyncio.create_task(connection.wait_closed_signal())
        try:
            checkpoint = None
            resumed = False
            while self._current(connection) and not closed.done():
                self.runtime.state_changed_event.clear()
                checkpoint = await self._checkpoint(connection, checkpoint)
                if checkpoint is None:
                    if not await self._wait(closed, [self.runtime.state_changed_event]):
                        return
                    continue
                if not resumed:
                    await self._resume(connection, checkpoint)
                    resumed = True
                    continue  # Reread durable local ACK; never use peer cursor as progress.
                rows = await asyncio.to_thread(
                    self.runtime.execution_owner.receipts_after,
                    checkpoint.through_sequence,
                    limit=1,
                )
                if not rows:
                    if self._current(connection) and not closed.done():
                        await self.runtime.emit_receipt_ready(connection, checkpoint)
                    timeout = self.poll_interval if self.runtime.producer_pending else None
                    if not await self._wait(closed, [self.runtime.state_changed_event], timeout):
                        return
                    continue
                receipt = rows[0]
                if receipt.sequence != checkpoint.through_sequence + 1:
                    raise conflict(
                        1, "Receipt replay has a gap", reason_code="receipt-cursor-mismatch"
                    )
                if not self._current(connection) or closed.done():
                    return
                await connection.send_work(
                    "receipt",
                    {
                        "log-incarnation-id": checkpoint.log_incarnation_id,
                        "receipt": receipt.public_payload(),
                    },
                )
                outcome, checkpoint = await self._await_ack(connection, closed, checkpoint, receipt)
                if outcome == "closed":
                    return
                if outcome == "resume":
                    resumed = False
        except asyncio.CancelledError:
            raise
        except Exception as error:
            details = getattr(error, "details", None)
            reason = details.get("reason_code") if isinstance(details, Mapping) else None
            if reason not in {
                "receipt-cursor-mismatch",
                "receipt-log-changed",
                "receipt-resume-mismatch",
                "receipt-cursor-contradiction",
                "receipt-ack-timeout",
                "receipt-resume-timeout",
            }:
                reason = "receipt-sender-failed"
            raise conflict(1, "Node receipt sender deferred", reason_code=reason) from None
        finally:
            closed.cancel()
            await asyncio.gather(closed, return_exceptions=True)
