"""Tests for src/ui/api.py, using FastAPI's TestClient with a fake LLM
client (no real Ollama needed) and a throwaway per-test SQLite database
and upload/export directory -- never touches the real data/app.db.

POST /upload is now purely deterministic (analyze_requirement() for every
row, no LLM at all) and runs synchronously in the request itself -- no
LocalLLMClient involved, no background task, nothing to poll. Only POST
/runs/{run_id}/requirements/generate touches an LLM client, via a
background task; FastAPI's TestClient runs BackgroundTasks synchronously
as part of the request/response cycle (confirmed empirically), so that
endpoint has also already finished by the time the test client gets its
response back -- no polling loop needed in these tests either.
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
# /upload -- purely deterministic now (analyze_requirement() for every
# row, no LLM), so none of these need a LocalLLMClient at all.
# ---------------------------------------------------------------------------


class TestUpload:
    def test_rejects_non_xlsx_files(self, api_env):
        client, _ = api_env
        response = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
        assert response.status_code == 400

    def test_happy_path_analyzes_and_completes_with_no_llm_involved(self, api_env, monkeypatch):
        client, tmp_path = api_env
        # If /upload tried to touch an LLM client at all, this would raise --
        # confirms analysis really is LLM-free, not just "didn't happen to fail".
        monkeypatch.setattr(api, "LocalLLMClient", _FakeUnreachableClient)

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

    def test_uploaded_file_bytes_are_persisted(self, api_env):
        client, tmp_path = api_env
        _upload(client)
        saved_files = list((tmp_path / "uploads").glob("*sample.xlsx"))
        assert len(saved_files) == 1
        assert saved_files[0].stat().st_size > 0

    def test_corrupt_workbook_marks_run_failed_with_friendly_code(self, api_env):
        client, _ = api_env
        corrupt_bytes = (Path(__file__).resolve().parent / "fixtures" / "corrupt_file.xlsx").read_bytes()
        run_id = _upload(client, filename="corrupt_file.xlsx", content=corrupt_bytes).json()["run_id"]
        run = client.get(f"/runs/{run_id}").json()

        assert run["status"] == "failed"
        assert run["error_message"] == api.INVALID_EXCEL_FILE
        assert "RuntimeError" not in (run["error_message"] or "")
        assert "BadZipFile" not in (run["error_message"] or "")


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/requirements/generate -- the only endpoint that ever
# touches an LLM client, and only for the ids a human selected.
# ---------------------------------------------------------------------------


class TestGenerateRequirements:
    def test_happy_path_generates_only_the_selected_requirement(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        run_id = _upload(client).json()["run_id"]
        requirements = client.get(f"/runs/{run_id}/requirements").json()
        target_id, other_id = requirements[0]["id"], requirements[1]["id"]

        response = client.post(
            f"/runs/{run_id}/requirements/generate", json={"requirement_ids": [target_id]}
        )
        assert response.status_code == 200

        updated = {r["id"]: r for r in client.get(f"/runs/{run_id}/requirements").json()}
        assert updated[target_id]["status"] == "generated"
        assert len(updated[target_id]["candidates"]) == 3
        # the other requirement was never touched
        assert updated[other_id]["status"] == "analyzed"
        assert updated[other_id]["candidates"] == []

    def test_select_all_generates_every_requirement(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        run_id = _upload(client).json()["run_id"]
        ids = [r["id"] for r in client.get(f"/runs/{run_id}/requirements").json()]

        client.post(f"/runs/{run_id}/requirements/generate", json={"requirement_ids": ids})

        for req in client.get(f"/runs/{run_id}/requirements").json():
            assert req["status"] == "generated"
            assert len(req["candidates"]) == 3

    def test_ollama_unreachable_marks_selected_requirements_failed(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeUnreachableClient)
        run_id = _upload(client).json()["run_id"]
        ids = [r["id"] for r in client.get(f"/runs/{run_id}/requirements").json()]

        client.post(f"/runs/{run_id}/requirements/generate", json={"requirement_ids": ids})

        for req in client.get(f"/runs/{run_id}/requirements").json():
            assert req["status"] == "failed"
            assert req["error_message"] == api.AI_SERVICE_UNAVAILABLE

    def test_llm_crash_marks_that_requirement_failed_with_reason(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeCrashesMidGenerationClient)
        run_id = _upload(client).json()["run_id"]
        target_id = client.get(f"/runs/{run_id}/requirements").json()[0]["id"]

        client.post(f"/runs/{run_id}/requirements/generate", json={"requirement_ids": [target_id]})

        req = client.get(f"/runs/{run_id}/requirements").json()[0]
        assert req["status"] == "failed"
        assert req["error_message"] is not None

    def test_unknown_run_id_returns_404(self, api_env):
        client, _ = api_env
        response = client.post("/runs/999/requirements/generate", json={"requirement_ids": [1]})
        assert response.status_code == 404

    def test_unknown_requirement_id_returns_404(self, api_env, monkeypatch):
        client, _ = api_env
        monkeypatch.setattr(api, "LocalLLMClient", _FakeWorkingClient)
        run_id = _upload(client).json()["run_id"]
        response = client.post(f"/runs/{run_id}/requirements/generate", json={"requirement_ids": [999999]})
        assert response.status_code == 404

    def test_empty_selection_returns_400(self, api_env):
        client, _ = api_env
        run_id = _upload(client).json()["run_id"]
        response = client.post(f"/runs/{run_id}/requirements/generate", json={"requirement_ids": []})
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# PUT /runs/{run_id}/requirements/{requirement_id} -- manual edit, no LLM.
# ---------------------------------------------------------------------------


class TestEditRequirement:
    def test_happy_path_updates_text_and_rescopes_deterministically(self, api_env):
        client, _ = api_env
        run_id = _upload(client).json()["run_id"]
        target_id = client.get(f"/runs/{run_id}/requirements").json()[0]["id"]
        new_text = "When the fuel level drops below reserve, the system shall alert the pilot."

        response = client.put(
            f"/runs/{run_id}/requirements/{target_id}", json={"recommended_text": new_text}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "edited"
        assert body["recommended_text"] == new_text
        assert body["recommended_index"] == -1
        assert body["needs_human_review"] is False
        assert body["candidates"] == []  # no LLM was ever involved

    def test_empty_text_returns_400(self, api_env):
        client, _ = api_env
        run_id = _upload(client).json()["run_id"]
        target_id = client.get(f"/runs/{run_id}/requirements").json()[0]["id"]
        response = client.put(f"/runs/{run_id}/requirements/{target_id}", json={"recommended_text": "   "})
        assert response.status_code == 400

    def test_unknown_requirement_id_returns_404(self, api_env):
        client, _ = api_env
        run_id = _upload(client).json()["run_id"]
        response = client.put(f"/runs/{run_id}/requirements/999999", json={"recommended_text": "x shall y."})
        assert response.status_code == 404

    def test_requirement_from_a_different_run_returns_404(self, api_env):
        client, _ = api_env
        run_1 = _upload(client).json()["run_id"]
        run_2 = _upload(client).json()["run_id"]
        req_from_run_1 = client.get(f"/runs/{run_1}/requirements").json()[0]["id"]

        response = client.put(
            f"/runs/{run_2}/requirements/{req_from_run_1}", json={"recommended_text": "x shall y."}
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# /runs, /runs/{id}, /runs/{id}/requirements
# ---------------------------------------------------------------------------


class TestRunsEndpoints:
    def test_list_runs_includes_uploaded_run(self, api_env):
        client, _ = api_env
        run_id = _upload(client).json()["run_id"]

        runs = client.get("/runs").json()
        assert any(r["id"] == run_id for r in runs)

    def test_unknown_run_id_returns_404(self, api_env):
        client, _ = api_env
        assert client.get("/runs/999").status_code == 404
        assert client.get("/runs/999/requirements").status_code == 404
        assert client.get("/runs/999/download").status_code == 404

    def test_requirements_endpoint_returns_the_analysis_trace_with_no_candidates_yet(self, api_env):
        client, _ = api_env
        run_id = _upload(client).json()["run_id"]

        requirements = client.get(f"/runs/{run_id}/requirements").json()
        assert len(requirements) == 2
        for req in requirements:
            assert req["original_text"]
            assert req["status"] == "analyzed"
            assert req["candidates"] == []  # nothing generated until a human asks
            assert req["recommended_index"] == -1
            assert "recommended_score" in req  # the real INCOSE score is there already
            assert "violations" in req
            assert req["needs_human_review"] is True  # nothing resolved yet
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

    def test_download_returns_a_valid_workbook_right_after_upload_before_any_generation(self, api_env):
        # The point of the two-phase split: export must work as soon as
        # analysis is done, with no LLM call and nothing generated yet.
        client, _ = api_env
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
