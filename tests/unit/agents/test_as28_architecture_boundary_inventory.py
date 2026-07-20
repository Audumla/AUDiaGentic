"""AS28 slice 0.5 — static/AST inventory of prohibited ACP-shaped agent dependencies.

These tests enumerate every prohibited ACP import/pattern that AS28 step 13 must
eliminate from the agents codebase. They initially assert ONLY known current
locations (allowlisted migration debt) so they do not falsely claim the
migration is done. In AS28 slice 4, these assertions are tightened to zero.

Prohibited dependencies tracked:
- AcpEvent, AcpLaunch, AcpResult, AcpSessionTransport (types from foundation.transports)
- on_event=, cancel_signal= (callback argument names in transport.prompt())
- raw .ext['acp'] reads (unmapped ACP protocol payload access)
- prepare_provider_acp_launch (public provider API)
- ProviderAcpLaunchResult (public provider contract type)
- build_acp_launch (provider-internal ACP launch builder)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# ── configuration ────────────────────────────────────────────────

_AGENTS_SRC = (
    Path(__file__).resolve()
    .parents[2]  # tests/
    .parent      # audiagentic repo root
    / "src"
    / "audiagentic"
    / "components"
    / "agents"
)

# Prohibited type imports (from foundation.transports or anywhere)
PROHIBITED_ACP_TYPES = [
    "AcpEvent",
    "AcpLaunch",
    "AcpResult",
    "AcpSessionTransport",
]

# Prohibited provider API symbols
PROHIBITED_PROVIDER_API = [
    "prepare_provider_acp_launch",
    "ProviderAcpLaunchResult",
]

# Prohibited callback argument names (passed to transport.prompt())
PROHIBITED_CALLBACK_ARGS = [
    "on_event=",
    "cancel_signal=",
]

# Prohibited raw ACP extension key reads
PROHIBITED_ACP_EXT_READS = [
    ".ext['acp']",
    '.ext["acp"]',
]

# Prohibited provider-internal function (should not be called from agents)
PROHIBITED_BUILDER_CALLS = [
    "build_acp_launch",
]

# ── allowlisted migration debt (slice 0.5 known current locations) ──

# These are the CURRENT known locations of ACP dependencies in agents code.
# Each entry maps a prohibited symbol to a set of allowed source files
# (relative to _AGENTS_SRC). In slice 4, this dict becomes empty.

ALLOWLISTED_MIGRATION_DEBT: dict[str, set[str]] = {
    # AcpLaunch — AS28 slice 4a: no longer used in agents code (OPEN path migrated)
    "AcpLaunch": set(),
    # AcpResult — return type of prompt_in_session / _prompt (slice 5+)
    "AcpResult": {
        "agents_gateway_sessions.py",
    },
    # AcpEvent — used in turn event callback (AS18, slice 5+)
    "AcpEvent": {
        "agents_gateway_turn_events.py",
    },
    # AcpSessionTransport — AS28 slice 4a: no longer imported by agents code
    "AcpSessionTransport": set(),
    # on_event= — callback wired in _prompt
    "on_event=": {
        "agents_gateway_sessions.py",
    },
    # cancel_signal= — cancel race in _prompt
    "cancel_signal=": {
        "agents_gateway_sessions.py",
    },
    # prepare_provider_acp_launch — called in session dispatch open path
    # prepare_provider_acp_launch — AS28 slice 4a: no longer used by agents code;
    # the OPEN path uses providers_api.prepare_provider_session_transport instead.
    "prepare_provider_acp_launch": set(),
    # ProviderAcpLaunchResult — not directly imported by agents, but used
    # indirectly through dispatch monkeypatching; no direct import expected.
    # This is intentionally NOT in the allowlist — if it appears, it's a
    # sign of deeper leakage.
}

# Raw .ext['acp'] reads are allowed only in turn_events (the projector)
ALLOWLISTED_ACP_EXT_READS = {
    "agents_gateway_turn_events.py",
}

# ── helpers ──────────────────────────────────────────────────────


def _collect_python_files() -> list[Path]:
    """Collect all .py files under agents_src."""
    return sorted(_AGENTS_SRC.rglob("*.py"))


def _file_relative(py_path: Path) -> str:
    return py_path.relative_to(_AGENTS_SRC).as_posix()


# ── AST-based import detection ───────────────────────────────────

class _ImportVisitor(ast.NodeVisitor):
    """Collect all import names from a file's AST."""

    def __init__(self) -> None:
        self.imports: set[str] = set()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports.add(name)
        # Also record the raw name (for `from x import AcpLaunch`)
        for alias in node.names:
            self.imports.add(alias.name)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports.add(name)


