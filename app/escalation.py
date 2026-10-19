"""One Telegram message per escalated chore, per Phase 2 of
docs/build-brief-evals.md.

The message names the repo, the reason and the instruction, carries the tail
of the test output and a link to the run page, and asks for a hint: a reply
to it becomes an advised rerun (app/telegram_webhook.py, app/advice.py). A
chore that left a diff also gets the Open it anyway button, through the same
approval row the button always used.

Nothing is sent for an eval chore, whose escalations belong in the report,
or for a chore whose chain already announced an escalation: the second one
goes in the report, not a new message. A chore from a review note is the
exception for a question: each question in its chain is announced, since each
one is waiting on an answer. It never gets the Open it anyway button, which
would open a diff the note guard refused or the checks never passed. Unlike
progress messages, this one carries test output, because the owner needs it to write a hint; it goes
only to the owner's own chat.
"""

import logging

import psycopg

from app.approvals import ask
from app.telegram import TelegramClient, TelegramError

# Sources whose chores tell nobody: no message, no outage retry, not in the
# report's escalations. An advised rerun keeps one (app/advice.py).
QUIET_SOURCES = ("eval", "bank")

logger = logging.getLogger("agent_runs.escalation")

OUTPUT_TAIL_CHARS = 1000
# Telegram refuses a message over 4096 characters. The question, the link and
# the reply line always fit, so the task section is what gives way.
MESSAGE_LIMIT = 4000
CUT = "\n(cut)"

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
    run_id: str,
    repo: str,
    task: str,
    reason: str,
    test_output: str,
    page_base_url: str,
    question: str = "",
) -> str:
    head = f"Chore on {repo} escalated ({run_id[:8]}): {reason}"
    rest = []
    if question:
        rest += ["", "The model asks:", question.strip()[:OUTPUT_TAIL_CHARS]]
    tail = (test_output or "").strip()[-OUTPUT_TAIL_CHARS:]
    if tail:
        rest += ["", "The tests ended:", tail]
    rest += [
        "",
        f"{page_base_url.rstrip('/')}/#/runs/{run_id}",
        "",
        "Reply to this message with a hint and I will rerun it from main with your hint. "
        "Or send /hint followed by the hint.",
    ]
    room = MESSAGE_LIMIT - len(head) - len("\n".join(rest)) - 4
    return "\n".join([head, "", _fit(task.strip(), room), *rest])


def _fit(task: str, room: int) -> str:
    """The task cut to room characters, on a line boundary. A fenced block the
    cut leaves open is closed again, so the cut falls in its content and never
    in a fence."""
    if len(task) <= room:
        return task
    lines = task[:room].split("\n")[:-1]
    while lines:
        open_fence = ""
        for line in lines:
            if len(line) >= 3 and set(line) == {"`"}:
                if not open_fence:
                    open_fence = line
                elif len(line) >= len(open_fence):
                    open_fence = ""
        text = "\n".join(lines) + CUT + (f"\n{open_fence}" if open_fence else "")
        if len(text) <= room:
            return text
        lines.pop()
    return CUT.strip()


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
    if source in QUIET_SOURCES:
        return None
    done = conn.execute(_DONE, (run_id,)).fetchone()
    output = (done[0] if done else None) or {}
    question = output.get("question") if source == "review_note" else None
    if not question and _already_announced(conn, run_id):
        return None
    text = escalation_text(
        run_id, repo, task, reason or output.get("reason", ""), output.get("test_output", ""),
        page_base_url, question if isinstance(question, str) else "",
    )  # fmt: skip
    try:
        if (output.get("diff") or "").strip() and source != "review_note":
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
