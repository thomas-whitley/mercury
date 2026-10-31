"""The deal finder (docs/superpowers/specs/2026-10-23-deal-finder-design.md).

Each scheduler tick reads OzBargain's two feeds (app/ozbargain.py) and stores
every deal with one vote snapshot. A deal that cannot be bought (expired,
targeted at some accounts, upcoming, or past its expiry) is never stored,
and one already stored that turns up expired is marked so it stops being
live. When neither feed has loaded for 24 hours one message says so, and
another says when they load again. Nothing here is a run, and no log line
carries a title.

The roundup is due at deals.roundup_time on deals.roundup_weekday in the
chat's timezone, and goes out on the first tick after, so a PC that was off
on Sunday morning sends it when it starts. It covers deals first seen since
the last scheduled roundup (7 days for the first), and leaves out any deal
already sent, blocked, no longer live, or gone from both feeds with a
sharply worse vote balance. A heading that notifies comes first, then each
deal as its own quiet message with the four rating buttons. A heading that
fails records nothing, so the next tick tries again; a deal whose message
fails is left unsent, and the rest still go.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import psycopg

from app.deal_score import Learned, Rated, Score, Snapshot, learn, score
from app.mercury_config import DealsConfig
from app.ozbargain import DROPPED_FLAGS, FRONT_FEED, NEW_FEED, FeedError, FeedItem, fetch_feed
from app.telegram import TelegramClient, TelegramError

if TYPE_CHECKING:
    from app.config import Settings
    from app.mercury_config import MercuryConfig

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
# A deal is live while it carries none of the flags that drop it and its
# expiry has not passed. now is filled in by each statement that uses it.
_LIVE = (
    "coalesce(d.flag, '') NOT IN ("
    + ", ".join(f"'{flag}'" for flag in sorted(DROPPED_FLAGS))
    + ") AND (d.expires_at IS NULL OR d.expires_at > {now})"
)
_MARK_FLAG = "UPDATE deals SET flag = %s, expires_at = coalesce(%s, expires_at) WHERE node_id = %s"
_IS_LIVE = f"SELECT {_LIVE.format(now='%s')} FROM deals d WHERE d.node_id = %s"
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
    """Not marked expired, targeted or upcoming, and not past its expiry. A
    deal that has dropped off both feeds is still live, since most do within
    a day."""
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


RATING_BUTTONS = (
    ("🔥 Great", "g"),
    ("👍 Good", "o"),
    ("👎 Not for me", "n"),
    ("💸 Overpriced", "p"),
)
RATING_NAMES = {letter: label for label, letter in RATING_BUTTONS}
FIRST_WINDOW = timedelta(days=7)
# Telegram refuses a message over 4,096 characters.
MAX_DEAL_CHARS = 4000
# A deal gone from the newest tick's feeds is left out once its positive
# share has fallen this far below the best it had.
DROPPED_SHARE_FALL = 0.15
DEAL_LINK = "https://www.ozbargain.com.au/node/{}"
EMPTY_ROUNDUP = "No new deals cleared the bar this week."
HEADINGS = {"scheduled": "Deals this week: {}", "now": "Deals so far this week: {}"}

_RATINGS = """
SELECT r.rating, r.silent, r.rated_at, d.category, d.store, d.tags
FROM deal_ratings r JOIN deals d USING (node_id)
"""
_STATE = "SELECT paused, size_offset, bar_offset FROM deal_state"
_LAST_SCHEDULED = "SELECT max(sent_at) FROM deal_roundups WHERE kind = 'scheduled'"
_SCHEDULED_SINCE = (
    "SELECT EXISTS (SELECT 1 FROM deal_roundups WHERE kind = 'scheduled' AND sent_at >= %s)"
)
_FIRST_SEEN = "SELECT min(first_seen_at) FROM deals"
# Live, never sent and not blocked. since and seen_at are each optional.
_CANDIDATES = f"""
SELECT d.node_id, d.posted_at, d.category, d.store, d.tags
FROM deals d
WHERE {_LIVE.format(now="%(now)s")}
  AND (%(since)s::timestamptz IS NULL OR d.first_seen_at >= %(since)s)
  AND (%(seen_at)s::timestamptz IS NULL OR d.last_seen_at = %(seen_at)s)
  AND NOT EXISTS (SELECT 1 FROM deal_sends s WHERE s.node_id = d.node_id)
  AND NOT EXISTS (
      SELECT 1 FROM deal_blocks b
      WHERE b.key = d.category OR b.key = d.store OR b.key = ANY(d.tags)
  )
