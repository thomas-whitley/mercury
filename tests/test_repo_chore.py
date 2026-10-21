"""The repo chore executor, against a local bare repo standing in for GitHub
and a fake of GitHub's pull request API.

It clones, branches as agent/<run id>, lets the model rewrite whole files,
runs the repo's own test command, and on green pushes the branch and opens a
pull request. Three red attempts end the run failed with the diff and the
test output, and nothing is pushed. A branch already on the remote means a
worker got that far before it died, so the chore picks up from there.
"""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from app.advice_text import advice_block
from app.chore_prompts import edit_prompt, read_prompt, shown_files, tree_listing
from app.github import GitHubClient
from app.mercury_config import RepoConfig
from app.model import StubModel
from app.repo_chore import (
    NEEDS_THOMAS,
    OUTAGE,
    OUTSIDE_PATHS,
    RED,
    SYSTEM,
    UNCHANGED,
    UNUSABLE,
    WEAKENED,
    ChoreSetup,
    run_repo_chore,
)
from app.runs import claim_run
from tests.github_fake import FakeGitHub
from tests.test_fallback import _Failing

REPO = "owner/fixture"
WORKER = "worker-1"
TOKEN = "ghp_test_token_never_logged"
# The fixture's own test: it passes today, and fails until subtract exists
# once test_subtract.py is added.
CALC = "def add(a, b):\n    return a + b\n"
TEST_ADD = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
TEST_SUBTRACT = (
    "from calc import subtract\n\n\ndef test_subtract():\n    assert subtract(5, 3) == 2\n"
)
GOOD_CALC = CALC + "\n\ndef subtract(a, b):\n    return a - b\n"
BAD_CALC = CALC + "\n\ndef subtract(a, b):\n    return a + b\n"
TEST_COMMAND = "python -m pytest -q -p no:cacheprovider"


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def remote(tmp_path) -> Path:
    """A bare repo at <tmp>/remotes/owner/fixture.git with calc.py and its test on main."""
    work = tmp_path / "seed"
    work.mkdir()
    git("init", "-q", "-b", "main", cwd=work)
    (work / "calc.py").write_text(CALC)
    (work / "test_calc.py").write_text(TEST_ADD)
    git("add", ".", cwd=work)
    git(
        "-c",
        "user.name=seed",
        "-c",
        "user.email=seed@example.com",
        "commit",
        "-qm",
        "seed",
        cwd=work,
    )
    bare = tmp_path / "remotes" / "owner" / "fixture.git"
    bare.parent.mkdir(parents=True)
    git("clone", "-q", "--bare", str(work), str(bare), cwd=tmp_path)
    return bare


@pytest.fixture
def github():
    server = FakeGitHub()
    yield server
    server.close()


def setup(tmp_path, github, test_command: str = TEST_COMMAND, **changes) -> ChoreSetup:
    return ChoreSetup(
        repo=RepoConfig(name=REPO, test_command=test_command),
        clone_base=f"file://{tmp_path / 'remotes'}",
        github=GitHubClient(TOKEN, github.url),
        token=TOKEN,
        test_timeout_seconds=60,
        **changes,
    )


def chore_run(conn, instruction: str = "Add subtract to calc.py", source: str = "api") -> str:
    run_id = str(
        conn.execute(
            "INSERT INTO runs (task, type, repo, source) VALUES (%s, 'repo_chore', %s, %s) "
            "RETURNING id",
            (instruction, REPO, source),
        ).fetchone()[0]
    )
    assert claim_run(conn, run_id, WORKER)
    return run_id


def pick(*paths: str) -> str:
    return json.dumps({"read": list(paths)})


def edit(**files: str) -> str:
    return json.dumps(
        {"files": {name.replace("__", "."): body for name, body in files.items()}, "summary": "x"}
    )


def change(calc: str) -> str:
    return json.dumps(
        {"files": {"calc.py": calc, "test_subtract.py": TEST_SUBTRACT}, "summary": "Add subtract"}
    )


def remote_branches(bare: Path) -> list[str]:
    return git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=bare).split()


def done(conn, run_id: str) -> dict:
    return conn.execute(
        "SELECT output FROM steps WHERE run_id = %s AND kind = 'done'", (run_id,)
    ).fetchone()[0]


def kinds(conn, run_id: str) -> list[str]:
    rows = conn.execute("SELECT kind FROM steps WHERE run_id = %s ORDER BY seq", (run_id,))
    return [row[0] for row in rows]


