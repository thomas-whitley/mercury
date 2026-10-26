"""Scoring chore diffs with a local decision model against the eval grades."""

from evals.decider import Scored, request_body, score_rows, summary
from evals.runner import EvalRow, EvalTask

TASKS = {"divide": EvalTask("divide", "o/r", "Add divide to calc.py.", "")}


def _row(graded: bool, diff: str = "diff --git a/calc.py b/calc.py\n+def divide") -> EvalRow:
    status = "succeeded" if graded else "failed"
    return EvalRow("divide", "ollama@beam", "ollama", None, status, graded, 0, 1.0, 0.0, diff=diff)


def _answer(yes: float) -> dict:
    return {"answers": {"match": {"probabilities": {"yes": yes, "partly": 0.0, "no": 1 - yes}}}}


def test_low_match_on_failed_row_is_caught():
    scored = score_rows([_row(False)], TASKS, lambda state: _answer(0.2))

    assert scored == [Scored("divide", "ollama@beam", False, 0.2)]
    assert "catch 100% (1 of 1 fails)" in summary(scored)


def test_low_match_on_passed_row_is_a_false_flag():
    scored = score_rows([_row(True)], TASKS, lambda state: _answer(0.3))

    assert "false flags 100% (1 of 1 passes)" in summary(scored)


def test_unscored_reply_is_skipped():
    scored = score_rows([_row(False)], TASKS, lambda state: {"error": "model not found"})

    assert scored[0].match is None
    text = summary(scored)
    assert "scored 0 of 1" in text
    assert "catch n/a (0 of 0 fails)" in text


def test_a_row_with_no_diff_is_not_sent():
    sent = []

    scored = score_rows([_row(False, diff="")], TASKS, lambda state: sent.append(state))

    assert sent == []
    assert scored[0].match is None


def test_the_state_carries_the_instruction_and_the_diff():
    sent = []

    score_rows([_row(True)], TASKS, lambda state: sent.append(state) or _answer(0.9))

    assert sent == [
        "Instruction:\nAdd divide to calc.py.\n\nDiff:\ndiff --git a/calc.py b/calc.py\n+def divide"
    ]


def test_summary_meets_the_bar():
    fails = [Scored("t", "c", False, m) for m in (0.1, 0.2, 0.3, 0.9)]
    passes = [Scored("t", "c", True, 0.9) for _ in range(5)]

    assert "meets the bar (catch 75%, false flags 0%)" in summary(fails + passes)


def test_summary_misses_the_bar_on_false_flags():
    fails = [Scored("t", "c", False, 0.1) for _ in range(4)]
    passes = [Scored("t", "c", True, m) for m in (0.1, 0.9, 0.9, 0.9, 0.9)]

    assert "does not meet the bar (catch 100%, false flags 20%)" in summary(fails + passes)


def test_the_request_asks_one_choice_question():
    body = request_body("clef-flash", "state")

    assert body["model"] == "clef-flash"
    assert body["state"] == "state"
    question = body["questions"]["match"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"yes", "partly", "no"}
