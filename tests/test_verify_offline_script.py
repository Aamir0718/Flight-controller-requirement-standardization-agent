"""Tests for scripts/verify_offline.py.

No real network connectivity is required: the "blocked" tests attempt a
connection to a TEST-NET-3 address (203.0.113.0/24, RFC 5737 -- reserved
for documentation, guaranteed unroutable) inside NetworkGuard, which must
raise before any real connection attempt happens, so these are fast and
deterministic regardless of the test machine's actual network state. The
"allowed" tests use a real loopback server to prove the guard doesn't
also break the one connection it's supposed to let through.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import verify_offline as vo  # noqa: E402

from ingestion.parser import parse_workbook  # noqa: E402
from llm.local_llm_client import LLMResult, LLMUnavailableError  # noqa: E402

NON_ROUTABLE_ADDRESS = ("203.0.113.1", 80)  # RFC 5737 TEST-NET-3, never real traffic


_DUMMY_ALLOWED_HOST = "vllm.internal.example"


class _FakeQuietClient:
    """Never touches a socket -- simulates a well-behaved LLM client."""

    temperature = 0.2

    def check_reachable(self):
        pass

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        return LLMResult(
            pattern="Ubiquitous", rewritten_text="The system shall respond within 100 ms.",
            vague_terms=[], confidence=0.8, notes="", raw={},
        )


class _FakeMisbehavingClient:
    """Simulates a dependency that tries to phone home -- this is exactly
    what NetworkGuard exists to catch."""

    temperature = 0.2

    def check_reachable(self):
        pass

    def generate_structured(self, system_prompt, user_prompt, *, temperature=None, seed=None):
        socket.create_connection(NON_ROUTABLE_ADDRESS, timeout=1)  # never reached: guard blocks first
        raise AssertionError("unreachable")


class _RaisesUnavailableClient:
    def check_reachable(self):
        raise LLMUnavailableError("simulated: LLM endpoint not reachable")


# ---------------------------------------------------------------------------
# _is_loopback_or_allowed
# ---------------------------------------------------------------------------


class TestIsLoopbackOrAllowed:
    @pytest.mark.parametrize("address", [
        "127.0.0.1", "localhost", "::1", "0.0.0.0",
        ("127.0.0.1", 11434), ("localhost", 11434), ("::1", 8080),
        "127.255.255.255",  # entire 127.0.0.0/8 is loopback
    ])
    def test_recognizes_loopback_addresses_regardless_of_allowed_host(self, address):
        assert vo._is_loopback_or_allowed(address, _DUMMY_ALLOWED_HOST) is True

    @pytest.mark.parametrize("address", [
        "203.0.113.1", "8.8.8.8", ("203.0.113.1", 80), "example.com",
        ("api.openai.com", 443), "2001:db8::1",
    ])
    def test_rejects_addresses_that_are_neither_loopback_nor_the_allowed_host(self, address):
        assert vo._is_loopback_or_allowed(address, _DUMMY_ALLOWED_HOST) is False

    def test_recognizes_the_configured_allowed_host_itself(self):
        assert vo._is_loopback_or_allowed(_DUMMY_ALLOWED_HOST, _DUMMY_ALLOWED_HOST) is True
        assert vo._is_loopback_or_allowed((_DUMMY_ALLOWED_HOST, 8001), _DUMMY_ALLOWED_HOST) is True

    def test_a_different_host_is_still_rejected_even_if_similar(self):
        assert vo._is_loopback_or_allowed("evil-" + _DUMMY_ALLOWED_HOST, _DUMMY_ALLOWED_HOST) is False


# ---------------------------------------------------------------------------
# NetworkGuard
# ---------------------------------------------------------------------------


class TestNetworkGuard:
    def test_blocks_connect_to_non_loopback_address(self):
        with pytest.raises(vo.NetworkAccessBlockedError, match="203.0.113.1"):
            with vo.NetworkGuard(_DUMMY_ALLOWED_HOST):
                socket.create_connection(NON_ROUTABLE_ADDRESS, timeout=1)

    def test_blocks_raw_socket_connect_to_non_loopback_address(self):
        with pytest.raises(vo.NetworkAccessBlockedError):
            with vo.NetworkGuard(_DUMMY_ALLOWED_HOST):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.connect(NON_ROUTABLE_ADDRESS)
                finally:
                    s.close()

    def test_allows_loopback_connection_through(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def accept_once():
            conn, _ = server.accept()
            conn.close()

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        try:
            with vo.NetworkGuard(_DUMMY_ALLOWED_HOST):
                client_sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                client_sock.close()
        finally:
            thread.join(timeout=2)
            server.close()
        # reaching here without NetworkAccessBlockedError is the assertion

    def test_restores_original_socket_methods_after_normal_exit(self):
        original_connect = socket.socket.connect
        original_create_connection = socket.create_connection
        with vo.NetworkGuard(_DUMMY_ALLOWED_HOST):
            pass
        assert socket.socket.connect is original_connect
        assert socket.create_connection is original_create_connection

    def test_restores_original_socket_methods_after_exception(self):
        original_connect = socket.socket.connect
        original_create_connection = socket.create_connection
        with pytest.raises(vo.NetworkAccessBlockedError):
            with vo.NetworkGuard(_DUMMY_ALLOWED_HOST):
                socket.create_connection(NON_ROUTABLE_ADDRESS, timeout=1)
        assert socket.socket.connect is original_connect
        assert socket.create_connection is original_create_connection

    def test_does_not_attempt_a_real_connection_before_blocking(self):
        # If this actually tried to connect, a 1-second timeout to an
        # unroutable test address would make this test slow; asserting it
        # completes near-instantly is itself evidence the real connect()
        # was never called.
        import time

        start = time.monotonic()
        with pytest.raises(vo.NetworkAccessBlockedError):
            with vo.NetworkGuard(_DUMMY_ALLOWED_HOST):
                socket.create_connection(NON_ROUTABLE_ADDRESS, timeout=1)
        assert time.monotonic() - start < 0.5


# ---------------------------------------------------------------------------
# Sample workbook
# ---------------------------------------------------------------------------


def test_build_sample_workbook_produces_3_parseable_requirements(tmp_path):
    sample_path = tmp_path / "sample.xlsx"
    vo._build_sample_workbook(sample_path)

    result = parse_workbook(sample_path)
    assert not result.issues
    assert len(result.candidates) == 3
    assert all("shall" in c.text for c in result.candidates)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_fails_fast_when_ollama_unreachable(self, monkeypatch, capsys):
        monkeypatch.setattr(vo, "LocalLLMClient", _RaisesUnavailableClient)
        exit_code = vo.main([])
        assert exit_code == 1
        assert "ERROR" in capsys.readouterr().err

    def test_passes_end_to_end_with_a_well_behaved_client(self, monkeypatch, capsys):
        monkeypatch.setattr(vo, "LocalLLMClient", _FakeQuietClient)
        exit_code = vo.main([])
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "PASS" in out
        assert "3 requirement" in out

    def test_fails_loudly_when_a_dependency_attempts_a_non_loopback_connection(self, monkeypatch, capsys):
        monkeypatch.setattr(vo, "LocalLLMClient", _FakeMisbehavingClient)
        exit_code = vo.main([])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "FAIL" in captured.err
        assert "203.0.113.1" in captured.err

    def test_socket_methods_are_restored_even_after_main_reports_a_block(self, monkeypatch):
        original_connect = socket.socket.connect
        monkeypatch.setattr(vo, "LocalLLMClient", _FakeMisbehavingClient)
        vo.main([])
        assert socket.socket.connect is original_connect