def test_a_green_change_is_pushed_to_its_branch_and_opened_as_a_pull_request(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    branch = f"agent/{run_id}"
    assert result.status == "succeeded"
    assert branch in remote_branches(remote)
    assert "def subtract" in git("show", f"{branch}:calc.py", cwd=remote)
    assert git("show", "main:calc.py", cwd=remote) == CALC.strip()
    [pull] = github.pulls
    assert (pull["head"], pull["base"]) == (branch, "main")
    finished = done(migrated_db, run_id)
    assert (finished["status"], finished["pr_url"]) == ("succeeded", pull["html_url"])
    # The diff stays, so an eval chore whose pull request fails its grade can
    # be advised with it (decision 47 of docs/build-brief-evals.md).
    assert "+def subtract" in finished["diff"]
    assert kinds(migrated_db, run_id) == ["clone", "read", "edit", "test", "push", "pr", "done"]
    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert status == ("succeeded",)


def test_the_model_sees_the_tree_then_the_files_it_asked_for(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    first, second = model.prompts
    assert "Add subtract to calc.py" in first
    assert "calc.py" in first and "test_calc.py" in first
    assert "def add" not in first
    assert CALC in second


def test_red_tests_are_shown_to_the_model_and_it_tries_again(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(BAD_CALC), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    retry = model.prompts[2]
    assert "assert 8 == 2" in retry
    assert "return a + b" in retry
    assert kinds(migrated_db, run_id).count("test") == 2


def test_three_red_attempts_escalate_the_run_with_the_diff_and_push_nothing(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(BAD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "escalated"
    assert remote_branches(remote) == ["main"]
    assert github.pulls == []
    output = done(migrated_db, run_id)
    assert output["status"] == "escalated"
    assert output["reason"] == RED
    row = migrated_db.execute("SELECT escalation_reason FROM runs WHERE id = %s", (run_id,))
    assert row.fetchone() == (RED,)
    assert "+def subtract(a, b):" in output["diff"]
    assert "test_subtract.py" in output["diff"]
    assert "assert 8 == 2" in output["test_output"]
    assert kinds(migrated_db, run_id).count("edit") == 3


def test_a_path_outside_the_repo_is_not_written(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    escape = json.dumps({"files": {"../escaped.py": "x = 1\n", ".git/config": ""}, "summary": ""})
    model = StubModel(replies=[pick("calc.py"), escape, change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert not list(tmp_path.rglob("escaped.py"))
    assert "not allowed" in model.prompts[2]


def test_only_the_files_the_model_wrote_are_committed(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])
    litter = f"{TEST_COMMAND} && touch build-output.txt"

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github, litter), worker_id=WORKER)

    files = git("ls-tree", "--name-only", f"agent/{run_id}", cwd=remote).split()
    assert sorted(files) == ["calc.py", "test_calc.py", "test_subtract.py"]


def test_the_test_command_never_sees_a_secret(migrated_db, remote, github, tmp_path, monkeypatch):
    monkeypatch.setenv("MERCURY_GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@db/x")
    seen = tmp_path / "env.txt"
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    run_repo_chore(
        migrated_db,
        run_id,
        model,
        setup(tmp_path, github, f"env > {seen} && {TEST_COMMAND}"),
        worker_id=WORKER,
    )

    env = seen.read_text()
    assert TOKEN not in env
    assert "DATABASE_URL" not in env
    assert "PATH=" in env


def test_the_token_is_sent_to_github_and_never_stored_in_a_step(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert all(header == f"Bearer {TOKEN}" for header in github.authorizations)
    stored = migrated_db.execute(
        "SELECT string_agg(output::text, ' ') FROM steps WHERE run_id = %s", (run_id,)
    ).fetchone()[0]
    assert TOKEN not in stored


def test_a_branch_already_on_the_remote_is_picked_up_without_the_model(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    # A first worker pushed the green branch and died before the pull request.
    work = tmp_path / "first-worker"
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    git("checkout", "-qb", f"agent/{run_id}", cwd=work)
    (work / "calc.py").write_text(GOOD_CALC)
    git("-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qam", "x", cwd=work)
    git("push", "-q", "origin", f"agent/{run_id}", cwd=work)
    model = StubModel(replies=["never read"])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert model.prompts == []
    [pull] = github.pulls
    assert pull["head"] == f"agent/{run_id}"
    clone_step = migrated_db.execute(
        "SELECT output FROM steps WHERE run_id = %s AND kind = 'clone'", (run_id,)
    ).fetchone()[0]
    assert clone_step["resumed"] is True


def test_a_pull_request_already_open_is_not_opened_twice(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])
    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)
    # The worker died after opening it and before closing the run.
    migrated_db.execute(
        "UPDATE runs SET status = 'running', finished_at = NULL WHERE id = %s", (run_id,)
    )

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert len(github.pulls) == 1


def test_a_chore_stops_at_its_token_budget(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(BAD_CALC)], tokens_per_reply=30_000)

    result = run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER, token_budget=50_000
    )

    assert result.status == "budget_exhausted"
    assert remote_branches(remote) == ["main"]
    assert done(migrated_db, run_id)["status"] == "budget_exhausted"


def worker_settings(tmp_path, github, monkeypatch):
    from app.config import load_settings

    monkeypatch.setenv("DATABASE_URL", migrated_url(tmp_path))
    monkeypatch.setenv("WORKER_ID", WORKER)
    monkeypatch.setenv("GITHUB_API_URL", github.url)
    monkeypatch.setenv("GITHUB_CLONE_BASE", f"file://{tmp_path / 'remotes'}")
    monkeypatch.setenv("MERCURY_GITHUB_TOKEN", TOKEN)
    return load_settings()


def migrated_url(tmp_path) -> str:
    return tmp_path.joinpath(".db-url").read_text()


def test_the_worker_runs_a_claimed_chore(
    migrated_db, clean_db, remote, github, tmp_path, monkeypatch
):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    result = process_run(
        migrated_db,
        run_id,
        settings,
        model_builder=lambda settings, provider: model,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
    )

    assert result.status == "succeeded"
    assert len(github.pulls) == 1


def test_the_worker_refuses_a_chore_whose_repo_left_the_config(
    migrated_db, clean_db, remote, github, tmp_path, monkeypatch
):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = chore_run(migrated_db)

    result = process_run(
        migrated_db,
        run_id,
        settings,
        model_builder=lambda settings, provider: StubModel(replies=["{}"]),
        repos=(),
    )

    assert result is None
    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert status == ("refused",)
    assert remote_branches(remote) == ["main"]


# Open it anyway: a failed chore offers a button, and pressing it creates a
# run that reapplies the failed diff and opens the pull request regardless.

CHAT = 42


def failed_chore(conn, remote, github, tmp_path) -> str:
    run_id = chore_run(conn)
    model = StubModel(replies=[pick("calc.py"), change(BAD_CALC)])
    assert (
        run_repo_chore(conn, run_id, model, setup(tmp_path, github), worker_id=WORKER).status
        == "escalated"
    )
    return run_id


def anyway_run(conn, source_run_id: str) -> str:
    run_id = str(
        conn.execute(
            "INSERT INTO runs (task, type, repo, source_run_id) "
            "SELECT task, 'repo_chore', repo, id FROM runs WHERE id = %s RETURNING id",
            (source_run_id,),
        ).fetchone()[0]
    )
    assert claim_run(conn, run_id, WORKER)
    return run_id


def test_open_anyway_pushes_the_failed_diff_and_says_the_tests_failed(
    migrated_db, remote, github, tmp_path
):
    failed = failed_chore(migrated_db, remote, github, tmp_path)
    run_id = anyway_run(migrated_db, failed)
    model = StubModel(replies=["never read"])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert model.prompts == []
    branch = f"agent/{run_id}"
    assert "return a + b" in git("show", f"{branch}:calc.py", cwd=remote)
    assert "test_subtract.py" in git("ls-tree", "--name-only", branch, cwd=remote).split()
    [pull] = github.pulls
    assert pull["head"] == branch
    assert "failed" in pull["body"]
    assert failed in pull["body"]
    assert kinds(migrated_db, run_id) == ["clone", "apply", "push", "pr", "done"]


@pytest.mark.parametrize("source", ["api", "n8n", "mcp", "telegram"])
def test_an_escalated_chore_tells_the_owner_whatever_its_source(
    migrated_db, clean_db, remote, github, fake_telegram, tmp_path, monkeypatch, source
):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = chore_run(migrated_db)
    migrated_db.execute("UPDATE runs SET source = %s WHERE id = %s", (source, run_id))
    model = StubModel(replies=[pick("calc.py"), change(BAD_CALC)])

    process_run(
        migrated_db,
        run_id,
        settings,
        model_builder=lambda settings, provider: model,
        owner_chat_id=CHAT,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
    )

    [message] = fake_telegram.sent()
    assert message["chat_id"] == CHAT
    assert RED in message["text"]
    [[button, _]] = message["reply_markup"]["inline_keyboard"]
    assert button["text"] == "Open it anyway"
    row = migrated_db.execute("SELECT action, run_id FROM approvals").fetchone()
    assert row == ("open_anyway", uuid.UUID(run_id))
    stored = migrated_db.execute(
        "SELECT escalation_message_id FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    # The fake numbers its messages from 1, and this is the only one sent.
    assert stored == (1,)


def test_a_succeeded_chore_offers_nothing(
    migrated_db, clean_db, remote, github, fake_telegram, tmp_path, monkeypatch
):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = chore_run(migrated_db)
    migrated_db.execute(
        "UPDATE runs SET telegram_chat_id = %s, telegram_message_id = 7 WHERE id = %s",
        (CHAT, run_id),
    )
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    process_run(
        migrated_db,
        run_id,
        settings,
        model_builder=lambda settings, provider: model,
        owner_chat_id=CHAT,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
    )

    assert fake_telegram.sent() == []
    assert migrated_db.execute("SELECT count(*) FROM approvals").fetchone() == (0,)


# In the image the worker is root, and a test command running as the worker's
# user could read its keys from /proc/<pid>/environ. So as root the command
# runs as the unprivileged chore user, and with no such user it does not run.


class _FakeProcess:
    returncode = 0
    pid = 1

    def communicate(self, timeout=None):
        return "ok", None


def test_as_root_the_test_command_runs_as_the_chore_user(tmp_path, monkeypatch):
    import pwd

    from app import repo_chore

    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / "calc.py").write_text(CALC)
    chowned, popen_kwargs = [], {}
    monkeypatch.setattr(repo_chore.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        repo_chore.pwd,
        "getpwnam",
        lambda name: pwd.struct_passwd((name, "x", 4321, 4321, "", "/", "/bin/sh")),
    )
    monkeypatch.setattr(
        repo_chore.os, "chown", lambda path, uid, gid, **kwargs: chowned.append((str(path), uid))
    )

    def fake_popen(args, **kwargs):
        popen_kwargs.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(repo_chore.subprocess, "Popen", fake_popen)
    killed = []
    monkeypatch.setattr(
        repo_chore, "kill_user_processes", lambda uid, gid: killed.append((uid, gid))
    )
    chore = setup(tmp_path, github=type("G", (), {"url": "http://unused"})())

    passed, _, _ = repo_chore._run_tests(clone, chore, tmp_path)

    assert passed
    # Whatever the command left running is gone before git runs as root.
    assert killed == [(4321, 4321)]
    assert (popen_kwargs["user"], popen_kwargs["group"]) == (4321, 4321)
    assert popen_kwargs["extra_groups"] == []
    assert (str(clone / "calc.py"), 4321) in chowned
    assert (str(tmp_path / "home"), 4321) in chowned


def test_as_root_a_failed_kill_stops_the_chore_before_git(tmp_path, monkeypatch):
    import pwd

    from app import repo_chore
    from app.sandbox import SandboxError

    clone = tmp_path / "repo"
    clone.mkdir()
    monkeypatch.setattr(repo_chore.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        repo_chore.pwd,
        "getpwnam",
        lambda name: pwd.struct_passwd((name, "x", 4321, 4321, "", "/", "/bin/sh")),
    )
    monkeypatch.setattr(repo_chore.os, "chown", lambda *a, **k: None)
    monkeypatch.setattr(repo_chore.subprocess, "Popen", lambda *a, **k: _FakeProcess())

    def cannot_kill(uid, gid):
        raise SandboxError("the kill helper exited 1")

    monkeypatch.setattr(repo_chore, "kill_user_processes", cannot_kill)
    chore = setup(tmp_path, github=type("G", (), {"url": "http://unused"})())

    with pytest.raises(repo_chore.ChoreError, match="kill helper"):
        repo_chore._run_tests(clone, chore, tmp_path)


def test_as_root_with_no_chore_user_the_tests_do_not_run(tmp_path, monkeypatch):
    from app import repo_chore

    clone = tmp_path / "repo"
    clone.mkdir()

    def no_such_user(name):
        raise KeyError(name)

    monkeypatch.setattr(repo_chore.os, "geteuid", lambda: 0)
    monkeypatch.setattr(repo_chore.pwd, "getpwnam", no_such_user)
    monkeypatch.setattr(repo_chore.subprocess, "Popen", lambda *a, **k: pytest.fail("ran as root"))
    chore = setup(tmp_path, github=type("G", (), {"url": "http://unused"})())

    with pytest.raises(repo_chore.ChoreError, match="chore user"):
        repo_chore._run_tests(clone, chore, tmp_path)


def test_three_unusable_replies_escalate_with_their_own_reason(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), "I would change calc.py like so."])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert remote_branches(remote) == ["main"]


def test_a_model_that_never_answers_ends_in_error_as_an_outage(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)

    result = run_repo_chore(
        migrated_db,
        run_id,
        _Failing(),
        setup(tmp_path, github),
        worker_id=WORKER,
        retry_attempts=1,
        retry_backoff_seconds=0,
    )

    assert result.status == "error"
    assert done(migrated_db, run_id)["reason"] == OUTAGE


REWRITTEN_TEST_CALC = (
    "from calc import subtract\n\n\ndef test_subtract():\n    assert subtract(5, 3) == 2\n"
)


def drop_add(calc: str) -> str:
    """A green change that replaces main's test_add with a test of its own."""
    return json.dumps(
        {"files": {"calc.py": calc, "test_calc.py": REWRITTEN_TEST_CALC}, "summary": "x"}
    )


def test_a_green_change_that_drops_a_test_is_retried_with_the_test_named(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    restored = json.dumps(
        {
            "files": {
                "calc.py": GOOD_CALC,
                "test_calc.py": TEST_ADD,
                "test_subtract.py": TEST_SUBTRACT,
            },
            "summary": "x",
        }
    )
    model = StubModel(replies=[pick("calc.py"), drop_add(GOOD_CALC), restored])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert "removed test_add" in model.prompts[2]
    assert "Keep every existing test" in model.prompts[2]
    # main's own test file, which the first attempt overwrote, is shown back.
    assert TEST_ADD.strip() in model.prompts[2]
    assert kinds(migrated_db, run_id).count("guard") == 1
    branch = f"agent/{run_id}"
    assert "def test_add" in git("show", f"{branch}:test_calc.py", cwd=remote)


def test_three_attempts_that_drop_a_test_escalate_as_weakened_and_push_nothing(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), drop_add(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "escalated"
    output = done(migrated_db, run_id)
    assert output["reason"] == WEAKENED
    assert output["problems"] == ["test_calc.py: removed test_add"]
    assert remote_branches(remote) == ["main"]
    assert github.pulls == []


def test_an_advised_rerun_starts_from_main_with_the_hint_and_the_failed_attempt(
    migrated_db, remote, github, tmp_path
):
    failed = chore_run(migrated_db)
    red = StubModel(replies=[pick("calc.py"), change(BAD_CALC)])
    run_repo_chore(migrated_db, failed, red, setup(tmp_path, github), worker_id=WORKER)
    advised = str(
        migrated_db.execute(
            "INSERT INTO runs (task, type, repo, source_run_id, hint) "
            "VALUES ('Add subtract to calc.py', 'repo_chore', %s, %s, %s) RETURNING id",
            (REPO, failed, "subtract must return a - b, not a + b"),
        ).fetchone()[0]
    )
    assert claim_run(migrated_db, advised, WORKER)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, advised, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert kinds(migrated_db, advised)[:3] == ["clone", "read", "edit"]
    edit_prompt = model.prompts[1]
    assert "The owner's hint: subtract must return a - b, not a + b" in edit_prompt
    assert "+    return a + b" in edit_prompt  # the failed diff
    assert "assert 8 == 2" in edit_prompt  # its test output
    assert "(tests still failing after 3 attempts)" in edit_prompt


def test_a_second_advised_rerun_that_escalates_is_marked_for_a_claude_session(
    migrated_db, clean_db, remote, github, fake_telegram, tmp_path, monkeypatch
):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    settings = worker_settings(tmp_path, github, monkeypatch)
    newest = chore_run(migrated_db)
    migrated_db.execute(
        "UPDATE runs SET status = 'escalated', finished_at = now() WHERE id = %s", (newest,)
    )
    for hint in ("first hint", "second hint"):
        newest = str(
            migrated_db.execute(
                "INSERT INTO runs (task, type, repo, source_run_id, hint, status, finished_at) "
                "VALUES ('Add subtract to calc.py', 'repo_chore', %s, %s, %s, 'escalated', now()) "
                "RETURNING id",
                (REPO, newest, hint),
            ).fetchone()[0]
        )
    # The second advised rerun is the one the worker runs now.
    migrated_db.execute(
        "UPDATE runs SET status = 'pending', finished_at = NULL WHERE id = %s", (newest,)
    )
    assert claim_run(migrated_db, newest, settings.worker_id)
    model = StubModel(replies=[pick("calc.py"), change(BAD_CALC)])

    process_run(
        migrated_db,
        newest,
        settings,
        model_builder=lambda settings, provider: model,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
    )

    row = migrated_db.execute(
        "SELECT status, needs_claude FROM runs WHERE id = %s", (newest,)
    ).fetchone()
    assert row == ("escalated", True)


def _after_the_push(monkeypatch, hook) -> None:
    """Run hook right after the chore's own push returns, before its push step lands."""
    from app import repo_chore

    original = repo_chore._Git.run

    def run(self, *args, **kwargs):
        out = original(self, *args, **kwargs)
        if args[:1] == ("push",) and "--delete" not in args:
            hook()
        return out

    monkeypatch.setattr(repo_chore._Git, "run", run)


def test_a_cancel_between_the_push_and_the_pull_request_deletes_the_branch(
    migrated_db, remote, github, tmp_path, monkeypatch
):
    from app.runs import cancel_run

    run_id = chore_run(migrated_db)
    _after_the_push(monkeypatch, lambda: cancel_run(migrated_db, run_id))
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "lost"
    assert remote_branches(remote) == ["main"]
    assert github.pulls == []


def test_a_takeover_between_the_push_and_the_pull_request_keeps_the_branch(
    migrated_db, remote, github, tmp_path, monkeypatch
):
    run_id = chore_run(migrated_db)
    _after_the_push(
        monkeypatch,
        lambda: migrated_db.execute(
            "UPDATE runs SET claimed_by = 'worker-2' WHERE id = %s", (run_id,)
        ),
    )
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "lost"
    assert f"agent/{run_id}" in remote_branches(remote)


def unchanged() -> str:
    """A green reply that writes calc.py back exactly as main has it."""
    return json.dumps({"files": {"calc.py": CALC}, "summary": "x"})


def test_a_green_attempt_that_changes_nothing_is_retried_with_feedback(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), unchanged(), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert "leaves the repository as it was" in model.prompts[2]


def test_three_attempts_that_change_nothing_escalate_rather_than_error(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), unchanged()])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == UNCHANGED
    assert remote_branches(remote) == ["main"]


def test_the_worker_announces_an_escalation_for_a_run_id_it_claimed_as_a_uuid(
    migrated_db, clean_db, remote, github, fake_telegram, tmp_path, monkeypatch
):
    """claim_next_run hands process_run the id as the database returns it, a
    UUID. The live worker crashed on run_id[:8] with exactly that on 2026-10-07."""
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(BAD_CALC)])

    process_run(
        migrated_db,
        uuid.UUID(run_id),
        settings,
        model_builder=lambda settings, provider: model,
        owner_chat_id=CHAT,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
    )

    [message] = fake_telegram.sent()
    assert f"escalated ({run_id[:8]})" in message["text"]


