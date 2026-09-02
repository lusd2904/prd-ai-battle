"""HTTP server for the read-only 对照表 view. 127.0.0.1:1780 only."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from prd_ai_battle.web.board import board_payload, draft_payload, matrix_payload, timeline_payload

MATRIX_HOST = "127.0.0.1"
MATRIX_PORT = 1780
MATRIX_URL = "http://127.0.0.1:1780"

_STATIC = Path(__file__).with_name("static")


class BindError(ValueError):
    pass


def validate_bind(host: str, port: int, *, production: bool = True) -> tuple[str, int]:
    """Never 0.0.0.0. Never 8080. Production is exactly 127.0.0.1:1780."""
    if host in {"0.0.0.0", "::", "[::]", "*"}:
        raise BindError("web board binds only 127.0.0.1:1780 — never 0.0.0.0")
    if port == 8080:
        raise BindError("web board binds only 127.0.0.1:1780 — never 8080")
    if host not in {"127.0.0.1", "localhost"}:
        raise BindError("web board binds only 127.0.0.1:1780")
    if production and port != MATRIX_PORT:
        raise BindError("web board binds only 127.0.0.1:1780")
    return "127.0.0.1", port


def _html() -> bytes:
    path = _STATIC / "index.html"
    if path.is_file():
        return path.read_bytes()
    return b"<html><body>prd-ai-battle</body></html>"


class BoardHandler(BaseHTTPRequestHandler):
    workspace: Path
    search_root: Path

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict[str, Any], code: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def _project_id(self, query: dict[str, list[str]]) -> str | None:
        values = query.get("project") or query.get("id")
        if not values:
            return None
        return values[0] or None

    def _workspace(self, query: dict[str, list[str]]) -> Path:
        from prd_ai_battle.web.board import resolve_workspace

        return resolve_workspace(self.workspace, self._project_id(query), self.search_root)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            self._send(200, _html(), "text/html; charset=utf-8")
            return
        if path == "/api/board":
            self._json(
                board_payload(
                    self.workspace,
                    project_id=self._project_id(query),
                    search_root=self.search_root,
                )
            )
            return
        ws = self._workspace(query)
        if path == "/api/matrix":
            self._json(matrix_payload(ws))
            return
        if path == "/api/timeline":
            self._json(timeline_payload(ws))
            return
        if path == "/api/draft":
            self._json(draft_payload(ws))
            return
        if path == "/api/projects":
            from prd_ai_battle.web.board import list_projects

            self._json({"projects": list_projects(self.workspace, search_root=self.search_root)})
            return
        self._json({"ok": False, "error": "not found"}, code=404)

    def do_POST(self) -> None:  # noqa: N802
        self._json({"ok": False, "error": "read-only: no clause edit, no draft write"}, code=405)

    def do_PUT(self) -> None:  # noqa: N802
        self.do_POST()

    def do_PATCH(self) -> None:  # noqa: N802
        self.do_POST()


def make_handler(workspace: Path, search_root: Path | None = None) -> type[BoardHandler]:
    ws = Path(workspace)
    search = Path(search_root) if search_root is not None else Path.cwd()

    class Bound(BoardHandler):
        workspace = ws
        search_root = search

    return Bound


def serve(
    *,
    host: str = MATRIX_HOST,
    port: int = MATRIX_PORT,
    workspace: Path,
    search_root: Path | None = None,
    production: bool = True,
) -> None:
    bind_host, bind_port = validate_bind(host, port, production=production)
    handler = make_handler(workspace, search_root)
    httpd = ThreadingHTTPServer((bind_host, bind_port), handler)
    print(f"本机对照表 {MATRIX_URL}  (bind {bind_host}:{bind_port}，只读)", flush=True)
    httpd.serve_forever()
