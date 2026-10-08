"""The bank's training examples (Task 44 of docs/build-brief-evals.md,
decisions 38 and 59): self, then rescued without the hint, then the commit
itself, and never a validation chore."""

import json
from dataclasses import replace

import pytest

from app.advice_text import advice_block
from app.chore_prompts import SYSTEM
from bank import export
from bank.chores import BankChore
from bank.grade import ensure_mirror
from evals.runner import EvalRow
from tests.bank_repo import CORE_SUB, EXTRA, PKG, library_repo

READ = {
    "seq": 2, "system": SYSTEM, "prompt": "Instruction:\nAdd sub.ADVICE\n\nFiles",
    "reply": '{"read": ["pkg/core.py"]}',
}  # fmt: skip
EDIT = {
    "seq": 9, "system": SYSTEM, "prompt": "Instruction:\nAdd sub.ADVICE\n\nContents",
    "reply": '{"files": {"pkg/core.py": "x"}, "summary": "s"}',
}  # fmt: skip


def with_advice(advice: str, *calls: dict) -> list[dict]:
    return [{**c, "prompt": c["prompt"].replace("ADVICE", advice)} for c in calls]


def test_a_run_s_first_and_last_calls_are_its_two_turns():
    records = export.from_calls("pkg-1", "self", [READ, {"seq": 5, "reply": "{}"}, EDIT])

    assert [r["turn"] for r in records] == ["read", "edit"]
    assert {r["origin"] for r in records} == {"self"}
    assert [m["role"] for m in records[1]["messages"]] == ["system", "user", "assistant"]
    assert records[1]["messages"][2]["content"] == EDIT["reply"]


def test_a_run_whose_last_reply_has_no_files_gives_no_example():
    assert export.from_calls("pkg-1", "self", [READ, {**EDIT, "reply": '{"read": []}'}]) is None
    assert export.from_calls("pkg-1", "self", [READ, {**EDIT, "reply": "not json"}]) is None
    assert export.from_calls("pkg-1", "self", [READ]) is None


def test_a_rescued_example_has_neither_the_hint_nor_the_earlier_diff():
    hint = "Keep add where it is."
    advice = advice_block(hint, {"status": "escalated", "reason": "red", "diff": "+bad\n"})

    records = export.rescued("pkg-1", hint, advice, with_advice(advice, READ, EDIT))

    text = json.dumps(records)
    assert hint not in text
    assert "+bad" not in text
    assert records[0]["messages"][1]["content"] == "Instruction:\nAdd sub.\n\nFiles"
    assert {r["origin"] for r in records} == {"rescued"}


def test_a_rescued_example_whose_advice_is_not_in_its_prompt_is_dropped():
    assert export.rescued("pkg-1", "a hint", "\n\nThe owner's hint: a hint", [READ, EDIT]) is None


def test_a_rescued_example_whose_reply_repeats_the_hint_is_dropped():
    advice = "\n\nThe owner's hint: use sub"
    calls = with_advice(advice, READ, {**EDIT, "reply": '{"files": {"a": "use sub"}}'})

    assert export.rescued("pkg-1", "use sub", advice, calls) is None


def test_the_reference_reads_the_changed_source_and_what_the_tests_import():
    tree = ["pkg/__init__.py", "pkg/core.py", "pkg/util.py", "tests/test_core.py"]
    tests = {"tests/test_core.py": "from pkg.util import x\nimport pkg.core\nimport os\n"}

    assert export.reference_reads(tree, ["pkg/core.py"], tests, PKG) == [
        "pkg/core.py",
        "pkg/util.py",
    ]


def mined(tmp_path) -> tuple[BankChore, object]:
    _, shas = library_repo(tmp_path)
    mirror = ensure_mirror(PKG, f"file://{tmp_path / 'remote'}", root=tmp_path / "m")
    chore = BankChore(
        "pkg-1", "pkg", "thomas-whitley/pkg", "In pkg/core.py add sub(a, b).", shas["base"],
        shas["adds_sub"], ("tests/test_core.py::test_sub",),
        ("tests/test_core.py", "tests/test_extra.py"), "training",
    )  # fmt: skip
    return chore, mirror


