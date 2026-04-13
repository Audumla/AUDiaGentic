"""Check imports under repository domains against frozen dependency rules.

Domain model reflects the v3 structural refactor:

  IMPLEMENTED:
    foundation       — shared contracts and config (base layer, no domain deps)
    planning         — planning workflows
    execution        — job orchestration and bridges
    interoperability — external integrations (providers, protocols/streaming)
    runtime          — lifecycle and state persistence
    release          — governance, audit, and release finalization
    channels/cli     — CLI operator surface

  SCAFFOLD ONLY (reserved, no executable code):
    knowledge                          — optional capability domain
    channels/vscode                    — VS Code editor integration
    interoperability/mcp               — MCP protocol scaffolding
    interoperability/protocols/acp     — ACP inter-agent protocol scaffolding

  DEPENDENCY NOTES:
    execution -> release   intentional (release_bridge.py is a one-way seam)
    interoperability -> execution  intentional (gemini adapter calls prompt_launch)
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path

# Use the shared repo-root helper so this tool works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.lib.repo_paths import REPO_ROOT, SRC_ROOT

DOMAIN_ROOT = SRC_ROOT / "audiagentic"

# Canonical domains after v3 refactor.
FROZEN_DOMAINS = {
    "foundation",
    "planning",
    "execution",
    "interoperability",
    "runtime",
    "release",
    "channels",
    "knowledge",
}

# Allowed import directions. A domain may only import from listed domains.
# Omitted domains default to no allowed cross-domain imports.
ALLOWED: dict[str, set[str]] = {
    "foundation": set(),
    "planning": {"foundation"},
    "execution": {"foundation", "runtime", "interoperability", "release"},
    "interoperability": {"foundation", "execution"},
    "runtime": {"foundation"},
    "release": {"foundation", "runtime"},
    "channels": {"foundation", "runtime", "execution", "release"},
    "knowledge": {"foundation"},
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
    package = (
        package_name_for(path)
        if path.name == "__init__.py"
        else package_name_for(path.parent / "__init__.py")
    )
    try:
        target = "." * level + (module or "")
        return importlib.util.resolve_name(target, package)
    except ImportError:
        return None


def domain_for_file(path: Path) -> str | None:
    try:
        rel = path.relative_to(DOMAIN_ROOT)
    except ValueError:
        return None
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
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        allowed = ALLOWED.get(domain, set())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = imported_domain(alias.name)
                    if target and target != domain and target not in allowed:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)} imports forbidden domain "
                            f"'{target}' via '{alias.name}'"
                        )
            elif isinstance(node, ast.ImportFrom):
                module_name = resolve_module_name(path, node.module, node.level)
                target = imported_domain(module_name) if module_name else None
                if target and target != domain and target not in allowed:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} imports forbidden domain "
                        f"'{target}' via '{module_name}'"
                    )
    return violations


def main() -> int:
    args = parse_args()
    root = (
        (REPO_ROOT / args.root).resolve()
        if not Path(args.root).is_absolute()
        else Path(args.root)
    )
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
