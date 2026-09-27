"""Cancel-aware FIFO admission without cancelling the preceding session turn."""
import asyncio

from audiagentic.foundation.contracts.errors import AudiaGenticError


async def acquire_turn_lock(lock: asyncio.Lock, cancel: asyncio.Event) -> None:
    acquire = asyncio.create_task(lock.acquire())
    cancelled = asyncio.create_task(cancel.wait())
    transferred = False
    try:
        await asyncio.wait((acquire, cancelled), return_when=asyncio.FIRST_COMPLETED)
        if cancel.is_set():
            raise AudiaGenticError(
                code="CON-AGW-099", kind="agents",
                message="session request cancelled before FIFO admission",
            )
        await acquire
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        if cancel.is_set():
            raise AudiaGenticError(
                code="CON-AGW-099", kind="agents",
                message="session request cancelled before FIFO admission",
            )
        transferred = True
    finally:
        if not transferred:
            cancelled.cancel()
            if not acquire.done():
                acquire.cancel()
            await asyncio.gather(acquire, cancelled, return_exceptions=True)
            if not acquire.cancelled() and acquire.done():
                if acquire.exception() is None and acquire.result():
                    lock.release()
