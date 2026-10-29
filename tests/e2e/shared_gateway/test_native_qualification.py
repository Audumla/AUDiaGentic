"""Explicitly paid/native installed qualification; no default native execution."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.opt_in
@pytest.mark.requires_network
@pytest.mark.slow
def test_installed_shared_native():
    if os.environ.get("AUDIAGENTIC_RUN_SHARED_NATIVE_E2E") != "1":
        pytest.skip("set AUDIAGENTIC_RUN_SHARED_NATIVE_E2E=1 and AUDIAGENTIC_SHARED_NATIVE_ARGS")
    arguments = json.loads(os.environ["AUDIAGENTIC_SHARED_NATIVE_ARGS"])
    assert isinstance(arguments, list) and all(isinstance(value, str) for value in arguments)
    # No outer timeout: the driver owns bounded waits and process-tree cleanup.
    subprocess.run(
        [sys.executable, "-I", str(Path(__file__).with_name("qualify_native.py")), *arguments],
        check=True,
    )
