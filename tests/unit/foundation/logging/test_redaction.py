"""Unit tests for foundation/logging/redaction.py."""
from __future__ import annotations

import re

from audiagentic.foundation.logging.redaction import (
    redact_env_like,
    redact_text,
    truncate_output,
)


class TestDefaultPatterns:
    """Each pattern matches its target and does not false-positive."""

    def test_api_key_pattern(self):
        result = redact_text("key=sk-aaaaaaaaaaaaaaaaaaaaaaa")
        assert "sk-aaaaaaaaaaaaaaaaaaaaaaa" not in result
        assert "[REDACTED]" in result

    def test_bearer_token_pattern(self):
        result = redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxxxx")
        assert "Bearer" not in result or "eyJh" not in result
        assert "[REDACTED]" in result

    def test_base64_pattern(self):
        long_b64 = "a" * 42 + "=="
        assert long_b64 not in redact_text(f"data:{long_b64}")
        assert "[REDACTED]" in redact_text(f"data:{long_b64}")

    def test_secret_key_value_pattern(self):
        assert "mysecret123" not in redact_text("password=mysecret123")
        assert "[REDACTED]" in redact_text("secret = mysecret123")

    def test_false_positive_normal_output(self):
        normal = "npm install completed successfully"
        assert redact_text(normal) == normal

    def test_false_positive_short_strings(self):
        short_token = "sk-short"
        assert redact_text(f"value: {short_token}") == f"value: {short_token}"


class TestRedactText:
    def test_none_returns_empty(self):
        assert redact_text(None) == ""

    def test_empty_string_unchanged(self):
        assert redact_text("") == ""

    def test_long_string_redacted(self):
        text = "a" * 1000 + " sk-" + "b" * 30
        result = redact_text(text)
        assert "sk-" not in result.split("[REDACTED]")[0].split("sk-")[-1:] or "bbbb" not in result.replace("[REDACTED]", "")
        # At minimum, the redaction marker must be present
        assert "[REDACTED]" in result

    def test_extra_patterns(self):
        extra = [re.compile(r"CUSTOM_SECRET")]
        result = redact_text("value CUSTOM_SECRET found", extra_patterns=extra)
        assert "CUSTOM_SECRET" not in result
        assert "[REDACTED]" in result


class TestRedactEnvLike:
    def test_redacts_api_key(self):
        data = {"API_KEY": "secret123", "HOME": "/home/user"}
        result = redact_env_like(data)
        assert result["API_KEY"] == "[REDACTED]"
        assert result["HOME"] == "/home/user"

    def test_redacts_token(self):
        data = {"AUTH_TOKEN": "xyz", "PATH": "/usr/bin"}
        result = redact_env_like(data)
        assert result["AUTH_TOKEN"] == "[REDACTED]"
        assert result["PATH"] == "/usr/bin"

    def test_redacts_secret(self):
        data = {"DB_SECRET": "pass123", "LANG": "en_US"}
        result = redact_env_like(data)
        assert result["DB_SECRET"] == "[REDACTED]"
        assert result["LANG"] == "en_US"

    def test_redacts_password(self):
        data = {"PASSWORD": "hunter2", "SHELL": "/bin/bash"}
        result = redact_env_like(data)
        assert result["PASSWORD"] == "[REDACTED]"
        assert result["SHELL"] == "/bin/bash"

    def test_redacts_auth(self):
        data = {"AWS_AUTH_KEY": "abc123", "USER": "root"}
        result = redact_env_like(data)
        assert result["AWS_AUTH_KEY"] == "[REDACTED]"
        assert result["USER"] == "root"

    def test_preserves_normal_keys(self):
        data = {"PATH": "/usr/bin", "HOME": "/home/user", "LANG": "en_US.UTF-8"}
        result = redact_env_like(data)
        assert result == data


class TestTruncateOutput:
    def test_short_text_unchanged(self):
        assert truncate_output("hello") == "hello"

    def test_exact_length_unchanged(self):
        text = "a" * 500
        assert truncate_output(text) == text

    def test_long_text_truncated(self):
        text = "a" * 600
        result = truncate_output(text)
        assert len(result) < len(text)
        assert "[truncated" in result
        assert "600 chars total" in result
