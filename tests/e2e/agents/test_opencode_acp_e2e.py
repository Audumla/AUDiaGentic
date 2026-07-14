from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.opencode.acp import build_acp_launch
from audiagentic.foundation.execution import run_acp_prompt


@pytest.mark.opt_in
@pytest.mark.requires_network
@pytest.mark.slow
@pytest.mark.timeout(180)
def test_opencode_acp_deep_coder_round_trip() -> None:
    if os.environ.get("AUDIAGENTIC_RUN_OPENCODE_ACP_E2E") != "1":
        pytest.skip("set AUDIAGENTIC_RUN_OPENCODE_ACP_E2E=1")
    if shutil.which("opencode") is None:
        pytest.skip("opencode is not installed")

    root = Path.cwd()
    result = asyncio.run(
        run_acp_prompt(
            build_acp_launch(root, model_id="brutus/deep-coder"),
            cwd=root,
            prompt="Reply with exactly ACP_DEEP_CODER_OK and nothing else.",
        )
    )
    text = "".join(
        str(event.payload.get("content", {}).get("text", ""))
        for event in result.events
        if event.kind == "agent_message_chunk"
    )
    assert text == "ACP_DEEP_CODER_OK"
    assert result.events
