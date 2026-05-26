from __future__ import annotations

from pathlib import Path

from audiagentic.runtime.harness.paths import _PKG_ROOT

_AGENT_DIR = Path(__file__).parent
_TEMPLATES_DIR = _AGENT_DIR.parent / "templates"
_OPENCODE_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "opencode.yaml"

DEFAULT_API_KEY = "dummy"


def _print(msg: str) -> None:
    print(msg, flush=True)


def load_opencode_config(project_root: Path | None = None) -> dict:
    from audiagentic.runtime.config import load_layered_config
    return load_layered_config(
        pkg_default_path=_OPENCODE_CONFIG,
        project_root=project_root,
        namespace="harness/opencode",
    )
