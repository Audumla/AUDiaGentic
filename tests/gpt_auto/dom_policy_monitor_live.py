"""Manual live monitor for gpt-auto workflow evidence across one Gateway session.

Run from the repository root:

    python tests/gpt_auto/dom_policy_monitor_live.py

The first turn establishes a disposable ChatGPT conversation.  A second CDP
client then observes only configured DOM-signal transitions while two follow-up
review turns run through the public GatewayClient and production Gateway path.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from audiagentic.components.agents.gateway.client import get_gateway_client
from audiagentic.components.providers.adapters.gpt_auto.cdp.bridge import PythonCdpBridge
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.urls import (
    parse_provider_session_id,
    url_matches_provider_session,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "gpt-auto-dom-policy-monitor"


def _submit(
    client, prompt: str, *, session_id: str | None = None, stage: int
) -> dict[str, Any]:
    task = client.submit_execution_request(
        "gpt-auto-reviewer-agent",
        prompt_body=prompt,
        session_id=session_id,
        session_keep_alive=True,
        timeout_seconds=3900,
        source=SOURCE,
        metadata={"plan-item-id": "SH10", "monitor-stage": stage},
    )
    return client.wait_execution_request(ROOT, task["request-id"], 3930)


async def _monitor(
    chat_url: str, stop: threading.Event, ready: threading.Event, result: dict[str, Any]
) -> None:
    provider_document = yaml.safe_load(
        (ROOT / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )
    config = GptAutoConfig.from_project_dict(provider_document)
    bridge = PythonCdpBridge(config)
    transitions: list[dict[str, Any]] = []
    stage_summaries: dict[int, dict[str, Any]] = {}
    try:
        await bridge.start()
        pages = await bridge.call("list_pages")
        provider_session_id = parse_provider_session_id(chat_url)
        page = next(
            (
                item
                for item in pages
                if provider_session_id
                and url_matches_provider_session(
                    str(item.get("url") or ""), provider_session_id
                )
            ),
            None,
        )
        if page is None:
            raise RuntimeError(f"monitor could not find provider page {chat_url}")
        page_handle = str(page["pageHandle"])
        signals = config.workflow.bridge_signals()
        baseline = await bridge.call("snapshot", {"pageHandle": page_handle, "signals": signals})
        baseline_users = int(baseline.get("userCount") or 0)
        previous: tuple[Any, ...] | None = None
        started = time.monotonic()
        ready.set()
        while not stop.is_set():
            snap = await bridge.call("snapshot", {"pageHandle": page_handle, "signals": signals})
            user_count = int(snap.get("userCount") or 0)
            assistant_count = int(snap.get("assistantCount") or 0)
            stage = max(0, user_count - baseline_users)
            present = tuple(sorted(name for name, value in snap.get("domSignals", {}).items() if value))
            text_length = len(str(snap.get("latestAssistantText") or ""))
            state = (
                stage,
                assistant_count,
                present,
                bool(snap.get("composerEditable")),
                text_length // 100,
            )
            summary = stage_summaries.setdefault(
                stage,
                {
                    "samples": 0,
                    "signals-seen": [],
                    "max-text-chars": 0,
                    "composer-editable-values": [],
                },
            )
            summary["samples"] += 1
            summary["signals-seen"] = sorted(set(summary["signals-seen"]) | set(present))
            summary["max-text-chars"] = max(summary["max-text-chars"], text_length)
            summary["composer-editable-values"] = sorted(
                set(summary["composer-editable-values"]) | {bool(snap.get("composerEditable"))}
            )
            if state != previous:
                transitions.append(
                    {
                        "at-seconds": round(time.monotonic() - started, 2),
                        "stage": stage,
                        "users": user_count,
                        "assistants": assistant_count,
                        "signals": list(present),
                        "composer-editable": bool(snap.get("composerEditable")),
                        "text-chars": text_length,
                    }
                )
                previous = state
            await asyncio.sleep(0.25)
        result.update(
            {
                "baseline-users": baseline_users,
                "transitions": transitions,
                "stage-summaries": stage_summaries,
            }
        )
    except Exception as exc:
        result["monitor-error"] = str(exc)
        ready.set()
    finally:
        await bridge.stop()


def _monitor_thread(
    chat_url: str, stop: threading.Event, ready: threading.Event, result: dict[str, Any]
) -> None:
    asyncio.run(_monitor(chat_url, stop, ready, result))


def main() -> int:
    client = get_gateway_client(ROOT)
    session_id: str | None = None
    stop = threading.Event()
    thread: threading.Thread | None = None
    try:
        first = _submit(
            client,
            "Review SH10's reconnect-at-deadline proof. Name two acceptance risks.",
            stage=1,
        )
        session_value = first.get("session-id")
        if session_value:
            session_id = str(session_value)
        if first.get("state") != "completed":
            print(json.dumps({"first": first}, default=str, indent=2))
            return 1
        chat_url = str((first.get("provider-metadata") or {})["chat-url"])
        ready = threading.Event()
        monitor_result: dict[str, Any] = {}
        thread = threading.Thread(
            target=_monitor_thread,
            args=(chat_url, stop, ready, monitor_result),
            daemon=True,
        )
        thread.start()
        if not ready.wait(30) or monitor_result.get("monitor-error"):
            print(json.dumps(monitor_result, indent=2))
            return 1
        results = [first]
        results.append(
            _submit(
                client,
                "Challenge that review with three concrete false-pass modes. Keep it concise.",
                session_id=session_id,
                stage=2,
            )
        )
        if results[-1].get("state") != "completed":
            print(json.dumps({"results": results}, default=str, indent=2))
            return 1
        results.append(
            _submit(
                client,
                "Finalize the review with three proof invariants and one completion blocker.",
                session_id=session_id,
                stage=3,
            )
        )
        stop.set()
        thread.join(35)
        providers = [result.get("provider-metadata") or {} for result in results]
        output = {
            "ok": all(result.get("state") == "completed" for result in results)
            and len({provider.get("provider-session-id") for provider in providers}) == 1
            and "monitor-error" not in monitor_result
            and not thread.is_alive(),
            "request-ids": [result.get("request-id") for result in results],
            "session-id": session_id,
            "same-provider-session": len(
                {provider.get("provider-session-id") for provider in providers}
            )
            == 1,
            **monitor_result,
        }
        print(json.dumps(output, indent=2))
        return 0 if output["ok"] else 1
    finally:
        stop.set()
        if thread is not None and thread.is_alive():
            thread.join(35)
        if session_id is not None:
            get_gateway_client().close_execution_session(ROOT, session_id)


if __name__ == "__main__":
    raise SystemExit(main())
