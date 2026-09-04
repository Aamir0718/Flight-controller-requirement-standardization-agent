"""Verifies the pipeline makes network connections ONLY to loopback or the
one configured LLM endpoint host (config/settings.yaml's llm.base_url) --
builds a small sample requirement sheet, installs a network guard that
raises loudly on any attempted connection to any OTHER address, and runs
the full pipeline (src/pipeline/graph.py: Parse -> RuleFlag ->
ClassifyPattern -> GenerateCandidates -> ScoreAndRecommend -> Finalize)
plus a storage round-trip (src/storage/db.py: save + Excel export)
against it.

This project is no longer air-gapped in the strict "loopback only" sense
-- config/settings.yaml's llm.base_url points at a DRDO-internal vLLM
server, a genuine non-loopback network address, and that is intentional
(see src/llm/local_llm_client.py's module docstring). What this guard
still verifies is the thing that actually matters: nothing in this
codebase or its dependencies silently reaches out to any host OTHER than
that one configured, known endpoint -- no public internet call, no
unexpected third-party service, nothing beyond the single destination
this project is explicitly configured to trust.

IMPORTANT -- what this script can and cannot prove
----------------------------------------------------
This is an automated, in-process, CI-friendly smoke check. Monkeypatching
socket.socket.connect()/connect_ex()/socket.create_connection() in the
current Python process catches every connection routed through Python's
own socket layer -- which is how httpx (and therefore LocalLLMClient),
urllib, and most pure-Python networking gets to the wire -- but it is NOT
an airtight guarantee:

- It cannot see connections opened by a C extension or a subprocess that
  bypasses Python's socket module entirely.
- It cannot detect OS-level network activity (e.g. a background updater)
  outside this process.
- It only guards for the duration this process runs; nothing here proves
  anything about what happens before or after.

This script is REQUIRED before every release (see README.md's pre-release
checklist) as a fast, repeatable, automatable gate -- but it is not a
substitute for the real test: running the application on a machine with
its network cable unplugged (and the LLM endpoint therefore genuinely
unreachable) to confirm the deterministic parts of this project (EARS/
INCOSE analysis, manual edit, Excel export) still work, exactly as
src/llm/local_llm_client.py and src/consistency/analyzer.py are designed
to degrade. A passing run of this script is necessary, not sufficient --
see README.md for the full pre-release checklist.

Usage:
    python scripts/verify_offline.py
"""

from __future__ import annotations

import argparse
import socket
import sys
import tempfile
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import storage.db as db  # noqa: E402
from config import get_settings  # noqa: E402
from llm.local_llm_client import LocalLLMClient, LLMUnavailableError  # noqa: E402
from pipeline.graph import build_graph, run_workbook  # noqa: E402

_LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_loopback_or_allowed(address, allowed_host: str) -> bool:
    """True if ``address`` (a (host, port) tuple, or a bare host string)
    is either the local loopback interface, or the one configured LLM
    endpoint host this guard allows through."""
    host = address[0] if isinstance(address, tuple) else address
    if host in _LOOPBACK_HOSTNAMES or host == allowed_host:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False  # not a literal IP (an unresolved hostname) -- not provably allowed


class NetworkAccessBlockedError(RuntimeError):
    """Raised the instant code under NetworkGuard attempts to open a
    connection to a host that is neither loopback nor the configured LLM
    endpoint -- before any real connection, DNS lookup over the wire, or
    data transfer happens."""


