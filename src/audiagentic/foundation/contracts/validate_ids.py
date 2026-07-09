"""Validate canonical ids across fixtures and configs."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.cli_io import print_json
from audiagentic.foundation.components.ids import CORE_COMPONENT_IDS, get_optional_component_ids
from audiagentic.foundation.contracts.canonical_ids import (
    validate_ids,
    validate_schema_files,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import SCHEMA_DIR
from audiagentic.foundation.paths.package import REPO_ROOT


def _extract_ids(payload: Any) -> tuple[list[str], list[str]]:
    providers: list[str] = []
    components: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"provider-id", "provider_id"} and isinstance(value, str):
                providers.append(value)
            elif key == "providers" and isinstance(value, dict):
                providers.extend([k for k in value.keys() if isinstance(k, str)])
            elif key in {"component-id", "component_id"} and isinstance(value, str):
                components.append(value)
            elif key == "components" and isinstance(value, dict):
                components.extend([k for k in value.keys() if isinstance(k, str)])
            else:
                nested_providers, nested_components = _extract_ids(value)
                providers.extend(nested_providers)
                components.extend(nested_components)
    elif isinstance(payload, list):
        for item in payload:
            nested_providers, nested_components = _extract_ids(item)
            providers.extend(nested_providers)
            components.extend(nested_components)
    return providers, components


def _load_payload(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise AudiaGenticError(
        code="VAL-VIDS-001",
        kind="contracts",
        message=f"unsupported file type: {path.suffix}",
        details={"file": str(path), "suffix": path.suffix},
    )


def _should_validate_content(path: Path) -> bool:
    name = path.name.lower()
    if ".invalid." in name:
        return False
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path
    schema_root = SCHEMA_DIR.resolve()
    try:
        return schema_root not in resolved.parents and resolved != schema_root
    except RuntimeError:
        return True


def scan_paths(
    paths: Iterable[Path],
    *,
    provider_ids: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    allowed_provider_ids = tuple(provider_ids) if provider_ids is not None else None
    findings: list[dict[str, str]] = []
    for path in paths:
        if path.is_dir():
            files = list(path.rglob("*.json")) + list(path.rglob("*.yaml")) + list(
                path.rglob("*.yml")
            )
        else:
            files = [path]
        for file_path in files:
            if not _should_validate_content(file_path):
                continue
            try:
                payload = _load_payload(file_path)
            except Exception as exc:  # noqa: BLE001
                findings.append({"path": str(file_path), "issue": f"parse-error: {exc}"})
                continue
            providers, components = _extract_ids(payload)
            if allowed_provider_ids is not None:
                for issue in validate_ids(providers, allowed_provider_ids):
                    findings.append({"path": str(file_path), "issue": issue})
            # Descriptor-derived (requires registry population; falls back to
            # core-only during early bootstrap, so validation stays permissive).
            known_component_ids = CORE_COMPONENT_IDS | get_optional_component_ids()
            for issue in validate_ids(components, known_component_ids):
                findings.append({"path": str(file_path), "issue": issue})
    schema_findings = validate_schema_files(SCHEMA_DIR)
    for issue in schema_findings:
        findings.append({"path": str(SCHEMA_DIR.relative_to(REPO_ROOT)), "issue": issue})
    return findings


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate canonical ids.")
    parser.add_argument("paths", nargs="*", help="Paths to scan")
    parser.add_argument(
        "--provider-id",
        action="append",
        dest="provider_ids",
        help="Allowed provider id. Repeat to validate provider ids from foundation-only CLI.",
    )
    args = parser.parse_args(argv)
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        paths = [REPO_ROOT / "docs", REPO_ROOT / "docs" / "examples"]
    findings = scan_paths(paths, provider_ids=args.provider_ids)
    status = "ok" if not findings else "error"
    payload = {"status": status, "findings": findings}
    print_json(payload, indent=2, sort_keys=True)
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
