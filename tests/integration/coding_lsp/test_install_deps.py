"""Docker installation integration test for coding_lsp dependencies.

Run inside the Docker container built from Dockerfile.lsp-install-test.
Validates install, uninstall, and reinstall operations for all four LSP servers,
plus privilege/platform detection and system dependency state checks.

Sections:
  1. Toolchain availability
  2. Privilege + platform detection
  3. System dependency state (pre-installed in base image)
  4. PlatformRecipe resolution
  5. LSP detect_missing — before install
  6. LSP install — all 4 servers
  7. LSP verify binaries on PATH after install
  8. LSP detect_missing — after install (expect none)
  9. LSP uninstall — fast servers (pyright, typescript-language-server, clangd)
 10. LSP verify binaries gone after uninstall
 11. LSP detect_missing — after uninstall (expect 3 missing)
 12. LSP install/uninstall cycle — reinstall pyright, verify, uninstall again
"""
from __future__ import annotations

import shutil
import sys
import time

from audiagentic.components.optional.coding_lsp.lsp_dependencies import get_lsp_dependencies
from audiagentic.foundation.dependencies import (
    SYSTEM_DEPENDENCIES,
    detect_missing,
    install_dependencies,
    uninstall_dependencies,
)
from audiagentic.foundation.invoke.toolchains.detect import (
    detect_pkg_manager,
    platform_key,
    privilege_prefix,
)

ALL_SERVERS = ["pyright", "typescript-language-server", "rust-analyzer", "clangd"]
FAST_SERVERS = ["pyright", "typescript-language-server", "clangd"]

BINARY: dict[str, str] = {
    "pyright": "pyright-langserver",
    "typescript-language-server": "typescript-language-server",
    "rust-analyzer": "rust-analyzer",
    "clangd": "clangd",
}

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def _ok_count(results: dict) -> int:
    return sum(1 for r in results["results"] if r.get("ok"))


# ── 1. Toolchain availability ────────────────────────────────────────────────
section("1. Toolchain availability")
for tool in ("uv", "npm", "cargo", "apt-get", "git", "gh"):
    check(f"{tool} on PATH", shutil.which(tool) is not None)

# ── 2. Privilege + platform detection ───────────────────────────────────────
section("2. Privilege + platform detection")
prefix = privilege_prefix()
check("running as root (no sudo needed)", prefix == ())
pkg_mgr = detect_pkg_manager()
check(f"package manager detected: {pkg_mgr}", pkg_mgr is not None)
check("apt selected as package manager on Debian/Ubuntu", pkg_mgr == "apt")
check("platform_key() is 'linux'", platform_key() == "linux")

# ── 3. System dependency state ───────────────────────────────────────────────
section("3. System dependency state (pre-installed in base image)")
sys_missing = detect_missing(SYSTEM_DEPENDENCIES, ["git", "gh", "uv"])
check("git present in base image", "git" not in sys_missing)
check("gh present in base image", "gh" not in sys_missing)
check("uv present in base image", "uv" not in sys_missing)

# ── 4. PlatformRecipe resolution ─────────────────────────────────────────────
section("4. PlatformRecipe resolution")
deps = get_lsp_dependencies()
clangd_spec = deps["clangd"]
from audiagentic.foundation.invoke.context import InvocationContext

ctx = InvocationContext()
plan = clangd_spec.install.plan(ctx)
check("clangd PlatformRecipe resolves (apt path)", plan.status != "failed")

# ── 5. detect_missing before install ────────────────────────────────────────
section("5. detect_missing before install")
missing_before = detect_missing(deps, ALL_SERVERS)
print(f"  missing: {missing_before}")

# ── 6. Install all 4 LSP servers ────────────────────────────────────────────
section("6. LSP install — all 4 servers")
if not missing_before:
    print("  All already present — skipping install")
else:
    t0 = time.monotonic()
    result = install_dependencies(deps, missing_before)
    elapsed = time.monotonic() - t0
    for r in result["results"]:
        suffix = f"  error={r.get('error')}" if not r["ok"] else ""
        print(f"  {r['name']}: ok={r['ok']}{suffix}")
    print(f"  total install time: {elapsed:.1f}s")
    check(
        f"all {len(missing_before)} servers installed ok",
        _ok_count(result) == len(missing_before),
    )

# ── 7. Verify binaries on PATH after install ─────────────────────────────────
section("7. LSP verify binaries on PATH after install")
for server, binary in BINARY.items():
    check(f"{server} ({binary}) on PATH", shutil.which(binary) is not None)

# ── 8. detect_missing after install ──────────────────────────────────────────
section("8. detect_missing after install")
missing_after_install = detect_missing(deps, ALL_SERVERS)
print(f"  missing: {missing_after_install}")
check("no servers missing after install", missing_after_install == [])

# ── 9. Uninstall fast servers ────────────────────────────────────────────────
# rust-analyzer is excluded — compile from source takes >10 min, cycling adds no value.
section(f"9. LSP uninstall — fast servers {FAST_SERVERS}")
t0 = time.monotonic()
uninstall_result = uninstall_dependencies(deps, FAST_SERVERS)
elapsed = time.monotonic() - t0
for r in uninstall_result["results"]:
    suffix = f"  error={r.get('error')}" if not r["ok"] else ""
    print(f"  {r['name']}: ok={r['ok']}{suffix}")
print(f"  total uninstall time: {elapsed:.1f}s")
check(
    f"all {len(FAST_SERVERS)} fast servers uninstalled ok",
    _ok_count(uninstall_result) == len(FAST_SERVERS),
)

# ── 10. Verify binaries gone after uninstall ─────────────────────────────────
section("10. LSP verify binaries gone after uninstall")
for server in FAST_SERVERS:
    binary = BINARY[server]
    check(f"{server} ({binary}) absent after uninstall", shutil.which(binary) is None)
check(
    "rust-analyzer still present (not uninstalled)",
    shutil.which(BINARY["rust-analyzer"]) is not None,
)

# ── 11. detect_missing after uninstall ───────────────────────────────────────
section("11. detect_missing after uninstall")
missing_after_uninstall = detect_missing(deps, ALL_SERVERS)
print(f"  missing: {missing_after_uninstall}")
for server in FAST_SERVERS:
    check(f"{server} reported missing by detect_missing", server in missing_after_uninstall)
check(
    "rust-analyzer NOT reported missing",
    "rust-analyzer" not in missing_after_uninstall,
)

# ── 12. Install/uninstall cycle — pyright ────────────────────────────────────
section("12. Install/uninstall cycle — pyright")
t0 = time.monotonic()
reinstall = install_dependencies(deps, ["pyright"])
elapsed = time.monotonic() - t0
check("pyright reinstall ok", _ok_count(reinstall) == 1)
check("pyright binary on PATH after reinstall", shutil.which(BINARY["pyright"]) is not None)
print(f"  pyright reinstall time: {elapsed:.1f}s")

t0 = time.monotonic()
re_uninstall = uninstall_dependencies(deps, ["pyright"])
elapsed = time.monotonic() - t0
check("pyright second uninstall ok", _ok_count(re_uninstall) == 1)
check("pyright binary absent after second uninstall", shutil.which(BINARY["pyright"]) is None)
print(f"  pyright re-uninstall time: {elapsed:.1f}s")

missing_cycle_end = detect_missing(deps, ["pyright"])
check("pyright reported missing after cycle end", "pyright" in missing_cycle_end)

# ── Result ────────────────────────────────────────────────────────────────────
if FAILURES:
    print(f"\nFAILED ({len(FAILURES)}): {FAILURES}")
    sys.exit(1)
else:
    print("\nAll checks passed.")
