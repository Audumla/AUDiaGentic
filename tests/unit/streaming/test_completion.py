"""Tests for provider completion normalization."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.protocols.streaming.completion import (
    CompletionStatus,
    Decision,
    NormalizationMethod,
    ProviderCompletion,
    Recommendation,
    ResultSource,
    build_synthetic_fallback,
    completion_artifact_dir,
    completion_path,
    normalize_provider_result,
    persist_completion,
    try_extract_json_from_stdout,
    validate_provider_completion,
)


class TestProviderCompletion:
    """Tests for ProviderCompletion dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        completion = ProviderCompletion(provider_id="test")
        assert completion.contract_version == "v1"
        assert completion.provider_id == "test"
        assert completion.status == CompletionStatus.OK.value
        assert completion.recommendation == Recommendation.PASS_WITH_NOTES.value
        assert completion.findings == []
        assert completion.follow_up_actions == []
        assert completion.evidence == []
        assert completion.notes == []
        assert completion.stdout == ""
        assert completion.stderr == ""
        assert completion.returncode == 0
        assert completion.result_source == ResultSource.FALLBACK_SYNTHETIC.value
        assert (
            completion.normalization_method
            == NormalizationMethod.FALLBACK_DERIVED.value
        )

    def test_to_dict(self):
        """Test conversion to dictionary."""
        completion = ProviderCompletion(
            provider_id="test",
            job_id="job_123",
            status=CompletionStatus.OK.value,
            decision=Decision.APPROVED.value,
            findings=[{"kind": "info", "message": "test finding"}],
            recommendation=Recommendation.PASS.value,
        )
        d = completion.to_dict()
        assert d["contract-version"] == "v1"
        assert d["provider-id"] == "test"
        assert d["job-id"] == "job_123"
        assert d["status"] == "ok"
        assert d["decision"] == "approved"
        assert len(d["findings"]) == 1
        assert d["recommendation"] == "pass"

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "contract-version": "v1",
            "provider-id": "opencode",
            "job-id": "job_123",
            "status": "ok",
            "decision": "approved",
            "findings": [{"kind": "info", "message": "test"}],
            "recommendation": "pass",
            "result-source": "stdout-json",
            "normalization-method": "provider-native-json",
            "created-at": "2026-04-05T12:00:00.000000Z",
        }
        completion = ProviderCompletion.from_dict(data)
        assert completion.provider_id == "opencode"
        assert completion.job_id == "job_123"
        assert completion.status == "ok"
        assert completion.decision == "approved"
        assert completion.result_source == "stdout-json"

    def test_from_dict_validation_error(self):
        """Test from_dict raises error on invalid data."""
        data = {
            "contract-version": "v1",
            "provider-id": "opencode",
            "status": "invalid-status",
            "recommendation": "pass",
            "result-source": "stdout-json",
            "normalization-method": "provider-native-json",
        }
        with pytest.raises(AudiaGenticError) as exc_info:
            ProviderCompletion.from_dict(data)
            
        assert exc_info.value.code == "COMPLETION-VALIDATION-003"


class TestNormalizeProviderResult:
    """Tests for normalize_provider_result function."""

    def test_basic_normalization(self):
        """Test basic result normalization."""
        completion = normalize_provider_result(
            provider_id="test",
            job_id="job_123",
            stdout="some output",
            stderr="",
            returncode=0,
            result_source=ResultSource.STDOUT_JSON,
            normalization_method=NormalizationMethod.PROVIDER_NATIVE_JSON,
        )
        assert completion.provider_id == "test"
        assert completion.job_id == "job_123"
        assert completion.stdout == "some output"
        assert completion.returncode == 0
        assert completion.result_source == "stdout-json"
        assert completion.normalization_method == "provider-native-json"

    def test_non_zero_return_code(self):
        """Test that non-zero return code sets error status."""
        completion = normalize_provider_result(
            provider_id="test",
            job_id="job_123",
            stdout="",
            stderr="error occurred",
            returncode=1,
            result_source=ResultSource.STDOUT_JSON,
            normalization_method=NormalizationMethod.PROVIDER_NATIVE_JSON,
        )
        assert completion.status == CompletionStatus.ERROR.value
        assert any("non-zero exit code" in note for note in completion.notes)

    def test_with_subject(self):
        """Test normalization with subject."""
        subject = {"kind": "job", "job-id": "job_123"}
        completion = normalize_provider_result(
            provider_id="test",
            job_id="job_123",
            stdout="",
            stderr="",
            returncode=0,
            result_source=ResultSource.STDOUT_JSON,
            normalization_method=NormalizationMethod.PROVIDER_NATIVE_JSON,
            subject=subject,
        )
        assert completion.subject == subject


