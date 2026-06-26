"""Tests for the local_openai adapter."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from audiagentic.components.providers.adapters.local_openai import adapter


class TestLocalOpenAiAdapter(unittest.TestCase):
    """Test the local_openai adapter run function."""

    def test_run_requires_model(self):
        """run() raises when no model is provided."""
        packet_ctx = {"job-id": "test-job", "prompt-body": "test prompt"}
        provider_cfg = {"api-base-url": "http://localhost:11434"}
        with self.assertRaises(Exception) as ctx:
            adapter.run(packet_ctx, provider_cfg)
        self.assertIn("model-id or default-model is required", str(ctx.exception))

    def test_run_uses_default_model(self):
        """run() uses default-model from provider_cfg."""
        packet_ctx = {
            "job-id": "test-job",
            "prompt-body": "test prompt",
        }
        provider_cfg = {
            "api-base-url": "http://localhost:11434",
            "default-model": "test-model",
        }
        mock_response = MagicMock()
        mock_response.read.return_value = b'data: {"delta": {"content": "hello"}}\n'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = adapter.run(packet_ctx, provider_cfg)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["model"], "test-model")
        self.assertTrue(result["stream"])

    def test_run_uses_packet_model(self):
        """run() uses model-id from packet_ctx when no default-model."""
        packet_ctx = {
            "job-id": "test-job",
            "prompt-body": "test prompt",
            "model-id": "packet-model",
        }
        provider_cfg = {
            "api-base-url": "http://localhost:11434",
        }
        mock_response = MagicMock()
        mock_response.read.return_value = b'data: {"delta": {"content": "hello"}}\n'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = adapter.run(packet_ctx, provider_cfg)

        self.assertEqual(result["model"], "packet-model")

    def test_run_non_stream(self):
        """run() handles non-streaming responses."""
        packet_ctx = {
            "job-id": "test-job",
            "prompt-body": "test prompt",
        }
        provider_cfg = {
            "api-base-url": "http://localhost:11434",
            "default-model": "test-model",
            "stream": False,
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "test output"}}],
            "model": "test-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = adapter.run(packet_ctx, provider_cfg)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["stream"])
        self.assertIn("usage", result)

    def test_run_http_error(self):
        """run() raises on HTTP errors."""
        import email.message
        import urllib.error
        packet_ctx = {
            "job-id": "test-job",
            "prompt-body": "test prompt",
        }
        provider_cfg = {
            "api-base-url": "http://localhost:11434",
            "default-model": "test-model",
        }
        mock_headers = email.message.Message()
        mock_exc = urllib.error.HTTPError(
            "http://localhost:11434/v1/chat/completions",
            401,
            "Unauthorized",
            mock_headers,
            None,
        )
        mock_exc.read = MagicMock(return_value=b'{"error": {"message": "Bad API key"}}')

        with patch("urllib.request.urlopen", side_effect=mock_exc):
            with self.assertRaises(Exception) as ctx:
                adapter.run(packet_ctx, provider_cfg)
            self.assertIn("401", str(ctx.exception))

    def test_build_messages(self):
        """_build_messages creates proper OpenAI messages."""
        packet_ctx = {"job-id": "test-job", "packet-id": "test-packet"}
        messages = adapter._build_messages(packet_ctx, "user prompt here")
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("user prompt here", messages[1]["content"])

    def test_fetch_api_key_from_config(self):
        """_fetch_api_key reads from provider config."""
        cfg = {"api-key": "test-key-123"}
        self.assertEqual(adapter._fetch_api_key(cfg), "test-key-123")

    def test_fetch_api_key_from_env_fallback(self):
        """_fetch_api_key falls back to OPENAI_API_KEY."""
        cfg = {"OPENAI_API_KEY": "env-key"}
        self.assertEqual(adapter._fetch_api_key(cfg), "env-key")

    def test_resolve_base_url(self):
        """_resolve_base_url reads from config."""
        cfg = {"api-base-url": "http://my-server:8080"}
        self.assertEqual(adapter._resolve_base_url(cfg), "http://my-server:8080")

    def test_resolve_base_url_default(self):
        """_resolve_base_url defaults to OpenAI."""
        cfg = {}
        self.assertEqual(adapter._resolve_base_url(cfg), "https://api.openai.com")


if __name__ == "__main__":
    unittest.main()
