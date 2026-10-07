"""The rescue pass (Phase 3 of docs/build-brief-evals.md, decisions 47 to 50):
a brief of each failed row for a Claude session, which never shows a grade,
then its hints sent through advise, or through delegate.ps1 for a delegate
row, and the rerun graded on its own branch."""

import json
import subprocess

import pytest

from evals import rescue, runner
from evals.runner import EvalRow, EvalTask, load_rows, row_key, write_rows

TASK = EvalTask(id="divide", repo="o/fixture", instruction="Add divide.", grade="x = 1\n")
TASKS = {"divide": TASK}
GRADE_TEXT = "grade_hidden (unittest.loader._FailedTest.grade_hidden) ... ERROR"


def failed(
    column: str = "gemini",
    status: str = "escalated",
    detail: str = "tests still failing after 3 attempts",
    run_id: str | None = "run-1",
    repeat: int = 1,
) -> EvalRow:
    return EvalRow(
        "divide", column, column, run_id, status, False, 900, 30.0, 0.0, detail,
        repeat=repeat, diff="+def div(a, b):\n", test_tail="AssertionError: 2 != 2.5",
    )  # fmt: skip


def test_a_wrong_pull_request_is_briefed_with_its_diff_and_never_its_grade():
    row = failed(status="succeeded", detail=GRADE_TEXT)

    text, hints = rescue.brief([row], TASKS)

    assert "## divide/gemini/1" in text
    assert "Add divide." in text
    assert "+def div(a, b):" in text
    assert rescue.WRONG_PULL in text
    assert "grade_hidden" not in text
    assert hints == {"divide/gemini/1": ""}


def test_an_escalated_row_is_briefed_with_its_reason_and_test_tail():
    text, _ = rescue.brief([failed()], TASKS)

    assert "tests still failing after 3 attempts" in text
    assert "AssertionError: 2 != 2.5" in text


@pytest.mark.parametrize("status", ["timeout", "error", "refused"])
def test_a_row_no_hint_can_fix_is_listed_as_not_rescued(status):
    text, hints = rescue.brief([failed(status=status)], TASKS)

    assert hints == {}
    assert f"divide/gemini/1: {status}" in text


def test_a_passing_row_is_not_briefed():
    passed = failed(status="succeeded")
    passed.graded = True

    text, hints = rescue.brief([passed], TASKS)

    assert hints == {}
    assert "divide/gemini/1" not in text


class _Response:
    def __init__(self, status_code: int, body=None, text: str = "") -> None:
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Api:
    """advise answers with run-2, which then succeeds."""

    def __init__(self, advised: _Response | None = None) -> None:
        self.advised = advised or _Response(201, {"id": "run-2", "status": "pending"})
        self.posts: list[tuple[str, dict | None]] = []

    def post(self, path: str, json: dict | None = None) -> _Response:
        self.posts.append((path, json))
        return self.advised

    def get(self, path: str) -> _Response:
        if path.endswith("/events"):
            return _Response(200, [{"id": 1, "kind": "done", "seq": 9, "output": {}}])
        return _Response(
            200, {"status": "succeeded", "provider": "gemini", "tokens": 500,
                  "duration_seconds": 20.0},
        )  # fmt: skip


class _GitHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, params: dict | None = None) -> _Response:
        return _Response(200, [{"number": 8}])

    def patch(self, path: str, json: dict) -> _Response:
        return _Response(200)

    def delete(self, path: str) -> _Response:
        self.calls.append(("delete", path))
        return _Response(204)


def _apply(rows, hints, api=None, github=None, **kwargs):
    return rescue.apply_hints(
        rows, hints, TASKS, api or _Api(), github or _GitHub(), "file:///unused", None,
        timeout_seconds=60, poll_seconds=0, sleep=lambda s: None, **kwargs,
    )  # fmt: skip


def test_a_hint_for_a_mercury_row_is_sent_through_advise_on_its_column(monkeypatch):
    graded: list[str] = []
    monkeypatch.setattr(
        runner, "grade_branch", lambda url, branch, *a, **k: graded.append(branch) or (True, "")
    )
    api, github = _Api(), _GitHub()
    row = failed(column="ollama")

    [after] = _apply([row], {"divide/ollama/1": "Use float division."}, api, github)

    assert api.posts == [
        ("/runs/run-1/advise", {"hint": "Use float division.", "provider": "ollama"})
    ]
    assert graded == ["agent/run-2"]
    assert ("delete", "/repos/o/fixture/git/refs/heads/agent/run-2") in github.calls
    assert after.rescue_hint == "Use float division."
    assert (after.rescue.run_id, after.rescue.graded, after.rescue.repeat) == ("run-2", True, 1)


def test_advice_that_is_refused_is_recorded_as_a_refused_rescue():
    api = _Api(_Response(422, text='{"detail":"Run run-1 is error, not escalated."}'))

    [after] = _apply([failed()], {"divide/gemini/1": "a hint"}, api)

    assert (after.rescue.status, after.rescue.graded) == ("refused", False)
    assert "not escalated" in after.rescue.detail


def test_a_hint_for_a_row_that_does_not_exist_stops_before_any_rerun():
    api = _Api()

    with pytest.raises(ValueError, match="divide/gemini/2"):
        _apply([failed()], {"divide/gemini/1": "a hint", "divide/gemini/2": "another"}, api)

    assert api.posts == []


def test_a_blank_hint_reruns_nothing():
    api = _Api()

    [after] = _apply([failed()], {"divide/gemini/1": "  "}, api)

    assert api.posts == []
    assert (after.rescue, after.rescue_hint) == (None, None)


def test_a_delegate_row_reruns_with_the_hint_and_its_earlier_diff(tmp_path):
    seen: list[str] = []

    def fake_delegate(work, instruction, model, timeout):
        seen.append(instruction)
        return subprocess.CompletedProcess([], 0, "", "")

    row = failed(
        column="delegate:local", status="failed", detail="FAILED (failures=1)", run_id=None
    )

    [after] = _apply(
        [row], {"divide/delegate:local/1": "Return a float."},
        delegate=fake_delegate, clone_url=_bare_repo(tmp_path),
    )  # fmt: skip

    [instruction] = seen
    assert instruction.startswith("Add divide.")
    assert "Return a float." in instruction
    assert "+def div(a, b):" in instruction
    assert after.rescue.status == "failed"  # the fake changed nothing


def _bare_repo(tmp_path) -> str:
    work = tmp_path / "seed"
    work.mkdir()
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "."],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed"],
    ):
        subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare.as_uri()


def test_rows_with_a_rescue_round_trip_through_the_json(tmp_path):
    row = failed()
    row.rescue_hint = "a hint"
    row.rescue = failed(run_id="run-2")
    path = tmp_path / "2026-10-08T0100Z.json"

    write_rows([row], path)

    assert load_rows(path) == [row]
    assert json.loads(path.read_text(encoding="utf-8"))[0]["rescue"]["run_id"] == "run-2"
    assert (tmp_path / "2026-10-08T0100Z.md").exists()


def test_a_row_key_names_the_task_column_and_repeat():
    assert row_key(failed(column="local", repeat=3)) == "divide/local/3"


def test_the_table_summarises_every_results_file_together(tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_rows([failed(column="gemini")], first)
    write_rows([failed(column="local")], second)

    table = rescue.table([first, second])

    assert "| gemini | 0 of 1 |" in table
    assert "| local | 0 of 1 |" in table
