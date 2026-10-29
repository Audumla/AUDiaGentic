"""Read-only settings commands: ``config show``, ``config validate``, ``config paths``.

They never build the application graph, probe providers or write files.
Exit codes: 0 ok, 1 requested key not set, 2 invalid settings, 3 discovery or
read failure.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

EXIT_NOT_SET = 1
EXIT_INVALID = 2
EXIT_UNAVAILABLE = 3
_INVALID_CODES = {"CFG-SET-002", "CFG-SET-003", "CFG-SET-004"}


def add_settings_parsers(config_sub: Any) -> None:
    show = config_sub.add_parser("show", help="Show effective settings (read-only)")
    show.add_argument("key", nargs="?", help="Dotted key, for example agents.default")
    show.add_argument("--origin", action="store_true", help="Show the scope, file and line of each value")
    show.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    show.add_argument("--config", dest="config_file", metavar="FILE", help="Explicit settings file (highest file scope)")
    validate = config_sub.add_parser("validate", help="Validate every settings scope (read-only)")
    validate.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    validate.add_argument("--config", dest="config_file", metavar="FILE", help="Explicit settings file (highest file scope)")
    paths = config_sub.add_parser("paths", help="Show settings, state and cache locations (read-only)")
    paths.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    paths.add_argument("--config", dest="config_file", metavar="FILE", help="Explicit settings file (highest file scope)")


SETTINGS_COMMANDS = {"show", "validate", "paths"}
_MISSING = object()


def run_settings_command(args: argparse.Namespace) -> int:
    from audiagentic.foundation.config import settings

    try:
        if args.config_cmd == "paths":
            return _paths(args, settings)
        resolved = settings.resolve_settings(
            project=args.project, config_file=args.config_file, collect=args.config_cmd == "validate",
        )
    except AudiaGenticError as error:
        _emit_error(args, error)
        return EXIT_INVALID if error.code in _INVALID_CODES else EXIT_UNAVAILABLE
    if args.config_cmd == "validate":
        return _validate(args, resolved)
    return _show(args, resolved)


def _emit_error(args: argparse.Namespace, error: AudiaGenticError) -> None:
    details = error.details or {}
    if args.as_json:
        print(json.dumps({"ok": False, "error-code": error.code, "message": error.message, "details": details}))
        return
    where = details.get("file") or details.get("project") or ""
    if details.get("line") is not None:
        where += f":{details['line']}:{details['column']}"
    pointer = details.get("pointer")
    print(f"{error.code}: {error.message}" + (f" ({where}{' ' + pointer if pointer else ''})" if where else ""))


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict) and value:
        rows = []
        for name, child in value.items():
            rows.extend(_flatten(child, f"{prefix}.{name}" if prefix else name))
        return rows
    return [(prefix, value)]


def _origin_dict(origin: Any) -> dict[str, Any] | None:
    if origin is None:
        return None
    return {"scope": origin.scope, "file": origin.file, "line": origin.line, "column": origin.column,
            "deleted": origin.deleted}


def _show(args: argparse.Namespace, resolved: Any) -> int:
    if args.key:
        value = resolved.get(args.key, _MISSING)
        origin = resolved.origin(args.key)
        if value is _MISSING:
            if args.as_json:
                print(json.dumps({"key": args.key, "found": False, "origin": _origin_dict(origin)}))
            else:
                print(f"{args.key} is not set" + (f" ({origin.describe()})" if args.origin and origin else ""))
            return EXIT_NOT_SET
        if args.as_json:
            print(json.dumps({"key": args.key, "found": True, "value": value, "origin": _origin_dict(origin)}))
        else:
            print(f"{args.key} = {json.dumps(value)}" + (f"  # {origin.describe()}" if args.origin and origin else ""))
        return 0
    if args.as_json:
        payload: dict[str, Any] = {"values": resolved.values,
                                   "project-root": str(resolved.project_root) if resolved.project_root else None}
        if args.origin:
            payload["origins"] = {pointer: _origin_dict(origin) for pointer, origin in sorted(resolved.origins.items())}
        print(json.dumps(payload, indent=2))
        return 0
    for key, value in _flatten(resolved.values):
        origin = resolved.origin(key) if key else None
        print(f"{key} = {json.dumps(value)}" + (f"  # {origin.describe()}" if args.origin and origin else ""))
    if args.origin:
        for pointer, origin in sorted(resolved.origins.items()):
            if origin.deleted:
                print(f"{pointer.lstrip('/').replace('/', '.')}  # {origin.describe()}")
    return 0



def _validate(args: argparse.Namespace, resolved: Any) -> int:
    present = [{"scope": s.scope, "file": str(s.path)} for s in resolved.sources if s.present]
    issues = [{"file": i.file, "line": i.line, "column": i.column, "pointer": i.pointer or "/", "message": i.message}
              for i in resolved.issues]
    if args.as_json:
        print(json.dumps({"ok": not issues, "scopes": present, "issues": issues}, indent=2))
    else:
        for issue in resolved.issues:
            print(issue.describe())
        print(f"{'invalid' if issues else 'ok'}: {len(present)} settings file(s) checked"
              + (f", {len(issues)} issue(s)" if issues else ""))
    return EXIT_INVALID if issues else 0


def _paths(args: argparse.Namespace, settings: Any) -> int:
    project_root = settings.discover_project_root(args.project)
    sources = settings.scope_sources(project_root=project_root, config_file=args.config_file)
    rows = [{"kind": "settings", "scope": s.scope, "path": str(s.path) if s.path else None, "present": s.present}
            for s in sources]
    from audiagentic.foundation.paths.home import user_cache_dir, user_state_dir
    from audiagentic.foundation.paths.names import home_source

    home, home_origin = home_source(args.config_file)
    rows += [{"kind": "home", "scope": home_origin, "path": str(home), "present": home.is_dir()},
             {"kind": "state", "scope": "user", "path": str(user_state_dir()), "present": user_state_dir().is_dir()},
             {"kind": "cache", "scope": "user", "path": str(user_cache_dir()), "present": user_cache_dir().is_dir()}]
    if args.as_json:
        print(json.dumps({"project-root": str(project_root) if project_root else None, "paths": rows}, indent=2))
    else:
        print(f"project root: {project_root or '(none)'}")
        for row in rows:
            print(f"{row['kind']:<8} {row['scope']:<8} {row['path'] or '(none)'}{'' if row['present'] else '  (absent)'}")
    return 0
