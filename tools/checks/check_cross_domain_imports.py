from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
DOMAIN_ROOT = SRC_ROOT / "audiagentic"
FROZEN_DOMAINS = {
    "contracts",
    "core",
    "config",
    "scoping",
    "execution",
    "runtime",
    "channels",
    "streaming",
    "observability",
}
ALLOWED: dict[str, set[str]] = {
    "contracts": set(),
    "core": {"contracts"},
    "config": {"contracts", "core"},
    "scoping": {"contracts", "core", "config"},
    "execution": {"contracts", "core", "config", "runtime", "streaming"},
    "runtime": {"contracts", "core", "config"},
    "channels": {"contracts", "core", "config", "runtime", "execution"},
    "streaming": {"execution", "runtime", "channels", "contracts", "core"},
    "observability": {"runtime", "contracts", "core", "config"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check imports under new repository domains against frozen dependency rules."
    )
    parser.add_argument(
        "--root",
        default=str(DOMAIN_ROOT),
        help="Root to scan (default: src/audiagentic).",
    )
    return parser.parse_args()


def package_name_for(path: Path) -> str:
    rel = path.relative_to(SRC_ROOT).with_suffix("")
    return ".".join(rel.parts)


def resolve_module_name(path: Path, module: str | None, level: int) -> str | None:
    if level == 0:
        return module
    package = package_name_for(path.parent / "__init__.py" if path.name == "__init__.py" else path)
    package = package_name_for(path) if path.name == "__init__.py" else package_name_for(path.parent / "__init__.py")
    try:
        target = "." * level + (module or "")
        return importlib.util.resolve_name(target, package)
    except ImportError:
        return None


def domain_for_file(path: Path) -> str | None:
    rel = path.relative_to(DOMAIN_ROOT)
    if not rel.parts:
        return None
    domain = rel.parts[0]
    return domain if domain in FROZEN_DOMAINS else None


def imported_domain(module_name: str) -> str | None:
    if not module_name or not module_name.startswith("audiagentic."):
        return None
    parts = module_name.split(".")
    if len(parts) < 2:
        return None
    domain = parts[1]
    return domain if domain in FROZEN_DOMAINS else None


def collect_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        domain = domain_for_file(path)
        if domain is None:
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            module_name: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = imported_domain(alias.name)
                    if target and target != domain and target not in ALLOWED[domain]:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)} imports forbidden domain {target} via {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module_name = resolve_module_name(path, node.module, node.level)
                target = imported_domain(module_name) if module_name else None
                if target and target != domain and target not in ALLOWED[domain]:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} imports forbidden domain {target} via {module_name}"
                    )
    return violations


def main() -> int:
    args = parse_args()
    root = (REPO_ROOT / args.root).resolve() if not Path(args.root).is_absolute() else Path(args.root)
    if not root.exists():
        print(f"scan root does not exist: {root}", file=sys.stderr)
        return 1
    violations = collect_violations(root)
    if violations:
        print("Cross-domain dependency violations:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("Cross-domain dependency check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
