"""The card: one Telegram message for a review note that needs Thomas, per
docs/superpowers/specs/2026-11-13-review-note-triage-design.md.

It says what the note is (who, which page, their words in a fence they cannot
close), how old it is, and one suggestion line from the sorting model. The
buttons are fixed: nothing in the note or the suggestion becomes a button or a
link. A card for an escalated chore offers Dismiss only.
"""

import datetime
import re

from app.advice_text import fenced_lines
from app.escalation import MESSAGE_LIMIT, _fit

SUGGESTION_LIMIT = 150
# Tapped or highlighted text longer than this is left off the card; the body is enough.
SHORT_SNIPPET = 200
LATE_AFTER = datetime.timedelta(days=1)
BUTTON = re.compile(r"^note:(\d+):(dismiss|change)$")


def _written_at(written: str) -> datetime.datetime | None:
    """D1's updated_at, "YYYY-MM-DD HH:MM:SS" in UTC, or None when it is not that."""
    try:
        parsed = datetime.datetime.fromisoformat(written.strip())
    except (ValueError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


def age_line(
    written: str, picked_up: datetime.datetime, now: datetime.datetime, held_by_page: bool
) -> str:
    """ "Written 28 Oct, 16 days ago." plus why it is late when Mercury picked it
    up more than a day after it was written. Empty when written is unreadable."""
    at = _written_at(written)
    if at is None:
        return ""
    days = (now - at).days
    if days < 1:
        line = "Written today."
    else:
        line = f"Written {at.day} {at:%b}, {days} day{'s' if days != 1 else ''} ago."
    if held_by_page:
        line += " Held up behind another note on the same page."
    elif picked_up - at > LATE_AFTER:
        line += " Picked up late."
    return line


def card_text(
    reviewer: str,
    page: str,
    body: str,
    anchor: str | None,
    quote: str | None,
    age: str,
    suggestion: str | None,
) -> str:
    head = f"{reviewer} left a note on {page}:"
    tail: list[str] = []
    if anchor and len(anchor) <= SHORT_SNIPPET:
        tail += fenced_lines("They tapped:", anchor)
    if quote and len(quote) <= SHORT_SNIPPET:
        tail += fenced_lines("They highlighted:", quote)
    if age:
        tail.append(age)
    if suggestion and suggestion.strip():
        tail.append("Suggestion: " + " ".join(suggestion.split())[:SUGGESTION_LIMIT])
    room = MESSAGE_LIMIT - len(head) - len("\n".join(tail)) - 4
    # Cut first, so a long one-line note keeps its start; _fit then keeps the fence whole.
    words = body if len(body) < room - 20 else body[: room - 20] + " (cut)"
    return "\n".join([head, _fit("\n".join(fenced_lines("", words))[1:], room), *tail])


def card_buttons(note_id: int, can_change: bool) -> list[tuple[str, str]]:
    buttons = [("Dismiss", f"note:{note_id}:dismiss")]
    if can_change:
        buttons.append(("Treat as a change", f"note:{note_id}:change"))
    return buttons