def test_every_model_call_is_recorded_with_its_prompt_and_reply(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    migrated_db.execute("UPDATE runs SET provider = 'local' WHERE id = %s", (run_id,))
    replies = [pick("calc.py"), change(GOOD_CALC)]

    run_repo_chore(
        migrated_db, run_id, StubModel(replies=replies), setup(tmp_path, github), worker_id=WORKER
    )

    rows = migrated_db.execute(
        "SELECT seq, provider, system, prompt, reply, tokens FROM model_calls "
        "WHERE run_id = %s ORDER BY id",
        (run_id,),
    ).fetchall()
    assert [row[0] for row in rows] == [2, 3]  # the read step, then the first edit
    assert {row[1] for row in rows} == {"local"}
    assert {row[2] for row in rows} == {SYSTEM}
    assert "Instruction:\nAdd subtract to calc.py" in rows[0][3]
    assert "=== calc.py ===" in rows[1][3]
    assert [row[4] for row in rows] == replies
    assert [row[5] for row in rows] == [100, 100]


def test_the_recorded_prompts_are_the_ones_chore_prompts_builds(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    run_repo_chore(
        migrated_db, run_id, StubModel(replies=[pick("calc.py"), change(GOOD_CALC)]),
        setup(tmp_path, github), worker_id=WORKER,
    )  # fmt: skip
    work = tmp_path / "check"
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    listing = tree_listing(git("ls-files", cwd=work).splitlines())

    prompts = [
        row[0]
        for row in migrated_db.execute(
            "SELECT prompt FROM model_calls WHERE run_id = %s ORDER BY seq", (run_id,)
        ).fetchall()
    ]

    assert prompts[0] == read_prompt("Add subtract to calc.py", "", listing)
    assert prompts[1] == edit_prompt(
        "Add subtract to calc.py", "", listing, shown_files(work, ["calc.py"])
    )


def push_commit(remote: Path, tmp_path: Path, name: str, body: str) -> str:
    """Add one commit to the bare remote's main and return its sha."""
    work = tmp_path / f"push-{name}"
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    (work / name).write_text(body)
    git("add", name, cwd=work)
    git(
        "-c", "user.name=seed", "-c", "user.email=seed@example.com", "commit", "-qm", name,
        cwd=work,
    )  # fmt: skip
    git("push", "-q", "origin", "main", cwd=work)
    return git("rev-parse", "HEAD", cwd=work)


def test_a_chore_with_a_base_starts_from_that_commit(migrated_db, remote, github, tmp_path):
    base = git("rev-parse", "main", cwd=remote)
    push_commit(remote, tmp_path, "later.py", "X = 1\n")
    run_id = chore_run(migrated_db)
    migrated_db.execute("UPDATE runs SET base_sha = %s WHERE id = %s", (base, run_id))
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert "later.py" not in model.prompts[0]
    assert git("rev-parse", f"agent/{run_id}~1", cwd=remote) == base


def test_a_base_that_is_not_in_the_repo_ends_the_chore_in_error(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    migrated_db.execute("UPDATE runs SET base_sha = %s WHERE id = %s", ("0" * 40, run_id))

    result = run_repo_chore(
        migrated_db, run_id, StubModel(replies=[pick("calc.py")]), setup(tmp_path, github),
        worker_id=WORKER,
    )  # fmt: skip

    assert result.status == "error"
    assert "git checkout failed" in done(migrated_db, run_id)["reason"]
    assert TOKEN not in json.dumps(done(migrated_db, run_id))


def test_a_nul_byte_in_a_reply_is_recorded_without_it_and_the_chore_carries_on(
    migrated_db, remote, github, tmp_path
):
    """Postgres text cannot hold NUL, and recording a call must never end a chore."""
    run_id = chore_run(migrated_db)
    replies = [pick("calc.py") + "\x00", change(GOOD_CALC)]

    result = run_repo_chore(
        migrated_db, run_id, StubModel(replies=replies), setup(tmp_path, github), worker_id=WORKER
    )

    assert result.status == "succeeded"
    first = migrated_db.execute(
        "SELECT reply FROM model_calls WHERE run_id = %s ORDER BY id LIMIT 1", (run_id,)
    ).fetchone()[0]
    assert first == pick("calc.py")


def test_advice_after_a_wrong_pull_request_says_so_and_shows_its_diff():
    block = advice_block("Name it divide.", {"status": "succeeded", "diff": "+def div"})

    assert "opened a pull request" in block
    assert "+def div" in block
    assert "test output" not in block


PAGES = ("src/pages/",)
ABOUT = "<h1>About us</h1>\n"


def write_to(path: str, body: str) -> str:
    return json.dumps({"files": {path: body}, "summary": "x"})


def new_file(path: str, body: str, summary: str = "x") -> str:
    """A note chore's reply that creates a file."""
    return json.dumps({"edits": [{"path": path, "find": "", "replace": body}], "summary": summary})


def note_change(calc: str) -> str:
    """A note chore's reply that does what change() does for an ordinary one."""
    return json.dumps(
        {
            "edits": [
                {"path": "calc.py", "find": CALC, "replace": calc},
                {"path": "test_subtract.py", "find": "", "replace": TEST_SUBTRACT},
            ],
            "summary": "Add subtract",
        }
    )


def change_for(source: str, calc: str) -> str:
    return note_change(calc) if source == "review_note" else change(calc)


def note_chore(conn, instruction: str = "A reviewer left a note.") -> str:
    return chore_run(conn, instruction, source="review_note")


def test_a_note_chore_outside_its_paths_is_refused_and_escalates(
    migrated_db, remote, github, tmp_path
):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), new_file("package.json", "{}")])

    result = run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER
    )

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS
    assert OUTSIDE_PATHS == "changes outside the paths a note may touch"
    assert remote_branches(remote) == ["main"]
    assert github.pulls == []
    # The first prompt is the read, the second the first edit. The retries name the path.
    assert "package.json" not in model.prompts[1]
    assert "package.json" in model.prompts[2]
    assert "package.json" in model.prompts[3]
    assert kinds(migrated_db, run_id).count("test") == 0
    assert kinds(migrated_db, run_id).count("edit") == 3


