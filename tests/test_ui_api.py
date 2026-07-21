"""Tests for src/ui/api.py, using FastAPI's TestClient with a fake LLM
client (no real Ollama needed) and a throwaway per-test SQLite database
and upload/export directory -- never touches the real data/app.db.

FastAPI's TestClient runs BackgroundTasks synchronously as part of the
request/response cycle (confirmed empirically), so `POST /upload` has
already finished processing by the time the test client gets its
response back -- no polling loop needed in these tests.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

import storage.db as db_module
import ui.api as api

from llm.local_llm_client import LLMResult, OllamaUnavailableError

_REAL_CONNECT = db_module.connect


class _FakeWorkingClient:
    temperature = 0.2

    def check_reachable(self):
        pass

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        return LLMResult(
            pattern="Ubiquitous", rewritten_text="The system shall respond within 100 ms.",
            vague_terms=[], confidence=0.8, notes="", raw={},
        )


class _FakeUnreachableClient:
    def check_reachable(self):
        raise OllamaUnavailableError("simulated: Ollama not reachable")


class _FakeCrashesMidGenerationClient:
    temperature = 0.2
    calls = 0

    def check_reachable(self):
        pass

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        raise RuntimeError("simulated model crash")


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """Points api.py's DB connection, upload dir, and export dir at
    throwaway tmp_path locations, and returns (client, upload_dir)."""
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(db_module, "connect", lambda path=None: _REAL_CONNECT(db_path))
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api, "EXPORT_DIR", tmp_path / "exports")
    return TestClient(api.app), tmp_path


def _sample_workbook_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Requirement"])
    ws.append(["R1", "The flight control computer shall compute attitude at 50 Hz."])
    ws.append(["R2", "While on battery power, the system shall enter low power mode."])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _upload(client: TestClient, filename: str = "sample.xlsx", content: bytes | None = None):
    content = content if content is not None else _sample_workbook_bytes()
    return client.post(
        "/upload",
        files={"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(api_env):
    client, _ = api_env
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /upload
# ---------------------------------------------------------------------------


class TestUpload:
    def test_rejects_non_xlsx_files(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        response = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
        assert response.status_code == 400

    def test_happy_path_processes_and_completes(self, api_env, monkeypatch):
        client, tmp_path = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)

        response = _upload(client)
        assert response.status_code == 200
        body = response.json()
        assert "run_id" in body

        run = client.get(f"/runs/{body['run_id']}").json()
        assert run["status"] == "completed"
        assert run["total_requirements"] == 2
        assert run["requirement_count"] == 2
        assert run["error_message"] is None
        assert run["file_name"] == "sample.xlsx"

    def test_uploaded_file_bytes_are_persisted(self, api_env, monkeypatch):
        client, tmp_path = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        _upload(client)
        saved_files = list((tmp_path / "uploads").glob("*sample.xlsx"))
        assert len(saved_files) == 1
        assert saved_files[0].stat().st_size > 0

    def test_ollama_unreachable_marks_run_failed(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeUnreachableClient)

        run_id = _upload(client).json()["run_id"]
        run = client.get(f"/runs/{run_id}").json()

        assert run["status"] == "failed"
        assert "OllamaUnavailableError" in run["error_message"]

    def test_llm_crash_marks_run_failed_with_reason(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeCrashesMidGenerationClient)

        run_id = _upload(client).json()["run_id"]
        run = client.get(f"/runs/{run_id}").json()

        assert run["status"] == "failed"
        assert "RuntimeError" in run["error_message"]
        # total_requirements was set (parsing succeeded) even though generation failed
        assert run["total_requirements"] == 2


# ---------------------------------------------------------------------------
# /runs, /runs/{id}, /runs/{id}/requirements
# ---------------------------------------------------------------------------


class TestRunsEndpoints:
    def test_list_runs_includes_uploaded_run(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        run_id = _upload(client).json()["run_id"]

        runs = client.get("/runs").json()
        assert any(r["id"] == run_id for r in runs)

    def test_unknown_run_id_returns_404(self, api_env):
        client, _ = api_env
        assert client.get("/runs/999").status_code == 404
        assert client.get("/runs/999/requirements").status_code == 404
        assert client.get("/runs/999/download").status_code == 404

    def test_requirements_endpoint_returns_full_pipeline_trace(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        run_id = _upload(client).json()["run_id"]

        requirements = client.get(f"/runs/{run_id}/requirements").json()
        assert len(requirements) == 2
        for req in requirements:
            assert req["original_text"]
            assert len(req["candidates"]) == 3
            assert "recommended_index" in req
            assert "needs_human_review" in req
            assert "vague_term_suggestions" in req


# ---------------------------------------------------------------------------
# /runs/{id}/download
# ---------------------------------------------------------------------------


class TestDownload:
    def test_download_before_completion_returns_409(self, api_env):
        client, _ = api_env
        conn = db_module.connect()
        run_id = db_module.create_run(conn, file_name="pending.xlsx")
        conn.close()

        response = client.get(f"/runs/{run_id}/download")
        assert response.status_code == 409

    def test_download_returns_a_valid_workbook(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        run_id = _upload(client).json()["run_id"]

        response = client.get(f"/runs/{run_id}/download")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        workbook = load_workbook(io.BytesIO(response.content))
        sheet = workbook.active
        assert sheet.max_row == 3  # header + 2 requirements
        assert sheet.cell(row=1, column=1).value == "#"
