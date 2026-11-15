"""Dismiss and Treat as a change on a note's card, and a reply to the card as
a hint (app/note_buttons.py)."""

import dataclasses

import pytest

from app.config import load_settings
from app.mercury_config import MercuryConfig
from app.note_buttons import hint_on_card, press
from tests.test_review_notes import REPO, make_config

WRITTEN = "2026-10-28 09:48:42"
MERCURY = MercuryConfig(sites=(), repos=(REPO,), review_notes=make_config(reviewer_name="Luke"))


def settings(**changes):
    return dataclasses.replace(load_settings(), **changes)


def seed(conn, state: str = "asked", card_updated_at: str | None = WRITTEN, **cols) -> None:
    conn.execute(
        "INSERT INTO review_notes (note_id, host, page, note_updated_at, state, card_message_id, "
        "card_updated_at, note_body, note_anchor) "
        "VALUES (5, %s, '/', %s, %s, 70, %s, 'Change the heading', 'Our story')",
        (MERCURY.review_notes.live_hosts[0], WRITTEN, state, card_updated_at),
    )
    for column, value in cols.items():
        conn.execute(f"UPDATE review_notes SET {column} = %s WHERE note_id = 5", (value,))


def state(conn) -> str | None:
    row = conn.execute("SELECT state FROM review_notes WHERE note_id = 5").fetchone()
    return row[0] if row else None


def chore_run(conn, run_status: str = "escalated") -> str:
    return str(
        conn.execute(
            "INSERT INTO runs (task, type, provider, repo, status, source) "
            "VALUES ('t', 'repo_chore', 'gemini', 'owner/site', %s, 'review_note') RETURNING id",
            (run_status,),
        ).fetchone()[0]
    )


def test_dismiss_asked(migrated_db):
    seed(migrated_db)
    assert press(migrated_db, 5, "dismiss", MERCURY, settings()) == "Dismissed."
    assert state(migrated_db) == "dismiss"


def test_dismiss_question(migrated_db):
    run_id = chore_run(migrated_db)
    seed(migrated_db, "question", run_id=run_id)
    assert press(migrated_db, 5, "dismiss", MERCURY, settings()) == "Dismissed."
    assert state(migrated_db) == "dismiss"


def test_dismiss_refused_while_running(migrated_db):
    first = chore_run(migrated_db)
    seed(migrated_db, "question", run_id=first)
    migrated_db.execute(
        "INSERT INTO runs (task, type, provider, repo, status, source, source_run_id) "
        "VALUES ('t', 'repo_chore', 'gemini', 'owner/site', 'running', 'review_note', %s)",
        (first,),
    )
    answer = press(migrated_db, 5, "dismiss", MERCURY, settings())
    assert answer == "A rerun is going; close its pull request to drop the note."
    assert state(migrated_db) == "question"


def test_dismiss_refused_with_pr(migrated_db):
    seed(migrated_db, "question", run_id=chore_run(migrated_db), pr_url="https://x/pull/1")
    answer = press(migrated_db, 5, "dismiss", MERCURY, settings())
    assert answer == "A rerun is going; close its pull request to drop the note."
    assert state(migrated_db) == "question"


@pytest.mark.parametrize("action", ["dismiss", "change"])
def test_press_after_edit(migrated_db, action):
    seed(migrated_db, card_updated_at="2026-10-01 00:00:00")
    answer = press(migrated_db, 5, action, MERCURY, settings())
    assert answer == "Luke changed this note since. I'll send the new version."
    # The row goes, so the next tick records the note again from D1 and sorts its new words.
    assert state(migrated_db) is None


def test_press_twice(migrated_db):
    seed(migrated_db)
    press(migrated_db, 5, "dismiss", MERCURY, settings())
    assert press(migrated_db, 5, "dismiss", MERCURY, settings()) == "Already dismissed."
    assert state(migrated_db) == "dismiss"


def test_press_gone(migrated_db):
    seed(migrated_db, "gone")
    assert press(migrated_db, 5, "dismiss", MERCURY, settings()) == "Luke deleted this note."


def test_press_untracked(migrated_db):
    answer = press(migrated_db, 5, "dismiss", MERCURY, settings())
    assert answer == "That note is no longer tracked."


def test_change_starts_chore(migrated_db):
    seed(migrated_db)
    answer = press(migrated_db, 5, "change", MERCURY, settings())
    assert answer.startswith("Started a chore, ")
    assert state(migrated_db) == "chore"
    task = migrated_db.execute("SELECT task FROM runs WHERE type = 'repo_chore'").fetchone()[0]
    assert "Change the heading" in task


def test_change_when_day_full_is_queued(migrated_db):
    seed(migrated_db)
    answer = press(migrated_db, 5, "change", MERCURY, settings(max_runs_per_day=0))
    assert answer == "Queued. It starts when the page and today's limits allow."
    assert state(migrated_db) == "capped"


def test_change_twice(migrated_db):
    seed(migrated_db)
    press(migrated_db, 5, "change", MERCURY, settings())
    assert press(migrated_db, 5, "change", MERCURY, settings()) == "Already started."


def test_change_on_question_refused(migrated_db):
    seed(migrated_db, "question", run_id=chore_run(migrated_db))
    answer = press(migrated_db, 5, "change", MERCURY, settings())
    assert answer == "This one already ran. Reply with a hint instead."
    assert state(migrated_db) == "question"


def test_hint_on_asked_card(migrated_db):
    seed(migrated_db)
    answer = hint_on_card(migrated_db, 70, "make it bold", MERCURY, settings())
    assert answer.startswith("Started a chore, ")
    task = migrated_db.execute("SELECT task FROM runs WHERE type = 'repo_chore'").fetchone()[0]
    lines = task.split("\n")
    at = lines.index("make it bold")
    assert lines[at - 2] == "The site owner's hint:"


def test_hint_kept_when_queued(migrated_db):
    seed(migrated_db)
    hint_on_card(migrated_db, 70, "make it bold", MERCURY, settings(max_runs_per_day=0))
    assert state(migrated_db) == "capped"
    hint = migrated_db.execute("SELECT hint FROM review_notes WHERE note_id = 5").fetchone()[0]
    assert hint == "make it bold"


def test_hint_on_unknown_message(migrated_db):
    seed(migrated_db)
    assert hint_on_card(migrated_db, 999, "x", MERCURY, settings()) is None
