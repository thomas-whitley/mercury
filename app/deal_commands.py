"""The deal finder's Telegram side, called from app/telegram_webhook.py once
the allowed chat check has passed: the rating buttons. Each function is sync
and opens its own connection, so the webhook runs it in a threadpool.

A press records the rating and edits the deal's message to show it, keeping
all four buttons so a rating can be changed later. A Telegram error is logged
and the rating stands.
"""

import logging
import re
from datetime import datetime

import psycopg

from app.deals import RATING_NAMES, buttons, record_rating
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
        logger.info("deal %s rated %s", node_id, rating)
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
