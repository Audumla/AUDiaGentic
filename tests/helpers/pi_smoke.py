"""Native Pi launch policy for bounded real-model Docker smoke tests."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path


def restrict_smoke_pi(project_root: Path, monkeypatch, *, tools: str | None = None) -> None:
    """Wrap the real CLI, not the protocol/model, with explicit smoke policy.

    A coding agent's default system prompt and unrestricted tools are not an
    echo test: small CPU models may keep editing files indefinitely. Tool-tap
    tests expose bash only; text tests expose no tools. Neither may discover
    unrelated extensions/context from the image or generate hidden reasoning.
    """
    real_pi = shutil.which("pi")
    assert real_pi is not None
    args = [
        real_pi,
        "--thinking",
        "off",
        "--no-extensions",
        "--no-context-files",
        "--no-skills",
        "--no-prompt-templates",
    ]
    args += ["--tools", tools] if tools else ["--no-tools"]
    args += [
        "--system-prompt",
        "Follow the user's instruction exactly. After answering or performing the requested single tool call, end the turn. Do not perform additional work.",
    ]
    wrapper_root = project_root / "smoke-bin"
    wrapper_root.mkdir()
    wrapper = wrapper_root / "pi"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.join(args) + ' "$@"\n', encoding="utf-8")
    wrapper.chmod(0o700)
    monkeypatch.setenv("PATH", str(wrapper_root) + os.pathsep + os.environ.get("PATH", ""))
