"""Prompt injection into ChatGPT's input field.

Waits for the textarea element, types the prompt text, and presses Enter
to submit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Selectors known to match ChatGPT's input area — try in order.
CHATGPT_INPUT_SELECTORS = [
    "textarea[placeholder]",  # generic: any textarea with placeholder
    'div[class*="prompt-textarea"]',  # older ChatGPT layout
    '[data-testid="prompt-textarea"]',  # data-testid (if present)
]

# JavaScript that focuses and types into the first matching input.
_FOCUS_AND_TYPE_JS = """
() => {
    // Try common selectors
    const selectors = [
        'textarea[placeholder]',
        'div[class*="prompt-textarea"]',
        '[data-testid="prompt-textarea"]',
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
            el.focus();
            el.click();
            return true;
        }
    }
    // Fallback: find any textarea in a contenteditable or input-like container
    const textareas = document.querySelectorAll('textarea');
    for (const ta of textareas) {
        if (ta.closest('form') || ta.parentElement?.textContent?.includes('Ask')) {
            ta.focus();
            ta.click();
            return true;
        }
    }
    return false;
}
"""

# JavaScript to detect if ChatGPT appears ready (logged in + input visible).
_IS_READY_JS = """
() => {
    const input = document.querySelector('textarea[placeholder]');
    return !!input && !document.querySelector('.error-page, [data-testid*="error"]');
}
"""


async def wait_for_chatgpt_ready(
    client: Any,
    timeout: float = 10.0,
) -> bool:
    """Wait for ChatGPT to be loaded and ready for input.

    Returns ``True`` if the page is ready within *timeout* seconds.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = await client.evaluate(_IS_READY_JS)
        if result:
            logger.debug("ChatGPT is ready")
            return True
        await asyncio.sleep(0.5)

    # Also check for a login screen — that means user needs to authenticate
    is_login = await client.evaluate("() => document.body.textContent.includes('Sign in')")
    if is_login:
        logger.info("ChatGPT is on the sign-in page — user must log in")
    else:
        logger.debug("ChatGPT not ready after %.1fs", timeout)
    return False


async def inject_prompt(
    client: Any,
    prompt: str,
    typing_delay: float = 0.02,
) -> None:
    """Type *prompt* into ChatGPT's input field and press Enter.

    Steps:
    1. Focus the textarea via DOM script.
    2. Type the text character-by-character (human-like speed).
    3. Wait a brief pause, then press Enter to submit.
    """
    logger.info("Injecting prompt (%d chars)", len(prompt))

    # Focus the input area
    focused = await client.evaluate(_FOCUS_AND_TYPE_JS)
    if not focused:
        raise RuntimeError("Could not focus ChatGPT input — make sure you're on chat.openai.com")

    await asyncio.sleep(0.3)  # brief pause after focus

    # Type the prompt
    await client.type_text(prompt, delay=typing_delay)

    # Pause before submit — lets the UI process the text
    await asyncio.sleep(0.5)

    # Submit
    logger.info("Submitting prompt")
    await client.press_key("Enter")


async def inject_prompt_with_retry(
    client: Any,
    prompt: str,
    typing_delay: float = 0.02,
    max_retries: int = 2,
) -> None:
    """Inject a prompt, retrying focus if the first attempt fails."""
    for attempt in range(1, max_retries + 1):
        try:
            await inject_prompt(client, prompt, typing_delay)
            return
        except RuntimeError as exc:
            if attempt < max_retries:
                logger.warning(
                    "inject_prompt attempt %d failed: %s — retrying",
                    attempt,
                    exc,
                )
                await asyncio.sleep(1.0)
            else:
                raise
