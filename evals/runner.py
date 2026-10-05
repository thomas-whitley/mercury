"""Runs Mercury's chore evals and grades each result with a test the model
never saw.

A task is one YAML file under evals/chores/: the repo, an instruction that
names every file and function it expects, and a grade test. Each task runs
once per column per repeat. A Mercury column queues it as a repo_chore
through POST /runs, and a chore that opens a pull request is graded on its
branch, which is then closed and deleted so the fixture keeps only main.
The delegate column (Task 5) runs delegate.ps1 on a local clone instead.

A result passes when it still has every test id main has, its own tests
pass, and the grade test passes.

uv run python -m evals.runner --columns gemini,ollama --repeats 1
reads MERCURY_URL, MERCURY_BEARER_TOKEN and MERCURY_GITHUB_TOKEN.
"""

import argparse
import base64
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import yaml

from app.config import PROVIDERS

OPEN = {"pending", "running", "awaiting_approval"}
GRADE_MODULE = "grade_hidden"
HERE = Path(__file__).parent
FIXTURE_URL = "https://github.com/thomas-whitley/mercury-fixture.git"
# The fixture's own tests, as its test_command in mercury.yaml runs them.
REPO_TESTS = [sys.executable, "-m", "unittest", "discover", "-v"]
# unittest's exit status when it finds no tests, which a repo with none returns.
NO_TESTS_RAN = 5
# Prints every test id unittest discovers, one per line, without running any.
LIST_TESTS = (
    "import unittest\n"
    "def walk(suite):\n"
    "    for t in suite:\n"
    "        walk(t) if isinstance(t, unittest.TestSuite) else print(t.id())\n"
    "walk(unittest.defaultTestLoader.discover('.'))\n"
)
_TEXT = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


class EvalAborted(Exception):
    """The batch cannot go on, for example because chores wait for Approve."""


@dataclass(frozen=True)
class EvalTask:
    id: str
    repo: str
    instruction: str
    grade: str


@dataclass
class EvalRow:
    task: str
    provider: str  # the column asked for: a provider, or delegate:<model>
    answered_by: str | None  # runs.provider at the end, after any fallback
    run_id: str | None
    status: str  # succeeded, failed, timeout, refused, or another final run status
    graded: bool  # kept main's tests, passed its own, and passed the hidden test
    tokens: int | None  # None where the column cannot count them
    seconds: float | None
    usd: float
    detail: str = ""


def load_tasks(directory: Path) -> list[EvalTask]:
    tasks = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks.append(
            EvalTask(
                id=path.stem,
                repo=data["repo"],
                instruction=data["instruction"].strip(),
                grade=data["grade"],
            )
        )
    return tasks


def _env(home: str, token: str | None) -> dict[str, str]:
    """No secret but the token, and that only as git's own header."""
    env = {
        "PATH": os.environ["PATH"],
        "HOME": home,
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONUTF8": "1",
    }
    if "SYSTEMROOT" in os.environ:  # Windows cannot start a process without it
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
    return env


def clone(
    clone_url: str, branch: str | None, dest: Path, token: str | None, timeout_seconds: float
) -> str | None:
    """None when the branch (or the default branch) is cloned into dest, else
    why not. Raises subprocess.TimeoutExpired, which callers turn into a row."""
    pick = ["--branch", branch] if branch else []
    result = subprocess.run(
        ["git", "clone", "-q", "--depth", "1", *pick, clone_url, str(dest)],
        env=_env(str(dest.parent), token),
        timeout=timeout_seconds,
        **_TEXT,
    )
    return None if result.returncode == 0 else "clone failed: " + result.stderr[-1000:]


def test_ids(work: Path, timeout_seconds: float = 120) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", LIST_TESTS],
        cwd=work,
        env=_env(str(work.parent), None),
        timeout=timeout_seconds,
        **_TEXT,
    )
    return set(result.stdout.split())


test_ids.__test__ = False  # a helper, not a test, for pytest's collector


