"""advise reruns an escalated chore from main with the owner's hint, per
decisions 6 and 8 of docs/build-brief-evals.md. It starts without Approve,
on the type's first rung, at most twice for one chore; after that the chore
is marked for a Claude session and advise refuses a third."""

import pytest

from app.advice import (
    MAX_ADVISED,
    AdviceRefused,
    advise,
    advised_count,
    mark_if_needs_claude,
)
from app.mercury_config import RepoConfig
from tests.test_escalation import escalated_chore

REPOS = (RepoConfig(name="owner/fixture", test_command="python -m pytest -q"),)


def run_row(conn, run_id: str) -> dict:
    row = conn.execute(
        "SELECT task, type, repo, status, source, source_run_id::text, hint, provider "
        "FROM runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    keys = ("task", "type", "repo", "status", "source", "source_run_id", "hint", "provider")
    return dict(zip(keys, row, strict=True))


def test_advice_on_an_escalated_chore_queues_a_rerun_that_needs_no_approval(migrated_db):
    failed = escalated_chore(migrated_db, "tests still failing after 3 attempts")

    new_id = advise(migrated_db, failed, "  Use float division.  ", "mcp", REPOS)

    assert run_row(migrated_db, new_id) == {
        "task": "Add divide to calc.py",
        "type": "repo_chore",
        "repo": "owner/fixture",
        "status": "pending",
        "source": "mcp",
        "source_run_id": failed,
        "hint": "Use float division.",
        "provider": "gemini",
    }


@pytest.mark.parametrize("status", ["succeeded", "failed", "running", "error"])
def test_advice_on_a_chore_that_did_not_escalate_is_refused(migrated_db, status):
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute("UPDATE runs SET status = %s WHERE id = %s", (status, run_id))

    with pytest.raises(AdviceRefused, match="escalated"):
        advise(migrated_db, run_id, "a hint", "mcp", REPOS)
    assert migrated_db.execute("SELECT count(*) FROM runs").fetchone() == (1,)


def test_advice_on_a_run_that_is_not_a_chore_is_refused(migrated_db):
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute("UPDATE runs SET type = 'pytest' WHERE id = %s", (run_id,))

    with pytest.raises(AdviceRefused, match="repo chore"):
        advise(migrated_db, run_id, "a hint", "mcp", REPOS)


def test_advice_on_an_older_run_of_a_chore_is_refused(migrated_db):
    first = escalated_chore(migrated_db, "x")
    escalated_chore(migrated_db, "x", source_run_id=first, hint="earlier hint")

    with pytest.raises(AdviceRefused, match="newer run"):
        advise(migrated_db, first, "a hint", "mcp", REPOS)


@pytest.mark.parametrize("hint", ["", "   ", "x" * 2001])
def test_a_blank_or_huge_hint_is_refused(migrated_db, hint):
    run_id = escalated_chore(migrated_db, "x")

    with pytest.raises(AdviceRefused, match="hint"):
        advise(migrated_db, run_id, hint, "mcp", REPOS)


def test_a_repo_no_longer_listed_is_refused(migrated_db):
    run_id = escalated_chore(migrated_db, "x")

    with pytest.raises(AdviceRefused, match="owner/other"):
        advise(migrated_db, run_id, "a hint", "mcp", (RepoConfig(name="owner/other"),))


def _advised_chain(conn, advised_runs: int) -> str:
    """An escalated chore followed by that many escalated advised reruns.
    Returns the newest run."""
    newest = escalated_chore(conn, "x")
    for number in range(advised_runs):
        newest = escalated_chore(conn, "x", source_run_id=newest, hint=f"hint {number}")
    return newest


def test_a_third_advised_rerun_is_refused_and_says_to_take_it_to_claude(migrated_db):
    newest = _advised_chain(migrated_db, MAX_ADVISED)

    with pytest.raises(AdviceRefused, match="Claude session"):
        advise(migrated_db, newest, "a third hint", "mcp", REPOS)


def test_an_outage_retry_of_an_advised_run_is_not_counted_as_advice(migrated_db):
    advised = _advised_chain(migrated_db, 1)
    # An outage retry copies the hint but comes from a run that ended in error.
    migrated_db.execute("UPDATE runs SET status = 'error' WHERE id = %s", (advised,))
    retry = escalated_chore(migrated_db, "x", source_run_id=advised, hint="hint 0")

    new_id = advise(migrated_db, retry, "a second hint", "mcp", REPOS)

    assert run_row(migrated_db, new_id)["hint"] == "a second hint"


def test_the_second_failed_advised_rerun_is_marked_for_a_claude_session(migrated_db):
    one = _advised_chain(migrated_db, 1)
    two = _advised_chain(migrated_db, MAX_ADVISED)

    assert mark_if_needs_claude(migrated_db, one) is False
    assert mark_if_needs_claude(migrated_db, two) is True
    flags = dict(
        migrated_db.execute(
            "SELECT id::text, needs_claude FROM runs WHERE id IN (%s, %s)", (one, two)
        )
    )
    assert flags == {one: False, two: True}


def test_an_eval_chore_that_opened_a_pull_request_can_be_advised(migrated_db):
    run_id = escalated_chore(migrated_db, "x", source="eval")
    migrated_db.execute("UPDATE runs SET status = 'succeeded' WHERE id = %s", (run_id,))

    new_id = advise(migrated_db, run_id, "Name it divide.", "api", REPOS)

    assert run_row(migrated_db, new_id)["source_run_id"] == run_id


def test_a_succeeded_chore_that_is_not_an_eval_chore_is_still_refused(migrated_db):
    run_id = escalated_chore(migrated_db, "x", source="bank")
    migrated_db.execute("UPDATE runs SET status = 'succeeded' WHERE id = %s", (run_id,))

    with pytest.raises(AdviceRefused, match="escalated"):
        advise(migrated_db, run_id, "a hint", "mcp", REPOS)


@pytest.mark.parametrize("quiet", ["eval", "bank"])
def test_the_rerun_of_a_quiet_chore_keeps_its_source(migrated_db, quiet):
    run_id = escalated_chore(migrated_db, "x", source=quiet)

    new_id = advise(migrated_db, run_id, "a hint", "mcp", REPOS)

    assert run_row(migrated_db, new_id)["source"] == quiet


def test_a_named_provider_runs_the_rerun(migrated_db):
    run_id = escalated_chore(migrated_db, "x")

    new_id = advise(migrated_db, run_id, "a hint", "api", REPOS, provider="ollama")

    assert run_row(migrated_db, new_id)["provider"] == "ollama"


def test_a_rerun_of_a_succeeded_eval_chore_counts_as_advice(migrated_db):
    run_id = escalated_chore(migrated_db, "x", source="eval")
    migrated_db.execute("UPDATE runs SET status = 'succeeded' WHERE id = %s", (run_id,))

    new_id = advise(migrated_db, run_id, "a hint", "api", REPOS)

    assert advised_count(migrated_db, new_id) == 1