@pytest.mark.parametrize(
    "path", ["src/pages", "src/pagesx/a.astro", "src/other/a.astro", "SRC/pages/a.astro"]
)
def test_a_path_needs_an_entry_that_ends_in_a_slash_or_an_exact_match(
    migrated_db, remote, github, tmp_path, path
):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), new_file(path, "x")])

    run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER
    )

    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS
    assert github.pulls == []


def test_an_entry_without_a_slash_allows_just_that_file(migrated_db, remote, github, tmp_path):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), new_file("src/site.config.ts", "x = 1\n")])
    config = setup(tmp_path, github, allowed_paths=("src/site.config.ts",))

    result = run_repo_chore(migrated_db, run_id, model, config, worker_id=WORKER)

    assert result.status == "succeeded"


def test_one_refused_attempt_then_an_allowed_one_opens_the_pull_request(
    migrated_db, remote, github, tmp_path
):
    run_id = note_chore(migrated_db)
    model = StubModel(
        replies=[
            pick("calc.py"),
            new_file("package.json", "{}"),
            new_file("src/pages/about.astro", ABOUT),
        ]
    )

    result = run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER
    )

    assert result.status == "succeeded"
    assert len(github.pulls) == 1


def test_a_note_chore_inside_its_paths_opens_its_pull_request(
    migrated_db, remote, github, tmp_path
):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), new_file("src/pages/about.astro", ABOUT)])

    result = run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER
    )

    assert result.status == "succeeded"
    pushed = git("ls-tree", "-r", "--name-only", f"agent/{run_id}", cwd=remote)
    assert "src/pages/about.astro" in pushed.split()
    assert len(github.pulls) == 1


def test_a_chore_without_allowed_paths_keeps_todays_rules(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), edit(package__json="{}")])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"


