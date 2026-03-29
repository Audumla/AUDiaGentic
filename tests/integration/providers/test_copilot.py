from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.adapters import copilot


def test_copilot_adapter_contract() -> None:
    result = copilot.run({"provider-id": "copilot"}, {"default-model": "copilot-stub"})
    assert result["provider-id"] == "copilot"
    assert result["status"] == "ok"
