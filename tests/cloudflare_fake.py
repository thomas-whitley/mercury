"""A fake of the one Cloudflare call Mercury makes, the D1 query endpoint
(POST /accounts/{account}/d1/database/{database}/query), on a real local
socket. It holds review_comments rows and answers the open notes query with
them, in the shape D1's REST API uses. It records every call and the
Authorization header each carried. Point CLOUDFLARE_API_URL at `url` to use it.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeCloudflare:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.authorizations: list[str] = []
        self.paths: list[str] = []
        # Each row has id, host, page, anchor_text, quote, body, updated_at, status.
        self.notes: list[dict] = []
        self.status_override: int | None = None
        # An answer with HTTP 200 and "success": false.
        self.fail_with_success_false = False
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's name
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                status, body = fake._answer(self.path, payload, self.headers)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def add_note(self, note_id: int, **fields) -> dict:
        note = {
            "id": note_id,
            "host": "live.example.com",
            "page": "/about/",
            "anchor_text": "Our story",
            "quote": None,
            "body": "Change the heading to Who we are",
            "updated_at": "2026-10-19 01:00:00",
            "status": "open",
            **fields,
        }
        self.notes.append(note)
        return note

    def _answer(self, path: str, payload: dict, headers) -> tuple[int, object]:
        with self._lock:
            self.calls.append(payload)
            self.paths.append(path)
            self.authorizations.append(headers.get("Authorization", ""))
            if self.status_override is not None:
                return self.status_override, {"success": False, "errors": [{"message": "no"}]}
            if self.fail_with_success_false:
                return 200, {"success": False, "errors": [{"code": 7500, "message": "bad"}]}
            if "review_comments" not in payload.get("sql", ""):
                return 400, {"success": False, "errors": [{"message": "unknown query"}]}
            keys = ("id", "host", "page", "anchor_text", "quote", "body", "updated_at")
            open_rows = sorted(
                (n for n in self.notes if n["status"] == "open"), key=lambda n: n["id"]
            )
            results = [{key: n[key] for key in keys} for n in open_rows]
            return 200, {
                "success": True,
                "errors": [],
                "result": [{"success": True, "results": results, "meta": {}}],
            }

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
