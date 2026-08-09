"""gpt-auto adapter — CDP-driven ChatGPT via puppeteer-core.

Connects to an already-running Chrome/Brave browser (navigator.webdriver = false)
to avoid bot detection.  No Playwright, no new browser launch.

The one-shot ``run()`` is a thin wrapper around the session transport:
open → prompt → close.  The tab stays open after each run; the conversation
persists in ChatGPT.  There is no "one-shot" behavior — it's a single turn
through a real session.
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
from audiagentic.foundation.transports.agent_session import SessionPrompt

from .provider import GptAutoError

logger = logging.getLogger(__name__)


def _build_prompt(
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any],
) -> str:
    """Assemble the full prompt text from the execution packet.

    If no user prompt was supplied and ``use-prompt-pool`` is enabled in the
    provider config, a prompt is drawn from the rotating pool (used mainly by
    automated testing to avoid bot detection from repeated canned prompts).
    """
    system = packet_ctx.get("system-prompt", "")
    user_text = packet_ctx.get("prompt", "")
    modified = packet_ctx.get("modified-prompt")

    if not user_text and not modified and provider_cfg.get("use-prompt-pool"):
        from audiagentic.components.providers.adapters.gpt_auto.prompt_pool import (
            pick_prompt,
        )
        user_text = pick_prompt()

    parts: list[str] = []
    if system:
        parts.append(system)
    prompt_body = modified if modified is not None else user_text
    if prompt_body:
        parts.append(prompt_body)
    return "\n\n".join(parts) if parts else user_text


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    """Execute a single turn through ChatGPT via the session transport.

    Thin wrapper: open → humanize pause → prompt → capture metadata → close.
    The browser tab stays open after the run; the conversation persists.
    """
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    project_name = _resolve_project_name(working_root, provider_cfg)
    prompt = _build_prompt(packet_ctx, provider_cfg)
    logger.info("gpt-auto: executing prompt (%d chars) for project '%s'", len(prompt), project_name)

    timeout = provider_cfg.get("response-timeout", 120)
    tab_selection_timeout = provider_cfg.get("tab-selection-timeout", 15)
    typing_speed = provider_cfg.get("typing-speed", 0.03)
    cdp_url = provider_cfg.get("cdp-url", "http://127.0.0.1:9222")
    min_delay_between_requests = provider_cfg.get("min-delay-between-requests", 5.0)
    logger.info(
        "gpt-auto adapter config project=%s prompt-chars=%d response-timeout=%ss tab-selection-timeout=%ss login-wait=disabled min-delay=%ss",
        project_name,
        len(prompt),
        timeout,
        tab_selection_timeout,
        min_delay_between_requests,
        extra={"gpt-auto-phase": "adapter.config"},
    )

    # Build transport config — the session transport owns CDP lifecycle, workspace
    # resolution, bring_to_front, stability-window polling, and tab mapping.
    transport_cfg: dict[str, Any] = {
        "response_wait_timeout": timeout,
        "tab_selection_timeout": tab_selection_timeout,
        "typing_speed": typing_speed,
    }

    # Resume an existing conversation if a conversation-id was supplied.
    resume_ref = provider_cfg.get("conversation-id") or packet_ctx.get("conversation-id")

    from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
        build_gpt_auto_session_transport,
    )

    transport = build_gpt_auto_session_transport(
        project_root=cwd,
        config=transport_cfg,
        project_name=project_name,
        resume_provider_ref=resume_ref,
    )

    def _sink(obs: Any) -> None:
        """Discard observations — one-shot path doesn't need them."""

    loop = asyncio.new_event_loop()
    try:
        # Open session (resolves workspace, brings tab to front, maps tab state)
        loop.run_until_complete(transport.open())

        # Human-like pause between requests (reduces bot-detection flagging).
        if min_delay_between_requests > 0:
            from audiagentic.components.providers.adapters.gpt_auto.humanize import (
                jittered,
            )
            pause = jittered(min_delay_between_requests, jitter=0.4)
            logger.info("gpt-auto: pausing %.1fs before request", pause)
            loop.run_until_complete(asyncio.sleep(pause))

        # Single turn through the session transport (brings tab to front, injects,
        # polls with stability window).
        result = loop.run_until_complete(
            transport.prompt(
                SessionPrompt(turn_id="one-shot-1", body=prompt),
                sink=_sink,
            )
        )

        output_text = result.final_summary if result.stop_reason == "end_turn" else None

        # Capture metadata from the current URL (transport's client).
        metadata: dict[str, Any] = {}
        try:
            chat_url = loop.run_until_complete(transport._client.get_url())  # type: ignore[union-attr]
            metadata["chat-url"] = chat_url
            if "/c/" in chat_url:
                conv_id = chat_url.split("/c/")[-1].rstrip("/")
                metadata["conversation-id"] = conv_id
            if "/g/g-p-" in chat_url:
                ws_segment = chat_url.split("/g/g-p-")[1].split("/")[0]
                metadata["workspace-id"] = f"ws-{ws_segment}"
        except Exception:
            logger.debug("failed to capture one-shot metadata", exc_info=True)

    except AudiaGenticError:
        raise
    except GptAutoError as exc:
        raise AudiaGenticError(
            code="EXT-GPTAUTO-013",
            kind="providers",
            message=f"gpt-auto CDP automation failed: {exc}",
            details={"provider-id": "gpt-auto", "error": str(exc)},
        ) from exc
    except Exception as exc:
        raise AudiaGenticError(
            code="EXT-GPTAUTO-013",
            kind="providers",
            message=f"gpt-auto CDP automation failed: {exc}",
            details={"provider-id": "gpt-auto", "error": str(exc)},
        ) from exc
    finally:
        loop.run_until_complete(transport.close())
        loop.close()

    return finalize_run(
        provider_id="gpt-auto",
        packet_ctx=packet_ctx,
        provider_cfg=provider_cfg,
        command=["gpt-auto", "cdp"],
        stdout_text=output_text or "",
        stderr_text="",
        returncode=0 if output_text is not None else 1,
        parsed_data={**{"response": output_text}, **metadata},
        result_source=(
            ResultSource.STDOUT_TEXT
            if output_text is not None
            else ResultSource.FALLBACK_SYNTHETIC
        ),
        output_text=output_text,
        extra_result={**{"job-id": packet_ctx.get("job-id"), "project-name": project_name}, **metadata},
    )
