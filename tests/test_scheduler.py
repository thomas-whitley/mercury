"""The scheduler: creates a site_check run through the API with the bearer
token, checks the site itself in the same process, writes the result, and
tracks consecutive failures per schedule entry.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.schedule_state import is_suspended, record_failure
from app.scheduler import run_due_checks, schedule_flight_watch, schedule_weekly_checks

BEARER_TOKEN = "test-bearer-token"
# Nothing listens on port 1, so a check against it fails at once.
UNREACHABLE = "http://127.0.0.1:1"


def test_run_due_checks_creates_a_run_and_writes_its_result(start_server, migrated_db, monkeypatch):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()

    created = run_due_checks(migrated_db, (f"{base_url}/health",), base_url, BEARER_TOKEN)

    assert len(created) == 1
    run_id = created[0]
    row = migrated_db.execute(
        "SELECT type, status, tokens_used, source FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row == ("site_check", "succeeded", 0, "scheduler")

    output = migrated_db.execute(
        "SELECT output FROM steps WHERE run_id = %s AND kind = 'check'", (run_id,)
    ).fetchone()[0]
    assert output["passed"] is True
    assert output["status_code"] == 200


def test_run_due_checks_records_a_failed_check(start_server, migrated_db, monkeypatch):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()

    created = run_due_checks(migrated_db, (UNREACHABLE,), base_url, BEARER_TOKEN)

    row = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (created[0],)).fetchone()
    assert row == ("failed",)


def test_run_due_checks_skips_a_suspended_site(start_server, migrated_db, monkeypatch):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    for _ in range(3):
        record_failure(migrated_db, f"site_uptime:{UNREACHABLE}")

    created = run_due_checks(migrated_db, (UNREACHABLE,), base_url, BEARER_TOKEN)

    assert created == []


def test_run_due_checks_suspends_after_the_third_consecutive_failure(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    name = f"site_uptime:{UNREACHABLE}"

    run_due_checks(migrated_db, (UNREACHABLE,), base_url, BEARER_TOKEN)
    run_due_checks(migrated_db, (UNREACHABLE,), base_url, BEARER_TOKEN)
    assert is_suspended(migrated_db, name) is False

    run_due_checks(migrated_db, (UNREACHABLE,), base_url, BEARER_TOKEN)

    assert is_suspended(migrated_db, name) is True


def test_run_due_checks_counts_a_refused_post_as_a_failure(start_server, migrated_db, monkeypatch):
    """A wrong or expired token must suspend the schedule, not skip it
    quietly every hour with nothing to show that checks have stopped."""
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    site = f"{base_url}/health"

    for _ in range(3):
        created = run_due_checks(migrated_db, (site,), base_url, "wrong-token")
        assert created == []

    assert is_suspended(migrated_db, f"site_uptime:{site}") is True


def test_run_due_checks_logs_the_created_run_with_no_client(
    start_server, migrated_db, monkeypatch, caplog
):
    """The exact line the live deploy's exit condition greps for.

    create_app() calls configure_logging(), which replaces the root handlers
    and caplog's with them, so the handler goes on the scheduler's logger.
    """
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    scheduler_logger = logging.getLogger("agent_runs.scheduler")
    scheduler_logger.addHandler(caplog.handler)

    try:
        with caplog.at_level("INFO", logger="agent_runs.scheduler"):
            created = run_due_checks(migrated_db, (f"{base_url}/health",), base_url, BEARER_TOKEN)
    finally:
        scheduler_logger.removeHandler(caplog.handler)

    assert f"scheduled run {created[0]} created with no client" in caplog.text


# Weekly browser checks: the scheduler only creates them. The self hosted
# checks worker claims them, and a lighthouse check nobody claims in the
# window falls back to PageSpeed on the Python worker.
PAGE = "https://a.example/"


def _checks(conn, page=PAGE):
    return conn.execute(
        "SELECT check_kind, status, claimed_by FROM runs "
        "WHERE type = 'site_check' AND task = %s ORDER BY check_kind",
        (page,),
    ).fetchall()


def test_schedule_weekly_checks_creates_a_lighthouse_and_a_crawl_per_page(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()

    created = schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)

    assert len(created) == 2
    # Created and left pending for a worker; the scheduler runs neither.
    assert _checks(migrated_db) == [
        ("broken_links", "pending", None),
        ("lighthouse", "pending", None),
    ]


def test_schedule_weekly_checks_creates_nothing_inside_the_week(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)
    migrated_db.execute("UPDATE runs SET created_at = now() - interval '6 days 23 hours'")

    created = schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)

    assert created == []
    assert len(_checks(migrated_db)) == 2


def test_schedule_weekly_checks_creates_the_next_once_the_week_is_up(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)
    migrated_db.execute("UPDATE runs SET created_at = now() - interval '7 days 1 minute'")

    created = schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)

    assert len(created) == 2
    assert len(_checks(migrated_db)) == 4


def test_schedule_weekly_checks_is_due_per_kind(start_server, migrated_db, monkeypatch):
    """A lighthouse check from this week does not hold back an overdue crawl."""
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)
    migrated_db.execute(
        "UPDATE runs SET created_at = now() - interval '8 days' WHERE check_kind = 'broken_links'"
    )

    created = schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)

    kinds = migrated_db.execute(
        "SELECT check_kind FROM runs WHERE id = ANY(%s::uuid[])", (created,)
    ).fetchall()
    assert kinds == [("broken_links",)]


def test_schedule_weekly_checks_logs_and_carries_on_when_the_api_refuses(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()

    created = schedule_weekly_checks(migrated_db, (PAGE,), base_url, "wrong-token")

    assert created == []
    assert _checks(migrated_db) == []


def _orphan(conn, minutes_old: int, kind: str | None = None, claimed: bool = False) -> str:
    """A site_check row the API wrote after the scheduler's POST had given up."""
    return str(
        conn.execute(
            "INSERT INTO runs (task, type, check_kind, claimed_by, created_at) "
            "VALUES ('https://example.com/health', 'site_check', %s, %s, "
            "now() - make_interval(mins => %s)) RETURNING id",
            (kind, "worker-1" if claimed else None, minutes_old),
        ).fetchone()[0]
    )