def _get_imports(py_path: Path) -> set[str]:
    """Return the set of imported names from a Python file."""
    try:
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    visitor = _ImportVisitor()
    visitor.visit(tree)
    return visitor.imports


# ── text-based pattern detection (for callback args and ext reads) ──

def _get_text_patterns(py_path: Path) -> dict[str, bool]:
    """Check for prohibited text patterns in a Python file."""
    try:
        source = py_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {p: False for p in PROHIBITED_CALLBACK_ARGS + PROHIBITED_ACP_EXT_READS}

    patterns: dict[str, bool] = {}
    for arg_name in PROHIBITED_CALLBACK_ARGS:
        # Match the keyword argument as a standalone token (e.g. on_event=)
        # Use word boundary to avoid matching 'session_event' for 'on_event'
        kwarg = arg_name.rstrip('=')
        pattern = r'\b' + re.escape(kwarg) + r'\s*='
        patterns[arg_name] = bool(re.search(pattern, source))

    for ext_read in PROHIBITED_ACP_EXT_READS:
        pattern = re.escape(ext_read)
        patterns[ext_read] = bool(re.search(pattern, source))

    return patterns


# ── tests ────────────────────────────────────────────────────────

class TestAcpTypeImports:
    """Characterize current ACP type import locations in agents code.

    Slice 0.5: assert only allowlisted migration debt.
    Slice 4: tighten to zero allowed imports.
    """

    def test_acp_type_imports_match_allowlist(self):
        """Every ACP type import must be in the allowlist.

        If a new file imports an Acp* type, it will appear here and the
        allowlist must be updated — or better, the new import should be
        rejected if migration has begun.
        """
        files = _collect_python_files()
        actual_debt: dict[str, set[str]] = {t: set() for t in PROHIBITED_ACP_TYPES}

        for py_path in files:
            rel_name = _file_relative(py_path)
            imports = _get_imports(py_path)
            for acp_type in PROHIBITED_ACP_TYPES:
                if acp_type in imports:
                    actual_debt[acp_type].add(rel_name)

        # Slice 0.5: verify allowlist covers all current debt
        for acp_type, allowed_files in ALLOWLISTED_MIGRATION_DEBT.items():
            if acp_type in actual_debt:
                unexpected = actual_debt[acp_type] - allowed_files
                assert not unexpected, (
                    f"{acp_type} imported from unallowlisted files: {unexpected}; "
                    f"update ALLOWLISTED_MIGRATION_DEBT or remove the import"
                )

        # Ensure no unexpected ACP types appear at all
        for acp_type in PROHIBITED_ACP_TYPES:
            if acp_type not in ALLOWLISTED_MIGRATION_DEBT:
                assert actual_debt.get(acp_type, set()) == set(), (
                    f"{acp_type} imported but NOT in allowlist — migration debt "
                    f"found in: {actual_debt[acp_type]}"
                )

    def test_open_path_no_acp_launch_or_session_transport(self):
        """AS28 slice 4a: agents_gateway_sessions.py OPEN path no longer
        imports AcpLaunch or AcpSessionTransport.

        The open_session method resolves a provider-neutral transport via
        providers_api.prepare_provider_session_transport. AcpLaunch and
        AcpSessionTransport must not cross the agent-session-open boundary.
        """
        sessions_py = _AGENTS_SRC / "agents_gateway_sessions.py"
        imports = _get_imports(sessions_py)
        leaked_open_types = {"AcpLaunch", "AcpSessionTransport"} & imports
        assert not leaked_open_types, (
            f"agents_gateway_sessions.py OPEN path imports ACP types: {leaked_open_types}; "
            "must use providers_api.prepare_provider_session_transport instead"
        )


