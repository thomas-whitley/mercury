"""The eval's rescue pass (Phase 3 of docs/build-brief-evals.md, decisions 47
to 50): how often one hint from a Claude session turns a failed row into a
pass.

  python -m evals.rescue brief evals/results/<stamp>.json
writes <stamp>.rescue.md, one section per failed row that a hint might fix,
and <stamp>.hints.yaml, a blank hint for each. The brief shows what an owner
would see: the instruction, the last diff, the tail of the repo's own test
output and why it stopped. It never shows a grade test or its output, so a
hint cannot carry the answer.

A Claude session reads the brief and writes one hint per row into the hints
file. Nothing else writes a hint: no paid model is called (decision 4).

  python -m evals.rescue apply evals/results/<stamp>.json evals/results/<stamp>.hints.yaml
sends each hint. A Mercury row is advised through POST /runs/{id}/advise on
the column it failed on, and the rerun is graded on its own branch, which is
then closed and deleted. A delegate row reruns delegate.ps1 on a fresh clone
with the same advice block Mercury would add. The rows are written back to
the JSON with their rescue, and the summary beside it is rewritten. Run it
against the Mercury that ran the rows: MERCURY_URL, MERCURY_BEARER_TOKEN and
MERCURY_GITHUB_TOKEN are read as the runner reads them.
"""

import argparse
import os
import sys
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

import httpx2
import yaml

from app.advice_text import advice_block
from evals.runner import (
    FIXTURE_URL,
    HERE,
    RESCUABLE,
    EvalAborted,
    EvalRow,
    EvalTask,
    contained,
    follow,
    load_rows,
    load_tasks,
    row_key,
    run_delegate,
    write_rows,
)

WRONG_PULL = "It opened a pull request; a check outside the repo's tests found it wrong."
STAYED_RED = "It did not leave a change with the repo's own tests green."
FENCE = "````"


def rescuable(row: EvalRow) -> bool:
    return not row.graded and row.status in RESCUABLE


def _reason(row: EvalRow) -> str:
    # A succeeded row's detail is grading output, so it is never shown.
    if row.status == "succeeded":
        return WRONG_PULL
    if row.status == "escalated":
        return row.detail
    return STAYED_RED


def brief(rows: list[EvalRow], tasks: dict[str, EvalTask]) -> tuple[str, dict[str, str]]:
    """The brief's Markdown, and a blank hint for each row it asks about."""
    lines = [
        "# Rescue brief",
        "",
        "One section per failed row. Write one hint for each into the hints file: what "
        "the model got wrong and what to do instead, in a few sentences, at most 2,000 "
        "characters. Work from what is here; the grade test is not shown, and a hint "
        "should not guess at it.",
    ]
    hints: dict[str, str] = {}
    for row in rows:
        if not rescuable(row):
            continue
        key = row_key(row)
        hints[key] = ""
        lines += [
            "",
            f"## {key}",
            "",
            "Instruction:",
            "",
            FENCE,
            tasks[row.task].instruction,
            FENCE,
            "",
            f"Why it failed: {_reason(row)}",
            "",
            "Its last diff:",
            "",
            FENCE + "diff",
            row.diff.rstrip() or "(no diff)",
            FENCE,
        ]
        if row.test_tail.strip() and row.status != "succeeded":
            lines += [
                "",
                "The repo's own test output ended:",
                "",
                FENCE,
                row.test_tail.rstrip(),
                FENCE,
            ]
    skipped = [row for row in rows if not row.graded and not rescuable(row)]
    if skipped:
        lines += ["", "## Not rescued", "", "These failed for a reason no hint can fix.", ""]
        lines += [f"- {row_key(row)}: {row.status}" for row in skipped]
    return "\n".join(lines) + "\n", hints


def check_hints(rows: list[EvalRow], hints: dict[str, str]) -> None:
    """Every key must name a briefed row, before anything is rerun."""
    known = {row_key(row) for row in rows if rescuable(row)}
    unknown = sorted(set(hints) - known)
    if unknown:
        raise ValueError(f"no failed row is called {unknown[0]}; check the hints file")


