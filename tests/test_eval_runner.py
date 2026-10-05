"""The eval runner, against a local bare repo and fake API and GitHub
clients. The live runs are in evals/results/, not here."""

import subprocess
from pathlib import Path

import pytest

from app.config import PROVIDERS
from evals import runner
from evals.runner import (
    EvalAborted,
    EvalRow,
    EvalTask,
    grade_branch,
    load_tasks,
    run_one,
    summarise,
)

GRADE_PASS = (
    "import unittest\nfrom calc import add\n\n\n"
    "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
)
GRADE_FAIL = GRADE_PASS.replace("5)", "6)")
GRADE_CALLABLE = (
    "import unittest\nfrom calc import add\n\n\n"
    "class T(unittest.TestCase):\n    def test_add_exists(self):\n"
    "        self.assertTrue(callable(add))\n"
)
GRADE_MISSING = (
    "import unittest\nfrom roman import to_roman\n\n\n"
    "class T(unittest.TestCase):\n    def test_one(self):\n"
    "        self.assertEqual(to_roman(1), 'I')\n"
)
SEED_TEST = (
    "import unittest\nfrom calc import add\n\n\n"
    "class AddTest(unittest.TestCase):\n    def test_add(self):\n"
    "        self.assertEqual(add(2, 3), 5)\n"
)


def remote(
    tmp_path: Path,
    branch: str = "agent/run-1",
    seed_test: bool = False,
    on_branch: dict[str, str] | None = None,
) -> str:
    """A bare repo whose main holds calc.py (and test_calc.py with seed_test),
    plus one more branch carrying on_branch's files. HEAD is main, as on GitHub."""
    work = tmp_path / "seed"
    work.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)

    def commit(message: str) -> None:
        git("add", ".")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)

    git("init", "-q", "-b", "main")
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    if seed_test:
        (work / "test_calc.py").write_text(SEED_TEST, encoding="utf-8")
    commit("seed")
    git("checkout", "-q", "-b", branch)
    for name, text in (on_branch or {}).items():
        (work / name).write_text(text, encoding="utf-8")
    if on_branch:
        commit("chore")
    git("checkout", "-q", "main")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare.as_uri()


def test_a_branch_that_meets_the_grade_passes(tmp_path):
    passed, output = grade_branch(remote(tmp_path), "agent/run-1", GRADE_PASS)
    assert passed
    assert "OK" in output


def test_a_branch_that_misses_the_grade_fails(tmp_path):
    passed, _ = grade_branch(remote(tmp_path), "agent/run-1", GRADE_FAIL)
    assert not passed


def test_a_grade_that_cannot_import_its_module_fails_without_raising(tmp_path):
    passed, output = grade_branch(remote(tmp_path), "agent/run-1", GRADE_MISSING)
    assert not passed
    assert "roman" in output


def test_a_missing_branch_fails_the_grade(tmp_path):
    passed, output = grade_branch(remote(tmp_path), "agent/other", GRADE_PASS)
    assert not passed
    assert output.startswith("clone failed")


def test_a_branch_that_deletes_a_test_from_main_fails(tmp_path):
    url = remote(tmp_path, seed_test=True, on_branch={"test_calc.py": "import unittest\n"})

    passed, output = grade_branch(url, "agent/run-1", GRADE_PASS)

    assert not passed
    assert output.startswith("tests removed")
    assert "test_add" in output


def test_a_branch_that_breaks_its_own_tests_fails(tmp_path):
    url = remote(
        tmp_path, seed_test=True, on_branch={"calc.py": "def add(a, b):\n    return a - b\n"}
    )

    passed, output = grade_branch(url, "agent/run-1", GRADE_CALLABLE)

    assert not passed
    assert output.startswith("own tests failed")


def test_a_branch_that_keeps_main_s_tests_and_adds_its_own_passes(tmp_path):
    extra = (
        SEED_TEST + "\n    def test_add_negative(self):\n        self.assertEqual(add(-1, 1), 0)\n"
    )
    url = remote(tmp_path, seed_test=True, on_branch={"test_calc.py": extra})

    passed, output = grade_branch(url, "agent/run-1", GRADE_PASS)

    assert passed, output


def test_tasks_load_from_yaml_named_by_their_file(tmp_path):
    (tmp_path / "b.yaml").write_text(
        "repo: o/r\ninstruction: |\n  Do b.\ngrade: |\n  x = 1\n", encoding="utf-8"
    )
    (tmp_path / "a.yaml").write_text(
        "repo: o/r\ninstruction: Do a.\ngrade: x = 2\n", encoding="utf-8"
    )

    tasks = load_tasks(tmp_path)

    assert [t.id for t in tasks] == ["a", "b"]
    assert tasks[1] == EvalTask(id="b", repo="o/r", instruction="Do b.", grade="x = 1\n")


