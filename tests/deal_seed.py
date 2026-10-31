"""Rows for the deal finder's tests, written straight to the tables. Every
title is invented."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MELBOURNE = ZoneInfo("Australia/Melbourne")
# Sunday 1 November 2026, 10:00 in Melbourne.
SUNDAY = datetime(2026, 11, 1, 10, 0, tzinfo=MELBOURNE)
CHAT = 42


def seed_deal(
    conn,
    node_id: int,
    *,
    title: str | None = None,
    pos: int = 20,
    neg: int = 0,
    first_seen: datetime = SUNDAY - timedelta(days=2),
    seen_at: datetime | None = None,
    category: str | None = "cat:x",
    store: str | None = "store:s",
    tags: tuple[str, ...] = (),
    flag: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    seen_at = seen_at or SUNDAY - timedelta(hours=1)
    conn.execute(
        "INSERT INTO deals (node_id, title, posted_at, expires_at, flag, category, store, tags, "
        "first_seen_at, last_seen_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            node_id,
            title or f"Invented deal {node_id}",
            first_seen - timedelta(hours=1),
            expires_at,
            flag,
            category,
            store,
            list(tags),
            first_seen,
            seen_at,
        ),
    )
    conn.execute(
        "INSERT INTO deal_feature_names (key, name) VALUES ('store:s', 'Invented Store') "
        "ON CONFLICT DO NOTHING"
    )
    snapshot(conn, node_id, seen_at, pos, neg)


def snapshot(conn, node_id, seen_at, pos, neg=0, front=False):
    conn.execute(
        "INSERT INTO deal_snapshots VALUES (%s, %s, %s, %s, 0, %s)",
        (node_id, seen_at, pos, neg, front),
    )


def record_send(conn, node_id, sent_at, *, kind="roundup", message_id=5, chat_id=CHAT, text=None):
    conn.execute(
        "INSERT INTO deal_sends (node_id, kind, chat_id, message_id, text, score, sent_at) "
        "VALUES (%s, %s, %s, %s, %s, '{}', %s)",
        (node_id, kind, chat_id, message_id, text or f"Invented deal {node_id}", sent_at),
    )
