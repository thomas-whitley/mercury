"""One Telegram message per escalated chore, per Phase 2 of
docs/build-brief-evals.md.

The message names the repo, the reason and the instruction, carries the tail
of the test output and a link to the run page, and asks for a hint: a reply
to it becomes an advised rerun (app/telegram_webhook.py, app/advice.py). A
chore that left a diff also gets the Open it anyway button, through the same
approval row the button always used.

Nothing is sent for an eval chore, whose escalations belong in the report,
or for a chore whose chain already announced an escalation: the second one
goes in the report, not a new message. Unlike progress messages, this one
carries test output, because the owner needs it to write a hint; it goes
only to the owner's own chat.
"""

import logging

import psycopg

from app.approvals import ask
from app.telegram import TelegramClient, TelegramError

logger = logging.getLogger("agent_runs.escalation")

OUTPUT_TAIL_CHARS = 1000

_CHAIN = """
WITH RECURSIVE chain(id, source_run_id, depth) AS (
    SELECT id, source_run_id, 0 FROM runs WHERE id = %s
    UNION ALL
    SELECT r.id, r.source_run_id, c.depth + 1 FROM runs r JOIN chain c ON r.id = c.source_run_id
)
SELECT id FROM chain ORDER BY depth
"""

_RUN = """
SELECT task, repo, source, escalation_reason FROM runs WHERE id = %s
"""
_DONE = "SELECT output FROM steps WHERE run_id = %s AND kind = 'done'"
_SET_MESSAGE = "UPDATE runs SET escalation_message_id = %s WHERE id = %s"
_SET_MESSAGE_FROM_APPROVAL = """
UPDATE runs SET escalation_message_id = (SELECT message_id FROM approvals WHERE id = %s)
WHERE id = %s
RETURNING escalation_message_id
"""


def chain_ids(conn: psycopg.Connection, run_id: str) -> list[str]:
    """This run and every run before it through source_run_id, newest first."""
    return [str(row[0]) for row in conn.execute(_CHAIN, (run_id,)).fetchall()]


def chain_root(conn: psycopg.Connection, run_id: str) -> str:
    """The first run of a chore's chain: the one the owner or a caller asked for."""
    return chain_ids(conn, run_id)[-1]


def _already_announced(conn: psycopg.Connection, run_id: str) -> bool:
    earlier = chain_ids(conn, run_id)[1:]
    if not earlier:
        return False
    row = conn.execute(
        "SELECT count(*) FROM runs "
        "WHERE id = ANY(%s::uuid[]) AND escalation_message_id IS NOT NULL",
        (earlier,),
    ).fetchone()
    return row[0] > 0


def escalation_text(
    run_id: str, repo: str, task: str, reason: str, test_output: str, page_base_url: str
) -> str:
    lines = [f"Chore on {repo} escalated ({run_id[:8]}): {reason}", "", task.strip()]
    tail = (test_output or "").strip()[-OUTPUT_TAIL_CHARS:]
    if tail:
        lines += ["", "The tests ended:", tail]
    lines += [
        "",
        f"{page_base_url.rstrip('/')}/#/runs/{run_id}",
        "",
        "Reply to this message with a hint and I will rerun it from main with your hint.",
    ]
    return "\n".join(lines)


def announce_escalation(
    conn: psycopg.Connection,
    telegram: TelegramClient | None,
    chat_id: int | None,
    run_id: str,
    page_base_url: str,
) -> int | None:
    """Send the escalation message and return its id, or None when nothing
    was sent. Never raises for Telegram: the run stays escalated either way."""
    if telegram is None or chat_id is None:
        return None
    task, repo, source, reason = conn.execute(_RUN, (run_id,)).fetchone()
    if source == "eval" or _already_announced(conn, run_id):
        return None
    done = conn.execute(_DONE, (run_id,)).fetchone()
    output = (done[0] if done else None) or {}
    text = escalation_text(
        run_id, repo, task, reason or output.get("reason", ""), output.get("test_output", ""),
        page_base_url,
    )  # fmt: skip
    try:
        if (output.get("diff") or "").strip():
            # One transaction, so a message that could not be sent leaves no approval row.
            with conn.transaction():
                approval_id = ask(conn, telegram, chat_id, "open_anyway", text, run_id=run_id)
                row = conn.execute(_SET_MESSAGE_FROM_APPROVAL, (approval_id, run_id)).fetchone()
            logger.info(
                "escalation of %s sent as message %s", run_id, row[0], extra={"run_id": run_id}
            )
            return row[0]
        message_id = telegram.send_message(chat_id, text)
    except TelegramError as error:
        logger.error("escalation of %s not sent: %s", run_id, error, extra={"run_id": run_id})
        return None
    conn.execute(_SET_MESSAGE, (message_id, run_id))
    logger.info("escalation of %s sent as message %s", run_id, message_id, extra={"run_id": run_id})
    return message_id
