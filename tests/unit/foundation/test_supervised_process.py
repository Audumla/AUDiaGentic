from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from audiagentic.foundation.system.process import pid_alive
from audiagentic.foundation.system.supervised_process import spawn_supervised


def test_spawn_supervised_uses_replacement_environment_and_cwd(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import json, os; "
            "print(json.dumps({'cwd': os.getcwd(), "
            "'allowed': os.environ.get('AG_TEST_ALLOWED'), "
            "'blocked': os.environ.get('AG_TEST_BLOCKED')}))"
        ),
    ]
    with spawn_supervised(
        command,
        cwd=tmp_path,
        env={"AG_TEST_ALLOWED": "present"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as child:
        stdout, stderr = child.communicate(timeout=10)

    assert stderr == ""
    assert json.loads(stdout) == {
        "cwd": str(tmp_path),
        "allowed": "present",
        "blocked": None,
    }


def test_spawn_supervised_close_is_idempotent() -> None:
    child = spawn_supervised([sys.executable, "-c", "import time; time.sleep(60)"])
    child.close()
    child.close()
    assert child.poll() is not None


def test_spawn_supervised_close_reaps_child_and_grandchild() -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import subprocess, sys, time; "
            "grandchild=subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(60)']); "
            "print(grandchild.pid, flush=True); time.sleep(60)"
        ),
    ]
    child = spawn_supervised(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert child.stdout is not None
    grandchild_pid = int(child.stdout.readline().strip())
    child_pid = child.pid
    assert pid_alive(child_pid)
    assert pid_alive(grandchild_pid)

    child.close()

    deadline = time.monotonic() + 5
    while (pid_alive(child_pid) or pid_alive(grandchild_pid)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_alive(child_pid)
    assert not pid_alive(grandchild_pid)
