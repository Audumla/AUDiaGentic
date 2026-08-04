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

# JavaScript that extracts the last assistant message's text,
# filtering out "thinking" blocks used by reasoning models.
_GET_LAST_ASSISTANT_TEXT_JS = """
() => {
    const messages = document.querySelectorAll(
        '[data-message-author-role="assistant"]'
    );
    if (messages.length === 0) return null;
    
    const lastMsg = messages[messages.length - 1];
    
    // Create a clone to manipulate without affecting the UI
    const clone = lastMsg.cloneNode(true);
    
    // Remove "Thought" / "Thinking" sections common in reasoning models
    // They often use specific classes or tags like <details> or specific data attributes
    const thinkingSelectors = [
        'details', 
        '.thought', 
        '[data-testid="thought-block"]',
        '.bg-token-main-surface-secondary' // common container for thinking
    ];
    
    thinkingSelectors.forEach(sel => {
        clone.querySelectorAll(sel).forEach(el => el.remove());
    });
    
    return clone.innerText.trim();
}
"""

# JavaScript that returns the length of the filtered assistant message.
_GET_LAST_ASSISTANT_LENGTH_JS = """
() => {
    const text = (() => {
        const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
        if (messages.length === 0) return "";
        const clone = messages[messages.length - 1].cloneNode(true);
        ['details', '.thought', '[data-testid="thought-block"]'].forEach(sel => {
            clone.querySelectorAll(sel).forEach(el => el.remove());
        });
        return clone.innerText;
    })();
    return text.length;
}
"""

# JavaScript to detect whether ChatGPT is still generating.
_IS_GENERATING_JS = """
() => {
    // 1. Look for the "Stop generating" button
    if (document.querySelector('[data-testid="stop-generating"]')) return true;

    // 2. Look for the "Continue generating" button (means it's paused/ready for more)
    if (document.querySelector('[data-testid="continue-generating"]')) return false;

    // 3. Check for loading/streaming indicators
    const loaders = document.querySelectorAll('.loading-dots, [class*="streaming"], .result-streaming');
    if (loaders.length > 0) return true;

    // 4. Check for active reasoning/thinking
    const thinking = document.querySelector('.bg-token-main-surface-secondary, details[open]');
    if (thinking && thinking.textContent.includes('Thought')) return true;

    return false;
}
"""


async def get_assistant_text(client: Any) -> str | None:
    """Return the filtered text of the latest assistant message, or ``None``."""
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
    done_marker: str | None = None,
) -> str | None:
    """Poll for ChatGPT's response text until it stops changing or times out.

    Args:
        client: A PlaywrightClient instance with an active page.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        on_chunk: Optional callback receiving partial text as it arrives.
        baseline_length: Length of the last known assistant message before
            this prompt (used to detect a new response).
        done_marker: If set, treats the arrival of this string as completion.

    Returns:
        The full text of the latest assistant message, or ``None`` on timeout.
    """
    logger.info("Waiting for ChatGPT response (timeout=%.0fs)", timeout)
    deadline = time.monotonic() + timeout
    last_text: str | None = None
    
    # Wait for response to start (text length > baseline)
    start_wait_deadline = time.monotonic() + 15.0 # Wait up to 15s for generation to even begin
    while time.monotonic() < start_wait_deadline:
        text = await get_assistant_text(client)
        if text and len(text) > baseline_length:
            break
        await asyncio.sleep(1.0)

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

        # Check for done marker in the text
        if done_marker and done_marker in text:
            logger.info("Done marker '%s' detected", done_marker)
            return text

        # Check if generation has stopped
        generating = await is_generating(client)
        if not generating:
            # Wait one more short interval to be sure nothing more arrives
            await asyncio.sleep(1.0)
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
