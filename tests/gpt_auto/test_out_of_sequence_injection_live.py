"""Manual live out-of-sequence human-interference acceptance for gpt-auto (GP04/GP05).

Run from the repository root:

    python tests/gpt_auto/test_out_of_sequence_injection_live.py

Drives PersistentChat/GptAutoProviderRuntime directly against two real,
dedicated ChatGPT projects ("gpt-t1" and "gpt-t2"), one fresh conversation
per project (not reusing any prior conversation), with simple deterministic
prompts. This isolates the out-of-sequence-injection scenarios from the
separate, already-documented @github/tool-connector stall risk exercised in
test_adversarial_endurance_live.py.

  E2 -- IDLE variant: inject a foreign composer submit (bypassing
        GptAutoTurn entirely, exactly as a human typing into the tab would)
        on gpt-t1 while idle between our own turns, then submit a real
        adapter turn and verify it resolves to the CORRECT response rather
        than getting confused by the foreign exchange.

  E3 -- MID-GENERATION variant: start a real adapter turn on gpt-t2, inject
        a foreign composer submit shortly after send while the assistant is
        still generating, then verify our own turn still resolves correctly
        (or fails safely with clear diagnostics -- never silently
        misattributes the foreign exchange), and that a subsequent control
        turn still works normally.

Each scenario is isolated with its own try/except so one project's failure
does not abort the other's coverage. This consumes real ChatGPT quota. It
is NOT pytest-collected (no ``test_*`` functions, only ``main()``).
"""

from __future__ import annotations

import asyncio
import json
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
    print(f"[{project_name}] opened FRESH session={session_id} page={chat.page_handle}")
    return transport


async def _send(transport: GptAutoSessionTransport, label: str, text: str) -> dict[str, Any]:
    started = time.time()
    result = await transport.prompt(
        SessionPrompt(turn_id=f"{label}-{uuid.uuid4().hex[:8]}", body=text), lambda _obs: None
    )
    record = {
        "label": label,
        "stop-reason": result.stop_reason,
        "final-summary": (result.final_summary or "")[:200],
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


async def scenario_idle_injection(runtime: GptAutoProviderRuntime, config: GptAutoConfig) -> dict[str, Any]:
    print("\n=== E2: idle out-of-sequence injection on FRESH gpt-t1 conversation ===")
    transport = await _open_chat(runtime, config, f"e2-a-{uuid.uuid4().hex[:8]}", PROJECT_A_NAME)
    try:
        baseline = await _send(transport, "E2-A-baseline", "Reply with just the words E2-A-BASELINE and nothing else.")
        chat_state_before_injection = str(transport.chat.state)
        injection = await _inject_foreign_message(
            transport, "IGNORE THIS -- a human typed this directly into the tab while idle (E2 test)."
        )
        await asyncio.sleep(8.0)
        real_turn = await _send(
            transport, "E2-A-post-idle-injection", "Reply with just the words E2-A-CORRECT-TURN and nothing else."
        )
        result = {
            "baseline-turn": baseline,
            "chat-state-before-injection": chat_state_before_injection,
            "injection": injection,
            "real-turn-after-injection": real_turn,
            "real_turn_stop_reason_terminal": real_turn["stop-reason"] is not None,
            "provider-session-id-stable": baseline["provider-session-id"] == real_turn["provider-session-id"],
        }
    except Exception as exc:  # noqa: BLE001 - capture, don't abort the other scenario
        result = {"scenario-error": f"{type(exc).__name__}: {exc}", "chat-state-final": str(transport.chat.state)}
    finally:
        await transport.close()
    return result


async def scenario_mid_generation_injection(runtime: GptAutoProviderRuntime, config: GptAutoConfig) -> dict[str, Any]:
    print("\n=== E3: mid-generation out-of-sequence injection on FRESH gpt-t2 conversation ===")
    transport = await _open_chat(runtime, config, f"e3-b-{uuid.uuid4().hex[:8]}", PROJECT_B_NAME)
    try:

        async def real_turn_task() -> dict[str, Any]:
            return await _send(
                transport,
                "E3-B-real-turn",
                "Write a two-paragraph explanation of why idempotent recovery matters for "
                "browser-automation-driven chat sessions. Take a normal amount of time to answer.",
            )

        task = asyncio.create_task(real_turn_task())
        await asyncio.sleep(4.0)
        injection_result: dict[str, Any] | None = None
        injection_error: str | None = None
        try:
            injection_result = await _inject_foreign_message(
                transport, "IGNORE THIS -- a human typed this mid-generation (E3 test)."
            )
        except Exception as exc:  # noqa: BLE001 - a rejected/blocked injection is itself a valid result
            injection_error = f"{type(exc).__name__}: {exc}"

        real_turn = await task
        control_turn = await _send(
            transport, "E3-B-control-after", "Reply with just the words E3-B-STILL-WORKS and nothing else."
        )
        result = {
            "injection-result": injection_result,
            "injection-error": injection_error,
            "real-turn": real_turn,
            "real_turn_stop_reason_terminal": real_turn["stop-reason"] is not None,
            "control-turn-after": control_turn,
            "control_turn_stop_reason_terminal": control_turn["stop-reason"] is not None,
            "chat-state-final": str(transport.chat.state),
        }
    except Exception as exc:  # noqa: BLE001 - capture, don't abort the other scenario
        result = {"scenario-error": f"{type(exc).__name__}: {exc}", "chat-state-final": str(transport.chat.state)}
    finally:
        await transport.close()
    return result


async def _main_async() -> int:
    config = _load_config()
    runtime = GptAutoProviderRuntime(config)
    report: dict[str, Any] = {}
    try:
        await runtime.ensure_available()
        results = await asyncio.gather(
            scenario_idle_injection(runtime, config),
            scenario_mid_generation_injection(runtime, config),
            return_exceptions=True,
        )
        report["E2-idle-injection"] = (
            results[0] if not isinstance(results[0], BaseException) else f"{type(results[0]).__name__}: {results[0]}"
        )
        report["E3-mid-generation-injection"] = (
            results[1] if not isinstance(results[1], BaseException) else f"{type(results[1]).__name__}: {results[1]}"
        )
    finally:
        await runtime.shutdown()

    print("\n=== Final out-of-sequence injection report ===")
    print(json.dumps(report, indent=2, default=str))
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
