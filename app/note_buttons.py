"""Dismiss and Treat as a change on a review note's card, and a reply to the
card as a hint, per docs/superpowers/specs/2026-11-13-review-note-triage-design.md.

Each press locks the note's row, so a second press finds the first one's
result. A card sent before the note was edited changes nothing: the row goes,
and the next scheduler tick reads the note again from D1, sorts its new words
and sends a new card. Dismiss only marks the row; the scheduler writes the D1
"done" (app/review_notes.py finish_dismissals). It never cancels a run or
closes a pull request: while either is open it refuses and says so.
"""

import logging

import psycopg

from app.config import Settings
from app.mercury_config import MercuryConfig
from app.review_notes import _NEWEST_RUN, Note, _advance_note

logger = logging.getLogger("agent_runs.note_buttons")

STILL_GOING = "A rerun is going; close its pull request to drop the note."
QUEUED = "Queued. It starts when the page and today's limits allow."
ALREADY_RAN = "This one already ran. Reply with a hint instead."
UNTRACKED = "That note is no longer tracked."

_LOCK = """
SELECT state, run_id, pr_url, note_updated_at, card_updated_at, host, page,
       note_body, note_anchor, note_quote
FROM review_notes WHERE note_id = %s FOR UPDATE
"""
_BY_CARD = "SELECT note_id FROM review_notes WHERE card_message_id = %s AND state = 'asked'"
_SET_STATE = "UPDATE review_notes SET state = %s, updated_at = now() WHERE note_id = %s"
_TO_CAPPED = """
UPDATE review_notes SET state = 'capped', run_id = NULL, hint = %s, updated_at = now()
WHERE note_id = %s
"""
_FORGET = "DELETE FROM review_notes WHERE note_id = %s"
_RUN_STATUS = "SELECT status FROM runs WHERE id = %s"
_GOING = ("pending", "running", "awaiting_approval")


def press(
    conn: psycopg.Connection, note_id: int, action: str, mercury: MercuryConfig, settings: Settings
) -> str:
    """Act on one press of a card button and return the short answer shown to Thomas."""
    with conn.transaction():
        return _press(conn, note_id, action, mercury, settings, hint=None)


def hint_on_card(
    conn: psycopg.Connection, message_id: int, hint: str, mercury: MercuryConfig, settings: Settings
) -> str | None:
    """A reply to an asked note's card: treat it as a change, with the reply as
    Thomas's hint. None when no asked note's card has this message id."""
    row = conn.execute(_BY_CARD, (message_id,)).fetchone()
    if row is None:
        return None
    with conn.transaction():
        return _press(conn, row[0], "change", mercury, settings, hint=hint.strip() or None)


def _press(conn, note_id: int, action: str, mercury, settings, hint: str | None) -> str:
    config = mercury.review_notes
    reviewer = config.reviewer_name if config else "The reviewer"
    row = conn.execute(_LOCK, (note_id,)).fetchone()
    if row is None:
        return UNTRACKED
    state, run_id, pr_url, written, card_written, host, page, body, anchor, quote = row
    if state == "gone":
        return f"{reviewer} deleted this note."
    if state in ("dismiss", "dismissed"):
        return "Already dismissed."
    if card_written is not None and written != card_written:
        conn.execute(_FORGET, (note_id,))
        logger.info("review note %s was edited after its card; sorting it again", note_id)
        return f"{reviewer} changed this note since. I'll send the new version."

    if action == "dismiss":
        if state not in ("asked", "question", "capped") or pr_url or _going(conn, run_id):
            return STILL_GOING
        conn.execute(_SET_STATE, ("dismiss", note_id))
        logger.info("review note %s dismissed by Thomas", note_id)
        return "Dismissed."

    # action == "change"
    if state == "question":
        return ALREADY_RAN
    if state != "asked":
        return "Already started."
    repo = next((r for r in mercury.repos if config and r.name == config.repo), None)
    if config is None or repo is None:
        return UNTRACKED
    conn.execute(_TO_CAPPED, (hint, note_id))
    note = Note(id=note_id, host=host, page=page, anchor_text=anchor, quote=quote,
                body=body or "", updated_at=written)  # fmt: skip
    started = _advance_note(conn, note, "capped", config, repo, settings)
    logger.info("review note %s treated as a change by Thomas", note_id)
    return f"Started a chore, {started[:8]}." if started else QUEUED


def _going(conn, run_id) -> bool:
    """Whether the newest run in the note's chain is still queued or running."""
    if run_id is None:
        return False
    newest = conn.execute(_NEWEST_RUN, (run_id,)).fetchone()[0]
    return conn.execute(_RUN_STATUS, (newest,)).fetchone()[0] in _GOING
