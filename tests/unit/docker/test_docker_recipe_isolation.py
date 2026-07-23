"""Static gates for clean-room Docker test recipes."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKER_DIR = ROOT / "tests" / "docker"


def _dockerfiles() -> list[Path]:
    return sorted(DOCKER_DIR.glob("Dockerfile*"))


def test_recipes_never_copy_the_whole_development_context() -> None:
    offenders: list[str] = []
    broad_copy = re.compile(r"^\s*(?:COPY|ADD)\s+(?:--\S+\s+)*\.\s+/?app/?\s*$", re.MULTILINE)
    for path in _dockerfiles():
        if broad_copy.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == [], f"broad development-context copies: {offenders}"


def test_recipes_never_import_user_owned_harness_state() -> None:
    forbidden = (".claude/", ".codex/", ".config/", ".cache/")
    offenders: list[str] = []
    for path in _dockerfiles():
        for line in path.read_text(encoding="utf-8").splitlines():
            normalized = line.strip().replace("\\", "/").lower()
            if normalized.startswith(("copy ", "add ")) and any(
                token in normalized for token in forbidden
            ):
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == [], "user-owned harness state copied into Docker:\n" + "\n".join(offenders)


def test_mutating_recipes_declare_disposable_home() -> None:
    recipe_names = {
        "Dockerfile.gateway-opencode",
        "Dockerfile.gateway-pi-smoke",
        "Dockerfile.lsp-install-test",
        "Dockerfile.provider-cli-comprehensive",
        "Dockerfile.provider-cli-test",
        "Dockerfile.provider-config-matrix-e2e",
        "Dockerfile.provider-lifecycle-e2e",
        "Dockerfile.provider-lsp-e2e",
    }
    missing: list[str] = []
    for name in sorted(recipe_names):
        source = (DOCKER_DIR / name).read_text(encoding="utf-8")
        if "ENV HOME=/tmp/" not in source or "ENV AUDIAGENTIC_HOME=/tmp/" not in source:
            missing.append(name)
    assert missing == [], f"mutating recipes without disposable HOME/AUDIAGENTIC_HOME: {missing}"
