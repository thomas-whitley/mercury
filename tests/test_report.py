"""The report, per decision 9 of docs/build-brief-evals.md: escalations first,
then the chores Mercury started itself, then where the eval lives, then spend
against the caps. Served at GET /report and by the MCP report tool."""

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from psycopg.types.json import Jsonb

from app.report import build_report, waiting_counts
from tests.test_escalation import escalated_chore

CAPS = {"daily_tokens": 500_000, "monthly_usd": 5.0, "max_runs_per_day": 40}
WEEK_AGO = datetime.now(UTC) - timedelta(days=7)


def report(conn, since=WEEK_AGO) -> str:
    return build_report(conn, since, **CAPS)


def spend(conn, run_id: str, tokens: int) -> None:
    conn.execute(
        "INSERT INTO steps (run_id, seq, kind, tokens, finished_at) "
        "VALUES (%s, 2, 'edit', %s, now())",
        (run_id, tokens),
    )
    conn.execute("UPDATE runs SET tokens_used = %s WHERE id = %s", (tokens, run_id))


def test_an_escalated_chain_shows_every_run_its_diff_output_and_state(migrated_db):
    first = escalated_chore(
        migrated_db, "tests still failing after 3 attempts", diff="+bad\n", test_output="E nope"
    )
    second = escalated_chore(
        migrated_db,
        "weakened tests",
        source_run_id=first,
        hint="keep test_add",
        diff="+    return a / b\n",
        test_output="E   AssertionError: 3 != 3.5",
    )
    spend(migrated_db, second, 1234)

    text = report(migrated_db)

    escalations = text.split("## Escalations", 1)[1].split("\n## ", 1)[0]
    assert "owner/fixture: Add divide to calc.py" in escalations
    assert first[:8] in escalations and second[:8] in escalations
    assert "| gemini | 1,234 | 0.0000 | escalated | weakened tests | keep test_add |" in escalations
    assert "+    return a / b" in escalations  # the newest run's diff, not the first's
    assert "+bad" not in escalations
    assert "3 != 3.5" in escalations
    assert "Waiting for a hint (reply on Telegram or call advise)." in escalations


def test_a_chore_marked_for_a_claude_session_says_so(migrated_db):
    run_id = escalated_chore(migrated_db, "tests still failing after 3 attempts")
    migrated_db.execute("UPDATE runs SET needs_claude = true WHERE id = %s", (run_id,))

    assert "Take it to a Claude session." in report(migrated_db)


def test_a_rescued_chore_shows_its_pull_request(migrated_db):
    first = escalated_chore(migrated_db, "tests still failing after 3 attempts")
    rescued = escalated_chore(migrated_db, "x", source_run_id=first, hint="a hint")
    migrated_db.execute(
        "UPDATE runs SET status = 'succeeded', escalation_reason = NULL WHERE id = %s", (rescued,)
    )
    migrated_db.execute(
        "UPDATE steps SET output = %s WHERE run_id = %s",
        (Jsonb({"status": "succeeded", "pr_url": "https://github.com/o/f/pull/9"}), rescued),
    )

    assert "Rescued: https://github.com/o/f/pull/9" in report(migrated_db)


def test_an_escalation_before_since_is_left_out(migrated_db):
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute(
        "UPDATE runs SET created_at = now() - interval '30 days' WHERE id = %s", (run_id,)
    )

    assert run_id[:8] not in report(migrated_db)
    assert "No escalations." in report(migrated_db)


def test_chores_mercury_started_are_listed_with_their_pull_requests(migrated_db):
    assert "None yet." in report(migrated_db)
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute(
        "UPDATE runs SET source = 'scheduler', status = 'succeeded' WHERE id = %s", (run_id,)
    )
    migrated_db.execute(
        "UPDATE steps SET output = %s WHERE run_id = %s",
        (Jsonb({"status": "succeeded", "pr_url": "https://github.com/o/f/pull/3"}), run_id),
    )

    started = report(migrated_db).split("## Chores Mercury started", 1)[1].split("\n## ", 1)[0]
    assert "https://github.com/o/f/pull/3" in started


def test_the_spend_section_states_each_cap(migrated_db):
    run_id = escalated_chore(migrated_db, "x")
    spend(migrated_db, run_id, 2500)

    spend_section = report(migrated_db).split("## Spend", 1)[1]
    assert "gemini: 2,500 of 500,000 tokens today" in spend_section
    assert "of 5.00 USD this month" in spend_section
    assert "of 40 model runs today" in spend_section


def test_the_eval_section_says_where_the_results_are(migrated_db):
    assert "evals/results/" in report(migrated_db).split("## Eval", 1)[1]


def test_waiting_counts_leave_out_eval_chores(migrated_db):
    escalated_chore(migrated_db, "x")
    escalated_chore(migrated_db, "x", source="eval")
    marked = escalated_chore(migrated_db, "x")
    migrated_db.execute("UPDATE runs SET needs_claude = true WHERE id = %s", (marked,))
    advised_from = escalated_chore(migrated_db, "x")
    escalated_chore(migrated_db, "x", source_run_id=advised_from, hint="h")

    assert waiting_counts(migrated_db) == (2, 1)


@pytest.fixture
def reporting_api(start_server, auth_headers):
    return start_server()


def test_get_report_needs_the_token_and_returns_markdown(reporting_api, auth_headers, migrated_db):
    assert httpx2.get(f"{reporting_api}/report").status_code == 401

    response = httpx2.get(f"{reporting_api}/report?since=2026-01-01", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# Mercury report since 2026-01-01")


def test_get_report_refuses_a_bad_date(reporting_api, auth_headers):
    response = httpx2.get(f"{reporting_api}/report?since=yesterday", headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.parametrize("source", ["eval", "bank"])
def test_a_quiet_chore_is_left_out_of_the_escalations(migrated_db, source):
    """A bank batch on a 7B model escalates most of its chores; listing each
    one would bury the escalations Thomas has to act on (decisions 18, 27)."""
    run_id = escalated_chore(migrated_db, "tests still failing after 3 attempts", source=source)

    assert run_id[:8] not in report(migrated_db)
