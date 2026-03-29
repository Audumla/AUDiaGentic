from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.adapters import cline


def test_cline_adapter_contract() -> None:
    result = cline.run({"provider-id": "cline"}, {"default-model": "cline-stub"})
    assert result["provider-id"] == "cline"
    assert result["status"] == "ok"
