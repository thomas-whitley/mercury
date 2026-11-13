"""Every new review note is sorted first (app/note_sort.py), whatever its page
or the day's limits. tests/test_review_notes.py stands in a "change" verdict
for its older chore tests; this file uses the real queue_sort."""

import psycopg

from app.review_notes import start_note_chores
from tests.test_review_notes import REPO, make_config, note


def runs_of(conn, type_: str) -> list:
    return conn.execute("SELECT id, status FROM runs WHERE type = %s", (type_,)).fetchall()


def state_of(conn, note_id: int) -> str:
    return conn.execute("SELECT state FROM review_notes WHERE note_id = %s", (note_id,)).fetchone()[
        0
    ]


def test_new_note_is_sorted_not_chored(migrated_db):
    started = start_note_chores(migrated_db, [note(1)], make_config(), REPO)

    assert started == []
    assert state_of(migrated_db, 1) == "sorting"
    [(run_id, status)] = runs_of(migrated_db, "note_sort")
    assert status == "pending"
    assert runs_of(migrated_db, "repo_chore") == []
    words = migrated_db.execute(
        "SELECT run_id, note_body, note_anchor FROM review_notes WHERE note_id = 1"
    ).fetchone()
    assert words == (run_id, "Change the heading", "Our story")


def test_new_note_sorted_while_page_busy(migrated_db):
    migrated_db.execute(
        "INSERT INTO review_notes (note_id, host, page, note_updated_at, state) "
        "VALUES (9, 'h', '/about/', 't', 'waiting')"
    )
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    assert state_of(migrated_db, 1) == "sorting"


def test_new_note_sorted_over_daily_cap(migrated_db):
    start_note_chores(migrated_db, [note(1)], make_config(daily_cap=0), REPO)
    assert state_of(migrated_db, 1) == "sorting"


def test_failed_sort_is_requeued(migrated_db):
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    [(first, _)] = runs_of(migrated_db, "note_sort")

    start_note_chores(migrated_db, [note(1)], make_config(), REPO)  # still pending: no new run
    assert len(runs_of(migrated_db, "note_sort")) == 1

    migrated_db.execute(
        "UPDATE runs SET status = 'error', finished_at = now() WHERE id = %s", (first,)
    )
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)

    runs = runs_of(migrated_db, "note_sort")
    assert len(runs) == 2
    newest = migrated_db.execute("SELECT run_id FROM review_notes WHERE note_id = 1").fetchone()[0]
    assert newest != first and state_of(migrated_db, 1) == "sorting"


def test_refused_sort_is_requeued(migrated_db):
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    [(first, _)] = runs_of(migrated_db, "note_sort")
    migrated_db.execute(
        "UPDATE runs SET status = 'refused', finished_at = now() WHERE id = %s", (first,)
    )
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    assert len(runs_of(migrated_db, "note_sort")) == 2


def test_capped_from_sort_starts_chore_when_free(migrated_db):
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    migrated_db.execute("UPDATE review_notes SET state = 'capped', run_id = NULL")

    started = start_note_chores(migrated_db, [note(1)], make_config(), REPO)

    assert len(started) == 1
    assert state_of(migrated_db, 1) == "chore"
    assert len(runs_of(migrated_db, "repo_chore")) == 1


def test_capped_waiting_for_page_sets_held(migrated_db):
    migrated_db.execute(
        "INSERT INTO review_notes (note_id, host, page, note_updated_at, state) "
        "VALUES (9, 'h', '/about/', 't', 'waiting')"
    )
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    migrated_db.execute("UPDATE review_notes SET state = 'capped', run_id = NULL WHERE note_id = 1")

    start_note_chores(migrated_db, [note(1)], make_config(), REPO)

    held = migrated_db.execute("SELECT held_by_page FROM review_notes WHERE note_id = 1")
    assert held.fetchone()[0] is True
    assert state_of(migrated_db, 1) == "capped"


def test_preview_host_unchanged(migrated_db):
    start_note_chores(migrated_db, [note(1, host="preview.example")], make_config(), REPO)
    assert state_of(migrated_db, 1) == "preview"
    assert runs_of(migrated_db, "note_sort") == []


def test_asked_note_is_left_alone(migrated_db):
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    migrated_db.execute("UPDATE review_notes SET state = 'asked'")
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    assert len(runs_of(migrated_db, "note_sort")) == 1
    assert state_of(migrated_db, 1) == "asked"


def test_sort_rolls_back_on_error(migrated_db, monkeypatch):
    def broken(*args, **kwargs):
        raise psycopg.errors.UndefinedTable("boom")

    monkeypatch.setattr("app.review_notes.start_chore", broken)
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    assert state_of(migrated_db, 1) == "sorting"  # sorting never touches start_chore
