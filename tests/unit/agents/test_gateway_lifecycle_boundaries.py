"""Architecture regression tests: gateway adapters own no lease, drain,
shutdown-gate, or process-kill policy (SH10 Slice C).

Module names corrected for the post-SH18 module layout -- the fat
``agents_gateway_mcp.py``/``agents_gateway_events.py``/``agents_gateway_lifecycle.py``
this item originally named no longer exist. The real modules are
``mcp/gateway_mcp.py``, ``mcp/admin_mcp.py``, ``gateway/events.py``
(adapters), and ``gateway/service/lifecycle.py`` (the lifecycle authority
itself, checked by the inverse assertion below).
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "audiagentic"

ADAPTER_FILES = [
    "commands/gateway.py",
    "components/agents/mcp/gateway_mcp.py",
    "components/agents/mcp/admin_mcp.py",
    "components/agents/gateway/events.py",
]

# Patterns that reach into lease/drain/shutdown-gate/process-kill internals
# rather than dispatching through the client or lifecycle module's own
# public methods (request_stop/request_drain/request_resume/service_status).
FORBIDDEN = [
    "ManagedServiceStore(",
    "acquire_lease(",
    ".transition(",
    "ManagedServiceShutdown",
    "kill_process_tree",
    "signal_owned_process",
]


def test_adapters_own_no_lease_drain_or_process_policy() -> None:
    violations: list[str] = []
    for name in ADAPTER_FILES:
        path = SRC / name
        text = path.read_text(encoding="utf-8")
        hits = [f for f in FORBIDDEN if f in text]
        if hits:
            violations.append(f"{name}: {hits}")
    assert not violations, (
        "Gateway adapters must dispatch through the client/lifecycle module, "
        "not reach into lease/drain/process-kill internals directly:\n  "
        + "\n  ".join(violations)
    )


def test_gateway_serve_signal_handler_installs_its_own_process_signals_only() -> None:
    """commands/gateway.py's Slice B signal handling installs signal.signal()
    for its own process's graceful shutdown -- that is not the forbidden
    pattern (signalling *another* owned process); confirm the file's own
    signal use stays confined to signal.signal()/getattr(signal, ...), never
    a process-kill helper."""
    text = (SRC / "commands/gateway.py").read_text(encoding="utf-8")
    hits = [f for f in FORBIDDEN if f in text]
    assert not hits, f"commands/gateway.py: {hits}"


def test_lifecycle_module_imports_no_mcp_fastmcp_or_click() -> None:
    """Inverse assertion: the lifecycle authority itself must not depend on
    any protocol adapter framework -- protocol details flow one way, from
    adapter to lifecycle, never the reverse."""
    text = (SRC / "components/agents/gateway/service/lifecycle.py").read_text(encoding="utf-8")
    import_lines = [
        line for line in text.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    hits = [
        line for line in import_lines
        if "mcp" in line.lower() or "fastmcp" in line.lower() or "click" in line.lower()
    ]
    assert not hits, f"lifecycle.py imports a protocol adapter framework: {hits}"