class NetworkGuard:
    """Context manager: for its duration, any attempt to open a socket
    connection to a host other than loopback or ``allowed_host`` raises
    NetworkAccessBlockedError immediately instead of attempting the real
    connection.

    Patches socket.socket.connect/connect_ex and socket.create_connection
    -- the choke points essentially all pure-Python networking (httpx,
    urllib, the stdlib itself) ultimately goes through. See this module's
    docstring for what this can and can't prove.
    """

    def __init__(self, allowed_host: str):
        self.allowed_host = allowed_host

    def __enter__(self) -> "NetworkGuard":
        self._real_connect = socket.socket.connect
        self._real_connect_ex = socket.socket.connect_ex
        self._real_create_connection = socket.create_connection

        def guarded_connect(sock_self, address):
            self._check(address)
            return self._real_connect(sock_self, address)

        def guarded_connect_ex(sock_self, address):
            self._check(address)
            return self._real_connect_ex(sock_self, address)

        def guarded_create_connection(address, *args, **kwargs):
            self._check(address)
            return self._real_create_connection(address, *args, **kwargs)

        socket.socket.connect = guarded_connect
        socket.socket.connect_ex = guarded_connect_ex
        socket.create_connection = guarded_create_connection
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        socket.socket.connect = self._real_connect
        socket.socket.connect_ex = self._real_connect_ex
        socket.create_connection = self._real_create_connection
        return False

    def _check(self, address) -> None:
        if not _is_loopback_or_allowed(address, self.allowed_host):
            raise NetworkAccessBlockedError(
                f"Blocked an outbound connection attempt to {address!r}. This "
                f"project must only ever reach loopback or the one configured "
                f"LLM endpoint host ('{self.allowed_host}', from config/settings.yaml's "
                "llm.base_url -- see README.md). Something just tried to reach "
                "a different, unexpected address."
            )


def _build_sample_workbook(path: Path) -> None:
    """A small, self-contained sample sheet -- not a fixture borrowed from
    tests/, so this script has no dependency on test infrastructure."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Requirements"
    sheet.append(["ID", "Requirement"])
    sheet.append(["REQ-001", "The flight control computer shall compute attitude at 50 Hz."])
    sheet.append(["REQ-002", "While on battery power, the system shall enter low power mode."])
    sheet.append(["REQ-003", "When an overheat condition is detected, the FCC shall shut down the affected channel."])
    workbook.save(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)

    settings = get_settings()
    allowed_host = urlparse(settings["llm"]["base_url"]).hostname
    if not allowed_host:
        print(
            f"ERROR: could not parse a hostname out of llm.base_url "
            f"({settings['llm']['base_url']!r}) in config/settings.yaml.",
            file=sys.stderr,
        )
        return 1

    client = LocalLLMClient()
    try:
        client.check_reachable()
    except LLMUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            f"(The configured LLM endpoint ('{allowed_host}') must be reachable for "
            "this check -- it is the one non-loopback connection this guard allows.)",
            file=sys.stderr,
        )
        return 1

    compiled_graph = build_graph(client=client)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        sample_path = tmp_dir / "sample_requirements.xlsx"
        db_path = tmp_dir / "verify_offline.db"
        export_path = tmp_dir / "verify_offline_export.xlsx"

        _build_sample_workbook(sample_path)

        print(f"Network guard active: only loopback and '{allowed_host}' connections are allowed.")
        print(f"Running the full pipeline against {sample_path.name} ...")

        try:
            with NetworkGuard(allowed_host):
                results = run_workbook(compiled_graph, sample_path)

                conn = db.connect(db_path)
                run_id = db.save_pipeline_run(
                    conn, file_name=sample_path.name, results=results, file_path=sample_path
                )
                db.export_run_to_excel(conn, run_id, export_path)
                conn.close()
        except NetworkAccessBlockedError as exc:
            print(f"\nFAIL: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 -- report clearly, don't leave a bare traceback
            print(f"\nFAIL: pipeline raised {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    print(
        f"\nPASS: processed {len(results)} requirement(s); no connections outside "
        f"loopback / '{allowed_host}' were attempted."
    )
    print(
        "Reminder: this is an in-process check, not a substitute for physically "
        "disconnecting the network to confirm the deterministic parts of this "
        "project still work with the LLM endpoint genuinely unreachable -- see "
        "README.md's pre-release checklist."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
