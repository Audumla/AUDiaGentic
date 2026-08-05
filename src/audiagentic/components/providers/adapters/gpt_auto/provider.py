"""Top-level gpt-auto provider — CDP-driven ChatGPT browser automation.

Uses puppeteer-core via CDP to connect to an already-running Chrome/Brave,
so ``navigator.webdriver`` stays ``false`` and ChatGPT doesn't detect bot
presence.  No Playwright, no new browser launch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GptAutoError(Exception):
    """Raised when the gpt-auto provider fails to produce a response."""
    pass


# Natural prompt variations for testing — avoid identical rapid-fire prompts.
_TEST_PROMPTS = [
    "What are the trade-offs between SQL and NoSQL databases?",
    "Explain how merge sort works with an example.",
    "What's the difference between authentication and authorization?",
    "How does a CDN improve website performance?",
    "Compare React and Vue.js for building SPAs.",
]


def _resolve_project_name(working_root: str | None) -> str:
    """Get the project name from the working root or git config."""
    if not working_root:
        return "AUDiaGentic"

    # Try git remote origin first
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, cwd=working_root,
        )
        if result.returncode == 0:
            remote = result.stdout.strip()
            # Extract last path component (repo name)
            repo = Path(remote).stem
            return repo or "AUDiaGentic"
    except Exception:
        pass

    # Fall back to directory name
    return Path(working_root).name or "AUDiaGentic"


async def run(
    prompt: str,
    *,
    config: Any | None = None,
    on_chunk: Callable[[str], None] | None = None,
    cdp_url: str = "http://127.0.0.1:9222",
    project_name: str = "AUDiaGentic",
) -> str:
    """Run a prompt through ChatGPT via CDP browser automation.

    Args:
        prompt: The text to send to ChatGPT.
        config: A ``GptAutoConfig`` instance (or dict).  Uses defaults when omitted.
        on_chunk: Optional callback receiving the latest response text as it grows.
        cdp_url: Chrome DevTools Protocol URL of the running browser.
        project_name: AUDiaGentic project name — maps to ChatGPT workspace.

    Returns:
        The full response text from ChatGPT.

    Raises:
        GptAutoError: If the connection fails, ChatGPT is unreachable, or times out.
    """
    from audiagentic.components.providers.adapters.gpt_auto.cdp_client import (
        CdpClient,
    )
    from audiagentic.components.providers.adapters.gpt_auto.config import (
        GptAutoConfig,
    )
    from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
        wait_for_response,
    )
    from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
        inject_prompt,
        wait_for_chatgpt_ready,
    )
    from audiagentic.components.providers.adapters.gpt_auto.workspace import (
        ensure_workspace,
    )

    if isinstance(config, dict):
        cfg = GptAutoConfig.from_dict(config)
    elif config is not None:
        cfg = config
    else:
        cfg = GptAutoConfig()

    client = CdpClient(cdp_url=cdp_url)

    try:
        await client.start()
        logger.info("Connected to browser via CDP")

        # Find ChatGPT tab
        tab = await client.find_tab(url_pattern="chatgpt")
        if not tab:
            await client.screenshot(path="/tmp/gpt-auto-no-tab.png")
            raise GptAutoError(
                "No ChatGPT tab found. Open chat.openai.com in your browser first."
            )
        logger.info("Found ChatGPT tab: %s", tab.url)

        # Find workspace for the project (find_workspace navigates there if found)
        ws = await ensure_workspace(client, project_name)
        if ws:
            logger.info("Working in workspace '%s': %s", ws.name, ws.url)
            # ensure_workspace navigated to the workspace, re-find tab after context change
            await client.find_tab(url_pattern="chatgpt")

        # Wait for ChatGPT to be ready (logged in, ProseMirror visible)
        ready = await wait_for_chatgpt_ready(
            client,
            timeout=float(getattr(cfg, "tab_selection_timeout", 15)),
            login_timeout=float(getattr(cfg, "login_timeout", 120)),
        )
        if not ready:
            await client.screenshot(path="/tmp/gpt-auto-not-ready.png")
            raise GptAutoError(
                "ChatGPT did not become ready. Make sure you are logged in."
            )

        logger.info("ChatGPT is ready — injecting prompt")

        # Inject the prompt into ProseMirror editor
        await inject_prompt(client, prompt, typing_delay=cfg.typing_speed)
        logger.info("Prompt submitted — waiting for response")

        # Poll for response from <p> elements
        response = await wait_for_response(
            client,
            timeout=float(cfg.response_wait_timeout),
            interval=float(cfg.polling_interval),
            on_chunk=on_chunk,
            prompt_text=prompt,
        )

        if not response:
            raise GptAutoError("No response received from ChatGPT before timeout")

        return response

    except GptAutoError:
        raise
    except Exception as exc:
        raise GptAutoError(f"gpt-auto request failed: {exc}") from exc
    finally:
        await client.stop()
        logger.info("CDP connection closed")


def run_sync(
    prompt: str,
    *,
    config: Any | None = None,
    on_chunk: Callable[[str], None] | None = None,
    cdp_url: str = "http://127.0.0.1:9222",
    project_name: str = "AUDiaGentic",
) -> str:
    """Synchronous wrapper around ``run()``."""
    return asyncio.get_event_loop().run_until_complete(
        run(prompt, config=config, on_chunk=on_chunk, cdp_url=cdp_url, project_name=project_name)
    )


def get_test_prompt(index: int = 0) -> str:
    """Get a natural test prompt to avoid bot detection from identical queries."""
    return _TEST_PROMPTS[index % len(_TEST_PROMPTS)]