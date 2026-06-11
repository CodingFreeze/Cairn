"""`cairn mission` — live dashboard server (localhost-only, read-only).

Serves the static dashboard in mission/ plus one JSON endpoint, GET /api/board:
    {entries: [...board.jsonl...],
     dag: synthesized from entries (deps/produces/consumes/schema),
     vault_tail: last 5 decisions + issues bullets}

SECURITY model:
  - Binds 127.0.0.1 ONLY — never exposed on the network.
  - Read-only: only GET is implemented (http.server answers 501 otherwise).
  - Static paths resolve via realpath and must stay under the mission/ dir
    (traversal / absolute / encoded attempts -> 403/404). Only an allowlisted
    set of file suffixes is served.
  - Board/vault reads go through board.read_board / vaultio's safe_open_read,
    so the symlink/escape guards of the control plane apply here too.
"""
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from cairn_core import board, vaultio
from cairn_core.safepath import safe_open_read

MISSION_DIR = Path(__file__).resolve().parent.parent.parent / "mission"
VAULT_TAIL_N = 5

# Suffix allowlist for static serving — anything else is 404 (no dotfiles,
# no source maps, nothing surprising).
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".md": "text/plain; charset=utf-8",
}


def synthesize_dag(entries):
    """Build the graph payload the dashboard renders from board entries.

    deps are filtered to ids present on the board (the client also sanitizes,
    but never ship an edge to a node that does not exist).
    """
    ids = {e["id"] for e in entries}
    dag = []
    for e in entries:
        deps = [d for d in e.get("depends_on", []) if d in ids and d != e["id"]]
        dag.append({
            "id": e["id"],
            "title": e.get("owner") or "",
            "deps": deps,
            "schema": bool(e.get("schema", False)),
            "produces": list(e.get("produces", [])),
            "consumes": list(e.get("consumes", [])),
        })
    return dag


def _tail_bullets(cairn_dir, name, limit=VAULT_TAIL_N):
    """Last `limit` bullet lines of a vault file ([] when absent/empty)."""
    try:
        p = vaultio.resolve_vault_file(cairn_dir, name)
        if not os.path.lexists(str(p)):
            return []
        with safe_open_read(cairn_dir, p) as fh:
            lines = fh.read().splitlines()
    except (ValueError, OSError):
        return []
    bullets = [ln.strip() for ln in lines if ln.strip().startswith("- ")]
    return bullets[-limit:]


def vault_tail(cairn_dir):
    return {
        "decisions": _tail_bullets(cairn_dir, "decisions"),
        "issues": _tail_bullets(cairn_dir, "issues"),
    }


def board_payload(cairn_dir):
    """The /api/board response. Graceful on empty/invalid state: never raises."""
    try:
        entries = board.read_board(cairn_dir)
    except (ValueError, OSError) as exc:
        return {"entries": [], "dag": [],
                "vault_tail": {"decisions": [], "issues": []},
                "error": str(exc)}
    return {"entries": entries,
            "dag": synthesize_dag(entries),
            "vault_tail": vault_tail(cairn_dir)}


def resolve_static(mission_dir, url_path):
    """Map a request path to a file under mission_dir.

    Returns (status, real_path_or_None). 403 when the resolved realpath
    escapes the mission dir, 404 when missing/not-allowlisted.
    """
    raw = unquote(url_path)
    if "\x00" in raw or "\\" in raw:
        return 403, None
    if raw.endswith("/"):
        raw += "index.html"
    parts = [p for p in raw.split("/") if p]
    root = os.path.realpath(str(mission_dir))
    candidate = os.path.join(root, *parts) if parts else os.path.join(root, "index.html")
    real = os.path.realpath(candidate)
    # realpath containment: the resolved target (after any symlinks and any
    # ../ normalization, including %2e%2e-encoded) must stay under mission/.
    if real != root and not real.startswith(root + os.sep):
        return 403, None
    if Path(real).suffix not in CONTENT_TYPES or not os.path.isfile(real):
        return 404, None
    return 200, real


class MissionHandler(BaseHTTPRequestHandler):
    cairn_dir = None      # injected by make_server
    mission_dir = MISSION_DIR
    server_version = "CairnMission"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/board":
            return self._send_json(board_payload(self.cairn_dir))
        status, real = resolve_static(self.mission_dir, path)
        if status != 200:
            return self._send_error(status)
        with open(real, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[Path(real).suffix])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status):
        body = json.dumps({"error": status}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep the CLI quiet
        pass


def make_server(cairn_dir, port=4517):
    """ThreadingHTTPServer bound to 127.0.0.1 ONLY (port 0 = ephemeral, tests)."""
    handler = type("Handler", (MissionHandler,), {"cairn_dir": Path(cairn_dir)})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(cairn_dir, port=4517, open_browser=True):
    httpd = make_server(cairn_dir, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?live=1"
    print(f"cairn mission · {url}  (Ctrl-C to stop; replay demo at /index.html)")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
