"""Prompt injection into ChatGPT's ProseMirror editor.

ChatGPT uses a ProseMirror-based rich text editor (div.ProseMirror) for input,
not a textarea.  Click the editor, type the prompt, press Enter to submit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_PROSEMIRROR_SELECTOR = ".ProseMirror"

# JavaScript: check if ChatGPT chat interface is ready (logged in + input visible)
_IS_READY_JS = """
() => {
    const editor = document.querySelector('.ProseMirror');
    if (!editor) return false;

    const text = document.body.textContent || '';
    if (text.includes('Sign in') || text.includes('Log in') || text.includes('Welcome back')) return false;
    if (document.querySelector('[data-testid="login-button"], [data-testid="signup-button"]')) return false;
    if (document.querySelector('.error-page, [data-testid*="error"]')) return false;
    return true;
}
"""

_IS_LOGIN_PAGE_JS = """
() => {
    const text = document.body.textContent || '';
    if (text.includes('Sign in') || text.includes('Log in') || text.includes('Welcome back')) return 'login';
    if (document.querySelector('[data-testid="login-button"], [data-testid="signup-button"]')) return 'login';
    const emailInput = document.querySelector('input[type="email"]');
    const passInput = document.querySelector('input[type="password"]');
    if (emailInput && passInput && !document.querySelector('.ProseMirror')) return 'login';
    return 'unknown';
}
"""

_IS_LOGGED_IN_JS = """
() => {
    const chatInput = document.querySelector('.ProseMirror');
    const hasHistory = document.querySelector('[data-testid="conversation"], .conversation-list, nav[aria-label="Chat history"]') !== null;
    return !!chatInput || hasHistory;
}
"""

_GET_EDITOR_TEXT_JS = """
() => {
    const editor = document.querySelector('.ProseMirror');
    if (!editor) return '';
    return editor.innerText.trim();
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

    page_state = await client.evaluate(_IS_LOGIN_PAGE_JS)
    if page_state == 'login':
        logger.info("Login page detected — waiting (timeout: %.0fs)", login_timeout)
        return await _wait_for_login(client, login_timeout)

    is_ready = await client.evaluate(_IS_READY_JS)
    if is_ready:
        logger.info("ChatGPT is ready")
        return True

    logger.info("Waiting for chat interface (timeout: %.0fs)", timeout)
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
    """Wait for user to complete login."""
    deadline = asyncio.get_event_loop().time() + login_timeout
    last_logged = 0.0

    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()

        if login_timeout - remaining >= last_logged + 15:
            logger.info("Waiting for login... %.0fs remaining", remaining)
            last_logged = login_timeout - remaining

        is_ready = await client.evaluate(_IS_READY_JS)
        if is_ready:
            logger.info("Login detected")
            return True

        is_logged_in = await client.evaluate(_IS_LOGGED_IN_JS)
        if is_logged_in:
            logger.info("Logged in state detected")
            return True

        await asyncio.sleep(1.0)

    logger.error("Login timeout after %.0fs", login_timeout)
    return False


# JavaScript: inject text into ProseMirror editor with proper event dispatching
# and submit by clicking the send button. Works around puppeteer CDP limitations
# where keyboard events don't reach React/ProseMirror handlers.
_INJECT_AND_SUBMIT_JS = """(prompt) => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };

    // Clear existing text
    el.innerHTML = '';
    el.focus();

    // Dispatch beforeinput event (React/ProseMirror listens for this)
    const inputEvent = new InputEvent('beforeinput', {
        bubbles: true, cancelable: true,
        inputType: 'insertText', data: prompt,
    });
    el.dispatchEvent(inputEvent);

    // Set the text content directly
    el.textContent = prompt;

    // Dispatch input event to notify React of the change
    const afterInput = new Event('input', { bubbles: true });
    el.dispatchEvent(afterInput);

    // Also dispatch composition events (React may listen for these)
    el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    el.dispatchEvent(new CompositionEvent('compositionupdate', { bubbles: true, data: prompt }));
    el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: prompt }));

    // Click the send button to submit — try multiple selectors
    const btns = document.querySelectorAll('button, [role="button"]');
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('send') || label.includes('submit')) {
            b.click();
            return { submitted: true, textLength: el.innerText.length, buttonLabel: b.getAttribute('aria-label') };
        }
    }
    
    // Fallback 1: look for the send button near the editor by position (bottom-right of input area)
    const editorRect = el.getBoundingClientRect();
    for (const b of btns) {
        const bRect = b.getBoundingClientRect();
        const style = window.getComputedStyle(b);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        // Send button is typically to the right of the editor at roughly the same height
        if (bRect.width > 0 && bRect.height > 0 && 
            bRect.left > editorRect.left + editorRect.width * 0.5 &&
            Math.abs(bRect.top - editorRect.bottom) < 60) {
            b.click();
            return { submitted: true, textLength: el.innerText.length, fallbackPosition: true };
        }
    }

    // Fallback 2: try keyboard Enter (works in most ChatGPT contexts)
    const enterEvent = new KeyboardEvent('keydown', {
        bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', which: 13, keyCode: 13
    });
    el.dispatchEvent(enterEvent);
    return { submitted: true, textLength: el.innerText.length, fallbackMethod: 'keyboard' };
}"""


async def inject_prompt(
    client: Any,
    prompt: str,
    typing_delay: float = 0.03,
) -> None:
    """Inject *prompt* into ChatGPT's ProseMirror editor and submit.

    Uses JS evaluate to inject text and dispatch events directly in the page
    context — works around puppeteer CDP limitations where click/keyboard
    events don't reach React/ProseMirror handlers when connected via CDP to
    an already-running browser.
    """
    logger.info("Injecting prompt (%d chars)", len(prompt))

    result = await client.evaluate(_INJECT_AND_SUBMIT_JS, prompt)
    if isinstance(result, dict):
        if "error" in result:
            raise RuntimeError(f"inject_prompt failed: {result['error']}")
        logger.info("Prompt injected and submitted (%d chars)", result.get("textLength", 0))


async def inject_prompt_with_retry(
    client: Any,
    prompt: str,
    typing_delay: float = 0.03,
    max_retries: int = 2,
) -> None:
    """Inject a prompt, retrying focus if the first attempt fails."""
    for attempt in range(1, max_retries + 1):
        try:
            await inject_prompt(client, prompt, typing_delay)
            return
        except RuntimeError as exc:
            if attempt < max_retries:
                logger.warning("inject_prompt attempt %d failed: %s — retrying", attempt, exc)
                await asyncio.sleep(1.0)
            else:
                raise
