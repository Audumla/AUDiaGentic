from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.interoperability.providers.adapters import continue_


def test_continue_adapter_contract() -> None:
    result = continue_.run({"provider-id": "continue"}, {"default-model": "continue-stub"})
    assert result["provider-id"] == "continue"
    assert result["status"] == "ok"
