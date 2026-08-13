"""Architecture guard: every ``__all__`` entry resolves at runtime (CC36).

Catches MA11-class regressions where a symbol is removed from a module but a
re-exporting ``__init__.py`` (or its consumers) still lists it — the break
that removed ``WorkflowAnswer`` from ``workflow/invocation/models.py`` while
``invocation/__init__.py`` kept exporting it (commit 4e6198c9).
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil

import pytest

import audiagentic

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("websockets") is None,
    reason="websockets is not installed (install the gpt-auto extra)",
)


def _iter_module_names() -> list[str]:
    names = ["audiagentic"]
    for info in pkgutil.walk_packages(audiagentic.__path__, prefix="audiagentic."):
        names.append(info.name)
    return names


def test_every_all_export_resolves() -> None:
    failures: list[str] = []
    for name in _iter_module_names():
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — report, don't abort the sweep
            failures.append(f"{name}: import failed: {type(exc).__name__}: {exc}")
            continue
        exported = getattr(module, "__all__", None)
        if not exported:
            continue
        for symbol in exported:
            try:
                getattr(module, symbol)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}.{symbol}: {type(exc).__name__}: {exc}")
    assert not failures, "unresolvable __all__ exports:\n" + "\n".join(failures)
