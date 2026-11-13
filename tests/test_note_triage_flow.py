# ruff: noqa: F811 - pytest fixtures imported from test_review_notes are parameters here
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
        "UPDATE runs SET status = 'error', finished_at = now() - interval '2 hours' WHERE id = %s",
        (first,),
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
        "UPDATE runs SET status = 'refused', finished_at = now() - interval '2 hours' "
        "WHERE id = %s",
        (first,),
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


# ---- The scheduler's part: D1 "done" for dismissals, cards for old questions,
# edits and deletions of notes still being sorted or asked about ----

from app.d1 import D1Client  # noqa: E402
from app.review_notes import card_for_old_questions, finish_dismissals  # noqa: E402
from app.telegram import TelegramClient  # noqa: E402
from tests.test_review_notes import (  # noqa: E402, F401 - fixtures used by name
    DONE_SQL,
    cloudflare,
    d1_for,
    d1_writes,
    github,
    settle,
)


def seed_row(conn, state: str, **cols) -> None:
    conn.execute(
        "INSERT INTO review_notes (note_id, host, page, note_updated_at, state, note_body) "
        "VALUES (1, 'live.example.com', '/about/', '2026-10-19 01:00:00', %s, 'hello')",
        (state,),
    )
    for column, value in cols.items():
        conn.execute(f"UPDATE review_notes SET {column} = %s WHERE note_id = 1", (value,))


def test_dismiss_marks_d1_done(migrated_db, cloudflare):
    cloudflare.add_note(1)
    seed_row(migrated_db, "dismiss")

    assert finish_dismissals(migrated_db, d1_for(cloudflare)) == 1

    assert d1_writes(cloudflare) == [{"sql": DONE_SQL, "params": [1]}]
    assert state_of(migrated_db, 1) == "dismissed"


def test_dismiss_d1_down_retries(migrated_db):
    seed_row(migrated_db, "dismiss")
    unreachable = D1Client("t", "acct", "db", "http://127.0.0.1:9")
    assert finish_dismissals(migrated_db, unreachable) == 0
    assert state_of(migrated_db, 1) == "dismiss"


def test_dismissed_note_is_not_marked_gone(migrated_db, cloudflare, github):
    cloudflare.add_note(1, status="done")
    seed_row(migrated_db, "dismissed")
    settle(migrated_db, cloudflare, github)
    assert state_of(migrated_db, 1) == "dismissed"


def test_asked_edit_flagged(migrated_db, cloudflare, github):
    cloudflare.add_note(1, updated_at="2026-11-01 00:00:00")
    seed_row(migrated_db, "asked")
    settle(migrated_db, cloudflare, github)
    written = migrated_db.execute("SELECT note_updated_at FROM review_notes").fetchone()[0]
    assert written == "2026-11-01 00:00:00"
    assert state_of(migrated_db, 1) == "asked"


def test_asked_gone(migrated_db, cloudflare, github):
    seed_row(migrated_db, "asked")
    settle(migrated_db, cloudflare, github)
    assert state_of(migrated_db, 1) == "gone"


def test_sorting_gone(migrated_db, cloudflare, github):
    seed_row(migrated_db, "sorting")
    settle(migrated_db, cloudflare, github)
    assert state_of(migrated_db, 1) == "gone"


def test_old_question_gets_one_card(migrated_db, fake_telegram):
    seed_row(migrated_db, "question")
    client = TelegramClient("123:abc", base_url=fake_telegram.url)

    assert card_for_old_questions(migrated_db, client, 42, "Luke") == 1
    assert card_for_old_questions(migrated_db, client, 42, "Luke") == 0

    [sent] = fake_telegram.sent()
    assert sent["text"].startswith("Luke left a note on /about/:")
    assert "note:1:dismiss" in str(sent["reply_markup"])
    assert "note:1:change" not in str(sent["reply_markup"])
    card, written = migrated_db.execute(
        "SELECT card_message_id, card_updated_at FROM review_notes"
    ).fetchone()
    assert (card, written) == (1, "2026-10-19 01:00:00")


def test_old_question_card_waits_for_telegram(migrated_db):
    seed_row(migrated_db, "question")
    client = TelegramClient("123:abc", base_url="http://127.0.0.1:9")
    assert card_for_old_questions(migrated_db, client, 42, "Luke") == 0
    card = migrated_db.execute("SELECT card_message_id FROM review_notes").fetchone()[0]
    assert card is None