class _Response:
    def __init__(self, status_code: int, body=None, text: str = "") -> None:
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Api:
    """POST /runs answers created; GET /runs/{id} walks through statuses,
    repeating the last one."""

    def __init__(self, created: _Response, statuses: list[dict]) -> None:
        self.created, self.statuses, self.posted = created, list(statuses), []

    def post(self, path: str, json: dict) -> _Response:
        self.posted.append(json)
        return self.created

    def get(self, path: str) -> _Response:
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return _Response(200, status)


class _GitHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, params: dict | None = None) -> _Response:
        self.calls.append(("get", path))
        return _Response(200, [{"number": 7}])

    def patch(self, path: str, json: dict) -> _Response:
        self.calls.append(("patch", path))
        return _Response(200)

    def delete(self, path: str) -> _Response:
        self.calls.append(("delete", path))
        return _Response(204)


TASK = EvalTask(id="divide", repo="o/fixture", instruction="Add divide.", grade=GRADE_PASS)
DONE = {"status": "succeeded", "provider": "gemini", "tokens": 900, "duration_seconds": 40.0}
PENDING = _Response(201, {"id": "run-1", "status": "pending"})


def _run(api, github, timeout: float = 900) -> EvalRow:
    ticks = iter(range(0, 100_000, 5))
    return run_one(
        api,
        github,
        TASK,
        "gemini",
        "file:///unused",
        None,
        timeout_seconds=timeout,
        poll_seconds=0,
        sleep=lambda seconds: None,
        clock=lambda: next(ticks),
    )


def test_a_green_chore_is_graded_and_its_pull_request_closed(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", lambda *a, **k: (True, "OK"))
    api = _Api(PENDING, [{"status": "running"}, DONE])
    github = _GitHub()

    row = _run(api, github)

    assert api.posted == [
        {
            "type": "repo_chore",
            "inputs": {"task": "Add divide.", "repo": "o/fixture"},
            "provider": "gemini",
        }
    ]
    assert (row.status, row.graded, row.tokens, row.answered_by) == (
        "succeeded",
        True,
        900,
        "gemini",
    )
    assert ("patch", "/repos/o/fixture/pulls/7") in github.calls
    assert ("delete", "/repos/o/fixture/git/refs/heads/agent/run-1") in github.calls


def test_a_red_chore_is_not_graded_and_nothing_is_closed(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", pytest.fail)
    api = _Api(PENDING, [{**DONE, "status": "failed"}])
    github = _GitHub()

    row = _run(api, github)

    assert (row.status, row.graded) == ("failed", False)
    assert github.calls == []


def test_a_chore_that_never_finishes_is_a_timeout():
    api = _Api(PENDING, [{"status": "running", "tokens": 0}])

    row = _run(api, _GitHub(), timeout=60)

    assert (row.status, row.graded) == ("timeout", False)


def test_a_refused_chore_is_recorded_not_raised():
    api = _Api(_Response(422, text='{"detail":"I can only work on a/b."}'), [])

    row = _run(api, _GitHub())

    assert (row.status, row.run_id) == ("refused", None)
    assert "only work on" in row.detail


def test_a_chore_waiting_for_approval_stops_the_batch():
    api = _Api(_Response(201, {"id": "run-1", "status": "awaiting_approval"}), [])

    with pytest.raises(EvalAborted, match="auto_approve"):
        _run(api, _GitHub())


def test_cost_uses_the_rate_of_the_provider_that_answered(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", lambda *a, **k: (True, "OK"))
    answered = {**DONE, "provider": "haiku", "tokens": 1_000_000}
    api = _Api(PENDING, [answered])

    row = _run(api, _GitHub())

    assert row.usd == pytest.approx(PROVIDERS["haiku"].usd_per_million_tokens)


def _row(provider: str, graded: bool, status: str = "succeeded", tokens: int | None = 1000):
    return EvalRow("t", provider, provider, "id", status, graded, tokens, 30.0, 0.0)


def test_the_summary_counts_hidden_test_passes_per_column():
    table = summarise([_row("gemini", True), _row("gemini", False, "failed"), _row("ollama", True)])

    assert "| gemini | 1 of 2 | 1 of 2 | 1000 | 30 | 0.0000 |" in table
    assert "| ollama | 1 of 1 | 1 of 1 | 1000 | 30 | 0.0000 |" in table


def test_the_summary_shows_no_tokens_for_a_column_that_cannot_count_them():
    table = summarise([_row("delegate:local", True, tokens=None)])

    assert "| delegate:local | 1 of 1 | 1 of 1 | n/a | 30 | 0.0000 |" in table
