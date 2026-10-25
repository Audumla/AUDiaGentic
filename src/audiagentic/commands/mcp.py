"""Keyword CLI protocol adapter. Project and Providers own all domain policy."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from audiagentic.foundation.io import load_yaml_file


def _help(key: str) -> str:
    source = Path(__file__).resolve().parents[1] / "config/components/project/onboarding-cli.yaml"
    return load_yaml_file(source)[key]


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int | None:
    """Translate one parsed command; None selects the existing module route."""
    tail = list(args.tail)
    if getattr(args, "management_help", False):
        print(_help(args.command))
        return 0
    if args.command == "help":
        print(_help("root"))
        return 0
    if args.command == "mcp" and tail and tail[0] == "--":
        if len(tail) < 2:
            parser.error("mcp -- requires MODULE")
        args.module, args.module_args = tail[1], tail[2:]
        return None
    if (
        args.command == "mcp"
        and tail
        and tail[0] not in {"list", "help", "install", "-h", "--help"}
    ):
        if len(tail) < 2 or tail[1] != "help":
            args.module, args.module_args = tail[0], tail[1:]
            return None
    if not tail or tail in (["help"], ["-h"], ["--help"]):
        print(_help(args.command))
        return 0
    if tail == ["install", "help"] and args.command == "mcp":
        print(_help("install"))
        return 0

    install = args.command == "mcp" and tail[0] == "install"
    if install:
        if len(tail) < 4 or tail[2] != "harness":
            parser.error("expected: mcp install MCP_ID harness ID[,ID...]")
        values = tail[3].split(",")
        if any(not value.strip() for value in values):
            parser.error("harness list contains an empty ID")
        harness_ids = list(dict.fromkeys(value.strip() for value in values))
        mcp_id, rest = tail[1], tail[4:]
    elif tail[0] == "list":
        mcp_id, rest = None, tail[1:]
    elif len(tail) >= 2 and tail[1] == "help":
        mcp_id, rest = tail[0], tail[2:]
    else:
        parser.error("expected list, ID help, or mcp install MCP_ID harness ID[,ID...]")

    options: dict[str, str | bool] = {}
    while rest:
        key, *rest = rest
        allowed = {"project", "component-profile", "output"}
        if install:
            allowed |= {"config", "dry-run", "non-interactive"}
        if key not in allowed or key in options:
            parser.error(f"unknown or repeated clause: {key}")
        if key in {"dry-run", "non-interactive"}:
            options[key] = True
        else:
            if not rest:
                parser.error(f"{key} requires a value")
            options[key], *rest = rest
    if options.get("output", "text") not in {"text", "json"}:
        parser.error("output must be text or json")
    if args.project is not None and "project" in options:
        parser.error("project supplied both as a root option and a keyword")
    if args.component_profile is not None and "component-profile" in options:
        parser.error("component profile supplied twice")
    root_value = options.get("project", args.project)
    root = Path(str(root_value)).resolve() if root_value else None
    profile = options.get("component-profile", args.component_profile)
    if profile:
        os.environ["AUDIAGENTIC_COMPONENT_PROFILE"] = str(profile)
    if root:
        os.environ["AUDIAGENTIC_REPO_ROOT"] = str(root)

    if args.command == "harness":
        from audiagentic.components.providers import providers_api

        rows = [entry.to_mapping() for entry in providers_api.list_harness_mcp_targets()]
        if mcp_id is not None:
            rows = [entry for entry in rows if entry["provider_id"] == mcp_id]
            if not rows:
                parser.error("unknown harness ID")
        result = rows[0] if mcp_id is not None else rows
    else:
        from audiagentic.components.project import project_api

        if install:
            from audiagentic.foundation.paths.project import find_project_root

            root = root or find_project_root()
            if root is None:
                parser.error("installation requires an existing project or project PATH")
            result = project_api.install_mcp(
                root,
                mcp_id=mcp_id,
                harness_ids=harness_ids,
                dry_run=bool(options.get("dry-run", False)),
                config_file=Path(str(options["config"])) if "config" in options else None,
                non_interactive=bool(options.get("non-interactive", False)),
            )
        else:
            result = project_api.list_mcp_catalog(root, mcp_id)
    print(
        json.dumps(
            result,
            indent=None if options.get("output") == "json" else 2,
            ensure_ascii=options.get("output") == "json",
        )
    )
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1
