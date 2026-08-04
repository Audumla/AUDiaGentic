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

# JavaScript to check ChatGPT page state - DETECT LOGIN PAGE FIRST
_IS_LOGIN_PAGE_JS = """
() => {
    const text = document.body.textContent || '';
    // Login page indicators
    if (text.includes('Sign in') || text.includes('Log in') || text.includes('Welcome back')) return 'login';
    if (document.querySelector('[data-testid="login-button"], [data-testid="signup-button"], [data-testid="auth-page"]')) return 'login';
    // Email/password inputs without chat interface = login page
    const emailInput = document.querySelector('input[type="email"], input[name="email"], input[autocomplete="email"]');
    const passInput = document.querySelector('input[type="password"]');
    if (emailInput && passInput && !document.querySelector('textarea[placeholder*="Message"], textarea[data-testid="prompt-textarea"]')) return 'login';
    return 'unknown';
}
"""

# JavaScript to check if ChatGPT chat interface is ready (logged in + input visible)
_IS_READY_JS = """
() => {
    // Must have the actual chat prompt textarea (not login forms)
    const chatInput = document.querySelector('textarea[data-testid="prompt-textarea"], textarea[placeholder*="Message"], textarea[placeholder*="Ask"], div[class*="prompt-textarea"]');
    if (!chatInput) return false;
    
    // Must NOT be on login/auth page
    const text = document.body.textContent || '';
    if (text.includes('Sign in') || text.includes('Log in') || text.includes('Welcome back')) return false;
    if (document.querySelector('[data-testid="login-button"], [data-testid="signup-button"], [data-testid="auth-page"]')) return false;
    
    // No error page
    if (document.querySelector('.error-page, [data-testid*="error"]')) return false;
    
    return true;
}
"""

# JavaScript to check if logged in (has conversation history or chat input)
_IS_LOGGED_IN_JS = """
() => {
    const chatInput = document.querySelector('textarea[data-testid="prompt-textarea"], textarea[placeholder*="Message"], textarea[placeholder*="Ask"]');
    const hasHistory = document.querySelector('[data-testid="conversation"], .conversation-list, [data-testid="history"], nav[aria-label="Chat history"]') !== null;
    return !!chatInput || hasHistory;
}
"""


async def wait_for_chatgpt_ready(
    client: Any,
    timeout: float = 30.0,
    login_timeout: float = 120.0,
) -> bool:
    """Wait for ChatGPT to be loaded and ready for input.

    Returns ``True`` if the page is ready within *timeout* seconds.
    If on login page, waits up to *login_timeout* for user to log in.
    """
    logger.info("Checking ChatGPT login state...")

    # FIRST: Check if on login page (before ready check)
    page_state = await client.evaluate(_IS_LOGIN_PAGE_JS)
    if page_state == 'login':
        logger.info("ChatGPT login page detected — waiting for user to log in (timeout: %.0fs)", login_timeout)
        logger.info("Please log in to ChatGPT in the browser window...")
        return await _wait_for_login(client, login_timeout)

    # Check if already logged in and ready
    is_ready = await client.evaluate(_IS_READY_JS)
    if is_ready:
        logger.info("ChatGPT is ready (already logged in)")
        return True

    # Page loaded but not ready — wait for input to appear
    logger.info("ChatGPT loading... waiting for chat input field (timeout: %.0fs)", timeout)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = await client.evaluate(_IS_READY_JS)
        if result:
            logger.info("ChatGPT is ready")
            return True
        await asyncio.sleep(0.5)

    logger.warning("ChatGPT not ready after %.1fs", timeout)
    return False


async def _wait_for_login(client: Any, login_timeout: float) -> bool:
    """Wait for user to complete login on the sign-in page."""
    deadline = asyncio.get_event_loop().time() + login_timeout
    last_logged = 0.0

    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()

        # Log progress every 15 seconds
        if login_timeout - remaining >= last_logged + 15:
            logger.info("Still waiting for login... %.0fs remaining", remaining)
            last_logged = login_timeout - remaining

        # Check if login completed (input field appeared)
        is_ready = await client.evaluate(_IS_READY_JS)
        if is_ready:
            logger.info("Login detected — ChatGPT is ready")
            return True

        # Also check if logged in (has conversation history)
        is_logged_in = await client.evaluate(_IS_LOGGED_IN_JS)
        if is_logged_in:
            logger.info("Logged in state detected")
            return True

        await asyncio.sleep(1.0)

    logger.error("Login timeout after %.0fs", login_timeout)
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
