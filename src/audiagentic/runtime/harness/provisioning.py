"""Provider-neutral embedded-rig asset provisioning."""
from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path

from audiagentic.foundation.cli_io import print_message


def _repo_root(project_root: Path | None) -> Path | None:
    candidates = [project_root.resolve(), *project_root.resolve().parents] if project_root else []
    candidates.extend(Path(__file__).resolve().parents)
    return next((path for path in candidates if (path / "src" / "audiagentic").exists()), None)


def should_provision_embedded_rig() -> bool:
    return (
        os.environ.get("AUDIAGENTIC_PROVISION_PI_RIG") == "1"
        or os.environ.get("AUDIAGENTIC_DOCKER_TESTS") == "1"
        or os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") == "1"
        or "pytest" in (os.environ.get("PYTEST_CURRENT_TEST") or "").lower()
    )


def provision_embedded_rig(target: Path, project_root: Path | None) -> None:
    """Provision test/explicit embedded-rig assets without provider ownership."""
    from audiagentic.runtime.rig.embedded.recipe import llama_cpp_recipe

    bin_dir = target / "rig" / "bin"
    result = llama_cpp_recipe(bin_dir).provision({})
    if not result.success:
        raise RuntimeError(result.error or result.status)
    models_dir = bin_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    targets = (models_dir / "Qwen3.5-0.8B.Q8_0.gguf", models_dir / "Qwen_Qwen3.5-2B-Q4_K_S.gguf")
    if all(path.exists() for path in targets):
        return
    root = _repo_root(project_root)
    fixture = None if root is None else root / "tests" / "unit" / "runtime" / "Qwen3.5-0.8B-UD-Q5_K_XL.gguf"
    if fixture is not None and fixture.exists():
        for path in targets:
            if not path.exists():
                shutil.copyfile(fixture, path)
        return
    source = os.environ.get("AUDIAGENTIC_PI_RIG_MODEL_URL", "https://huggingface.co/lmstudio-community/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf?download=true")
    destination = next(path for path in targets if not path.exists())
    print_message(f"Downloading embedded rig smoke model to {destination}")
    urllib.request.urlretrieve(source, destination)
    for path in targets:
        if not path.exists():
            shutil.copyfile(destination, path)
