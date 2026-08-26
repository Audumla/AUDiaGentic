"""AS41: Pi RPC tap enrichment — the concrete PreSpawnHook + AuxiliaryObservationSource

pair that plugs into the generic, provider-blind seams in
``foundation/transports/acp.py``. This is the ONLY module in the whole tap
enrichment path allowed to know "Pi" and "tap" exist as concepts — the
transport and the gateway never do (AS28 boundary; see AS41's plan notes for
the two design corrections that led here).

Frame vocabulary is deliberately closed to what a real Docker transcript
proved this session (``tests/integration/providers/test_pi_rpc_tap_transcript_e2e.py``):
``agent_start``, ``agent_end``, ``message_update``, ``turn_end``. Every other
real, source-documented Pi RPC event type (``tool_execution_*``,
``compaction_*``, ``queue_update``, ...) degrades to ``TRANSPORT_UNKNOWN``
until it has its own transcript proof — mirrors
``_map_acp_event_to_observation``'s own closed-vocabulary discipline.

Tap frames intentionally carry no source sequence. Pi's RPC tap and ACP
stream are independent event namespaces, so inventing a counter here can
collide with native ACP sequence numbers at the common gateway activity sink.
The sink assigns its own aggregate sequence under the request lock; ``None``
therefore means "auxiliary evidence, no comparable native sequence", rather
than a false ordering assertion. Terminal tap frames remain observational:
only the ACP request result can terminalize a gateway turn.
"""
from __future__ import annotations

import queue
import threading
from typing import Any

from audiagentic.components.providers.adapters.pi.rpc_tap import (
    JsonlTapDecodeError,
    JsonlTapFrame,
)
from audiagentic.components.providers.adapters.pi.rpc_tap_receiver import (
    iter_tap_frames,
    open_tap_listener_for_launch,
    tap_listener_config,
)
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import (
    CorrelationQuality,
    TransportObservation,
    TransportObservationKind,
)

# Closed vocabulary: only frame types Docker-proven this session. Anything
# else -> TRANSPORT_UNKNOWN with zero attributes (never leak raw payload).
_PI_FRAME_KIND_TO_TRANSPORT: dict[str, TransportObservationKind] = {
    "agent_start": TransportObservationKind.ACTIVITY,
    "message_update": TransportObservationKind.IN_PROGRESS,
    "turn_end": TransportObservationKind.TERMINAL,
    "agent_end": TransportObservationKind.TERMINAL,
}


def map_pi_rpc_frame_to_observation(
    frame: JsonlTapFrame,
    *,
    ag_session_id: str,
    turn_id: str | None,
    sequence: int | None,
) -> TransportObservation:
    """Map one decoded Pi RPC tap frame to a bounded TransportObservation.

    Never raises (TransportObservation construction itself only fails on a
    genuine contract violation, which a hardcoded empty attributes dict and
    a real ISO timestamp cannot trigger) and never leaks the raw frame
    payload — only the closed-vocabulary kind is derived from it.
    """
    payload = frame.payload if isinstance(frame.payload, dict) else {}
    frame_type = payload.get("type")
    kind = _PI_FRAME_KIND_TO_TRANSPORT.get(str(frame_type), TransportObservationKind.TRANSPORT_UNKNOWN)
    return TransportObservation(
        ag_session_id=ag_session_id,
        turn_id=turn_id,
        sequence=sequence,
        kind=kind,
        observed_at=now_iso_z(),
        correlation_quality=CorrelationQuality.REQUEST_SCOPED,
        attributes={},
    )


class PiRpcTapObservationSource:
    """AuxiliaryObservationSource backed by a background thread.

    ``iter_tap_frames`` does blocking socket I/O (``conn.recv_bytes()``) —
    it cannot run on the asyncio loop `poll()` is called from, so a daemon
    thread drains it into a thread-safe queue; `poll()` only ever does a
    non-blocking ``get_nowait()``, honoring the protocol's "never block"
    contract.
    """

    def __init__(self, listener: Any) -> None:
        self._listener = listener
        self._queue: queue.Queue[JsonlTapFrame] = queue.Queue()
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for item in iter_tap_frames(self._listener):
                if isinstance(item, JsonlTapDecodeError):
                    # Malformed frame isolated to tap ingestion (AS40) —
                    # never surfaced as an observation, never fatal.
                    continue
                self._queue.put(item)
        except Exception:  # noqa: BLE001 — tap failure degrades richness only
            pass

    async def poll(
        self, ag_session_id: str, turn_id: str | None,
    ) -> TransportObservation | None:
        try:
            frame = self._queue.get_nowait()
        except queue.Empty:
            return None
        return map_pi_rpc_frame_to_observation(
            frame, ag_session_id=ag_session_id, turn_id=turn_id, sequence=None,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._listener.close()
        except Exception:  # noqa: BLE001 — best-effort teardown
            pass


class PiRpcTapPreSpawnHook:
    """Concrete PreSpawnHook for Pi's RPC tap (AS41).

    Safe to attach unconditionally to any Pi ACP launch: if the launch did
    not enable the tap (``build_acp_launch(enable_rpc_tap=False)``, the
    default), ``on_environment_ready`` finds no tap configuration and
    returns ``None`` — a plain no-op, same as never attaching a hook.
    """

    def on_environment_ready(self, environment: Any) -> PiRpcTapObservationSource | None:
        env = dict(environment)
        if tap_listener_config(env) is None:
            return None
        listener = open_tap_listener_for_launch(env)
        return PiRpcTapObservationSource(listener)

    def on_close(self, hook_state: Any | None) -> None:
        if hook_state is not None:
            hook_state.close()


__all__ = [
    "PiRpcTapObservationSource",
    "PiRpcTapPreSpawnHook",
    "map_pi_rpc_frame_to_observation",
]
