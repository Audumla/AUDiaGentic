#!/usr/bin/env python3
"""Single consolidated test entrypoint for AUDiaGentic.

Runs the entire test suite in the right execution mode for the current
environment, instead of forcing the developer to remember a dozen markers and
Make targets.

Execution model
---------------
Docker available (auto-detected)
    Windows/Mac is just the launch pad. Docker does ALL the work:
    - the clean suite image runs every non-mutating test inside Linux
    - each recipe image runs its mutating install/uninstall scenario in isolation
    Running tests again on the host would be a redundant pass over the same
    tests in a worse environment, so the host phase is skipped entirely.

No Docker daemon
    Fall back to the host for what it can safely run: the non-mutating suite
    in parallel (``-n auto --dist loadgroup``). ``mutates_host`` tests auto-skip
    because they need a Linux package manager. The ``no_parallel`` enforcement
    hook in ``tests/conftest.py`` keeps stateful modules serial-on-one-worker.

Usage
-----
    python tests/run_all.py              # host suite; + docker if daemon present
    python tests/run_all.py --fast       # host suite only, never touch docker
    python tests/run_all.py --no-docker  # alias for --fast
    python tests/run_all.py --docker      # require docker; fail if no daemon
    python tests/run_all.py --lsp-install # also run the slow (~15 min) clean-room
                                          # LSP install image (rust-analyzer compile)
    python tests/run_all.py --host-docker-tests  # also run host daemon-driven docker tests
    python tests/run_all.py -k expr ...   # extra args are forwarded to the host pytest

Exit code is non-zero if any executed phase fails.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DOCKER_DIR = REPO_ROOT / "tests" / "docker"

BASE_IMAGE = "audia-test-base:latest"

# Docker image registry. The historical per-scenario sprawl is collapsed only
# where it is SAFE to do so:
#   - the clean, NON-mutating suite is consolidated into one image (whole suite,
#     not a hand-picked subset);
#   - the three clean-room packaging checks merge into one.
# The mutating images are kept ISOLATED on purpose: each exercises a real MCP
# install RECIPE and asserts install/uninstall from a clean toolchain. Sharing a
# container would leak server/CLI state between tests and invalidate those
# assertions, so each gets its own fresh image (mirroring run_provider_cli_isolated).
#
# Fields: tag, dockerfile, slow (opt-in / very slow), mutating (recipe-isolated).
class Img:
    def __init__(self, tag: str, dockerfile: str, *, slow: bool = False, note: str = ""):
        self.tag = tag
        self.dockerfile = dockerfile
        self.slow = slow
        self.note = note


SUITE = Img("audiagentic-test:latest", "Dockerfile.test", note="clean non-mutating suite")
PACKAGING = Img("audia-packaging:latest", "Dockerfile.packaging", note="clean-room wheel validation")

# Recipe / mutating images — isolated, run real install recipes.
RECIPE_IMAGES = [
    Img("audia-provider-cli-test:latest", "Dockerfile.provider-cli-test", note="provider CLI provisioning recipe"),
    Img("audia-provider-cli-comprehensive:latest", "Dockerfile.provider-cli-comprehensive", note="provider CLI comprehensive recipe"),
    Img("audiagentic-provider-lifecycle-e2e:latest", "Dockerfile.provider-lifecycle-e2e", note="provider full lifecycle recipe"),
    Img("audia-provider-lsp-e2e:latest", "Dockerfile.provider-lsp-e2e", note="provider LSP install recipe"),
    Img("audia-mcp-tools-e2e:latest", "Dockerfile.mcp-tools-e2e", note="LSP MCP tools (consumes baked servers)"),
    Img("audiagentic-gateway-crash-matrix:local", "Dockerfile.gateway-crash-matrix", note="SH07 real-subprocess crash/recovery matrix"),
    Img("audiagentic-gateway-opencode:local", "Dockerfile.gateway-opencode", note="real npm-CLI-provider gateway dispatch (dynamic discovery)"),
    Img("audiagentic-gateway-concurrency:local", "Dockerfile.gateway-concurrency", note="real concurrent gateway load + negative paths"),
    Img("audiagentic-gateway-pi-smoke:local", "Dockerfile.gateway-pi-smoke", note="SH16 real Pi CLI + embedded rig gateway dispatch"),
    Img("audiagentic-pi-rpc-tap-e2e:local", "Dockerfile.pi-rpc-tap-e2e", note="AS40 real pi-acp RPC tee shim, tapped conversational turn"),
    Img("audiagentic-pi-acp-resume-e2e:local", "Dockerfile.pi-acp-resume-e2e", note="AS49 real pi-acp session/load resume after process death"),
]
# Very slow clean-toolchain install (rust-analyzer compiles ~15 min) — opt-in.
LSP_INSTALL = Img("audiagentic-lsp-install-test:latest", "Dockerfile.lsp-install-test", slow=True, note="clean LSP install recipe (rust compile)")


def _c(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def banner(text: str) -> None:
    print()
    print(_c(f"=== {text} ", "1;36") + _c("=" * max(0, 60 - len(text)), "36"))


def run(cmd: list[str], **kw) -> int:
    print(_c("$ " + " ".join(cmd), "2"))
    return subprocess.run(cmd, cwd=REPO_ROOT, **kw).returncode


def docker_daemon_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=20
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def host_phase(extra: list[str]) -> int:
    """Run all non-Docker-daemon tests in parallel as one safe command."""
    banner("HOST suite (parallel, capped xdist --dist loadgroup)")
    workers = os.environ.get("AUDIAGENTIC_XDIST_WORKERS", "8")
    cmd = [
        sys.executable, "-m", "pytest",
        "-n", workers, "--dist", "loadgroup",
        "-m", "not docker and not opt_in",  # exclude daemon-driven and explicit opt-in tests
        *extra,
    ]
    return run(cmd)


def host_sensitive_smoke_phase() -> int:
    """Run a tiny host-only smoke layer for local toolchain breakage.

    Docker images validate packaged behavior in clean Linux containers, but they
    cannot catch host PATH / shim corruption on the actual developer machine.
    Keep this phase tiny and deterministic.
    """
    failures = 0

    banner("HOST-sensitive smoke: MCP imports / tool listing")
    if run([sys.executable, "tests/docker/_server_smoke.py"]) != 0:
        failures += 1

    banner("HOST-sensitive smoke: real pyright initialize")
    if run([sys.executable, "-m", "pytest", "tests/integration/coding_lsp/test_pyright_bridge.py", "-q", "-k", "test_pyright_initialize"]) != 0:
        failures += 1

    return 1 if failures else 0


def build_image(img: Img) -> int:
    return run([
        "docker", "build", "-f", str(DOCKER_DIR / img.dockerfile), "-t", img.tag, "."
    ])


def build_and_run(img: Img, failures: list[str]) -> None:
    banner(f"DOCKER: {img.tag}  ({img.note})")
    if build_image(img) != 0:
        failures.append(f"{img.tag}:build")
    elif run(["docker", "run", "--rm", img.tag]) != 0:
        failures.append(img.tag)


def docker_phase(include_lsp_install: bool, *, include_host_docker_tests: bool) -> int:
    """Build the image set once and run the in-container suites.

    Mutating recipe images run in their own fresh containers so install/uninstall
    state never leaks between tests.
    """
    failures: list[str] = []

    banner("DOCKER: build base image")
    if build_image(Img(BASE_IMAGE, "Dockerfile.test-base")) != 0:
        print(_c("base image build failed - aborting docker phase", "1;31"))
        return 1

    build_and_run(SUITE, failures)
    build_and_run(PACKAGING, failures)
    for img in RECIPE_IMAGES:
        build_and_run(img, failures)

    if include_lsp_install:
        build_and_run(LSP_INSTALL, failures)
    else:
        print(_c("\nSkipping slow clean-room LSP install image "
                 "(rust-analyzer compile ~15 min) - pass --lsp-install to include it.", "33"))

    if include_host_docker_tests:
        # Host-side tests that drive a daemon themselves (mark.docker). Keep
        # opt-in: they are slower and validate the host/daemon boundary rather
        # than the main in-container regression path.
        banner("DOCKER: host-side daemon tests (mark.docker)")
        if run([sys.executable, "-m", "pytest", "-m", "docker", "-p", "no:cacheprovider"]) != 0:
            failures.append("host-docker-tests")
    else:
        print(_c("\nSkipping host-side daemon tests (mark.docker) - pass --host-docker-tests to include them.", "33"))

    if failures:
        print(_c(f"\nDocker phase failures: {', '.join(failures)}", "1;31"))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fast", "--no-docker", dest="fast", action="store_true",
                       help="host suite only; never build or run Docker")
    group.add_argument("--docker", dest="require_docker", action="store_true",
                       help="require a Docker daemon; fail if unavailable")
    parser.add_argument("--lsp-install", action="store_true",
                        help="also run the slow clean-room LSP install image (~15 min)")
    parser.add_argument("--host-docker-tests", action="store_true",
                        help="also run host daemon-driven docker tests (mark.docker)")
    args, extra = parser.parse_known_args(argv)

    if args.fast:
        # Explicit opt-out: run on the host, never touch Docker.
        return host_phase(extra)

    if docker_daemon_available():
        # Docker is available: let it do ALL the work. The suite image already
        # runs every non-mutating test, and the recipe images cover mutating ones.
        # There is no point also running on the Windows/Mac host — that is a
        # redundant pass over the same tests in a worse environment.
        #
        # Exception: keep a tiny host-sensitive smoke layer for issues Docker
        # can never see, like broken Windows PATH shims for local MCP/LSP CLIs.
        print(_c("Docker daemon detected - running host-sensitive smokes plus full container suite.", "36"))
        host_rc = host_sensitive_smoke_phase()
        docker_rc = docker_phase(
            include_lsp_install=args.lsp_install,
            include_host_docker_tests=args.host_docker_tests,
        )
        return 1 if host_rc or docker_rc else 0

    # No Docker daemon. Fall back to the host for what it can run (non-mutating).
    msg = "No Docker daemon reachable"
    if args.require_docker:
        print(_c(f"\n{msg} but --docker was requested - failing.", "1;31"))
        return 1
    print(_c(f"\n{msg} - falling back to host suite (non-mutating only).", "33"))
    return host_phase(extra)


if __name__ == "__main__":
    raise SystemExit(main())