def test_a_reference_example_replies_with_the_commit_s_source_files_only(tmp_path):
    chore, mirror = mined(tmp_path)

    read, edit = export.reference(chore, PKG, mirror, tmp_path / "w")

    assert json.loads(read["messages"][2]["content"]) == {"read": ["pkg/core.py"]}
    assert "=== pkg/core.py ===" in edit["messages"][1]["content"]
    reply = json.loads(edit["messages"][2]["content"])
    assert reply["files"] == {"pkg/core.py": CORE_SUB, "pkg/extra.py": EXTRA}
    assert reply["summary"] == "Add sub and twice"
    assert "test_sub" not in json.dumps([read, edit])


class _Response:
    def __init__(self, body) -> None:
        self.status_code, self._body = 200, body

    def json(self):
        return self._body


class _CallsApi:
    def __init__(self, calls: dict[str, list[dict]], done: dict[str, dict]) -> None:
        self.calls, self.done = calls, done

    def get(self, path: str) -> _Response:
        run_id = path.split("/")[2]
        if path.endswith("/calls"):
            return _Response(self.calls.get(run_id, []))
        return _Response([{"kind": "done", "output": self.done.get(run_id, {})}])


def row(task: str, run_id: str, status: str, graded: bool) -> EvalRow:
    return EvalRow(task, "local", "local", run_id, status, graded, 1, 1.0, 0.0)


def test_the_export_takes_self_then_rescued_then_reference_and_never_validation(tmp_path):
    chore, mirror = mined(tmp_path)
    passed, saved, failed = (replace(chore, id=f"pkg-{n}") for n in ("a", "b", "c"))
    validation = replace(chore, id="pkg-v", split="validation")
    hint = "Keep add."
    first = {"status": "escalated", "reason": "red", "diff": "+bad\n", "test_output": "boom"}
    advice = advice_block(hint, first)
    escalated = row("pkg-b", "run-2", "escalated", False)
    escalated.rescue, escalated.rescue_hint = row("pkg-b", "run-3", "succeeded", True), hint
    rows = [
        row("pkg-a", "run-1", "succeeded", True),
        escalated,
        row("pkg-c", "run-4", "escalated", False),
        row("pkg-v", "run-5", "succeeded", True),
    ]
    api = _CallsApi(
        {"run-1": [READ, EDIT], "run-3": with_advice(advice, READ, EDIT), "run-5": [READ, EDIT]},
        {"run-2": first},
    )

    records, counts = export.export(
        rows, [passed, saved, failed, validation], {"pkg": PKG}, api, {"pkg": mirror},
        tmp_path / "w",
    )  # fmt: skip

    origins = {(r["chore"], r["origin"]) for r in records}
    assert origins == {("pkg-a", "self"), ("pkg-b", "rescued"), ("pkg-c", "reference")}
    assert len(records) == 6
    assert dict(counts) == {
        "self": 1, "rescued": 1, "reference": 1, "validation, not exported": 1,
    }  # fmt: skip
    assert hint not in json.dumps(records)


def test_a_training_chore_with_no_row_yet_is_not_exported(tmp_path):
    chore, mirror = mined(tmp_path)

    records, counts = export.export(
        [], [chore], {"pkg": PKG}, _CallsApi({}, {}), {"pkg": mirror}, tmp_path / "w"
    )

    assert records == []
    assert counts["not run"] == 1


class _DownApi:
    def get(self, path: str):
        return type("R", (), {"status_code": 404, "json": lambda self: {"detail": "not found"}})()


def test_an_export_that_cannot_read_a_graded_run_s_calls_stops_rather_than_guessing(tmp_path):
    # A wrong MERCURY_URL or a lost compose volume would otherwise turn every
    # self example into a reference one and overwrite the file (finding 2).
    chore, mirror = mined(tmp_path)

    with pytest.raises(export.ExportError, match="run-1"):
        export.export(
            [row("pkg-1", "run-1", "succeeded", True)], [chore], {"pkg": PKG}, _DownApi(),
            {"pkg": mirror}, tmp_path / "w",
        )  # fmt: skip


def test_a_graded_run_with_no_recorded_calls_stops_the_export(tmp_path):
    chore, mirror = mined(tmp_path)

    with pytest.raises(export.ExportError, match="no model calls"):
        export.export(
            [row("pkg-1", "run-1", "succeeded", True)], [chore], {"pkg": PKG},
            _CallsApi({}, {}), {"pkg": mirror}, tmp_path / "w",
        )  # fmt: skip
