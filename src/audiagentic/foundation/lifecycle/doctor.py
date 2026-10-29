"""``doctor`` mechanics: discover component-declared checks and run them read-only.

Each component declares its checks in
``config/components/<component>/doctor/checks.yaml`` as ``id`` plus a
``module:attr`` ``ref`` (resolved by ``foundation.config.refs``), so no central
list names component checks. A check takes a ``DoctorContext`` and returns
``CheckResult`` values; checks never write files. Foundation's own generic
checks (settings validity, package data) are declared the same way.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.config.refs import resolve_ref
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.names import get_component_config_dirs

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class DoctorContext:
    project: Path | None  # explicit --project, else discovery inside the checks


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: str  # ok | warn | fail
    message: str
    fix: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"check": self.check, "status": self.status, "message": self.message, "fix": self.fix}


@dataclass(frozen=True)
class DeclaredCheck:
    check_id: str
    component: str
    ref: str


def declared_checks() -> list[DeclaredCheck]:
    checks: list[DeclaredCheck] = []
    for base in get_component_config_dirs():
        for path in sorted(base.glob("*/doctor/checks.yaml")):
            component = path.parent.parent.name
            for item in (load_yaml_file(path) or {}).get("checks", []):
                checks.append(DeclaredCheck(item["id"], component, item["ref"]))
    return checks


def run_checks(context: DoctorContext) -> list[CheckResult]:
    """Run every declared check; a check that raises becomes a failed result."""
    results: list[CheckResult] = []
    for declared in declared_checks():
        try:
            check: Callable[[DoctorContext], list[CheckResult]] = resolve_ref(declared.ref)
            results.extend(check(context))
        except AudiaGenticError as error:
            results.append(CheckResult(declared.check_id, FAIL, f"{error.code}: {error.message}",
                                       _fix_for(error)))
        except Exception as error:  # noqa: BLE001 - report, never crash doctor
            results.append(CheckResult(declared.check_id, FAIL, f"check crashed: {type(error).__name__}: {error}"))
    return results


def _fix_for(error: AudiaGenticError) -> str | None:
    from audiagentic.foundation.contracts.errors import get_error_resolution

    details = error.details or {}
    where = details.get("file")
    if where and details.get("line") is not None:
        where += f":{details['line']}"
    resolution = get_error_resolution(error.code)
    return f"{resolution} ({where})" if where and resolution else resolution or where


def check_package_data(context: DoctorContext) -> list[CheckResult]:
    """Packaged defaults and schemas this release needs are installed."""
    del context
    from audiagentic.foundation.config.settings import vendor_settings_path
    from audiagentic.foundation.contracts.schema_registry import schema_path

    missing = [] if vendor_settings_path().is_file() else [str(vendor_settings_path())]
    for stem in ("settings", "agent-file"):
        try:
            schema_path(stem)
        except FileNotFoundError:
            missing.append(f"{stem}.schema.json")
    if missing:
        return [CheckResult("package.data", FAIL, f"missing packaged files: {', '.join(missing)}",
                            "Reinstall audiagentic (pip install --force-reinstall audiagentic)")]
    return [CheckResult("package.data", OK, "packaged defaults and schemas present")]