def test_a_question_ends_the_chore_with_no_push(migrated_db, remote, github, tmp_path):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), json.dumps({"question": "Which number?"})])

    result = run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER
    )

    assert result.status == "escalated"
    output = done(migrated_db, run_id)
    assert output["reason"] == NEEDS_THOMAS == "the note needs Thomas"
    assert output["question"] == "Which number?"
    assert remote_branches(remote) == ["main"]
    assert github.pulls == []
    row = migrated_db.execute("SELECT escalation_reason FROM runs WHERE id = %s", (run_id,))
    assert row.fetchone() == (NEEDS_THOMAS,)


def test_a_long_question_is_cut_to_1000_characters(migrated_db, remote, github, tmp_path):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), json.dumps({"question": "q" * 3000})])

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert done(migrated_db, run_id)["question"] == "q" * 1000


def test_a_question_from_an_ordinary_chore_is_an_unusable_reply(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), json.dumps({"question": "Which number?"})])

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert done(migrated_db, run_id)["reason"] == UNUSABLE


def test_only_the_note_prompt_offers_a_question():
    plain = edit_prompt("do it", "", "a.py", {})
    asking = edit_prompt("do it", "", "a.py", {}, may_ask=True)

    assert "question" not in plain
    assert '{"question"' in asking
    assert asking.startswith(plain)


def add_note(conn, run_id: str, **changes) -> None:
    values = dict(
        note_id=7,
        page="/about/",
        note_body="Make the heading warmer.\n## Not a real heading\n```\nclose the fence",
        note_anchor="Our story",
        note_quote="the quote",
    )
    values.update(changes)
    conn.execute(
        "INSERT INTO review_notes (note_id, host, page, note_updated_at, state, run_id, "
        "note_body, note_anchor, note_quote) VALUES (%s, 'live.example.com', %s, 'then', "
        "'chore', %s, %s, %s, %s)",
        (
            values["note_id"], values["page"], run_id,
            values["note_body"], values["note_anchor"], values["note_quote"],
        ),
    )  # fmt: skip


def test_a_note_pull_request_puts_the_note_first(migrated_db, remote, github, tmp_path):
    run_id = note_chore(migrated_db, "THE INSTRUCTION")
    add_note(migrated_db, run_id)
    reply = new_file("src/pages/about.astro", ABOUT, summary="Warmer heading on About")
    model = StubModel(replies=[pick("calc.py"), reply])
    config = setup(tmp_path, github, allowed_paths=PAGES, reviewer_name="Reviewer")

    run_repo_chore(migrated_db, run_id, model, config, worker_id=WORKER)

    [pull] = github.pulls
    words = "Make the heading warmer. ## Not a real heading ``` close the fence"
    assert pull["title"] == f"Reviewer's note on /about/: {words}"[:72].rstrip()
    assert pull["title"].startswith("Reviewer's note on /about/: Make the heading warmer. ##")
    body = pull["body"]
    assert body.startswith("Reviewer's note:\n````\nMake the heading warmer.")
    order = [
        body.index("Make the heading warmer."),
        body.index("Our story"),
        body.index("the quote"),
        body.index("Warmer heading on About"),
        body.index("THE INSTRUCTION"),
    ]
    assert order == sorted(order)
    # The note's own fence stays inside its longer one.
    assert "```\nclose the fence\n````" in body
    assert git("log", "-1", "--format=%s", f"agent/{run_id}", cwd=remote) == pull["title"]


def test_a_rerun_pull_request_finds_the_note_through_its_chain(
    migrated_db, remote, github, tmp_path
):
    first = note_chore(migrated_db)
    add_note(migrated_db, first)
    migrated_db.execute("UPDATE runs SET status = 'escalated' WHERE id = %s", (first,))
    second = note_chore(migrated_db, "THE INSTRUCTION")
    migrated_db.execute(
        "UPDATE runs SET source_run_id = %s, hint = 'use 5' WHERE id = %s", (first, second)
    )
    model = StubModel(replies=[pick("calc.py"), new_file("src/pages/about.astro", ABOUT)])
    config = setup(tmp_path, github, allowed_paths=PAGES, reviewer_name="Reviewer")

    run_repo_chore(migrated_db, second, model, config, worker_id=WORKER)

    [pull] = github.pulls
    assert pull["title"].startswith("Reviewer's note on /about/: ")
    assert pull["body"].startswith("Reviewer's note:")


def test_a_note_chore_with_no_note_row_keeps_the_ordinary_layout(
    migrated_db, remote, github, tmp_path
):
    run_id = note_chore(migrated_db, "Add subtract to calc.py")
    model = StubModel(replies=[pick("calc.py"), note_change(GOOD_CALC)])

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    [pull] = github.pulls
    assert pull["title"] == "Add subtract to calc.py"


def test_an_ordinary_pull_request_keeps_its_layout(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    [pull] = github.pulls
    assert pull["title"] == "Add subtract to calc.py"
    assert pull["body"].startswith("Add subtract to calc.py\n\nOpened by Mercury run")


def test_the_note_never_reaches_a_log_line(migrated_db, remote, github, tmp_path, caplog):
    run_id = note_chore(migrated_db)
    add_note(migrated_db, run_id, note_body="SECRET WORDS")
    reply = new_file("src/pages/about.astro", ABOUT)
    model = StubModel(replies=[pick("calc.py"), reply])
    config = setup(tmp_path, github, allowed_paths=PAGES, reviewer_name="Reviewer")

    with caplog.at_level("DEBUG"):
        run_repo_chore(migrated_db, run_id, model, config, worker_id=WORKER)

    assert "SECRET WORDS" not in caplog.text


def notes_config(**changes):
    from app.mercury_config import ReviewNotesConfig

    values = dict(
        enabled=True,
        repo=REPO,
        reviewer_name="Reviewer",
        live_hosts=("live.example.com",),
        preview_pattern="https://{alias}.example.workers.dev",
        account_id="a",
        database_id="d",
        allowed_paths=PAGES,
        shared_paths=(),
        sensitive_files=(),
    )
    values.update(changes)
    return ReviewNotesConfig(**values)


def process_note(migrated_db, clean_db, github, tmp_path, monkeypatch, model, **kwargs):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = note_chore(migrated_db)
    result = process_run(
        migrated_db,
        run_id,
        settings,
        model_builder=lambda settings, provider: model,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
        **kwargs,
    )
    return run_id, result


def test_the_worker_gives_a_note_chore_the_configured_paths(
    migrated_db, clean_db, remote, github, tmp_path, monkeypatch
):
    model = StubModel(replies=[pick("calc.py"), new_file("package.json", "{}")])

    run_id, result = process_note(
        migrated_db, clean_db, github, tmp_path, monkeypatch, model, review_notes=notes_config()
    )

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS


def test_the_worker_lets_a_note_chore_with_no_config_write_nothing(
    migrated_db, clean_db, remote, github, tmp_path, monkeypatch
):
    model = StubModel(replies=[pick("calc.py"), new_file("src/pages/about.astro", ABOUT)])

    run_id, result = process_note(migrated_db, clean_db, github, tmp_path, monkeypatch, model)

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS


def test_the_worker_names_the_reviewer_in_the_pull_request(
    migrated_db, clean_db, remote, github, tmp_path, monkeypatch
):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = note_chore(migrated_db)
    add_note(migrated_db, run_id)
    model = StubModel(replies=[pick("calc.py"), new_file("src/pages/about.astro", ABOUT)])

    process_run(
        migrated_db,
        run_id,
        settings,
        model_builder=lambda settings, provider: model,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
        review_notes=notes_config(reviewer_name="Pat"),
    )

    assert github.pulls[0]["title"].startswith("Pat's note on /about/: ")


def test_an_ordinary_chore_is_not_given_the_note_paths(
    migrated_db, clean_db, remote, github, tmp_path, monkeypatch
):
    from app.worker import process_run

    tmp_path.joinpath(".db-url").write_text(clean_db)
    settings = worker_settings(tmp_path, github, monkeypatch)
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), edit(package__json="{}")])

    result = process_run(
        migrated_db,
        run_id,
        settings,
        model_builder=lambda settings, provider: model,
        repos=(RepoConfig(name=REPO, test_command=TEST_COMMAND),),
        review_notes=notes_config(),
    )

    assert result.status == "succeeded"


