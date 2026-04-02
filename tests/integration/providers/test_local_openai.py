from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.execution.providers.adapters import local_openai


def test_local_openai_adapter_contract() -> None:
    result = local_openai.run({"provider-id": "local-openai"}, {"default-model": "gpt-oss"})
    assert result["provider-id"] == "local-openai"
    assert result["status"] == "ok"


def test_local_openai_adapter_allows_qwen_alias() -> None:
    result = local_openai.run({"provider-id": "qwen"}, {"default-model": "qwen-coder"})
    assert result["provider-id"] == "qwen"
