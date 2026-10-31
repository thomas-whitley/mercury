"""A fake of OzBargain's two RSS feeds on a real local socket, serving
/deals/feed and /feed in OzBargain's shape. Point OZBARGAIN_URL at `url`
to use it. Every title in the tests is invented.
"""

import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SITE = "https://www.ozbargain.com.au"


def item_xml(
    node_id: int | None,
    title: str,
    *,
    pos: int = 10,
    neg: int = 0,
    comments: int = 2,
    posted: str = "Fri, 23 Oct 2026 03:00:00 +0000",
    expiry: str | None = None,
    flag: str | None = None,
    category: tuple[str, str] | None = ("computing", "Computing"),
    store: tuple[str, str] | None = ("amazon-au", "Amazon AU"),
    tags: tuple[tuple[str, str], ...] = (("ssd", "SSD"),),
    meta: bool = True,
) -> str:
    """One <item>. title is raw text and is escaped here, as OzBargain does."""
    parts = [f"<title>{escape(title)}</title>"]
    if node_id is not None:
        parts.append(f"<link>{SITE}/node/{node_id}</link>")
        parts.append(f'<guid isPermaLink="false">{node_id} at {SITE}</guid>')
    parts.append(f"<pubDate>{posted}</pubDate>")
    if meta:
        extra = f' expiry="{expiry}"' if expiry else ""
        parts.append(
            f'<ozb:meta comment-count="{comments}" click-count="5" votes-pos="{pos}" '
            f'votes-neg="{neg}"{extra}/>'
        )
    if flag:
        parts.append(f'<ozb:title-msg type="{flag}">{flag.title()}</ozb:title-msg>')
    features = [("cat", category), ("brand", store)] + [("tag", tag) for tag in tags]
    for kind, feature in features:
        if feature:
            slug, name = feature
            parts.append(f'<category domain="{SITE}/{kind}/{slug}">{escape(name)}</category>')
    return "<item>" + "".join(parts) + "</item>"


def feed_xml(*items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<rss version="2.0" xmlns:ozb="{SITE}"><channel><title>OzBargain</title>'
        + "".join(items)
        + "</channel></rss>"
    ).encode()


class FakeOzBargain:
    def __init__(self) -> None:
        self.new_items: list[str] = []
        self.front_items: list[str] = []
        # A status to answer every request with, or one path's requests.
        self.status_override: int | None = None
        self.path_status: dict[str, int] = {}
        # A body to serve as is instead of the items, by path.
        self.raw: dict[str, bytes] = {}
        self.requests: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server's name
                with fake._lock:
                    fake.requests.append((self.path, self.headers.get("User-Agent", "")))
                    status = fake.path_status.get(self.path, fake.status_override)
                    if status is None and self.path in fake.raw:
                        status, body = 200, fake.raw[self.path]
                    elif status is None and self.path == "/deals/feed":
                        status, body = 200, feed_xml(*fake.new_items)
                    elif status is None and self.path == "/feed":
                        status, body = 200, feed_xml(*fake.front_items)
                    else:
                        status, body = status or 404, b"no"
                self.send_response(status)
                self.send_header("Content-Type", "application/rss+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def paths(self) -> list[str]:
        with self._lock:
            return [path for path, _ in self.requests]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