def grade_dir(
    work: Path,
    grade_source: str,
    base_ids: set[str] | None = None,
    timeout_seconds: float = 120,
) -> tuple[bool, str]:
    """Grade a checkout. With base_ids, every one of main's test ids must
    still be there. Then its own tests must pass, then the grade test. Never
    raises for a bad checkout or a bad grade; the answer is the boolean."""
    env = _env(str(work.parent), None)
    try:
        if base_ids is not None:
            lost = base_ids - test_ids(work, timeout_seconds)
            if lost:
                return False, "tests removed: " + ", ".join(sorted(lost))
        own = subprocess.run(REPO_TESTS, cwd=work, env=env, timeout=timeout_seconds, **_TEXT)
        if own.returncode not in (0, NO_TESTS_RAN):
            return False, "own tests failed: " + (own.stdout + own.stderr)[-3000:]
        (work / f"{GRADE_MODULE}.py").write_text(grade_source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", GRADE_MODULE],
            cwd=work,
            env=env,
            timeout=timeout_seconds,
            **_TEXT,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_seconds:.0f} s"
    return result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def grade_branch(
    clone_url: str,
    branch: str,
    grade_source: str,
    token: str | None = None,
    timeout_seconds: float = 120,
) -> tuple[bool, str]:
    """Clone the branch and the default branch, and grade the branch against
    the default branch's test ids."""
    with tempfile.TemporaryDirectory() as home:
        work, base = Path(home) / "work", Path(home) / "base"
        try:
            error = clone(clone_url, branch, work, token, timeout_seconds) or clone(
                clone_url, None, base, token, timeout_seconds
            )
            if error:
                return False, error
            base_ids = test_ids(base, timeout_seconds)
        except subprocess.TimeoutExpired:
            return False, f"clone timed out after {timeout_seconds:.0f} s"
        return grade_dir(work, grade_source, base_ids, timeout_seconds)


def close_pull_and_branch(github, repo: str, branch: str) -> None:
    owner = repo.split("/")[0]
    pulls = github.get(
        f"/repos/{repo}/pulls", params={"head": f"{owner}:{branch}", "state": "open"}
    )
    for pull in pulls.json():
        github.patch(f"/repos/{repo}/pulls/{pull['number']}", json={"state": "closed"})
    github.delete(f"/repos/{repo}/git/refs/heads/{branch}")


DELEGATE_SCRIPT = Path(r"C:\Projects\Cheap AI\scripts\delegate.ps1")


def _call_delegate_script(work: Path, instruction: str, model: str, timeout_seconds: float):
    """delegate.ps1 needs the desktop's own environment (OpenCode, Ollama), so
    it gets it whole. It edits the clean checkout and does not commit."""
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(DELEGATE_SCRIPT),
            "-Dir",
            str(work),
            "-Task",
            instruction,
            "-Model",
            model,
        ],
        timeout=timeout_seconds,
        check=False,
        **_TEXT,
    )


def run_delegate(
    task: EvalTask,
    model: str,
    clone_url: str,
    *,
    delegate: Callable[[Path, str, str, float], None] | None = None,
    timeout_seconds: float = 1800,
    clock: Callable[[], float] = time.monotonic,
) -> EvalRow:
    column = f"delegate:{model}"
    delegate = delegate or _call_delegate_script

    def row(status: str, graded: bool, seconds: float | None, detail: str) -> EvalRow:
        return EvalRow(
            task.id, column, column, None, status, graded, None, seconds, 0.0, detail[-2000:]
        )

    with tempfile.TemporaryDirectory() as home:
        work = Path(home) / "work"
        error = clone(clone_url, "main", work, None, 120)
        if error:
            return row("refused", False, None, error)
        base_ids = test_ids(work)
        start = clock()
        try:
            delegate(work, task.instruction, model, timeout_seconds)
        except subprocess.TimeoutExpired:
            return row("timeout", False, clock() - start, "delegate.ps1 timed out")
        seconds = clock() - start
        # Mercury opens a pull request only when the repo's own tests pass.
        tests = subprocess.run(REPO_TESTS, cwd=work, env=_env(home, None), timeout=600, **_TEXT)
        if tests.returncode not in (0, NO_TESTS_RAN):
            return row("failed", False, seconds, tests.stdout + tests.stderr)
        graded, detail = grade_dir(work, task.grade, base_ids)
        return row("succeeded", graded, seconds, detail)


