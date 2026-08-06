"""DOM response extraction from ChatGPT.

Polls the page for the latest assistant message and returns its text content.
Uses ``[data-message-author-role]`` blocks — the current ChatGPT DOM marks each
user/assistant message with ``data-message-author-role="user"`` /
``"assistant"``.  The extractor returns only the **last** assistant block, so
a follow-up turn never includes earlier responses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# JavaScript: extract the latest assistant response only.
# ChatGPT's current DOM marks every message with data-message-author-role.
# We take the last [data-message-author-role="assistant"] block that is a real
# model response. Request placeholders (id^="request-placeholder-request-", no
# data-message-model-slug) carry a transient "Thinking" label and must be
# ignored — otherwise the extractor returns "Thinking" as if it were the answer.
_GET_LAST_RESPONSE_TEXT_JS = """() => {
    const blocks = document.querySelectorAll('[data-message-author-role="assistant"]');
    for (let i = blocks.length - 1; i >= 0; i--) {
        const last = blocks[i];
        if (last.getAttribute('data-message-id', '').startsWith('request-placeholder-request-')) continue;
        const text = (last.innerText || '').trim();
        if (text.length > 0) return text;
    }
    return null;
}"""

# JavaScript: snapshot of the assistant-message state — text of the last real
# assistant block plus how many real assistant blocks exist.  Used to detect a
# NEW response (block count increased, or the last block's text changed)
# regardless of length, so a follow-up that is shorter than the previous
# response is still detected.  Request placeholders are excluded.
_GET_RESPONSE_STATE_JS = """() => {
    const blocks = document.querySelectorAll('[data-message-author-role="assistant"]');
    const real = Array.from(blocks).filter(b => !b.getAttribute('data-message-id', '').startsWith('request-placeholder-request-'));
    const count = real.length;
    if (count === 0) return { count: 0, text: null };
    const last = real[count - 1];
    const text = (last.innerText || '').trim();
    return { count, text: text.length > 0 ? text : null };
}"""

# JavaScript: detect whether ChatGPT is still generating.
# Covers token streaming (result-streaming / [class*="streaming"]) AND the
# reasoning/thinking phase (result-thinking), which appears BEFORE any tokens
# are streamed. Without the thinking-phase check, the poller would see the
# static "Thinking" placeholder as the finished answer and return it early.
_IS_GENERATING_JS = """
() => {
    // Stop generating button visible = still generating. This is the primary
    // and most reliable signal — it stays visible through streaming, thinking,
    // and browsing/tool-use phases (e.g. @github plugin). When the response
    // completes, this element disappears or changes tooltip.
    if (document.querySelector('[data-testid="stop-generating"]')) return true;

    // Loading/streaming indicators — includes the reasoning phase, where the
    // assistant block carries a result-thinking class before streaming starts.
    // The browsing/searching phase also uses result-thinking while ChatGPT is
    // reading external content (e.g. GitHub). Without this check, stability
    // would accumulate on stale text during browsing and return early.
    const loaders = document.querySelectorAll('.loading-dots, [class*="streaming"], .result-streaming, .result-thinking, [class*="result-thinking"]');
    if (loaders.length > 0) return true;

    // Check for a stop button near the editor — ChatGPT shows this while streaming
    const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('stop')) return true;
    }

    // Page-level busy indicators — ChatGPT may show these during browsing/searching
    const busySelectors = [
        '[class*="spinner"]',
        '[class*="loading"]',
        '[aria-busy="true"]',
        '[data-busy="true"]',
        '[class*="busy"]',
    ];
    for (const sel of busySelectors) {
        if (document.querySelector(sel)) return true;
    }

    // Editor not editable or disabled = ChatGPT is still working on the response.
    const editor = document.querySelector('.ProseMirror');
    if (editor) {
        if (!editor.isContentEditable || editor.hasAttribute('disabled') || !editor.getAttribute('contenteditable')) return true;
    }

    return false;
}
"""


async def get_response_text(client: Any) -> str | None:
    """Return the text of the latest assistant response, or ``None``."""
    result = await client.evaluate(_GET_LAST_RESPONSE_TEXT_JS)
    if isinstance(result, str) and result.strip():
        return result.strip()
    return None


async def _get_response_state(client: Any) -> tuple[int, str | None]:
    """Return ``(assistant_block_count, last_block_text)`` for the page."""
    result = await client.evaluate(_GET_RESPONSE_STATE_JS)
    if not isinstance(result, dict):
        return 0, None
    count = result.get("count") or 0
    text = result.get("text")
    return int(count), (str(text).strip() if isinstance(text, str) and text.strip() else None)


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

    A new response is recognized by *assistant-block identity*, not by length:
    either the number of assistant blocks increases (a fresh turn) or the last
    block's text changes from the baseline.  This means a follow-up that is
    shorter than the previous response is still detected, which length-only
    baselines get wrong.

    Args:
        client: A CdpClient instance with an active page.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        on_chunk: Optional callback receiving partial text as it arrives.
        baseline_length: Retained for API compatibility; new-content detection
            uses block identity rather than length.
        done_marker: If set, treats the arrival of this string as completion.
        prompt_text: Retained for API compatibility; the role-based extractor
            already returns only the assistant response so this is unused.

    Returns:
        The full text of the latest response, or ``None`` on timeout.
    """
    logger.info("Waiting for ChatGPT response (timeout=%.0fs)", timeout)

    base_count, base_text = await _get_response_state(client)

    def is_new(text: str | None) -> bool:
        if not text:
            return False
        if len(text) > baseline_length:
            return True
        return text != base_text

    deadline = time.monotonic() + timeout
    last_text: str | None = None

    # Wait for response to start — either a new assistant block appears or
    # ChatGPT begins generating (stop button appears).  Without this, the
    # previous turn's stale assistant text would be returned as if it were the
    # new response.
    start_deadline = time.monotonic() + 15.0
    while time.monotonic() < start_deadline:
        count, text = await _get_response_state(client)
        if count > base_count or is_new(text):
            break
        if await is_generating(client):
            break
        await asyncio.sleep(1.0)

    while time.monotonic() < deadline:
        count, text = await _get_response_state(client)

        # A response only counts when the block identity moved past baseline
        if not (count > base_count or is_new(text)):
            await asyncio.sleep(interval)
            continue

        # New content detected
        if text and text != last_text:
            last_text = text
            if on_chunk is not None:
                on_chunk(text)
            logger.debug("Response growing: %d chars", len(text))

        # Done marker check
        if done_marker and text and done_marker in text:
            logger.info("Done marker detected")
            return text

        # Check if generation has stopped
        generating = await is_generating(client)
        if not generating:
            # Wait one more interval to confirm nothing more arrives
            await asyncio.sleep(1.0)
            final_text = await get_response_text(client)
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
