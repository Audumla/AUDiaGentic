from __future__ import annotations

from pathlib import Path

from audiagentic.runtime.harness.pi.paths import find_pi_package_root

TRUTHY = {"1", "true", "yes", "on"}

_AGENT_DIR = Path(__file__).parent

_PKG_ROOT = find_pi_package_root(_AGENT_DIR)
_RIG_CONFIG = _PKG_ROOT / "config" / "provisioning" / "rig" / "rig.yaml"
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"