"""
_SNAPSHOTS = """
SELECT node_id, seen_at, votes_pos, votes_neg, comments, front_page
FROM deal_snapshots WHERE node_id = ANY(%s) ORDER BY seen_at
"""
_NEWEST_TICK = "SELECT max(seen_at) FROM deal_snapshots"
_DEAL_FOR_TEXT = """
SELECT d.title, n.name, s.votes_pos, s.votes_neg
FROM deals d
LEFT JOIN deal_feature_names n ON n.key = d.store
LEFT JOIN LATERAL (
    SELECT votes_pos, votes_neg FROM deal_snapshots
    WHERE node_id = d.node_id ORDER BY seen_at DESC LIMIT 1
) s ON true
WHERE d.node_id = %s
"""
_INSERT_ROUNDUP = """
INSERT INTO deal_roundups (kind, sent_at, heading_message_id) VALUES (%s, %s, %s) RETURNING id
"""
_INSERT_SEND = """
INSERT INTO deal_sends (node_id, kind, roundup_id, chat_id, message_id, text, score, sent_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""


def buttons(node_id: int) -> list[tuple[str, str]]:
    """The four rating buttons. deal:<node id>:<letter> is well under
    Telegram's 64 byte limit on callback data."""
    return [(label, f"deal:{node_id}:{letter}") for label, letter in RATING_BUTTONS]


def learned(conn: psycopg.Connection, now: datetime, config: DealsConfig) -> Learned:
    ratings = [
        Rated(rating, silent, rated_at, category, store, tuple(tags))
        for rating, silent, rated_at, category, store, tags in conn.execute(_RATINGS)
    ]
    return learn(ratings, now, config)


def roundup_size(conn: psycopg.Connection, config: DealsConfig) -> int:
    size_offset = conn.execute(_STATE).fetchone()[1]
    return max(1, config.roundup_size + size_offset * config.size_step)


def _share(s: Snapshot) -> float:
    return s.votes_pos / (s.votes_pos + s.votes_neg) if s.votes_pos + s.votes_neg else 0.0


def _dropped(history: list[Snapshot], newest_tick: datetime | None) -> bool:
    if not history or newest_tick is None or history[-1].seen_at >= newest_tick:
        return False
    return _share(history[-1]) < max(_share(s) for s in history) - DROPPED_SHARE_FALL


def candidates(
    conn: psycopg.Connection,
    now: datetime,
    config: DealsConfig,
    *,
    since: datetime | None = None,
    seen_at: datetime | None = None,
) -> list[tuple[int, Score]]:
    """Deals that may be sent, scored and best first, none scoring 0. since
    keeps deals first seen from then on; seen_at keeps those seen on that tick."""
    rows = conn.execute(_CANDIDATES, {"now": now, "since": since, "seen_at": seen_at}).fetchall()
    if not rows:
        return []
    histories: dict[int, list[Snapshot]] = {row[0]: [] for row in rows}
    for node_id, *values in conn.execute(_SNAPSHOTS, (list(histories),)):
        histories[node_id].append(Snapshot(*values))
    newest_tick = conn.execute(_NEWEST_TICK).fetchone()[0]
    taught = learned(conn, now, config)
    scored = []
    for node_id, posted_at, category, store, tags in rows:
        history = histories[node_id]
        if _dropped(history, newest_tick):
            continue
        result = score(posted_at, history, category, store, tuple(tags), taught, now, config)
        if result.total > 0:
            scored.append((node_id, result))
    scored.sort(key=lambda pair: (-pair[1].total, pair[0]))
    return scored


def window_start(conn: psycopg.Connection, now: datetime) -> datetime:
    last = conn.execute(_LAST_SCHEDULED).fetchone()[0]
    return last if last is not None else now - FIRST_WINDOW


def ranked(
    conn: psycopg.Connection, since: datetime, now: datetime, config: DealsConfig
) -> list[tuple[int, Score]]:
    return candidates(conn, now, config, since=since)[: roundup_size(conn, config)]


def roundup_due(
    conn: psycopg.Connection, now: datetime, timezone: str, config: DealsConfig
) -> bool:
    """Due from the most recent roundup day and time at or before now, until a
    scheduled roundup is sent. Never due while paused, and never for a due
    time before the first deal was seen, so turning deals on does not send a
    roundup of one tick's deals at once."""
    if conn.execute(_STATE).fetchone()[0]:
        return False
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    day = local.date() - timedelta(days=(local.weekday() - config.roundup_weekday) % 7)
    due = datetime.combine(day, config.roundup_time, tzinfo=zone)
    if due > local:
        due = datetime.combine(day - timedelta(days=7), config.roundup_time, tzinfo=zone)
    first_seen = conn.execute(_FIRST_SEEN).fetchone()[0]
    if first_seen is None or first_seen > due:
        return False
    return not conn.execute(_SCHEDULED_SINCE, (due,)).fetchone()[0]


def deal_text(conn: psycopg.Connection, node_id: int) -> str:
    """The title as OzBargain gives it (with the price), the store, the votes
    and the deal page. Plain text, so nothing in a title needs escaping."""
    title, store, pos, neg = conn.execute(_DEAL_FOR_TEXT, (node_id,)).fetchone()
    votes = f"+{pos or 0} −{neg or 0}"
    tail = f"\n{store} · {votes}" if store else f"\n{votes}"
    tail += "\n" + DEAL_LINK.format(node_id)
    room = MAX_DEAL_CHARS - len(tail)
    if len(title) > room:
        title = title[: room - 1] + "…"
    return title + tail


def send_roundup(
    conn: psycopg.Connection,
    telegram: TelegramClient,
    chat_id: int,
    kind: str,
    now: datetime,
    config: DealsConfig,
) -> int | None:
    """Send a roundup of kind 'scheduled' or 'now'. Returns its id, or None
    when the heading could not be sent and nothing was recorded."""
    picked = ranked(conn, window_start(conn, now), now, config)
    heading = HEADINGS[kind].format(len(picked)) if picked else EMPTY_ROUNDUP
    try:
        heading_id = telegram.send_message(chat_id, heading)
    except TelegramError as error:
        logger.error("could not send the deal roundup heading: %s", error)
        return None
    roundup_id = conn.execute(_INSERT_ROUNDUP, (kind, now, heading_id)).fetchone()[0]
    sent = sum(
        _send_deal(conn, telegram, chat_id, node_id, result, now, "roundup", roundup_id)
        for node_id, result in picked
    )
    logger.info("deal roundup %s sent with %s of %s deal(s)", roundup_id, sent, len(picked))
    return roundup_id


_NEWEST_SEND = """
SELECT message_id, text FROM deal_sends WHERE node_id = %s AND chat_id = %s
ORDER BY sent_at DESC, id DESC LIMIT 1
"""
_RATE = """
INSERT INTO deal_ratings (node_id, rating, silent, rated_at) VALUES (%s, %s, false, %s)
ON CONFLICT (node_id) DO UPDATE SET rating = excluded.rating, silent = false,
    rated_at = excluded.rated_at
"""
# A sent deal still live silence_days after it was first sent, with no
# rating. One that expired unrated counts for nothing.
_SILENCE = f"""
INSERT INTO deal_ratings (node_id, rating, silent, rated_at)
SELECT d.node_id, 'n', true, %(now)s
FROM deals d
WHERE {_LIVE.format(now="%(now)s")}
  AND (SELECT min(sent_at) FROM deal_sends s WHERE s.node_id = d.node_id)
      <= %(now)s - make_interval(days => %(days)s)
  AND NOT EXISTS (SELECT 1 FROM deal_ratings r WHERE r.node_id = d.node_id)
"""
_BUTTON_RATINGS = "SELECT count(*) FROM deal_ratings WHERE NOT silent"


def record_rating(
    conn: psycopg.Connection, node_id: int, chat_id: int, rating: str, now: datetime
) -> tuple[int, str] | None:
    """Record a press, replacing any earlier rating of the deal, silent or
    not. Returns the message id and text of the deal's newest message to the
    chat, or None, recording nothing, when it was never sent there."""
    sent = conn.execute(_NEWEST_SEND, (node_id, chat_id)).fetchone()
    if sent is None:
        return None
    conn.execute(_RATE, (node_id, rating, now))
    return sent[0], sent[1]


def record_silence(conn: psycopg.Connection, now: datetime, config: DealsConfig) -> int:
    """Count each sent deal left unrated for silence_days as a weak Not for me."""
    added = conn.execute(_SILENCE, {"now": now, "days": config.silence_days}).rowcount
    if added:
        logger.info("%s unrated deal(s) counted as silence", added)
    return added


def button_ratings(conn: psycopg.Connection) -> int:
    """Distinct deals rated with a button. Silence never counts."""
    return conn.execute(_BUTTON_RATINGS).fetchone()[0]


_WOULD_HAVE_ALERTED = "SELECT node_id FROM deal_would_alert"
_WOULD_ALERT = """
INSERT INTO deal_would_alert (node_id, first_at, total) VALUES (%s, %s, %s)
ON CONFLICT (node_id) DO UPDATE SET total = greatest(deal_would_alert.total, excluded.total)
"""


def alert_bar(conn: psycopg.Connection, config: DealsConfig) -> float:
    """The total an alert must reach. /deals less raises it a step, more lowers it."""
    bar_offset = conn.execute(_STATE).fetchone()[2]
    return config.alert_bar + bar_offset * config.bar_step


def send_alerts(
    conn: psycopg.Connection,
    telegram: TelegramClient,
    chat_id: int,
    now: datetime,
    config: DealsConfig,
) -> list[int]:
    """Send each deal seen on the newest tick that clears the alert bar, on
    its own and notifying. Until alerts_after deals are rated with a button,
    or while paused, nothing is sent and each is kept in deal_would_alert to
    set the bar from. A deal kept there first cleared the bar on an earlier
    tick, so it is never sent later, and switching alerts on sends no burst.
    Returns the node ids sent."""
    newest_tick = conn.execute(_NEWEST_TICK).fetchone()[0]
    if newest_tick is None:
        return []
    bar = alert_bar(conn, config)
    strong = [
        (node_id, result)
        for node_id, result in candidates(conn, now, config, seen_at=newest_tick)
        if result.total >= bar
    ]
    paused = conn.execute(_STATE).fetchone()[0]
    if paused or button_ratings(conn) < config.alerts_after:
        for node_id, result in strong:
            conn.execute(_WOULD_ALERT, (node_id, now, result.total))
        if strong:
            logger.info("%s deal(s) would have been alerts", len(strong))
        return []
    held = {row[0] for row in conn.execute(_WOULD_HAVE_ALERTED)}
    sent = [
        node_id
        for node_id, result in strong
        if node_id not in held
        and _send_deal(conn, telegram, chat_id, node_id, result, now, "alert")
    ]
    if sent:
        logger.info("%s deal alert(s) sent", len(sent))
    return sent


def tick(
    conn: psycopg.Connection,
    settings: "Settings",
    config: "MercuryConfig",
    telegram: TelegramClient | None,
    now: datetime | None = None,
) -> None:
    """The deal finder's part of a scheduler tick: read the feeds, count a
    week of silence, send the roundup when due, then any alerts. Off unless
    deals.enabled and a chat are configured. Nothing here may stop the rest
    of the tick, and only the error's class is logged, since a message can
    quote a title."""
    deals_config = config.deals
    chat_id = config.telegram_chat_id
    if not deals_config.enabled or chat_id is None:
        return
    now = now or datetime.now(UTC)
    try:
        fetch_and_ingest(conn, settings.ozbargain_url, now, telegram, chat_id)
        record_silence(conn, now, deals_config)
        if telegram is None:
            return
        if roundup_due(conn, now, config.timezone, deals_config):
            send_roundup(conn, telegram, chat_id, "scheduled", now, deals_config)
        send_alerts(conn, telegram, chat_id, now, deals_config)
    except Exception as error:  # noqa: BLE001 - nothing here may stop the rest of the tick
        logger.error("deal finder step failed: %s", type(error).__name__)


def _send_deal(
    conn: psycopg.Connection,
    telegram: TelegramClient,
    chat_id: int,
    node_id: int,
    result: Score,
    now: datetime,
    kind: str,
    roundup_id: int | None = None,
) -> bool:
    """Send one deal and record it. A roundup's deals are quiet; an alert
    notifies. A deal that could not be sent is not recorded."""
    text = deal_text(conn, node_id)
    try:
        message_id = telegram.send_message(
            chat_id,
            text,
            buttons(node_id),
            disable_link_preview=True,
            disable_notification=kind == "roundup",
            per_row=2,
        )
    except TelegramError as error:
        logger.error("could not send deal %s: %s", node_id, error)
        return False
    conn.execute(
        _INSERT_SEND,
        (node_id, kind, roundup_id, chat_id, message_id, text, json.dumps(result.as_json()), now),
    )
    return True