def test_an_orphaned_uptime_run_is_closed_as_an_error_with_its_reason(
    start_server, migrated_db, monkeypatch
):
    """On 2026-09-30 at 21:00 the ingress dropped the scheduler's POST while
    the api cold started, then delivered it. The row it wrote stayed pending
    with nobody to close it."""
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    orphan = _orphan(migrated_db, minutes_old=60)

    run_due_checks(migrated_db, (), base_url, BEARER_TOKEN)

    status, finished = migrated_db.execute(
        "SELECT status, finished_at IS NOT NULL FROM runs WHERE id = %s", (orphan,)
    ).fetchone()
    done = migrated_db.execute(
        "SELECT payload FROM events WHERE run_id = %s AND payload->>'kind' = 'done'", (orphan,)
    ).fetchone()[0]
    assert (status, finished) == ("error", True)
    assert done["output"]["status"] == "error"
    assert "scheduler" in done["output"]["reason"]


def test_a_recent_or_claimed_or_weekly_pending_check_is_left_alone(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    recent = _orphan(migrated_db, minutes_old=2)
    claimed = _orphan(migrated_db, minutes_old=60, claimed=True)
    weekly = _orphan(migrated_db, minutes_old=60, kind="lighthouse")

    run_due_checks(migrated_db, (), base_url, BEARER_TOKEN)

    rows = migrated_db.execute(
        "SELECT id::text, status FROM runs WHERE id = ANY(%s::uuid[])",
        ([recent, claimed, weekly],),
    ).fetchall()
    assert {status for _, status in rows} == {"pending"}


def test_an_orphaned_ci_watch_run_is_closed_too(start_server, migrated_db, monkeypatch):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    orphan = _orphan(migrated_db, minutes_old=60, kind="ci_watch")

    run_due_checks(migrated_db, (), base_url, BEARER_TOKEN)

    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (orphan,)).fetchone()
    assert status == ("error",)


# The flight watch: a daily and a weekly flight_watch check, created here and
# left pending for the flight-finder worker on the home PC to claim.
MELBOURNE = ZoneInfo("Australia/Melbourne")


def _at(hour: int, minute: int, day: int = 1) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=MELBOURNE)


def _flight_watches(conn, task: str) -> list[tuple]:
    return conn.execute(
        "SELECT check_kind, status, claimed_by, source FROM runs "
        "WHERE type = 'site_check' AND check_kind = 'flight_watch' AND task = %s",
        (task,),
    ).fetchall()


def _schedule_flight_watch(conn, api, now):
    return schedule_flight_watch(conn, api, BEARER_TOKEN, "Australia/Melbourne", now=now)


