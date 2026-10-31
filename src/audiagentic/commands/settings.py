"""Settings commands: ``config show``, ``validate``, ``paths`` (read-only) and ``config set``.

They never build the application graph or probe providers. ``config set`` is the
only one that writes, and only the settings file of the scope it names.
Exit codes: 0 ok, 1 requested key not set, 2 invalid settings or input,
3 discovery, read or write failure.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from audiagentic.foundation.config.strict_yaml import settings_error
from audiagentic.foundation.contracts.errors import AudiaGenticError

EXIT_NOT_SET = 1
EXIT_INVALID = 2
EXIT_UNAVAILABLE = 3
_INVALID_CODES = {"CFG-SET-002", "CFG-SET-003", "CFG-SET-004", "CFG-SET-009", "CFG-SET-012", "CFG-SET-013"}


def add_settings_parsers(config_sub: Any) -> None:
    show = config_sub.add_parser("show", help="Show effective settings (read-only)")
    show.add_argument("key", nargs="?", help="Dotted key, for example agents.default")
    show.add_argument("--origin", action="store_true", help="Show the scope, file and line of each value")
    show.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    show.add_argument("--config", dest="config_file", metavar="FILE", help="Explicit settings file (highest file scope)")
    validate = config_sub.add_parser("validate", help="Validate every settings scope (read-only)")
    validate.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    validate.add_argument("--config", dest="config_file", metavar="FILE", help="Explicit settings file (highest file scope)")
    write = config_sub.add_parser(
        "set", help="Set or remove settings keys in one scope's settings file (comments and order are kept)",
    )
    write.add_argument("assignments", nargs="*", metavar="KEY=VALUE",
                       help="Dotted key and YAML or JSON value, for example providers.pi.enabled=false")
    write.add_argument("--unset", action="append", default=[], metavar="KEY", help="Remove a key (repeatable)")
    write.add_argument("--scope", choices=("project", "user-project", "user"), default="project",
                       help="Which settings file to write (default: project, .audiagentic/settings.yaml)")
    write.add_argument("--dry-run", action="store_true", help="Show the change without writing")
    write.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    write.add_argument("--config", dest="config_file", metavar="FILE", help=argparse.SUPPRESS)
    migrate = config_sub.add_parser(
        "migrate", help="Move legacy configuration to its current home (preview unless --apply)",
    )
    migrate.add_argument("--apply", action="store_true", help="Make the change (default: preview only)")
    migrate.add_argument("--rollback", metavar="MANIFEST", help="Undo the migration recorded in this manifest file")
    migrate.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    migrate.add_argument("--config", dest="config_file", metavar="FILE", help=argparse.SUPPRESS)
    paths = config_sub.add_parser("paths", help="Show settings, state and cache locations (read-only)")
    paths.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    paths.add_argument("--config", dest="config_file", metavar="FILE", help="Explicit settings file (highest file scope)")


SETTINGS_COMMANDS = {"show", "validate", "paths", "set", "migrate"}
_MISSING = object()


def run_settings_command(args: argparse.Namespace) -> int:
    from audiagentic.foundation.config import settings

    try:
        if args.config_cmd == "paths":
            return _paths(args, settings)
        if args.config_cmd == "set":
            return _set(args, settings)
        if args.config_cmd == "migrate":
            return _migrate(args, settings)
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


def _split_key(key: str) -> list[str]:
    """Dotted key to its parts; a backslash escapes a dot inside a part."""
    parts, current, escaped = [], "", False
    for char in key:
        if escaped:
            current, escaped = current + char, False
        elif char == "\\":
            escaped = True
        elif char == ".":
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    if escaped or not all(parts):
        raise settings_error(13, "Settings key is not valid", key=key)
    return parts


def _parse_value(text: str, key: str) -> Any:
    from audiagentic.foundation.config.strict_yaml import resolve_plain_scalar

    if text[:1] in {'"', "[", "{"}:
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise settings_error(13, "Settings value is not valid JSON", key=key, reason=error.msg) from None
    try:
        return resolve_plain_scalar(text)
    except ValueError as error:
        raise settings_error(13, "Settings value is not valid", key=key, reason=str(error)) from None


def build_patch(assignments: list[str], unsets: list[str]) -> dict[str, Any]:
    """A minimal nested merge patch; ``null`` marks a removal. Overlapping keys are rejected."""
    patch: dict[str, Any] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise settings_error(13, "Expected KEY=VALUE", argument=assignment)
    changes = [(key, _parse_value(value, key)) for key, _, value in (a.partition("=") for a in assignments)]
    changes += [(key, None) for key in unsets]
    for key, value in changes:
        parts = _split_key(key)
        cursor = patch
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
            if not isinstance(cursor, dict):
                raise settings_error(13, "Settings keys overlap", key=key)
        if parts[-1] in cursor:
            raise settings_error(13, "Settings keys overlap", key=key)
        cursor[parts[-1]] = value
    if not patch:
        raise settings_error(13, "Nothing to set: give KEY=VALUE or --unset KEY")
    return patch


def _set(args: argparse.Namespace, settings: Any) -> int:
    from audiagentic.foundation.config.writer import write_settings_patch

    patch = build_patch(args.assignments, args.unset)
    project_root = settings.discover_project_root(args.project)
    result = write_settings_patch(args.scope, patch, project_root=project_root, dry_run=args.dry_run)
    shadowed = []
    if result.written:
        resolved = settings.resolve_settings(project=project_root, config_file=args.config_file)
        for key in result.keys:
            origin = resolved.origin(key)
            if origin is not None and origin.file not in (None, str(result.path)):
                shadowed.append({"key": key, "effective-from": origin.describe()})
    if args.as_json:
        print(json.dumps({
            "ok": True, "file": str(result.path), "scope": result.scope, "changed": result.changed,
            "written": result.written, "keys": list(result.keys), "backup": str(result.backup) if result.backup else None,
            "shadowed": shadowed, "diff": result.diff,
        }, indent=2))
        return 0
    if not result.changed:
        print(f"unchanged: {result.path}")
        return 0
    print(result.diff, end="" if result.diff.endswith("\n") else "\n")
    verb = "would change" if args.dry_run else "changed"
    print(f"{verb} {len(result.keys)} key(s) in {result.path}: {', '.join(result.keys)}")
    if result.backup:
        print(f"previous content kept at {result.backup}")
    for item in shadowed:
        print(f"note: {item['key']} is overridden by a higher scope: {item['effective-from']}")
    return 0


def _migrate(args: argparse.Namespace, settings: Any) -> int:
    """Move legacy configuration to its current home (see features.migration)."""
    from pathlib import Path

    from audiagentic.foundation.features import migration

    project_root = settings.discover_project_root(args.project)
    if project_root is None:
        raise settings_error(8, "Settings scope has no file here: run inside a project checkout")

    def emit(payload: dict[str, Any], text: str) -> int:
        print(json.dumps(payload, indent=2) if args.as_json else text)
        return 0

    try:
        if args.rollback:
            report = migration.rollback_provider_config_migration(project_root, Path(args.rollback))
            return emit({"ok": True, **report}, f"restored {len(report['restored'])}, kept {len(report['kept'])}"
                        + "".join(f"\n  kept: {item}" for item in report["kept"]))
        plan = migration.plan_provider_config_migration(project_root)
        conflicts = sorted(".".join(p) for p in plan.conflicts)
        if conflicts or plan.unknown:
            raise ValueError(f"conflicting existing values: {conflicts}; legacy keys with no home: {list(plan.unknown)}")
        if not args.apply:
            return emit(
                {"ok": True, "applied": False, "settings": len(plan.values), "local-state": len(plan.observations),
                 "sources": [str(p) for p in plan.sources]},
                f"{len(plan.values)} setting(s) and {len(plan.observations)} local-state value(s) from "
                f"{len(plan.sources)} legacy file(s) would move" + ("; run with --apply" if plan.sources else ""),
            )
        result = migration.apply_provider_config_migration(project_root)
        return emit({"ok": True, "applied": True, **result},
                    result["status"] + (f": manifest {result['manifest']}" if "manifest" in result else ""))
    except (ValueError, OSError) as error:
        if args.as_json:
            print(json.dumps({"ok": False, "message": str(error)}))
        else:
            print(f"migrate failed: {error}")
        return EXIT_INVALID
