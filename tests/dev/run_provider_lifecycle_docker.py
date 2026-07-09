from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = ROOT / "tests" / "docker" / "provider-lifecycle.env"

PASSTHROUGH_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "DASHSCOPE_API_KEY",
    "GH_TOKEN",
    "AUDIAGENTIC_TEST_PROVIDER_PROMPT",
    "AUDIAGENTIC_TEST_PROVIDER_EXPECTED",
    "AUDIAGENTIC_TEST_PI_MODEL",
    "AUDIAGENTIC_TEST_PI_PROVIDER",
    "AUDIAGENTIC_TEST_CLAUDE_MODEL",
    "AUDIAGENTIC_TEST_CLINE_AUTH",
    "AUDIAGENTIC_TEST_CLINE_MODEL",
    "AUDIAGENTIC_TEST_CODEX_MODEL",
    "AUDIAGENTIC_TEST_COPILOT_MODEL",
    "AUDIAGENTIC_TEST_GEMINI_MODEL",
    "AUDIAGENTIC_TEST_LOCAL_OPENAI_MODEL",
    "AUDIAGENTIC_TEST_LOCAL_OPENAI_BASE_URL",
    "AUDIAGENTIC_TEST_OPENCODE_MODEL",
    "AUDIAGENTIC_TEST_QWEN_MODEL",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run provider lifecycle docker image with optional env-file support."
    )
    parser.add_argument(
        "--image",
        default="audiagentic-provider-lifecycle-e2e:latest",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Optional docker --env-file path. Default: tests/docker/provider-lifecycle.env",
    )
    args = parser.parse_args()

    command = ["docker", "run", "--rm"]

    env_file = Path(args.env_file)
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    else:
        print(f"Env file not found, continuing without it: {env_file}")

    for name in PASSTHROUGH_ENV:
        if name in os.environ:
            command.extend(["-e", name])

    command.append(args.image)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
