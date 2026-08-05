"""Prompt injection into ChatGPT's ProseMirror editor.

ChatGPT uses a ProseMirror-based rich text editor (div.ProseMirror) for input,
not a textarea.  Click the editor, type the prompt, press Enter to submit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from audiagentic.components.providers.adapters.gpt_auto.humanize import (
    think_delay,
    typing_delays,
)

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


# Clear any existing text in the ProseMirror editor and focus it.
_CLEAR_EDITOR_JS = """() => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };
    el.innerHTML = '';
    el.focus();
    return { ok: true };
}"""

# JavaScript: inject a text chunk into the ProseMirror editor with proper
# event dispatching.  Works around puppeteer CDP limitations where keyboard
# events don't reach React/ProseMirror handlers when connected via CDP to an
# already-running browser.  Typing is simulated by appending word chunks with
# human pauses between them (see inject_prompt).
_APPEND_TEXT_JS = """(text) => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };

    const existing = el.textContent || '';
    const next = existing + text;

    // Dispatch beforeinput event (React/ProseMirror listens for this)
    const inputEvent = new InputEvent('beforeinput', {
        bubbles: true, cancelable: true,
        inputType: 'insertText', data: text,
    });
    el.dispatchEvent(inputEvent);

    // Set the text content directly
    el.textContent = next;

    // Dispatch input event to notify React of the change
    const afterInput = new Event('input', { bubbles: true });
    el.dispatchEvent(afterInput);

    return { ok: true, textLength: next.length };
}"""

# Submit the current editor content by clicking the send button — try multiple
# selectors, fall back to a keyboard Enter.
_SUBMIT_JS = """() => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };

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
    humanize: bool = True,
    think_min: float = 1.5,
    think_max: float = 6.0,
    paste_threshold: int = 300,
) -> None:
    """Inject *prompt* into ChatGPT's ProseMirror editor and submit.

    Uses JS evaluate to inject text and dispatch events directly in the page
    context.  When ``humanize`` is True (default):

    - Prompts at or above ``paste_threshold`` characters are pasted in one
      shot (like Ctrl+V from a file) — fast, and humans do paste long text.
    - Shorter prompts are typed word-by-word with jittered per-character
      delays, looking like a real typist.

    Either way a randomized "thinking" pause is taken before pressing send,
    which looks far less scripted to ChatGPT's bot detection.
    """
    logger.info("Injecting prompt (%d chars)", len(prompt))

    clear = await client.evaluate(_CLEAR_EDITOR_JS)
    if isinstance(clear, dict) and "error" in clear:
        raise RuntimeError(f"inject_prompt failed: {clear['error']}")

    words = prompt.split()
    if humanize and words:
        if len(prompt) >= paste_threshold:
            # Large prompt -> simulate a paste (single-shot, fast)
            result = await client.evaluate(_APPEND_TEXT_JS, prompt)
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(f"inject_prompt failed: {result['error']}")
            logger.info("Prompt pasted in one shot (%d chars)", len(prompt))
        else:
            delays = typing_delays(len(prompt))
            # Map the per-char delay schedule onto the position of each word end
            char_index = 0
            for word in words:
                if char_index > 0:
                    # A natural gap between words (~average of the next char delay)
                    await asyncio.sleep(delays[min(char_index, len(delays) - 1)] * 1.5)
                result = await client.evaluate(_APPEND_TEXT_JS, word + " ")
                if isinstance(result, dict) and "error" in result:
                    raise RuntimeError(f"inject_prompt failed: {result['error']}")
                char_index += len(word) + 1
            # Final prompt minus trailing space is handled naturally by ChatGPT
            logger.info("Prompt typed with humanized cadence (%d chars)", char_index)

        # Human "thinking" pause before pressing send
        pause = think_delay(think_min, think_max)
        logger.info("Thinking before submit (%.1fs)", pause)
        await asyncio.sleep(pause)

        result = await client.evaluate(_SUBMIT_JS)
        if isinstance(result, dict):
            if "error" in result:
                raise RuntimeError(f"inject_prompt failed: {result['error']}")
            logger.info("Prompt submitted (%d chars)", result.get("textLength", 0))
        return

    # Non-humanized fallback: inject whole prompt, then submit
    result = await client.evaluate(_APPEND_TEXT_JS, prompt)
    if isinstance(result, dict):
        if "error" in result:
            raise RuntimeError(f"inject_prompt failed: {result['error']}")
        result = await client.evaluate(_SUBMIT_JS)
        if isinstance(result, dict) and "error" in result:
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