def run_one(
    api,
    github,
    task: EvalTask,
    provider: str,
    clone_base: str,
    token: str | None,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> EvalRow:
    created = api.post(
        "/runs",
        json={
            "type": "repo_chore",
            "inputs": {"task": task.instruction, "repo": task.repo},
            "provider": provider,
        },
    )
    if created.status_code != 201:
        return EvalRow(
            task.id, provider, None, None, "refused", False, 0, None, 0.0, created.text[:300]
        )
    run = created.json()
    if run["status"] == "awaiting_approval":
        raise EvalAborted(
            f"run {run['id']} is waiting for Approve: {task.repo} is not auto_approve in the "
            "live mercury.yaml. Decline it on Telegram, set auto_approve, and run again."
        )
    run_id = run["id"]
    deadline = clock() + timeout_seconds
    while True:
        response = api.get(f"/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] not in OPEN:
            break
        if clock() >= deadline:
            run = {**run, "status": "timeout"}
            break
        sleep(poll_seconds)

    if run["status"] == "refused":
        # The worker closes a run it will not execute as refused. Past the daily
        # run limit it refuses every model run, so going on would record fails
        # that measure the limit and not the model.
        raise EvalAborted(
            f"run {run_id} was refused by the worker, most likely because the daily run limit "
            "MAX_RUNS_PER_DAY (default 20) is reached. Raise it in mercury-config for the "
            "day of the eval, or continue tomorrow. Its events give the exact reason."
        )
    graded, detail = False, ""
    if run["status"] == "succeeded":
        branch = f"agent/{run_id}"
        graded, detail = grade_branch(f"{clone_base}/{task.repo}.git", branch, task.grade, token)
        close_pull_and_branch(github, task.repo, branch)
    tokens = run.get("tokens") or 0
    answered = run.get("provider")
    rate = PROVIDERS[answered].usd_per_million_tokens if answered in PROVIDERS else 0.0
    return EvalRow(
        task.id,
        provider,
        answered,
        run_id,
        run["status"],
        graded,
        tokens,
        run.get("duration_seconds"),
        tokens * rate / 1_000_000,
        detail[-2000:],
    )


def summarise(rows: list[EvalRow]) -> str:
    lines = [
        "| Column | Passed the hidden test | Opened a PR | Median tokens | Median seconds "
        "| Cost USD |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for column in sorted({row.provider for row in rows}):
        mine = [row for row in rows if row.provider == column]
        tokens = [row.tokens for row in mine if row.tokens is not None]
        seconds = [row.seconds for row in mine if row.seconds is not None]
        lines.append(
            f"| {column} | {sum(r.graded for r in mine)} of {len(mine)} "
            f"| {sum(r.status == 'succeeded' for r in mine)} of {len(mine)} "
            f"| {f'{statistics.median(tokens):.0f}' if tokens else 'n/a'} "
            f"| {f'{statistics.median(seconds):.0f}' if seconds else 'n/a'} "
            f"| {sum(r.usd for r in mine):.4f} |"
        )
    lines += ["", "| Task | Column | Status | Graded |", "| --- | --- | --- | --- |"]
    for row in sorted(rows, key=lambda r: (r.task, r.provider)):
        verdict = "pass" if row.graded else "fail"
        lines.append(f"| {row.task} | {row.provider} | {row.status} | {verdict} |")
    return "\n".join(lines)


def write_results(rows: list[EvalRow], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    (out / f"{stamp}.json").write_text(
        json.dumps([asdict(r) for r in rows], indent=2) + "\n", encoding="utf-8"
    )
    report = out / f"{stamp}.md"
    report.write_text(summarise(rows) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives the live deploy
    parser = argparse.ArgumentParser(description="Run the chore evals.")
    parser.add_argument(
        "--columns", default="gemini,ollama", help="providers, and delegate:<model> (Task 5)"
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--only", default="", help="comma separated task ids")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)

    columns = [c for c in args.columns.split(",") if c]
    unknown = [c for c in columns if c not in PROVIDERS and not c.startswith("delegate:")]
    if unknown:
        parser.error(f"unknown column {unknown[0]}; providers: {', '.join(PROVIDERS)}")
    tasks = load_tasks(HERE / "chores")
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t.id in wanted]

    api = github = token = None
    if any(not c.startswith("delegate:") for c in columns):
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
    rows: list[EvalRow] = []
    try:
        for _ in range(args.repeats):
            for task in tasks:
                for column in columns:
                    row = _run_column(column, task, api, github, token, args.timeout)
                    rows.append(row)
                    print(
                        f"{task.id} {column}->{row.answered_by} {row.status} "
                        f"graded={'pass' if row.graded else 'fail'} tokens={row.tokens}",
                        flush=True,
                    )
    except EvalAborted as stop:
        print(stop, file=sys.stderr)
    finally:
        if rows:
            report = write_results(rows, HERE / "results")
            print(report.read_text(encoding="utf-8"))
            print(f"written to {report}")
    return 0 if rows else 1


def _run_column(column, task, api, github, token, timeout) -> EvalRow:  # pragma: no cover
    if column.startswith("delegate:"):
        return run_delegate(task, column.split(":", 1)[1], FIXTURE_URL)
    return run_one(
        api,
        github,
        task,
        column,
        "https://github.com",
        token,
        timeout_seconds=timeout,
        poll_seconds=5.0,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
