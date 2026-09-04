"""Tests for src/ui/streamlit_app.py.

Pure helper functions (_build_summary_table, _highlight_needs_review) are
tested directly. Full-page rendering is tested with Streamlit's official
streamlit.testing.v1.AppTest, which executes the real script -- so all
`requests.get`/`requests.post` calls it makes are monkeypatched to a small
in-memory fake backend instead of hitting a real API process. No real
network call, no real API server, no real Ollama needed anywhere here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import ui.streamlit_app as app

APP_PATH = str(Path(__file__).resolve().parent.parent / "src" / "ui" / "streamlit_app.py")


def _requirement(
    sequence_in_run=0,
    original_text="While in orbit, the star tracker shall track reference stars continuously.",
    recommended_index=1,
    needs_human_review=False,
    vague_term_suggestions=None,
    has_invented_number=False,
):
    candidates = [
        {"index": 0, "rewritten_text": "candidate zero", "score": 80.0, "has_invented_number": False},
        {"index": 1, "rewritten_text": "candidate one (the good one)", "score": 96.4,
         "has_invented_number": has_invented_number},
        {"index": 2, "rewritten_text": "candidate two", "score": 70.0, "has_invented_number": False},
    ]
    return {
        "sequence_in_run": sequence_in_run,
        "original_text": original_text,
        "ears_pattern": {"pattern": "State-driven"},
        "candidates": candidates,
        "recommended_index": recommended_index,
        "recommended_text": candidates[recommended_index]["rewritten_text"],
        "needs_human_review": needs_human_review,
        "vague_term_suggestions": vague_term_suggestions or [],
    }


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


class TestApiBaseUrl:
    def test_always_uses_loopback_regardless_of_configured_bind_host(self):
        # config/settings.yaml's ui.api_host may be "0.0.0.0" (a bind
        # address); the client must always target 127.0.0.1.
        assert app.API_BASE_URL.startswith("http://127.0.0.1:")

    def test_uses_configured_port(self):
        from config import get_settings

        expected_port = get_settings()["ui"]["api_port"]
        assert app.API_BASE_URL == f"http://127.0.0.1:{expected_port}"


class TestBuildSummaryTable:
    def test_produces_one_row_per_requirement(self):
        table = app._build_summary_table([_requirement(sequence_in_run=0), _requirement(sequence_in_run=1)])
        assert len(table) == 2
        assert list(table["#"]) == [1, 2]

    def test_recommended_candidate_column_is_marked(self):
        table = app._build_summary_table([_requirement(recommended_index=1)])
        row = table.iloc[0]
        assert row["Candidate 2"].startswith("⭐ ")
        assert not row["Candidate 1"].startswith("⭐ ")
        assert not row["Candidate 3"].startswith("⭐ ")

    def test_needs_review_column_reflects_the_flag(self):
        table = app._build_summary_table([_requirement(needs_human_review=True)])
        assert table.iloc[0]["Needs Review"] == "Yes"
        table2 = app._build_summary_table([_requirement(needs_human_review=False)])
        assert table2.iloc[0]["Needs Review"] == "No"

    def test_suggestions_are_joined_or_show_placeholder(self):
        with_suggestion = app._build_summary_table(
            [_requirement(vague_term_suggestions=[{"term": "fast", "suggestion": "give a number"}])]
        )
        assert with_suggestion.iloc[0]["Suggestions"] == "fast: give a number"

        without = app._build_summary_table([_requirement(vague_term_suggestions=[])])
        assert without.iloc[0]["Suggestions"] == "(none)"

    def test_original_text_and_ears_pattern_columns(self):
        table = app._build_summary_table([_requirement(original_text="The gateway shall log events.")])
        assert table.iloc[0]["Original Requirement"] == "The gateway shall log events."
        assert table.iloc[0]["EARS Pattern"] == "State-driven"


class TestHighlightNeedsReview:
    def test_needs_review_row_gets_red_background(self):
        row = pd.Series({"Needs Review": "Yes", "Other": "x"})
        styles = app._highlight_needs_review(row)
        assert all(app.NEEDS_REVIEW_COLOR in s for s in styles)
        assert len(styles) == len(row)

    def test_ok_row_gets_green_background(self):
        row = pd.Series({"Needs Review": "No", "Other": "x"})
        styles = app._highlight_needs_review(row)
        assert all(app.OK_COLOR in s for s in styles)


# ---------------------------------------------------------------------------
# Full-page rendering via AppTest
# ---------------------------------------------------------------------------


def _fake_get_factory(runs_by_id: dict, requirements_by_run_id: dict, download_bytes: bytes = b"fake-xlsx"):
    def fake_get(url, timeout=30, **kwargs):
        resp = MagicMock()
        if url.endswith("/health"):
            resp.status_code = 200
            resp.json.return_value = {"status": "ok"}
        elif url.endswith("/runs"):
            resp.status_code = 200
            resp.json.return_value = list(runs_by_id.values())
        elif "/download" in url:
            run_id = int(url.rsplit("/runs/", 1)[1].split("/")[0])
            run = runs_by_id.get(run_id)
            if run is None or run["status"] != "completed":
                resp.status_code = 409
            else:
                resp.status_code = 200
                resp.content = download_bytes
        elif url.endswith("/requirements"):
            run_id = int(url.rsplit("/runs/", 1)[1].split("/")[0])
            resp.status_code = 200
            resp.json.return_value = requirements_by_run_id.get(run_id, [])
        elif "/runs/" in url:
            run_id = int(url.rsplit("/runs/", 1)[1])
            run = runs_by_id.get(run_id)
            resp.status_code = 200 if run else 404
            if run:
                resp.json.return_value = run
        return resp

    return fake_get


def _unreachable_get(url, timeout=30, **kwargs):
    import requests

    raise requests.exceptions.ConnectionError("simulated: nothing listening")


class TestAppRendering:
    def test_shows_error_when_api_unreachable(self):
        with patch("requests.get", side_effect=_unreachable_get):
            at = AppTest.from_file(APP_PATH)
            at.run()
        assert not at.exception
        assert any("Can't reach the API backend" in e.value for e in at.error)

    def test_shows_prompt_when_no_run_yet(self):
        fake_get = _fake_get_factory(runs_by_id={}, requirements_by_run_id={})
        with patch("requests.get", side_effect=fake_get):
            at = AppTest.from_file(APP_PATH)
            at.run()
        assert not at.exception
        assert any("Upload a spreadsheet" in i.value for i in at.info)

    def test_sidebar_lists_previous_runs(self):
        runs = {1: {"id": 1, "file_name": "a.xlsx", "status": "completed"}}
        fake_get = _fake_get_factory(runs_by_id=runs, requirements_by_run_id={})
        with patch("requests.get", side_effect=fake_get):
            at = AppTest.from_file(APP_PATH)
            at.run()
        assert not at.exception
        sidebar_buttons = [b.label for b in at.sidebar.button]
        assert any("a.xlsx" in label for label in sidebar_buttons)

    def test_completed_run_renders_table_and_expanders_and_download(self):
        requirements = [
            _requirement(sequence_in_run=0, needs_human_review=False),
            _requirement(sequence_in_run=1, needs_human_review=True,
                        vague_term_suggestions=[{"term": "fast", "suggestion": "give a number"}]),
        ]
        runs = {5: {"id": 5, "file_name": "reqs.xlsx", "status": "completed",
                    "requirement_count": 2, "total_requirements": 2, "error_message": None}}
        fake_get = _fake_get_factory(runs_by_id=runs, requirements_by_run_id={5: requirements})

        with patch("requests.get", side_effect=fake_get):
            at = AppTest.from_file(APP_PATH)
            at.session_state["run_id"] = 5
            at.run()

        assert not at.exception
        assert len(at.dataframe) == 1
        assert len(at.expander) == 2
        assert len(at.download_button) == 1
        # the needs-review requirement's error banner and suggestion text render
        assert any("needs human review" in e.value.lower() for e in at.error)
        assert any("give a number" in m.value for m in at.markdown)

    def test_failed_run_shows_error_with_reason(self):
        runs = {7: {"id": 7, "file_name": "bad.xlsx", "status": "failed",
                    "requirement_count": 0, "total_requirements": 3,
                    "error_message": "LLMUnavailableError: simulated"}}
        fake_get = _fake_get_factory(runs_by_id=runs, requirements_by_run_id={})

        with patch("requests.get", side_effect=fake_get):
            at = AppTest.from_file(APP_PATH)
            at.session_state["run_id"] = 7
            at.run()

        assert not at.exception
        assert any("LLMUnavailableError" in e.value for e in at.error)

    def test_unknown_run_id_shows_not_found(self):
        fake_get = _fake_get_factory(runs_by_id={}, requirements_by_run_id={})
        with patch("requests.get", side_effect=fake_get):
            at = AppTest.from_file(APP_PATH)
            at.session_state["run_id"] = 999
            at.run()
        assert not at.exception
        assert any("not found" in e.value.lower() for e in at.error)
