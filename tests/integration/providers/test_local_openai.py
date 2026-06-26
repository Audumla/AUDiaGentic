from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.components.providers.adapters.local_openai import adapter as local_openai

_FAKE_RESPONSE = json.dumps({
    "choices": [{
        "message": {"role": "assistant", "content": "done"},
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
})


def _fake_urlopen(*args, **kwargs):
    class _Resp:
        def read(self, *a, **k):
            return _FAKE_RESPONSE.encode()
    return _Resp()


@patch("audiagentic.components.providers.adapters.local_openai.adapter.urllib.request.urlopen", _fake_urlopen)
def test_local_openai_adapter_contract() -> None:
    result = local_openai.run({"provider-id": "local-openai"}, {"default-model": "gpt-oss"})
    assert result["provider-id"] == "local-openai"
    assert result["status"] == "ok"


@patch("audiagentic.components.providers.adapters.local_openai.adapter.urllib.request.urlopen", _fake_urlopen)
def test_local_openai_adapter_allows_qwen_alias() -> None:
    result = local_openai.run({"provider-id": "qwen"}, {"default-model": "qwen-coder"})
    assert result["provider-id"] == "qwen"
