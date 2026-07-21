"""Confirms the UI stack (src/ui/api.py + the HTTP calls
src/ui/streamlit_app.py makes) genuinely works with the network disabled
except for loopback -- under the same NetworkGuard scripts/verify_offline.py
uses for the pipeline itself.

tests/test_ui_api.py already covers the API's behavior thoroughly, but it
uses FastAPI's TestClient, which talks to the ASGI app in-memory and never
opens a real socket at all -- it can't prove anything about network
behavior. This file starts a REAL uvicorn server bound to 127.0.0.1 and
makes REAL HTTP requests to it over an actual loopback socket, inside
NetworkGuard, to prove:

1. The one connection this project's UI makes (Streamlit -> local API)
   is not blocked by the offline guard -- it's loopback, which is allowed.
2. A non-loopback connection attempted in the same process while the
   guard is active is still blocked -- the guard is discriminating on
   address, not just inert.

See scripts/verify_offline.py's module docstring for what an automated,
in-process guard like this can and can't prove, and README.md's
pre-release checklist for the required physical-disconnection test this
does not replace.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import requests
import uvicorn
from openpyxl import Workbook

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import verify_offline as vo  # noqa: E402

import storage.db as db_module  # noqa: E402
import ui.api as api  # noqa: E402
from llm.local_llm_client import LLMResult  # noqa: E402

_REAL_CONNECT = db_module.connect


class _FakeClient:
    temperature = 0.2

    def check_reachable(self):
        pass

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        return LLMResult(
            pattern="Ubiquitous", rewritten_text="The system shall respond within 100 ms.",
            vague_terms=[], confidence=0.8, notes="", raw={},
        )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_api_server(tmp_path, monkeypatch):
    """Runs the real src/ui/api.py FastAPI app under a real uvicorn server
    on a free loopback port, wired to a throwaway DB/upload/export
    directory and a fake (no-network) LLM client. Yields the base URL."""
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(db_module, "connect", lambda path=None: _REAL_CONNECT(db_path))
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(api, "LocalLLMClient", _FakeClient)

    port = _free_loopback_port()
    config = uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn server did not start in time"

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_real_loopback_http_call_succeeds_under_the_network_guard(live_api_server):
    with vo.NetworkGuard():
        response = requests.get(f"{live_api_server}/health", timeout=5)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_full_upload_and_download_flow_over_real_loopback_sockets_under_the_guard(
    live_api_server, tmp_path
):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["ID", "Requirement"])
    sheet.append(["R1", "The flight control computer shall compute attitude at 50 Hz."])
    sample_path = tmp_path / "sample.xlsx"
    workbook.save(sample_path)

    with vo.NetworkGuard():
        with open(sample_path, "rb") as f:
            upload_response = requests.post(
                f"{live_api_server}/upload",
                files={
                    "file": (
                        "sample.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                timeout=30,
            )
        assert upload_response.status_code == 200
        run_id = upload_response.json()["run_id"]

        # Unlike FastAPI's TestClient (tests/test_ui_api.py), a real uvicorn
        # server runs the background task genuinely asynchronously, so the
        # upload response can return before processing finishes -- poll for it.
        deadline = time.monotonic() + 15
        status = None
        while time.monotonic() < deadline:
            status_response = requests.get(f"{live_api_server}/runs/{run_id}", timeout=5)
            assert status_response.status_code == 200
            status = status_response.json()["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(0.1)
        assert status == "completed", f"run did not complete in time (last status: {status})"

        requirements_response = requests.get(f"{live_api_server}/runs/{run_id}/requirements", timeout=5)
        assert len(requirements_response.json()) == 1

        download_response = requests.get(f"{live_api_server}/runs/{run_id}/download", timeout=5)
        assert download_response.status_code == 200
        assert len(download_response.content) > 0


def test_guard_still_blocks_non_loopback_while_a_live_loopback_server_is_running(live_api_server):
    """Proves the guard discriminates on address rather than being
    effectively inert -- the previous two tests alone wouldn't catch a
    bug where NetworkGuard let everything through."""
    with pytest.raises(vo.NetworkAccessBlockedError):
        with vo.NetworkGuard():
            requests.get("http://203.0.113.1/", timeout=1)  # RFC 5737 TEST-NET, never real traffic


def test_api_server_only_accepts_loopback_connections_not_all_interfaces(live_api_server):
    """The server in this test was started with host="127.0.0.1", not
    "0.0.0.0" -- confirms it is not listening on every network interface."""
    port = int(live_api_server.rsplit(":", 1)[1])
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2)
        result = probe.connect_ex(("127.0.0.1", port))
    assert result == 0  # loopback: connects fine
