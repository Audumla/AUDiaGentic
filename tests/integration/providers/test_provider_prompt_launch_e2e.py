"""Docker-gated provider prompt launch validation for executable providers.

The provider registry and descriptor tests cover catalogue-only providers.
This suite is reserved for providers with an executable launch contract, so
catalogue stubs and intentionally unsupported adapters do not become fake
skipped tests.

Cloud/API-backed providers are env-gated so the Docker recipe can opt into the
providers/models it has credentials for without making the suite flaky.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from audiagentic.components.providers.descriptors.registry import all_descriptors
from audiagentic.components.providers.services.execution.execution import execute_provider
from audiagentic.components.providers.services.lifecycle.lifecycle import (
    install_provider_cli,
    uninstall_provider_cli,
)
from audiagentic.foundation.paths.home import global_harness_runtime
from audiagentic.runtime.harness import (
    RunnerParams,
    build_global_context,
    refresh_materialized_agent_config,
    run_agent,
)
from audiagentic.runtime.harness.provisioning import provision_embedded_rig

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="provider prompt launch e2e runs in Docker",
    ),
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
        reason="provider prompt launch e2e requires real provider CLI install",
    ),
]

_DEFAULT_PROMPT = "Reply with exactly: OK"
_DEFAULT_EXPECTED = "OK"
_COPILOT_PROMPT = "Print OK to stdout in POSIX shell"


def _require_env(*names: str) -> None:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip("missing env: " + ", ".join(missing))


def _packet_ctx(project_root: Path, provider_id: str, prompt: str) -> dict[str, object]:
    return {
        "provider-id": provider_id,
        "packet-id": f"smoke-{provider_id}",
        "job-id": f"job-{provider_id}",
        "prompt-id": f"prompt-{provider_id}",
        "project-id": "AUDiaGentic",
        "workflow-profile": "smoke",
        "surface": "cli",
        "working-root": str(project_root),
        "prompt-body": prompt,
        "stream-controls": {},
    }


def _assert_contains(result: dict[str, object], provider_id: str, expected: str) -> None:
    output = str(result.get("output") or "")
    assert expected in output, (
        f"{provider_id} output missing expected text {expected!r}: {output!r}"
    )


def _assert_non_empty(result: dict[str, object], provider_id: str) -> None:
    output = str(result.get("output") or "")
    assert output.strip(), f"{provider_id} output was empty"


def _execute_provider(
    *,
    project_root: Path,
    provider_id: str,
    model: str,
    prompt: str,
    provider_cfg: dict[str, object] | None = None,
) -> dict[str, object]:
    descriptor = all_descriptors()[provider_id]
    cfg = {
        "enabled": True,
        "access-mode": descriptor.access_mode,
        "default-model": model,
    }
    if provider_cfg:
        cfg.update(provider_cfg)
    return execute_provider(
        provider_id=provider_id,
        packet_ctx=_packet_ctx(project_root, provider_id, prompt),
        provider_cfg=cfg,
    )


def _with_installed_cli(
    provider_id: str,
    project_root: Path,
    run_fn: Callable[[], None],
) -> None:
    descriptor = all_descriptors()[provider_id]
    if descriptor.cli_install is None:
        run_fn()
        return
    install_result = install_provider_cli(
        provider_id,
        timeout=600,
        project_root=project_root,
    )
    assert install_result.get("status") == "installed", install_result
    try:
        run_fn()
    finally:
        uninstall_provider_cli(
            provider_id,
            timeout=600,
            project_root=project_root,
        )


def _env_model(provider_id: str) -> str:
    env_name = f"AUDIAGENTIC_TEST_{provider_id.upper().replace('-', '_')}_MODEL"
    _require_env(env_name)
    return os.environ[env_name]


def _success_case(
    provider_id: str,
    *,
    project_root: Path,
    prompt: str = _DEFAULT_PROMPT,
    expected: str = _DEFAULT_EXPECTED,
    provider_cfg: dict[str, object] | None = None,
    required_env: tuple[str, ...] = (),
    assert_fn: Callable[[dict[str, object], str], None] | None = None,
) -> None:
    _require_env(*required_env)
    def _run() -> None:
        result = _execute_provider(
            project_root=project_root,
            provider_id=provider_id,
            model=_env_model(provider_id),
            prompt=prompt,
            provider_cfg=provider_cfg,
        )
        assert int(result.get("returncode", 0)) == 0, result
        if assert_fn is not None:
            assert_fn(result, provider_id)
        else:
            _assert_contains(result, provider_id, expected)

    _with_installed_cli(provider_id, project_root, _run)


def _pi_case(project_root: Path) -> None:
    def _run() -> None:
        model = os.environ.get("AUDIAGENTIC_TEST_PI_MODEL", "qwen3.5-0.8b")
        os.environ["AUDIAGENTIC_AG_MODEL"] = model
        os.environ["AUDIAGENTIC_RIG_MODEL_PROFILE"] = model
        os.environ["AUDIAGENTIC_AG_PROVIDER"] = os.environ.get(
            "AUDIAGENTIC_TEST_PI_PROVIDER",
            "audiagentic",
        )
        harness_runtime = global_harness_runtime()
        provision_embedded_rig(harness_runtime, project_root)
        refresh_materialized_agent_config(harness_runtime, project_root=project_root)
        rig_bin_dir = harness_runtime / "rig" / "bin"
        assert rig_bin_dir.is_dir(), f"AG rig bin directory was not provisioned: {rig_bin_dir}"
        ctx = build_global_context(
            project_root=project_root,
            agent_runtime=harness_runtime,
            enable_mcp=False,
        )
        exit_code = run_agent(ctx, RunnerParams(prompt=_DEFAULT_PROMPT, mode="text"), smoke=False)
        assert exit_code == 0, f"pi harness exited with {exit_code}"

    _with_installed_cli("pi", project_root, _run)


def _assert_opencode(result: dict[str, object], provider_id: str) -> None:
    _assert_contains(result, provider_id, _DEFAULT_EXPECTED)
    assert result.get("session-id"), f"{provider_id} missing session-id: {result}"


def _opencode_case(project_root: Path) -> None:
    _success_case(
        "opencode",
        project_root=project_root,
        provider_cfg={"execution-policy": {"output-format": "json"}},
        required_env=("OPENAI_API_KEY",),
        assert_fn=_assert_opencode,
    )


def _claude_case(project_root: Path) -> None:
    _success_case(
        "claude",
        project_root=project_root,
        provider_cfg={
            "execution-policy": {
                "output-format": "text",
                "permission-mode": "acceptEdits",
            }
        },
        required_env=("ANTHROPIC_API_KEY",),
    )


def _codex_case(project_root: Path) -> None:
    _success_case(
        "codex",
        project_root=project_root,
        provider_cfg={"execution-policy": {"full-auto": True}},
        required_env=("OPENAI_API_KEY",),
    )


def _cline_case(project_root: Path) -> None:
    _success_case(
        "cline",
        project_root=project_root,
        provider_cfg={"execution-policy": {"output-format": "json", "auto-approve": True}},
        required_env=("AUDIAGENTIC_TEST_CLINE_AUTH",),
    )


def _gemini_case(project_root: Path) -> None:
    _success_case(
        "gemini",
        project_root=project_root,
        provider_cfg={"execution-policy": {"output-format": "text"}},
        required_env=("GEMINI_API_KEY",),
    )


def _qwen_case(project_root: Path) -> None:
    _success_case(
        "qwen",
        project_root=project_root,
        required_env=("DASHSCOPE_API_KEY",),
    )


def _copilot_case(project_root: Path) -> None:
    _success_case(
        "copilot",
        project_root=project_root,
        prompt=_COPILOT_PROMPT,
        provider_cfg={},
        required_env=("GH_TOKEN",),
        assert_fn=_assert_non_empty,
    )


def _local_openai_case(project_root: Path) -> None:
    _require_env(
        "AUDIAGENTIC_TEST_LOCAL_OPENAI_MODEL",
        "AUDIAGENTIC_TEST_LOCAL_OPENAI_BASE_URL",
    )
    result = _execute_provider(
        project_root=project_root,
        provider_id="local-openai",
        model=os.environ["AUDIAGENTIC_TEST_LOCAL_OPENAI_MODEL"],
        prompt=_DEFAULT_PROMPT,
        provider_cfg={
            "api-base-url": os.environ["AUDIAGENTIC_TEST_LOCAL_OPENAI_BASE_URL"],
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
            "stream": False,
            "access-mode": "api",
        },
    )
    assert int(result.get("returncode", 0)) == 0, result
    _assert_contains(result, "local-openai", _DEFAULT_EXPECTED)


def _dispatch(provider_id: str, project_root: Path) -> None:
    if provider_id == "pi":
        _pi_case(project_root)
        return
    if provider_id == "opencode":
        _opencode_case(project_root)
        return
    if provider_id == "claude":
        _claude_case(project_root)
        return
    if provider_id == "codex":
        _codex_case(project_root)
        return
    if provider_id == "cline":
        _cline_case(project_root)
        return
    if provider_id == "gemini":
        _gemini_case(project_root)
        return
    if provider_id == "qwen":
        _qwen_case(project_root)
        return
    if provider_id == "copilot":
        _copilot_case(project_root)
        return
    if provider_id == "local-openai":
        _local_openai_case(project_root)
        return
    raise AssertionError(f"unhandled provider_id {provider_id!r}")


_EXECUTABLE_PROVIDER_IDS = (
    "claude",
    "cline",
    "codex",
    "copilot",
    "gemini",
    "local-openai",
    "opencode",
    "pi",
    "qwen",
)


@pytest.mark.parametrize("provider_id", _EXECUTABLE_PROVIDER_IDS)
@pytest.mark.timeout(600)
def test_provider_prompt_launch_contract(
    provider_id: str,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)
    _dispatch(provider_id, project_root)
