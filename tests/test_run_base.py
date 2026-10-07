"""A repo chore may name the commit it starts from (decision 29 of
docs/build-brief-evals.md). The bank's chores each start from the parent of
a mined commit."""

import pytest
from pydantic import ValidationError

from app.advice import advise
from app.mercury_config import RepoConfig
from app.run_request import RunRequest

SHA = "a" * 40
REPOS = (RepoConfig(name="owner/fixture", test_command="true"),)


def test_a_chore_may_name_a_full_commit_as_its_base():
    run = RunRequest(type="repo_chore", inputs={"task": "x", "repo": "owner/fixture", "base": SHA})

    assert run.inputs["base"] == SHA


@pytest.mark.parametrize("base", ["abc1234", "g" * 40, "A" * 40, 7])
def test_a_base_that_is_not_a_full_lowercase_sha_is_refused(base):
    with pytest.raises(ValidationError):
        RunRequest(type="repo_chore", inputs={"task": "x", "repo": "owner/fixture", "base": base})


def test_only_a_chore_takes_a_base():
    with pytest.raises(ValidationError):
        RunRequest(type="pytest", inputs={"task": "x", "base": SHA})


def test_an_advised_rerun_starts_from_the_same_base(migrated_db):
    run_id = migrated_db.execute(
        "INSERT INTO runs (task, type, repo, status, base_sha) "
        "VALUES ('x', 'repo_chore', 'owner/fixture', 'escalated', %s) RETURNING id::text",
        (SHA,),
    ).fetchone()[0]

    new_id = advise(migrated_db, run_id, "try the other file", "mcp", REPOS)

    base = migrated_db.execute("SELECT base_sha FROM runs WHERE id = %s", (new_id,)).fetchone()
    assert base == (SHA,)


def test_an_advised_rerun_of_a_local_chore_stays_on_local(migrated_db):
    """A rescue measured on gemini would say nothing about the local model
    (decisions 26 and 37)."""
    run_id = migrated_db.execute(
        "INSERT INTO runs (task, type, repo, status, provider) "
        "VALUES ('x', 'repo_chore', 'owner/fixture', 'escalated', 'local') RETURNING id::text"
    ).fetchone()[0]

    new_id = advise(migrated_db, run_id, "try the other file", "mcp", REPOS)

    provider = migrated_db.execute("SELECT provider FROM runs WHERE id = %s", (new_id,)).fetchone()
    assert provider == ("local",)
