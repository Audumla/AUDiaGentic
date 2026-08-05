"""gpt-auto adapter — CDP-driven ChatGPT via puppeteer-core.

Connects to an already-running Chrome/Brave browser (navigator.webdriver = false)
to avoid bot detection.  No Playwright, no new browser launch.
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


def _resolve_project_name(working_root: str | None, provider_cfg: dict[str, Any]) -> str:
    """Get the project name from config or git."""
    # Explicit config override
    if provider_cfg.get("project-name"):
        return provider_cfg["project-name"]

    # Try git remote origin
    if working_root:
        import subprocess
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5, cwd=working_root,
            )
            if result.returncode == 0:
                remote = result.stdout.strip()
                repo = Path(remote).stem
                return repo or "AUDiaGentic"
        except Exception:
            pass

    # Fall back to directory name
    if working_root:
        return Path(working_root).name or "AUDiaGentic"
    return "AUDiaGentic"


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    """Execute a prompt through ChatGPT via CDP browser automation."""
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    project_name = _resolve_project_name(working_root, provider_cfg)

    prompt = _build_prompt(packet_ctx, provider_cfg)
    logger.info("gpt-auto: executing prompt (%d chars) for project '%s'", len(prompt), project_name)

    timeout = provider_cfg.get("response-timeout", 120)
    login_timeout = provider_cfg.get("login-timeout", 30)
    typing_speed = provider_cfg.get("typing-speed", 0.03)
    cdp_url = provider_cfg.get("cdp-url", "http://127.0.0.1:9222")
    min_delay_between_requests = provider_cfg.get("min-delay-between-requests", 5.0)
    humanize = provider_cfg.get("humanize", True)
    think_min = provider_cfg.get("think-delay-min", 1.5)
    think_max = provider_cfg.get("think-delay-max", 6.0)
    conversation_id = provider_cfg.get("conversation-id") or packet_ctx.get("conversation-id")

    output_text, metadata = _run_browser(
        prompt=prompt,
        project_name=project_name,
        timeout=timeout,
        login_timeout=login_timeout,
        typing_speed=typing_speed,
        cdp_url=cdp_url,
        min_delay_between_requests=min_delay_between_requests,
        humanize=humanize,
        think_min=think_min,
        think_max=think_max,
        conversation_id=conversation_id,
        cwd=cwd,
    )

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


def _run_browser(
    prompt: str,
    project_name: str,
    timeout: int,
    login_timeout: int,
    typing_speed: float,
    cdp_url: str,
    min_delay_between_requests: float,
    humanize: bool,
    think_min: float,
    think_max: float,
    conversation_id: str | None,
    cwd: Path | None,
) -> tuple[str | None, dict[str, Any]]:
    """Run the CDP browser automation in an event loop."""
    from audiagentic.components.providers.adapters.gpt_auto.cdp_client import (
        CdpClient,
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

    client = CdpClient(cdp_url=cdp_url)

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.start())
            logger.info("gpt-auto: connected to browser via CDP")

            # Find any ChatGPT tab
            tab = loop.run_until_complete(client.find_tab(url_pattern="chatgpt"))
            if not tab:
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-010",
                    kind="providers",
                    message="No ChatGPT tab found — open chat.openai.com first",
                    details={"provider-id": "gpt-auto"},
                )

            # Find workspace for the project (find_workspace navigates there if found).
            # When conversation_id is given, the workspace chat URL is rebuilt so the
            # SAME conversation continues (persistent agent sessions). Otherwise we land
            # on /project — the project's new-chat page — for a fresh session.
            ws = loop.run_until_complete(
                ensure_workspace(client, project_name, conversation_id=conversation_id, project_root=cwd)
            )
            if ws:
                logger.info("gpt-auto: working in workspace '%s': %s", ws.name, ws.url)
                if conversation_id:
                    # Resumed an existing conversation — stay on it, don't reset to /project
                    loop.run_until_complete(client.find_tab(url_pattern="chatgpt"))
                else:
                    # Fresh session: ensure we're on the project new-chat page
                    current_url = loop.run_until_complete(client.get_url())
                    if "/c/" in current_url or "/project" not in current_url:
                        # We're in an existing chat — go back to project home for a new one
                        ws_base = current_url.split("/c/")[0] if "/c/" in current_url else None
                        if ws_base and "/g/g-p-" in ws_base:
                            new_chat_url = ws_base.rstrip("/") + "/project"
                            loop.run_until_complete(client.evaluate(f'() => {{ window.location.href = "{new_chat_url}"; }}'))
                            # Re-find tab after navigation (context destroyed)
                            for _ in range(10):
                                import time as _time
                                _time.sleep(0.5)
                                loop.run_until_complete(client.find_tab(url_pattern="chatgpt"))
                                new_url = loop.run_until_complete(client.get_url())
                                if "/project" in new_url:
                                    break
                            logger.info("gpt-auto: started fresh chat at %s", new_chat_url)
                    else:
                        # Already on /project — re-find tab after context change
                        loop.run_until_complete(client.find_tab(url_pattern="chatgpt"))

            # Wait for ChatGPT ready (ProseMirror visible)
            ready = loop.run_until_complete(
                wait_for_chatgpt_ready(client, timeout=30.0, login_timeout=float(login_timeout))
            )
            if not ready:
                debug_path = str(cwd / "gpt-auto-not-ready.png" if cwd else "/tmp/gpt-auto-not-ready.png")
                loop.run_until_complete(client.screenshot(path=debug_path))
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-011",
                    kind="providers",
                    message="ChatGPT not ready after login timeout",
                    details={"provider-id": "gpt-auto", "timeout": login_timeout},
                )

            # Human-like pause between requests (reduces bot-detection flagging)
            from audiagentic.components.providers.adapters.gpt_auto.humanize import (
                jittered,
            )
            if min_delay_between_requests > 0:
                pause = jittered(min_delay_between_requests, jitter=0.4)
                logger.info("gpt-auto: pausing %.1fs before request", pause)
                loop.run_until_complete(asyncio.sleep(pause))

            # Inject prompt into ProseMirror editor (humanized typing + think pause)
            loop.run_until_complete(
                inject_prompt(
                    client,
                    prompt,
                    typing_speed,
                    humanize=humanize,
                    think_min=think_min,
                    think_max=think_max,
                )
            )
            logger.info("gpt-auto: prompt submitted")

            chunks: list[str] = []

            def on_chunk(text: str) -> None:
                chunks.append(text)

            response = loop.run_until_complete(
                wait_for_response(client, timeout=float(timeout), interval=2.0, on_chunk=on_chunk, prompt_text=prompt)
            )

            if not response:
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-012",
                    kind="providers",
                    message="No response received from ChatGPT before timeout",
                    details={"provider-id": "gpt-auto", "timeout": timeout},
                )

            # Capture session/conversation metadata after response (ChatGPT may have updated URL to /c/{conv-id})
            chat_url = loop.run_until_complete(client.get_url())
            metadata = {"chat-url": chat_url}
            if "/c/" in chat_url:
                conv_id = chat_url.split("/c/")[-1].rstrip("/")
                metadata["conversation-id"] = conv_id
            if "/g/g-p-" in chat_url:
                ws_segment = chat_url.split("/g/g-p-")[1].split("/")[0]
                metadata["workspace-id"] = f"ws-{ws_segment}"

            # Remember the tab that holds this workspace + the conversation id so the
            # NEXT run reuses the same tab instead of opening yet another one.
            from audiagentic.components.providers.adapters.gpt_auto import tab_state
            if cwd is not None:
                tabs = loop.run_until_complete(client.list_tabs())
                tab_id = next((t.tab_id for t in tabs if chat_url and chat_url.startswith(t.url.split("#")[0].rstrip("/"))), "")
                if not tab_id and tabs:
                    tab_id = tabs[-1].tab_id
                tab_state.update_mapping(
                    project_name,
                    tab_id=tab_id,
                    workspace_url=chat_url.split("/c/")[0] if "/c/" in chat_url else chat_url,
                    conversation_id=metadata.get("conversation-id"),
                    project_root=cwd,
                )

            return response, metadata

        finally:
            loop.run_until_complete(client.stop())
            loop.close()

    except AudiaGenticError:
        raise
    except Exception as exc:
        raise AudiaGenticError(
            code="EXT-GPTAUTO-013",
            kind="providers",
            message=f"gpt-auto CDP automation failed: {exc}",
            details={"provider-id": "gpt-auto", "error": str(exc)},
        ) from exc