def _rescue_mercury(
    row, task, hint, api, github, clone_base, token, *, timeout_seconds, poll_seconds, sleep, clock
) -> EvalRow:
    response = api.post(f"/runs/{row.run_id}/advise", json={"hint": hint, "provider": row.provider})
    if response.status_code != 201:
        return EvalRow(
            row.task, row.provider, None, None, "refused", False, 0, None, 0.0,
            response.text[:300], repeat=row.repeat,
        )  # fmt: skip
    rescued = follow(
        api, github, task, row.provider, response.json()["id"], clone_base, token,
        timeout_seconds=timeout_seconds, poll_seconds=poll_seconds, sleep=sleep, clock=clock,
    )  # fmt: skip
    rescued.repeat = row.repeat
    return rescued


def _rescue_delegate(row, task, hint, *, clone_url, delegate, timeout_seconds) -> EvalRow:
    # The same block Mercury adds to an advised rerun (app/advice_text.py).
    earlier = {"status": "escalated", "reason": _reason(row), "diff": row.diff}
    earlier["test_output"] = row.test_tail
    instruction = task.instruction + advice_block(hint, earlier)
    model = row.provider.split(":", 1)[1]
    kwargs = {"delegate": delegate} if delegate else {}
    rescued = run_delegate(
        task, model, clone_url, instruction=instruction, timeout_seconds=timeout_seconds, **kwargs
    )
    rescued.repeat = row.repeat
    return rescued


def apply_hints(
    rows: list[EvalRow],
    hints: dict[str, str],
    tasks: dict[str, EvalTask],
    api,
    github,
    clone_base: str,
    token: str | None,
    *,
    timeout_seconds: float,
    poll_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    delegate=None,
    clone_url: str = FIXTURE_URL,
) -> list[EvalRow]:
    """Rerun each row that has a non blank hint and record the rerun on it.
    An EvalAborted stops the pass; the rows done so far keep their rescue."""
    check_hints(rows, hints)
    for row in rows:
        hint = (hints.get(row_key(row)) or "").strip()
        if not hint or not rescuable(row):
            continue
        task = tasks[row.task]
        if row.provider.startswith("delegate:"):
            run = partial(
                _rescue_delegate, row, task, hint,
                clone_url=clone_url, delegate=delegate, timeout_seconds=timeout_seconds,
            )  # fmt: skip
        else:
            run = partial(
                _rescue_mercury, row, task, hint, api, github, clone_base, token,
                timeout_seconds=timeout_seconds, poll_seconds=poll_seconds, sleep=sleep,
                clock=clock,
            )  # fmt: skip
        row.rescue_hint = hint
        row.rescue = contained(run, row.task, row.provider, token)
    return rows


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives a live Mercury
    parser = argparse.ArgumentParser(description="The eval's rescue pass.")
    commands = parser.add_subparsers(dest="command", required=True)
    brief_cmd = commands.add_parser("brief", help="write the brief and a blank hints file")
    brief_cmd.add_argument("results", type=Path)
    apply_cmd = commands.add_parser("apply", help="send the hints and grade the reruns")
    apply_cmd.add_argument("results", type=Path)
    apply_cmd.add_argument("hints", type=Path)
    apply_cmd.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)

    rows = load_rows(args.results)
    tasks = {task.id: task for task in load_tasks(HERE / "chores")}
    stem = args.results.with_suffix("")
    if args.command == "brief":
        text, hints = brief(rows, tasks)
        Path(f"{stem}.rescue.md").write_text(text, encoding="utf-8")
        Path(f"{stem}.hints.yaml").write_text(
            yaml.safe_dump(hints, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        print(f"{len(hints)} rows to rescue; written to {stem}.rescue.md and {stem}.hints.yaml")
        return 0

    hints = yaml.safe_load(args.hints.read_text(encoding="utf-8")) or {}
    api = github = token = None
    if any(not row.provider.startswith("delegate:") for row in rows):
        token = os.environ["MERCURY_GITHUB_TOKEN"]
        api = httpx2.Client(
            base_url=os.environ["MERCURY_URL"].rstrip("/"),
            headers={"Authorization": f"Bearer {os.environ['MERCURY_BEARER_TOKEN']}"},
            timeout=60,
        )
        github = httpx2.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=30,
        )
    try:
        apply_hints(
            rows, hints, tasks, api, github, "https://github.com", token,
            timeout_seconds=args.timeout,
        )  # fmt: skip
    except EvalAborted as stop:
        print(stop, file=sys.stderr)
    finally:
        report = write_rows(rows, args.results)
        print(report.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
