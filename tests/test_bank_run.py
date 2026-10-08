"""The bank runner (Task 42 of docs/build-brief-evals.md, decisions 26 and
36): training chores only, each posted quiet on local from its base, and a
chore queued again only when its row says nothing about the model."""

import pytest

from bank import run
from bank.chores import BankChore, split_of
from evals.runner import EvalAborted, EvalRow, write_rows
from tests.test_eval_runner import _Api, _GitHub, _Response

DONE = {"status": "succeeded", "provider": "local", "tokens": 50, "duration_seconds": 9.0}
PENDING = _Response(201, {"id": "r1", "status": "pending"})


def chore(n: int) -> BankChore:
    key = f"pkg-{n:010d}"
    return BankChore(
        key, "pkg", "thomas-whitley/pkg", "Add sub.", "a" * 40, "b" * 40,
        ("tests/test_core.py::test_sub",), ("tests/test_core.py",), split_of(key),
    )  # fmt: skip


def of_split(split: str, count: int) -> list[BankChore]:
    return [c for c in (chore(n) for n in range(200)) if c.split == split][:count]


def row(task: str, status: str) -> EvalRow:
    return EvalRow(task, "local", "local", "r", status, False, 1, 1.0, 0.0)


@pytest.mark.parametrize("outage", ["error", "timeout", "refused"])
def test_a_chore_with_the_model_s_answer_is_not_queued_again_and_an_outage_is(tmp_path, outage):
    answered, broken, fresh = of_split("training", 3)
    write_rows([row(answered.id, "escalated"), row(broken.id, outage)], tmp_path / "a.json")

    assert run.pending([fresh, answered, broken], tmp_path) == sorted(
        [broken, fresh], key=lambda c: c.id
    )


def test_a_validation_chore_is_never_queued(tmp_path):
    assert run.pending(of_split("validation", 2), tmp_path) == []


def test_a_library_can_be_picked(tmp_path):
    [mine] = of_split("training", 1)
    other = BankChore(**{**mine.__dict__, "library": "other"})

    assert run.pending([mine, other], tmp_path, library="pkg") == [mine]


def batch(api, chores, count, rows=None):
    grades = {c.id: (lambda branch: (True, "")) for c in chores}
    return run.run_batch(
        api, _GitHub(), chores, grades, count, "https://github.com", None,
        timeout_seconds=900, poll_seconds=0, sleep=lambda s: None, on_row=lambda r: None,
        rows=rows,
    )  # fmt: skip


def test_a_batch_posts_each_chore_on_local_from_its_base_and_stops_at_the_count():
    chores = of_split("training", 3)
    api = _Api(PENDING, [DONE])

    rows = batch(api, chores, 2)

    assert [r.task for r in rows] == [c.id for c in chores[:2]]
    assert all(r.graded for r in rows)
    assert {p["provider"] for p in api.posted} == {"local"}
    assert {p["source"] for p in api.posted} == {"bank"}
    assert {p["inputs"]["base"] for p in api.posted} == {"a" * 40}


def test_a_batch_stopped_by_the_daily_cap_keeps_the_rows_it_finished():
    chores = of_split("training", 3)
    api = _Api(PENDING, [DONE, {"status": "refused"}])
    rows: list[EvalRow] = []

    with pytest.raises(EvalAborted):
        batch(api, chores, 3, rows)

    assert [r.task for r in rows] == [chores[0].id]