class TestBuildSyntheticFallback:
    """Tests for build_synthetic_fallback function."""

    def test_synthetic_fallback(self):
        """Test synthetic fallback creation."""
        completion = build_synthetic_fallback(
            provider_id="test",
            job_id="job_123",
            stdout="unstructured output",
            stderr="",
            returncode=0,
        )
        assert completion.provider_id == "test"
        assert completion.job_id == "job_123"
        assert completion.result_source == ResultSource.FALLBACK_SYNTHETIC.value
        assert (
            completion.normalization_method
            == NormalizationMethod.FALLBACK_DERIVED.value
        )
        assert completion.recommendation == Recommendation.PASS_WITH_NOTES.value

    def test_synthetic_fallback_with_subject(self):
        """Test synthetic fallback with subject."""
        subject = {"kind": "packet", "packet-id": "PKT-TEST-001"}
        completion = build_synthetic_fallback(
            provider_id="test",
            job_id="job_123",
            stdout="",
            stderr="",
            returncode=0,
            subject=subject,
        )
        assert completion.subject == subject


class TestValidateProviderCompletion:
    """Tests for validate_provider_completion function."""

    def test_valid_completion(self):
        """Test validation of valid completion."""
        payload = {
            "contract-version": "v1",
            "provider-id": "test",
            "status": "ok",
            "recommendation": "pass",
            "result-source": "stdout-json",
            "normalization-method": "provider-native-json",
        }
        issues = validate_provider_completion(payload)
        assert len(issues) == 0

    def test_missing_required_fields(self):
        """Test validation catches missing required fields."""
        payload = {
            "contract-version": "v1",
            "provider-id": "test",
        }
        issues = validate_provider_completion(payload)
        # Should have issues for missing status, recommendation, result-source, normalization-method
        assert len(issues) > 0

    def test_invalid_status(self):
        """Test validation catches invalid status."""
        payload = {
            "contract-version": "v1",
            "provider-id": "test",
            "status": "invalid",
            "recommendation": "pass",
            "result-source": "stdout-json",
            "normalization-method": "provider-native-json",
        }
        issues = validate_provider_completion(payload)
        assert len(issues) > 0


class TestPathHelpers:
    """Tests for completion path helper functions."""

    def test_completion_artifact_dir(self, tmp_path):
        job_id = "job-123"
        expected = tmp_path / ".audiagentic" / "runtime" / "jobs" / job_id / "completions"
        assert completion_artifact_dir(tmp_path, job_id) == expected

    def test_completion_path(self, tmp_path):
        job_id = "job-123"
        provider_id = "opencode"
        expected = tmp_path / ".audiagentic" / "runtime" / "jobs" / job_id / "completions" / f"completion.{provider_id}.json"
        assert completion_path(tmp_path, job_id, provider_id) == expected


class TestPersistCompletion:
    """Tests for persist_completion function."""

    def test_persist_valid_completion(self, tmp_path):
        completion = ProviderCompletion(
            provider_id="opencode",
            job_id="job-123",
            status=CompletionStatus.OK.value,
            recommendation=Recommendation.PASS.value,
            result_source=ResultSource.STDOUT_JSON.value,
            normalization_method=NormalizationMethod.PROVIDER_NATIVE_JSON.value,
        )
        
        path = persist_completion(tmp_path, "job-123", completion)
        
        assert path.exists()
        assert path.name == "completion.opencode.json"
        
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            
        assert data["provider-id"] == "opencode"
        assert data["job-id"] == "job-123"
        assert data["status"] == "ok"
        
        # Test read-back using from_dict to prove roundtrip
        loaded = ProviderCompletion.from_dict(data)
        assert loaded.provider_id == "opencode"

    def test_persist_invalid_completion_fails(self, tmp_path):
        # Create directly via __init__ to bypass from_dict validation
        completion = ProviderCompletion(
            provider_id="test",
            status="invalid-status",
        )
        
        with pytest.raises(AudiaGenticError) as exc_info:
            persist_completion(tmp_path, "job-123", completion)
            
        assert exc_info.value.code == "COMPLETION-VALIDATION-002"
        assert "cannot be persisted" in exc_info.value.message


class TestTryExtractJsonFromStdout:
    """Tests for try_extract_json_from_stdout function."""

    def test_extract_valid_json(self):
        stdout = 'Here is my answer:\n```json\n{"status": "ok", "findings": []}\n```\nHope it helps!'
        extracted = try_extract_json_from_stdout(stdout)
        assert extracted == {"status": "ok", "findings": []}

    def test_extract_no_json(self):
        stdout = "Here is my answer:\nIt has no json."
        extracted = try_extract_json_from_stdout(stdout)
        assert extracted is None

    def test_extract_invalid_json(self):
        stdout = 'Here is my answer:\n```json\n{status: "ok"\n```\n'
        extracted = try_extract_json_from_stdout(stdout)
        assert extracted is None
