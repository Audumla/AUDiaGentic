"""Tests for the local AI tester."""
from __future__ import annotations

import email.message
import json
import unittest
from unittest.mock import MagicMock, patch

from .ai_tester import ChatResult, LocalAITester


class TestLocalAITester(unittest.TestCase):
    """Test LocalAITester without actually starting the rig."""

    def test_chat_raises_when_not_running(self):
        """chat() raises when endpoint is empty."""
        tester = LocalAITester()
        with self.assertRaises(Exception) as ctx:
            tester.chat("Hello")
        self.assertIn("CFG-TESTER-001", str(ctx.exception))

    def test_chat_messages_raises_when_not_running(self):
        """chat_messages() raises when endpoint is empty."""
        tester = LocalAITester()
        with self.assertRaises(Exception) as ctx:
            tester.chat_messages([{"role": "user", "content": "Hello"}])
        self.assertIn("CFG-TESTER-001", str(ctx.exception))

    def test_chat_raises_when_no_model(self):
        """chat() raises when model is not set."""
        tester = LocalAITester(endpoint="http://localhost:1234")
        with self.assertRaises(Exception) as ctx:
            tester.chat("Hello")
        self.assertIn("CFG-TESTER-002", str(ctx.exception))

    def test_chat_result_default_values(self):
        """ChatResult has sensible defaults."""
        result = ChatResult()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.content, "")
        self.assertIsNone(result.model)
        self.assertIsNone(result.usage)
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_message)
        self.assertIsNone(result.raw_response)

    def test_chat_result_with_error(self):
        """ChatResult can hold error info."""
        result = ChatResult(
            status="error",
            error_code="http-401",
            error_message="Unauthorized",
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "http-401")
        self.assertEqual(result.error_message, "Unauthorized")

    def test_health_uninitialized(self):
        """health() returns uninitialized when endpoint is empty."""
        tester = LocalAITester()
        result = tester.health()
        self.assertEqual(result["status"], "uninitialized")

    def test_stop_noop_when_port_zero(self):
        """stop() is a no-op when port is 0."""
        tester = LocalAITester(port=0)
        tester.stop()


class TestLocalAITesterChatHttpError(unittest.TestCase):
    """Test HTTP error handling in chat_messages."""

    def test_http_401_error(self):
        """chat_messages returns error for HTTP 401."""
        import urllib.error
        tester = LocalAITester(
            endpoint="http://localhost:42001/v1",
            model="test-model",
        )
        headers = email.message.Message()
        mock_exc = urllib.error.HTTPError(
            "http://localhost:42001/v1/chat/completions",
            401,
            "Unauthorized",
            headers,
            None,
        )
        mock_exc.read = MagicMock(return_value=b'{"error": {"message": "Bad key"}}')

        with patch("urllib.request.urlopen", side_effect=mock_exc):
            result = tester.chat("Hello")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "http-401")
        self.assertIn("Bad key", result.error_message)

    def test_http_500_error(self):
        """chat_messages returns error for HTTP 500."""
        import urllib.error
        tester = LocalAITester(
            endpoint="http://localhost:42001/v1",
            model="test-model",
        )
        headers = email.message.Message()
        mock_exc = urllib.error.HTTPError(
            "http://localhost:42001/v1/chat/completions",
            500,
            "Internal Server Error",
            headers,
            None,
        )
        mock_exc.read = MagicMock(return_value=b"Server error")

        with patch("urllib.request.urlopen", side_effect=mock_exc):
            result = tester.chat("Hello")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "http-500")

    def test_connection_error(self):
        """chat_messages returns error for connection failures."""
        import urllib.error
        tester = LocalAITester(
            endpoint="http://localhost:99999/v1",
            model="test-model",
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = tester.chat("Hello")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "connection")

    def test_timeout_error(self):
        """chat_messages returns error for timeouts."""
        tester = LocalAITester(
            endpoint="http://localhost:42001/v1",
            model="test-model",
            timeout=0.001,
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError(),
        ):
            result = tester.chat("Hello")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "timeout")


class TestLocalAITesterSuccessfulResponse(unittest.TestCase):
    """Test successful response parsing."""

    def test_successful_chat(self):
        """chat_messages parses successful response."""
        tester = LocalAITester(
            endpoint="http://localhost:42001/v1",
            model="test-model",
        )
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "4 is the answer"}}],
            "model": "test-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = tester.chat("What is 2+2?")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.content, "4 is the answer")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.usage["prompt_tokens"], 10)

    def test_api_error_in_response(self):
        """chat_messages parses API error from response body."""
        tester = LocalAITester(
            endpoint="http://localhost:42001/v1",
            model="test-model",
        )
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "error": {"code": "model_not_found", "message": "Model not loaded"},
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = tester.chat("Hello")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "model_not_found")


class TestCreateAsyncTester(unittest.TestCase):
    """Test create_async_tester factory function."""

    def test_create_async_tester_returns_tester(self):
        """create_async_tester returns a LocalAITester instance."""
        mock_result = MagicMock()
        mock_result.base_url = "http://127.0.0.1:42001/v1"
        mock_result.model = "qwen2.5:3b"
        mock_result.port = 42001
        mock_result.pid = 12345

        with patch(
            "audiagentic.runtime.rig.embedded.launch.start_embedded_rig",
            return_value=mock_result,
        ), patch(
            "audiagentic.runtime.rig.registry.register_client",
        ):
            from .ai_tester import create_async_tester
            tester = create_async_tester(model_profile="qwen2.5:3b")

        self.assertIsInstance(tester, LocalAITester)
        self.assertEqual(tester.model, "qwen2.5:3b")
        self.assertEqual(tester.port, 42001)

        tester.stop()


if __name__ == "__main__":
    unittest.main()
