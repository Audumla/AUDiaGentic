"""DOM response extraction from ChatGPT.

Polls the page for the latest assistant message and returns its text content.
Uses ``<p>`` elements in the main content area — not ``[data-message-author-role]``
which is no longer present in ChatGPT's current DOM structure.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# JavaScript: extract the latest assistant response from <p> elements.
# Filters out sidebar, navigation, and UI chrome — only main content paras.
# Skips the user's prompt (first long paragraph) to avoid returning it as response.
_GET_LAST_RESPONSE_TEXT_JS = """(promptText) => {
    const ps = document.querySelectorAll('p');
    let paras = [];
    let foundUserMessage = false;

    ps.forEach(p => {
        const t = p.innerText.trim();
        // Skip short text, UI chrome, sidebar
        if (t.length < 20) return;
        if (t.includes('ChatGPT') || t.includes('Library') || t.includes('Upgrade')) return;

        // Walk up to check if we're in the main content area
        let el = p.parentElement;
        while (el) {
            if (el.className && typeof el.className === 'string') {
                if (el.className.includes('sidebar') || el.className.includes('chat-history')) return;
            }
            // If parent is a <main> or content area, this is ours
            if (el.tagName === 'MAIN') break;
            el = el.parentElement;
        }

        // Skip the user's own prompt to avoid returning it as response
        if (promptText && t.includes(promptText.trim())) {
            foundUserMessage = true;
            return;
        }

        paras.push(t);
    });

    if (paras.length === 0) return null;
    return paras.join('\\n\\n');
}"""

# JavaScript: detect whether ChatGPT is still generating.
_IS_GENERATING_JS = """
() => {
    // Stop generating button visible = still generating
    if (document.querySelector('[data-testid="stop-generating"]')) return true;

    // Loading/streaming indicators
    const loaders = document.querySelectorAll('.loading-dots, [class*="streaming"], .result-streaming');
    if (loaders.length > 0) return true;

    // Check for a stop button near the editor — ChatGPT shows this while streaming
    const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('stop')) return true;
    }

    return false;
}
"""


async def get_response_text(client: Any, prompt_text: str | None = None) -> str | None:
    """Return the text of the latest assistant response, or ``None``."""
    result = await client.evaluate(_GET_LAST_RESPONSE_TEXT_JS, prompt_text or "")
    if isinstance(result, str) and result.strip():
        return result.strip()
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
    prompt_text: str | None = None,
) -> str | None:
    """Poll for ChatGPT's response text until it stops changing or times out.

    Args:
        client: A CdpClient instance with an active page.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        on_chunk: Optional callback receiving partial text as it arrives.
        baseline_length: Length of the last known response (to detect new content).
        done_marker: If set, treats the arrival of this string as completion.
        prompt_text: The user's prompt text — used to filter out the user message
            from the DOM when extracting the assistant response.

    Returns:
        The full text of the latest response, or ``None`` on timeout.
    """
    logger.info("Waiting for ChatGPT response (timeout=%.0fs)", timeout)
    deadline = time.monotonic() + timeout
    last_text: str | None = None

    # Wait for response to start (text length > baseline)
    start_deadline = time.monotonic() + 15.0
    while time.monotonic() < start_deadline:
        text = await get_response_text(client, prompt_text)
        if text and len(text) > baseline_length:
            break
        await asyncio.sleep(1.0)

    while time.monotonic() < deadline:
        text = await get_response_text(client, prompt_text)

        if text is None or len(text) <= baseline_length:
            await asyncio.sleep(interval)
            continue

        # New content detected
        if text != last_text:
            last_text = text
            if on_chunk is not None:
                on_chunk(text)
            logger.debug("Response growing: %d chars", len(text))

        # Done marker check
        if done_marker and done_marker in text:
            logger.info("Done marker detected")
            return text

        # Check if generation has stopped
        generating = await is_generating(client)
        if not generating:
            # Wait one more interval to confirm nothing more arrives
            await asyncio.sleep(1.0)
            final_text = await get_response_text(client, prompt_text)
            if final_text and final_text == last_text:
                logger.info("Response complete (%d chars)", len(final_text))
                return final_text
            if final_text and final_text != last_text:
                last_text = final_text
                if on_chunk is not None:
                    on_chunk(last_text)

        await asyncio.sleep(interval)

    logger.warning(
        "Response wait timed out after %.0fs — partial (%d chars)",
        timeout,
        len(last_text) if last_text else 0,
    )
    return last_text


async def wait_for_generation_to_stop(
    client: Any,
    timeout: float = 30.0,
) -> bool:
    """Wait for ChatGPT to finish generating.

    Returns ``True`` if generation stopped, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        gen = await is_generating(client)
        if not gen:
            return True
        await asyncio.sleep(1.0)
    return False
