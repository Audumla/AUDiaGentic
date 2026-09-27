import asyncio

import pytest

from audiagentic.components.agents.gateway.session.fifo_wait import acquire_turn_lock
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.mark.asyncio
async def test_cancelled_waiter_leaves_predecessor_locked_and_replacement_can_wait():
    lock = asyncio.Lock()
    await lock.acquire()
    cancel = asyncio.Event()
    waiter = asyncio.create_task(acquire_turn_lock(lock, cancel))
    await asyncio.sleep(0)
    cancel.set()
    with pytest.raises(AudiaGenticError, match='cancelled before FIFO'):
        await asyncio.wait_for(waiter, 1)
    assert lock.locked()
    replacement = asyncio.create_task(acquire_turn_lock(lock, asyncio.Event()))
    lock.release()
    await asyncio.wait_for(replacement, 1)
    assert lock.locked()
    lock.release()


@pytest.mark.asyncio
async def test_cancel_wins_simultaneous_free_lock_without_leaking_lock():
    lock = asyncio.Lock()
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(AudiaGenticError):
        await acquire_turn_lock(lock, cancel)
    assert not lock.locked()


@pytest.mark.asyncio
async def test_task_cancellation_does_not_release_predecessor_lock():
    lock = asyncio.Lock()
    await lock.acquire()
    waiter = asyncio.create_task(acquire_turn_lock(lock, asyncio.Event()))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert lock.locked()
    lock.release()
