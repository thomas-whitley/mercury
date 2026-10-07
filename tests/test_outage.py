"""A chore whose model never answered on any provider is retried by the
hourly scheduler Job, at most three times in a row, per decision 17 of
docs/build-brief-evals.md. The run after the third retry escalates."""

from psycopg.types.json import Jsonb

from app.outage import MAX_OUTAGE_RETRIES, retry_outages
from app.repo_chore import OUTAGE
from app.telegram import TelegramClient

CHAT = 42
PAGE = "https://mercury.test"


def outage_run(
    conn,
    minutes_ago: int = 45,
    *,
    source_run_id: str | None = None,
    hint: str | None = None,
    source: str = "n8n",
) -> str:
    run_id = str(
        conn.execute(
            "INSERT INTO runs (task, type, provider, repo, status, source, source_run_id, hint, "
            "created_at, finished_at) "
            "VALUES ('Add divide', 'repo_chore', 'ollama', 'owner/fixture', 'error', %s, %s, %s, "
            "now() - make_interval(mins => %s + 1), now() - make_interval(mins => %s)) "
            "RETURNING id",
            (source, source_run_id, hint, minutes_ago, minutes_ago),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO steps (run_id, seq, kind, output) VALUES (%s, 1, 'done', %s)",
        (run_id, Jsonb({"status": "error", "reason": OUTAGE})),
    )
    return run_id


def retries_of(conn, run_id: str) -> list[tuple]:
    return conn.execute(
        "SELECT task, repo, status, source, hint, provider FROM runs WHERE source_run_id = %s",
        (run_id,),
    ).fetchall()


def test_an_outage_older_than_half_an_hour_is_retried_once(migrated_db):
    failed = outage_run(migrated_db, hint="use floats")

    queued = retry_outages(migrated_db, None, None, PAGE)

    assert len(queued) == 1
    assert retries_of(migrated_db, failed) == [
        ("Add divide", "owner/fixture", "pending", "n8n", "use floats", "gemini")
    ]


def test_a_fresh_outage_waits_for_the_next_tick(migrated_db):
    failed = outage_run(migrated_db, minutes_ago=5)

    assert retry_outages(migrated_db, None, None, PAGE) == []
    assert retries_of(migrated_db, failed) == []


def test_running_twice_queues_one_retry(migrated_db):
    outage_run(migrated_db)

    first = retry_outages(migrated_db, None, None, PAGE)
    second = retry_outages(migrated_db, None, None, PAGE)

    assert (len(first), second) == (1, [])


def test_an_error_that_was_not_an_outage_is_left(migrated_db):
    failed = outage_run(migrated_db)
    migrated_db.execute(
        "UPDATE steps SET output = %s WHERE run_id = %s",
        (Jsonb({"status": "error", "reason": "git clone failed"}), failed),
    )

    assert retry_outages(migrated_db, None, None, PAGE) == []


def test_after_three_retries_the_fourth_outage_escalates_and_tells_the_owner(
    migrated_db, fake_telegram
):
    newest = outage_run(migrated_db)
    for _ in range(MAX_OUTAGE_RETRIES):
        newest = outage_run(migrated_db, source_run_id=newest)

    queued = retry_outages(migrated_db, TelegramClient("123:abc", fake_telegram.url), CHAT, PAGE)

    assert queued == []
    row = migrated_db.execute(
        "SELECT status, escalation_reason FROM runs WHERE id = %s", (newest,)
    ).fetchone()
    assert row == ("escalated", OUTAGE)
    [message] = fake_telegram.sent()
    assert OUTAGE in message["text"]


def test_an_eval_chore_escalates_after_its_outages_without_a_message(migrated_db, fake_telegram):
    newest = outage_run(migrated_db, source="eval")
    for _ in range(MAX_OUTAGE_RETRIES):
        newest = outage_run(migrated_db, source_run_id=newest, source="eval")

    retry_outages(migrated_db, TelegramClient("123:abc", fake_telegram.url), CHAT, PAGE)

    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (newest,)).fetchone()
    assert status == ("escalated",)
    assert fake_telegram.sent() == []


def test_a_retry_that_follows_an_escalation_counts_from_zero(migrated_db):
    """Only the outages at the end of a chain count; an advised rerun that
    then hits an outage starts its own three."""
    first = outage_run(migrated_db)
    migrated_db.execute("UPDATE runs SET status = 'escalated' WHERE id = %s", (first,))
    newest = outage_run(migrated_db, source_run_id=first, hint="a hint")
    for _ in range(MAX_OUTAGE_RETRIES - 1):
        newest = outage_run(migrated_db, source_run_id=newest, hint="a hint")

    assert len(retry_outages(migrated_db, None, None, PAGE)) == 1
