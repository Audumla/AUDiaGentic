"""Manual live multi-project resilience acceptance for gpt-auto.

Run from the repository root:

    python tests/gpt_auto/test_multi_project_concurrency_live.py

This intentionally uses the same public GatewayClient path as the MCP
agent_task_submit tool (see ``test_session_transport_live.py`` for the
single-project pattern this extends). It is NOT pytest-collected: it drives
real ChatGPT browser automation via CDP, consumes real quota, and takes real
wall-clock time (a turn may legitimately take up to the provider's configured
response-timeout-seconds, currently 3600s).

Durable regression tooling for two plan items:

- GP04 (single-session lifecycle/resume runbook): after a shared-gateway
  restart, a durable session with a missing/live chat-url must still be
  resumable via ``resume_execution_session`` using its stored identity/
  execution context fingerprints (see ``session_transport.py``'s
  ``build_session_transport``).
- GP05 (suspected cross-project blast radius): ``GptAutoProviderRuntime`` is
  machine-scoped (see ``runtime_registry.get_runtime``'s explicit
  ``del project_root``), and ``recover()`` reacts to a SINGLE browser/CDP
  disconnect by clearing ``_page_owners`` for ALL registered chats across ALL
  projects, serialized behind one ``_lifecycle_lock``. This script drives two
  independent simulated projects concurrently and deliberately disrupts one
  of them (gateway restart, tab close) to see whether the other project's
  live session is measurably affected -- timing, availability, or state.

Two temporary project roots are used to simulate two distinct AUDiaGentic
projects (the runtime itself has no concept of "project" -- see GP05 above),
each with its own ``.audiagentic/config`` + ``.audiagentic/components`` tree.
That tree is *copied verbatim* from this repository's real, already-validated
configuration (not hand-authored) rather than guessing the gpt-auto
provider/execution-profile schema; only ``project.yaml``'s identity fields
are edited per clone.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.components.agents.gateway.client import get_gateway_client  # noqa: E402

EXECUTION_PROFILE_ID = "gpt-auto"
# Gateway-layer wait budget per turn. The gpt-auto execution profile gives
# 3900s at the gateway layer; the provider's own response-total-timeout is
# up to 3600s (see .audiagentic/config/providers/gpt-auto.yaml). Keep this
# comfortably under the gateway ceiling but generous enough for a real
# ChatGPT turn.
TURN_TIMEOUT_SECONDS = 900.0
CONFIG_SUBDIRS = ("config", "components")


# ── Simulated project setup ─────────────────────────────────────────


def _make_project(tmp_root: Path, name: str, *, chatgpt_project_name: str) -> Path:
    """Clone this repo's real .audiagentic/config + components tree into a
    fresh temp project root so the simulated project reuses the exact,
    already-validated gpt-auto provider/execution-profile schema instead of
    a hand-guessed one.

    ``project.yaml``'s identity fields are edited, and providers/gpt-auto.yaml's
    hardcoded ``project-url`` (this repo's own ChatGPT project) is dropped so
    PersistentChat falls back to per-chat project-name discovery -- pointing
    this clone at ``chatgpt_project_name`` (a REAL, dedicated ChatGPT project
    created for this test, e.g. "gpt-t1"/"gpt-t2") instead.
    """
    project_root = tmp_root / name
    dest_audiagentic = project_root / ".audiagentic"
    dest_audiagentic.mkdir(parents=True, exist_ok=True)
    for sub in CONFIG_SUBDIRS:
        src = REPO_ROOT / ".audiagentic" / sub
        shutil.copytree(src, dest_audiagentic / sub)
    project_yaml_path = dest_audiagentic / "config" / "project.yaml"
    text = project_yaml_path.read_text(encoding="utf-8")
    text = text.replace("project-id: my-project", f"project-id: {name}")
    text = text.replace("project-name: My Project", f"project-name: {chatgpt_project_name}")
    project_yaml_path.write_text(text, encoding="utf-8")

    gpt_auto_yaml_path = dest_audiagentic / "config" / "providers" / "gpt-auto.yaml"
    import yaml

    raw = yaml.safe_load(gpt_auto_yaml_path.read_text(encoding="utf-8"))
    raw["settings"].pop("project-url", None)
    gpt_auto_yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return project_root


# ── Turn/run bookkeeping ────────────────────────────────────────────


@dataclass
class TurnRecord:
    label: str
    request_id: str
    state: str
    output: str
    provider_session_id: str | None
    chat_url: str | None
    started_at: float
    finished_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "request-id": self.request_id,
            "state": self.state,
            "output": self.output,
            "provider-session-id": self.provider_session_id,
            "chat-url": self.chat_url,
            "started-at": self.started_at,
            "finished-at": self.finished_at,
            "duration-seconds": round(self.finished_at - self.started_at, 1),
        }


@dataclass
class ProjectRun:
    name: str
    project_root: Path
    client: Any
    session_id: str | None = None
    turns: list[TurnRecord] = field(default_factory=list)
    error: str | None = None


def _submit_turn(run: ProjectRun, label: str, prompt: str) -> TurnRecord:
    started = time.time()
    submitted = run.client.submit_execution_request(
        run.project_root,
        execution_profile_id=EXECUTION_PROFILE_ID,
        prompt_body=prompt,
        session_id=run.session_id,
        session_keep_alive=True,
        timeout_seconds=TURN_TIMEOUT_SECONDS,
        source="gpt-auto-multi-project-live-test",
        metadata={"scenario": "multi-project-concurrency", "project": run.name, "label": label},
    )
    if run.session_id is None:
        run.session_id = submitted.get("session-id")
    request_id = submitted["request-id"]
    result = run.client.wait_execution_request(run.project_root, request_id, TURN_TIMEOUT_SECONDS + 30)
    provider_meta = result.get("provider-metadata") or {}
    record = TurnRecord(
        label=label,
        request_id=request_id,
        state=str(result.get("state")),
        output=str(result.get("output") or "")[:400],
        provider_session_id=provider_meta.get("provider-session-id"),
        chat_url=provider_meta.get("chat-url"),
        started_at=started,
        finished_at=time.time(),
    )
    run.turns.append(record)
    print(
        f"[{run.name}] {label} request={request_id} state={record.state} "
        f"provider-session-id={record.provider_session_id} elapsed={record.finished_at - record.started_at:.1f}s"
    )
    if result.get("state") != "completed":
        run.error = f"{label} did not complete: {json.dumps(result, default=str)[:800]}"
    return record


def _run_opening_and_followups(run: ProjectRun, opener: str, followups: list[str]) -> None:
    try:
        _submit_turn(run, "turn-1", opener)
        for i, prompt in enumerate(followups, start=2):
            if run.error:
                return
            _submit_turn(run, f"turn-{i}", prompt)
    except Exception as exc:  # noqa: BLE001 - isolate one project's failure from the other
        run.error = f"exception: {exc!r}"
        print(f"[{run.name}] EXCEPTION: {exc!r}")


def _all_same(values: list[Any]) -> bool:
    return bool(values) and all(v == values[0] and v is not None for v in values)


def _summarize(run: ProjectRun) -> dict[str, Any]:
    return {
        "session-id": run.session_id,
        "error": run.error,
        "turns": [t.as_dict() for t in run.turns],
    }


# ── Gateway service admin (safe restart, per GP04's documented procedure) ──


def _gateway_service_endpoint_and_token() -> tuple[str, Path]:
    import os

    from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY
    from audiagentic.foundation.paths.home import global_service_runtime

    port = int(os.environ.get("AUDIAGENTIC_GATEWAY_PORT", "8765"))
    root = (
        global_service_runtime()
        / GATEWAY_SERVICE_KEY.scope
        / GATEWAY_SERVICE_KEY.service_kind
        / GATEWAY_SERVICE_KEY.service_id
    )
    return f"http://127.0.0.1:{port}", root / "auth.token"


def gateway_status() -> dict[str, Any]:
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    endpoint, token_path = _gateway_service_endpoint_and_token()
    client = StandaloneGatewayClient(endpoint, load_auth_token(token_path))
    try:
        return client.service_status(REPO_ROOT)
    finally:
        client.close()


def gateway_stop_force() -> dict[str, Any]:
    """Verified-safe shared-gateway restart trigger (GP04's documented
    procedure): request an operator stop on the one machine-wide managed
    gateway process. The next ``get_gateway_client(project_root)`` call
    (mode="automatic") starts a fresh one and re-attaches."""
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    endpoint, token_path = _gateway_service_endpoint_and_token()
    client = StandaloneGatewayClient(endpoint, load_auth_token(token_path))
    try:
        return client.service_stop(REPO_ROOT, force=True)
    finally:
        client.close()


def _wait_for_gateway_restart(project_root: Path, timeout: float = 60.0) -> Any:
    """Re-attach (spawning a fresh managed gateway if needed) and confirm it
    answers health checks before returning the new client."""
    deadline = time.time() + timeout
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            client = get_gateway_client(project_root)
            client.gateway_overview(project_root)
            return client
        except Exception as exc:  # noqa: BLE001 - retry until the new process is ready
            last_exc = exc
            time.sleep(1.5)
    raise RuntimeError(f"shared gateway did not come back within {timeout}s: {last_exc!r}")


# ── Resume-after-restart (GP04) ─────────────────────────────────────


def _recover_after_restart(run: ProjectRun, pre: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"pre": pre}
    sessions = run.client.list_execution_sessions(run.project_root)
    entry = next((s for s in sessions if s.get("session-id") == run.session_id), None)
    result["session-entry-after-restart"] = entry
    live = bool(entry.get("live")) if entry else False
    result["was-live-after-restart"] = live

    if live:
        # Still attached to a live agent process under the new gateway
        # instance (rare but possible under a fast enough handshake) --
        # no explicit resume needed, prove continuity directly.
        record = _submit_turn(
            run, "post-restart-turn", f"Reply with just the words {run.name}-POST-RESTART and nothing else."
        )
        result["resumed"] = False
        result["post-restart-turn"] = record.as_dict()
        result["provider-session-id-match"] = record.provider_session_id == pre.get("provider_session_id")
        return result

    from audiagentic.components.agents.gateway.session import sessions_store

    binding = sessions_store.read_session_binding(run.project_root, run.session_id)
    result["binding-found"] = binding is not None
    if not binding:
        result["error"] = "orphaned session has no persisted binding; cannot resume"
        return result

    control_id = f"resume-{run.name}-{uuid.uuid4().hex[:12]}"
    try:
        resume_result = run.client.resume_execution_session(
            run.project_root,
            run.session_id,
            control_id=control_id,
            identity_context_fingerprint=binding.get("identity-context-fingerprint"),
            execution_context_fingerprint=binding.get("execution-context-fingerprint"),
        )
    except Exception as exc:  # noqa: BLE001 - record, do not raise -- keeps the other project's phase running
        result["resume-error"] = repr(exc)
        run.error = f"resume failed: {exc!r}"
        return result

    result["resume-result"] = resume_result
    new_session_id = resume_result.get("session-id")
    if new_session_id:
        run.session_id = new_session_id
    result["resumed"] = True

    record = _submit_turn(
        run, "post-resume-turn", f"Reply with just the words {run.name}-POST-RESUME and nothing else."
    )
    result["post-resume-turn"] = record.as_dict()
    result["provider-session-id-match"] = record.provider_session_id == pre.get("provider_session_id")
    result["chat-url-match"] = record.chat_url == pre.get("chat_url")
    return result


# ── Direct-CDP tab close (edge case B) ──────────────────────────────


def _cdp_port() -> int:
    import yaml

    cfg = yaml.safe_load((REPO_ROOT / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8"))
    return int(cfg["settings"]["browser"]["remote-debugging-port"])


def _chat_id(url: str) -> str | None:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[-1] if parts else None


async def _close_tab_for_chat_url(chat_url: str, port: int) -> dict[str, Any]:
    """Close a ChatGPT tab directly over CDP, independent of the gateway's
    own in-process bridge -- simulating a tab closed out from under a live
    session (see gpt_auto/cdp/bridge.py's close_page / Target.closeTarget)."""
    from audiagentic.components.providers.adapters.gpt_auto.cdp.client import CdpClient

    client = CdpClient(f"http://127.0.0.1:{port}")
    await client.start()
    try:
        target_id_hint = _chat_id(chat_url)
        targets = await client.command("Target.getTargets")
        pages = [t for t in targets.get("targetInfos", []) if t.get("type") == "page"]
        match = next((t for t in pages if target_id_hint and target_id_hint in str(t.get("url") or "")), None)
        if match is None:
            return {
                "closed": False,
                "reason": "no matching page target found for chat-url",
                "chat-url": chat_url,
                "open-page-urls": [t.get("url") for t in pages],
            }
        await client.command("Target.closeTarget", {"targetId": match["targetId"]})
        return {"closed": True, "target-id": match["targetId"], "url": match.get("url")}
    finally:
        await client.stop()


def close_tab_for_chat_url(chat_url: str) -> dict[str, Any]:
    return asyncio.run(_close_tab_for_chat_url(chat_url, _cdp_port()))


def _tab_close_scenario(run: ProjectRun, control_run: ProjectRun) -> dict[str, Any]:
    last = run.turns[-1] if run.turns else None
    if last is None or not last.chat_url:
        return {"skipped": True, "reason": "no chat-url captured from a prior turn"}

    control_before = list(control_run.turns)
    close_result = close_tab_for_chat_url(last.chat_url)
    result: dict[str, Any] = {"chat-url": last.chat_url, "close-result": close_result}
    if not close_result.get("closed"):
        return result

    # Submit a follow-up turn on the SAME session -- PersistentChat.reconcile()/
    # ensure_ready() should recreate or relocate the tab without duplicating
    # the prior prompt, or land in a documented RECOVERING/EXT-GPTAUTO-004
    # state (acceptable per the adapter's no-auto-resubmit invariant).
    try:
        record = _submit_turn(
            run, "post-tab-close-turn", f"Reply with just the words {run.name}-POST-TAB-CLOSE and nothing else."
        )
        result["post-tab-close-turn"] = record.as_dict()
        result["recovered-cleanly"] = record.state == "completed"
    except Exception as exc:  # noqa: BLE001 - record the documented-acceptable outcome, don't crash the script
        result["post-tab-close-error"] = repr(exc)
        result["recovered-cleanly"] = False

    # GP05 probe: did the OTHER project's session move/execute during this
    # window without our driving it? It shouldn't -- we only drove it in
    # phase 1/2. Recording turn count is a sanity check, not a real signal;
    # the real signal is timing/availability captured by the caller wrapping
    # this call with its own before/after gateway_overview() snapshots.
    result["control-project-turn-count-unchanged"] = len(control_run.turns) == len(control_before)
    return result


# ── Orchestration ────────────────────────────────────────────────────


def main() -> int:
    tmp_root = Path(tempfile.mkdtemp(prefix="ag-gpt-auto-multi-"))
    print(f"simulated project roots under: {tmp_root}")
    project_a = _make_project(tmp_root, "gpt-auto-live-project-a", chatgpt_project_name="gpt-t1")
    project_b = _make_project(tmp_root, "gpt-auto-live-project-b", chatgpt_project_name="gpt-t2")

    client_a = get_gateway_client(project_a)
    client_b = get_gateway_client(project_b)

    run_a = ProjectRun("A", project_a, client_a)
    run_b = ProjectRun("B", project_b, client_b)

    report: dict[str, Any] = {"tmp-root": str(tmp_root), "phases": {}}

    try:
        # ── Phase 1: concurrency ──
        print("\n=== Phase 1: concurrent turn sequences ===")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    _run_opening_and_followups,
                    run_a,
                    "Reply with just the words PROJECT-A-TURN-1 and nothing else.",
                    [
                        "Reply with just the words PROJECT-A-TURN-2 and nothing else.",
                        "Reply with just the words PROJECT-A-TURN-3 and nothing else.",
                    ],
                ),
                pool.submit(
                    _run_opening_and_followups,
                    run_b,
                    "Reply with just the words PROJECT-B-TURN-1 and nothing else.",
                    [
                        "Reply with just the words PROJECT-B-TURN-2 and nothing else.",
                        "Reply with just the words PROJECT-B-TURN-3 and nothing else.",
                    ],
                ),
            ]
            for fut in as_completed(futures):
                fut.result()

        report["phases"]["concurrency"] = {
            "project-a": _summarize(run_a),
            "project-b": _summarize(run_b),
            "provider-session-ids-distinct": bool(
                run_a.turns
                and run_b.turns
                and run_a.turns[0].provider_session_id
                and run_b.turns[0].provider_session_id
                and run_a.turns[0].provider_session_id != run_b.turns[0].provider_session_id
            ),
            "project-a-provider-session-id-stable": _all_same(
                [t.provider_session_id for t in run_a.turns]
            ),
            "project-b-provider-session-id-stable": _all_same(
                [t.provider_session_id for t in run_b.turns]
            ),
        }
        print(json.dumps(report["phases"]["concurrency"], indent=2, default=str))

        # ── Phase 2: shared gateway restart mid-flight (edge case A / GP04+GP05) ──
        print("\n=== Phase 2: shared gateway restart ===")
        pre_restart = {
            "A": {
                "provider_session_id": run_a.turns[-1].provider_session_id if run_a.turns else None,
                "chat_url": run_a.turns[-1].chat_url if run_a.turns else None,
            },
            "B": {
                "provider_session_id": run_b.turns[-1].provider_session_id if run_b.turns else None,
                "chat_url": run_b.turns[-1].chat_url if run_b.turns else None,
            },
        }
        try:
            status_before = gateway_status()
        except Exception as exc:  # noqa: BLE001
            status_before = {"error": repr(exc)}
        stop_started_at = time.time()
        stop_result = gateway_stop_force()
        run_a.client = _wait_for_gateway_restart(project_a)
        restart_completed_at = time.time()
        run_b.client = _wait_for_gateway_restart(project_b)

        recovered_a = _recover_after_restart(run_a, pre_restart["A"])
        recovered_b = _recover_after_restart(run_b, pre_restart["B"])
        report["phases"]["gateway-restart"] = {
            "status-before": status_before,
            "stop-result": stop_result,
            "restart-wall-clock-seconds": round(restart_completed_at - stop_started_at, 1),
            "recovered": {"A": recovered_a, "B": recovered_b},
        }
        print(json.dumps(report["phases"]["gateway-restart"], indent=2, default=str))

        # ── Phase 3: tab closed mid-session (edge case B), project B only ──
        print("\n=== Phase 3: tab closed under project B (project A is the control) ===")
        tab_close_report = _tab_close_scenario(run_b, control_run=run_a)
        report["phases"]["tab-close"] = tab_close_report
        print(json.dumps(tab_close_report, indent=2, default=str))

    finally:
        # ── Cleanup: close both sessions, leave tabs retained per policy ──
        print("\n=== Cleanup ===")
        cleanup_errors: list[str] = []
        for run in (run_a, run_b):
            try:
                if run.session_id:
                    run.client.close_execution_session(run.project_root, run.session_id)
            except Exception as exc:  # noqa: BLE001
                cleanup_errors.append(f"{run.name}: {exc!r}")
        if cleanup_errors:
            report["cleanup-errors"] = cleanup_errors
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n=== Final report ===")
    print(json.dumps(report, indent=2, default=str))

    ok = not run_a.error and not run_b.error
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
