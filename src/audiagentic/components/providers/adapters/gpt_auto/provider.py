"""Top-level gpt-auto provider — standalone ChatGPT browser driver.

Exports ``run()`` which launches Chrome, navigates to ChatGPT, types the
prompt, waits for the response, and returns the text.  No external API
connectivity required — just a ChatGPT account and Playwright installed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class GptAutoError(Exception):
    """Raised when the gpt-auto provider fails to produce a response."""

    pass


async def run(
    prompt: str,
    *,
    config: Any | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """Run a prompt through ChatGPT via browser automation.

    Args:
        prompt: The text to send to ChatGPT.
        config: A ``GptAutoConfig`` instance (or dict).  Uses defaults when omitted.
        on_chunk: Optional callback receiving the latest response text as it grows.

    Returns:
        The full response text from ChatGPT.

    Raises:
        GptAutoError: If the browser cannot be started, ChatGPT is unreachable,
            or the response times out.
    """
    from audiagentic.components.providers.adapters.gpt_auto.config import (
        GptAutoConfig,
    )
    from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
        wait_for_response,
    )
    from audiagentic.components.providers.adapters.gpt_auto.playwright_client import (
        PlaywrightClient,
    )
    from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
        inject_prompt,
        wait_for_chatgpt_ready,
    )

    # Resolve config
    if isinstance(config, dict):
        cfg = GptAutoConfig.from_dict(config)
    elif config is not None:
        cfg = config
    else:
        cfg = GptAutoConfig()

    client = PlaywrightClient(
        target_url=cfg.target_url,
        profile_dir=cfg.profile_dir if hasattr(cfg, "profile_dir") else None,
        browser_path=getattr(cfg, "browser_path", None),
    )

    try:
        await client.start()
        logger.info("Browser launched")

        # Give the user time to log in if needed
        ready = await wait_for_chatgpt_ready(
            client,
            timeout=float(getattr(cfg, "tab_selection_timeout", 15)),
        )

        if not ready:
            # Take a screenshot for debugging
            await client.screenshot(path="/tmp/gpt-auto-debug.png")
            raise GptAutoError(
                "ChatGPT did not become ready within the timeout. "
                "Make sure you are logged in at chat.openai.com. "
                "A debug screenshot was saved to /tmp/gpt-auto-debug.png"
            )

        logger.info("ChatGPT is ready — injecting prompt")

        # Inject the prompt
        await inject_prompt(
            client,
            prompt,
            typing_delay=cfg.typing_speed,
        )

        logger.info("Prompt submitted — waiting for response")

        # Wait for and extract the response
        response = await wait_for_response(
            client,
            timeout=float(cfg.response_wait_timeout),
            interval=float(cfg.polling_interval),
            on_chunk=on_chunk,
        )

        if response is None:
            raise GptAutoError("No response received from ChatGPT before timeout")

        return response

    except GptAutoError:
        raise
    except Exception as exc:
        raise GptAutoError(f"gpt-auto request failed: {exc}") from exc
    finally:
        await client.stop()
        logger.info("Browser closed")


def run_sync(
    prompt: str,
    *,
    config: Any | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """Synchronous wrapper around ``run()``.

    Blocks the current thread until ChatGPT responds.
    """
    return asyncio.get_event_loop().run_until_complete(
        run(prompt, config=config, on_chunk=on_chunk)
    )
