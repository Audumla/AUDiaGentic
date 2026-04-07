from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
DEFAULT_SCAN_ROOTS = [
    REPO_ROOT / "src" / "audiagentic",
    REPO_ROOT / "tools",
    REPO_ROOT / "tests",
]


@dataclass
class ImportRecord:
    file: str
    domain: str
    imports: list[str]
    unresolved_internal_imports: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory Python imports across the refactor scan roots."
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Optional additional scan root relative to the repository root.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the default text summary.",
    )
    return parser.parse_args()


def iter_python_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f"scan root does not exist: {root}")
        if root.is_file():
            files.append(root)
            continue
        files.extend(sorted(path for path in root.rglob("*.py") if path.is_file()))
    return files


def classify_domain(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT)
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "src" and parts[1] == "audiagentic":
        return parts[2]
    return parts[0]


def package_name_for(path: Path) -> str:
    rel = path.relative_to(SRC_ROOT).with_suffix("")
    return ".".join(rel.parts)


def resolve_module_name(path: Path, module: str | None, level: int) -> str | None:
    if level == 0:
        return module
    if not path.is_relative_to(SRC_ROOT):
        return None
    package = package_name_for(path.parent / "__init__.py" if path.name == "__init__.py" else path)
    package = package_name_for(path) if path.name == "__init__.py" else package_name_for(path.parent / "__init__.py")
    try:
        target = "." * level + (module or "")
        return importlib.util.resolve_name(target, package)
    except ImportError:
        return None


def module_exists(module_name: str) -> bool:
    if not module_name.startswith("audiagentic"):
        return True
    rel = Path(*module_name.split("."))
    candidates = [
        SRC_ROOT / rel.with_suffix(".py"),
        SRC_ROOT / rel / "__init__.py",
        SRC_ROOT / rel,
    ]
    return any(candidate.exists() for candidate in candidates)


def extract_imports(path: Path) -> ImportRecord:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"unable to read {path}: {exc}") from exc
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(f"unable to parse {path}: {exc}") from exc

    imports: list[str] = []
    unresolved: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                if alias.name.startswith("audiagentic") and not module_exists(alias.name):
                    unresolved.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module_name = resolve_module_name(path, node.module, node.level)
            if not module_name:
                continue
            imports.append(module_name)
            if module_name.startswith("audiagentic") and not module_exists(module_name):
                unresolved.append(module_name)
    return ImportRecord(
        file=str(path.relative_to(REPO_ROOT)),
        domain=classify_domain(path),
        imports=sorted(set(imports)),
        unresolved_internal_imports=sorted(set(unresolved)),
    )


def to_text(records: list[ImportRecord]) -> str:
    lines: list[str] = []
    grouped: dict[str, list[ImportRecord]] = {}
    for record in records:
        grouped.setdefault(record.domain, []).append(record)
    for domain in sorted(grouped):
        lines.append(f"[{domain}]")
        for record in grouped[domain]:
            lines.append(f"- {record.file}")
            for module_name in record.imports:
                marker = " (unresolved)" if module_name in record.unresolved_internal_imports else ""
                lines.append(f"  - {module_name}{marker}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    roots = list(DEFAULT_SCAN_ROOTS)
    if args.roots:
        roots.extend(REPO_ROOT / root for root in args.roots)
    records = [extract_imports(path) for path in iter_python_files(roots)]
    unresolved = [
        {"file": record.file, "imports": record.unresolved_internal_imports}
        for record in records
        if record.unresolved_internal_imports
    ]
    if args.json:
        payload = {
            "records": [record.__dict__ for record in records],
            "unresolved_internal_imports": unresolved,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(to_text(records))
        if unresolved:
            print("\nUnresolved internal imports:")
            for entry in unresolved:
                print(f"- {entry['file']}: {', '.join(entry['imports'])}")
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
