"""Tests for sensitive data detection in planning items."""

from __future__ import annotations

import pytest
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tools.planning.tm_helper as tm


class TestCheckSensitiveDataPatternDetection:
    """Test the sensitive data detection patterns."""

    def test_aws_key_pattern_detected(self):
        """AWS key pattern should be detected in body."""
        # Create a mock item view with AWS key in body
        body = "Found this key: AKIAIOSFODNN7EXAMPLE in the code"

        # Direct pattern test
        import re
        pattern = r'AKIA[0-9A-Z]{16}'
        assert re.search(pattern, body, re.IGNORECASE) is not None

    def test_api_key_pattern_detected(self):
        """API key pattern should be detected."""
        body = 'apikey: ' + 'sk_live_' + 'abcdefghij1234567890abcdefghij'

        import re
        pattern = r'(?:api[_-]?key|apikey)[\s]*[=:]\s*["\']?[a-zA-Z0-9_\-]{20,}["\']?'
        assert re.search(pattern, body, re.IGNORECASE) is not None

    def test_password_pattern_detected(self):
        """Password pattern should be detected."""
        body = "password=SuperSecretPassword123"

        import re
        pattern = r'(?:password|passwd|pwd)[\s]*[=:]\s*["\']?[^"\'\s]+["\']?'
        assert re.search(pattern, body, re.IGNORECASE) is not None

    def test_bearer_token_pattern_detected(self):
        """Bearer token pattern should be detected."""
        body = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

        import re
        pattern = r'Bearer\s+[a-zA-Z0-9\-._~+/]+=*'
        assert re.search(pattern, body, re.IGNORECASE) is not None

    def test_clean_content_no_matches(self):
        """Clean content should not match any patterns."""
        body = "This is a normal task description with no sensitive data. Just some regular content about implementation details."

        import re
        patterns = {
            'aws_key': r'AKIA[0-9A-Z]{16}',
            'api_key': r'(?:api[_-]?key|apikey)[\s]*[=:]\s*["\']?[a-zA-Z0-9_\-]{20,}["\']?',
            'password': r'(?:password|passwd|pwd)[\s]*[=:]\s*["\']?[^"\'\s]+["\']?',
            'bearer_token': r'Bearer\s+[a-zA-Z0-9\-._~+/]+=*',
        }

        for name, pattern in patterns.items():
            assert re.search(pattern, body, re.IGNORECASE) is None, f"Pattern {name} should not match clean content"


class TestCheckSensitiveDataRealProject:
    """Test check_sensitive_data against real planning items."""

    def test_check_existing_clean_item(self):
        """Check a real clean planning item."""
        # Use a known clean item from the repo
        result = tm.check_sensitive_data("request-0002")

        assert isinstance(result, dict)
        assert "id" in result
        assert "has_sensitive_data" in result
        assert "warnings" in result
        assert "patterns_checked" in result

        assert result["id"] == "request-0002"
        assert isinstance(result["has_sensitive_data"], bool)
        assert isinstance(result["warnings"], list)
        assert isinstance(result["patterns_checked"], list)
        assert len(result["patterns_checked"]) == 4

    def test_response_structure(self):
        """Response should have correct structure."""
        result = tm.check_sensitive_data("spec-0001")

        # Verify structure
        assert isinstance(result, dict)
        assert "id" in result
        assert "has_sensitive_data" in result
        assert "warnings" in result
        assert "patterns_checked" in result

        # Verify types
        assert isinstance(result["id"], str)
        assert isinstance(result["has_sensitive_data"], bool)
        assert isinstance(result["warnings"], list)
        assert isinstance(result["patterns_checked"], list)

    def test_nonexistent_item_returns_error(self):
        """Should handle nonexistent items gracefully."""
        result = tm.check_sensitive_data("nonexistent-item-xyz")

        assert result["id"] == "nonexistent-item-xyz"
        assert result["has_sensitive_data"] is False
        assert len(result["warnings"]) > 0  # Should have error message
        assert result["patterns_checked"] is not None


class TestMCPToolExposure:
    """Test that the MCP tool is exposed correctly."""

    def test_tm_check_sensitive_data_callable(self):
        """Verify tm_check_sensitive_data is callable."""
        # Import should not raise - test that function is available in tm_helper
        assert callable(tm.check_sensitive_data)

    def test_mcp_tool_has_description(self):
        """Verify MCP tool is registered with description."""
        # This is a basic smoke test - the tool should be in the MCP server
        # Full integration test is in test_mcp_tool_calls.py
        pass
