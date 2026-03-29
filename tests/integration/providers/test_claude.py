from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.adapters import claude


def test_claude_adapter_contract() -> None:
    result = claude.run({"provider-id": "claude"}, {"default-model": "claude-stub"})
    assert result["provider-id"] == "claude"
    assert result["status"] == "ok"