@pytest.mark.parametrize(
    "path",
    [
        "src/pages/../../package.json",
        "src/pages/./x.astro",
        "/etc/passwd",
        "src\\pages\\x.astro",
        "src/pages//x.astro",
    ],
)
def test_a_path_that_only_looks_like_it_is_under_an_allowed_folder_is_outside(path):
    from app.repo_chore import _outside_paths

    assert _outside_paths({path: "x"}, PAGES) == [path]


def test_an_honest_path_under_an_allowed_folder_is_not_outside():
    from app.repo_chore import _outside_paths

    assert _outside_paths({"src/pages/a/b.astro": "x"}, PAGES) == []


def link_into_remote(remote, tmp_path, name: str, target: str) -> None:
    work = tmp_path / "linker"
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    (work / "src" / "pages").mkdir(parents=True)
    (work / "src" / "pages" / name).symlink_to(target)
    git("add", ".", cwd=work)
    git(
        "-c", "user.name=seed", "-c", "user.email=seed@example.com",
        "commit", "-qm", "link", cwd=work,
    )  # fmt: skip
    git("push", "-q", "origin", "main", cwd=work)


@pytest.mark.parametrize(
    "target, written",
    [
        ("../..", "src/pages/link/escape.txt"),
        ("../../..", "src/pages/link/escape.txt"),
        ("../../../escape.txt", "src/pages/link"),
    ],
)
def test_a_write_through_a_symlink_out_of_the_allowed_folder_is_refused(
    migrated_db, remote, github, tmp_path, monkeypatch, target, written
):
    import pathlib

    link_into_remote(remote, tmp_path, "link", target)
    run_id = note_chore(migrated_db)
    reply = new_file(written, "pwned")
    model = StubModel(replies=[pick("calc.py"), reply])
    writes = []
    real = pathlib.Path.write_text
    monkeypatch.setattr(
        pathlib.Path,
        "write_text",
        lambda self, *a, **k: (writes.append(str(self)), real(self, *a, **k))[1],
    )

    result = run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER
    )

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS
    assert remote_branches(remote) == ["main"]
    assert not [w for w in writes if w.endswith(("escape.txt", "/link"))]


def test_a_note_chore_retry_prompts_keep_the_question_option_and_the_paths(
    migrated_db, remote, github, tmp_path
):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), note_change(BAD_CALC)])

    allowed = ("calc.py", "test_subtract.py")

    run_repo_chore(
        migrated_db, run_id, model, setup(tmp_path, github, allowed_paths=allowed), worker_id=WORKER
    )

    edits = model.prompts[1:]
    assert len(edits) == 3
    assert "tests still failing" not in edits[0]
    assert "failed" in edits[1] and "failed" in edits[2]
    for prompt in edits:
        assert '{"question"' in prompt
        assert "test_subtract.py" in prompt


# The test command runs code the model wrote, as the chore user, and git then
# commits and pushes as root. Each trick below is something that code can try
# against that git. None may change what is committed, where it is pushed, or
# run anything as root.
PACKAGE = '{"name": "fixture"}\n'
HOOKS = (
    "mkdir -p .git/hooks && for h in pre-commit pre-push; do "
    "printf '#!/bin/sh\ntouch {marker}-%s\n' $h > .git/hooks/$h && chmod +x .git/hooks/$h; "
    "done"
)
TRICKS = {
    "hooks": HOOKS,
    "insteadof": "git config url.{evil}/.insteadOf {real}/",
    "swap": (
        "mv .git .git-moved && git init -q && git remote add origin {evil}/owner/fixture.git && "
        + HOOKS
    ),
    "tamper": (
        "printf '{{\"name\": \"pwned\"}}\n' > package.json && printf '# tampered\n' >> calc.py "
        "&& git add package.json calc.py"
    ),
    "background": "{{ (sleep 1; touch {marker}-background) > /dev/null 2>&1 & }}",
}
TRICKS["all"] = " && ".join(
    TRICKS[name] for name in ("hooks", "insteadof", "tamper", "background", "swap")
)


@pytest.mark.parametrize("source", ["api", "review_note"])
@pytest.mark.parametrize("trick", sorted(TRICKS))
def test_what_the_test_command_does_to_git_never_reaches_the_commit_or_the_push(
    migrated_db, remote, github, tmp_path, source, trick
):
    import time

    push_commit(remote, tmp_path, "package.json", PACKAGE)
    evil = tmp_path / "evil"
    (evil / "owner").mkdir(parents=True)
    git("clone", "-q", "--bare", str(remote), str(evil / "owner" / "fixture.git"), cwd=tmp_path)
    marker = tmp_path / "marker"
    command = TRICKS[trick].format(
        marker=marker, evil=f"file://{evil}", real=f"file://{tmp_path / 'remotes'}"
    )
    run_id = chore_run(migrated_db, source=source)
    model = StubModel(replies=[pick("calc.py"), change_for(source, GOOD_CALC)])
    allowed = ("calc.py", "test_subtract.py") if source == "review_note" else None
    config = setup(tmp_path, github, f"{command} && {TEST_COMMAND}", allowed_paths=allowed)

    result = run_repo_chore(migrated_db, run_id, model, config, worker_id=WORKER)
    time.sleep(1.5)  # long enough for a process the test command left behind to act

    branch = f"agent/{run_id}"
    assert result.status == "succeeded"
    assert sorted(path.name for path in tmp_path.glob("marker*")) == []
    assert branch in remote_branches(remote)
    assert remote_branches(evil / "owner" / "fixture.git") == ["main"]
    changed = git("diff", "--name-only", "main", branch, cwd=remote).split()
    assert changed == ["calc.py", "test_subtract.py"]
    assert git("show", f"{branch}:calc.py", cwd=remote) == GOOD_CALC.strip()
    assert git("show", f"{branch}:package.json", cwd=remote) == PACKAGE.strip()
    assert git("rev-parse", f"{branch}~1", cwd=remote) == git("rev-parse", "main", cwd=remote)


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root and a chore user, as in the image")
@pytest.mark.parametrize("source", ["api", "review_note"])
def test_as_root_the_chore_user_cannot_reach_roots_git_or_outlive_its_tests(
    migrated_db, remote, github, tmp_path, source
):
    """Only meaningful as root in the image's layout, where the test command
    really runs as another user. It goes for the worker's own git dir and
    work tree by name, and leaves a process in a session of its own."""
    import tempfile
    import time

    shared = Path(tempfile.mkdtemp())
    shared.chmod(0o777)
    marker = shared / "marker"
    evil = tmp_path / "evil"
    (evil / "owner").mkdir(parents=True)
    git("clone", "-q", "--bare", str(remote), str(evil / "owner" / "fixture.git"), cwd=tmp_path)
    attack = (
        'test "$(id -u)" != 0 && test -d ../root && ! ls ../root > /dev/null 2>&1 && '
        "{ mkdir -p ../root/git/hooks; "
        f"printf '#!/bin/sh\ntouch {marker}-hook\n' > ../root/git/hooks/pre-commit; "
        f"git --git-dir=../root/git config url.file://{evil}/.insteadOf "
        f"file://{tmp_path / 'remotes'}/; "
        f"printf 'pwned\n' > ../root/repo/calc.py; true; }} 2> /dev/null && "
        f"{{ setsid sh -c 'sleep 1; touch {marker}-setsid' > /dev/null 2>&1 < /dev/null & }}"
    )
    run_id = chore_run(migrated_db, source=source)
    model = StubModel(replies=[pick("calc.py"), change_for(source, GOOD_CALC)])
    allowed = ("calc.py", "test_subtract.py") if source == "review_note" else None
    config = setup(tmp_path, github, f"{attack} && {TEST_COMMAND}", allowed_paths=allowed)

    result = run_repo_chore(migrated_db, run_id, model, config, worker_id=WORKER)
    time.sleep(2)

    branch = f"agent/{run_id}"
    assert result.status == "succeeded"
    assert sorted(path.name for path in shared.iterdir()) == []
    assert branch in remote_branches(remote)
    assert remote_branches(evil / "owner" / "fixture.git") == ["main"]
    assert git("show", f"{branch}:calc.py", cwd=remote) == GOOD_CALC.strip()


