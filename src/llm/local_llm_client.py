"""Thin wrapper around a local Ollama instance.

- Model name, host, port, timeout, and temperature all come from
  config/settings.yaml (via src/config.get_settings()) -- never hardcoded.
- Refuses to run if Ollama isn't reachable: check_reachable() (called
  automatically before every request) raises OllamaUnavailableError with a
  clear message. There is no fallback path to any external/hosted API --
  this project is fully offline by design (see README).
- generate_structured() enforces JSON-only output matching a fixed schema
  ({pattern, rewritten_text, vague_terms, confidence, notes}). If the model
  returns malformed JSON or is missing required keys, it retries exactly
  once with a stricter instruction before raising LLMResponseError.
- generate_json() is the same idea but for any caller-supplied schema
  (e.g. consistency.analyzer's contradiction check), since that response
  shape is different from the fixed candidate-rewrite schema above.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
import ollama

from config import get_settings

REQUIRED_KEYS = {"pattern", "rewritten_text", "vague_terms", "confidence", "notes"}

# Connection-level failures from the ollama client surface as httpx
# exceptions (ConnectError, ConnectTimeout, ...) or, occasionally, a bare
# OSError from the underlying socket layer.
_CONNECTIVITY_EXCEPTIONS = (httpx.HTTPError, ConnectionError, OSError)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string"},
        "rewritten_text": {"type": "string"},
        "vague_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["term", "suggestion"],
            },
        },
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["pattern", "rewritten_text", "vague_terms", "confidence", "notes"],
}


class OllamaUnavailableError(RuntimeError):
    """Raised when the configured local Ollama instance cannot be reached.

    Callers must not catch this to fall back to a remote/hosted API --
    this project is required to run fully offline (see README.md).
    """


class LLMResponseError(RuntimeError):
    """Raised when Ollama's response isn't valid JSON matching the
    required schema, even after one stricter retry."""


@dataclass(frozen=True)
class VagueTermSuggestion:
    term: str
    suggestion: str


@dataclass(frozen=True)
class LLMResult:
    pattern: str
    rewritten_text: str
    vague_terms: list[VagueTermSuggestion]
    confidence: float
    notes: str
    raw: dict[str, Any]


_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_STRICT_RETRY_INSTRUCTION = (
    "Your previous response was not valid JSON matching the required schema. "
    "Respond with ONLY a single JSON object -- no markdown code fences, no "
    "commentary before or after it -- containing exactly these keys: "
    'pattern (string), rewritten_text (string), vague_terms (array of '
    '{"term": string, "suggestion": string} objects, possibly empty), '
    "confidence (number between 0 and 1), notes (string)."
)


class LocalLLMClient:
    """Talks to one local Ollama model, configured via config/settings.yaml."""

    def __init__(self, settings: dict[str, Any] | None = None):
        ollama_cfg = (settings or get_settings())["ollama"]
        self.model = ollama_cfg["model"]
        self.host = f"http://{ollama_cfg['host']}:{ollama_cfg['port']}"
        self.request_timeout_seconds = ollama_cfg.get("request_timeout_seconds", 120)
        self.temperature = ollama_cfg.get("temperature", 0.2)
        self._client = ollama.Client(host=self.host, timeout=self.request_timeout_seconds)

    def check_reachable(self) -> None:
        """Raises OllamaUnavailableError if the configured Ollama instance
        cannot be reached. Never falls back to any other API."""
        try:
            self._client.list()
        except _CONNECTIVITY_EXCEPTIONS as exc:
            raise OllamaUnavailableError(
                f"Cannot reach Ollama at {self.host} (configured model "
                f"'{self.model}'). Start it locally (e.g. `ollama serve`) and "
                "confirm host/port in config/settings.yaml. This project runs "
                "fully offline and never falls back to an external API."
            ) from exc

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> LLMResult:
        """Sends system_prompt + user_prompt to the local model and returns
        a parsed, schema-validated LLMResult. Retries once with a stricter
        instruction if the first response isn't valid JSON matching the
        schema; raises LLMResponseError if the retry also fails.

        ``temperature``/``seed`` override the config-file defaults for this
        one call -- e.g. src/pipeline/candidate_generator.py varies them
        across calls to sample genuinely different candidate rewrites
        rather than repeating the same settings 3 times.
        """
        self.check_reachable()
        effective_temperature = self.temperature if temperature is None else temperature

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw_text = self._chat(messages, effective_temperature, seed)
        parsed = self._try_parse(raw_text)

        if parsed is None:
            retry_messages = messages + [
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content": _STRICT_RETRY_INSTRUCTION},
            ]
            raw_text = self._chat(retry_messages, effective_temperature, seed)
            parsed = self._try_parse(raw_text)

        if parsed is None:
            raise LLMResponseError(
                "Ollama did not return valid JSON matching the required schema "
                f"({sorted(REQUIRED_KEYS)}), even after a stricter retry. Last "
                f"raw response: {raw_text!r}"
            )

        return self._to_result(parsed)

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        required_keys: set[str],
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Like generate_structured, but for any caller-supplied schema --
        used by callers (e.g. consistency.analyzer) whose prompts need a
        response shape other than the fixed candidate-rewrite schema."""
        self.check_reachable()
        effective_temperature = self.temperature if temperature is None else temperature
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw_text = self._chat_with_schema(messages, schema, effective_temperature, seed)
        parsed = self._try_parse_generic(raw_text, required_keys)

        if parsed is None:
            retry_messages = messages + [
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content": (
                    "Your previous response was not valid JSON matching the required "
                    f"schema. Respond with ONLY a JSON object containing exactly these "
                    f"keys: {sorted(required_keys)}."
                )},
            ]
            raw_text = self._chat_with_schema(retry_messages, schema, effective_temperature, seed)
            parsed = self._try_parse_generic(raw_text, required_keys)

        if parsed is None:
            raise LLMResponseError(
                f"Ollama did not return valid JSON matching schema {sorted(required_keys)}, "
                f"even after a stricter retry. Last raw response: {raw_text!r}"
            )
        return parsed

    def _chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str:
        return self._chat_with_schema(messages, RESPONSE_SCHEMA, temperature, seed)

    def _chat_with_schema(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str:
        options: dict[str, Any] = {
            "temperature": self.temperature if temperature is None else temperature,
            "num_predict": 1024,
        }
        if seed is not None:
            options["seed"] = seed
        response = self._client.chat(
            model=self.model,
            messages=messages,
            format=schema,
            options=options,
        )
        return response["message"]["content"]

    @staticmethod
    def _try_parse(raw_text: str) -> dict[str, Any] | None:
        data = LocalLLMClient._try_parse_generic(raw_text, REQUIRED_KEYS)
        if data is None:
            return None

        if not isinstance(data["pattern"], str) or not isinstance(data["rewritten_text"], str):
            return None
        if not isinstance(data["notes"], str):
            return None
        if not isinstance(data["confidence"], (int, float)) or isinstance(data["confidence"], bool):
            return None
        if not isinstance(data["vague_terms"], list):
            return None
        for item in data["vague_terms"]:
            if not isinstance(item, dict) or "term" not in item or "suggestion" not in item:
                return None
            if not isinstance(item["term"], str) or not isinstance(item["suggestion"], str):
                return None

        return data

    @staticmethod
    def _try_parse_generic(raw_text: str, required_keys: set[str]) -> dict[str, Any] | None:
        # Remove markdown code fences
        text = _JSON_FENCE.sub("", raw_text.strip()).strip()

        # Replace common non-ASCII characters with ASCII equivalents BEFORE brace counting
        # gemma3:4b sometimes uses smart quotes and other non-ASCII characters
        # This must happen BEFORE we count braces, or smart quotes will confuse the parser
        text = text.replace('\u2018', "'").replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        text = text.replace('\u2013', '-').replace('\u2014', '-').replace('\u00b1', '+/-')
        text = text.strip()

        # Remove ALL remaining non-ASCII characters (hallucinated Bengali chars, etc.)
        text = ''.join(char for char in text if ord(char) < 128)
        text = text.strip()

        # Find the matching close-brace for the first '{', tracking whether
        # we're inside a JSON string so that '{'/'}' characters that are part
        # of a string's *content* (e.g. stray text a model appended inside a
        # "notes" value) don't get miscounted as structural braces.
        brace_count = 0
        json_end = -1
        in_string = False
        escape_next = False
        for i, char in enumerate(text):
            if in_string:
                if escape_next:
                    escape_next = False
                elif char == '\\':
                    escape_next = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break

        if json_end > 0:
            text = text[:json_end]

        # Strip any trailing whitespace and stray characters after the JSON object
        text = text.strip()
        # Remove any trailing characters after the last closing brace
        # The model sometimes adds extra quotes, newlines, or other junk after the JSON
        # Find the last closing brace and keep everything up to and including it
        last_brace_idx = text.rfind('}')
        if last_brace_idx != -1:
            text = text[:last_brace_idx + 1]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to fix common JSON errors: trailing quotes in string values
            # The model sometimes writes: "notes": "text""}
            # instead of: "notes": "text"}
            # Find and fix such patterns
            fixed_text = re.sub(r'""\s*\}', '"}', text)
            fixed_text = re.sub(r"''\s*\}", "'}", fixed_text)
            try:
                data = json.loads(fixed_text)
            except json.JSONDecodeError:
                return None

        # Handle case where JSON is returned as a string instead of an object
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict) or not required_keys.issubset(data.keys()):
            return None

        return data

    @staticmethod
    def _to_result(data: dict[str, Any]) -> LLMResult:
        return LLMResult(
            pattern=data["pattern"],
            rewritten_text=data["rewritten_text"],
            vague_terms=[
                VagueTermSuggestion(term=v["term"], suggestion=v["suggestion"])
                for v in data["vague_terms"]
            ],
            confidence=float(data["confidence"]),
            notes=data["notes"],
            raw=data,
        )