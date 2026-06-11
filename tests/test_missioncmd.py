"""Handler unit tests for `cairn mission` (missioncmd http server).

Pattern: run the real ThreadingHTTPServer on port 0 (ephemeral) in a daemon
thread, issue requests with http.client (which sends paths verbatim — no
client-side normalization that would mask traversal attempts), shut down.
"""
import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cairn_core import board, missioncmd, vaultio  # noqa: E402


# --- fixtures ----------------------------------------------------------------

def _scaffold(tmp_path):
    """Minimal .cairn with two board entries and a few vault bullets."""
    cairn = tmp_path / ".cairn"
    (cairn / "vault").mkdir(parents=True)
    board.add_entry(cairn, {"id": "T1", "schema": True, "produces": ["ConfigSchema"]})
    board.add_entry(cairn, {"id": "T2", "depends_on": ["T1"],
                            "consumes": ["ConfigSchema"], "status": "in-progress",
                            "branch": "cairn/T2"})
    for i in range(7):
        vaultio.append(cairn, "decisions", f"decision number {i}")
    vaultio.append(cairn, "issues", "one known issue")
    return cairn


@pytest.fixture()
def server(tmp_path):
    cairn = _scaffold(tmp_path)
    httpd = missioncmd.make_server(cairn, port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _get(httpd, path, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    try:
        conn.putrequest(method, path, skip_host=False)  # path sent verbatim
        conn.endheaders()
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


# --- /api/board ----------------------------------------------------------------

def test_api_board_returns_valid_json(server):
    status, headers, body = _get(server, "/api/board")
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    data = json.loads(body)
    assert {e["id"] for e in data["entries"]} == {"T1", "T2"}
    assert "error" not in data


def test_api_board_synthesizes_dag_from_entries(server):
    _, _, body = _get(server, "/api/board")
    dag = {n["id"]: n for n in json.loads(body)["dag"]}
    assert dag["T1"]["schema"] is True
    assert dag["T1"]["produces"] == ["ConfigSchema"]
    assert dag["T2"]["deps"] == ["T1"]
    assert dag["T2"]["consumes"] == ["ConfigSchema"]


def test_api_board_vault_tail_last_five(server):
    _, _, body = _get(server, "/api/board")
    tail = json.loads(body)["vault_tail"]
    assert len(tail["decisions"]) == 5            # 7 appended, tail of 5
    assert tail["decisions"][-1].endswith("decision number 6")
    assert len(tail["issues"]) == 1


def test_api_board_graceful_on_empty_cairn(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir()                                  # no board.jsonl, no vault/
    httpd = missioncmd.make_server(cairn, port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        _, _, body = _get(httpd, "/api/board")
        data = json.loads(body)
        assert data["entries"] == [] and data["dag"] == []
        assert data["vault_tail"] == {"decisions": [], "issues": []}
    finally:
        httpd.shutdown(); httpd.server_close()


def test_api_board_invalid_board_reports_error_not_500(tmp_path):
    cairn = tmp_path / ".cairn"
    cairn.mkdir()
    (cairn / "board.jsonl").write_text("not json\n")
    httpd = missioncmd.make_server(cairn, port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        status, _, body = _get(httpd, "/api/board")
        data = json.loads(body)
        assert status == 200 and data["entries"] == [] and data["error"]
    finally:
        httpd.shutdown(); httpd.server_close()


# --- static serving + traversal -------------------------------------------------

def test_static_index_served(server):
    status, headers, body = _get(server, "/")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"CAIRN" in body


def test_static_js_served(server):
    status, headers, _ = _get(server, "/live.js")
    assert status == 200
    assert headers["Content-Type"].startswith("text/javascript")


@pytest.mark.parametrize("path", [
    "/../bin/cairn",                       # plain dot-dot
    "/../../etc/passwd",                   # deeper dot-dot
    "/%2e%2e/%2e%2e/etc/passwd",           # URL-encoded dot-dot
    "/..%2f..%2fetc%2fpasswd",             # encoded slash variant
    "/%2e%2e%2f%2e%2e%2fbin%2fcairn",      # fully encoded
    "//etc/passwd",                        # absolute-looking
    "/etc/passwd",                         # absolute under root -> missing
    "/..\\..\\windows",                    # backslash variant
])
def test_static_traversal_rejected(server, path):
    status, _, body = _get(server, path)
    assert status in (403, 404), (path, status)
    assert b"root:" not in body and b"def serve" not in body


def test_static_unknown_suffix_404(server, tmp_path):
    status, _, _ = _get(server, "/nope.py")
    assert status == 404


# --- bind + read-only ------------------------------------------------------------

def test_server_binds_localhost_only(server):
    assert server.server_address[0] == "127.0.0.1"


def test_post_is_rejected(server):
    status, _, _ = _get(server, "/api/board", method="POST")
    assert status == 501                            # read-only: GET only


# --- pure helpers ----------------------------------------------------------------

def test_synthesize_dag_filters_unknown_and_self_deps():
    entries = [{"id": "A", "depends_on": ["A", "ghost", "B"]}, {"id": "B"}]
    dag = {n["id"]: n for n in missioncmd.synthesize_dag(entries)}
    assert dag["A"]["deps"] == ["B"]


def test_resolve_static_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.html"
    outside.write_text("<html>secret</html>")
    mission = tmp_path / "mission"
    mission.mkdir()
    (mission / "leak.html").symlink_to(outside)
    status, real = missioncmd.resolve_static(mission, "/leak.html")
    assert status == 403 and real is None
