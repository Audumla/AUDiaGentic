"""MA18 Step 5 — OpenCode ACP binding tests.

Prove that the OpenCode ACP adapter:
- Contains only launch/config differences (executable, args, cwd, env)
- Imports no orchestration/store/gateway
- Mutates no config file
"""
from __future__ import annotations

import ast
from unittest.mock import patch

from audiagentic.foundation.transports.acp import AcpLaunch

# Forbidden imports: the acp.py binding must not import these modules.
_FORBIDDEN_IMPORTS = frozenset((
    "audiagentic.components.agents",
    "audiagentic.runtime",
    "audiagentic.foundation.workflow",
    "audiagentic.foundation.toolchains.artifact_registry",
    "audiagentic.foundation.workflow.provider_cli",
    "audiagentic.components.providers.workflow.provider_cli",
))


def _get_imports_from_ast(source: str) -> set[str]:
    """Extract all import paths from AST."""
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class TestImportGuards:
    """OpenCode ACP module must not import orchestration or store modules."""

    def test_no_orchestration_imports(self):
        acp_source = (
            __import__(
                "audiagentic.components.providers.adapters.opencode.acp",
                fromlist=[""],
            )
            .__file__ or ""
        )
        # Read the source file to check AST imports
        with open(acp_source, encoding="utf-8") as f:
            source = f.read()

        imports = _get_imports_from_ast(source)
        for imp in imports:
            for forbidden in _FORBIDDEN_IMPORTS:
                assert not imp.startswith(forbidden), (
                    f"OpenCode ACP binding imports forbidden module: {imp} (forbidden prefix: {forbidden})"
                )

    def test_no_store_imports(self):
        acp_source = (
            __import__(
                "audiagentic.components.providers.adapters.opencode.acp",
                fromlist=[""],
            )
            .__file__ or ""
        )
        with open(acp_source, encoding="utf-8") as f:
            source = f.read()

        imports = _get_imports_from_ast(source)
        for imp in imports:
            assert "workflow" not in imp.lower(), (
                f"OpenCode ACP binding imports workflow: {imp}"
            )
            assert "store" not in imp.lower(), (
                f"OpenCode ACP binding imports store: {imp}"
            )


class TestBuildAcpLaunch:
    """build_acp_launch produces only launch params, mutates nothing."""

    def test_returns_acp_launch(self, tmp_path):
        with patch(
            "audiagentic.components.providers.adapters.cli.require_executable",
            return_value="opencode",
        ):
            from audiagentic.components.providers.adapters.opencode.acp import build_acp_launch

            launch = build_acp_launch(tmp_path)

        assert isinstance(launch, AcpLaunch)
        # executable is whatever require_executable returns (may be full path on some platforms)
        assert "opencode" in launch.executable
        assert "acp" in launch.args

    def test_model_override_via_env(self, tmp_path):
        with patch(
            "audiagentic.components.providers.adapters.cli.require_executable",
            return_value="opencode",
        ):
            from audiagentic.components.providers.adapters.opencode.acp import build_acp_launch

            launch = build_acp_launch(tmp_path, model_id="test-model")

        assert "OPENCODE_CONFIG_CONTENT" in launch.environment
        import json
        config = json.loads(launch.environment["OPENCODE_CONFIG_CONTENT"])
        assert config["model"] == "test-model"

    def test_enabled_providers_set_from_project_config(self, tmp_path):
        """Build acp_launch must include enabled_providers from project provider keys."""
        import json

        # Create project opencode config with a custom provider
        opencode_dir = tmp_path / ".opencode"
        opencode_dir.mkdir()
        (opencode_dir / "opencode.json").write_text(
            json.dumps({
                "provider": {
                    "audiagentic": {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "audiagentic",
                        "options": {
                            "baseURL": "http://127.0.0.1:42001/v1",
                            "apiKey": "{env:AUDIAGENTIC_RIG_API_KEY}",
                        },
                    }
                }
            })
        )

        with patch(
            "audiagentic.components.providers.adapters.cli.require_executable",
            return_value="opencode",
        ):
            from audiagentic.components.providers.adapters.opencode.acp import build_acp_launch

            launch = build_acp_launch(tmp_path, model_id="audiagentic/test-model")

        config = json.loads(launch.environment["OPENCODE_CONFIG_CONTENT"])
        assert "enabled_providers" in config
        assert "audiagentic" in config["enabled_providers"]

    def test_no_file_mutation(self, tmp_path):
        """build_acp_launch must not create or modify any files."""
        # Create a baseline of file tree before the call
        marker = tmp_path / "marker.txt"
        marker.write_text("before")

        with patch(
            "audiagentic.components.providers.adapters.cli.require_executable",
            return_value="opencode",
        ):
            from audiagentic.components.providers.adapters.opencode.acp import build_acp_launch

            build_acp_launch(tmp_path)

        # Marker unchanged, no new files in opencode config dir
        assert marker.read_text() == "before"
        opencode_dir = tmp_path / ".opencode"
        if opencode_dir.exists():
            contents = list(opencode_dir.iterdir())
            assert len(contents) == 0, (
                f"build_acp_launch created files in .opencode: {contents}"
            )


class TestProviderNeutral:
    """AcpLaunch carries no provider-specific orchestration state."""

    def test_launch_has_only_specified_fields(self, tmp_path):
        with patch(
            "audiagentic.components.providers.adapters.cli.require_executable",
            return_value="opencode",
        ):
            from audiagentic.components.providers.adapters.opencode.acp import build_acp_launch

            launch = build_acp_launch(tmp_path)

        # AcpLaunch only has: executable, args, environment
        fields = set(launch.__dataclass_fields__)
        assert fields == {"executable", "args", "environment"}, (
            f"AcpLaunch has unexpected fields: {fields}"
        )
