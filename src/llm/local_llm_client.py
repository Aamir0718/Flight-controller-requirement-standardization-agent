"""Thin wrapper around an OpenAI-compatible chat completions endpoint
(vLLM, in this project's case -- config/settings.yaml's llm.base_url
points at a DRDO-internal vLLM server, not a hosted/public API).

- base_url, model, api_key, timeout, and temperature all come from
  config/settings.yaml's `llm` section (via src/config.get_settings())
  -- never hardcoded. api_key is optional (empty string/absent means no
  Authorization header is sent at all -- this project's own DRDO server
  doesn't require one).
- Refuses to run if the endpoint isn't reachable: check_reachable()
  (called automatically before every request) raises LLMUnavailableError
  with a clear message. There is no automatic fallback to any other
  endpoint -- if this one's down, every LLM-dependent feature (candidate
  generation, contradiction detection) fails clearly rather than silently
  trying somewhere else; the deterministic parts of this project (EARS/
  INCOSE analysis, manual edit, Excel export) never depend on this module
  at all and keep working regardless.
- Talks plain OpenAI chat-completions JSON over HTTP (POST
  {base_url}/chat/completions, GET {base_url}/models for the reachability
  check) via httpx -- no `openai` SDK dependency, since this is the only
  two calls this project ever needs and httpx is already a dependency.
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

from config import get_settings

REQUIRED_KEYS = {"pattern", "rewritten_text", "vague_terms", "confidence", "notes"}

# Connection-level failures (server down, DNS/host unreachable, timeout)
# surface as these from httpx or, occasionally, a bare OSError from the
# underlying socket layer. A non-2xx HTTP response (wrong model name,
# malformed request, server-side error) is handled separately via
# httpx.HTTPStatusError, since the response body usually explains exactly
# what was wrong -- worth showing verbatim rather than folding into the
# same generic "unreachable" message.
_CONNECTIVITY_EXCEPTIONS = (httpx.TransportError, ConnectionError, OSError)

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


class LLMUnavailableError(RuntimeError):
    """Raised when the configured LLM endpoint (config/settings.yaml's
    llm.base_url) cannot be reached, or rejects a request outright (wrong
    model name, malformed request, server error).

    Callers must not catch this to fall back to a different endpoint --
    there is exactly one configured LLM endpoint, and every feature that
    depends on it (candidate generation, contradiction detection) is
    expected to fail clearly, not silently degrade to something else. The
    deterministic parts of this project never depend on this module and
    are unaffected either way -- see src/pipeline/graph.py's
    analyze_requirement() and src/storage/db.py's apply_manual_edit().
    """


class LLMResponseError(RuntimeError):
    """Raised when the model's response isn't valid JSON matching the
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
    """Talks to one OpenAI-compatible chat completions endpoint (vLLM),
    configured via config/settings.yaml's `llm` section. The class name
    predates the switch away from a locally-run Ollama instance -- kept
    as-is rather than renamed, since every caller (src/pipeline/graph.py,
    src/pipeline/candidate_generator.py, src/consistency/analyzer.py)
    imports it by this name and nothing about the public contract changed.
    """

    def __init__(self, settings: dict[str, Any] | None = None):
        llm_cfg = (settings or get_settings())["llm"]
        self.model = llm_cfg["model"]
        self.base_url = llm_cfg["base_url"].rstrip("/")
        self.api_key = llm_cfg.get("api_key") or None
        self.request_timeout_seconds = llm_cfg.get("request_timeout_seconds", 120)
        self.temperature = llm_cfg.get("temperature", 0.2)

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        self._client = httpx.Client(
            base_url=self.base_url, timeout=self.request_timeout_seconds, headers=headers
        )

    def check_reachable(self) -> None:
        """Raises LLMUnavailableError if the configured endpoint cannot be
        reached, or responds with an error (e.g. authentication)."""
        try:
            response = self._client.get("/models")
            response.raise_for_status()
        except _CONNECTIVITY_EXCEPTIONS as exc:
            raise LLMUnavailableError(
                f"Cannot reach the LLM endpoint at {self.base_url} (configured model "
                f"'{self.model}'). Confirm the vLLM server is running and reachable "
                "from this machine, and that llm.base_url in config/settings.yaml is "
                "correct. This project never falls back to a different endpoint."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMUnavailableError(
                f"The LLM endpoint at {self.base_url} responded with "
                f"{exc.response.status_code}: {exc.response.text[:300]}. Confirm "
                "llm.api_key (if the server requires one) in config/settings.yaml."
            ) from exc

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> LLMResult:
        """Sends system_prompt + user_prompt to the configured model and
        returns a parsed, schema-validated LLMResult. Retries once with a
        stricter instruction if the first response isn't valid JSON
        matching the schema; raises LLMResponseError if the retry also
        fails.

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
                "The model did not return valid JSON matching the required schema "
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
                f"The model did not return valid JSON matching schema {sorted(required_keys)}, "
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
        # OpenAI-compatible chat completions body. `response_format:
        # json_object` is the widely-supported baseline (real OpenAI and
        # vLLM both honor it) for "must be valid JSON" -- it does not
        # enforce the exact schema server-side, so the schema itself is
        # still spelled out in the prompt (src/llm/prompts.py) and
        # enforced client-side by _try_parse()/_try_parse_generic() below,
        # same as before. `schema` is accepted for call-site symmetry with
        # the old Ollama `format` parameter but isn't sent -- kept as a
        # parameter in case a future server-side `json_schema` mode is
        # worth wiring in.
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
        }
        if seed is not None:
            payload["seed"] = seed

        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except _CONNECTIVITY_EXCEPTIONS as exc:
            raise LLMUnavailableError(
                f"Cannot reach the LLM endpoint at {self.base_url} (configured model "
                f"'{self.model}') while generating a response. Confirm the vLLM server "
                "is running and reachable from this machine."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMUnavailableError(
                f"The LLM endpoint at {self.base_url} rejected the request "
                f"({exc.response.status_code}): {exc.response.text[:300]}. If this "
                f"mentions the model name, confirm llm.model ('{self.model}') in "
                "config/settings.yaml exactly matches what the server has loaded "
                "(GET {base_url}/models lists the served name)."
            ) from exc

        data = response.json()
        return data["choices"][0]["message"]["content"]

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
        # some models sometimes use smart quotes and other non-ASCII characters
        # This must happen BEFORE we count braces, or smart quotes will confuse the parser
        text = text.replace('‘', "'").replace('’', "'").replace('“', '"').replace('”', '"')
        text = text.replace('–', '-').replace('—', '-').replace('±', '+/-')
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
