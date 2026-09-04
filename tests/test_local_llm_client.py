"""Unit tests for src/llm/local_llm_client.py.

These never touch the network: check_reachable()'s underlying HTTP calls
and _chat() are monkeypatched so the suite stays fast and doesn't require
a real, reachable vLLM endpoint. The one test that talks to a real (if
reachable) endpoint lives in tests/test_llm_integration.py and auto-skips
when it isn't running.
"""

from __future__ import annotations

import httpx
import pytest

from llm.local_llm_client import (
    LLMResponseError,
    LLMResult,
    LocalLLMClient,
    LLMUnavailableError,
)

SETTINGS = {
    "llm": {
        "base_url": "http://localhost:8001/v1",
        "model": "llama3.1",
        "api_key": "",
        "request_timeout_seconds": 5,
        "temperature": 0.2,
    }
}

VALID_JSON_RESPONSE = """{
  "pattern": "Event-driven",
  "rewritten_text": "When the sensor detects a fault, the controller shall log the event.",
  "vague_terms": [{"term": "quickly", "suggestion": "specify a maximum response time in milliseconds"}],
  "confidence": 0.85,
  "notes": "Trigger condition was already present in the original text."
}"""


def _client() -> LocalLLMClient:
    return LocalLLMClient(settings=SETTINGS)


def _fake_response(status_code: int = 200, json_body: dict | None = None, text_body: str = "") -> httpx.Response:
    request = httpx.Request("POST", "http://localhost:8001/v1/chat/completions")
    if json_body is not None:
        return httpx.Response(status_code, request=request, json=json_body)
    return httpx.Response(status_code, request=request, text=text_body)


def _openai_response(content: str) -> httpx.Response:
    return _fake_response(200, {"choices": [{"message": {"content": content}}]})


class TestConfigDrivenSettings:
    def test_reads_model_base_url_from_given_settings_not_hardcoded(self):
        custom = {
            "llm": {
                "base_url": "http://some-other-host:22222/v1",
                "model": "totally-different-model",
                "api_key": "",
                "request_timeout_seconds": 7,
                "temperature": 0.9,
            }
        }
        client = LocalLLMClient(settings=custom)
        assert client.model == "totally-different-model"
        assert client.base_url == "http://some-other-host:22222/v1"
        assert client.request_timeout_seconds == 7
        assert client.temperature == 0.9

    def test_reads_real_project_config_when_no_settings_given(self):
        from config import get_settings

        expected = get_settings()["llm"]
        client = LocalLLMClient()
        assert client.model == expected["model"]
        assert client.base_url == expected["base_url"].rstrip("/")

    def test_trailing_slash_on_base_url_is_stripped(self):
        client = LocalLLMClient(settings={"llm": {**SETTINGS["llm"], "base_url": "http://x:8001/v1/"}})
        assert client.base_url == "http://x:8001/v1"

    def test_no_api_key_means_no_authorization_header(self):
        client = _client()
        assert "Authorization" not in client._client.headers

    def test_api_key_becomes_a_bearer_authorization_header(self):
        client = LocalLLMClient(settings={"llm": {**SETTINGS["llm"], "api_key": "secret-token"}})
        assert client._client.headers["Authorization"] == "Bearer secret-token"


