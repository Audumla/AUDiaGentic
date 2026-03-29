from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.adapters import gemini


def test_gemini_adapter_contract() -> None:
    result = gemini.run({"provider-id": "gemini"}, {"default-model": "gemini-stub"})
    assert result["provider-id"] == "gemini"
    assert result["status"] == "ok"
