"""Unit tests for foundation/logging/redaction.py."""
from __future__ import annotations

import json
import re

from audiagentic.foundation.logging.redaction import (
    is_bulk_key,
    is_sensitive_key,
    redact_env_like,
    redact_error_envelope,
    redact_text,
    safe_metadata,
    summarize_structure,
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

    def test_url_credential_pattern(self):
        url = "https://user:secrettoken@github.com/repo/commit"
        result = redact_text(url)
        assert "secrettoken" not in result
        assert "[REDACTED]" in result
        # The URL scheme and host should still be present
        assert "https://" in result
        assert "@github.com" in result


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


class TestIsSensitiveKey:
    def test_secret_keys_match(self):
        for key in (
            "api_key", "token", "SECRET", "password", "Authorization",
            "auth-header", "AUTH_TOKEN",
        ):
            assert is_sensitive_key(key), f"{key!r} should be sensitive"

    def test_bulk_keys_not_secret(self):
        for key in ("stdout", "stderr", "output", "input", "prompt-body", "raw_output"):
            assert not is_sensitive_key(key), f"{key!r} should NOT be a secret key"
            assert is_bulk_key(key), f"{key!r} should be a bulk key"

    def test_benign_keys_pass(self):
        for key in ("correlation_id", "job-id", "trigger-id", "status", "event_type", "subject"):
            assert not is_sensitive_key(key), f"{key!r} should be benign"
            assert not is_bulk_key(key), f"{key!r} should not be a bulk key"


class TestSummarizeStructure:
    """EDJ24 — deterministic, redacted, bounded JSON summaries."""

    def test_sensitive_values_redacted(self):
        payload = {
            "prompt-body": "SECRET_PROMPT",
            "api_key": "sk-123",
            "nested": {"token": "tkn"},
        }
        summary = summarize_structure(payload)
        # prompt-body is BULK_KEY — content-redacted, NOT blanked. Clean diagnostic survives.
        assert "SECRET_PROMPT" in summary
        # api_key is SECRET_KEY — blanket-replaced.
        assert "sk-123" not in summary
        # nested.token is SECRET_KEY — blanket-replaced.
        assert "tkn" not in summary
        assert "[REDACTED]" in summary

    def test_deterministic_output(self):
        payload = {"b": 1, "a": {"z": [1, 2], "y": "x"}}
        assert summarize_structure(payload) == summarize_structure(payload)
        # sort_keys => key order in the input dict does not matter
        assert summarize_structure({"a": 1, "b": 2}) == summarize_structure({"b": 2, "a": 1})

    def test_output_is_json(self):
        summary = summarize_structure({"a": [1, "two", None], "b": True})
        json.loads(summary)

    def test_bounded_for_deep_nesting(self):
        deep: dict = {"leaf": "v"}
        for _ in range(50):
            deep = {"level": deep}
        summary = summarize_structure(deep, max_len=500)
        assert len(summary) <= 500
        assert "[TRUNCATED]" in summary

    def test_bounded_for_huge_lists(self):
        payload = {"items": [f"value-{i}" for i in range(10_000)]}
        summary = summarize_structure(payload, max_len=500)
        assert len(summary) <= 500

    def test_long_strings_truncated(self):
        summary = summarize_structure({"note": "x" * 5000}, max_len=500)
        assert len(summary) <= 500

    def test_secret_shaped_string_values_redacted(self):
        summary = summarize_structure({"note": "password=hunter2secret"})
        assert "hunter2secret" not in summary

    def test_never_raises_on_pathological_input(self):
        class Unserializable:
            def __str__(self):
                return "unserializable-object"

        summary = summarize_structure({"obj": Unserializable(), "b": {1, 2}})
        assert isinstance(summary, str)

    def test_non_dict_input(self):
        assert isinstance(summarize_structure("plain string"), str)
        assert isinstance(summarize_structure([1, 2, 3]), str)
        assert isinstance(summarize_structure(None), str)


class TestSafeMetadata:
    """EDJ24 — allowlist-only metadata with recursively redacted values."""

    def test_only_allowlisted_keys_survive(self):
        metadata = {
            "correlation_id": "corr-1",
            "job-id": "job-7",
            "trigger-id": "trg-1",
            "subject": {"kind": "job", "id": "job-7"},
            "source-component": "planning",
            "api_key": "sk-123",
            "arbitrary": "value",
        }
        result = safe_metadata(metadata)
        assert set(result) == {
            "correlation_id", "job-id", "trigger-id", "subject", "source-component",
        }
        assert "sk-123" not in json.dumps(result)

    def test_nested_values_redacted(self):
        result = safe_metadata({"subject": {"kind": "job", "token": "tkn-1"}})
        assert result["subject"]["token"] == "[REDACTED]"

    def test_non_mapping_returns_empty(self):
        assert safe_metadata(None) == {}
        assert safe_metadata("string") == {}
        assert safe_metadata([1, 2]) == {}


class TestRedactErrorEnvelope:
    """Shared redact_error_envelope replaces local variants (RV328)."""

    def test_sensitive_keys_redacted(self):
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        err = AudiaGenticError(
            code="INT-TST-001",
            kind="test",
            message="test error",
            details={
                "stdout": "some output with password=hunter2",
                "api_key": "sk-secret",
                "provider_id": "claude",
            },
        )
        envelope = redact_error_envelope(err)
        # stdout is BULK_KEY — content-redacted, NOT blanked. The password value is replaced.
        assert envelope["details"]["stdout"] == "some output with password=[REDACTED]"
        # api_key is SECRET_KEY — blanket-replaced.
        assert envelope["details"]["api_key"] == "[REDACTED]"
        assert envelope["details"]["provider_id"] == "claude"

    def test_nested_details_redacted(self):
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        err = AudiaGenticError(
            code="INT-TST-002",
            kind="test",
            message="test error",
            details={
                "nested": {
                    "token": "secret_token",
                    "safe": "value",
                },
            },
        )
        envelope = redact_error_envelope(err)
        assert envelope["details"]["nested"]["token"] == "[REDACTED]"
        assert envelope["details"]["nested"]["safe"] == "value"

    def test_dict_input(self):
        envelope = redact_error_envelope({
            "error": "something",
            "details": {
                "stderr": "error output",
                "count": 42,
            },
        })
        # stderr is BULK_KEY — content-redacted, NOT blanked. Clean diagnostic survives intact.
        assert envelope["details"]["stderr"] == "error output"
        assert envelope["details"]["count"] == 42
