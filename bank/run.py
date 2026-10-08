"""Runs a batch of bank chores on the home model through the compose
Mercury (decisions 26, 35 and 36 of docs/build-brief-evals.md). Each chore is
posted quiet (source bank) on local from its base, followed, graded against
its commit's tests, and its pull request and branch closed and deleted. Only
training chores run here; validation chores are run only to choose between
adapters, in 5d.

  python -m bank.run --count 10 [--library <name>]
reads MERCURY_URL (the compose Mercury, http://localhost:8001),
MERCURY_BEARER_TOKEN and MERCURY_GITHUB_TOKEN, and writes
bank/results/<stamp>.json and its summary. local/queue-bank.ps1 wraps it.
"""

import argparse
import os
import sys
import time
from functools import partial
from pathlib import Path

import httpx2

from bank.chores import HERE, TRAINING, BankChore, load_bank, load_libraries
from bank.grade import ensure_mirror, grade_branch
from evals.runner import (
    RESCUABLE,
    EvalAborted,
    EvalRow,
    contained,
    load_rows,
    run_one,
    write_results,
)

RESULTS = HERE / "results"
PROVIDER = "local"


def tried(results: Path = RESULTS) -> set[str]:
    """Chores with a row that holds the model's answer. A row that ended in
    error, timeout or refused says nothing about the model, so it does not
    count and the chore is queued again."""
    return {
        row.task
        for path in sorted(results.glob("*.json"))
        for row in load_rows(path)
        if row.status in RESCUABLE
    }


def pending(
    chores: list[BankChore], results: Path = RESULTS, library: str | None = None
) -> list[BankChore]:
    done = tried(results)
    return sorted(
        (
            chore
            for chore in chores
            if chore.split == TRAINING
            and chore.id not in done
            and (library is None or chore.library == library)
        ),
        key=lambda chore: chore.id,
    )


def print_row(row: EvalRow) -> None:
    print(
        f"{row.task} {row.status} graded={'pass' if row.graded else 'fail'} "
        f"tokens={row.tokens} unusable={row.unusable}",
        flush=True,
    )


def run_batch(
    api, github, chores, grades, count, clone_base, token, *, timeout_seconds,
    poll_seconds=5.0, sleep=time.sleep, clock=time.monotonic, on_row=print_row, rows=None,
) -> list[EvalRow]:  # fmt: skip
    """Rows go into rows as they finish, so a caller that passes a list keeps
    them when an EvalAborted (the daily cap) stops the batch part way."""
    rows = [] if rows is None else rows
    for chore in chores[:count]:
        row = contained(
            partial(
                run_one, api, github, chore, PROVIDER, clone_base, token,
                timeout_seconds=timeout_seconds, poll_seconds=poll_seconds, sleep=sleep,
                clock=clock, source="bank", base=chore.base, grade=grades[chore.id],
            ),
            chore.id, PROVIDER, token,
        )  # fmt: skip
        rows.append(row)
        on_row(row)
    return rows


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives the compose Mercury
    parser = argparse.ArgumentParser(description="Run a batch of bank chores on local.")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--library", default=None)
    parser.add_argument("--only", default=None, help="one chore id, run even if it has a row")
    parser.add_argument("--out", type=Path, default=RESULTS)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)

    chores = load_bank()
    if args.only:
        chores = [chore for chore in chores if chore.id == args.only]
    else:
        chores = pending(chores, RESULTS, args.library)
    libraries = load_libraries()
    token = os.environ["MERCURY_GITHUB_TOKEN"]
    clone_base = "https://github.com"
    mirrors = {name: ensure_mirror(lib, clone_base, token) for name, lib in libraries.items()}
    grades = {
        chore.id: partial(
            grade_branch, chore, libraries[chore.library], mirrors[chore.library],
            clone_base, token,
        )
        for chore in chores
    }  # fmt: skip
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
    rows: list[EvalRow] = []
    try:
        run_batch(
            api, github, chores, grades, args.count, clone_base, token,
            timeout_seconds=args.timeout, rows=rows,
        )  # fmt: skip
    except EvalAborted as stop:
        print(stop, file=sys.stderr)
    finally:
        if rows:
            report = write_results(rows, args.out)
            print(report.read_text(encoding="utf-8"))
            print(f"written to {report}")
    return 0 if rows else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
