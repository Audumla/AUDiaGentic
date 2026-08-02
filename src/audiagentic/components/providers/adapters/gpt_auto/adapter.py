"""gpt-auto adapter — browser-driven ChatGPT via Playwright.

Called by the provider execution service.  No CLI, no MCP, no API key —
launches a Chromium browser with persistent cookies, types the prompt into
chat.openai.com, and reads the response from the DOM.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import (
    finalize_run,
)
from audiagentic.components.providers.protocols.streaming.completion import (
    ResultSource,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _build_prompt(
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any],
) -> str:
    """Assemble the full prompt text from the execution packet."""
    system = packet_ctx.get("system-prompt", "")
    user_text = packet_ctx.get("prompt", "")
    modified = packet_ctx.get("modified-prompt")

    parts: list[str] = []
    if system:
        parts.append(system)
    prompt_body = modified if modified is not None else user_text
    if prompt_body:
        parts.append(prompt_body)
    return "\n\n".join(parts) if parts else user_text


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    """Execute a prompt through ChatGPT via browser automation.

    This is the adapter entry point called by the provider execution service.
    """
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    prompt = _build_prompt(packet_ctx, provider_cfg)
    logger.info("gpt-auto: executing prompt (%d chars)", len(prompt))

    # Read config overrides from provider_cfg
    timeout = provider_cfg.get("response-timeout", 120)
    login_timeout = provider_cfg.get("login-timeout", 30)
    typing_speed = provider_cfg.get("typing-speed", 0.02)

    # Run the async browser automation in an event loop
    output_text = _run_browser(
        prompt=prompt,
        timeout=timeout,
        login_timeout=login_timeout,
        typing_speed=typing_speed,
        cwd=cwd,
    )

    return finalize_run(
        provider_id="gpt-auto",
        packet_ctx=packet_ctx,
        provider_cfg=provider_cfg,
        command=["gpt-auto", "browser"],
        stdout_text=output_text or "",
        stderr_text="",
        returncode=0 if output_text is not None else 1,
        parsed_data={"response": output_text},
        result_source=(
            ResultSource.STDOUT_TEXT
            if output_text is not None
            else ResultSource.FALLBACK_SYNTHETIC
        ),
        output_text=output_text,
        extra_result={"job-id": packet_ctx.get("job-id")},
    )


def _run_browser(
    prompt: str,
    timeout: int,
    login_timeout: int,
    typing_speed: float,
    cwd: Path | None,
) -> str | None:
    """Run the browser automation in an event loop."""
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

    client = PlaywrightClient(
        target_url="https://chat.openai.com",
    )

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.start())
            logger.info("gpt-auto: browser launched")

            ready = loop.run_until_complete(
                wait_for_chatgpt_ready(client, timeout=float(login_timeout))
            )
            if not ready:
                loop.run_until_complete(
                    client.screenshot(path=str(cwd / "gpt-auto-not-ready.png" if cwd else "/tmp/gpt-auto-not-ready.png"))
                )
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-001",
                    kind="providers",
                    message="ChatGPT not ready after login timeout",
                    details={
                        "provider-id": "gpt-auto",
                        "timeout": login_timeout,
                    },
                )

            loop.run_until_complete(inject_prompt(client, prompt, typing_speed))
            logger.info("gpt-auto: prompt submitted")

            chunks: list[str] = []
            def on_chunk(text: str) -> None:
                chunks.append(text)

            response = loop.run_until_complete(
                wait_for_response(
                    client,
                    timeout=float(timeout),
                    interval=2.0,
                    on_chunk=on_chunk,
                )
            )

            if response is None:
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-002",
                    kind="providers",
                    message="No response received from ChatGPT before timeout",
                    details={
                        "provider-id": "gpt-auto",
                        "timeout": timeout,
                    },
                )

            return response

        finally:
            loop.run_until_complete(client.stop())
            loop.close()

    except AudiaGenticError:
        raise
    except Exception as exc:
        raise AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message=f"gpt-auto browser automation failed: {exc}",
            details={"provider-id": "gpt-auto", "error": str(exc)},
        ) from exc
