"""Architecture regression tests: prohibit direct OS signalling outside foundation seams.

AS17 requires that process lifetime signals (SIGTERM, SIGKILL, kill_process_tree)
flow through the approved foundation contract: adopt/observe/stop via
audiagentic.foundation.system.adopted_process and audiagentic.foundation.system.process.

These tests verify that future changes do not reintroduce direct os.kill /
subprocess.taskkill calls in component layers that should use the foundation seam.

Forbidden patterns in non-foundation code:
- ``os.kill`` for process signalling (not for signal 0 / liveness checks)
- ``signal.kill_process_tree`` imported outside foundation.system
- subprocess calls to taskkill or kill outside foundation.system
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


def _get_python_files(directory: Path) -> list[Path]:
    """Get all Python files in a directory recursively, excluding __pycache__."""
    if not directory.exists():
        return []
    return sorted(
        p for p in directory.rglob("*.py")
        if "__pycache__" not in p.parts and "/test_" not in str(p)
    )


def _get_imports(filepath: Path) -> list[str]:
    """Extract all import module names from a Python file."""
    try:
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, SystemError, RecursionError):
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


# Patterns that represent direct OS signalling (not through the foundation seam).
_SIGNAL_PATTERNS = [
    # os.kill with a real signal (not signal 0 / liveness check)
    r"os\.kill\s*\(",
    # subprocess calls to taskkill (Windows force-kill)
    r"taskkill\s*\/PID",
    r"'taskkill'",
    # os.killpg for group kill without going through the seam
    r"os\.killpg\s*\(",
]


class TestNoDirectProcessSignalling:
    """Verify no component code directly signals processes.

    Process signalling must go through foundation.system.adopted_process
    (stop_child) or foundation.system.process (kill_process_tree) which
    enforce ownership verification before sending signals.

    Allowed exceptions:
    - foundation/system/ modules themselves (they define the seam)
    - supervised_run signal forwarding (SIGINT/SIGTERM forwarding, not
      termination — this is a legitimate forwarder, not a terminator)
    """

    @pytest.fixture
    def src_root(self) -> Path:
        return WORKSPACE_ROOT / "src" / "audiagentic"

    @pytest.fixture
    def foundation_system_dir(self, src_root: Path) -> Path:
        return src_root / "foundation" / "system"

    def _is_foundation_system(self, filepath: Path, foundation_system_dir: Path) -> bool:
        """Check if a file is inside foundation/system/ (the seam owner)."""
        try:
            filepath.relative_to(foundation_system_dir)
            return True
        except ValueError:
            return False

    def _is_supervised_run(self, filepath: Path) -> bool:
        """supervised_run.py forwards signals — that's a legitimate forwarder."""
        return filepath.name == "supervised_process.py"

    def test_no_direct_os_kill_in_components(self, src_root: Path) -> None:
        """No component code calls os.kill for process signalling.

        This is the key boundary: components (agents, providers, memory, etc.)
        must signal processes through the foundation adopted-process seam,
        not directly via os.kill. The foundation layer itself is exempt — it
        defines the approved seam.
        """
        violations = []
        component_dirs = [
            src_root / "components" / "agents",
            src_root / "components" / "providers",
            src_root / "components" / "memory",
            src_root / "components" / "coding_lsp",
            src_root / "components" / "agent_jobs",
            src_root / "components" / "planning",
        ]

        for comp_dir in component_dirs:
            if not comp_dir.exists():
                continue
            for pyfile in _get_python_files(comp_dir):
                try:
                    with open(pyfile, encoding="utf-8") as f:
                        source = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                for pattern in _SIGNAL_PATTERNS:
                    matches = re.finditer(pattern, source)
                    for match in matches:
                        # Get surrounding context to distinguish legitimate uses
                        start = max(0, match.start() - 40)
                        end = min(len(source), match.end() + 40)
                        context = source[start:end].replace("\n", " ")
                        violations.append(
                            f"{pyfile.relative_to(src_root)}: "
                            f"direct signal pattern '{match.group()}' — {context}"
                        )

        assert not violations, (
            "Direct process signalling found in component code.\n"
            "Use foundation.system.adopted_process.stop_child instead:\n\n"
            + "\n".join(violations)
        )

    def test_no_kill_process_tree_import_outside_foundation(
        self, src_root: Path, foundation_system_dir: Path
    ) -> None:
        """No component code imports kill_process_tree directly.

        The foundation seam provides stop_child which calls kill_process_tree
        after ownership verification. Bypassing the seam risks signalling
        PID-reused processes or externally-owned children.
        """
        violations = []
        for pyfile in _get_python_files(src_root):
            if self._is_foundation_system(pyfile, foundation_system_dir):
                continue

            imports = _get_imports(pyfile)
            for imp in imports:
                if "kill_process_tree" in imp and "foundation.system" not in imp:
                    violations.append(
                        f"{pyfile.relative_to(src_root)}: imports {imp}"
                    )

        assert not violations, (
            "kill_process_tree imported outside foundation/system/.\n"
            "Use foundation.system.adopted_process.stop_child instead:\n"
            + "\n".join(violations)
        )

    def test_no_subprocess_taskkill_in_components(self, src_root: Path) -> None:
        """No component code invokes taskkill via subprocess.

        Windows force-kill must go through kill_process_tree in foundation,
        which enforces ownership verification first.
        """
        violations = []
        for comp_dir in [
            src_root / "components",
            src_root / "foundation" / "transports",  # ACP transport should use seam
        ]:
            if not comp_dir.exists():
                continue
            for pyfile in _get_python_files(comp_dir):
                try:
                    with open(pyfile, encoding="utf-8") as f:
                        source = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                if "taskkill" in source.lower():
                    violations.append(
                        f"{pyfile.relative_to(src_root)}: references 'taskkill'"
                    )

        assert not violations, (
            "Direct taskkill subprocess calls found.\n"
            "Use foundation.system.process.kill_process_tree instead:\n"
            + "\n".join(violations)
        )
