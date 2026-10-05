"""The eval runner, against a local bare repo and fake API and GitHub
clients. The live runs are in evals/results/, not here."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.config import PROVIDERS
from evals import runner
from evals.runner import (
    DiscoveryFailed,
    EvalAborted,
    EvalRow,
    EvalTask,
    _call_delegate_script,
    _run_tree,
    close_pull_and_branch,
    contained,
    grade_branch,
    load_tasks,
    run_delegate,
    run_one,
    summarise,
    test_ids,
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
        self.cancelled: list[str] = []

    def post(self, path: str, json: dict | None = None) -> _Response:
        if path.endswith("/cancel"):
            self.cancelled.append(path)
            return _Response(200, {"cancelled": True})
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

    github = _GitHub()

    row = _run(api, github, timeout=60)

    assert (row.status, row.graded) == ("timeout", False)
    assert api.cancelled == ["/runs/run-1/cancel"]
    # The chore may have pushed its branch just before the cancel landed.
    assert ("delete", "/repos/o/fixture/git/refs/heads/agent/run-1") in github.calls


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


GRADE_DIVIDE = (
    "import unittest\nfrom calc import divide\n\n\n"
    "class T(unittest.TestCase):\n    def test_divide(self):\n"
    "        self.assertEqual(divide(6, 3), 2)\n"
)
DIVIDE_TASK = EvalTask(id="divide", repo="o/fixture", instruction="Add divide.", grade=GRADE_DIVIDE)
CALC_WITH_DIVIDE = "def add(a, b):\n    return a + b\n\n\ndef divide(a, b):\n    return a / b\n"


def _delegate_writing(files: dict[str, str], returncode: int = 0, stderr: str = ""):
    def delegate(work, instruction, model, timeout_seconds):
        for name, text in files.items():
            (work / name).write_text(text, encoding="utf-8")
        return subprocess.CompletedProcess(["pwsh"], returncode, "", stderr)

    return delegate


def test_a_delegate_change_that_keeps_the_tests_green_is_graded(tmp_path):
    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": CALC_WITH_DIVIDE}),
    )

    assert (row.provider, row.status, row.graded, row.tokens) == (
        "delegate:local",
        "succeeded",
        True,
        None,
    )


def test_a_delegate_change_that_breaks_the_tests_is_failed_and_not_graded(tmp_path):
    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": "oops("}),
    )

    assert (row.status, row.graded) == ("failed", False)


def test_a_delegate_change_that_replaces_main_s_test_is_not_graded_a_pass(tmp_path):
    own_test = (
        "import unittest\nfrom calc import divide\n\n\n"
        "class DivideTest(unittest.TestCase):\n    def test_divide(self):\n"
        "        self.assertEqual(divide(4, 2), 2)\n"
    )
    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": CALC_WITH_DIVIDE, "test_calc.py": own_test}),
    )

    assert (row.status, row.graded) == ("succeeded", False)
    assert row.detail.startswith("tests removed")


def test_a_delegate_that_runs_too_long_is_a_timeout(tmp_path):
    def slow(work, instruction, model, timeout_seconds):
        raise subprocess.TimeoutExpired("pwsh", timeout_seconds)

    row = run_delegate(DIVIDE_TASK, "local", remote(tmp_path, seed_test=True), delegate=slow)

    assert (row.status, row.graded) == ("timeout", False)


def test_a_run_the_worker_refused_stops_the_batch_naming_the_daily_limit():
    api = _Api(PENDING, [{"status": "refused", "provider": "gemini", "tokens": 0}])

    with pytest.raises(EvalAborted, match="MAX_RUNS_PER_DAY") as stop:
        _run(api, _GitHub())

    assert "run-1" in str(stop.value)


def test_the_timeout_clock_starts_only_once_the_run_leaves_pending(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", lambda *a, **k: (True, "OK"))
    # 30 polls at 5 s each wait 150 s in the queue, longer than the 60 s timeout.
    api = _Api(PENDING, [{"status": "pending"}] * 30 + [{"status": "running"}, DONE])

    row = _run(api, _GitHub(), timeout=60)

    assert (row.status, row.graded) == ("succeeded", True)
    assert api.cancelled == []


def test_a_run_that_never_leaves_pending_is_cancelled_after_three_timeouts_of_waiting():
    api = _Api(PENDING, [{"status": "pending"}])

    row = _run(api, _GitHub(), timeout=60)

    assert row.status == "timeout"
    assert api.cancelled == ["/runs/run-1/cancel"]


def test_an_error_in_one_row_is_recorded_without_the_token():
    def boom():
        raise RuntimeError("clone of https://x-access-token:s3cret@host failed: s3cret")

    row = contained(boom, "divide", "gemini", "s3cret")

    assert (row.status, row.graded, row.task, row.provider) == ("error", False, "divide", "gemini")
    assert "RuntimeError" in row.detail
    assert "s3cret" not in row.detail


def test_an_aborted_batch_is_not_contained():
    def stop():
        raise EvalAborted("stop")

    with pytest.raises(EvalAborted):
        contained(stop, "divide", "gemini", None)


def test_the_branch_is_cleaned_up_even_when_grading_raises(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("grading blew up")

    monkeypatch.setattr(runner, "grade_branch", broken)
    api = _Api(PENDING, [DONE])
    github = _GitHub()

    with pytest.raises(RuntimeError, match="grading blew up"):
        _run(api, github)

    assert ("delete", "/repos/o/fixture/git/refs/heads/agent/run-1") in github.calls


class _FailingGitHub(_GitHub):
    def __init__(self, patch_status: int = 200, delete_status: int = 204) -> None:
        super().__init__()
        self.patch_status, self.delete_status = patch_status, delete_status

    def patch(self, path: str, json: dict) -> _Response:
        super().patch(path, json)
        return _Response(self.patch_status)

    def delete(self, path: str) -> _Response:
        super().delete(path)
        return _Response(self.delete_status)


def test_a_pull_request_that_cannot_be_closed_is_an_error():
    with pytest.raises(RuntimeError, match="403"):
        close_pull_and_branch(_FailingGitHub(patch_status=403), "o/fixture", "agent/run-1")


def test_a_branch_that_cannot_be_deleted_is_an_error():
    with pytest.raises(RuntimeError, match="500"):
        close_pull_and_branch(_FailingGitHub(delete_status=500), "o/fixture", "agent/run-1")


@pytest.mark.parametrize("status", [404, 422])
def test_a_branch_that_was_never_pushed_is_not_an_error(status):
    close_pull_and_branch(_FailingGitHub(delete_status=status), "o/fixture", "agent/run-1")


def test_every_temporary_directory_ignores_cleanup_errors(monkeypatch, tmp_path):
    real = runner.tempfile.TemporaryDirectory
    seen: list[dict] = []

    def recording(*args, **kwargs):
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", recording)

    grade_branch("file:///no/such/repo.git", "main", GRADE_PASS)
    run_delegate(DIVIDE_TASK, "local", "file:///no/such/repo.git")

    assert [kwargs.get("ignore_cleanup_errors") for kwargs in seen] == [True, True]


def test_a_delegate_clone_that_times_out_is_a_timeout_row(monkeypatch, tmp_path):
    def slow_clone(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 120)

    monkeypatch.setattr(runner, "clone", slow_clone)

    row = run_delegate(DIVIDE_TASK, "local", "file:///unused")

    assert (row.status, row.graded) == ("timeout", False)


def test_a_delegate_test_listing_that_times_out_is_a_timeout_row(monkeypatch, tmp_path):
    def slow_ids(*args, **kwargs):
        raise subprocess.TimeoutExpired("python", 120)

    monkeypatch.setattr(runner, "test_ids", slow_ids)

    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": CALC_WITH_DIVIDE}),
    )

    assert (row.status, row.graded) == ("timeout", False)


def test_a_delegate_repo_test_run_that_times_out_is_a_timeout_row(monkeypatch, tmp_path):
    real_run = subprocess.run

    def run(args, *a, **kwargs):
        if args == runner.REPO_TESTS:
            raise subprocess.TimeoutExpired("python", 600)
        return real_run(args, *a, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", run)

    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": CALC_WITH_DIVIDE}),
    )

    assert (row.status, row.graded) == ("timeout", False)


def test_a_delegate_that_cannot_start_pwsh_is_an_error_row(tmp_path):
    def missing(work, instruction, model, timeout_seconds):
        raise FileNotFoundError("pwsh")

    row = run_delegate(DIVIDE_TASK, "local", remote(tmp_path, seed_test=True), delegate=missing)

    assert (row.status, row.graded) == ("error", False)
    assert "pwsh" in row.detail


def test_a_delegate_that_exits_nonzero_is_failed_with_the_end_of_its_stderr(tmp_path):
    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing(
            {"calc.py": CALC_WITH_DIVIDE}, returncode=1, stderr="x" * 5000 + "model server down"
        ),
    )

    assert (row.status, row.graded) == ("failed", False)
    assert row.detail.endswith("model server down")


def test_a_delegate_that_changes_nothing_is_failed(tmp_path):
    row = run_delegate(
        DIVIDE_TASK, "local", remote(tmp_path, seed_test=True), delegate=_delegate_writing({})
    )

    assert (row.status, row.graded, row.detail) == ("failed", False, "no change")


def test_a_command_s_output_goes_to_a_file_not_a_pipe(tmp_path):
    out = tmp_path / "out.log"
    code = "import sys; print('said'); print('oops', file=sys.stderr); sys.exit(3)"

    result = _run_tree([sys.executable, "-c", code], out, 30, None)

    assert result.returncode == 3
    assert "said" in out.read_text(encoding="utf-8")
    assert "oops" in result.stderr


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.mark.skipif(os.name == "nt", reason="the Windows branch kills with taskkill")
def test_a_timeout_kills_the_whole_process_tree(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        _run_tree([sys.executable, "-c", code], tmp_path / "out.log", 2, None)

    grandchild = int(pid_file.read_text())
    for _ in range(30):
        if not _alive(grandchild):
            break
        time.sleep(0.1)
    assert not _alive(grandchild)


def test_the_delegate_script_runs_with_its_output_in_the_temp_dir(monkeypatch, tmp_path):
    seen = {}

    def fake_tree(cmd, out_path, timeout_seconds, env):
        seen.update(cmd=cmd, out=out_path, timeout=timeout_seconds)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner, "_run_tree", fake_tree)
    work = tmp_path / "work"

    _call_delegate_script(work, "Add divide.", "local", 77)

    assert seen["cmd"][:3] == ["pwsh", "-NoProfile", "-File"]
    assert seen["cmd"][seen["cmd"].index("-Dir") + 1] == str(work)
    assert seen["out"].parent == tmp_path
    assert seen["timeout"] == 77


def test_the_runner_timeout_reaches_the_delegate_column(monkeypatch):
    seen = {}

    def fake_delegate(task, model, clone_url, **kwargs):
        seen.update(model=model, **kwargs)

    monkeypatch.setattr(runner, "run_delegate", fake_delegate)

    runner._run_column("delegate:local-gpt", DIVIDE_TASK, None, None, None, 77)

    assert seen == {"model": "local-gpt", "timeout_seconds": 77}


SKIPPED_TEST = SEED_TEST.replace(
    "    def test_add", "    @unittest.skip('later')\n    def test_add"
)
SKIPPED_CLASS = SEED_TEST.replace("class AddTest", "@unittest.skip('later')\nclass AddTest")
EXPECTED_FAILURE = SEED_TEST.replace(
    "    def test_add", "    @unittest.expectedFailure\n    def test_add"
).replace("5)", "6)")


@pytest.mark.parametrize(
    "replacement", [SKIPPED_TEST, SKIPPED_CLASS, EXPECTED_FAILURE], ids=["skip", "class", "xfail"]
)
def test_a_branch_that_skips_one_of_main_s_tests_fails(tmp_path, replacement):
    url = remote(tmp_path, seed_test=True, on_branch={"test_calc.py": replacement})

    passed, output = grade_branch(url, "agent/run-1", GRADE_PASS)

    assert not passed
    assert output.startswith("tests skipped")
    assert "test_add" in output


def test_a_test_listing_that_crashes_raises_instead_of_returning_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "LIST_TESTS", "raise SystemExit(3)")

    with pytest.raises(DiscoveryFailed):
        test_ids(tmp_path)


def test_a_default_branch_whose_tests_cannot_be_listed_fails_the_grade(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "LIST_TESTS", "raise SystemExit(3)")

    passed, output = grade_branch(remote(tmp_path), "agent/run-1", GRADE_PASS)

    assert not passed
    assert output.startswith("test discovery failed")


def test_a_delegate_run_on_a_main_whose_tests_cannot_be_listed_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "LIST_TESTS", "raise SystemExit(3)")

    row = run_delegate(DIVIDE_TASK, "local", remote(tmp_path, seed_test=True))

    assert (row.status, row.graded) == ("error", False)
    assert row.detail.startswith("test discovery failed")


def test_the_summary_counts_rows_that_fell_back_and_shows_who_answered():
    fell_back = EvalRow("t1", "gemini", "ollama", "id", "succeeded", True, 1000, 30.0, 0.0)
    refused = EvalRow("t2", "gemini", None, None, "refused", False, 0, None, 0.0)

    table = summarise([_row("gemini", True), fell_back, refused])

    assert "| Fell back |" in table
    assert "| gemini | 2 of 3 | 2 of 3 | 1000 | 30 | 0.0000 | 1 |" in table
    assert "| t1 | gemini | ollama | succeeded | pass |" in table
    assert "| t2 | gemini | n/a | refused | fail |" in table
