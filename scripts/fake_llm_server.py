"""A tiny fake OpenAI-compatible server for TEMPORARY local testing --
no model download, no GPU, no Hugging Face account, no gated model
access. It doesn't actually rewrite anything intelligently; it just
returns a fixed, valid response so you can prove the whole app (Generate
button, error handling, candidate scoring, Excel export) really talks to
config/settings.yaml's llm.base_url correctly, end to end.

This is for testing THIS APP's plumbing, not for evaluating real
requirement rewrites -- every "candidate" it returns is the same canned
text. Once you've confirmed Generate works, switch back to a real model
(scripts/verify_offline.py's docstring / the walkthrough your assistant
gave you for downloading a small Gemma model) or the real DRDO endpoint.

Usage:
    python scripts/fake_llm_server.py [--port 8001]

Then point config/settings.yaml at it:
    llm:
      base_url: "http://localhost:8001/v1"
      model: "fake-model"      # this server accepts any model name
      api_key: ""

Leave this running in its own terminal; Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

# A canned, schema-valid response for src/llm/local_llm_client.py's fixed
# candidate-rewrite schema (pattern/rewritten_text/vague_terms/confidence/
# notes). Every request gets this same text back -- good enough to prove
# the request/response round-trip works, not to judge rewrite quality.
_CANNED_REWRITE = {
    "pattern": "Ubiquitous",
    "rewritten_text": "The system shall respond to the operator within 200 milliseconds.",
    "vague_terms": [],
    "confidence": 0.9,
    "notes": "Canned response from scripts/fake_llm_server.py -- not a real model.",
}

# A canned "no contradiction" response for consistency.analyzer's
# different schema (is_contradiction/reason), used if you also test the
# consistency check's contradiction detection against this fake server.
_CANNED_CONTRADICTION = {
    "is_contradiction": False,
    "reason": "Canned response from scripts/fake_llm_server.py -- not a real judgment.",
}


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # quieter default logging
        print(f"[fake_llm_server] {self.address_string()} {format % args}")

    def _write_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._write_json(200, {"object": "list", "data": [{"id": "fake-model", "object": "model"}]})
        else:
            self._write_json(404, {"error": f"unknown path {self.path}"})

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._write_json(404, {"error": f"unknown path {self.path}"})
            return

        length = int(self.headers.get("Content-Length", 0))
        request_body = json.loads(self.rfile.read(length)) if length else {}
        last_user_message = ""
        for message in reversed(request_body.get("messages", [])):
            if message.get("role") == "user":
                last_user_message = message.get("content", "")
                break

        # Guess which schema the caller wants by looking for the
        # contradiction-check's distinctive prompt wording, so this one
        # fake server can stand in for either call this app makes.
        if re.search(r"contradict", last_user_message, re.IGNORECASE):
            content = json.dumps(_CANNED_CONTRADICTION)
        else:
            content = json.dumps(_CANNED_REWRITE)

        self._write_json(
            200,
            {
                "id": "fake-completion",
                "object": "chat.completion",
                "model": request_body.get("model", "fake-model"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
            },
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)

    server = HTTPServer(("127.0.0.1", args.port), _FakeOpenAIHandler)
    print(f"Fake OpenAI-compatible server running at http://127.0.0.1:{args.port}/v1")
    print("Point config/settings.yaml's llm.base_url here to test with no real model.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
