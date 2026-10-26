"""Scores saved chore diffs with a local System One decision model (Ollama's
POST /v1/systemone) and compares its answer with the eval's own grade.

A row is flagged when the model gives "yes, it does what was asked" less
than half its probability. The bar for using one on Mercury's note messages
(docs/model-search.md in Cheap AI): it flags at least 3 in 4 failed rows and
under 1 in 5 passed ones.

uv run python -m evals.decider --model clef-flash evals/results/<file>.json [...]
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx2

from evals.runner import HERE, EvalRow, EvalTask, load_rows, load_tasks

FLAG_BELOW = 0.5
CATCH_AT_LEAST = 0.75
FALSE_FLAGS_UNDER = 0.20
QUESTION = {
    "type": "choice",
    "instructions": "Does the diff do what the instruction asked, fully and nothing else?",
    "criteria": {
        "yes": "Does all of it",
        "partly": "Does some of it or adds unrelated changes",
        "no": "Does not do it",
    },
}


@dataclass(frozen=True)
class Scored:
    task: str
    column: str
    graded: bool
    match: float | None  # the probability of "yes"; None when unscored


def request_body(model: str, state: str) -> dict:
    return {"model": model, "state": state, "questions": {"match": QUESTION}}


def _yes(reply: object) -> float | None:
    try:
        return float(reply["answers"]["match"]["probabilities"]["yes"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return None


def score_rows(
    rows: list[EvalRow], tasks: dict[str, EvalTask], ask: Callable[[str], object]
) -> list[Scored]:
    """A row with no diff is not sent. Its diff was cut at the runner's
    EVIDENCE_DIFF_CHARS, which keeps the state under the 64 KiB local limit."""
    scored = []
    for row in rows:
        match = None
        if row.diff:
            state = f"Instruction:\n{tasks[row.task].instruction}\n\nDiff:\n{row.diff}"
            match = _yes(ask(state))
        scored.append(Scored(row.task, row.provider, row.graded, match))
    return scored


def _rate(hits: int, of: int) -> str:
    return f"{hits / of:.0%}" if of else "n/a"


def summary(scored: list[Scored]) -> str:
    done = [s for s in scored if s.match is not None]
    fails = [s for s in done if not s.graded]
    passes = [s for s in done if s.graded]
    caught = sum(s.match < FLAG_BELOW for s in fails)
    flagged = sum(s.match < FLAG_BELOW for s in passes)
    catch, false = _rate(caught, len(fails)), _rate(flagged, len(passes))
    meets = (
        bool(fails)
        and bool(passes)
        and caught / len(fails) >= CATCH_AT_LEAST
        and flagged / len(passes) < FALSE_FLAGS_UNDER
    )
    verdict = "meets the bar" if meets else "does not meet the bar"
    return (
        f"scored {len(done)} of {len(scored)}; "
        f"catch {catch} ({caught} of {len(fails)} fails), "
        f"false flags {false} ({flagged} of {len(passes)} passes); "
        f"{verdict} (catch {catch}, false flags {false})"
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - calls Ollama
    parser = argparse.ArgumentParser(description="Score chore diffs with a decision model.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--url", default="http://localhost:11434")
    parser.add_argument("--tasks-dir", type=Path, default=HERE / "chores")
    parser.add_argument("results", nargs="+", type=Path)
    args = parser.parse_args(argv)

    tasks = {task.id: task for task in load_tasks(args.tasks_dir)}
    rows = [row for path in args.results for row in load_rows(path) if row.task in tasks]
    client = httpx2.Client(base_url=args.url.rstrip("/"), timeout=600)

    def ask(state: str) -> object:
        response = client.post("/v1/systemone", json=request_body(args.model, state))
        return response.json()

    scored = score_rows(rows, tasks, ask)
    for s in scored:
        print(f"{s.task} {s.column} graded={'pass' if s.graded else 'fail'} match={s.match}")
    print(summary(scored))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