def test_an_advised_rerun_of_a_question_shows_the_question_it_answers(
    migrated_db, remote, github, tmp_path
):
    asked = note_chore(migrated_db)
    question = "Which heading, the page title or the ``` banner?"
    run_repo_chore(
        migrated_db, asked,
        StubModel(replies=[pick("calc.py"), json.dumps({"question": question})]),
        setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER,
    )  # fmt: skip
    assert done(migrated_db, asked)["reason"] == NEEDS_THOMAS
    advised = str(
        migrated_db.execute(
            "INSERT INTO runs (task, type, repo, source, source_run_id, hint) "
            "VALUES ('A reviewer left a note.', 'repo_chore', %s, 'review_note', %s, %s) "
            "RETURNING id",
            (REPO, asked, "The page title."),
        ).fetchone()[0]
    )
    assert claim_run(migrated_db, advised, WORKER)
    model = StubModel(replies=[pick("calc.py"), new_file("src/pages/about.astro", ABOUT)])

    run_repo_chore(
        migrated_db, advised, model, setup(tmp_path, github, allowed_paths=PAGES), worker_id=WORKER
    )

    for prompt in model.prompts[:2]:
        assert f"````\n{question}\n````" in prompt  # fenced, and the fence outlasts its backticks
        assert "The owner's hint: The page title." in prompt
        assert "answered it with the hint" in prompt


def test_a_long_question_is_capped_in_the_advice():
    from app.advice_text import MAX_QUESTION_CHARS

    block = advice_block("Yes.", {"status": "escalated", "question": "q" * 5_000})

    assert "q" * MAX_QUESTION_CHARS in block
    assert "q" * (MAX_QUESTION_CHARS + 1) not in block


# Note chores edit by search and replace. Untouched text cannot change, because
# the model never types a whole file out again.
DASH = "—"
EN_DASH = "–"
ABOUT_PATH = "src/pages/about.astro"
TRIAL_ABOUT = f"<h1>Our tidy work</h1>\r\n<p>A {DASH} B</p>\n<p>C {DASH} D</p>\n<p>E {DASH} F</p>\n"


def edits_reply(*items: tuple[str, str, str], summary: str = "x") -> str:
    return json.dumps(
        {
            "edits": [{"path": p, "find": f, "replace": r} for p, f, r in items],
            "summary": summary,
        }
    )


def push_bytes(remote: Path, tmp_path: Path, path: str, body: bytes) -> None:
    work = tmp_path / "push-bytes"
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    target = work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    git("add", path, cwd=work)
    git(
        "-c", "user.name=seed", "-c", "user.email=seed@example.com", "commit", "-qm", "page",
        cwd=work,
    )  # fmt: skip
    git("push", "-q", "origin", "main", cwd=work)


def pushed_bytes(remote: Path, run_id: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "-p", f"agent/{run_id}:{path}"],
        cwd=remote, check=True, capture_output=True,
    ).stdout  # fmt: skip


def run_note(migrated_db, github, tmp_path, replies, *, allowed=PAGES):
    run_id = note_chore(migrated_db)
    model = StubModel(replies=replies)
    config = setup(tmp_path, github, allowed_paths=allowed)
    result = run_repo_chore(migrated_db, run_id, model, config, worker_id=WORKER)
    return run_id, model, result


def last_reply_problem(prompt: str) -> str:
    return prompt.split("Your last reply could not be used.")[-1]


def test_a_one_word_edit_leaves_every_other_byte_of_the_file_as_it_was(
    migrated_db, remote, github, tmp_path
):
    push_bytes(remote, tmp_path, ABOUT_PATH, TRIAL_ABOUT.encode())
    reply = edits_reply((ABOUT_PATH, "tidy work", "neat work"))

    run_id, model, result = run_note(migrated_db, github, tmp_path, [pick(ABOUT_PATH), reply])

    assert result.status == "succeeded"
    pushed = pushed_bytes(remote, run_id, ABOUT_PATH)
    assert pushed == TRIAL_ABOUT.replace("tidy work", "neat work").encode()
    assert pushed.count(DASH.encode()) == 3
    assert EN_DASH.encode() not in pushed
    assert b"\r\n" in pushed
    # The model is shown the CRLF as it is, so a find can be copied exactly.
    assert "\r\n" in model.prompts[1]


@pytest.mark.parametrize("find, said", [("no such text", "not found"), ("<p>", "found 3 times")])
def test_a_find_that_is_missing_or_ambiguous_writes_nothing_and_is_named_in_the_retry(
    migrated_db, remote, github, tmp_path, find, said
):
    push_bytes(remote, tmp_path, ABOUT_PATH, TRIAL_ABOUT.encode())
    # The first edit is fine. The reply is refused whole, so it is not applied.
    reply = edits_reply((ABOUT_PATH, "<h1>", "<h2>"), (ABOUT_PATH, find, "x"))

    run_id, model, result = run_note(
        migrated_db, github, tmp_path, [pick(ABOUT_PATH), reply, reply, reply]
    )

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert remote_branches(remote) == ["main"]
    assert kinds(migrated_db, run_id).count("test") == 0
    assert "Your last reply could not be used" not in model.prompts[1]
    for retry in model.prompts[2:]:
        problem = last_reply_problem(retry)
        assert ABOUT_PATH in problem
        assert said in problem
        assert "longer" in problem
        assert "<h2>" not in retry


def test_two_edits_to_one_file_apply_in_order_and_the_second_may_match_the_first(
    migrated_db, remote, github, tmp_path
):
    push_bytes(remote, tmp_path, ABOUT_PATH, TRIAL_ABOUT.encode())
    reply = edits_reply(
        (ABOUT_PATH, "Our tidy work", "Our neat work"),
        (ABOUT_PATH, "neat work</h1>", "neat work, done</h1>"),
    )

    run_id, _, result = run_note(migrated_db, github, tmp_path, [pick(ABOUT_PATH), reply])

    assert result.status == "succeeded"
    pushed = pushed_bytes(remote, run_id, ABOUT_PATH)
    assert pushed == TRIAL_ABOUT.replace("Our tidy work", "Our neat work, done").encode()


def test_an_empty_find_creates_a_file_that_does_not_exist_yet(
    migrated_db, remote, github, tmp_path
):
    reply = edits_reply(("src/pages/new.astro", "", ABOUT))

    run_id, _, result = run_note(migrated_db, github, tmp_path, [pick("calc.py"), reply])

    assert result.status == "succeeded"
    assert pushed_bytes(remote, run_id, "src/pages/new.astro") == ABOUT.encode()


def test_an_empty_find_on_a_file_that_exists_is_unusable(migrated_db, remote, github, tmp_path):
    push_bytes(remote, tmp_path, ABOUT_PATH, TRIAL_ABOUT.encode())
    reply = edits_reply((ABOUT_PATH, "", "wiped"))

    run_id, model, _ = run_note(
        migrated_db, github, tmp_path, [pick(ABOUT_PATH), reply, reply, reply]
    )

    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert remote_branches(remote) == ["main"]
    assert ABOUT_PATH in last_reply_problem(model.prompts[2])


def test_a_file_written_by_an_earlier_attempt_is_the_text_the_next_edit_matches(
    migrated_db, remote, github, tmp_path
):
    first = edits_reply(("calc.py", CALC, BAD_CALC), ("test_subtract.py", "", TEST_SUBTRACT))
    # BAD_CALC holds "return a + b" twice, so the second edit names the def line.
    second = edits_reply(
        (
            "calc.py",
            "def subtract(a, b):\n    return a + b",
            "def subtract(a, b):\n    return a - b",
        )
    )

    run_id, _, result = run_note(
        migrated_db, github, tmp_path, [pick("calc.py"), first, second],
        allowed=("calc.py", "test_subtract.py"),
    )  # fmt: skip

    assert result.status == "succeeded"
    assert pushed_bytes(remote, run_id, "calc.py") == GOOD_CALC.encode()


def test_an_edit_outside_the_allowed_paths_is_refused_as_before(
    migrated_db, remote, github, tmp_path
):
    reply = edits_reply(("package.json", "", "{}"))

    run_id, model, result = run_note(migrated_db, github, tmp_path, [pick("calc.py"), reply])

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS
    assert "package.json" in model.prompts[2]
    assert remote_branches(remote) == ["main"]


