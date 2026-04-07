"""Validate canonical ids across fixtures and configs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.contracts.canonical_ids import (
    CANONICAL_COMPONENT_IDS,
    CANONICAL_PROVIDER_IDS,
    validate_ids,
    validate_schema_files,
)
from audiagentic.contracts.schema_registry import SCHEMA_DIR


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
    raise ValueError("unsupported file type")


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


def scan_paths(paths: Iterable[Path]) -> list[dict[str, str]]:
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
            for issue in validate_ids(providers, CANONICAL_PROVIDER_IDS):
                findings.append({"path": str(file_path), "issue": issue})
            for issue in validate_ids(components, CANONICAL_COMPONENT_IDS):
                findings.append({"path": str(file_path), "issue": issue})
    schema_findings = validate_schema_files(SCHEMA_DIR)
    for issue in schema_findings:
        findings.append({"path": str(SCHEMA_DIR.relative_to(REPO_ROOT)), "issue": issue})
    return findings


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate canonical ids.")
    parser.add_argument("paths", nargs="*", help="Paths to scan")
    args = parser.parse_args(argv)
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        paths = [REPO_ROOT / "docs", REPO_ROOT / "docs" / "examples"]
    findings = scan_paths(paths)
    status = "ok" if not findings else "error"
    payload = {"status": status, "findings": findings}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
