"""Manual live low-level PersistentChat/GptAutoProviderRuntime acceptance.

Run from the repository root:

    python tests/gpt_auto/test_dual_project_runtime_live.py

Drives the real gpt-auto adapter machinery DIRECTLY -- GptAutoProviderRuntime
+ PersistentChat + GptAutoSessionTransport/GptAutoTurn -- bypassing the
gateway's dispatch/session-store/admission layer entirely. This is the lower
layer validated FIRST; see test_multi_project_concurrency_live.py for the
same scenarios re-verified through the full MCP/gateway surface.

Targets two REAL, dedicated ChatGPT projects created for this purpose:
"gpt-t1" and "gpt-t2", matched by name via PersistentChat's project
discovery (chat.py's find_project_url path over https://chatgpt.com/projects,
exercised deterministically in test_project_discovery.py). Both simulated
chats share ONE GptAutoProviderRuntime -- the runtime is machine-scoped by
design (runtime_registry.get_runtime's explicit ``del project_root``), so
this is the natural, honest way to construct two "projects" at this layer:
there is no project-scoped runtime to instantiate twice.

Three scenarios, run in order:
  L1 -- concurrency: two PersistentChat instances driven concurrently
        (asyncio.gather), 3 turns each, interleaved.
  L2 -- isolated page loss: close ONE chat's page directly over CDP
        (Target.closeTarget on its exact pageHandle, via the SAME bridge the
        runtime already owns) and confirm only that chat's page_lost() fires.
        _route_events only escalates page_closed/page_crashed to the chat
        that owns the handle (runtime.py's _route_events), never every chat
        -- this is the routing-level isolation GP05 needs to hold.
  L3 -- global recover() blast radius (the direct GP05 probe): call
        runtime.recover() -- the exact code path a real browser/CDP
        disconnect triggers (runtime.py lines ~274-300) -- while BOTH chats
        are healthy and idle, and measure whether the untouched chat is
        forced through bridge_replaced()+reconcile() too, and how long that
        costs it. Deterministic: no need to actually kill the browser to
        exercise this path.

This consumes real ChatGPT quota and real wall-clock time. It is NOT
pytest-collected (no ``test_*`` functions, only ``main()``).
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
TURN_TIMEOUT_HINT_SECONDS = 900.0  # informational; real bound is config.turn.response_timeout_seconds


def _load_config() -> GptAutoConfig:
    """Load the repo's real, validated gpt-auto settings, but force
    per-chat project-name discovery (drop project-url) so this script
    resolves gpt-t1/gpt-t2 by name rather than reusing the repo's own
    ChatGPT project URL."""
    import yaml

    raw = yaml.safe_load((REPO_ROOT / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8"))
    settings = dict(raw["settings"])
    settings.pop("project-url", None)
    return GptAutoConfig.from_dict(settings)


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
    print(
        f"[{project_name}] opened session={session_id} page={chat.page_handle} "
        f"project_url={chat.project_url}"
    )
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
        "chat-url": transport.chat.chat_url,
        "elapsed-seconds": round(time.time() - started, 1),
    }
    print(
        f"[{transport.chat.project_name}] {label} stop-reason={record['stop-reason']} "
        f"provider-session-id={record['provider-session-id']} elapsed={record['elapsed-seconds']}s"
    )
    return record


# ── L1: concurrency ──────────────────────────────────────────────────


async def scenario_concurrency(runtime: GptAutoProviderRuntime, config: GptAutoConfig) -> dict[str, Any]:
    print("\n=== L1: concurrent direct PersistentChat turns (gpt-t1 + gpt-t2) ===")
    transport_a = await _open_chat(runtime, config, f"direct-a-{uuid.uuid4().hex[:8]}", PROJECT_A_NAME)
    transport_b = await _open_chat(runtime, config, f"direct-b-{uuid.uuid4().hex[:8]}", PROJECT_B_NAME)

    async def sequence(transport: GptAutoSessionTransport, prefix: str, prompts: list[str]) -> list[dict[str, Any]]:
        out = []
        for i, prompt in enumerate(prompts, start=1):
            out.append(await _send(transport, f"{prefix}-turn-{i}", prompt))
        return out

    results_a, results_b = await asyncio.gather(
        sequence(
            transport_a,
            "L1-A",
            [
                "Reply with just the words L1-A-TURN-1 and nothing else.",
                "Reply with just the words L1-A-TURN-2 and nothing else.",
                "Reply with just the words L1-A-TURN-3 and nothing else.",
            ],
        ),
        sequence(
            transport_b,
            "L1-B",
            [
                "Reply with just the words L1-B-TURN-1 and nothing else.",
                "Reply with just the words L1-B-TURN-2 and nothing else.",
                "Reply with just the words L1-B-TURN-3 and nothing else.",
            ],
        ),
    )

    provider_ids_a = [r["provider-session-id"] for r in results_a]
    provider_ids_b = [r["provider-session-id"] for r in results_b]
    report = {
        "results-a": results_a,
        "results-b": results_b,
        "provider-session-id-distinct": bool(
            provider_ids_a[0] and provider_ids_b[0] and provider_ids_a[0] != provider_ids_b[0]
        ),
        "provider-session-id-stable-a": len(set(provider_ids_a)) == 1 and provider_ids_a[0] is not None,
        "provider-session-id-stable-b": len(set(provider_ids_b)) == 1 and provider_ids_b[0] is not None,
    }
    return {"transport_a": transport_a, "transport_b": transport_b, "report": report}


# ── L2: isolated page loss ──────────────────────────────────────────


async def scenario_isolated_page_loss(
    runtime: GptAutoProviderRuntime,
    transport_a: GptAutoSessionTransport,
    transport_b: GptAutoSessionTransport,
) -> dict[str, Any]:
    print("\n=== L2: close gpt-t1's page directly over CDP; gpt-t2 must be unaffected ===")
    chat_a = transport_a.chat
    chat_b = transport_b.chat

    calls_a: list[str] = []
    calls_b: list[str] = []
    orig_page_lost_a = chat_a.page_lost
    orig_page_lost_b = chat_b.page_lost

    async def wrapped_a(handle: str) -> None:
        calls_a.append(handle)
        await orig_page_lost_a(handle)

    async def wrapped_b(handle: str) -> None:
        calls_b.append(handle)
        await orig_page_lost_b(handle)

    chat_a.page_lost = wrapped_a  # type: ignore[method-assign]
    chat_b.page_lost = wrapped_b  # type: ignore[method-assign]

    page_before_a = chat_a.page_handle
    page_before_b = chat_b.page_handle
    state_before_b = chat_b.state

    await runtime.bridge.call("close_page", {"pageHandle": page_before_a})

    # Give the bridge's event router a bounded window to observe and route
    # the Target.targetDestroyed CDP event to page_lost().
    deadline = time.time() + 10.0
    while time.time() < deadline and not calls_a:
        await asyncio.sleep(0.25)

    result = {
        "page-before-a": page_before_a,
        "page-before-b": page_before_b,
        "page-lost-called-on-a": bool(calls_a),
        "page-lost-called-on-b": bool(calls_b),
        "chat-b-state-unchanged": chat_b.state == state_before_b,
        "chat-b-page-handle-unchanged": chat_b.page_handle == page_before_b,
    }

    # Prove recovery: the next turn on A must succeed via reconcile/ensure_ready
    # without duplicating a prior prompt, and B must still work normally too.
    recovery_turn_a = await _send(transport_a, "L2-A-post-close-recovery", "Reply with just the words L2-A-RECOVERED and nothing else.")
    control_turn_b = await _send(transport_b, "L2-B-control", "Reply with just the words L2-B-UNAFFECTED and nothing else.")
    result["recovery-turn-a"] = recovery_turn_a
    result["control-turn-b"] = control_turn_b
    result["page-after-recovery-a"] = chat_a.page_handle
    result["page-changed-on-recovery-a"] = chat_a.page_handle != page_before_a

    chat_a.page_lost = orig_page_lost_a  # type: ignore[method-assign]
    chat_b.page_lost = orig_page_lost_b  # type: ignore[method-assign]
    return result


# ── L3: global recover() blast radius (direct GP05 probe) ──────────


async def scenario_global_recover(
    runtime: GptAutoProviderRuntime,
    transport_a: GptAutoSessionTransport,
    transport_b: GptAutoSessionTransport,
) -> dict[str, Any]:
    print("\n=== L3: runtime.recover() -- does gpt-t2 pay the cost of a disconnect it didn't cause? ===")
    chat_a = transport_a.chat
    chat_b = transport_b.chat

    reconcile_calls_b: list[float] = []
    orig_reconcile_b = chat_b.reconcile

    async def wrapped_reconcile_b(pages: list[dict[str, Any]]) -> None:
        reconcile_calls_b.append(time.time())
        await orig_reconcile_b(pages)

    chat_b.reconcile = wrapped_reconcile_b  # type: ignore[method-assign]

    page_before_a = chat_a.page_handle
    page_before_b = chat_b.page_handle
    state_before_b = chat_b.state

    started = time.time()
    await runtime.recover()
    elapsed = time.time() - started

    result = {
        "recover-wall-clock-seconds": round(elapsed, 2),
        "chat-b-reconcile-was-called": bool(reconcile_calls_b),
        "chat-b-state-before": str(state_before_b),
        "chat-b-state-after": str(chat_b.state),
        "chat-b-page-handle-before": page_before_b,
        "chat-b-page-handle-after": chat_b.page_handle,
        "chat-a-page-handle-before": page_before_a,
        "chat-a-page-handle-after": chat_a.page_handle,
    }

    # Prove both chats still function after the forced global reconciliation.
    post_recover_a = await _send(transport_a, "L3-A-post-recover", "Reply with just the words L3-A-POST-RECOVER and nothing else.")
    post_recover_b = await _send(transport_b, "L3-B-post-recover", "Reply with just the words L3-B-POST-RECOVER and nothing else.")
    result["post-recover-turn-a"] = post_recover_a
    result["post-recover-turn-b"] = post_recover_b

    chat_b.reconcile = orig_reconcile_b  # type: ignore[method-assign]
    return result


async def _main_async() -> int:
    config = _load_config()
    runtime = GptAutoProviderRuntime(config)
    report: dict[str, Any] = {}
    try:
        await runtime.ensure_available()

        concurrency = await scenario_concurrency(runtime, config)
        report["L1-concurrency"] = concurrency["report"]
        transport_a, transport_b = concurrency["transport_a"], concurrency["transport_b"]

        report["L2-isolated-page-loss"] = await scenario_isolated_page_loss(runtime, transport_a, transport_b)
        report["L3-global-recover"] = await scenario_global_recover(runtime, transport_a, transport_b)

        await transport_a.close()
        await transport_b.close()
    finally:
        await runtime.shutdown()

    print("\n=== Final low-level report ===")
    print(json.dumps(report, indent=2, default=str))
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
