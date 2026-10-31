"""The deal finder (docs/superpowers/specs/2026-10-23-deal-finder-design.md).

Each scheduler tick reads OzBargain's two feeds (app/ozbargain.py) and stores
every deal with one vote snapshot. A deal that cannot be bought (expired,
targeted at some accounts, upcoming, or past its expiry) is never stored,
and one already stored that turns up expired is marked so it stops being
live. When neither feed has loaded for 24 hours one message says so, and
another says when they load again. Nothing here is a run, and no log line
carries a title.
"""

import logging
from datetime import datetime, timedelta

import psycopg

from app.ozbargain import DROPPED_FLAGS, FRONT_FEED, NEW_FEED, FeedError, FeedItem, fetch_feed
from app.telegram import TelegramClient, TelegramError

logger = logging.getLogger("agent_runs.deals")

FEED_DOWN_AFTER = timedelta(hours=24)
FEED_DOWN_TEXT = "The OzBargain feeds have not loaded for 24 hours, so no deals are being read."
FEED_BACK_TEXT = "The OzBargain feeds are loading again."

_UPSERT_DEAL = """
INSERT INTO deals (node_id, title, posted_at, expires_at, flag, category, store, tags,
                   first_seen_at, last_seen_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (node_id) DO UPDATE SET
    title = excluded.title, expires_at = excluded.expires_at, flag = excluded.flag,
    category = excluded.category, store = excluded.store, tags = excluded.tags,
    last_seen_at = excluded.last_seen_at
"""
_UPSERT_NAME = """
INSERT INTO deal_feature_names (key, name) VALUES (%s, %s)
ON CONFLICT (key) DO UPDATE SET name = excluded.name
"""
_SNAPSHOT = """
INSERT INTO deal_snapshots (node_id, seen_at, votes_pos, votes_neg, comments, front_page)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (node_id, seen_at) DO NOTHING
"""
_MARK_FLAG = "UPDATE deals SET flag = %s, expires_at = coalesce(%s, expires_at) WHERE node_id = %s"
_IS_LIVE = """
SELECT flag IS DISTINCT FROM 'expired' AND (expires_at IS NULL OR expires_at > %s)
FROM deals WHERE node_id = %s
"""
_FEED_STATE = "SELECT coalesce(last_fetch_ok_at, created_at), feed_down_notified FROM deal_state"
_FETCH_OK = "UPDATE deal_state SET last_fetch_ok_at = %s, feed_down_notified = false"
_FEED_DOWN_NOTIFIED = "UPDATE deal_state SET feed_down_notified = true"


def _cannot_be_bought(item: FeedItem, now: datetime) -> bool:
    return item.flag in DROPPED_FLAGS or (item.expires_at is not None and item.expires_at <= now)


def ingest(
    conn: psycopg.Connection, new: list[FeedItem], front: list[FeedItem], now: datetime
) -> int:
    """Store one tick's items, a deal in both feeds once and on the front
    page. Returns how many deals were stored or updated with a snapshot."""
    merged: dict[int, tuple[FeedItem, bool]] = {item.node_id: (item, False) for item in new}
    for item in front:
        merged[item.node_id] = (item, True)

    stored = 0
    with conn.transaction():
        for item, front_page in merged.values():
            if _cannot_be_bought(item, now):
                # A deal already stored stops being live. A new one is never stored.
                conn.execute(_MARK_FLAG, (item.flag, item.expires_at, item.node_id))
                continue
            conn.execute(
                _UPSERT_DEAL,
                (
                    item.node_id,
                    item.title,
                    item.posted_at,
                    item.expires_at,
                    item.flag,
                    item.category.key if item.category else None,
                    item.store.key if item.store else None,
                    [tag.key for tag in item.tags],
                    now,
                    now,
                ),
            )
            for feature in (item.category, item.store, *item.tags):
                if feature is not None:
                    conn.execute(_UPSERT_NAME, (feature.key, feature.name))
            conn.execute(
                _SNAPSHOT,
                (item.node_id, now, item.votes_pos, item.votes_neg, item.comments, front_page),
            )
            stored += 1
    return stored


def is_live(conn: psycopg.Connection, node_id: int, now: datetime) -> bool:
    """Not marked expired and not past its expiry. A deal that has dropped off
    both feeds is still live, since most do within a day."""
    row = conn.execute(_IS_LIVE, (now, node_id)).fetchone()
    return bool(row and row[0])


def fetch_and_ingest(
    conn: psycopg.Connection,
    base_url: str,
    now: datetime,
    telegram: TelegramClient | None,
    chat_id: int | None,
) -> int:
    """Fetch both feeds and store what loaded. A feed that fails is logged
    and tried again next tick; the tick counts as fetched when either loaded."""
    loaded: dict[str, list[FeedItem]] = {}
    for path in (NEW_FEED, FRONT_FEED):
        try:
            loaded[path] = fetch_feed(base_url, path)
        except FeedError as error:
            logger.warning("deal feed not read: %s", error)

    since, notified = conn.execute(_FEED_STATE).fetchone()
    if not loaded:
        if not notified and now - since >= FEED_DOWN_AFTER:
            if _tell(telegram, chat_id, FEED_DOWN_TEXT):
                conn.execute(_FEED_DOWN_NOTIFIED)
        return 0

    stored = ingest(conn, loaded.get(NEW_FEED, []), loaded.get(FRONT_FEED, []), now)
    conn.execute(_FETCH_OK, (now,))
    if notified:
        _tell(telegram, chat_id, FEED_BACK_TEXT)
    logger.info("deal feeds read: %s deal(s) stored", stored)
    return stored


def _tell(telegram: TelegramClient | None, chat_id: int | None, text: str) -> bool:
    if telegram is None or chat_id is None:
        return False
    try:
        telegram.send_message(chat_id, text)
    except TelegramError as error:
        logger.error("could not send the deal feed message: %s", error)
        return False
    return True
