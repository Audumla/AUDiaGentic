"""Generated local surfaces are not repository or Docker build inputs."""

import json
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GENERATED = (
    "AGENTS.md", "CLAUDE.md", "COPILOT.md", "GEMINI.md", "QWEN.md",
    "SYSTEM.md", ".agents/mcp_config.json", ".qwen/settings.json",
    ".qwen/settings.json.orig", "_gp14_review_output.txt",
    "test_section_parser.py", "package.json", "package-lock.json",
)


def test_generated_root_artifacts_are_not_tracked():
    if not (ROOT / ".git").exists():
        pytest.skip("Git index is not part of the Docker source context")
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "ls-files", "-z", "--",
         *GENERATED, ".audiagentic/runtime"],
        cwd=ROOT, capture_output=True, check=True,
    )
    assert result.stdout == b"", result.stdout.decode()


def test_shared_ignore_policy_covers_generated_surfaces():
    rules = set((ROOT / ".gitignore").read_text().splitlines())
    for path in GENERATED:
        assert "/" + path in rules
    # Only tracked project settings are re-included (docs/guides/PROJECT_SETTINGS.md).
    assert "/.audiagentic/*" in rules
    assert {rule for rule in rules if rule.startswith("!/.audiagentic/")} == {
        "!/.audiagentic/settings.yaml", "!/.audiagentic/agents/", "!/.audiagentic/templates/",
    }
    assert not {"/.agents/", "/.qwen/", "/tmp*/"}.intersection(rules)


def _copy_sources(line):
    instruction, _, arguments = line.strip().partition(" ")
    if instruction.upper() != "COPY":
        return []
    while arguments.startswith("--"):
        option, _, arguments = arguments.partition(" ")
        if option.startswith("--from="):
            return []
        arguments = arguments.lstrip()
    paths = json.loads(arguments) if arguments.startswith("[") else shlex.split(arguments)
    return paths[:-1]


@pytest.mark.parametrize("line", [
    "COPY AGENTS.md ./",
    'COPY ["AGENTS.md", "./"]',
    'COPY --chown=1000:1000 ["AGENTS.md", "./"]',
])
def test_copy_source_check_handles_shell_and_json_forms(line):
    assert _copy_sources(line) == ["AGENTS.md"]


def test_copy_source_check_ignores_build_stage_sources():
    assert _copy_sources('COPY --from=builder ["AGENTS.md", "./"]') == []


def test_docker_recipes_do_not_copy_generated_root_surfaces():
    for recipe in (ROOT / "tests/docker").glob("Dockerfile.*"):
        for line in recipe.read_text(encoding="utf-8").splitlines():
            assert not set(_copy_sources(line)).intersection(GENERATED), recipe


def test_canonical_harness_template_is_retained():
    assert (ROOT / "src/audiagentic/components/providers/adapters/pi/templates/agent/SYSTEM.md").is_file()
    assert (ROOT / "src/audiagentic/components/providers/adapters/opencode/templates/AGENTS.md").is_file()


def test_full_suite_image_contains_tools_used_by_contract_collection():
    recipe = (ROOT / "tests/docker/Dockerfile.test").read_text(encoding="utf-8")
    assert any("tools" in _copy_sources(line) for line in recipe.splitlines())
    context_rules = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {"!tools/", "!tools/**"} <= context_rules
    assert "!.dockerignore" in context_rules
    assert any(".dockerignore" in _copy_sources(line) for line in recipe.splitlines())
    for tool in ("privacy_guard.py", "privacy_binary_allow.json", "extract_mcp.py"):
        assert (ROOT / "tools" / tool).is_file()
