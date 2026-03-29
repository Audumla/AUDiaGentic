from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.adapters import codex


def test_codex_adapter_contract() -> None:
    result = codex.run({"provider-id": "codex"}, {"default-model": "codex-stub"})
    assert result["provider-id"] == "codex"
    assert result["status"] == "ok"