class TestProviderApiImports:
    """Characterize current provider API ACP symbol imports in agents code.

    Slice 0.5: assert only allowlisted migration debt.
    Slice 4: tighten to zero allowed imports.
    """

    def test_provider_api_acp_symbols_match_allowlist(self):
        """Every use of prepare_provider_acp_launch or ProviderAcpLaunchResult
        in agents code must be in the allowlist.
        """
        files = _collect_python_files()
        actual_debt: dict[str, set[str]] = {s: set() for s in PROHIBITED_PROVIDER_API}

        for py_path in files:
            rel_name = _file_relative(py_path)
            imports = _get_imports(py_path)
            for symbol in PROHIBITED_PROVIDER_API:
                if symbol in imports:
                    actual_debt[symbol].add(rel_name)

        # Also check text-level usage (not just imports — could be called without import)
        for py_path in files:
            rel_name = _file_relative(py_path)
            try:
                source = py_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for symbol in PROHIBITED_PROVIDER_API:
                if symbol in source and rel_name not in actual_debt[symbol]:
                    # Only count if it's actually used (not just a comment)
                    if not _is_comment_only(symbol, source):
                        actual_debt[symbol].add(rel_name)

        for symbol, allowed_files in ALLOWLISTED_MIGRATION_DEBT.items():
            if symbol in actual_debt:
                unexpected = actual_debt[symbol] - allowed_files
                assert not unexpected, (
                    f"{symbol} used in unallowlisted files: {unexpected}"
                )

    # ── TODO: AS28 slice 4 boundary gate ──
    # In slice 4:
    # def test_no_provider_api_acp_symbols_in_agents(self):
    #     files = _collect_python_files()
    #     for py_path in files:
    #         source = py_path.read_text(encoding="utf-8")
    #         for symbol in PROHIBITED_PROVIDER_API:
    #             assert symbol not in source, (
    #                 f"{symbol} found in {_file_relative(py_path)}"
    #             )


def _is_comment_only(symbol: str, source: str) -> bool:
    """Rough check: is the symbol only in comments?"""
    for line in source.splitlines():
        stripped = line.strip()
        if symbol in stripped and not stripped.startswith("#"):
            return False
    return True


class TestCallbackArgumentPatterns:
    """Characterize current on_event=/cancel_signal= usage in agents code.

    Slice 0.5: assert only allowlisted migration debt.
    Slice 4: tighten to zero allowed uses.
    """

    def test_callback_args_match_allowlist(self):
        """on_event= and cancel_signal= keyword arguments must be in the allowlist.

        These are the ACP callback patterns that AS28 replaces with
        ObservationSink and SessionControlAction.CANCEL_TURN.
        """
        files = _collect_python_files()
        actual_debt: dict[str, set[str]] = {arg: set() for arg in PROHIBITED_CALLBACK_ARGS}

        for py_path in files:
            rel_name = _file_relative(py_path)
            patterns = _get_text_patterns(py_path)
            for arg in PROHIBITED_CALLBACK_ARGS:
                if patterns.get(arg, False):
                    actual_debt[arg].add(rel_name)

        for arg, allowed_files in ALLOWLISTED_MIGRATION_DEBT.items():
            if arg in actual_debt:
                unexpected = actual_debt[arg] - allowed_files
                assert not unexpected, (
                    f"{arg} used in unallowlisted files: {unexpected}"
                )

    # ── TODO: AS28 slice 4 boundary gate ──
    # In slice 4:
    # def test_no_callback_args_in_agents(self):
    #     files = _collect_python_files()
    #     for py_path in files:
    #         patterns = _get_text_patterns(py_path)
    #         for arg in PROHIBITED_CALLBACK_ARGS:
    #             assert not patterns.get(arg, False), (
    #                 f"{arg} found in {_file_relative(py_path)}"
    #             )


class TestAcpExtReads:
    """Characterize current raw .ext['acp'] reads in agents code.

    Slice 0.5: assert only allowlisted migration debt (turn_events projector).
    Slice 4: tighten to zero allowed reads — all ACP extension parsing must
    move behind the provider adapter boundary.
    """

    def test_acp_ext_reads_match_allowlist(self):
        """Raw .ext['acp'] / .ext["acp"] reads must be in the allowlist.

        After AS28 migration, only TransportObservation with bounded declared
        attributes (tool_call_id, tool_status) should be read — never raw ACP
        extension payloads.
        """
        files = _collect_python_files()
        actual_files: set[str] = set()

        for py_path in files:
            rel_name = _file_relative(py_path)
            patterns = _get_text_patterns(py_path)
            for ext_read in PROHIBITED_ACP_EXT_READS:
                if patterns.get(ext_read, False):
                    actual_files.add(rel_name)

        unexpected = actual_files - ALLOWLISTED_ACP_EXT_READS
        assert not unexpected, (
            f"Raw .ext['acp'] reads in unallowlisted files: {unexpected}; "
            f"only allowed in: {ALLOWLISTED_ACP_EXT_READS}"
        )

    # ── TODO: AS28 slice 4 boundary gate ──
    # In slice 4:
    # def test_no_acp_ext_reads_in_agents(self):
    #     files = _collect_python_files()
    #     for py_path in files:
    #         patterns = _get_text_patterns(py_path)
    #         for ext_read in PROHIBITED_ACP_EXT_READS:
    #             assert not patterns.get(ext_read, False), (
    #                 f"{ext_read} found in {_file_relative(py_path)}"
    #             )