def test_an_edit_through_a_symlink_out_of_the_allowed_folder_is_refused(
    migrated_db, remote, github, tmp_path
):
    link_into_remote(remote, tmp_path, "link", "../..")
    reply = edits_reply(("src/pages/link/calc.py", "def add", "def plus"))

    run_id, _, result = run_note(migrated_db, github, tmp_path, [pick("calc.py"), reply])

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS
    assert remote_branches(remote) == ["main"]


def test_a_note_chore_that_replies_with_files_gets_an_unusable_reply(
    migrated_db, remote, github, tmp_path
):
    replies = [pick("calc.py")] + [write_to("src/pages/a.astro", ABOUT)] * 3

    run_id, model, _ = run_note(migrated_db, github, tmp_path, replies)

    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert remote_branches(remote) == ["main"]
    assert "Your last reply could not be used" in model.prompts[2]


def one_edit(**changes) -> dict:
    return {"path": "src/pages/a.astro", "find": "", "replace": "x", **changes}


@pytest.mark.parametrize(
    "reply",
    [
        {"edits": "tidy"},
        {"edits": []},
        {"edits": {"path": "src/pages/a.astro"}},
        {"edits": [one_edit(replace=5)]},
        {"edits": [one_edit(find=None)]},
        {"edits": [one_edit(path=7)]},
        {"edits": [{"path": "src/pages/a.astro", "replace": "x"}]},
        {"edits": [{"path": "src/pages/a.astro", "find": ""}]},
        {"edits": ["src/pages/a.astro"]},
        {"edits": [one_edit(path=f"src/pages/a{i}.astro") for i in range(21)]},
        {"edits": [one_edit(replace="x" * 20_001)]},
        {"edits": [one_edit(path=ABOUT_PATH, find="y" * 20_001)]},
    ],
)
def test_a_malformed_or_oversized_edits_reply_is_unusable(
    migrated_db, remote, github, tmp_path, reply
):
    replies = [pick("calc.py")] + [json.dumps(reply)] * 3

    run_id, _, _ = run_note(migrated_db, github, tmp_path, replies)

    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert remote_branches(remote) == ["main"]


def test_twenty_edits_and_20000_characters_are_within_the_limits(
    migrated_db, remote, github, tmp_path
):
    items = [(f"src/pages/a{i}.astro", "", "x" * 1000) for i in range(19)]
    items.append(("src/pages/big.astro", "", "y" * 20_000))

    _, _, result = run_note(migrated_db, github, tmp_path, [pick("calc.py"), edits_reply(*items)])

    assert result.status == "succeeded"


def test_an_ordinary_chore_still_asks_for_files_and_its_prompt_is_unchanged():
    plain = edit_prompt("do it", "", "a.py", {"a.py": "x = 1\n"})

    assert plain == (
        "Instruction:\ndo it\n\nFiles in the repository:\na.py\n\n"
        "Contents:\n=== a.py ===\nx = 1\n\n\n"
        'Reply {"files": {"path": "the full new contents"}, "summary": "one line"}, '
        "including only files you change or create."
    )


def test_an_ordinary_chore_replying_with_edits_is_unusable(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    reply = edits_reply(("calc.py", CALC, GOOD_CALC))
    model = StubModel(replies=[pick("calc.py")] + [reply] * 3)

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert '"edits"' not in model.prompts[1]


def test_the_edit_prompt_for_a_note_asks_for_edits_and_says_how_to_write_them():
    prompt = edit_prompt("do it", "", "a.py", {"a.py": "x"}, may_ask=True, by_edits=True)

    assert '{"edits": [{"path"' in prompt
    assert '"find"' in prompt and '"replace"' in prompt
    assert '"files"' not in prompt
    assert "exactly" in prompt and "occur once" in prompt
    assert "in order" in prompt
    assert "stays as it is" in prompt
    assert '{"question"' in prompt


def test_every_prompt_of_a_note_chore_asks_for_edits_and_none_for_files(
    migrated_db, remote, github, tmp_path
):
    unchanged = edits_reply(("calc.py", "def add", "def add"))
    weakening = edits_reply(("test_calc.py", "def test_add", "def test_plus"))
    fumbled = edits_reply(("calc.py", "no such text", "x"))
    red = edits_reply(("calc.py", CALC, BAD_CALC), ("test_subtract.py", "", TEST_SUBTRACT))
    red_again = edits_reply(
        (
            "calc.py",
            "def subtract(a, b):\n    return a + b",
            "def subtract(a, b):\n    return a + 0",
        )
    )
    allowed = ("calc.py", "test_calc.py", "test_subtract.py")
    runs = [
        [pick("calc.py"), fumbled, red, red_again],
        [pick("calc.py"), unchanged, unchanged, unchanged],
        [pick("test_calc.py"), weakening, weakening, weakening],
    ]

    prompts = []
    for replies in runs:
        _, model, _ = run_note(migrated_db, github, tmp_path, replies, allowed=allowed)
        prompts += model.prompts[1:]

    assert len(prompts) == 9
    for prompt in prompts:
        assert '"edits"' in prompt
        assert '"files"' not in prompt
    assert any("Your last reply could not be used" in p for p in prompts)
    assert any("failed. Its output" in p for p in prompts)
    assert any("leaves the repository as it was" in p for p in prompts)
    assert any("removes or skips tests" in p for p in prompts)


def opened_paths(monkeypatch) -> list[str]:
    """Every path opened through Path.open from now on."""
    import pathlib

    seen: list[str] = []
    real = pathlib.Path.open

    def spy(self, *args, **kwargs):
        seen.append(str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", spy)
    return seen


def test_apply_edits_never_opens_a_file_that_a_symlink_leads_out_of_the_clone(
    tmp_path, monkeypatch
):
    from app.repo_chore import _apply_edits

    clone = tmp_path / "clone"
    clone.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET TEXT")
    (clone / "link.txt").symlink_to(outside)
    (clone / "dirlink").symlink_to(tmp_path)
    seen = opened_paths(monkeypatch)

    for path in ("link.txt", "dirlink/outside.txt"):
        written: dict[str, str] = {}
        files, problem = _apply_edits(
            [{"path": path, "find": "SECRET", "replace": "x"}], written, clone
        )
        assert files == {} and problem and "SECRET" not in problem
        assert written == {}

    assert not [p for p in seen if p.endswith("outside.txt") or p.endswith("link.txt")]


def test_a_symlink_that_stays_inside_the_clone_can_still_be_edited(tmp_path):
    from app.repo_chore import _apply_edits

    (tmp_path / "real.txt").write_text("one two")
    (tmp_path / "alias.txt").symlink_to("real.txt")

    files, problem = _apply_edits(
        [{"path": "alias.txt", "find": "two", "replace": "2"}], {}, tmp_path
    )

    assert problem is None and files == {"alias.txt": "one 2"}


def test_a_chore_with_no_allowed_paths_does_not_read_through_a_symlink_out_of_the_clone(
    migrated_db, remote, github, tmp_path, monkeypatch
):
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET TEXT")
    work = tmp_path / "linker2"
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    (work / "leak.txt").symlink_to(secret)
    git("add", ".", cwd=work)
    git("-c", "user.name=s", "-c", "user.email=s@example.com", "commit", "-qm", "l", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    seen = opened_paths(monkeypatch)
    reply = edits_reply(("leak.txt", "SECRET", "x"))
    run_id = note_chore(migrated_db)
    model = StubModel(replies=[pick("calc.py"), reply, reply, reply])

    run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert not [p for p in seen if p.endswith("leak.txt")]
    assert all("SECRET TEXT" not in prompt for prompt in model.prompts)
    assert remote_branches(remote) == ["main"]


def test_a_refused_path_is_never_read_for_an_edit(
    migrated_db, remote, github, tmp_path, monkeypatch
):
    link_into_remote(remote, tmp_path, "link", "../..")
    seen = opened_paths(monkeypatch)
    replies = [
        pick("calc.py"),
        edits_reply(("src/pages/link/calc.py", "def add", "def plus")),
        edits_reply(("package.json", "x", "y")),
        edits_reply(("../calc.py", "def add", "def plus")),
    ]

    run_id, _, _ = run_note(migrated_db, github, tmp_path, replies)

    assert done(migrated_db, run_id)["reason"] == OUTSIDE_PATHS
    assert not [p for p in seen if p.endswith(("link/calc.py", "package.json", "../calc.py"))]