def test_flight_watch_daily_created_once_after_half_past_seven(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()
    # The weekly one is made on the first tick whatever the hour, so it is
    # out of the way before the daily boundary is looked at.
    _schedule_flight_watch(migrated_db, api, _at(6, 0))

    assert _schedule_flight_watch(migrated_db, api, _at(7, 29)) == []
    assert _flight_watches(migrated_db, "daily") == []

    created = _schedule_flight_watch(migrated_db, api, _at(7, 30))

    assert len(created) == 1
    assert _flight_watches(migrated_db, "daily") == [("flight_watch", "pending", None, "scheduler")]
    assert _schedule_flight_watch(migrated_db, api, _at(8, 0)) == []
    assert _schedule_flight_watch(migrated_db, api, _at(23, 0)) == []


def test_flight_watch_daily_the_next_day_gets_its_own(start_server, migrated_db, monkeypatch):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()
    _schedule_flight_watch(migrated_db, api, _at(8, 0))
    migrated_db.execute(
        "UPDATE runs SET created_at = %s, status = 'succeeded', finished_at = now() "
        "WHERE task = 'daily'",
        (_at(8, 0),),
    )

    created = _schedule_flight_watch(migrated_db, api, _at(8, 0, day=2))

    assert len(created) == 1
    assert len(_flight_watches(migrated_db, "daily")) == 2


def test_flight_watch_weekly_created_when_none_in_7_days(start_server, migrated_db, monkeypatch):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()

    _schedule_flight_watch(migrated_db, api, _at(6, 0))
    assert _flight_watches(migrated_db, "weekly") == [
        ("flight_watch", "pending", None, "scheduler")
    ]

    migrated_db.execute("UPDATE runs SET created_at = now() - interval '6 days 23 hours'")
    assert _schedule_flight_watch(migrated_db, api, _at(6, 0)) == []

    migrated_db.execute(
        "UPDATE runs SET created_at = now() - interval '7 days 1 minute', "
        "status = 'succeeded', finished_at = now()"
    )
    created = _schedule_flight_watch(migrated_db, api, _at(6, 0))

    assert len(created) == 1
    assert len(_flight_watches(migrated_db, "weekly")) == 2


def test_flight_watch_logs_and_carries_on_when_the_api_refuses(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()

    created = schedule_flight_watch(
        migrated_db, api, "wrong-token", "Australia/Melbourne", now=_at(8, 0)
    )

    assert created == []
    assert _flight_watches(migrated_db, "daily") == []
    assert _flight_watches(migrated_db, "weekly") == []


def test_the_weekly_page_checks_never_create_a_flight_watch(start_server, migrated_db, monkeypatch):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()

    schedule_weekly_checks(migrated_db, (PAGE,), base_url, BEARER_TOKEN)

    count = migrated_db.execute(
        "SELECT count(*) FROM runs WHERE check_kind = 'flight_watch'"
    ).fetchone()[0]
    assert count == 0


def test_flight_watch_daily_waits_while_an_earlier_daily_is_unfinished(
    start_server, migrated_db, monkeypatch
):
    """A PC asleep for a week must wake to one daily, not seven run back to back."""
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()
    _schedule_flight_watch(migrated_db, api, _at(8, 0))
    migrated_db.execute("UPDATE runs SET created_at = %s WHERE task = 'daily'", (_at(8, 0),))

    assert _schedule_flight_watch(migrated_db, api, _at(7, 30, day=2)) == []

    migrated_db.execute(
        "UPDATE runs SET status = 'succeeded', finished_at = now() WHERE task = 'daily'"
    )
    created = _schedule_flight_watch(migrated_db, api, _at(8, 0, day=2))

    assert len(created) == 1
    assert len(_flight_watches(migrated_db, "daily")) == 2


def test_flight_watch_daily_waits_while_an_earlier_daily_is_claimed(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()
    _schedule_flight_watch(migrated_db, api, _at(8, 0))
    migrated_db.execute(
        "UPDATE runs SET created_at = %s, claimed_by = 'flights-1', status = 'running' "
        "WHERE task = 'daily'",
        (_at(8, 0),),
    )

    assert _schedule_flight_watch(migrated_db, api, _at(8, 0, day=2)) == []


def test_flight_watch_weekly_waits_while_an_earlier_weekly_is_unfinished(
    start_server, migrated_db, monkeypatch
):
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()
    _schedule_flight_watch(migrated_db, api, _at(6, 0))
    migrated_db.execute("UPDATE runs SET created_at = now() - interval '8 days'")

    assert _schedule_flight_watch(migrated_db, api, _at(6, 0)) == []

    migrated_db.execute(
        "UPDATE runs SET status = 'succeeded', finished_at = now() WHERE task = 'weekly'"
    )
    created = _schedule_flight_watch(migrated_db, api, _at(6, 0))

    assert len(created) == 1
    assert len(_flight_watches(migrated_db, "weekly")) == 2


def test_flight_watch_daily_is_made_once_a_day_even_after_it_closes(
    start_server, migrated_db, monkeypatch
):
    """The same day dedupe on its own: a closed daily holds nothing back, so
    only the check for one created since 07:30 stops a second one today."""
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    api = start_server()
    assert len(_schedule_flight_watch(migrated_db, api, _at(8, 0))) == 2
    migrated_db.execute(
        "UPDATE runs SET status = 'succeeded', finished_at = now() WHERE task = 'daily'"
    )

    assert _schedule_flight_watch(migrated_db, api, _at(9, 0)) == []
    assert _schedule_flight_watch(migrated_db, api, _at(23, 0)) == []
    assert len(_flight_watches(migrated_db, "daily")) == 1


def test_a_pending_flight_watch_is_not_closed_as_an_orphan(start_server, migrated_db, monkeypatch):
    """The home PC can sleep for hours, and its checks wait for it."""
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", BEARER_TOKEN)
    base_url = start_server()
    pending = _orphan(migrated_db, minutes_old=600, kind="flight_watch")

    run_due_checks(migrated_db, (), base_url, BEARER_TOKEN)

    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (pending,)).fetchone()
    assert status == ("pending",)