def test_scheduler_tick_finishes_dismissals_and_cards_old_questions(
    migrated_db, cloudflare, github, fake_telegram
):
    import dataclasses

    from app.github import GitHubClient
    from app.scheduler import advance_review_notes
    from tests.test_review_notes import mercury_config, settings_for

    cloudflare.add_note(1)
    cloudflare.add_note(2, page="/contact/")
    seed_row(migrated_db, "dismiss")
    migrated_db.execute(
        "INSERT INTO review_notes (note_id, host, page, note_updated_at, state, note_body) "
        "VALUES (2, 'live.example.com', '/contact/', '2026-10-19 01:00:00', 'question', 'hi')"
    )
    config = dataclasses.replace(
        mercury_config(make_config(live_hosts=("live.example.com",))), telegram_chat_id=42
    )
    client = TelegramClient("123:abc", base_url=fake_telegram.url)

    advance_review_notes(
        migrated_db, settings_for(cloudflare), config, client, GitHubClient("t", github.url)
    )

    assert state_of(migrated_db, 1) == "dismissed"
    assert cloudflare.notes[0]["status"] == "done"
    assert migrated_db.execute(
        "SELECT card_message_id IS NOT NULL FROM review_notes WHERE note_id = 2"
    ).fetchone() == (True,)


def test_sort_runs_do_not_use_the_daily_cap(migrated_db):
    # Review: a note_sort run was counted as a note chore, so chit-chat notes filled the cap.
    start_note_chores(migrated_db, [note(1)], make_config(daily_cap=1), REPO)
    migrated_db.execute("UPDATE review_notes SET state = 'asked' WHERE note_id = 1")
    start_note_chores(migrated_db, [note(2, page="/contact/")], make_config(daily_cap=1), REPO)
    migrated_db.execute("UPDATE review_notes SET state = 'capped', run_id = NULL WHERE note_id = 2")

    started = start_note_chores(
        migrated_db, [note(2, page="/contact/")], make_config(daily_cap=1), REPO
    )

    assert len(started) == 1


def test_failed_sort_waits_an_hour(migrated_db):
    # Review: a failed sort was queued again every tick, spending a model call each time.
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    [(first, _)] = runs_of(migrated_db, "note_sort")
    migrated_db.execute(
        "UPDATE runs SET status = 'error', finished_at = now() - interval '10 minutes' "
        "WHERE id = %s",
        (first,),
    )
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    assert len(runs_of(migrated_db, "note_sort")) == 1

    migrated_db.execute(
        "UPDATE runs SET finished_at = now() - interval '61 minutes' WHERE id = %s", (first,)
    )
    start_note_chores(migrated_db, [note(1)], make_config(), REPO)
    assert len(runs_of(migrated_db, "note_sort")) == 2


def test_card_carries_the_time_of_the_words_it_shows(
    migrated_db, cloudflare, github, fake_telegram
):
    # Review: an edit stamped on a sorting row made a card of old words look current,
    # so Dismiss would close words Thomas never saw.
    from app.config import load_settings
    from app.mercury_config import MercuryConfig
    from app.model import StubModel
    from app.note_buttons import press
    from app.note_sort import run_note_sort

    cloudflare.add_note(1, updated_at="2026-10-19 01:00:00")
    start_note_chores(migrated_db, open_notes_of(cloudflare), make_config(), REPO)
    cloudflare.notes[0]["updated_at"] = "2026-10-20 09:00:00"
    cloudflare.notes[0]["body"] = "Actually, change the phone number"
    settle(migrated_db, cloudflare, github)

    [(run_id, _)] = runs_of(migrated_db, "note_sort")
    client = TelegramClient("123:abc", base_url=fake_telegram.url)
    run_note_sort(migrated_db, str(run_id), StubModel(['{"kind": "other"}']), client, 42, "Luke")

    card = migrated_db.execute("SELECT card_updated_at FROM review_notes").fetchone()[0]
    assert card == "2026-10-19 01:00:00"
    mercury = MercuryConfig(sites=(), repos=(REPO,), review_notes=make_config())
    answer = press(migrated_db, 1, "dismiss", mercury, load_settings())
    assert answer.endswith("changed this note since. I'll send the new version.")


def test_note_starts_take_one_lock(migrated_db, database_url):
    # Review: the webhook and the scheduler could both start a chore on one page.
    import threading

    import psycopg

    from app.review_notes import START_LOCK

    migrated_db.execute(
        "INSERT INTO review_notes (note_id, host, page, note_updated_at, state, note_body) "
        "VALUES (1, 'live.example.com', '/about/', '2026-10-19 01:00:00', 'capped', 'x')"
    )
    holder = psycopg.connect(database_url)
    holder.execute("SELECT pg_advisory_xact_lock(%s)", (START_LOCK,))
    done = threading.Event()

    def start():
        with psycopg.connect(database_url, autocommit=True) as conn:
            start_note_chores(
                conn,
                [note(1, host="live.example.com")],
                make_config(live_hosts=("live.example.com",)),
                REPO,
            )
        done.set()

    worker = threading.Thread(target=start)
    worker.start()
    assert not done.wait(0.5)  # blocked on the lock
    holder.rollback()
    holder.close()
    assert done.wait(10)
    worker.join()


def open_notes_of(cloudflare):
    from app.review_notes import open_notes

    return open_notes(d1_for(cloudflare))
