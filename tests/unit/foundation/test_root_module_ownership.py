"""Guard deliberate ownership of modules directly under ``foundation``."""
from pathlib import Path


def test_foundation_root_contains_only_declared_cross_cutting_modules() -> None:
    foundation_root = (
        Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "foundation"
    )
    actual = {
        path.name
        for path in foundation_root.glob("*.py")
        if path.name != "__init__.py"
    }

    assert actual == {
        "cli_io.py",
        "i18n.py",
        "io.py",
        "registry_utils.py",
        "templates.py",
        "time.py",
    }