class TestReachability:
    def test_check_reachable_raises_clear_error_when_unreachable(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(
            client._client, "get", lambda path: (_ for _ in ()).throw(httpx.ConnectError("refused"))
        )
        with pytest.raises(LLMUnavailableError) as exc_info:
            client.check_reachable()
        message = str(exc_info.value)
        assert "llama3.1" in message
        assert "localhost:8001" in message

    def test_check_reachable_passes_when_reachable(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client._client, "get", lambda path: _fake_response(200, {"data": []}))
        client.check_reachable()  # must not raise

    def test_check_reachable_raises_on_error_status_code(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(
            client._client, "get", lambda path: _fake_response(401, text_body="Unauthorized")
        )
        with pytest.raises(LLMUnavailableError) as exc_info:
            client.check_reachable()
        assert "401" in str(exc_info.value)

    def test_generate_structured_checks_reachability_before_chatting(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(
            client._client, "get", lambda path: (_ for _ in ()).throw(httpx.ConnectError("refused"))
        )
        chat_called = []
        monkeypatch.setattr(
            client, "_chat", lambda messages, *args, **kwargs: chat_called.append(messages)
        )

        with pytest.raises(LLMUnavailableError):
            client.generate_structured("system", "user")
        assert chat_called == []  # never attempted a chat call


class TestStructuredJsonEnforcement:
    def test_parses_valid_json_on_first_try(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        calls = []

        def fake_chat(messages, *args, **kwargs):
            calls.append(messages)
            return VALID_JSON_RESPONSE

        monkeypatch.setattr(client, "_chat", fake_chat)

        result = client.generate_structured("system prompt", "user prompt")

        assert isinstance(result, LLMResult)
        assert result.pattern == "Event-driven"
        assert result.rewritten_text.startswith("When the sensor")
        assert result.confidence == 0.85
        assert len(result.vague_terms) == 1
        assert result.vague_terms[0].term == "quickly"
        assert len(calls) == 1  # no retry needed

    def test_request_body_has_openai_shape_with_temperature_and_seed(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        seen_payloads = []

        def fake_post(path, json):
            seen_payloads.append(json)
            return _openai_response(VALID_JSON_RESPONSE)

        monkeypatch.setattr(client._client, "post", fake_post)

        client.generate_structured("system", "user", temperature=0.9, seed=42)

        assert seen_payloads[0]["model"] == "llama3.1"
        assert seen_payloads[0]["temperature"] == 0.9
        assert seen_payloads[0]["seed"] == 42
        assert seen_payloads[0]["response_format"] == {"type": "json_object"}
        assert seen_payloads[0]["messages"] == [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ]

    def test_omitted_temperature_and_seed_fall_back_to_config_default_and_no_seed_key(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        seen_payloads = []

        def fake_post(path, json):
            seen_payloads.append(json)
            return _openai_response(VALID_JSON_RESPONSE)

        monkeypatch.setattr(client._client, "post", fake_post)

        client.generate_structured("system", "user")

        assert seen_payloads[0]["temperature"] == client.temperature
        assert "seed" not in seen_payloads[0]

    def test_connectivity_failure_during_chat_raises_llm_unavailable(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        monkeypatch.setattr(
            client._client, "post", lambda path, json: (_ for _ in ()).throw(httpx.ConnectError("refused"))
        )
        with pytest.raises(LLMUnavailableError):
            client.generate_structured("system", "user")

    def test_error_status_during_chat_raises_llm_unavailable_with_body(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        monkeypatch.setattr(
            client._client,
            "post",
            lambda path, json: _fake_response(400, text_body="model 'llama3.1' not found"),
        )
        with pytest.raises(LLMUnavailableError) as exc_info:
            client.generate_structured("system", "user")
        assert "not found" in str(exc_info.value)

    def test_strips_markdown_code_fences(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        fenced = f"```json\n{VALID_JSON_RESPONSE}\n```"
        monkeypatch.setattr(client, "_chat", lambda messages, *args, **kwargs: fenced)

        result = client.generate_structured("system", "user")
        assert result.pattern == "Event-driven"

    def test_retries_once_on_malformed_json_then_succeeds(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        responses = iter(["not json at all", VALID_JSON_RESPONSE])
        calls = []

        def fake_chat(messages, *args, **kwargs):
            calls.append(messages)
            return next(responses)

        monkeypatch.setattr(client, "_chat", fake_chat)

        result = client.generate_structured("system", "user")

        assert result.pattern == "Event-driven"
        assert len(calls) == 2  # first attempt + one stricter retry
        # the retry conversation includes the original messages, the bad
        # assistant reply, and the stricter follow-up instruction
        retry_messages = calls[1]
        assert retry_messages[0]["content"] == "system"
        assert retry_messages[-2]["content"] == "not json at all"
        assert "ONLY a single JSON object" in retry_messages[-1]["content"]

    def test_retries_once_on_missing_required_key_then_succeeds(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        missing_key = '{"pattern": "Event-driven", "rewritten_text": "X"}'  # no vague_terms/confidence/notes
        responses = iter([missing_key, VALID_JSON_RESPONSE])
        monkeypatch.setattr(client, "_chat", lambda messages, *args, **kwargs: next(responses))

        result = client.generate_structured("system", "user")
        assert result.pattern == "Event-driven"

    def test_raises_llm_response_error_after_failed_retry(self, monkeypatch):
        client = _client()
        monkeypatch.setattr(client, "check_reachable", lambda: None)
        calls = []

        def fake_chat(messages, *args, **kwargs):
            calls.append(messages)
            return "still not json"

        monkeypatch.setattr(client, "_chat", fake_chat)

        with pytest.raises(LLMResponseError):
            client.generate_structured("system", "user")
        assert len(calls) == 2  # exactly one retry, then gives up

    def test_rejects_json_missing_a_required_key(self):
        bad = '{"pattern": "Event-driven", "rewritten_text": "X", "confidence": 0.5, "notes": "n"}'
        assert LocalLLMClient._try_parse(bad) is None  # missing vague_terms

    def test_rejects_vague_terms_not_a_list(self):
        bad = VALID_JSON_RESPONSE.replace('"vague_terms": [{"term": "quickly", "suggestion": "specify a maximum response time in milliseconds"}]', '"vague_terms": "quickly"')
        assert LocalLLMClient._try_parse(bad) is None

    def test_rejects_vague_term_entry_missing_suggestion(self):
        bad = VALID_JSON_RESPONSE.replace(
            '{"term": "quickly", "suggestion": "specify a maximum response time in milliseconds"}',
            '{"term": "quickly"}',
        )
        assert LocalLLMClient._try_parse(bad) is None

    def test_rejects_non_numeric_confidence(self):
        bad = VALID_JSON_RESPONSE.replace('"confidence": 0.85', '"confidence": "high"')
        assert LocalLLMClient._try_parse(bad) is None

    def test_accepts_empty_vague_terms_list(self):
        clean = VALID_JSON_RESPONSE.replace(
            '"vague_terms": [{"term": "quickly", "suggestion": "specify a maximum response time in milliseconds"}]',
            '"vague_terms": []',
        )
        parsed = LocalLLMClient._try_parse(clean)
        assert parsed is not None
        assert parsed["vague_terms"] == []
