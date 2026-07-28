"""AS40: AG-side receiver for the Pi RPC tap.

Connects the tee shim's per-request tap connection (`rpc_tap_transport`) to
the strict JSONL codec (`rpc_tap`). This is observation-only ingress: it never
writes to the tap connection, never drives the underlying pi-acp session, and
a receiver failure degrades observation evidence only (AS40
cleanup_and_recovery). Mapping decoded frames onto AS19 evidence is AS41's
job, not this module's -- this module stops at "decoded JSON frame or bounded
decode error, in stream order".
"""
from __future__ import annotations

from collections.abc import Iterator

from audiagentic.components.providers.adapters.pi.rpc_tap import (
    JsonlTapDecodeError,
    JsonlTapDecoder,
    JsonlTapFrame,
)
from audiagentic.components.providers.adapters.pi.rpc_tap_shim import (
    TAP_ADDRESS_ENV,
    TAP_AUTHKEY_ENV,
)
from audiagentic.components.providers.adapters.pi.rpc_tap_transport import (
    open_tap_listener,
)


def tap_listener_config(launch_environment: dict[str, str]) -> tuple[str, bytes] | None:
    """Extract the (address, authkey) a launch's environment configured for its tap.

    Returns None when the launch did not enable an RPC tap
    (`build_acp_launch(..., enable_rpc_tap=False)`, the default).
    """
    address = launch_environment.get(TAP_ADDRESS_ENV)
    authkey_hex = launch_environment.get(TAP_AUTHKEY_ENV)
    if not address or not authkey_hex:
        return None
    return address, bytes.fromhex(authkey_hex)


def open_tap_listener_for_launch(launch_environment: dict[str, str]):
    """AG side: open the tap listener matching a launch's tap configuration.

    Must be called -- and the returned listener must be accepting -- before
    the launch is spawned, per AS40 (`runtime_isolation`: "AG creates and
    listens on before launch").
    """
    config = tap_listener_config(launch_environment)
    if config is None:
        raise ValueError("launch_environment has no RPC tap configured")
    address, authkey = config
    return open_tap_listener(address, authkey=authkey)


def iter_tap_frames(listener) -> Iterator[JsonlTapFrame | JsonlTapDecodeError]:
    """Accept the shim's one tap connection and yield decoded frames/errors in order.

    Read-only: never sends anything back on the connection. Ends (stops
    iterating) when the shim closes its end (EOFError) or the connection
    errors -- both are normal end-of-tap conditions, not raised to the caller.
    """
    decoder = JsonlTapDecoder()
    conn = listener.accept()
    try:
        while True:
            try:
                chunk = conn.recv_bytes()
            except EOFError:
                return
            except OSError:
                return
            yield from decoder.feed(chunk)
    finally:
        try:
            conn.close()
        except OSError:
            pass


__all__ = ["iter_tap_frames", "open_tap_listener_for_launch", "tap_listener_config"]
