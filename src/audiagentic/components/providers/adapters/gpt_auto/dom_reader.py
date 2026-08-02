"""DOM response extraction from ChatGPT.

Polls the page for the latest assistant message and returns its text content.
Supports optional streaming callback so callers can see partial results as they appear.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# JavaScript that extracts the last assistant message's text.
# ChatGPT uses data-message-author-role="assistant" on message containers;
# we grab the innerText of the last one.
_GET_LAST_ASSISTANT_TEXT_JS = """
() => {
    const messages = document.querySelectorAll(
        '[data-message-author-role="assistant"]'
    );
    if (messages.length === 0) return null;
    return messages[messages.length - 1].innerText;
}
"""

# JavaScript that returns the length of the last assistant message —
# used to detect whether new content has arrived.
_GET_LAST_ASSISTANT_LENGTH_JS = """
() => {
    const messages = document.querySelectorAll(
        '[data-message-author-role="assistant"]'
    );
    if (messages.length === 0) return 0;
    return messages[messages.length - 1].innerText?.length ?? 0;
}
"""

# JavaScript to detect whether ChatGPT is still generating.
_IS_GENERATING_JS = """
() => {
    // Look for the "Stop generating" button which appears during generation
    const stopBtn = document.querySelector('[data-testid="stop-generating"]');
    if (stopBtn) return true;

    // Alternative: check for a loading indicator near the last message
    const loaders = document.querySelectorAll('.loading-dots, [class*="streaming"]');
    return loaders.length > 0;
}
"""


async def get_assistant_text(client: Any) -> str | None:
    """Return the full text of the latest assistant message, or ``None``."""
    result = await client.evaluate(_GET_LAST_ASSISTANT_TEXT_JS)
    if isinstance(result, str):
        return result
    return None


async def is_generating(client: Any) -> bool:
    """Return whether ChatGPT appears to still be generating a response."""
    result = await client.evaluate(_IS_GENERATING_JS)
    return bool(result)


async def wait_for_response(
    client: Any,
    timeout: float = 120.0,
    interval: float = 2.0,
    on_chunk: Callable[[str], None] | None = None,
    baseline_length: int = 0,
) -> str | None:
    """Poll for ChatGPT's response text until it stops changing or times out.

    Args:
        client: A PlaywrightClient instance with an active page.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        on_chunk: Optional callback receiving partial text as it arrives.
        baseline_length: Length of the last known assistant message before
            this prompt (used to detect a new response).

    Returns:
        The full text of the latest assistant message, or ``None`` on timeout.
    """
    logger.info("Waiting for ChatGPT response (timeout=%.0fs)", timeout)
    deadline = time.monotonic() + timeout
    last_text: str | None = None

    while time.monotonic() < deadline:
        text = await get_assistant_text(client)

        # Skip if no response yet or it's the same length as baseline
        if text is None or len(text) <= baseline_length:
            await asyncio.sleep(interval)
            continue

        # New content detected
        if text != last_text:
            last_text = text
            if on_chunk is not None:
                on_chunk(text)
            logger.debug("Response growing: %d chars", len(text))

        # Check if generation has stopped
        generating = await is_generating(client)
        if not generating:
            # Wait one more interval to be sure nothing more arrives
            await asyncio.sleep(interval)
            final_text = await get_assistant_text(client)
            if final_text is not None and final_text == last_text:
                logger.info("Response complete (%d chars)", len(final_text))
                return final_text
            if final_text is not None:
                last_text = final_text
                if on_chunk is not None:
                    on_chunk(last_text)
        else:
            logger.debug("Still generating...")

        await asyncio.sleep(interval)

    # Timeout reached
    logger.warning(
        "Response wait timed out after %.0fs — returning partial (%d chars)",
        timeout,
        len(last_text) if last_text else 0,
    )
    return last_text


async def wait_for_generation_to_stop(
    client: Any,
    timeout: float = 30.0,
) -> bool:
    """Wait for ChatGPT to finish generating (stop button disappears).

    Returns ``True`` if generation stopped, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        gen = await is_generating(client)
        if not gen:
            return True
        await asyncio.sleep(1.0)
    return False
