"""The deal finder's Telegram side, called from app/telegram_webhook.py once
the allowed chat check has passed: the rating buttons and /deals. Each
function is sync and opens its own connection, so the webhook runs it in a
threadpool.

A press records the rating and edits the deal's message to show it, keeping
all four buttons so a rating can be changed later. A Telegram error is logged
and the rating stands.

/deals more and less move the roundup size by deals.size_step (never below
1) and the alert bar by one deals.bar_step. never and allow match a name
case-insensitively against the display name or slug of every category,
store and tag the feeds have shown, and act on every kind that matches.
why explains the last deal sent from the score kept when it was sent.
"""

import difflib
import logging
import re
from datetime import datetime, timedelta

import psycopg

from app.deal_score import Score, explain
from app.deals import (
    RATING_NAMES,
    alert_bar,
    buttons,
    record_rating,
    roundup_size,
    send_roundup,
)
from app.mercury_config import DealsConfig
from app.telegram import TelegramClient, TelegramError

logger = logging.getLogger("agent_runs.deals")

DEAL_BUTTON = re.compile(r"^deal:(\d+):([gonp])$")
NOT_SENT = "That deal was not sent to this chat."


def on_deal_button(
    database_url: str,
    telegram: TelegramClient | None,
    chat_id: int,
    callback_id: str,
    data: str,
    now: datetime,
) -> None:
    match = DEAL_BUTTON.match(data)
    if match is None:
        return
    node_id, rating = int(match[1]), match[2]
    with psycopg.connect(database_url, autocommit=True) as conn:
        sent = record_rating(conn, node_id, chat_id, rating, now)
    if sent is None:
        logger.info("a press on deal %s, which was not sent to this chat", node_id)
    else:
        # The rating itself stays out of the log.
        logger.info("deal %s rated", node_id)
    if telegram is None:
        return
    name = RATING_NAMES[rating]
    try:
        if sent is not None:
            message_id, text = sent
            telegram.edit_message_text(
                chat_id, message_id, f"{text}\n\nRated: {name}", buttons(node_id), per_row=2
            )
        telegram.answer_callback_query(callback_id, NOT_SENT if sent is None else f"Saved: {name}")
    except TelegramError as error:
        logger.error("could not show the deal rating in the chat: %s", error)


USAGE = "Usage: /deals more | less | never <name> | allow <name> | why | now | off | on"
DISABLED = "The deal finder is off in mercury.yaml."
KIND_NAMES = {"cat": "category", "store": "store", "tag": "tag"}
CLOSEST = 5
# The Telegram poller posts an update again when the api takes over 30
# seconds to answer, and a slow roundup can. A second /deals now inside this
# window is refused rather than sending the next ten deals.
NOW_COOLDOWN = timedelta(minutes=10)
NOW_TOO_SOON = "A roundup went out in the last 10 minutes."
_RECENT_NOW = "SELECT EXISTS (SELECT 1 FROM deal_roundups WHERE kind = 'now' AND sent_at > %s)"

_MORE = "UPDATE deal_state SET size_offset = size_offset + 1, bar_offset = bar_offset - 1"
_LESS = "UPDATE deal_state SET size_offset = size_offset - %s, bar_offset = bar_offset + 1"
_PAUSE = "UPDATE deal_state SET paused = %s"
_NAMES = "SELECT key, name FROM deal_feature_names ORDER BY key"
_BLOCK = "INSERT INTO deal_blocks (key) VALUES (%s) ON CONFLICT DO NOTHING"
_UNBLOCK = "DELETE FROM deal_blocks WHERE key = %s"
_LAST_SENT = """
SELECT d.title, s.score FROM deal_sends s JOIN deals d USING (node_id)
ORDER BY s.sent_at DESC, s.id DESC LIMIT 1
"""


def answer_deals(
    database_url: str,
    telegram: TelegramClient | None,
    chat_id: int,
    argument: str,
    config: DealsConfig,
    now: datetime,
) -> str | None:
    """The reply to /deals <argument>, or None when the command sent its own
    messages, as now does."""
    if not config.enabled:
        return DISABLED
    word, _, rest = argument.strip().partition(" ")
    word, rest = word.lower(), rest.strip()
    with psycopg.connect(database_url, autocommit=True) as conn:
        if word == "more":
            conn.execute(_MORE)
            return _size_and_bar(conn, config)
        if word == "less":
            # The size stops at 1, and the offset with it, so more undoes less.
            at_floor = roundup_size(conn, config) <= 1
            conn.execute(_LESS, (0 if at_floor else 1,))
            return _size_and_bar(conn, config)
        if word in ("never", "allow") and rest:
            return _never_or_allow(conn, word, rest)
        if word == "why":
            return _why(conn)
        if word == "now":
            if telegram is None:
                return "No Telegram token, so the roundup cannot be sent."
            if conn.execute(_RECENT_NOW, (now - NOW_COOLDOWN,)).fetchone()[0]:
                return NOW_TOO_SOON
            sent = send_roundup(conn, telegram, chat_id, "now", now, config)
            return None if sent is not None else "Could not send the roundup."
        if word in ("off", "on"):
            conn.execute(_PAUSE, (word == "off",))
            return "Deals paused." if word == "off" else "Deals on."
    return USAGE


def _size_and_bar(conn: psycopg.Connection, config: DealsConfig) -> str:
    return f"Roundup size {roundup_size(conn, config)}, alert bar {alert_bar(conn, config):.1f}."


def _never_or_allow(conn: psycopg.Connection, word: str, text: str) -> str:
    names = conn.execute(_NAMES).fetchall()
    wanted = text.lower()
    matched = [
        (key, name)
        for key, name in names
        if name.lower() == wanted or key.split(":", 1)[1].lower() == wanted
    ]
    if not matched:
        by_lower = {name.lower(): name for _, name in names}
        near = difflib.get_close_matches(wanted, sorted(by_lower), n=CLOSEST)
        closest = [by_lower[n] for n in near]
        listed = f" Closest: {', '.join(closest)}." if closest else ""
        return f"Nothing called {text}.{listed}"
    for key, _ in matched:
        conn.execute(_BLOCK if word == "never" else _UNBLOCK, (key,))
    described = ", ".join(f"{name} ({KIND_NAMES[key.split(':', 1)[0]]})" for key, name in matched)
    logger.info("deals %s: %s feature(s)", word, len(matched))
    return f"{'Blocked' if word == 'never' else 'Allowed again'}: {described}."


def _why(conn: psycopg.Connection) -> str:
    row = conn.execute(_LAST_SENT).fetchone()
    if row is None:
        return "No deal sent yet."
    title, stored = row
    try:
        result = Score(**stored)
    except TypeError:
        return f"{title}\nNo score was kept when it was sent."
    names = dict(conn.execute(_NAMES).fetchall())
    return f"{title}\n{explain(result, names)}"
