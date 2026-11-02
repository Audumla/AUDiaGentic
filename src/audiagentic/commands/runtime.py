"""Keyword CLI for the service runtime: protocol adapter only (behaviour in components/project/runtime)."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.cli_io import print_error, print_json, print_message

_HELP = """Runtime commands (keyword syntax):
  audiagentic runtime status [root PATH]
  audiagentic runtime install (wheel PATH | ref GITREF) [extras acp,a2a] [restart yes] [root PATH] [project PATH]
  audiagentic runtime prune [keep N] [root PATH]
  audiagentic runtime rollback [restart yes] [root PATH]
  audiagentic runtime help

The gateway and the MCP servers run from <runtime>/current, a symlink to one immutable,
non-editable venv <runtime>/<version>-<id>; no git worktree is ever load-bearing. The runtime
folder defaults to a sibling of the AUDiaGentic home (<home>/../runtime).

install builds a wheel of GITREF from a clean git export (or takes WHEEL), installs it into a new
folder, imports the gateway from that folder as a health check, and only then repoints `current`
(keeping the old target as `previous`). A failed build or check leaves `current` untouched.
install also prunes: it keeps `current`, `previous` and the 2 newest other folders, removes the
rest and the build folder, and never removes a folder a running process uses (`prune keep N` does it on demand).
rollback swaps `current` and `previous` after the same health check.
`restart yes` asks the container supervisor to restart only the gateway (it does not touch
the MCP servers: running clients keep the old runtime until they reconnect).
Options beginning with -- are not accepted; use the keywords shown above."""

_ALLOWED = {"status": {"root"}, "install": {"wheel", "ref", "extras", "restart", "root", "project"},
            "rollback": {"restart", "root"}, "prune": {"keep", "root"}}


def _clauses(rest: list[str], allowed: set[str]) -> dict[str, str] | None:
    clauses: dict[str, str] = {}
    while rest:
        key, *rest = rest
        if key not in allowed or key in clauses or not rest:
            return None
        clauses[key], *rest = rest
    return clauses


def dispatch_keyword(tokens: list[str]) -> int:
    if not tokens or tokens == ["help"]:
        print_message(_HELP)
        return 0
    if tokens[0] not in _ALLOWED or any(token.startswith("--") for token in tokens):
        print_error("Invalid runtime syntax. Run: audiagentic runtime help")
        return 2
    verb = tokens[0]
    clauses = _clauses(tokens[1:], _ALLOWED[verb])
    if (clauses is None or clauses.get("restart", "yes") != "yes"
            or (verb == "install" and ("wheel" in clauses) == ("ref" in clauses))):
        print_error(f"Invalid runtime {verb} syntax. Run: audiagentic runtime help")
        return 2

    from audiagentic.components.project.runtime import install as runtime
    from audiagentic.foundation.paths.home import audiagentic_home

    root = Path(clauses["root"]).expanduser().resolve() if "root" in clauses else runtime.default_root(audiagentic_home())
    try:
        if verb == "status":
            result = runtime.status(root)
        elif verb == "prune":
            if not clauses.get("keep", "2").isdigit():
                print_error("Invalid runtime prune syntax. Run: audiagentic runtime help")
                return 2
            result = runtime.prune(root, keep=int(clauses.get("keep", "2")))
        else:
            if verb == "rollback":
                result = runtime.rollback(root)
            else:
                from audiagentic.foundation.paths.project import discover_checkout_root

                extras = tuple(x for x in clauses.get("extras", ",".join(runtime.DEFAULT_EXTRAS)).split(",") if x)
                if "wheel" in clauses:
                    wheel = Path(clauses["wheel"]).expanduser().resolve()
                else:
                    repo = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
                    if repo is None:
                        print_error("Not inside a git repository. Give project PATH or use wheel PATH.")
                        return 2
                    build_dir = root / ".build"
                    build_dir.mkdir(parents=True, exist_ok=True)
                    wheel = runtime.wheel_from_ref(repo, clauses["ref"], build_dir)
                result = runtime.install(root, wheel, extras=extras)
            if "restart" in clauses:
                result["gateway-restart-requested"] = runtime.request_gateway_restart()
    except runtime.RuntimeInstallError as error:
        print_error(f"runtime {verb} refused: {error}")
        return 1
    print_json(result, sort_keys=True)
    return 0
