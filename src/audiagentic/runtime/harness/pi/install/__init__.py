from __future__ import annotations

import logging
import os
import shutil
import urllib.request
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.harness.reload import (
    build_runtime_sync as _build_sync,
)
from audiagentic.runtime.harness.reload import (
    write_reload_marker,
)

from . import constants as _c
from .config import materialize_agent_config

logger = logging.getLogger(__name__)
_TARGET = "pi-runtime"


def version_info(project_root: Path | None = None) -> dict[str, str]:
    """Resolve configured agent + MCP adapter versions (env override, else pi.yaml)."""
    pi_cfg = _c.load_pi_config(project_root=project_root)
    agent_cfg = pi_cfg.get("agent", {})
    return {
        "agent": _c.AGENT_VERSION or agent_cfg.get("version", "latest"),
        "mcp_adapter": _c.AGENT_MCP_ADAPTER_VERSION or agent_cfg.get("mcp_adapter_version", "latest"),
    }


def _repo_root(project_root: Path | None) -> Path | None:
    candidates: list[Path] = []
    if project_root is not None:
        current = project_root.resolve()
        candidates.extend([current, *current.parents])
    module_root = Path(__file__).resolve()
    candidates.extend(module_root.parents)
    for candidate in candidates:
        if (candidate / "src" / "audiagentic").exists():
            return candidate
    return None


def _should_provision_embedded_rig() -> bool:
    return (
        os.environ.get("AUDIAGENTIC_PROVISION_PI_RIG") == "1"
        or os.environ.get("AUDIAGENTIC_DOCKER_TESTS") == "1"
        or os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") == "1"
        or "pytest" in (os.environ.get("PYTEST_CURRENT_TEST") or "").lower()
    )


def _seed_test_model(target: Path, project_root: Path | None) -> None:
    model_dir = target / "rig" / "bin" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    target_models = (
        model_dir / "Qwen3.5-0.8B.Q8_0.gguf",
        model_dir / "Qwen_Qwen3.5-2B-Q4_K_S.gguf",
    )
    if all(path.exists() for path in target_models):
        return
    repo_root = _repo_root(project_root)
    source_model = None if repo_root is None else repo_root / "tests" / "unit" / "runtime" / "Qwen3.5-0.8B-UD-Q5_K_XL.gguf"
    if source_model is not None and source_model.exists():
        for target_model in target_models:
            if not target_model.exists():
                shutil.copyfile(source_model, target_model)
        print_message(f"Seeded embedded rig model fixtures: {', '.join(str(path) for path in target_models)}")
        return
    model_url = os.environ.get(
        "AUDIAGENTIC_PI_RIG_MODEL_URL",
        "https://huggingface.co/lmstudio-community/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf?download=true",
    )
    source_target = next((path for path in target_models if not path.exists()), target_models[0])
    print_message(f"Downloading embedded rig smoke model to {source_target}")
    urllib.request.urlretrieve(model_url, source_target)
    for target_model in target_models:
        if target_model != source_target and not target_model.exists():
            shutil.copyfile(source_target, target_model)
    print_message(f"Provisioned embedded rig smoke models: {', '.join(str(path) for path in target_models)}")


def _provision_embedded_rig(target: Path, project_root: Path | None) -> None:
    from audiagentic.runtime.rig.embedded.binaries import update_binaries

    update_binaries(target_bin_dir=target / "rig" / "bin")
    _seed_test_model(target, project_root)


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str = _TARGET,
    has_mcp_servers: bool = True,
) -> dict[str, object]:
    return _build_sync(reason=reason, component_id=component_id, target=target, has_mcp_servers=has_mcp_servers)


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
    has_mcp_servers: bool = True,
) -> Path:
    return write_reload_marker(project_root, reason=reason, component_id=component_id, target=_TARGET, has_mcp_servers=has_mcp_servers)


def install_to(target: Path, project_root: Path | None = None) -> int:
    for path in (target / "agent", target / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    rig_bin = target / "rig" / "bin"
    for platform_dir in ("windows", "macOS", "linux"):
        (rig_bin / "llama-server" / platform_dir).mkdir(parents=True, exist_ok=True)
    (rig_bin / "models").mkdir(parents=True, exist_ok=True)
    print_message(f"Rig binary dir: {rig_bin / 'llama-server'}")
    print_message("  Place llama-server binaries in the platform subfolder (windows/macOS/linux).")
    print_message(f"Model dir:      {rig_bin / 'models'}")
    print_message("  Place .gguf model files here.")
    if _should_provision_embedded_rig():
        print_message("Provisioning embedded rig assets for Pi runtime")
        _provision_embedded_rig(target, project_root)

    # AUDiaGentic no longer bundles a harness CLI. The harness is whichever
    # supported one is installed on the system (config-driven order); install
    # only provisions the rig backend and materializes the agent config.
    harness_cfg = _c.load_harness_config(project_root=project_root)
    materialize_agent_config(target, harness_cfg, project_root=project_root)
    return 0


def cleanup_runtime(target: Path) -> int:
    """Remove generated agent config while preserving user-owned assets.

    Rig binaries, models, and logs are left in place because they may be large
    user-managed assets or useful diagnostics.
    """
    for path in (target / "agent",):
        if path.exists():
            shutil.rmtree(path)
    return 0


def refresh_materialized_agent_config(target: Path, project_root: Path | None = None) -> int:
    """Rebuild generated agent config for current project/component state."""
    harness_cfg = _c.load_harness_config(project_root=project_root)
    materialize_agent_config(target, harness_cfg, project_root=project_root)
    return 0


def mcp_config_path(project_root: Path | None = None) -> Path:
    from audiagentic.runtime.harness.pi.mcp_format import pi_mcp_path
    return pi_mcp_path(project_root)


def read_mcp_config(path: Path) -> dict:
    from audiagentic.runtime.harness.pi.mcp_format import read_pi_mcp_json
    return read_pi_mcp_json(path)


def write_mcp_config(path: Path, entries: dict) -> None:
    from audiagentic.runtime.harness.pi.mcp_format import write_pi_mcp_json
    write_pi_mcp_json(path, entries)


def remove_mcp_config(path: Path, name: str) -> bool:
    from audiagentic.runtime.harness.pi.mcp_format import remove_pi_mcp_json
    return remove_pi_mcp_json(path, name)


def refresh_harness_config_if_installed(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> bool:
    """Regenerate mcp.json and request runtime reload if harness is installed.

    Returns True if harness was present and config was refreshed.
    """
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness import get_harness_type
    from audiagentic.runtime.harness.resolution import harness_cli_available

    harness_runtime = global_harness_runtime()
    if harness_cli_available(get_harness_type(project_root)) is None:
        return False
    refreshed = True
    try:
        refresh_materialized_agent_config(harness_runtime, project_root=project_root)
    except AudiaGenticError:
        logger.warning("Failed to refresh agent config for %s", component_id, exc_info=True, extra={"component": component_id})
        refreshed = False
    try:
        request_runtime_reload(project_root, reason=reason, component_id=component_id)
    except AudiaGenticError:
        logger.warning("Failed to request runtime reload for %s", component_id, exc_info=True, extra={"component": component_id})
        refreshed = False
    return refreshed

