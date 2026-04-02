"""Fresh install lifecycle operations."""
from __future__ import annotations

from pathlib import Path

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.checkpoints import write_checkpoint
from audiagentic.runtime.lifecycle.detector import detect_installed_state
from audiagentic.runtime.lifecycle.manifest import build_manifest, write_manifest
from tools.seed_example_project import seed_example_project

DEFAULT_VERSION = "0.1.0"


def apply_fresh_install(project_root: Path) -> dict:
    state = detect_installed_state(project_root)
    if state.state != "none":
        raise AudiaGenticError(
            code="LFC-BUSINESS-001",
            kind="business-rule",
            message="fresh install requires empty state",
            details={"state": state.state},
        )

    write_checkpoint(project_root, "planned", {"action": "fresh-install"})
    write_checkpoint(project_root, "pre-destructive", {"action": "fresh-install"})

    seed_example_project(project_root, overwrite=True)

    manifest_payload = build_manifest(
        installation_kind="fresh",
        current_version=DEFAULT_VERSION,
        previous_version=None,
        components={"core-lifecycle": "installed", "release-audit-ledger": "installed"},
        providers={"local-openai": "configured"},
        last_lifecycle_action="fresh-install",
    )
    write_manifest(project_root, manifest_payload)

    write_checkpoint(project_root, "post-cleanup", {"action": "fresh-install"})
    return {
        "contract-version": "v1",
        "mode": "apply",
        "status": "success",
        "completed-operations": ["create-.audiagentic", "write-configs", "write-manifest"],
        "warnings": [],
        "checkpoint-dir": ".audiagentic/runtime/lifecycle/checkpoints",
    }
