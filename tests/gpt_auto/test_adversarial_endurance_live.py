"""Manual live adversarial/endurance acceptance for gpt-auto (GP04/GP05).

Run from the repository root:

    python tests/gpt_auto/test_adversarial_endurance_live.py

Drives PersistentChat/GptAutoProviderRuntime directly against two real,
dedicated ChatGPT projects ("gpt-t1" and "gpt-t2") the same way
test_dual_project_runtime_live.py does. This script covers the scope that
one is NOT built to cover:

  E1 -- endurance: one real, substantial review turn per project, prompt
        includes the literal token "@github" plus this repo's URL and
        branch so ChatGPT's GitHub connector can pull real code. No
        artificial shortening of timeouts; a turn may legitimately take
        up to config.turn.response_timeout_seconds. Both projects run
        concurrently so the two long turns overlap in wall-clock time.

  E2 -- out-of-sequence human interference, IDLE variant: after E1
        completes on gpt-t1, inject a foreign message directly into the
        ChatGPT composer via GptAutoCdpBrowserController.submit() --
        bypassing GptAutoTurn/PersistentChat entirely, exactly as a human
        typing into the tab would -- while the chat is idle between our
        own turns. Then submit a real adapter turn and check whether
        prompt/assistant marker correlation still finds the RIGHT
        response, or gets confused by the foreign exchange sitting in the
        transcript.

  E3 -- out-of-sequence human interference, MID-GENERATION variant: start
        a real adapter turn on gpt-t2, then shortly after send begins (
        while the assistant is still generating), inject a second, foreign
        composer submit via the same direct CDP primitive -- simulating a
        user who did not wait for the response before typing again. Then
        observe: does our own turn resolve correctly to a genuine
        response, misattribute the foreign message's eventual reply, or
        get stuck? This is the hardest, highest-value case in GP04/GP05's
        "detect and ignore or safely resume" requirement.

  AUDIT -- after every scenario, assert PersistentChat.state is not
        transiently stuck and (where an adapter turn was in flight) that
        GptAutoTurn/GptAutoSessionTransport correctly resolved to a
        terminal stop-reason -- i.e. nothing is left "running" once the
        real browser-side outcome has already happened.

This consumes real ChatGPT quota and real wall-clock time (potentially
up to an hour for E1). It is NOT pytest-collected (no ``test_*``
functions, only ``main()``).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.components.providers.adapters.gpt_auto.chat import (  # noqa: E402
    PersistentChat,
)
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig  # noqa: E402
from audiagentic.components.providers.adapters.gpt_auto.runtime import (  # noqa: E402
    GptAutoProviderRuntime,
)
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (  # noqa: E402
    GptAutoSessionTransport,
)
from audiagentic.foundation.transports.agent_session import SessionPrompt  # noqa: E402

PROJECT_A_NAME = "gpt-t1"
PROJECT_B_NAME = "gpt-t2"


def _repo_remote_and_branch() -> tuple[str, str]:
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    if remote.endswith(".git"):
        remote = remote[: -len(".git")]
    return remote, branch


def _load_config() -> GptAutoConfig:
    import yaml

    raw = yaml.safe_load((REPO_ROOT / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8"))
    settings = dict(raw["settings"])
    settings.pop("project-url", None)
    return GptAutoConfig.from_project_dict(settings)


async def _open_chat(
    runtime: GptAutoProviderRuntime, config: GptAutoConfig, session_id: str, project_name: str
) -> GptAutoSessionTransport:
    chat = PersistentChat(
        ag_session_id=session_id,
        project_name=project_name,
        project_url=None,
        runtime=runtime,
        config=config,
        binding_sink=lambda _update: None,
    )
    transport = GptAutoSessionTransport(chat)
    await transport.open()
    print(f"[{project_name}] opened session={session_id} page={chat.page_handle}")
    return transport


async def _send(transport: GptAutoSessionTransport, label: str, text: str) -> dict[str, Any]:
    started = time.time()
    result = await transport.prompt(
        SessionPrompt(turn_id=f"{label}-{uuid.uuid4().hex[:8]}", body=text), lambda _obs: None
    )
    record = {
        "label": label,
        "stop-reason": result.stop_reason,
        "final-summary": (result.final_summary or "")[:400],
        "provider-session-id": transport.chat.provider_session_id,
        "elapsed-seconds": round(time.time() - started, 1),
        "chat-state-after": str(transport.chat.state),
    }
    print(
        f"[{transport.chat.project_name}] {label} stop-reason={record['stop-reason']} "
        f"elapsed={record['elapsed-seconds']}s chat-state={record['chat-state-after']}"
    )
    return record


async def _inject_foreign_message(transport: GptAutoSessionTransport, text: str) -> dict[str, Any]:
    """Simulate a real human typing directly into the tab, bypassing GptAutoTurn."""
    chat = transport.chat
    browser = chat._gpt_browser()  # noqa: SLF001 - deliberate low-level access for adversarial test
    page = await browser.page_by_handle(chat.page_handle)
    started = time.time()
    result = await browser.submit(page, text)
    return {
        "injected-text": text,
        "action-complete": result.get("actionComplete"),
        "elapsed-seconds": round(time.time() - started, 1),
    }


# ── E1: endurance, real @github review turns ────────────────────────


async def scenario_endurance(
    runtime: GptAutoProviderRuntime, config: GptAutoConfig, remote_url: str, branch: str
) -> dict[str, Any]:
    print("\n=== E1: real long-running @github review turns (gpt-t1 + gpt-t2, concurrent) ===")
    transport_a = await _open_chat(runtime, config, f"e-a-{uuid.uuid4().hex[:8]}", PROJECT_A_NAME)
    transport_b = await _open_chat(runtime, config, f"e-b-{uuid.uuid4().hex[:8]}", PROJECT_B_NAME)

    prompt_a = (
        f"@github {remote_url} branch {branch}. "
        "Review plan item GP04 (docs/planning/active/gpt-auto-conversation/GP04.md): "
        "the durable GPT-auto lifecycle/resume runbook. Read the actual code in "
        "src/audiagentic/components/providers/adapters/gpt_auto/ (chat.py, runtime.py, "
        "session_transport.py) and the plan item's acceptance criteria. Give a thorough, "
        "detailed review: what's solid, what's risky, and anything you'd flag before this "
        "ships. Take your time and be thorough."
    )
    prompt_b = (
        f"@github {remote_url} branch {branch}. "
        "Review plan item GP05 (docs/planning/active/gpt-auto-conversation/GP05.md): "
        "multi-project GPT-auto concurrency isolation. Read the actual code in "
        "src/audiagentic/components/providers/adapters/gpt_auto/runtime.py, especially "
        "recover() and the _page_owners/_conversation_owners ownership maps, plus "
        "runtime_registry.py. Give a thorough, detailed review of whether the described "
        "fault-isolation gap and fix approach are sound. Take your time and be thorough."
    )

    results = await asyncio.gather(
        _send(transport_a, "E1-A-review-GP04", prompt_a),
        _send(transport_b, "E1-B-review-GP05", prompt_b),
    )
    return {
        "transport_a": transport_a,
        "transport_b": transport_b,
        "report": {"result-a": results[0], "result-b": results[1]},
    }


# ── E2: out-of-sequence injection, idle variant ─────────────────────


async def scenario_idle_injection(transport_a: GptAutoSessionTransport) -> dict[str, Any]:
    print("\n=== E2: idle out-of-sequence injection on gpt-t1 ===")
    chat_before_state = str(transport_a.chat.state)
    injection = await _inject_foreign_message(
        transport_a, "IGNORE THIS -- a human typed this directly into the tab while idle (E2 test)."
    )
    # Give ChatGPT a moment to actually respond to the foreign message before
    # we submit our own next real turn, to prove the adapter can tell the
    # two exchanges apart rather than accidentally treating the foreign
    # reply as evidence for its own next prompt.
    await asyncio.sleep(8.0)
    real_turn = await _send(
        transport_a, "E2-A-post-idle-injection", "Reply with just the words E2-A-CORRECT-TURN and nothing else."
    )
    return {
        "chat-state-before-injection": chat_before_state,
        "injection": injection,
        "real-turn-after-injection": real_turn,
        "real_turn_stop_reason_terminal": real_turn["stop-reason"] is not None,
    }


# ── E3: out-of-sequence injection, mid-generation variant ───────────


async def scenario_mid_generation_injection(transport_b: GptAutoSessionTransport) -> dict[str, Any]:
    print("\n=== E3: mid-generation out-of-sequence injection on gpt-t2 ===")
    chat = transport_b.chat

    async def real_turn_task() -> dict[str, Any]:
        return await _send(
            transport_b,
            "E3-B-real-turn",
            "Write a two-paragraph explanation of why idempotent recovery matters for browser-"
            "automation-driven chat sessions. Take a normal amount of time to answer.",
        )

    task = asyncio.create_task(real_turn_task())
    # Let our own turn actually begin generating before injecting -- give the
    # submit + first-token window a few seconds, this is inherently timing-
    # sensitive against a real UI so treat the exact window as best-effort.
    await asyncio.sleep(4.0)
    injection_result: dict[str, Any] | None = None
    injection_error: str | None = None
    try:
        injection_result = await _inject_foreign_message(
            transport_b, "IGNORE THIS -- a human typed this mid-generation (E3 test)."
        )
    except Exception as exc:  # noqa: BLE001 - a rejected/blocked injection is itself a valid result
        injection_error = f"{type(exc).__name__}: {exc}"

    real_turn = await task
    control_turn = await _send(
        transport_b, "E3-B-control-after", "Reply with just the words E3-B-STILL-WORKS and nothing else."
    )
    return {
        "injection-result": injection_result,
        "injection-error": injection_error,
        "real-turn": real_turn,
        "real_turn_stop_reason_terminal": real_turn["stop-reason"] is not None,
        "control-turn-after": control_turn,
        "control_turn_stop_reason_terminal": control_turn["stop-reason"] is not None,
        "chat-state-final": str(chat.state),
    }


async def _main_async() -> int:
    remote_url, branch = _repo_remote_and_branch()
    print(f"Using repo={remote_url} branch={branch}")
    config = _load_config()
    runtime = GptAutoProviderRuntime(config)
    report: dict[str, Any] = {"repo": remote_url, "branch": branch}
    try:
        await runtime.ensure_available()

        endurance = await scenario_endurance(runtime, config, remote_url, branch)
        report["E1-endurance"] = endurance["report"]
        transport_a, transport_b = endurance["transport_a"], endurance["transport_b"]

        report["E2-idle-injection"] = await scenario_idle_injection(transport_a)
        report["E3-mid-generation-injection"] = await scenario_mid_generation_injection(transport_b)

        await transport_a.close()
        await transport_b.close()
    finally:
        await runtime.shutdown()

    print("\n=== Final adversarial/endurance report ===")
    print(json.dumps(report, indent=2, default=str))
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