class TestMigrationDebtInventory:
    """Aggregate migration debt summary — for visibility.

    This test always passes but prints the current state of ACP migration
    debt in the agents codebase. It serves as a dashboard for slice 0.5 → 4.
    """

    def test_migration_debt_summary(self, capsys):
        """Print the current inventory of ACP-shaped dependencies."""
        files = _collect_python_files()

        # Collect actual debt
        type_debt: dict[str, set[str]] = {t: set() for t in PROHIBITED_ACP_TYPES}
        api_debt: dict[str, set[str]] = {s: set() for s in PROHIBITED_PROVIDER_API}
        callback_debt: dict[str, set[str]] = {a: set() for a in PROHIBITED_CALLBACK_ARGS}
        ext_read_files: set[str] = set()

        for py_path in files:
            rel_name = _file_relative(py_path)
            imports = _get_imports(py_path)

            for t in PROHIBITED_ACP_TYPES:
                if t in imports:
                    type_debt[t].add(rel_name)

            try:
                source = py_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            for s in PROHIBITED_PROVIDER_API:
                if s in source and not _is_comment_only(s, source):
                    api_debt[s].add(rel_name)

            patterns = _get_text_patterns(py_path)
            for a in PROHIBITED_CALLBACK_ARGS:
                if patterns.get(a, False):
                    callback_debt[a].add(rel_name)

            for ext_read in PROHIBITED_ACP_EXT_READS:
                if patterns.get(ext_read, False):
                    ext_read_files.add(rel_name)

        # Print summary (visible in verbose test output)
        total_debt = 0
        lines = ["\n=== AS28 Migration Debt Summary ==="]
        lines.append(f"{'Category':<30} {'Symbol':<35} {'Files':}")
        lines.append("-" * 80)

        for symbol, files_set in type_debt.items():
            count = len(files_set)
            total_debt += count
            status = "ALLOWLISTED" if symbol in ALLOWLISTED_MIGRATION_DEBT else "UNEXPECTED"
            lines.append(f"AcpTypeImport{'':<16} {symbol:<35} [{status}] {sorted(files_set)}")

        for symbol, files_set in api_debt.items():
            count = len(files_set)
            total_debt += count
            status = "ALLOWLISTED" if symbol in ALLOWLISTED_MIGRATION_DEBT else "UNEXPECTED"
            lines.append(f"ProviderApiSymbol{'':<13} {symbol:<35} [{status}] {sorted(files_set)}")

        for arg, files_set in callback_debt.items():
            count = len(files_set)
            total_debt += count
            status = "ALLOWLISTED" if arg in ALLOWLISTED_MIGRATION_DEBT else "UNEXPECTED"
            lines.append(f"CallbackArg{'':<20} {arg:<35} [{status}] {sorted(files_set)}")

        ext_count = len(ext_read_files)
        total_debt += ext_count
        lines.append(
            f"AcpExtRead{'':<21} .ext['acp']{'':<19} "
            f"{'[ALLOWLISTED]' if ext_read_files.issubset(ALLOWLISTED_ACP_EXT_READS) else '[UNEXPECTED]'} "
            f"{sorted(ext_read_files)}"
        )

        lines.append("-" * 80)
        lines.append(f"Total debt items: {total_debt}")
        lines.append(
            "TODO: In AS28 slice 4, all categories should be empty (zero)."
        )
        summary = "\n".join(lines)
        print(summary)

        # Assert that allowlist is consistent with actual debt
        for symbol in PROHIBITED_ACP_TYPES + PROHIBITED_PROVIDER_API + PROHIBITED_CALLBACK_ARGS:
            if symbol not in ALLOWLISTED_MIGRATION_DEBT:
                combined = type_debt.get(symbol, set()) | api_debt.get(symbol, set()) | callback_debt.get(symbol, set())
                assert combined == set(), (
                    f"Unexpected ACP dependency found for {symbol}: {combined}; "
                    f"add to allowlist or remove the dependency"
                )
