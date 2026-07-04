"""AR11: LSP provider projection dispatches through the action registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.services import lsp_projection
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_unknown_action_raises_val_lspprj_001(tmp_path: Path):
    with pytest.raises(AudiaGenticError, match="VAL-LSPPRJ-001"):
        lsp_projection.handle_lsp_provider_projection(
            "coding-lsp.provider-projection",
            {"project_root": tmp_path, "action": "no-such-action"},
            {},
        )


def test_registered_action_dispatches_and_fills_result_slot(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(
        lsp_projection._ACTION_HANDLERS, "test-action", lambda payload: {"ok": True, "seen": True}
    )
    result_slot: dict = {}
    lsp_projection.handle_lsp_provider_projection(
        "coding-lsp.provider-projection",
        {"project_root": tmp_path, "action": "test-action", "result": result_slot},
        {},
    )
    assert result_slot == {"ok": True, "seen": True}
